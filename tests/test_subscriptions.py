import pytest
from platform_bp.services.subscriptions import change_plan, cancel_subscription, activate_subscription
from platform_bp.models import Plan, Subscription
import pytest
from platform_bp.services.subscriptions import change_plan, cancel_subscription, activate_subscription
from platform_bp.models import Plan, Subscription


def test_subscription_lifecycle(db_session):
    plan_a = Plan(name='A', price_cents=100)
    plan_b = Plan(name='B', price_cents=200)
    db_session.add_all([plan_a, plan_b])
    db_session.commit()

    sub = Subscription(school_id=1, plan_id=plan_a.id)
    db_session.add(sub)
    db_session.commit()

    # change plan
    changed = change_plan(sub.id, plan_b.id)
    assert changed.plan_id == plan_b.id

    # cancel
    cancelled = cancel_subscription(sub.id)
    assert cancelled.status == 'cancelled'

    # reactivate
    activated = activate_subscription(sub.id)
    assert activated.status == 'active'