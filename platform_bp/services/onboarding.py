from datetime import datetime
import os
import smtplib
from email.message import EmailMessage


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

        s = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
        s.ehlo()
        if smtp_user and smtp_pass:
            s.starttls()
            s.login(smtp_user, smtp_pass)
        s.send_message(msg)
        s.quit()
        return True
    except Exception:
        return False


def onboard_school(name, code, timezone='UTC', default_plan_name=None, created_by=None, welcome_email=None):
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

    # Import models/db lazily to avoid circular imports during package init
    from app import db, School
    from platform_bp.models import Plan, Subscription

    existing = School.query.filter_by(code=code).first()
    if existing:
        raise ValueError('School code already exists')

    with db.session.begin_nested():
        school = School(name=name.strip(), code=code.strip())
        db.session.add(school)
        db.session.flush()  # get school.id

        subscription = None
        if default_plan_name:
            plan = Plan.query.filter_by(name=default_plan_name).first()
            if plan:
                subscription = Subscription(school_id=school.id, plan_id=plan.id, status='active', started_at=datetime.utcnow())
                db.session.add(subscription)

    db.session.commit()

    # send welcome email (best-effort)
    if welcome_email:
        _send_welcome_email(welcome_email, school.name)

    return school, subscription


def get_onboarding_status(school_id):
    from app import School
    from platform_bp.models import Subscription
    school = School.query.get(school_id)
    if not school:
        return None
    sub = Subscription.query.filter_by(school_id=school_id).first()
    return {
        'school': {'id': school.id, 'name': school.name, 'code': school.code},
        'subscription': {'id': sub.id, 'plan_id': sub.plan_id, 'status': sub.status} if sub else None
    }
