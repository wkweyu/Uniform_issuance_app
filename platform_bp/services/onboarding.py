from datetime import UTC, datetime, timedelta
import os
import re
import smtplib
from email.message import EmailMessage

from blueprints.auth.utils import hash_password
from ..config.modules import bundle_family_options as configured_bundle_family_options
from .audit import log as audit_log
from .notifications import _open_smtp_client, _smtp_use_ssl
from .subscriptions import resolve_plan_for_commercial_selection, resolve_subscription_pricing


DEFAULT_TRIAL_DAYS = 14
DEFAULT_PLAN_NAMES = ('trial', 'starter', 'basic')


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


def _send_welcome_email(to_email, school_name, smtp_config=None):
    """Send a simple welcome email using SMTP. smtp_config can be omitted to use env vars.

    This function intentionally swallows exceptions so onboarding won't fail due to email.
    """
    try:
        smtp_host = smtp_config.get('host') if smtp_config else os.environ.get('SMTP_HOST')
        smtp_port = smtp_config.get('port') if smtp_config else int(os.environ.get('SMTP_PORT', '25'))
        smtp_user = smtp_config.get('user') if smtp_config else os.environ.get('SMTP_USER')
        smtp_pass = smtp_config.get('pass') if smtp_config else os.environ.get('SMTP_PASS')

        if not smtp_host:
            return False

        msg = EmailMessage()
        msg['Subject'] = f"Welcome to SkoolTrack Pro, {school_name}"
        msg['From'] = smtp_user or f"no-reply@{smtp_host}"
        msg['To'] = to_email
        msg.set_content(f"Your school {school_name} has been onboarded to SkoolTrack Pro.\n\nLogin and complete setup.")

        s = _open_smtp_client(smtp_host, smtp_port, timeout=10)
        s.ehlo()
        if smtp_user and smtp_pass:
            if not _smtp_use_ssl(smtp_port):
                s.starttls()
                s.ehlo()
            s.login(smtp_user, smtp_pass)
        s.send_message(msg)
        s.quit()
        return True
    except Exception:
        return False


def _normalize_school_code(code):
    normalized = re.sub(r'[^A-Za-z0-9]+', '', (code or '').strip().upper())
    return normalized


def _normalize_username(username):
    return (username or '').strip()


def _resolve_default_plan(default_plan_name=None, default_plan_id=None, bundle_family=None, billing_period=None):
    from platform_bp.models import Plan

    commercial_plan = resolve_plan_for_commercial_selection(
        bundle_family=bundle_family,
        billing_period=billing_period,
        plan_id=default_plan_id,
    )
    if commercial_plan is not None:
        return commercial_plan

    if default_plan_name:
        return Plan.query.filter_by(name=default_plan_name.strip()).first()

    plans = Plan.query.all()
    if not plans:
        return None

    named_defaults = {name: None for name in DEFAULT_PLAN_NAMES}
    for plan in plans:
        plan_name = (plan.name or '').strip().lower()
        if plan_name in named_defaults and named_defaults[plan_name] is None:
            named_defaults[plan_name] = plan

    for name in DEFAULT_PLAN_NAMES:
        if named_defaults[name] is not None:
            return named_defaults[name]

    return min(
        plans,
        key=lambda plan: (
            plan.price_cents if plan.price_cents is not None else 10**12,
            plan.created_at or datetime.max,
            plan.id or 10**12,
        ),
    )


def _build_subscription(plan, explicit_selection=False, status=None):
    subscription_status = (status or '').strip().lower() if status else None
    if subscription_status not in {'trial', 'active', 'grace_period', 'suspended', 'cancelled'}:
        subscription_status = 'active' if explicit_selection and (plan.price_cents or 0) > 0 else 'trial'

    trial_ends_at = None
    if subscription_status == 'trial':
        trial_ends_at = utc_now() + timedelta(days=DEFAULT_TRIAL_DAYS)

    return subscription_status, trial_ends_at


def onboard_school(
    name,
    code,
    timezone='UTC',
    default_plan_name=None,
    created_by=None,
    welcome_email=None,
    default_plan_id=None,
    admin_user=None,
    subscription_status=None,
    school_contact=None,
    student_count=None,
    student_band_id=None,
    bundle_family=None,
    billing_period=None,
):
    """Create school record, assign default plan/subscription if provided.

    Validation:
      - name and code required
      - code must be unique

    Returns (school, subscription) tuple. Uses DB transaction.
    """
    if not name or not name.strip():
        raise ValueError('School name is required')
    if not code or not code.strip():
        raise ValueError('School code is required')

    normalized_code = _normalize_school_code(code)
    if not normalized_code:
        raise ValueError('School code must contain letters or numbers')

    admin_payload = admin_user or {}
    admin_username = _normalize_username(admin_payload.get('username'))
    admin_password = admin_payload.get('password')
    if admin_username and not admin_password:
        raise ValueError('Admin password is required when admin username is provided')
    if admin_password and not admin_username:
        raise ValueError('Admin username is required when admin password is provided')

    # Import models/db lazily to avoid circular imports during package init
    from app import db, School, SchoolSettings, User
    from platform_bp.models import Plan, Subscription

    existing = School.query.filter_by(code=normalized_code).first()
    if existing:
        raise ValueError('School code already exists')

    contact = school_contact or {}
    default_plan = _resolve_default_plan(
        default_plan_name=default_plan_name,
        default_plan_id=default_plan_id,
        bundle_family=bundle_family,
        billing_period=billing_period,
    )
    explicit_plan_selected = bool(default_plan_name or default_plan_id or bundle_family or billing_period)

    valid_bundle_families = {code for code, _ in configured_bundle_family_options()}
    normalized_bundle_family = (bundle_family or '').strip() or None
    normalized_billing_period = (billing_period or '').strip() or None
    if normalized_bundle_family and normalized_bundle_family not in valid_bundle_families:
        raise ValueError('Selected bundle family is not supported')
    if (normalized_bundle_family or normalized_billing_period) and default_plan is None:
        raise ValueError('No commercial plan matches the selected bundle family and billing period')

    with db.session.begin_nested():
        school = School(
            name=name.strip(),
            code=normalized_code,
            email=(contact.get('email') or welcome_email or '').strip() or None,
            phone=(contact.get('phone') or '').strip() or None,
            address=(contact.get('address') or '').strip() or None,
            city=(contact.get('city') or '').strip() or None,
            country=(contact.get('country') or '').strip() or None,
        )
        db.session.add(school)
        db.session.flush()  # get school.id
        db.session.add(
            SchoolSettings(
                school_id=school.id,
                school_name=school.name,
                timezone=timezone or 'UTC',
                email=school.email,
                phone=school.phone,
                address=school.address,
            )
        )

        subscription = None
        if default_plan:
            resolved_status, trial_ends_at = _build_subscription(
                default_plan,
                explicit_selection=explicit_plan_selected,
                status=subscription_status,
            )
            amount_cents, billing_meta = resolve_subscription_pricing(
                default_plan,
                school_id=school.id,
                student_count=student_count,
                student_band_id=student_band_id,
            )
            subscription = Subscription(
                school_id=school.id,
                plan_id=default_plan.id,
                status=resolved_status,
                started_at=utc_now(),
                billing_cycle=default_plan.billing_period,
                amount_cents=amount_cents,
                trial_ends_at=trial_ends_at,
                billing_meta=billing_meta,
            )
            db.session.add(subscription)
            school.subscription_plan = default_plan.name
            school.subscription_status = resolved_status
            school.subscription_start = utc_now().date()
            school.subscription_end = trial_ends_at.date() if trial_ends_at else None

        admin_account = None
        if admin_username and admin_password:
            admin_account = User(
                username=admin_username,
                pwd=hash_password(admin_password),
                StaffID=(admin_payload.get('staff_id') or '').strip() or None,
                access_flag=1,
                TA=1,
                dateReg=utc_now().strftime('%Y-%m-%d %H:%M:%S'),
                _date=utc_now(),
                school_id=school.id,
            )
            db.session.add(admin_account)

    db.session.commit()

    audit_log(
        action='school_onboarded',
        target_table='schools',
        target_id=school.id,
        school_id=school.id,
        changes={
            'school_name': school.name,
            'school_code': school.code,
            'timezone': timezone or 'UTC',
        },
    )

    if subscription is not None:
        audit_log(
            action='subscription_provisioned',
            target_table='subscriptions',
            target_id=subscription.id,
            school_id=school.id,
            changes={
                'plan_id': subscription.plan_id,
                'status': subscription.status,
                'billing_cycle': subscription.billing_cycle,
                'amount_cents': subscription.amount_cents,
                'bundle_family': default_plan.bundle_family if default_plan else None,
                'student_count': (subscription.billing_meta or {}).get('student_count'),
                'student_band_label': (subscription.billing_meta or {}).get('student_band_label'),
            },
        )

    if admin_account is not None:
        audit_log(
            action='tenant_admin_created',
            target_table='users',
            target_id=admin_account.userNo,
            school_id=school.id,
            changes={
                'username': admin_account.username,
                'staff_id': admin_account.StaffID,
                'is_admin': True,
            },
        )

    # send welcome email (best-effort)
    if welcome_email:
        _send_welcome_email(welcome_email, school.name)

    return school, subscription, admin_account


def get_onboarding_status(school_id):
    from app import db, School
    from models import User
    from platform_bp.models import Plan
    from .subscriptions import get_subscription_by_school
    school = db.session.get(School, school_id)
    if not school:
        return None
    sub = get_subscription_by_school(school_id)
    admin_user = User.query.filter_by(school_id=school_id, TA=1).order_by(User.userNo.asc()).first()
    return {
        'school': {'id': school.id, 'name': school.name, 'code': school.code},
        'subscription': {
            'id': sub.id,
            'plan_id': sub.plan_id,
            'status': sub.status,
            'billing_cycle': sub.billing_cycle,
            'amount_cents': sub.amount_cents,
            'bundle_family': (db.session.get(Plan, sub.plan_id).bundle_family if sub and sub.plan_id else None),
            'student_count': (sub.billing_meta or {}).get('student_count'),
            'student_band_label': (sub.billing_meta or {}).get('student_band_label'),
        } if sub else None,
        'admin_user': {
            'userNo': admin_user.userNo,
            'username': admin_user.username,
            'staff_id': admin_user.StaffID,
        } if admin_user else None,
    }
