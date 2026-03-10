from flask import render_template, request, redirect, url_for, flash
from ..decorators import platform_required


@platform_required(role='platform_admin')
def list_subscriptions():
    from ..models import Subscription
    subs = Subscription.query.order_by(Subscription.started_at.desc()).all()
    return render_template('platform/subscriptions_list.html', subscriptions=subs)


@platform_required(role='platform_admin')
def create_subscription():
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        plan_id = request.form.get('plan_id')
        from app import db
        from ..models import Subscription
        sub = Subscription(school_id=school_id, plan_id=plan_id)
        db.session.add(sub)
        db.session.commit()
        flash('Subscription created', 'success')
        return redirect(url_for('platform.list_subscriptions'))
    from ..models import Plan
    plans = Plan.query.all()
    from app import School
    schools = School.query.all()
    return render_template('platform/subscriptions_create.html', plans=plans, schools=schools)


def register_routes(bp):
    bp.add_url_rule('/subscriptions', endpoint='list_subscriptions', view_func=list_subscriptions)
    bp.add_url_rule('/subscriptions/create', endpoint='create_subscription', view_func=create_subscription, methods=['GET', 'POST'])
