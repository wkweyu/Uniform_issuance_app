from collections import defaultdict

from extensions import db
from models import School

from ..config.modules import family_label
from ..models import Plan, PlatformUser, StudentBand, Subscription
from .schools import latest_subscriptions_by_school_ids
from .subscriptions import build_subscription_entitlement_summary


ACTIVE_REVENUE_STATUSES = {'trial', 'active', 'grace_period'}
ACTIVE_MAPPING_STATUSES = {'trial', 'active', 'grace_period'}
MAPPING_REVIEW_STATUS_LABELS = {
    'auto_mapped': 'Auto mapped',
    'confirmed': 'Confirmed mapped',
    'pending_review': 'Pending review',
    'review_required': 'Flagged for review',
}
RECURRING_MONTHS_BY_CYCLE = {
    'monthly': 1,
    'quarterly': 3,
    'semiannual': 6,
    'annual': 12,
}


def format_currency_from_cents(amount_cents):
    return f"KES {(amount_cents or 0) / 100:,.2f}"


def _cycle_to_months(billing_cycle):
    normalized_cycle = (billing_cycle or 'monthly').strip().lower()
    return RECURRING_MONTHS_BY_CYCLE.get(normalized_cycle, 1)


def _monthly_equivalent_cents(subscription):
    amount_cents = int(subscription.amount_cents or 0)
    cycle_months = _cycle_to_months(subscription.billing_cycle)
    return int(round(amount_cents / cycle_months)) if cycle_months else amount_cents


def _annualized_cents(subscription):
    return _monthly_equivalent_cents(subscription) * 12


def _mapping_review_details(subscription, entitlement_summary):
    billing_meta = dict(subscription.billing_meta or {})
    raw_status = (billing_meta.get('mapping_review_status') or '').strip().lower() or None
    is_ambiguous = not entitlement_summary.get('is_configured')

    if raw_status == 'confirmed':
        state = 'confirmed'
    elif raw_status == 'review_required':
        state = 'review_required'
    elif is_ambiguous:
        state = 'pending_review'
    else:
        state = 'auto_mapped'

    return {
        'state': state,
        'label': MAPPING_REVIEW_STATUS_LABELS[state],
        'is_ambiguous': is_ambiguous,
        'notes': billing_meta.get('mapping_review_notes'),
        'updated_at': billing_meta.get('mapping_review_updated_at'),
        'actor_user_id': billing_meta.get('mapping_review_actor_user_id'),
    }


def build_pricing_report_context(school_ids=None):
    school_query = School.query.order_by(School.name.asc())
    if school_ids:
        school_query = school_query.filter(School.id.in_(school_ids))
    schools = school_query.all()
    latest_subscriptions = latest_subscriptions_by_school_ids([school.id for school in schools])

    plans_by_id = {
        plan.id: plan
        for plan in Plan.query.order_by(Plan.name.asc()).all()
    }
    actor_ids = set()
    student_band_sort_order = {
        band.label: band.sort_order
        for band in StudentBand.query.filter_by(is_active=True).order_by(StudentBand.sort_order.asc()).all()
    }

    report_rows = []
    for school in schools:
        subscription = latest_subscriptions.get(school.id)
        if subscription is None:
            continue

        plan = plans_by_id.get(subscription.plan_id)
        if plan is None:
            continue

        entitlement_summary = build_subscription_entitlement_summary(subscription=subscription)
        module_rows = entitlement_summary.get('modules') or []
        mapping_review = _mapping_review_details(subscription, entitlement_summary)
        if mapping_review.get('actor_user_id'):
            actor_ids.add(mapping_review['actor_user_id'])

        billing_meta = dict(subscription.billing_meta or {})
        bundle_family = plan.bundle_family or 'unknown'
        student_band_label = billing_meta.get('student_band_label') or 'Unassigned'
        monthly_equivalent_cents = _monthly_equivalent_cents(subscription)
        annualized_cents = _annualized_cents(subscription)

        report_rows.append(
            {
                'school': school,
                'subscription': subscription,
                'plan': plan,
                'bundle_family': bundle_family,
                'bundle_family_label': family_label(bundle_family),
                'student_band_label': student_band_label,
                'student_band_sort_order': student_band_sort_order.get(student_band_label, 9999),
                'student_count': billing_meta.get('student_count'),
                'student_count_source': billing_meta.get('student_count_source'),
                'module_rows': module_rows,
                'module_codes': [module['code'] for module in module_rows],
                'module_names': [module['name'] for module in module_rows],
                'entitlement_summary': entitlement_summary,
                'mapping_review': mapping_review,
                'amount_cents': int(subscription.amount_cents or 0),
                'monthly_equivalent_cents': monthly_equivalent_cents,
                'annualized_cents': annualized_cents,
                'billing_cycle': subscription.billing_cycle or plan.billing_period or 'monthly',
                'effective_status': subscription.effective_status,
                'is_active_revenue': subscription.effective_status in ACTIVE_REVENUE_STATUSES,
                'is_active_mapping': subscription.effective_status in ACTIVE_MAPPING_STATUSES,
            }
        )

    actor_lookup = {
        user.id: user
        for user in PlatformUser.query.filter(PlatformUser.id.in_(actor_ids)).all()
    } if actor_ids else {}

    bundle_summary = defaultdict(lambda: {
        'bundle_family': None,
        'bundle_family_label': None,
        'school_count': 0,
        'active_school_count': 0,
        'projected_monthly_cents': 0,
        'projected_annual_cents': 0,
    })
    band_summary = defaultdict(lambda: {
        'student_band_label': None,
        'school_count': 0,
        'active_school_count': 0,
        'projected_monthly_cents': 0,
        'projected_annual_cents': 0,
        'sort_order': 9999,
    })
    module_summary = defaultdict(lambda: {
        'code': None,
        'name': None,
        'family_label': None,
        'school_ids': set(),
        'bundle_families': set(),
        'active_school_count': 0,
    })
    revenue_projection = defaultdict(lambda: {
        'bundle_family_label': None,
        'student_band_label': None,
        'school_count': 0,
        'projected_monthly_cents': 0,
        'projected_annual_cents': 0,
        'sort_order': 9999,
    })

    summary = {
        'schools_with_subscriptions': len(report_rows),
        'active_subscription_count': 0,
        'projected_monthly_cents': 0,
        'projected_annual_cents': 0,
        'ambiguous_active_count': 0,
        'pending_mapping_review_count': 0,
        'confirmed_mapping_count': 0,
        'review_required_count': 0,
        'auto_mapped_count': 0,
    }

    for row in report_rows:
        bundle_item = bundle_summary[row['bundle_family']]
        bundle_item['bundle_family'] = row['bundle_family']
        bundle_item['bundle_family_label'] = row['bundle_family_label']
        bundle_item['school_count'] += 1

        band_item = band_summary[row['student_band_label']]
        band_item['student_band_label'] = row['student_band_label']
        band_item['school_count'] += 1
        band_item['sort_order'] = min(band_item['sort_order'], row['student_band_sort_order'])

        if row['is_active_revenue']:
            summary['active_subscription_count'] += 1
            summary['projected_monthly_cents'] += row['monthly_equivalent_cents']
            summary['projected_annual_cents'] += row['annualized_cents']

            bundle_item['active_school_count'] += 1
            bundle_item['projected_monthly_cents'] += row['monthly_equivalent_cents']
            bundle_item['projected_annual_cents'] += row['annualized_cents']

            band_item['active_school_count'] += 1
            band_item['projected_monthly_cents'] += row['monthly_equivalent_cents']
            band_item['projected_annual_cents'] += row['annualized_cents']

            revenue_item = revenue_projection[(row['bundle_family_label'], row['student_band_label'])]
            revenue_item['bundle_family_label'] = row['bundle_family_label']
            revenue_item['student_band_label'] = row['student_band_label']
            revenue_item['school_count'] += 1
            revenue_item['projected_monthly_cents'] += row['monthly_equivalent_cents']
            revenue_item['projected_annual_cents'] += row['annualized_cents']
            revenue_item['sort_order'] = min(revenue_item['sort_order'], row['student_band_sort_order'])

        mapping_state = row['mapping_review']['state']
        if mapping_state == 'confirmed':
            summary['confirmed_mapping_count'] += 1
        elif mapping_state == 'review_required':
            summary['review_required_count'] += 1
        elif mapping_state == 'auto_mapped':
            summary['auto_mapped_count'] += 1

        if row['is_active_mapping'] and row['mapping_review']['is_ambiguous']:
            summary['ambiguous_active_count'] += 1
            if mapping_state == 'pending_review':
                summary['pending_mapping_review_count'] += 1

        for module in row['module_rows']:
            module_item = module_summary[module['code']]
            module_item['code'] = module['code']
            module_item['name'] = module['name']
            module_item['family_label'] = module['family_label']
            module_item['school_ids'].add(row['school'].id)
            module_item['bundle_families'].add(row['bundle_family_label'])
            if row['is_active_revenue']:
                module_item['active_school_count'] += 1

    bundle_rows = sorted(bundle_summary.values(), key=lambda item: item['bundle_family_label'] or '')
    band_rows = sorted(band_summary.values(), key=lambda item: (item['sort_order'], item['student_band_label']))
    module_rows = sorted(
        [
            {
                **item,
                'school_count': len(item['school_ids']),
                'bundle_family_labels': ', '.join(sorted(item['bundle_families'])),
            }
            for item in module_summary.values()
        ],
        key=lambda item: (-item['school_count'], item['name'] or item['code'] or ''),
    )
    revenue_rows = sorted(
        revenue_projection.values(),
        key=lambda item: (item['bundle_family_label'] or '', item['sort_order'], item['student_band_label'] or ''),
    )

    return {
        'summary': summary,
        'report_rows': report_rows,
        'bundle_rows': bundle_rows,
        'band_rows': band_rows,
        'module_rows': module_rows,
        'revenue_rows': revenue_rows,
        'actor_lookup': actor_lookup,
        'mapping_review_status_labels': MAPPING_REVIEW_STATUS_LABELS,
        'format_currency': format_currency_from_cents,
    }