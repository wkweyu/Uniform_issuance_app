import pytest
from platform_bp.services.onboarding import onboard_school, get_onboarding_status
from platform_bp.models import Plan


def test_onboard_creates_school_and_subscription(db_session):
    # create plan first
    p = Plan(name='TestPlan', price_cents=0)
    db_session.add(p)
    db_session.commit()

    school, sub = onboard_school('Test School', 'TEST01', default_plan_name='TestPlan', welcome_email=None)
    assert school.id is not None
    assert school.code == 'TEST01'
    assert sub is not None
    assert sub.plan_id == p.id


def test_onboard_validation_duplicate_code(db_session):
    # create initial school
    school, _ = onboard_school('S1', 'DUP1')
    with pytest.raises(ValueError):
        onboard_school('S2', 'DUP1')
