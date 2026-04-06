from datetime import UTC, datetime, timedelta

from sqlalchemy import inspect, text

from platform_bp.models import AuditLog, Plan, PlanBandPrice, StudentBand, Subscription
from platform_bp.services.subscriptions import activate_subscription, cancel_subscription_with_reason, change_plan, create_subscription_record, get_authoritative_active_student_count, get_subscription_by_school, get_subscription_reason_context, resolve_plan_for_commercial_selection, resolve_subscription_pricing, start_grace_period, suspend_subscription


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


def test_subscription_lifecycle(db_session):
    plan_a = Plan(name='A', price_cents=100)
    plan_b = Plan(name='B', price_cents=200)
    db_session.add_all([plan_a, plan_b])
    db_session.commit()

    sub = Subscription(school_id=901, plan_id=plan_a.id, amount_cents=plan_a.price_cents, billing_cycle=plan_a.billing_period)
    db_session.add(sub)
    db_session.commit()

    # change plan
    changed = change_plan(sub.id, plan_b.id)
    assert changed.plan_id == plan_b.id
    assert changed.amount_cents == plan_b.price_cents
    assert changed.billing_cycle == plan_b.billing_period

    # cancel
    cancelled = cancel_subscription_with_reason(sub.id, reason='Customer requested closure', reason_code='contract_terminated')
    assert cancelled.status == 'cancelled'
    assert cancelled.ended_at is not None
    assert cancelled.billing_meta['cancellation_reason_code'] == 'contract_terminated'

    # reactivate
    activated = activate_subscription(sub.id)
    assert activated.status == 'active'
    assert activated.ended_at is None

    audit_actions = [
        entry.action
        for entry in AuditLog.query.filter_by(target_table='subscriptions', target_id=str(sub.id), school_id=sub.school_id).order_by(AuditLog.id.asc()).all()
    ]
    assert audit_actions == [
        'subscription_plan_changed',
        'subscription_cancelled',
        'subscription_activated',
    ]


def test_subscription_effective_status_grace_and_trial(db_session):
    plan = Plan(name='TrialPlan', price_cents=0)
    db_session.add(plan)
    db_session.commit()

    grace_sub = Subscription(
        school_id=902,
        plan_id=plan.id,
        status='active',
        grace_period_ends_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=2),
    )
    trial_sub = Subscription(
        school_id=903,
        plan_id=plan.id,
        status='trial',
        trial_ends_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=5),
    )
    db_session.add_all([grace_sub, trial_sub])
    db_session.commit()

    assert grace_sub.effective_status == 'grace_period'
    assert grace_sub.allows_login is True
    assert grace_sub.allows_writes is False

    assert trial_sub.effective_status == 'trial'
    assert trial_sub.allows_login is True
    assert trial_sub.allows_writes is True


def test_subscription_grace_and_suspend_create_audit_entries(db_session):
    plan = Plan(name='LifecycleAudit', price_cents=1000)
    db_session.add(plan)
    db_session.commit()

    sub = Subscription(school_id=909, plan_id=plan.id, status='active', amount_cents=plan.price_cents, billing_cycle=plan.billing_period)
    db_session.add(sub)
    db_session.commit()

    start_grace_period(sub.id, until=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7))
    suspend_subscription(sub.id, reason='Payment risk', reason_code='chargeback_risk')

    entries = AuditLog.query.filter_by(target_table='subscriptions', target_id=str(sub.id), school_id=sub.school_id).order_by(AuditLog.id.asc()).all()

    assert [entry.action for entry in entries] == [
        'subscription_grace_period_started',
        'subscription_suspended',
    ]
    assert entries[0].changes['new_status'] == 'grace_period'
    assert entries[1].changes['new_status'] == 'suspended'
    assert entries[1].changes['suspension_reason_code'] == 'chargeback_risk'


def test_subscription_reason_context_prefers_structured_reason_codes(db_session):
    plan = Plan(name='ReasonCatalog', price_cents=1200)
    db_session.add(plan)
    db_session.commit()

    sub = Subscription(
        school_id=910,
        plan_id=plan.id,
        status='suspended',
        billing_meta={
            'suspension_reason_code': 'manual_admin_hold',
            'suspension_reason': 'Manual hold pending review',
        },
    )
    db_session.add(sub)
    db_session.commit()

    context = get_subscription_reason_context(sub)

    assert context['type'] == 'suspension'
    assert context['code'] == 'manual_admin_hold'
    assert context['label'] == 'Manual admin hold'
    assert context['text'] == 'Manual hold pending review'


def test_subscription_pricing_uses_student_band_amount_and_persists_context(db_session):
    plan = Plan(name='Band Plan', price_cents=10000, billing_period='monthly')
    band_small = StudentBand(label='band-plan-small', min_students=1, max_students=300, sort_order=10)
    band_medium = StudentBand(label='band-plan-medium', min_students=301, max_students=700, sort_order=20)
    db_session.add_all([plan, band_small, band_medium])
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=10000),
        PlanBandPrice(plan_id=plan.id, student_band_id=band_medium.id, price_cents=18000),
    ])
    db_session.commit()

    created = create_subscription_record(911, plan.id, student_count=420)

    assert created.amount_cents == 18000
    assert created.billing_meta['student_count'] == 420
    assert created.billing_meta['student_band_label'] == 'band-plan-medium'

    changed = change_plan(created.id, plan.id, student_count=250)

    assert changed.amount_cents == 10000
    assert changed.billing_meta['student_count'] == 250
    assert changed.billing_meta['student_band_label'] == 'band-plan-small'


def test_pricing_matrix_resolves_expected_plan_and_band_amounts_for_each_bundle_and_period(db_session):
    band_small = StudentBand(label='matrix-small', min_students=1, max_students=300, sort_order=10)
    band_large = StudentBand(label='matrix-large', min_students=301, max_students=None, sort_order=20)
    db_session.add_all([band_small, band_large])
    db_session.flush()

    bundle_period_prices = {
        ('academic', 'monthly'): (10000, 18000),
        ('academic', 'annual'): (90000, 162000),
        ('accounting', 'monthly'): (12000, 21000),
        ('accounting', 'annual'): (108000, 189000),
        ('combined', 'monthly'): (18000, 32000),
        ('combined', 'annual'): (162000, 288000),
    }

    for (bundle_family, billing_period), (small_price, large_price) in bundle_period_prices.items():
        plan = Plan(
            name=f'{bundle_family}-{billing_period}-matrix',
            price_cents=small_price,
            billing_period=billing_period,
            bundle_family=bundle_family,
        )
        db_session.add(plan)
        db_session.flush()
        db_session.add_all([
            PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=small_price),
            PlanBandPrice(plan_id=plan.id, student_band_id=band_large.id, price_cents=large_price),
        ])
    db_session.commit()

    for (bundle_family, billing_period), (small_price, large_price) in bundle_period_prices.items():
        resolved_plan = resolve_plan_for_commercial_selection(bundle_family=bundle_family, billing_period=billing_period)

        assert resolved_plan is not None
        assert resolved_plan.bundle_family == bundle_family
        assert resolved_plan.billing_period == billing_period

        small_amount, small_meta = resolve_subscription_pricing(resolved_plan, student_count=200)
        large_amount, large_meta = resolve_subscription_pricing(resolved_plan, student_count=900)

        assert small_amount == small_price
        assert small_meta['student_band_label'] == 'matrix-small'
        assert large_amount == large_price
        assert large_meta['student_band_label'] == 'matrix-large'


def test_authoritative_student_count_uses_current_allocations_with_legacy_fallback(db_session):
    _ensure_student_count_tables(db_session)

    db_session.execute(
        text(
            "INSERT INTO studentinfo (AdmNo, blocked, school_id) VALUES (:admno, :blocked, :school_id)"
        ),
        [
            {'admno': 'A100', 'blocked': 'NO', 'school_id': 951},
            {'admno': 'A200', 'blocked': 'NO', 'school_id': 951},
            {'admno': 'A300', 'blocked': 'YES', 'school_id': 951},
            {'admno': 'A400', 'blocked': 'NO', 'school_id': 951},
            {'admno': 'A500', 'blocked': 'NO', 'school_id': 951},
        ],
    )
    db_session.execute(
        text(
            "INSERT INTO class_allocation (student_id, school_id, is_current) VALUES (:student_id, :school_id, :is_current)"
        ),
        [
            {'student_id': 'A100', 'school_id': 951, 'is_current': 1},
            {'student_id': 'A200', 'school_id': 951, 'is_current': 0},
            {'student_id': 'A300', 'school_id': 951, 'is_current': 1},
        ],
    )
    db_session.execute(
        text(
            "INSERT INTO classallocation (AdmNo, school_id, thisYear) VALUES (:admno, :school_id, :this_year)"
        ),
        [
            {'admno': 'A200', 'school_id': 951, 'this_year': 2026},
            {'admno': 'A400', 'school_id': 951, 'this_year': 2026},
        ],
    )
    db_session.commit()

    assert get_authoritative_active_student_count(951) == 2


def test_subscription_pricing_recomputes_from_authoritative_student_count_when_no_override_is_supplied(db_session):
    _ensure_student_count_tables(db_session)

    plan = Plan(name='Live Count Plan', price_cents=9000, billing_period='monthly')
    band_small = StudentBand(label='live-count-small', min_students=1, max_students=2, sort_order=10)
    band_medium = StudentBand(label='live-count-medium', min_students=3, max_students=10, sort_order=20)
    db_session.add_all([plan, band_small, band_medium])
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=9000),
        PlanBandPrice(plan_id=plan.id, student_band_id=band_medium.id, price_cents=15000),
    ])
    db_session.execute(
        text(
            "INSERT INTO studentinfo (AdmNo, blocked, school_id) VALUES (:admno, :blocked, :school_id)"
        ),
        [
            {'admno': 'B100', 'blocked': 'NO', 'school_id': 952},
            {'admno': 'B200', 'blocked': 'NO', 'school_id': 952},
            {'admno': 'B300', 'blocked': 'NO', 'school_id': 952},
        ],
    )
    db_session.execute(
        text(
            "INSERT INTO class_allocation (student_id, school_id, is_current) VALUES (:student_id, :school_id, :is_current)"
        ),
        [
            {'student_id': 'B100', 'school_id': 952, 'is_current': 1},
            {'student_id': 'B200', 'school_id': 952, 'is_current': 1},
            {'student_id': 'B300', 'school_id': 952, 'is_current': 1},
        ],
    )
    db_session.commit()

    created = create_subscription_record(952, plan.id)

    assert created.amount_cents == 15000
    assert created.billing_meta['student_count'] == 3
    assert created.billing_meta['student_count_source'] == 'students_module'
    assert created.billing_meta['student_band_label'] == 'live-count-medium'

    db_session.execute(
        text(
            "UPDATE studentinfo SET blocked = 'YES' WHERE AdmNo IN ('B200', 'B300') AND school_id = :school_id"
        ),
        {'school_id': 952},
    )
    db_session.commit()

    changed = change_plan(created.id, plan.id)

    assert changed.amount_cents == 9000
    assert changed.billing_meta['student_count'] == 1
    assert changed.billing_meta['student_count_source'] == 'students_module'
    assert changed.billing_meta['student_band_label'] == 'live-count-small'


def test_get_subscription_by_school_auto_refreshes_band_and_writes_audit_entries(db_session):
    _ensure_student_count_tables(db_session)

    plan = Plan(name='Auto Refresh Plan', price_cents=9000, billing_period='monthly', bundle_family='combined')
    band_small = StudentBand(label='auto-refresh-small', min_students=1, max_students=2, sort_order=10)
    band_medium = StudentBand(label='auto-refresh-medium', min_students=3, max_students=10, sort_order=20)
    db_session.add_all([plan, band_small, band_medium])
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=9000),
        PlanBandPrice(plan_id=plan.id, student_band_id=band_medium.id, price_cents=15000),
    ])
    db_session.execute(
        text(
            "INSERT INTO studentinfo (AdmNo, blocked, school_id) VALUES (:admno, :blocked, :school_id)"
        ),
        [
            {'admno': 'C100', 'blocked': 'NO', 'school_id': 953},
            {'admno': 'C200', 'blocked': 'NO', 'school_id': 953},
            {'admno': 'C300', 'blocked': 'NO', 'school_id': 953},
        ],
    )
    db_session.execute(
        text(
            "INSERT INTO class_allocation (student_id, school_id, is_current) VALUES (:student_id, :school_id, :is_current)"
        ),
        [
            {'student_id': 'C100', 'school_id': 953, 'is_current': 1},
            {'student_id': 'C200', 'school_id': 953, 'is_current': 1},
            {'student_id': 'C300', 'school_id': 953, 'is_current': 1},
        ],
    )
    subscription = Subscription(
        school_id=953,
        plan_id=plan.id,
        status='active',
        amount_cents=9000,
        billing_cycle='monthly',
        billing_meta={
            'student_count': 1,
            'student_count_source': 'billing_meta',
            'student_band_id': band_small.id,
            'student_band_label': 'auto-refresh-small',
        },
    )
    db_session.add(subscription)
    db_session.commit()

    refreshed = get_subscription_by_school(953)

    assert refreshed is not None
    assert refreshed.amount_cents == 15000
    assert refreshed.billing_meta['student_count'] == 3
    assert refreshed.billing_meta['student_count_source'] == 'students_module'
    assert refreshed.billing_meta['student_band_label'] == 'auto-refresh-medium'

    actions = [
        entry.action
        for entry in AuditLog.query.filter_by(target_table='subscriptions', target_id=str(subscription.id), school_id=953).order_by(AuditLog.id.asc()).all()
    ]
    assert actions == [
        'subscription_pricing_refreshed',
        'subscription_band_changed',
    ]