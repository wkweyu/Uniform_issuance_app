import logging
from extensions import db
from ..config.modules import entitlement_filter_options as registry_entitlement_filter_options
from ..config.modules import family_color, family_label, module_definition, module_group_label, module_label
from platform_bp.models import ModuleCatalog, Plan, PlanBandPrice, PlanModule, StudentBand, Subscription
from datetime import UTC, datetime
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .audit import log as audit_log


logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


ACTIVE_ACCESS_STATES = {'trial', 'active', 'grace_period'}
WRITE_ACCESS_STATES = {'trial', 'active'}

SUSPENSION_REASON_OPTIONS = (
    ('billing_delinquency', 'Billing delinquency'),
    ('chargeback_risk', 'Chargeback or payment risk'),
    ('compliance_hold', 'Compliance review hold'),
    ('manual_admin_hold', 'Manual admin hold'),
)

CANCELLATION_REASON_OPTIONS = (
    ('tenant_offboarded', 'Tenant offboarded'),
    ('contract_terminated', 'Contract terminated'),
    ('duplicate_account', 'Duplicate account cleanup'),
    ('migration_cleanup', 'Migration cleanup'),
)

ENFORCEMENT_REASON_LABELS = {
    **dict(SUSPENSION_REASON_OPTIONS),
    **dict(CANCELLATION_REASON_OPTIONS),
}

BILLING_PERIOD_LABELS = {
    'monthly': 'Monthly',
    'quarterly': 'Quarterly',
    'semiannual': 'Semi-Annual',
    'annual': 'Annual',
}

ENTITLEMENT_STATE_FILTER_OPTIONS = (
    ('configured', 'Configured Entitlement'),
    ('unconfigured', 'Unconfigured Entitlement'),
    ('read_write', 'Read / Write Access'),
    ('read_only', 'Read Only Access'),
    ('disabled', 'Access Disabled'),
)


def get_enforcement_reason_options():
    return {
        'suspension': SUSPENSION_REASON_OPTIONS,
        'cancellation': CANCELLATION_REASON_OPTIONS,
    }


def get_reason_label(reason_code):
    if not reason_code:
        return None
    return ENFORCEMENT_REASON_LABELS.get(reason_code, reason_code.replace('_', ' ').title())


def get_subscription_reason_context(subscription):
    billing_meta = dict(subscription.billing_meta or {})
    if billing_meta.get('suspension_reason_code'):
        return {
            'type': 'suspension',
            'code': billing_meta.get('suspension_reason_code'),
            'label': get_reason_label(billing_meta.get('suspension_reason_code')),
            'text': billing_meta.get('suspension_reason'),
        }
    if billing_meta.get('cancellation_reason_code'):
        return {
            'type': 'cancellation',
            'code': billing_meta.get('cancellation_reason_code'),
            'label': get_reason_label(billing_meta.get('cancellation_reason_code')),
            'text': billing_meta.get('cancellation_reason'),
        }
    return {'type': None, 'code': None, 'label': None, 'text': None}


def _sync_school_snapshot(subscription, plan=None):
    from models import School

    school = db.session.get(School, subscription.school_id)
    if school is None:
        return

    resolved_plan = plan or db.session.get(Plan, subscription.plan_id)
    school.subscription_status = subscription.effective_status or subscription.status or school.subscription_status
    school.subscription_plan = resolved_plan.name if resolved_plan else school.subscription_plan
    if subscription.ended_at is not None:
        school.subscription_end = subscription.ended_at.date()


def _merged_billing_meta(subscription, **updates):
    billing_meta = dict(subscription.billing_meta or {})
    for key, value in updates.items():
        if value is None:
            billing_meta.pop(key, None)
        else:
            billing_meta[key] = value
    return billing_meta


def _clear_enforcement_reasons(subscription):
    return _merged_billing_meta(
        subscription,
        suspension_reason=None,
        suspension_reason_code=None,
        suspension_recorded_at=None,
        cancellation_reason=None,
        cancellation_reason_code=None,
        cancellation_recorded_at=None,
    )


def get_billing_period_options():
    periods = [
        row[0]
        for row in (
            db.session.query(Plan.billing_period)
            .filter(Plan.billing_period.isnot(None))
            .distinct()
            .order_by(Plan.billing_period.asc())
            .all()
        )
        if row[0]
    ]
    if not periods:
        periods = ['monthly', 'quarterly', 'annual']
    return [(period, BILLING_PERIOD_LABELS.get(period, period.replace('_', ' ').title())) for period in periods]


def resolve_plan_for_commercial_selection(bundle_family=None, billing_period=None, plan_id=None):
    normalized_bundle_family = (bundle_family or '').strip() or None
    normalized_billing_period = (billing_period or '').strip() or None

    if plan_id:
        return db.session.get(Plan, plan_id)

    if not normalized_bundle_family and not normalized_billing_period:
        return None

    query = Plan.query
    if normalized_bundle_family:
        query = query.filter_by(bundle_family=normalized_bundle_family)
    if normalized_billing_period:
        query = query.filter_by(billing_period=normalized_billing_period)

    return query.order_by(Plan.created_at.desc(), Plan.id.desc()).first()


def refresh_subscription_pricing(subscription, actor_user_id=None, reason='automatic_band_refresh'):
    resolved_subscription = subscription
    if isinstance(subscription, int):
        resolved_subscription = db.session.get(Subscription, subscription)

    if resolved_subscription is None or not resolved_subscription.plan_id:
        return resolved_subscription

    plan = db.session.get(Plan, resolved_subscription.plan_id)
    if plan is None:
        return resolved_subscription

    old_billing_meta = dict(resolved_subscription.billing_meta or {})
    old_amount_cents = resolved_subscription.amount_cents
    old_billing_cycle = resolved_subscription.billing_cycle

    new_amount_cents, new_billing_meta = resolve_subscription_pricing(
        plan,
        school_id=resolved_subscription.school_id,
        current_billing_meta=resolved_subscription.billing_meta,
    )
    new_billing_cycle = plan.billing_period or resolved_subscription.billing_cycle

    if (
        old_amount_cents == new_amount_cents
        and old_billing_cycle == new_billing_cycle
        and old_billing_meta == new_billing_meta
    ):
        return resolved_subscription

    resolved_subscription.amount_cents = new_amount_cents
    resolved_subscription.billing_meta = new_billing_meta
    resolved_subscription.billing_cycle = new_billing_cycle
    _sync_school_snapshot(resolved_subscription, plan=plan)
    db.session.commit()

    pricing_changes = {
        'refresh_reason': reason,
        'plan_id': plan.id,
        'plan_name': plan.name,
        'old_amount_cents': old_amount_cents,
        'new_amount_cents': resolved_subscription.amount_cents,
        'old_billing_cycle': old_billing_cycle,
        'new_billing_cycle': resolved_subscription.billing_cycle,
        'old_student_count': old_billing_meta.get('student_count'),
        'new_student_count': new_billing_meta.get('student_count'),
        'old_student_count_source': old_billing_meta.get('student_count_source'),
        'new_student_count_source': new_billing_meta.get('student_count_source'),
        'old_student_band_label': old_billing_meta.get('student_band_label'),
        'new_student_band_label': new_billing_meta.get('student_band_label'),
    }
    _audit_subscription_event(
        resolved_subscription,
        'subscription_pricing_refreshed',
        pricing_changes,
        actor_user_id=actor_user_id,
    )

    if old_billing_meta.get('student_band_id') != new_billing_meta.get('student_band_id'):
        _audit_subscription_event(
            resolved_subscription,
            'subscription_band_changed',
            {
                'refresh_reason': reason,
                'plan_id': plan.id,
                'plan_name': plan.name,
                'old_student_count': old_billing_meta.get('student_count'),
                'new_student_count': new_billing_meta.get('student_count'),
                'old_student_band_id': old_billing_meta.get('student_band_id'),
                'new_student_band_id': new_billing_meta.get('student_band_id'),
                'old_student_band_label': old_billing_meta.get('student_band_label'),
                'new_student_band_label': new_billing_meta.get('student_band_label'),
            },
            actor_user_id=actor_user_id,
        )

    return resolved_subscription


def get_subscription_by_school(school_id):
    subscription = Subscription.query.filter_by(school_id=school_id).order_by(Subscription.started_at.desc()).first()
    if subscription is None:
        return None
    return refresh_subscription_pricing(subscription, reason='subscription_lookup')


def get_subscription_state_for_school(school_id):
    sub = get_subscription_by_school(school_id)
    return sub.effective_status if sub else None


def school_allows_login(school_id):
    state = get_subscription_state_for_school(school_id)
    return state in ACTIVE_ACCESS_STATES if state else True


def get_plan_entitled_module_codes(plan):
    if plan is None:
        return None

    configured_module_codes = [
        row.code
        for row in (
            db.session.query(ModuleCatalog.code)
            .join(PlanModule, PlanModule.module_id == ModuleCatalog.id)
            .filter(PlanModule.plan_id == plan.id)
            .filter(PlanModule.is_included.is_(True), PlanModule.is_active.is_(True))
            .filter(ModuleCatalog.is_active.is_(True))
            .order_by(ModuleCatalog.sort_order.asc(), ModuleCatalog.code.asc())
            .all()
        )
    ]
    if configured_module_codes:
        return set(configured_module_codes)

    feature_snapshot = plan.features if isinstance(plan.features, dict) else {}
    feature_modules = feature_snapshot.get('modules')
    if feature_modules is None:
        return None
    return {str(code).strip() for code in feature_modules if str(code).strip()}


def list_plan_entitled_modules(plan):
    if plan is None:
        return []

    configured_modules = (
        db.session.query(ModuleCatalog.code, ModuleCatalog.name, ModuleCatalog.family, ModuleCatalog.sort_order)
        .join(PlanModule, PlanModule.module_id == ModuleCatalog.id)
        .filter(PlanModule.plan_id == plan.id)
        .filter(PlanModule.is_included.is_(True), PlanModule.is_active.is_(True))
        .filter(ModuleCatalog.is_active.is_(True))
        .order_by(ModuleCatalog.sort_order.asc(), ModuleCatalog.code.asc())
        .all()
    )
    if configured_modules:
        return [
            {
                'code': row.code,
                'name': row.name,
                'family': row.family,
                'family_label': family_label(row.family),
                'family_color': family_color(row.family),
                'group_label': module_group_label(row.code),
            }
            for row in configured_modules
        ]

    feature_snapshot = plan.features if isinstance(plan.features, dict) else {}
    feature_modules = feature_snapshot.get('modules') or []
    catalog_lookup = {
        row.code: {'name': row.name, 'family': row.family}
        for row in ModuleCatalog.query.filter(ModuleCatalog.code.in_(feature_modules)).all()
    } if feature_modules else {}
    return [
        {
            'code': code,
            'name': catalog_lookup.get(code, {}).get('name', module_label(code)),
            'family': (catalog_lookup.get(code, {}).get('family') or (module_definition(code) or {}).get('family')),
            'family_label': family_label((catalog_lookup.get(code, {}).get('family') or (module_definition(code) or {}).get('family'))),
            'family_color': family_color((catalog_lookup.get(code, {}).get('family') or (module_definition(code) or {}).get('family'))),
            'group_label': module_group_label(code),
        }
        for code in feature_modules
        if str(code).strip()
    ]


def get_entitlement_filter_options():
    return registry_entitlement_filter_options()


def get_entitlement_state_filter_options():
    return ENTITLEMENT_STATE_FILTER_OPTIONS


def build_entitlement_state_counts(summaries):
    counts = {code: 0 for code, _ in ENTITLEMENT_STATE_FILTER_OPTIONS}
    for summary in summaries:
        if summary.get('is_configured'):
            counts['configured'] += 1
        else:
            counts['unconfigured'] += 1

        state_key = summary.get('state_key')
        if state_key in counts and state_key not in {'configured', 'unconfigured'}:
            counts[state_key] += 1
    return counts


def empty_entitlement_summary(status=None):
    return {
        'is_configured': False,
        'configuration_state': 'unconfigured',
        'configuration_label': 'Unconfigured Entitlement',
        'status': status,
        'access_mode': 'unconfigured',
        'state_key': 'unconfigured',
        'state_label': 'Unconfigured Entitlement',
        'read_module_codes': None,
        'write_module_codes': None,
        'modules': [],
    }


def entitlement_summary_matches(summary, included_module_code=None, missing_module_code=None, entitlement_state=None):
    if included_module_code:
        if not summary['is_configured'] or included_module_code not in (summary['read_module_codes'] or set()):
            return False
    if missing_module_code:
        if summary['is_configured'] and missing_module_code in (summary['read_module_codes'] or set()):
            return False
    if entitlement_state:
        if entitlement_state == 'configured' and not summary['is_configured']:
            return False
        elif entitlement_state == 'unconfigured' and summary['is_configured']:
            return False
        elif entitlement_state not in {'configured', 'unconfigured'} and summary.get('state_key') != entitlement_state:
            return False
    return True


def get_subscription_entitled_module_codes(subscription=None, school_id=None):
    resolved_subscription = subscription
    if resolved_subscription is None and school_id is not None:
        resolved_subscription = get_subscription_by_school(school_id)
    if resolved_subscription is None or not resolved_subscription.plan_id:
        return None

    plan = db.session.get(Plan, resolved_subscription.plan_id)
    if plan is None:
        return None
    return get_plan_entitled_module_codes(plan)


def build_subscription_entitlement_summary(subscription=None, school_id=None):
    resolved_subscription = subscription if subscription is not None else get_subscription_by_school(school_id)
    if resolved_subscription is None or not resolved_subscription.plan_id:
        return empty_entitlement_summary(status=None)

    plan = db.session.get(Plan, resolved_subscription.plan_id)
    if plan is None:
        return empty_entitlement_summary(status=resolved_subscription.effective_status)

    plan_modules = list_plan_entitled_modules(plan)
    if not plan_modules:
        return empty_entitlement_summary(status=resolved_subscription.effective_status)

    status = resolved_subscription.effective_status
    read_module_codes = {module['code'] for module in plan_modules} if status in ACTIVE_ACCESS_STATES else set()
    write_module_codes = {module['code'] for module in plan_modules} if status in WRITE_ACCESS_STATES else set()
    access_mode = 'read_write' if status in WRITE_ACCESS_STATES else 'read_only' if status == 'grace_period' else 'disabled'
    state_label = 'Read / Write Access' if access_mode == 'read_write' else 'Read Only Access' if access_mode == 'read_only' else 'Access Disabled'

    modules = []
    for module in plan_modules:
        access_level = 'disabled'
        access_label = 'Disabled'
        if module['code'] in write_module_codes:
            access_level = 'read_write'
            access_label = 'Read / Write'
        elif module['code'] in read_module_codes:
            access_level = 'read_only'
            access_label = 'Read Only'

        modules.append(
            {
                **module,
                'access_level': access_level,
                'access_label': access_label,
            }
        )

    return {
        'is_configured': True,
        'configuration_state': 'configured',
        'configuration_label': 'Configured Entitlement',
        'status': status,
        'access_mode': access_mode,
        'state_key': access_mode,
        'state_label': state_label,
        'read_module_codes': read_module_codes,
        'write_module_codes': write_module_codes,
        'modules': modules,
    }


def _audit_subscription_event(subscription, action, changes, actor_user_id=None):
    audit_log(
        actor_user_id=actor_user_id,
        action=action,
        target_table='subscriptions',
        target_id=subscription.id,
        school_id=subscription.school_id,
        changes=changes,
    )


def update_subscription_mapping_review(subscription_id, review_status, review_notes=None, actor_user_id=None):
    subscription = db.session.get(Subscription, subscription_id)
    if subscription is None:
        raise ValueError('Subscription not found')

    normalized_status = (review_status or '').strip().lower()
    if normalized_status not in {'confirmed', 'review_required'}:
        raise ValueError('Invalid mapping review status')

    existing_meta = dict(subscription.billing_meta or {})
    previous_status = existing_meta.get('mapping_review_status')
    previous_notes = existing_meta.get('mapping_review_notes')

    subscription.billing_meta = _merged_billing_meta(
        subscription,
        mapping_review_status=normalized_status,
        mapping_review_notes=review_notes,
        mapping_review_updated_at=utc_now().isoformat(),
        mapping_review_actor_user_id=actor_user_id,
    )
    db.session.commit()

    _audit_subscription_event(
        subscription,
        'subscription_mapping_review_updated',
        {
            'old_mapping_review_status': previous_status,
            'new_mapping_review_status': normalized_status,
            'old_mapping_review_notes': previous_notes,
            'new_mapping_review_notes': review_notes,
        },
        actor_user_id=actor_user_id,
    )
    return subscription


ACTIVE_STUDENT_COUNT_SQL = text(
    """
    SELECT COUNT(DISTINCT s.AdmNo) AS count
    FROM studentinfo s
    WHERE s.school_id = :school_id
      AND COALESCE(s.blocked, 'NO') = 'NO'
      AND (
          EXISTS (
              SELECT 1
              FROM class_allocation ca
              WHERE ca.student_id = s.AdmNo
                AND ca.school_id = s.school_id
                AND ca.is_current = 1
          )
          OR (
              NOT EXISTS (
                  SELECT 1
                  FROM class_allocation ca_any
                  WHERE ca_any.student_id = s.AdmNo
                    AND ca_any.school_id = s.school_id
              )
              AND EXISTS (
                  SELECT 1
                  FROM classallocation legacy_ca
                  WHERE legacy_ca.AdmNo = s.AdmNo
                    AND legacy_ca.school_id = s.school_id
              )
          )
      )
    """
)


def get_authoritative_active_student_count(school_id):
    if school_id in (None, ''):
        return None

    try:
        result = db.session.execute(ACTIVE_STUDENT_COUNT_SQL, {'school_id': school_id}).mappings().first()
    except SQLAlchemyError as exc:
        logger.warning('Unable to resolve active student count for school %s: %s', school_id, exc)
        return None

    if not result:
        return 0
    return int(result.get('count') or 0)


def _normalize_student_count(student_count, current_billing_meta=None):
    if student_count is None and current_billing_meta:
        student_count = current_billing_meta.get('student_count')
    if student_count in (None, ''):
        return None
    try:
        normalized = int(student_count)
    except (TypeError, ValueError) as exc:
        raise ValueError('Student count must be a valid integer') from exc
    if normalized < 0:
        raise ValueError('Student count must be zero or greater')
    return normalized


def _resolve_effective_student_count(student_count=None, school_id=None, current_billing_meta=None):
    if student_count not in (None, ''):
        return _normalize_student_count(student_count), 'manual_override'

    persisted_count = _normalize_student_count(None, current_billing_meta=current_billing_meta)
    persisted_source = (current_billing_meta or {}).get('student_count_source') if current_billing_meta else None

    authoritative_count = get_authoritative_active_student_count(school_id)
    if authoritative_count is not None:
        if authoritative_count == 0 and persisted_count is not None and persisted_source == 'manual_override':
            return persisted_count, persisted_source
        return authoritative_count, 'students_module'

    if persisted_count is not None:
        return persisted_count, persisted_source or 'billing_meta'

    return None, None


def _candidate_student_bands_for_plan(plan_id=None):
    if plan_id is None:
        return StudentBand.query.filter_by(is_active=True).order_by(StudentBand.sort_order.asc()).all()

    priced_band_ids = [
        row.student_band_id
        for row in PlanBandPrice.query.filter_by(plan_id=plan_id).order_by(PlanBandPrice.student_band_id.asc()).all()
    ]
    if not priced_band_ids:
        return StudentBand.query.filter_by(is_active=True).order_by(StudentBand.sort_order.asc()).all()

    return (
        StudentBand.query
        .filter(StudentBand.id.in_(priced_band_ids), StudentBand.is_active.is_(True))
        .order_by(StudentBand.sort_order.asc())
        .all()
    )


def _resolve_student_band(student_count=None, student_band_id=None, current_billing_meta=None, plan_id=None):
    candidate_bands = _candidate_student_bands_for_plan(plan_id=plan_id)

    if student_band_id not in (None, ''):
        band = db.session.get(StudentBand, int(student_band_id))
        if band is None or not band.is_active:
            raise ValueError('Student band not found')
        return band

    normalized_count = _normalize_student_count(student_count, current_billing_meta=current_billing_meta)
    if not candidate_bands:
        return None
    if normalized_count is None:
        resolved_band_id = (current_billing_meta or {}).get('student_band_id')
        if resolved_band_id not in (None, ''):
            band = db.session.get(StudentBand, int(resolved_band_id))
            if band is None or not band.is_active:
                raise ValueError('Student band not found')
            return band
    if normalized_count is None:
        return candidate_bands[0]

    if normalized_count < (candidate_bands[0].min_students or 0):
        return candidate_bands[0]

    for band in candidate_bands:
        max_students = band.max_students
        if normalized_count >= band.min_students and (max_students is None or normalized_count <= max_students):
            return band
    return candidate_bands[-1]


def resolve_subscription_pricing(plan, school_id=None, student_count=None, student_band_id=None, current_billing_meta=None):
    billing_meta = dict(current_billing_meta or {})
    normalized_count, count_source = _resolve_effective_student_count(
        student_count=student_count,
        school_id=school_id,
        current_billing_meta=current_billing_meta,
    )
    band = _resolve_student_band(
        student_count=normalized_count,
        student_band_id=student_band_id,
        current_billing_meta=current_billing_meta,
        plan_id=plan.id,
    )

    amount_cents = plan.price_cents or 0
    if band is not None:
        plan_band_price = PlanBandPrice.query.filter_by(plan_id=plan.id, student_band_id=band.id).first()
        if plan_band_price is not None:
            amount_cents = plan_band_price.price_cents or 0
        billing_meta.update(
            {
                'pricing_model': 'student_band',
                'student_band_id': band.id,
                'student_band_label': band.label,
                'student_band_min_students': band.min_students,
                'student_band_max_students': band.max_students,
            }
        )
    if normalized_count is not None:
        billing_meta['student_count'] = normalized_count
        if count_source:
            billing_meta['student_count_source'] = count_source
    else:
        billing_meta.pop('student_count_source', None)

    return amount_cents, billing_meta


def create_subscription_record(school_id, plan_id, actor_user_id=None, status='active', billing_meta=None, student_count=None, student_band_id=None):
    plan = db.session.get(Plan, plan_id)
    if not plan:
        raise ValueError('Plan not found')

    amount_cents, resolved_billing_meta = resolve_subscription_pricing(
        plan,
        school_id=school_id,
        student_count=student_count,
        student_band_id=student_band_id,
        current_billing_meta=billing_meta,
    )

    subscription = Subscription(
        school_id=school_id,
        plan_id=plan.id,
        status=status,
        billing_cycle=plan.billing_period or 'monthly',
        amount_cents=amount_cents,
        renewal_date=utc_now(),
        billing_meta=resolved_billing_meta,
    )
    db.session.add(subscription)
    db.session.commit()
    _sync_school_snapshot(subscription, plan=plan)
    db.session.commit()
    _audit_subscription_event(
        subscription,
        'subscription_created',
        {
            'plan_id': plan.id,
            'plan_name': plan.name,
            'status': subscription.status,
            'billing_cycle': subscription.billing_cycle,
            'amount_cents': subscription.amount_cents,
            'student_count': subscription.billing_meta.get('student_count') if subscription.billing_meta else None,
            'student_band_label': subscription.billing_meta.get('student_band_label') if subscription.billing_meta else None,
        },
        actor_user_id=actor_user_id,
    )
    return subscription


def assign_plan_to_school(school_id, plan_id, actor_user_id=None, student_count=None, student_band_id=None):
    subscription = get_subscription_by_school(school_id)
    if subscription is None:
        return create_subscription_record(
            school_id,
            plan_id,
            actor_user_id=actor_user_id,
            student_count=student_count,
            student_band_id=student_band_id,
        )
    return change_plan(
        subscription.id,
        plan_id,
        actor_user_id=actor_user_id,
        student_count=student_count,
        student_band_id=student_band_id,
    )


def change_plan(subscription_id, new_plan_id, actor_user_id=None, student_count=None, student_band_id=None):
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    new_plan = db.session.get(Plan, new_plan_id)
    if not new_plan:
        raise ValueError('Plan not found')

    old_plan_id = sub.plan_id
    old_billing_cycle = sub.billing_cycle
    old_amount_cents = sub.amount_cents
    old_billing_meta = dict(sub.billing_meta or {})
    sub.plan_id = new_plan_id
    sub.renewal_date = utc_now()
    sub.amount_cents, sub.billing_meta = resolve_subscription_pricing(
        new_plan,
        school_id=sub.school_id,
        student_count=student_count,
        student_band_id=student_band_id,
        current_billing_meta=sub.billing_meta,
    )
    if new_plan.billing_period:
        sub.billing_cycle = new_plan.billing_period
    _sync_school_snapshot(sub, plan=new_plan)
    db.session.commit()
    _audit_subscription_event(
        sub,
        'subscription_plan_changed',
        {
            'old_plan_id': old_plan_id,
            'new_plan_id': new_plan.id,
            'new_plan_name': new_plan.name,
            'old_billing_cycle': old_billing_cycle,
            'new_billing_cycle': sub.billing_cycle,
            'old_amount_cents': old_amount_cents,
            'new_amount_cents': sub.amount_cents,
            'old_student_count': old_billing_meta.get('student_count'),
            'new_student_count': sub.billing_meta.get('student_count') if sub.billing_meta else None,
            'old_student_band_label': old_billing_meta.get('student_band_label'),
            'new_student_band_label': sub.billing_meta.get('student_band_label') if sub.billing_meta else None,
        },
        actor_user_id=actor_user_id,
    )
    return sub


def cancel_subscription(subscription_id, actor_user_id=None):
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    old_status = sub.status
    sub.status = 'cancelled'
    sub.renewal_date = None
    sub.ended_at = utc_now()
    resolved_reason = None
    sub.billing_meta = _merged_billing_meta(
        sub,
        suspension_reason=None,
        suspension_reason_code=None,
        suspension_recorded_at=None,
        cancellation_reason=resolved_reason,
        cancellation_reason_code=None,
        cancellation_recorded_at=utc_now().isoformat(),
    )
    _sync_school_snapshot(sub)
    db.session.commit()
    _audit_subscription_event(
        sub,
        'subscription_cancelled',
        {
            'old_status': old_status,
            'new_status': sub.status,
            'ended_at': sub.ended_at.isoformat() if sub.ended_at else None,
            'cancellation_reason': resolved_reason,
            'cancellation_reason_code': None,
        },
        actor_user_id=actor_user_id,
    )
    return sub


def cancel_subscription_with_reason(subscription_id, actor_user_id=None, reason=None, reason_code=None):
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    old_status = sub.status
    sub.status = 'cancelled'
    sub.renewal_date = None
    sub.ended_at = utc_now()
    resolved_reason = (reason or '').strip() or None
    resolved_reason_code = (reason_code or '').strip() or None
    sub.billing_meta = _merged_billing_meta(
        sub,
        suspension_reason=None,
        suspension_reason_code=None,
        suspension_recorded_at=None,
        cancellation_reason=resolved_reason,
        cancellation_reason_code=resolved_reason_code,
        cancellation_recorded_at=utc_now().isoformat(),
    )
    _sync_school_snapshot(sub)
    db.session.commit()
    _audit_subscription_event(
        sub,
        'subscription_cancelled',
        {
            'old_status': old_status,
            'new_status': sub.status,
            'ended_at': sub.ended_at.isoformat() if sub.ended_at else None,
            'cancellation_reason': resolved_reason,
            'cancellation_reason_code': resolved_reason_code,
        },
        actor_user_id=actor_user_id,
    )
    return sub


def activate_subscription(subscription_id, actor_user_id=None):
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    old_status = sub.status
    sub.status = 'active'
    sub.started_at = utc_now()
    sub.ended_at = None
    sub.archived_at = None
    sub.grace_period_ends_at = None
    sub.billing_meta = _clear_enforcement_reasons(sub)
    _sync_school_snapshot(sub)
    db.session.commit()
    _audit_subscription_event(
        sub,
        'subscription_activated',
        {
            'old_status': old_status,
            'new_status': sub.status,
            'started_at': sub.started_at.isoformat() if sub.started_at else None,
        },
        actor_user_id=actor_user_id,
    )
    return sub


def start_grace_period(subscription_id, until=None, actor_user_id=None):
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    old_status = sub.status
    sub.status = 'grace_period'
    sub.grace_period_ends_at = until or sub.grace_period_ends_at or utc_now()
    _sync_school_snapshot(sub)
    db.session.commit()
    _audit_subscription_event(
        sub,
        'subscription_grace_period_started',
        {
            'old_status': old_status,
            'new_status': sub.status,
            'grace_period_ends_at': sub.grace_period_ends_at.isoformat() if sub.grace_period_ends_at else None,
        },
        actor_user_id=actor_user_id,
    )
    return sub


def suspend_subscription(subscription_id, ended_at=None, actor_user_id=None, reason=None, reason_code=None):
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    old_status = sub.status
    sub.status = 'suspended'
    sub.ended_at = ended_at or utc_now()
    resolved_reason = (reason or '').strip() or None
    resolved_reason_code = (reason_code or '').strip() or None
    sub.billing_meta = _merged_billing_meta(
        sub,
        suspension_reason=resolved_reason,
        suspension_reason_code=resolved_reason_code,
        suspension_recorded_at=utc_now().isoformat(),
        cancellation_reason=None,
        cancellation_reason_code=None,
        cancellation_recorded_at=None,
    )
    _sync_school_snapshot(sub)
    db.session.commit()
    _audit_subscription_event(
        sub,
        'subscription_suspended',
        {
            'old_status': old_status,
            'new_status': sub.status,
            'ended_at': sub.ended_at.isoformat() if sub.ended_at else None,
            'suspension_reason': resolved_reason,
            'suspension_reason_code': resolved_reason_code,
        },
        actor_user_id=actor_user_id,
    )
    return sub
