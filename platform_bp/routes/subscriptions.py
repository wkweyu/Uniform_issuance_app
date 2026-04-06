import csv
from datetime import timedelta
from io import StringIO

from flask import abort, flash, make_response, redirect, render_template, request, session, url_for
from ..services.pricing_catalog import bundle_family_options
from ..decorators import get_current_platform_user, platform_required
from ..services.access import get_portfolio_school_ids, school_in_portfolio
from ..services.audit import list_logs
from ..services.subscriptions import (
    activate_subscription,
    assign_plan_to_school,
    build_entitlement_state_counts,
    build_subscription_entitlement_summary,
    cancel_subscription_with_reason,
    change_plan,
    create_subscription_record,
    empty_entitlement_summary,
    entitlement_summary_matches,
    get_entitlement_filter_options,
    get_entitlement_state_filter_options,
    get_enforcement_reason_options,
    get_billing_period_options,
    get_reason_label,
    refresh_subscription_pricing,
    resolve_plan_for_commercial_selection,
    get_subscription_reason_context,
    start_grace_period,
    suspend_subscription,
    utc_now,
)


def _resolve_subscription_redirect(default_endpoint='platform.list_subscriptions', **default_values):
    school_id = request.form.get('school_id', type=int)
    if school_id:
        return redirect(url_for('platform.school_detail', school_id=school_id))
    subscription_id = request.form.get('return_subscription_id', type=int)
    if subscription_id:
        return redirect(url_for('platform.subscription_detail', subscription_id=subscription_id))
    return redirect(url_for(default_endpoint, **default_values))


def _resolve_requested_plan_id():
    plan_id = request.form.get('plan_id', type=int)
    if plan_id:
        return plan_id

    bundle_family = (request.form.get('bundle_family') or '').strip() or None
    billing_period = (request.form.get('billing_period') or '').strip() or None
    plan = resolve_plan_for_commercial_selection(bundle_family=bundle_family, billing_period=billing_period)
    if plan is None:
        raise ValueError('Bundle family and billing period must match an available commercial plan')
    return plan.id


@platform_required(permission='billing_access')
def list_subscriptions():
    from app import School
    from ..models import Plan, Subscription
    status_filter = (request.args.get('status') or '').strip().lower() or None
    reason_code_filter = (request.args.get('reason_code') or '').strip() or None
    included_module_code_filter = (request.args.get('included_module_code') or '').strip() or None
    missing_module_code_filter = (request.args.get('missing_module_code') or '').strip() or None
    entitlement_state_filter = (request.args.get('entitlement_state') or '').strip() or None

    scoped_school_ids = get_portfolio_school_ids(get_current_platform_user())
    subscription_query = Subscription.query
    if scoped_school_ids:
        subscription_query = subscription_query.filter(Subscription.school_id.in_(scoped_school_ids))
    subs = subscription_query.order_by(Subscription.started_at.desc()).all()
    subs = [refresh_subscription_pricing(sub, reason='subscription_list_view') for sub in subs]
    entitlement_summaries = {sub.id: build_subscription_entitlement_summary(subscription=sub) for sub in subs}
    entitlement_state_counts = build_entitlement_state_counts(entitlement_summaries.values())
    if status_filter:
        subs = [sub for sub in subs if sub.effective_status == status_filter]
    if reason_code_filter:
        subs = [sub for sub in subs if get_subscription_reason_context(sub).get('code') == reason_code_filter]
    if included_module_code_filter or missing_module_code_filter or entitlement_state_filter:
        subs = [
            sub for sub in subs
            if entitlement_summary_matches(
                entitlement_summaries[sub.id],
                included_module_code=included_module_code_filter,
                missing_module_code=missing_module_code_filter,
                entitlement_state=entitlement_state_filter,
            )
        ]

    plans = Plan.query.order_by(Plan.name.asc()).all()
    school_query = School.query
    if scoped_school_ids:
        school_query = school_query.filter(School.id.in_(scoped_school_ids))
    schools = {school.id: school for school in school_query.order_by(School.name.asc()).all()}
    subscription_reason_context = {sub.id: get_subscription_reason_context(sub) for sub in subs}
    return render_template(
        'platform/subscriptions_list.html',
        subscriptions=subs,
        plans=plans,
        schools=schools,
        filters={
            'status': status_filter,
            'reason_code': reason_code_filter,
            'included_module_code': included_module_code_filter,
            'missing_module_code': missing_module_code_filter,
            'entitlement_state': entitlement_state_filter,
        },
        enforcement_reason_options=get_enforcement_reason_options(),
        entitlement_filter_options=get_entitlement_filter_options(),
        entitlement_state_filter_options=get_entitlement_state_filter_options(),
        subscription_reason_context=subscription_reason_context,
        entitlement_summaries=entitlement_summaries,
        entitlement_state_counts=entitlement_state_counts,
        export_query_string='&'.join(
            f"{key}={value}"
            for key, value in {
                'status': status_filter,
                'reason_code': reason_code_filter,
                'included_module_code': included_module_code_filter,
                'missing_module_code': missing_module_code_filter,
                'entitlement_state': entitlement_state_filter,
            }.items()
            if value
        ),
    )


def _build_subscription_export_rows(subscriptions):
    from app import School
    from ..models import AuditLog, Plan, PlatformUser

    plan_lookup = {plan.id: plan for plan in Plan.query.order_by(Plan.name.asc()).all()}
    school_lookup = {school.id: school for school in School.query.order_by(School.name.asc()).all()}
    subscription_ids = [str(subscription.id) for subscription in subscriptions]
    latest_logs_by_subscription = {}

    if subscription_ids:
        audit_logs = (
            AuditLog.query
            .filter(AuditLog.target_table == 'subscriptions')
            .filter(AuditLog.target_id.in_(subscription_ids))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .all()
        )
        for audit_log in audit_logs:
            latest_logs_by_subscription.setdefault(audit_log.target_id, []).append(audit_log)

    actor_ids = {
        audit_log.actor_user_id
        for audit_logs in latest_logs_by_subscription.values()
        for audit_log in audit_logs
        if audit_log.actor_user_id
    }
    actor_lookup = {
        user.id: user
        for user in PlatformUser.query.filter(PlatformUser.id.in_(actor_ids)).all()
    } if actor_ids else {}

    rows = []
    for subscription in subscriptions:
        reason_context = get_subscription_reason_context(subscription)
        candidate_logs = latest_logs_by_subscription.get(str(subscription.id), [])
        selected_log = None
        if reason_context.get('code'):
            for audit_log in candidate_logs:
                changes = dict(audit_log.changes or {})
                if changes.get('suspension_reason_code') == reason_context['code'] or changes.get('cancellation_reason_code') == reason_context['code']:
                    selected_log = audit_log
                    break
        if selected_log is None and candidate_logs:
            selected_log = candidate_logs[0]

        actor = actor_lookup.get(selected_log.actor_user_id) if selected_log and selected_log.actor_user_id else None
        rows.append(
            {
                'subscription': subscription,
                'plan': plan_lookup.get(subscription.plan_id),
                'school': school_lookup.get(subscription.school_id),
                'reason_context': reason_context,
                'entitlement_summary': build_subscription_entitlement_summary(subscription=subscription),
                'actor_log': selected_log,
                'actor': actor,
            }
        )
    return rows


@platform_required(permission='billing_access')
def export_subscriptions_csv():
    from ..models import Subscription

    status_filter = (request.args.get('status') or '').strip().lower() or None
    reason_code_filter = (request.args.get('reason_code') or '').strip() or None
    included_module_code_filter = (request.args.get('included_module_code') or '').strip() or None
    missing_module_code_filter = (request.args.get('missing_module_code') or '').strip() or None
    entitlement_state_filter = (request.args.get('entitlement_state') or '').strip() or None

    scoped_school_ids = get_portfolio_school_ids(get_current_platform_user())
    subscription_query = Subscription.query
    if scoped_school_ids:
        subscription_query = subscription_query.filter(Subscription.school_id.in_(scoped_school_ids))
    subscriptions = subscription_query.order_by(Subscription.started_at.desc()).all()
    subscriptions = [refresh_subscription_pricing(subscription, reason='subscription_export_view') for subscription in subscriptions]
    entitlement_summaries = {subscription.id: build_subscription_entitlement_summary(subscription=subscription) for subscription in subscriptions}
    if status_filter:
        subscriptions = [subscription for subscription in subscriptions if subscription.effective_status == status_filter]
    if reason_code_filter:
        subscriptions = [subscription for subscription in subscriptions if get_subscription_reason_context(subscription).get('code') == reason_code_filter]
    if included_module_code_filter or missing_module_code_filter or entitlement_state_filter:
        subscriptions = [
            subscription for subscription in subscriptions
            if entitlement_summary_matches(
                entitlement_summaries[subscription.id],
                included_module_code=included_module_code_filter,
                missing_module_code=missing_module_code_filter,
                entitlement_state=entitlement_state_filter,
            )
        ]

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'subscription_id',
        'school_name',
        'school_code',
        'plan_name',
        'status',
        'effective_status',
        'billing_cycle',
        'amount_cents',
        'entitlement_access_mode',
        'entitled_module_codes',
        'read_module_codes',
        'write_module_codes',
        'reason_code',
        'reason_label',
        'reason_text',
        'actor_name',
        'actor_email',
        'actor_role',
        'audit_action',
        'audit_created_at',
        'started_at',
        'renewal_date',
        'trial_ends_at',
        'grace_period_ends_at',
        'ended_at',
    ])

    for row in _build_subscription_export_rows(subscriptions):
        subscription = row['subscription']
        plan = row['plan']
        school = row['school']
        reason_context = row['reason_context']
        entitlement_summary = row['entitlement_summary']
        actor_log = row['actor_log']
        actor = row['actor']
        writer.writerow([
            subscription.id,
            school.name if school else '',
            school.code if school else '',
            plan.name if plan else '',
            subscription.status or '',
            subscription.effective_status or '',
            subscription.billing_cycle or '',
            subscription.amount_cents or 0,
            entitlement_summary.get('access_mode') or '',
            '|'.join(module['code'] for module in entitlement_summary.get('modules', [])),
            '|'.join(sorted(entitlement_summary.get('read_module_codes') or set())),
            '|'.join(sorted(entitlement_summary.get('write_module_codes') or set())),
            reason_context.get('code') or '',
            reason_context.get('label') or '',
            reason_context.get('text') or '',
            (actor.name or actor.email) if actor else ('Platform user' if actor_log and actor_log.actor_platform and actor_log.actor_user_id else 'System'),
            actor.email if actor else '',
            actor.role if actor else '',
            actor_log.action if actor_log else '',
            actor_log.created_at.isoformat() if actor_log and actor_log.created_at else '',
            subscription.started_at.isoformat() if subscription.started_at else '',
            subscription.renewal_date.isoformat() if subscription.renewal_date else '',
            subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else '',
            subscription.grace_period_ends_at.isoformat() if subscription.grace_period_ends_at else '',
            subscription.ended_at.isoformat() if subscription.ended_at else '',
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=subscriptions-billing-review.csv'
    return response


@platform_required(permission='billing_access')
def subscription_detail(subscription_id):
    from app import School, db
    from ..models import Plan, Subscription

    subscription = db.session.get(Subscription, subscription_id)
    if subscription is None:
        abort(404)
    subscription = refresh_subscription_pricing(subscription, reason='subscription_detail_view')
    if not school_in_portfolio(get_current_platform_user(), subscription.school_id):
        abort(403)
    school = db.session.get(School, subscription.school_id)
    plans = Plan.query.order_by(Plan.name.asc()).all()
    current_plan = db.session.get(Plan, subscription.plan_id) if subscription.plan_id else None
    audit_logs = list_logs(target_table='subscriptions', target_id=subscription.id, limit=20)
    entitlement_summary = build_subscription_entitlement_summary(subscription=subscription) if subscription else empty_entitlement_summary()
    return render_template(
        'platform/subscription_detail.html',
        subscription=subscription,
        school=school,
        plans=plans,
        current_plan=current_plan,
        audit_logs=audit_logs,
        entitlement_summary=entitlement_summary,
        current_student_count=(subscription.billing_meta or {}).get('student_count'),
        current_student_band_label=(subscription.billing_meta or {}).get('student_band_label'),
        bundle_family_options=bundle_family_options(),
        billing_period_options=get_billing_period_options(),
        suspension_reason=(subscription.billing_meta or {}).get('suspension_reason'),
        cancellation_reason=(subscription.billing_meta or {}).get('cancellation_reason'),
        suspension_reason_code=(subscription.billing_meta or {}).get('suspension_reason_code'),
        cancellation_reason_code=(subscription.billing_meta or {}).get('cancellation_reason_code'),
        enforcement_reason_options=get_enforcement_reason_options(),
        reason_label=get_reason_label,
    )


@platform_required(role='super_admin')
def create_subscription():
    if request.method == 'POST':
        school_id = request.form.get('school_id', type=int)
        student_count = request.form.get('student_count', type=int)
        try:
            plan_id = _resolve_requested_plan_id()
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('platform.list_subscriptions'))
        if not school_id:
            flash('School is required', 'error')
            return redirect(url_for('platform.list_subscriptions'))
        create_subscription_record(
            school_id,
            plan_id,
            actor_user_id=session.get('platform_user_id'),
            student_count=student_count,
        )
        flash('Subscription created', 'success')
        return _resolve_subscription_redirect()
    from ..models import Plan
    plans = Plan.query.all()
    from app import School
    schools = School.query.all()
    return render_template(
        'platform/subscriptions_create.html',
        plans=plans,
        schools=schools,
        bundle_family_options=bundle_family_options(),
        billing_period_options=get_billing_period_options(),
    )


@platform_required(role='super_admin')
def change_subscription_plan(subscription_id):
    student_count = request.form.get('student_count', type=int)
    try:
        plan_id = _resolve_requested_plan_id()
    except ValueError as exc:
        flash(str(exc), 'error')
        return _resolve_subscription_redirect()

    change_plan(
        subscription_id,
        plan_id,
        actor_user_id=session.get('platform_user_id'),
        student_count=student_count,
    )
    flash('Subscription plan updated', 'success')
    return _resolve_subscription_redirect()


@platform_required(role='super_admin')
def assign_school_plan_route(school_id):
    from app import School, db

    school = db.session.get(School, school_id)
    if school is None:
        abort(404)

    student_count = request.form.get('student_count', type=int)
    try:
        plan_id = _resolve_requested_plan_id()
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('platform.school_detail', school_id=school.id))

    assign_plan_to_school(
        school.id,
        plan_id,
        actor_user_id=session.get('platform_user_id'),
        student_count=student_count,
    )
    flash('School plan assignment updated.', 'success')
    return redirect(url_for('platform.school_detail', school_id=school.id))


@platform_required(role='super_admin')
def activate_subscription_route(subscription_id):
    activate_subscription(subscription_id, actor_user_id=session.get('platform_user_id'))
    flash('Subscription activated', 'success')
    return _resolve_subscription_redirect()


@platform_required(role='super_admin')
def cancel_subscription_route(subscription_id):
    cancel_subscription_with_reason(
        subscription_id,
        actor_user_id=session.get('platform_user_id'),
        reason=request.form.get('reason'),
        reason_code=request.form.get('reason_code'),
    )
    flash('Subscription cancelled', 'success')
    return _resolve_subscription_redirect()


@platform_required(role='super_admin')
def start_subscription_grace_period(subscription_id):
    days = request.form.get('days', type=int)
    until = utc_now() + timedelta(days=days) if days is not None else None
    start_grace_period(subscription_id, until=until, actor_user_id=session.get('platform_user_id'))
    flash('Subscription moved to grace period', 'success')
    return _resolve_subscription_redirect()


@platform_required(role='super_admin')
def suspend_subscription_route(subscription_id):
    suspend_subscription(
        subscription_id,
        actor_user_id=session.get('platform_user_id'),
        reason=request.form.get('reason'),
        reason_code=request.form.get('reason_code'),
    )
    flash('Subscription suspended', 'success')
    return _resolve_subscription_redirect()


def register_routes(bp):
    bp.add_url_rule('/subscriptions', endpoint='list_subscriptions', view_func=list_subscriptions)
    bp.add_url_rule('/subscriptions/export', endpoint='export_subscriptions_csv', view_func=export_subscriptions_csv)
    bp.add_url_rule('/subscriptions/<int:subscription_id>', endpoint='subscription_detail', view_func=subscription_detail)
    bp.add_url_rule('/subscriptions/create', endpoint='create_subscription', view_func=create_subscription, methods=['GET', 'POST'])
    bp.add_url_rule('/schools/<int:school_id>/assign-plan', endpoint='assign_school_plan_route', view_func=assign_school_plan_route, methods=['POST'])
    bp.add_url_rule('/subscriptions/<int:subscription_id>/change-plan', endpoint='change_subscription_plan', view_func=change_subscription_plan, methods=['POST'])
    bp.add_url_rule('/subscriptions/<int:subscription_id>/activate', endpoint='activate_subscription_route', view_func=activate_subscription_route, methods=['POST'])
    bp.add_url_rule('/subscriptions/<int:subscription_id>/cancel', endpoint='cancel_subscription_route', view_func=cancel_subscription_route, methods=['POST'])
    bp.add_url_rule('/subscriptions/<int:subscription_id>/grace-period', endpoint='start_subscription_grace_period', view_func=start_subscription_grace_period, methods=['POST'])
    bp.add_url_rule('/subscriptions/<int:subscription_id>/suspend', endpoint='suspend_subscription_route', view_func=suspend_subscription_route, methods=['POST'])
