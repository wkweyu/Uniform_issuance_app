from flask import jsonify, render_template, request, redirect, session, url_for, flash
from extensions import db
from ..services.pricing_catalog import bundle_family_options
from ..services.onboarding import onboard_school, get_onboarding_status
from ..services.subscriptions import get_billing_period_options
from ..decorators import platform_required


@platform_required(permission='onboarding_manage')
def onboarding_wizard():
    from ..models import Plan

    def _render_form():
        plans = Plan.query.order_by(Plan.price_cents.asc(), Plan.name.asc()).all()
        return render_template(
            'platform/onboarding.html',
            plans=plans,
            bundle_family_options=bundle_family_options(),
            billing_period_options=get_billing_period_options(),
        )

    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        timezone = request.form.get('timezone') or 'UTC'
        default_plan_id = request.form.get('default_plan_id', type=int)
        bundle_family = (request.form.get('bundle_family') or '').strip() or None
        billing_period = (request.form.get('billing_period') or '').strip() or None
        admin_username = request.form.get('admin_username')
        admin_password = request.form.get('admin_password')
        admin_staff_id = request.form.get('admin_staff_id')
        contact_email = request.form.get('contact_email')
        student_count = request.form.get('student_count', type=int)

        try:
            school, subscription, admin_account = onboard_school(
                name,
                code,
                timezone,
                welcome_email=contact_email or None,
                default_plan_id=default_plan_id,
                admin_user={
                    'username': admin_username,
                    'password': admin_password,
                    'staff_id': admin_staff_id,
                },
                school_contact={
                    'email': contact_email,
                    'phone': request.form.get('contact_phone'),
                    'address': request.form.get('address'),
                    'city': request.form.get('city'),
                    'country': request.form.get('country'),
                },
                student_count=student_count,
                bundle_family=bundle_family,
                billing_period=billing_period,
            )
        except ValueError as exc:
            flash(str(exc), 'error')
            return _render_form()
        flash(
            f"School onboarded for {school.name}. "
            f"Subscription: {(subscription.status if subscription else 'not provisioned')}. "
            f"Admin: {(admin_account.username if admin_account else 'not created')}",
            'success',
        )
        subscription_plan = db.session.get(Plan, subscription.plan_id) if subscription and subscription.plan_id else None
        session['platform_last_onboarding'] = {
            'school_id': school.id,
            'school_name': school.name,
            'school_code': school.code,
            'admin_username': admin_account.username if admin_account else None,
            'admin_password': admin_password if admin_account else None,
            'subscription_status': subscription.status if subscription else None,
            'bundle_family': subscription_plan.bundle_family if subscription_plan else None,
            'billing_period': subscription.billing_cycle if subscription else None,
            'student_count': (subscription.billing_meta or {}).get('student_count') if subscription else None,
            'student_band_label': (subscription.billing_meta or {}).get('student_band_label') if subscription else None,
            'login_url': url_for('auth.login', _external=True),
        }
        return redirect(url_for('platform.onboarding_confirmation', school_id=school.id))
    return _render_form()


@platform_required(permission='onboarding_manage')
def onboarding_status(school_id):
    status = get_onboarding_status(school_id)
    if status is None:
        return jsonify({'error': 'School not found'}), 404
    return jsonify(status)


@platform_required(permission='onboarding_manage')
def onboarding_confirmation(school_id):
    summary = session.get('platform_last_onboarding') or {}
    status = get_onboarding_status(school_id)
    if status is None:
        flash('School not found', 'error')
        return redirect(url_for('platform.list_schools'))

    if summary.get('school_id') != school_id:
        summary = {
            'school_id': school_id,
            'school_name': status['school']['name'],
            'school_code': status['school']['code'],
            'admin_username': status.get('admin_user', {}).get('username') if status.get('admin_user') else None,
            'admin_password': None,
            'subscription_status': status.get('subscription', {}).get('status') if status.get('subscription') else None,
            'login_url': url_for('auth.login', _external=True),
        }

    return render_template('platform/onboarding_confirmation.html', summary=summary, status=status)


def register_routes(bp):
    bp.add_url_rule('/onboarding', endpoint='onboarding_wizard', view_func=onboarding_wizard, methods=['GET', 'POST'])
    bp.add_url_rule('/onboarding/<int:school_id>/status', endpoint='onboarding_status', view_func=onboarding_status)
    bp.add_url_rule('/onboarding/<int:school_id>/confirmation', endpoint='onboarding_confirmation', view_func=onboarding_confirmation)
