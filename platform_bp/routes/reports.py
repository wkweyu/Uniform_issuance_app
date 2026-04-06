import csv
from io import StringIO

from flask import abort, flash, make_response, redirect, render_template, request, session, url_for
from extensions import db

from ..decorators import get_current_platform_user, platform_required
from ..services.access import get_portfolio_school_ids, school_in_portfolio
from ..services.reporting import build_pricing_report_context
from ..services.subscriptions import update_subscription_mapping_review


@platform_required(permission='billing_access')
def pricing_reports():
    scoped_school_ids = get_portfolio_school_ids(get_current_platform_user())
    return render_template('platform/pricing_reports.html', **build_pricing_report_context(school_ids=scoped_school_ids))


@platform_required(permission='billing_access')
def export_pricing_reports_csv():
    scoped_school_ids = get_portfolio_school_ids(get_current_platform_user())
    context = build_pricing_report_context(school_ids=scoped_school_ids)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'school_id',
        'school_name',
        'school_code',
        'subscription_id',
        'plan_name',
        'effective_status',
        'billing_cycle',
        'bundle_family',
        'student_band_label',
        'student_count',
        'student_count_source',
        'amount_cents',
        'projected_monthly_cents',
        'projected_annual_cents',
        'entitlement_configuration_state',
        'module_codes',
        'module_names',
        'mapping_review_state',
        'mapping_review_label',
        'mapping_review_is_ambiguous',
        'mapping_review_notes',
        'mapping_review_updated_at',
        'mapping_review_actor',
    ])

    for row in context['report_rows']:
        actor = context['actor_lookup'].get(row['mapping_review']['actor_user_id'])
        writer.writerow([
            row['school'].id,
            row['school'].name,
            row['school'].code,
            row['subscription'].id,
            row['plan'].name,
            row['effective_status'],
            row['billing_cycle'],
            row['bundle_family'],
            row['student_band_label'],
            row['student_count'] if row['student_count'] is not None else '',
            row['student_count_source'] or '',
            row['amount_cents'],
            row['monthly_equivalent_cents'],
            row['annualized_cents'],
            row['entitlement_summary']['configuration_state'],
            '|'.join(row['module_codes']),
            '|'.join(row['module_names']),
            row['mapping_review']['state'],
            row['mapping_review']['label'],
            'yes' if row['mapping_review']['is_ambiguous'] else 'no',
            row['mapping_review']['notes'] or '',
            row['mapping_review']['updated_at'] or '',
            (actor.name or actor.email) if actor else '',
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=pricing-state-review.csv'
    return response


@platform_required(role='super_admin')
def update_mapping_review(subscription_id):
    from ..models import Subscription

    subscription = db.session.get(Subscription, subscription_id)
    if subscription is None:
        abort(404)
    if not school_in_portfolio(get_current_platform_user(), subscription.school_id):
        abort(403)

    status = (request.form.get('mapping_review_status') or '').strip().lower()
    notes = (request.form.get('mapping_review_notes') or '').strip() or None
    if status not in {'confirmed', 'review_required'}:
        flash('Select a valid mapping review state.', 'error')
        return redirect(url_for('platform.pricing_reports'))

    update_subscription_mapping_review(
        subscription_id=subscription.id,
        review_status=status,
        review_notes=notes,
        actor_user_id=session.get('platform_user_id'),
    )
    flash('Mapping review updated.', 'success')
    return redirect(url_for('platform.pricing_reports'))


def register_routes(bp):
    bp.add_url_rule('/reports/pricing', endpoint='pricing_reports', view_func=pricing_reports)
    bp.add_url_rule('/reports/pricing/export', endpoint='export_pricing_reports_csv', view_func=export_pricing_reports_csv)
    bp.add_url_rule('/subscriptions/<int:subscription_id>/mapping-review', endpoint='update_mapping_review', view_func=update_mapping_review, methods=['POST'])