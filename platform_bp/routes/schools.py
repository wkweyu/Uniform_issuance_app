import csv
from io import StringIO

from flask import abort, jsonify, make_response, render_template, request, redirect, url_for, flash, session
from ..decorators import get_current_platform_user, platform_required
from ..services.access import filter_school_collection_for_user, get_portfolio_school_ids, school_in_portfolio
from ..services.audit import list_logs
from ..services.metrics import build_dashboard_metrics, build_metrics_trends, serialize_dashboard_metrics
from ..services.pricing_catalog import bundle_family_options
from ..services.schools import (
    create_school as create_school_record,
    latest_subscriptions_by_school_ids,
    parse_optional_date,
    set_school_active,
    set_school_subscription_end,
)
from ..services.subscriptions import get_enforcement_reason_options, get_reason_label
from ..services.subscriptions import (
    build_entitlement_state_counts,
    build_subscription_entitlement_summary,
    empty_entitlement_summary,
    entitlement_summary_matches,
    get_billing_period_options,
    get_entitlement_filter_options,
    get_entitlement_state_filter_options,
)


@platform_required(permission='dashboard')
def index():
    window_days = request.args.get('window_days', default=7, type=int) or 7
    return render_template('platform/index.html', **build_dashboard_metrics(window_days=window_days), selected_window_days=window_days)


def _school_list_context():
    from app import School

    included_module_code_filter = (request.args.get('included_module_code') or '').strip() or None
    missing_module_code_filter = (request.args.get('missing_module_code') or '').strip() or None
    entitlement_state_filter = (request.args.get('entitlement_state') or '').strip() or None

    current_user = get_current_platform_user()
    schools = filter_school_collection_for_user(current_user, School.query.order_by(School.name).all())
    latest_subscriptions = latest_subscriptions_by_school_ids([school.id for school in schools])
    entitlement_summaries = {
        school.id: build_subscription_entitlement_summary(subscription=latest_subscriptions.get(school.id)) if latest_subscriptions.get(school.id) is not None else empty_entitlement_summary()
        for school in schools
    }
    entitlement_state_counts = build_entitlement_state_counts(entitlement_summaries.values())

    if included_module_code_filter or missing_module_code_filter or entitlement_state_filter:
        schools = [
            school for school in schools
            if entitlement_summary_matches(
                entitlement_summaries[school.id],
                included_module_code=included_module_code_filter,
                missing_module_code=missing_module_code_filter,
                entitlement_state=entitlement_state_filter,
            )
        ]

    return {
        'schools': schools,
        'latest_subscriptions': latest_subscriptions,
        'entitlement_summaries': entitlement_summaries,
        'entitlement_state_counts': entitlement_state_counts,
        'entitlement_filter_options': get_entitlement_filter_options(),
        'entitlement_state_filter_options': get_entitlement_state_filter_options(),
        'filters': {
            'included_module_code': included_module_code_filter,
            'missing_module_code': missing_module_code_filter,
            'entitlement_state': entitlement_state_filter,
        },
        'export_query_string': '&'.join(
            f"{key}={value}"
            for key, value in {
                'included_module_code': included_module_code_filter,
                'missing_module_code': missing_module_code_filter,
                'entitlement_state': entitlement_state_filter,
            }.items()
            if value
        ),
    }


@platform_required(permission='dashboard')
def metrics_summary():
    window_days = request.args.get('window_days', default=7, type=int) or 7
    return jsonify(serialize_dashboard_metrics(build_dashboard_metrics(window_days=window_days)))


@platform_required(permission='dashboard')
def metrics_trends():
    window_days = request.args.get('window_days', default=30, type=int) or 30
    return jsonify(build_metrics_trends(window_days=window_days))


@platform_required(permission='billing_access')
def list_schools():
    return render_template('platform/schools_list.html', **_school_list_context())


@platform_required(permission='billing_access')
def export_schools_csv():
    context = _school_list_context()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'school_id',
        'school_name',
        'school_code',
        'school_status',
        'subscription_status',
        'subscription_end',
        'entitlement_configuration_state',
        'entitlement_access_mode',
        'entitled_module_names',
        'entitled_module_codes',
        'read_module_codes',
        'write_module_codes',
    ])

    for school in context['schools']:
        latest_subscription = context['latest_subscriptions'].get(school.id)
        entitlement_summary = context['entitlement_summaries'][school.id]
        writer.writerow([
            school.id,
            school.name,
            school.code,
            'active' if school.is_active else 'inactive',
            latest_subscription.effective_status if latest_subscription else (school.subscription_status or 'trial'),
            school.subscription_end.isoformat() if school.subscription_end else '',
            entitlement_summary.get('configuration_state') or '',
            entitlement_summary.get('access_mode') or '',
            '|'.join(module['name'] for module in entitlement_summary.get('modules', [])),
            '|'.join(module['code'] for module in entitlement_summary.get('modules', [])),
            '|'.join(sorted(entitlement_summary.get('read_module_codes') or set())),
            '|'.join(sorted(entitlement_summary.get('write_module_codes') or set())),
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=schools-entitlement-review.csv'
    return response


@platform_required(permission='billing_access')
def school_detail(school_id):
    from app import School, db
    from ..models import Plan, PlatformUser

    school = db.session.get(School, school_id)
    if school is None:
        abort(404)
    if not school_in_portfolio(get_current_platform_user(), school.id):
        abort(403)

    latest_subscription = latest_subscriptions_by_school_ids([school.id]).get(school.id)
    audit_logs = list_logs(school_id=school.id, limit=20)
    enforcement_actions = {
        'school_status_updated',
        'school_subscription_window_updated',
        'subscription_created',
        'subscription_plan_changed',
        'subscription_grace_period_started',
        'subscription_suspended',
        'subscription_cancelled',
        'subscription_activated',
    }
    enforcement_timeline = [entry for entry in list_logs(school_id=school.id, limit=50) if entry.action in enforcement_actions][:12]
    actor_ids = {entry.actor_user_id for entry in enforcement_timeline if entry.actor_user_id}
    platform_users = PlatformUser.query.filter(PlatformUser.id.in_(actor_ids)).all() if actor_ids else []
    timeline_actor_lookup = {
        user.id: {
            'name': user.name or user.email,
            'email': user.email,
            'role': user.role,
        }
        for user in platform_users
    }
    plans = Plan.query.order_by(Plan.price_cents.asc(), Plan.name.asc()).all()
    plan_map = {plan.id: plan for plan in plans}
    billing_meta = latest_subscription.billing_meta or {} if latest_subscription else {}
    entitlement_summary = build_subscription_entitlement_summary(subscription=latest_subscription) if latest_subscription else empty_entitlement_summary()
    return render_template(
        'platform/school_detail.html',
        school=school,
        latest_subscription=latest_subscription,
        audit_logs=audit_logs,
        enforcement_timeline=enforcement_timeline,
        timeline_actor_lookup=timeline_actor_lookup,
        plans=plans,
        bundle_family_options=bundle_family_options(),
        billing_period_options=get_billing_period_options(),
        current_plan=plan_map.get(latest_subscription.plan_id) if latest_subscription else None,
        suspension_reason=billing_meta.get('suspension_reason'),
        cancellation_reason=billing_meta.get('cancellation_reason'),
        suspension_reason_code=billing_meta.get('suspension_reason_code'),
        cancellation_reason_code=billing_meta.get('cancellation_reason_code'),
        current_student_count=billing_meta.get('student_count'),
        current_student_band_label=billing_meta.get('student_band_label'),
        entitlement_summary=entitlement_summary,
        enforcement_reason_options=get_enforcement_reason_options(),
        reason_label=get_reason_label,
    )


@platform_required(role='super_admin')
def create_school():
    from app import School

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        code = (request.form.get('code') or '').strip()
        tz = request.form.get('timezone') or 'UTC'
        is_active = bool(request.form.get('is_active'))
        subscription_end = parse_optional_date(request.form.get('subscription_end'))

        if not name or not code:
            flash('School name and code are required.', 'error')
            return render_template('platform/schools_create.html')
        if School.query.filter_by(code=code).first() is not None:
            flash('School code already exists.', 'error')
            return render_template('platform/schools_create.html')

        create_school_record(
            name=name,
            code=code,
            timezone=tz,
            is_active=is_active,
            subscription_end=subscription_end,
            actor_user_id=session.get('platform_user_id'),
        )
        flash('School created', 'success')
        return redirect(url_for('platform.list_schools'))
    return render_template('platform/schools_create.html')


@platform_required(role='super_admin')
def activate_school(school_id):
    from app import School, db

    school = db.session.get(School, school_id)
    if school is None:
        abort(404)

    set_school_active(school, True, actor_user_id=session.get('platform_user_id'))
    flash('School activated.', 'success')
    return redirect(url_for('platform.school_detail', school_id=school.id))


@platform_required(role='super_admin')
def deactivate_school(school_id):
    from app import School, db

    school = db.session.get(School, school_id)
    if school is None:
        abort(404)

    set_school_active(school, False, actor_user_id=session.get('platform_user_id'))
    flash('School deactivated.', 'success')
    return redirect(url_for('platform.school_detail', school_id=school.id))


@platform_required(role='super_admin')
def update_school_subscription_window(school_id):
    from app import School, db

    school = db.session.get(School, school_id)
    if school is None:
        abort(404)

    subscription_end = parse_optional_date(request.form.get('subscription_end'))
    set_school_subscription_end(school, subscription_end, actor_user_id=session.get('platform_user_id'))
    flash('School subscription window updated.', 'success')
    return redirect(url_for('platform.school_detail', school_id=school.id))


def register_routes(bp):
    bp.add_url_rule('/', endpoint='index', view_func=index)
    bp.add_url_rule('/metrics/summary', endpoint='metrics_summary', view_func=metrics_summary)
    bp.add_url_rule('/metrics/trends', endpoint='metrics_trends', view_func=metrics_trends)
    bp.add_url_rule('/schools', endpoint='list_schools', view_func=list_schools)
    bp.add_url_rule('/schools/export', endpoint='export_schools_csv', view_func=export_schools_csv)
    bp.add_url_rule('/schools/<int:school_id>', endpoint='school_detail', view_func=school_detail)
    bp.add_url_rule('/schools/create', endpoint='create_school', view_func=create_school, methods=['GET', 'POST'])
    bp.add_url_rule('/schools/<int:school_id>/activate', endpoint='activate_school', view_func=activate_school, methods=['POST'])
    bp.add_url_rule('/schools/<int:school_id>/deactivate', endpoint='deactivate_school', view_func=deactivate_school, methods=['POST'])
    bp.add_url_rule('/schools/<int:school_id>/subscription-window', endpoint='update_school_subscription_window', view_func=update_school_subscription_window, methods=['POST'])
