import pytest
from sqlalchemy import inspect, text

from models import User
from platform_bp.services.onboarding import onboard_school, get_onboarding_status
from platform_bp.models import Plan, PlanBandPrice, StudentBand


def _ensure_student_count_tables(db_session):
    engine = db_session.get_bind()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        if 'studentinfo' not in existing_tables:
            connection.execute(text(
                """
                CREATE TABLE studentinfo (
                    AdmNo VARCHAR(32) NOT NULL,
                    blocked VARCHAR(8),
                    school_id INTEGER NOT NULL,
                    PRIMARY KEY (AdmNo, school_id)
                )
                """
            ))
        if 'class_allocation' not in existing_tables:
            connection.execute(text(
                """
                CREATE TABLE class_allocation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id VARCHAR(32) NOT NULL,
                    class_id INTEGER,
                    academic_year_id INTEGER,
                    school_id INTEGER NOT NULL,
                    is_current BOOLEAN NOT NULL DEFAULT 1
                )
                """
            ))
        if 'classallocation' not in existing_tables:
            connection.execute(text(
                """
                CREATE TABLE classallocation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    AdmNo VARCHAR(32) NOT NULL,
                    classID INTEGER,
                    thisYear INTEGER,
                    school_id INTEGER NOT NULL
                )
                """
            ))


def test_onboard_creates_school_and_subscription(db_session):
    # create plan first
    p = Plan(name='TestPlan', price_cents=0)
    db_session.add(p)
    db_session.commit()

    school, sub, admin_user = onboard_school('Test School', 'TEST01', default_plan_name='TestPlan', welcome_email=None)
    assert school.id is not None
    assert school.code == 'TEST01'
    assert sub is not None
    assert sub.plan_id == p.id
    assert admin_user is None


def test_onboard_validation_duplicate_code(db_session):
    # create initial school
    school, _, _ = onboard_school('S1', 'DUP1')
    with pytest.raises(ValueError):
        onboard_school('S2', 'DUP1')


def test_onboard_creates_initial_admin_and_default_trial_subscription(db_session):
    starter = Plan(name='Starter', price_cents=0, billing_period='monthly')
    db_session.add(starter)
    db_session.commit()

    school, sub, admin_user = onboard_school(
        'Greenfield Academy',
        'gf-01',
        timezone='Africa/Nairobi',
        admin_user={'username': 'schooladmin', 'password': 'secret123', 'staff_id': 'ADM001'},
        school_contact={'email': 'office@greenfield.test', 'phone': '0700000000'},
    )

    assert school.code == 'GF01'
    assert school.email == 'office@greenfield.test'
    assert sub is not None
    assert sub.plan_id == starter.id
    assert sub.status == 'trial'
    assert sub.trial_ends_at is not None
    assert admin_user is not None
    assert admin_user.username == 'schooladmin'
    assert admin_user.TA == 1
    assert admin_user.school_id == school.id

    saved_admin = User.query.filter_by(username='schooladmin', school_id=school.id).first()
    assert saved_admin is not None

    status = get_onboarding_status(school.id)
    assert status['subscription']['status'] == 'trial'
    assert status['admin_user']['username'] == 'schooladmin'


def test_onboard_uses_student_band_pricing_when_student_count_is_provided(db_session):
    plan = Plan(name='Growth', price_cents=12000, billing_period='monthly')
    band_small = StudentBand(label='growth-small', min_students=1, max_students=300, sort_order=10)
    band_large = StudentBand(label='growth-large', min_students=301, max_students=700, sort_order=20)
    db_session.add_all([plan, band_small, band_large])
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=12000),
        PlanBandPrice(plan_id=plan.id, student_band_id=band_large.id, price_cents=24000),
    ])
    db_session.commit()

    school, sub, _ = onboard_school(
        'Banded Academy',
        'BAND1',
        default_plan_name='Growth',
        student_count=500,
    )

    assert school.code == 'BAND1'
    assert sub is not None
    assert sub.amount_cents == 24000
    assert sub.billing_meta['student_count'] == 500
    assert sub.billing_meta['student_band_label'] == 'growth-large'

    status = get_onboarding_status(school.id)
    assert status['subscription']['amount_cents'] == 24000
    assert status['subscription']['student_count'] == 500
    assert status['subscription']['student_band_label'] == 'growth-large'


def test_onboard_defaults_to_first_student_band_when_school_has_no_active_students(db_session):
    _ensure_student_count_tables(db_session)

    plan = Plan(name='Launch', price_cents=8000, billing_period='monthly')
    band_small = StudentBand(label='launch-small', min_students=1, max_students=300, sort_order=10)
    band_large = StudentBand(label='launch-large', min_students=301, max_students=700, sort_order=20)
    db_session.add_all([plan, band_small, band_large])
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=8000),
        PlanBandPrice(plan_id=plan.id, student_band_id=band_large.id, price_cents=16000),
    ])
    db_session.commit()

    school, sub, _ = onboard_school(
        'Launch Academy',
        'LCH1',
        default_plan_name='Launch',
    )

    assert school.code == 'LCH1'
    assert sub is not None
    assert sub.amount_cents == 8000
    assert sub.billing_meta['student_count'] == 0
    assert sub.billing_meta['student_count_source'] == 'students_module'
    assert sub.billing_meta['student_band_label'] == 'launch-small'

    status = get_onboarding_status(school.id)
    assert status['subscription']['amount_cents'] == 8000
    assert status['subscription']['student_count'] == 0
    assert status['subscription']['student_band_label'] == 'launch-small'


def test_onboard_resolves_plan_from_bundle_family_and_billing_period(db_session):
    monthly_plan = Plan(
        name='Academic Monthly Launch',
        price_cents=10000,
        billing_period='monthly',
        bundle_family='academic',
    )
    annual_plan = Plan(
        name='Academic Annual Launch',
        price_cents=90000,
        billing_period='annual',
        bundle_family='academic',
    )
    db_session.add_all([monthly_plan, annual_plan])
    db_session.commit()

    school, sub, _ = onboard_school(
        'Commercial Selection Academy',
        'CSA1',
        bundle_family='academic',
        billing_period='annual',
    )

    assert school.code == 'CSA1'
    assert sub is not None
    assert sub.plan_id == annual_plan.id
    assert sub.billing_cycle == 'annual'

    status = get_onboarding_status(school.id)
    assert status['subscription']['bundle_family'] == 'academic'
    assert status['subscription']['billing_cycle'] == 'annual'
