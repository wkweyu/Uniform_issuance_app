from app import db
from platform_bp.models import Subscription, Plan
from datetime import datetime


def change_plan(subscription_id, new_plan_id):
    sub = Subscription.query.get(subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    new_plan = Plan.query.get(new_plan_id)
    if not new_plan:
        raise ValueError('Plan not found')

    old_plan_id = sub.plan_id
    sub.plan_id = new_plan_id
    sub.renewal_date = datetime.utcnow()
    db.session.commit()
    return sub


def cancel_subscription(subscription_id):
    sub = Subscription.query.get(subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    sub.status = 'cancelled'
    sub.renewal_date = None
    db.session.commit()
    return sub


def get_subscription_by_school(school_id):
    return Subscription.query.filter_by(school_id=school_id).first()


def activate_subscription(subscription_id):
    sub = Subscription.query.get(subscription_id)
    if not sub:
        raise ValueError('Subscription not found')
    sub.status = 'active'
    sub.started_at = datetime.utcnow()
    db.session.commit()
    return sub
