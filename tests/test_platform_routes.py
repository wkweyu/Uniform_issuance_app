from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

from core.flash_messages import normalize_flash_category
from models import School, SchoolSettings, User
from platform_bp.models import AuditLog, ModuleCatalog, Plan, PlanModule, PlatformSetting, PlatformUser, SecurityEvent, SecurityNotificationDelivery, SecurityNotificationPreference, Subscription, SupportTicket
from platform_bp.services import notifications as notification_service
from platform_bp.services import security as security_service


def _login_platform_admin(client, platform_user_id, school_id=None):
    with client.session_transaction() as session:
        session['platform_user_id'] = platform_user_id
        if school_id is not None:
            session['school_id'] = school_id


def _reset_platform_access_settings(db_session):
    PlatformSetting.query.delete()
    db_session.commit()


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


def test_platform_routes_require_platform_session(client):
    response = client.get('/platform/schools')

    assert response.status_code == 302
    assert '/platform/login' in response.headers['Location']


def test_platform_tenant_user_search_requires_platform_session(client):
    response = client.get('/platform/tenant-users/search?q=teacher1')

    assert response.status_code == 302
    assert '/platform/login' in response.headers['Location']


def test_platform_login_and_school_list_access(client, db_session):
    db_session.add(
        PlatformUser(
            email='platform-admin@example.com',
            password_hash=generate_password_hash('secret123'),
            role='platform_admin',
        )
    )
    db_session.add(School(name='Tenant One', code='TEN1'))
    db_session.commit()

    response = client.post(
        '/platform/login',
        data={'email': 'platform-admin@example.com', 'password': 'secret123'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/platform/')

    school_list = client.get('/platform/schools')
    assert school_list.status_code == 200
    assert b'Control Plane' in school_list.data
    assert b'Tenant Portfolio' in school_list.data
    assert b'Tenant One' in school_list.data
    assert b'Manage' in school_list.data
    assert b'Configured' in school_list.data
    assert b'Export CSV' in school_list.data


def test_platform_login_page_uses_standard_login_layout(client):
    response = client.get('/platform/login')

    assert response.status_code == 200
    assert b'Platform Login' in response.data
    assert b'Sign in to access the control plane.' in response.data
    assert b'Sign In' in response.data


def test_platform_school_list_surfaces_entitlement_snapshot(client, db_session):
    platform_user = PlatformUser(
        email='school-list-entitlement-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Snapshot Academy', code='SNP1')
    plan = Plan(name='Snapshot Plan', price_cents=15000, billing_period='monthly')
    module_students = ModuleCatalog.query.filter_by(code='students').first() or ModuleCatalog(code='students', name='Students Management', family='academic', is_core=True, sort_order=10)
    module_fees = ModuleCatalog.query.filter_by(code='fees').first() or ModuleCatalog(code='fees', name='Fees Collection And Management', family='accounting', is_core=True, sort_order=20)
    db_session.add_all([platform_user, school, plan])
    if module_students.id is None:
        db_session.add(module_students)
    if module_fees.id is None:
        db_session.add(module_fees)
    db_session.flush()
    db_session.add_all([
        PlanModule(plan_id=plan.id, module_id=module_students.id, is_included=True, is_active=True),
        PlanModule(plan_id=plan.id, module_id=module_fees.id, is_included=True, is_active=True),
        Subscription(school_id=school.id, plan_id=plan.id, status='active', amount_cents=15000, billing_cycle='monthly'),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/schools')

    assert response.status_code == 200
    assert b'Snapshot Academy' in response.data
    assert b'Students Management' in response.data
    assert b'Fees Collection And Management' in response.data
    assert b'Academic Core' in response.data
    assert b'Accounting Core' in response.data


def test_platform_school_list_filters_by_entitlement_module_and_state(client, db_session):
    platform_user = PlatformUser(
        email='school-list-filter-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    fees_school = School(name='Fees School', code='FSC1', is_active=True)
    grace_school = School(name='Grace School', code='GSC1', is_active=True)
    legacy_school = School(name='Legacy School', code='LSC1', is_active=True)
    fees_plan = Plan(name='Fees School Plan', price_cents=15000, billing_period='monthly', features={'modules': ['students', 'fees']})
    grace_plan = Plan(name='Grace School Plan', price_cents=9000, billing_period='monthly', features={'modules': ['students']})
    legacy_plan = Plan(name='Legacy School Plan', price_cents=7000, billing_period='monthly')
    db_session.add_all([platform_user, fees_school, grace_school, legacy_school, fees_plan, grace_plan, legacy_plan])
    db_session.flush()
    db_session.add_all([
        Subscription(school_id=fees_school.id, plan_id=fees_plan.id, status='active', amount_cents=fees_plan.price_cents, billing_cycle=fees_plan.billing_period),
        Subscription(school_id=grace_school.id, plan_id=grace_plan.id, status='grace_period', amount_cents=grace_plan.price_cents, billing_cycle=grace_plan.billing_period),
        Subscription(school_id=legacy_school.id, plan_id=legacy_plan.id, status='active', amount_cents=legacy_plan.price_cents, billing_cycle=legacy_plan.billing_period),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    included_response = client.get('/platform/schools?included_module_code=fees')
    unconfigured_response = client.get('/platform/schools?missing_module_code=fees&entitlement_state=unconfigured')
    read_only_response = client.get('/platform/schools?entitlement_state=read_only')

    assert included_response.status_code == 200
    assert b'Fees School' in included_response.data
    assert b'Grace School' not in included_response.data
    assert b'Legacy School' not in included_response.data

    assert unconfigured_response.status_code == 200
    assert b'Legacy School' in unconfigured_response.data
    assert b'Fees School' not in unconfigured_response.data
    assert b'Grace School' not in unconfigured_response.data

    assert read_only_response.status_code == 200
    assert b'Grace School' in read_only_response.data
    assert b'Read Only Access' in read_only_response.data


def test_platform_schools_export_honors_entitlement_filters(client, db_session):
    platform_user = PlatformUser(
        email='school-export-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    fees_school = School(name='Export Fees School', code='EFS1', is_active=True)
    legacy_school = School(name='Export Legacy School', code='ELS1', is_active=True)
    fees_plan = Plan(name='Export Fees Plan', price_cents=16000, billing_period='monthly', features={'modules': ['students', 'fees']})
    legacy_plan = Plan(name='Export Legacy Plan', price_cents=8000, billing_period='monthly')
    db_session.add_all([platform_user, fees_school, legacy_school, fees_plan, legacy_plan])
    db_session.flush()
    db_session.add_all([
        Subscription(school_id=fees_school.id, plan_id=fees_plan.id, status='active', amount_cents=fees_plan.price_cents, billing_cycle=fees_plan.billing_period),
        Subscription(school_id=legacy_school.id, plan_id=legacy_plan.id, status='active', amount_cents=legacy_plan.price_cents, billing_cycle=legacy_plan.billing_period),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/schools/export?missing_module_code=fees&entitlement_state=unconfigured')

    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('text/csv')
    assert response.headers['Content-Disposition'] == 'attachment; filename=schools-entitlement-review.csv'
    csv_text = response.data.decode('utf-8')
    assert 'school_id,school_name,school_code,school_status,subscription_status,subscription_end,entitlement_configuration_state,entitlement_access_mode,entitled_module_names,entitled_module_codes,read_module_codes,write_module_codes' in csv_text
    assert 'Export Legacy School' in csv_text
    assert 'Export Fees School' not in csv_text
    assert ',unconfigured,unconfigured,' in csv_text


def test_platform_school_detail_shows_latest_subscription_and_audit(client, db_session):
    platform_user = PlatformUser(
        email='school-detail-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Detail Academy', code='DET1', subscription_status='active')
    plan = Plan(name='Detail Plan', price_cents=15000, billing_period='monthly')
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    subscription = Subscription(school_id=school.id, plan_id=plan.id, status='active', amount_cents=15000)
    audit_entry = AuditLog(
        actor_user_id=platform_user.id,
        actor_platform=True,
        action='school_created',
        target_table='schools',
        target_id=str(school.id),
        school_id=school.id,
    )
    db_session.add_all([subscription, audit_entry])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get(f'/platform/schools/{school.id}')

    assert response.status_code == 200
    assert b'Detail Academy' in response.data
    assert b'Latest Subscription' in response.data
    assert b'school_created' in response.data
    assert b'Billing Enforcement Timeline' in response.data


def test_platform_school_detail_surfaces_entitled_module_names(client, db_session):
    platform_user = PlatformUser(
        email='entitlement-school-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Entitlement Academy', code='ENT1', subscription_status='grace_period')
    plan = Plan(name='Entitlement Plan', price_cents=15000, billing_period='monthly')
    module_fees = ModuleCatalog.query.filter_by(code='fees').first() or ModuleCatalog(code='fees', name='Fees Collection And Management', family='accounting', is_core=True, sort_order=10)
    module_students = ModuleCatalog.query.filter_by(code='students').first() or ModuleCatalog(code='students', name='Students Management', family='academic', is_core=True, sort_order=20)
    db_session.add_all([platform_user, school, plan])
    if module_fees.id is None:
        db_session.add(module_fees)
    if module_students.id is None:
        db_session.add(module_students)
    db_session.flush()
    db_session.add_all([
        PlanModule(plan_id=plan.id, module_id=module_fees.id, is_included=True, is_active=True),
        PlanModule(plan_id=plan.id, module_id=module_students.id, is_included=True, is_active=True),
    ])
    subscription = Subscription(school_id=school.id, plan_id=plan.id, status='grace_period', amount_cents=15000, billing_cycle='monthly')
    db_session.add(subscription)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get(f'/platform/schools/{school.id}')

    assert response.status_code == 200
    assert b'Entitled Modules' in response.data
    assert b'Fees Collection And Management' in response.data
    assert b'Students Management' in response.data
    assert b'Accounting Core' in response.data
    assert b'Academic Core' in response.data
    assert b'Grace Period Read Only' in response.data
    assert b'Read Only' in response.data


def test_platform_create_school_creates_settings_and_audit_entry(client, db_session):
    platform_user = PlatformUser(
        email='creator@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    db_session.add(platform_user)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        '/platform/schools/create',
        data={
            'name': 'Provisioned Academy',
            'code': 'PRV1',
            'timezone': 'Africa/Nairobi',
            'subscription_end': '2026-11-30',
            'is_active': '1',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    school = School.query.filter_by(code='PRV1').first()
    assert school is not None
    assert school.subscription_end.isoformat() == '2026-11-30'

    settings = SchoolSettings.query.filter_by(school_id=school.id).first()
    assert settings is not None
    assert settings.timezone == 'Africa/Nairobi'

    audit_entry = AuditLog.query.filter_by(target_table='schools', target_id=str(school.id), action='school_created').first()
    assert audit_entry is not None


def test_super_admin_can_update_school_status_and_subscription_window(client, db_session):
    platform_user = PlatformUser(
        email='super-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='Lifecycle Academy', code='LIF1', is_active=True)
    db_session.add_all([platform_user, school])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    deactivate_response = client.post(f'/platform/schools/{school.id}/deactivate', follow_redirects=False)
    subscription_response = client.post(
        f'/platform/schools/{school.id}/subscription-window',
        data={'subscription_end': '2026-12-31'},
        follow_redirects=False,
    )
    activate_response = client.post(f'/platform/schools/{school.id}/activate', follow_redirects=False)

    assert deactivate_response.status_code == 302
    assert subscription_response.status_code == 302
    assert activate_response.status_code == 302

    db_session.refresh(school)
    assert school.is_active is True
    assert school.subscription_end.isoformat() == '2026-12-31'

    actions = [
        entry.action
        for entry in AuditLog.query.filter_by(target_table='schools', target_id=str(school.id)).order_by(AuditLog.id.asc()).all()
    ]
    assert 'school_status_updated' in actions
    assert 'school_subscription_window_updated' in actions


def test_platform_admin_cannot_use_super_admin_school_lifecycle_controls(client, db_session):
    platform_user = PlatformUser(
        email='not-super@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Restricted Academy', code='RST1', is_active=True)
    db_session.add_all([platform_user, school])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    deactivate_response = client.post(f'/platform/schools/{school.id}/deactivate', follow_redirects=False)
    create_response = client.post(
        '/platform/schools/create',
        data={'name': 'Blocked Academy', 'code': 'BLK1', 'timezone': 'UTC', 'is_active': '1'},
        follow_redirects=False,
    )

    assert deactivate_response.status_code == 403
    assert create_response.status_code == 403


def test_legacy_super_admin_school_controls_redirect_to_platform_login(client):
    with client.session_transaction() as session:
        session['userNo'] = 99
        session['school_id'] = 1
        session['is_super_admin'] = True
        session['logged_in'] = True

    response = client.get('/super_admin/schools', follow_redirects=False)

    assert response.status_code == 302
    assert '/platform/login' in response.headers['Location']
    assert 'next=' in response.headers['Location']


def test_school_detail_can_assign_plan_and_suspend_with_reason(client, db_session):
    platform_user = PlatformUser(
        email='enforcement-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='Enforcement Academy', code='ENF1', is_active=True)
    plan = Plan(name='Enforcement Plan', price_cents=23000, billing_period='monthly')
    db_session.add_all([platform_user, school, plan])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    assign_response = client.post(
        f'/platform/schools/{school.id}/assign-plan',
        data={'plan_id': str(plan.id)},
        follow_redirects=False,
    )

    assert assign_response.status_code == 302
    subscription = Subscription.query.filter_by(school_id=school.id).order_by(Subscription.id.desc()).first()
    assert subscription is not None
    assert subscription.plan_id == plan.id
    assert subscription.status == 'active'

    suspend_response = client.post(
        f'/platform/subscriptions/{subscription.id}/suspend',
        data={'school_id': str(school.id), 'reason_code': 'billing_delinquency', 'reason': 'Billing delinquency after grace period'},
        follow_redirects=False,
    )

    assert suspend_response.status_code == 302
    assert suspend_response.headers['Location'].endswith(f'/platform/schools/{school.id}')

    db_session.refresh(subscription)
    assert subscription.status == 'suspended'
    assert subscription.billing_meta['suspension_reason'] == 'Billing delinquency after grace period'
    assert subscription.billing_meta['suspension_reason_code'] == 'billing_delinquency'

    page_response = client.get(f'/platform/schools/{school.id}')

    assert page_response.status_code == 200
    assert b'enforcement-admin@example.com' in page_response.data
    assert b'Billing delinquency' in page_response.data

    actions = [
        entry.action
        for entry in AuditLog.query.filter_by(target_table='subscriptions', school_id=school.id).order_by(AuditLog.id.asc()).all()
    ]
    assert 'subscription_created' in actions
    assert 'subscription_suspended' in actions


def test_school_detail_assign_plan_uses_student_band_pricing(client, db_session):
    from platform_bp.models import PlanBandPrice, StudentBand

    platform_user = PlatformUser(
        email='school-band-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='School Band Academy', code='SBA1', is_active=True)
    plan = Plan(name='School Band Plan', price_cents=12000, billing_period='monthly')
    band_small = StudentBand(label='school-band-small', min_students=1, max_students=300, sort_order=10)
    band_medium = StudentBand(label='school-band-medium', min_students=301, max_students=700, sort_order=20)
    db_session.add_all([platform_user, school, plan, band_small, band_medium])
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=12000),
        PlanBandPrice(plan_id=plan.id, student_band_id=band_medium.id, price_cents=26000),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        f'/platform/schools/{school.id}/assign-plan',
        data={'plan_id': str(plan.id), 'student_count': '520'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    subscription = Subscription.query.filter_by(school_id=school.id).order_by(Subscription.id.desc()).first()
    assert subscription is not None
    assert subscription.amount_cents == 26000
    assert subscription.billing_meta['student_count'] == 520
    assert subscription.billing_meta['student_band_label'] == 'school-band-medium'


def test_school_detail_assign_plan_uses_authoritative_student_count_when_manual_count_is_omitted(client, db_session):
    from platform_bp.models import PlanBandPrice, StudentBand

    _ensure_student_count_tables(db_session)

    platform_user = PlatformUser(
        email='school-live-count-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='School Live Count Academy', code='SLC1', is_active=True)
    plan = Plan(name='School Live Count Plan', price_cents=12000, billing_period='monthly')
    band_small = StudentBand(label='school-live-count-small', min_students=1, max_students=2, sort_order=10)
    band_medium = StudentBand(label='school-live-count-medium', min_students=3, max_students=10, sort_order=20)
    db_session.add_all([platform_user, school, plan, band_small, band_medium])
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=12000),
        PlanBandPrice(plan_id=plan.id, student_band_id=band_medium.id, price_cents=26000),
    ])
    db_session.execute(
        text(
            "INSERT INTO studentinfo (AdmNo, blocked, school_id) VALUES (:admno, :blocked, :school_id)"
        ),
        [
            {'admno': 'R100', 'blocked': 'NO', 'school_id': school.id},
            {'admno': 'R200', 'blocked': 'NO', 'school_id': school.id},
            {'admno': 'R300', 'blocked': 'NO', 'school_id': school.id},
        ],
    )
    db_session.execute(
        text(
            "INSERT INTO class_allocation (student_id, school_id, is_current) VALUES (:student_id, :school_id, :is_current)"
        ),
        [
            {'student_id': 'R100', 'school_id': school.id, 'is_current': 1},
            {'student_id': 'R200', 'school_id': school.id, 'is_current': 1},
            {'student_id': 'R300', 'school_id': school.id, 'is_current': 1},
        ],
    )
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        f'/platform/schools/{school.id}/assign-plan',
        data={'plan_id': str(plan.id)},
        follow_redirects=False,
    )

    assert response.status_code == 302
    subscription = Subscription.query.filter_by(school_id=school.id).order_by(Subscription.id.desc()).first()
    assert subscription is not None
    assert subscription.amount_cents == 26000
    assert subscription.billing_meta['student_count'] == 3
    assert subscription.billing_meta['student_count_source'] == 'students_module'
    assert subscription.billing_meta['student_band_label'] == 'school-live-count-medium'


def test_school_detail_shows_cancellation_reason_in_enforcement_timeline(client, db_session):
    platform_user = PlatformUser(
        email='timeline-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='Timeline Academy', code='TLA1', is_active=True)
    plan = Plan(name='Timeline Plan', price_cents=18000, billing_period='monthly')
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    subscription = Subscription(school_id=school.id, plan_id=plan.id, status='active', amount_cents=plan.price_cents, billing_cycle=plan.billing_period)
    db_session.add(subscription)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    cancel_response = client.post(
        f'/platform/subscriptions/{subscription.id}/cancel',
        data={'school_id': str(school.id), 'reason_code': 'tenant_offboarded', 'reason': 'Tenant offboarded after consolidation'},
        follow_redirects=False,
    )

    assert cancel_response.status_code == 302
    db_session.refresh(subscription)
    assert subscription.billing_meta['cancellation_reason'] == 'Tenant offboarded after consolidation'
    assert subscription.billing_meta['cancellation_reason_code'] == 'tenant_offboarded'

    page_response = client.get(f'/platform/schools/{school.id}')

    assert page_response.status_code == 200
    assert b'Tenant offboarded after consolidation' in page_response.data
    assert b'Tenant offboarded' in page_response.data
    assert b'subscription_cancelled' in page_response.data


def test_subscriptions_list_filters_by_reason_code(client, db_session):
    platform_user = PlatformUser(
        email='filter-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school_a = School(name='Filter A', code='FLA1', is_active=True)
    school_b = School(name='Filter B', code='FLB1', is_active=True)
    plan = Plan(name='Filter Plan', price_cents=15000, billing_period='monthly')
    db_session.add_all([platform_user, school_a, school_b, plan])
    db_session.flush()
    sub_a = Subscription(
        school_id=school_a.id,
        plan_id=plan.id,
        status='suspended',
        amount_cents=plan.price_cents,
        billing_cycle=plan.billing_period,
        billing_meta={'suspension_reason_code': 'billing_delinquency', 'suspension_reason': 'Late payment'},
    )
    sub_b = Subscription(
        school_id=school_b.id,
        plan_id=plan.id,
        status='cancelled',
        amount_cents=plan.price_cents,
        billing_cycle=plan.billing_period,
        billing_meta={'cancellation_reason_code': 'duplicate_account', 'cancellation_reason': 'Duplicate tenant'},
    )
    db_session.add_all([sub_a, sub_b])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/subscriptions?reason_code=billing_delinquency')

    assert response.status_code == 200
    assert b'Filter A' in response.data
    assert b'Late payment' in response.data
    assert b'Filter B' not in response.data


def test_subscriptions_list_filters_by_missing_module_code(client, db_session):
    platform_user = PlatformUser(
        email='missing-module-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school_a = School(name='Missing Fees School', code='MFS1', is_active=True)
    school_b = School(name='Has Fees School', code='HFS1', is_active=True)
    plan_a = Plan(name='Students Only Plan', price_cents=12000, billing_period='monthly', features={'modules': ['students']})
    plan_b = Plan(name='Fees Enabled Plan', price_cents=18000, billing_period='monthly', features={'modules': ['students', 'fees']})
    db_session.add_all([platform_user, school_a, school_b, plan_a, plan_b])
    db_session.flush()
    db_session.add_all([
        Subscription(school_id=school_a.id, plan_id=plan_a.id, status='active', amount_cents=plan_a.price_cents, billing_cycle=plan_a.billing_period),
        Subscription(school_id=school_b.id, plan_id=plan_b.id, status='active', amount_cents=plan_b.price_cents, billing_cycle=plan_b.billing_period),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/subscriptions?missing_module_code=fees')

    assert response.status_code == 200
    assert b'Missing Fees School' in response.data
    assert b'Has Fees School' not in response.data


def test_subscriptions_list_filters_by_included_module_code_and_marks_unconfigured_entitlements(client, db_session):
    platform_user = PlatformUser(
        email='included-module-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school_a = School(name='Configured Fees School', code='CFS1', is_active=True)
    school_b = School(name='Configured Students School', code='CSS1', is_active=True)
    school_c = School(name='Legacy Entitlement School', code='LES1', is_active=True)
    plan_a = Plan(name='Configured Fees Plan', price_cents=18000, billing_period='monthly', features={'modules': ['students', 'fees']})
    plan_b = Plan(name='Configured Students Plan', price_cents=12000, billing_period='monthly', features={'modules': ['students']})
    plan_c = Plan(name='Legacy Plan', price_cents=9000, billing_period='monthly')
    db_session.add_all([platform_user, school_a, school_b, school_c, plan_a, plan_b, plan_c])
    db_session.flush()
    db_session.add_all([
        Subscription(school_id=school_a.id, plan_id=plan_a.id, status='active', amount_cents=plan_a.price_cents, billing_cycle=plan_a.billing_period),
        Subscription(school_id=school_b.id, plan_id=plan_b.id, status='active', amount_cents=plan_b.price_cents, billing_cycle=plan_b.billing_period),
        Subscription(school_id=school_c.id, plan_id=plan_c.id, status='active', amount_cents=plan_c.price_cents, billing_cycle=plan_c.billing_period),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    filtered_response = client.get('/platform/subscriptions?included_module_code=fees')
    unconfigured_response = client.get('/platform/subscriptions?entitlement_state=unconfigured')
    list_response = client.get('/platform/subscriptions')

    assert filtered_response.status_code == 200
    assert b'Configured Fees School' in filtered_response.data
    assert b'Configured Students School' not in filtered_response.data
    assert b'Legacy Entitlement School' not in filtered_response.data

    assert unconfigured_response.status_code == 200
    assert b'Legacy Entitlement School' in unconfigured_response.data
    assert b'Configured Fees School' not in unconfigured_response.data

    assert list_response.status_code == 200
    assert b'Unconfigured Entitlement' in list_response.data
    assert b'Read Only' in list_response.data
    assert b'Read / Write' in list_response.data


def test_subscriptions_list_surfaces_entitlement_snapshot(client, db_session):
    platform_user = PlatformUser(
        email='subscription-list-entitlement-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Subscription Snapshot School', code='SSS1', is_active=True)
    plan = Plan(name='Subscription Snapshot Plan', price_cents=17000, billing_period='monthly', features={'modules': ['fees', 'finance']})
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    subscription = Subscription(school_id=school.id, plan_id=plan.id, status='active', amount_cents=plan.price_cents, billing_cycle=plan.billing_period)
    db_session.add(subscription)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/subscriptions')

    assert response.status_code == 200
    assert b'Subscription Snapshot School' in response.data
    assert b'Fees Collection And Management' in response.data
    assert b'Financial Accounting' in response.data
    assert b'Accounting Core' in response.data


def test_subscriptions_export_includes_reason_and_actor_metadata(client, db_session):
    platform_user = PlatformUser(
        email='billing-reviewer@example.com',
        name='Billing Reviewer',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Billing Review School', code='BRS1', is_active=True)
    plan = Plan(name='Billing Review Plan', price_cents=17000, billing_period='monthly')
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    subscription = Subscription(
        school_id=school.id,
        plan_id=plan.id,
        status='suspended',
        amount_cents=plan.price_cents,
        billing_cycle=plan.billing_period,
        billing_meta={
            'suspension_reason_code': 'billing_delinquency',
            'suspension_reason': 'Invoice aged beyond grace period',
        },
    )
    db_session.add(subscription)
    db_session.flush()
    db_session.add(
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_suspended',
            target_table='subscriptions',
            target_id=str(subscription.id),
            school_id=school.id,
            changes={
                'suspension_reason_code': 'billing_delinquency',
                'suspension_reason': 'Invoice aged beyond grace period',
            },
            created_at=datetime(2026, 4, 3, 9, 30, 0),
        )
    )
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/subscriptions/export?reason_code=billing_delinquency')

    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('text/csv')
    assert response.headers['Content-Disposition'] == 'attachment; filename=subscriptions-billing-review.csv'
    csv_text = response.data.decode('utf-8')
    assert 'subscription_id,school_name,school_code,plan_name,status,effective_status,billing_cycle,amount_cents,entitlement_access_mode,entitled_module_codes,read_module_codes,write_module_codes,reason_code,reason_label,reason_text,actor_name,actor_email,actor_role,audit_action,audit_created_at,started_at,renewal_date,trial_ends_at,grace_period_ends_at,ended_at' in csv_text
    assert 'Billing Review School,BRS1,Billing Review Plan,suspended,suspended,monthly,17000,unconfigured' in csv_text
    assert 'billing_delinquency,Billing delinquency,Invoice aged beyond grace period' in csv_text
    assert 'Billing Reviewer,billing-reviewer@example.com,platform_admin,subscription_suspended,2026-04-03T09:30:00' in csv_text


def test_subscriptions_export_honors_missing_module_filter_and_includes_entitlement_summary(client, db_session):
    platform_user = PlatformUser(
        email='export-missing-module-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school_a = School(name='CSV Missing Fees', code='CMF1', is_active=True)
    school_b = School(name='CSV Has Fees', code='CHF1', is_active=True)
    plan_a = Plan(name='CSV Students Only', price_cents=10000, billing_period='monthly', features={'modules': ['students']})
    plan_b = Plan(name='CSV Combined', price_cents=20000, billing_period='monthly', features={'modules': ['students', 'fees']})
    db_session.add_all([platform_user, school_a, school_b, plan_a, plan_b])
    db_session.flush()
    db_session.add_all([
        Subscription(school_id=school_a.id, plan_id=plan_a.id, status='active', amount_cents=plan_a.price_cents, billing_cycle=plan_a.billing_period),
        Subscription(school_id=school_b.id, plan_id=plan_b.id, status='active', amount_cents=plan_b.price_cents, billing_cycle=plan_b.billing_period),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/subscriptions/export?missing_module_code=fees')

    assert response.status_code == 200
    csv_text = response.data.decode('utf-8')
    assert 'CSV Missing Fees' in csv_text
    assert 'CSV Has Fees' not in csv_text
    assert 'read_write,students,students,students' in csv_text


def test_platform_audit_page_filters_by_reason_code_and_exports_filtered_csv(client, db_session):
    platform_user = PlatformUser(
        email='reason-auditor@example.com',
        name='Reason Auditor',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Reason Filter School', code='RFS1')
    db_session.add_all([platform_user, school])
    db_session.flush()
    db_session.add_all([
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_suspended',
            target_table='subscriptions',
            target_id='501',
            school_id=school.id,
            changes={
                'suspension_reason_code': 'billing_delinquency',
                'suspension_reason': 'Past due invoice',
            },
            created_at=datetime(2026, 4, 2, 12, 0, 0),
        ),
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_cancelled',
            target_table='subscriptions',
            target_id='502',
            school_id=school.id,
            changes={
                'cancellation_reason_code': 'duplicate_account',
                'cancellation_reason': 'Merged tenant record',
            },
            created_at=datetime(2026, 4, 3, 12, 0, 0),
        ),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    page_response = client.get('/platform/audit?reason_code=billing_delinquency')
    csv_response = client.get('/platform/audit/export?reason_code=billing_delinquency')

    assert page_response.status_code == 200
    assert b'Reason Code' in page_response.data
    assert b'Billing delinquency' in page_response.data
    assert b'Past due invoice' in page_response.data
    assert b'Merged tenant record' not in page_response.data

    assert csv_response.status_code == 200
    csv_text = csv_response.data.decode('utf-8')
    assert 'subscription_suspended' in csv_text
    assert 'billing_delinquency' in csv_text
    assert 'duplicate_account' not in csv_text


def test_subscription_detail_keeps_operator_on_detail_page_after_actions(client, db_session):
    platform_user = PlatformUser(
        email='detail-workflow-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='Detail Workflow Academy', code='DWA1', is_active=True)
    plan_a = Plan(name='Starter Detail', price_cents=10000, billing_period='monthly')
    plan_b = Plan(name='Growth Detail', price_cents=20000, billing_period='annual')
    db_session.add_all([platform_user, school, plan_a, plan_b])
    db_session.flush()
    subscription = Subscription(school_id=school.id, plan_id=plan_a.id, status='active', amount_cents=plan_a.price_cents, billing_cycle=plan_a.billing_period)
    db_session.add(subscription)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        f'/platform/subscriptions/{subscription.id}/change-plan',
        data={'plan_id': str(plan_b.id), 'return_subscription_id': str(subscription.id)},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith(f'/platform/subscriptions/{subscription.id}')


def test_platform_subscription_detail_surfaces_entitled_module_names(client, db_session):
    platform_user = PlatformUser(
        email='entitlement-subscription-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Subscription Entitlement School', code='SES1', is_active=True)
    plan = Plan(name='Subscription Entitlement Plan', price_cents=20000, billing_period='monthly', features={'modules': ['fees', 'finance']})
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    module_fees = ModuleCatalog.query.filter_by(code='fees').first() or ModuleCatalog(code='fees', name='Fees Collection And Management', family='accounting', is_core=True, sort_order=10)
    module_finance = ModuleCatalog.query.filter_by(code='finance').first() or ModuleCatalog(code='finance', name='Financial Accounting', family='accounting', is_core=True, sort_order=20)
    if module_fees.id is None:
        db_session.add(module_fees)
    if module_finance.id is None:
        db_session.add(module_finance)
    subscription = Subscription(school_id=school.id, plan_id=plan.id, status='active', amount_cents=20000, billing_cycle='monthly')
    db_session.add(subscription)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get(f'/platform/subscriptions/{subscription.id}')

    assert response.status_code == 200
    assert b'Entitled Modules' in response.data
    assert b'Fees Collection And Management' in response.data
    assert b'Financial Accounting' in response.data
    assert b'Accounting Core' in response.data
    assert b'Full Access' in response.data
    assert b'Read / Write' in response.data


def test_subscription_detail_change_plan_uses_student_band_pricing(client, db_session):
    from platform_bp.models import PlanBandPrice, StudentBand

    platform_user = PlatformUser(
        email='subscription-band-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='Subscription Band Academy', code='SUBB1', is_active=True)
    plan_a = Plan(name='Subscription Starter', price_cents=10000, billing_period='monthly')
    plan_b = Plan(name='Subscription Growth', price_cents=18000, billing_period='annual')
    band_small = StudentBand(label='subscription-band-small', min_students=1, max_students=300, sort_order=10)
    band_large = StudentBand(label='subscription-band-large', min_students=301, max_students=900, sort_order=20)
    db_session.add_all([platform_user, school, plan_a, plan_b, band_small, band_large])
    db_session.flush()
    subscription = Subscription(
        school_id=school.id,
        plan_id=plan_a.id,
        status='active',
        amount_cents=plan_a.price_cents,
        billing_cycle=plan_a.billing_period,
        billing_meta={'student_count': 120, 'student_band_label': 'subscription-band-small', 'student_band_id': band_small.id},
    )
    db_session.add(subscription)
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan_b.id, student_band_id=band_small.id, price_cents=18000),
        PlanBandPrice(plan_id=plan_b.id, student_band_id=band_large.id, price_cents=32000),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        f'/platform/subscriptions/{subscription.id}/change-plan',
        data={
            'plan_id': str(plan_b.id),
            'student_count': '640',
            'return_subscription_id': str(subscription.id),
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith(f'/platform/subscriptions/{subscription.id}')

    db_session.refresh(subscription)
    assert subscription.plan_id == plan_b.id
    assert subscription.amount_cents == 32000
    assert subscription.billing_cycle == plan_b.billing_period
    assert subscription.billing_meta['student_count'] == 640
    assert subscription.billing_meta['student_band_label'] == 'subscription-band-large'


def test_platform_tenant_user_search_returns_matching_users(client, db_session):
    platform_user = PlatformUser(
        email='tenant-search-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Tenant Search School', code='TSS1')
    db_session.add_all([platform_user, school])
    db_session.flush()
    db_session.add_all([
        User(username='teacher1', StaffID='T001', pwd='plain-pass', access_flag=1, school_id=school.id),
        User(username='driver1', StaffID='D001', pwd='plain-pass', access_flag=1, school_id=school.id),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/tenant-users/search?q=teacher1')

    assert response.status_code == 200
    assert b'Tenant User Search' in response.data
    assert b'teacher1' in response.data
    assert b'driver1' not in response.data


def test_platform_dashboard_shows_metrics_cards(client, db_session):
    platform_user = PlatformUser(
        email='dashboard-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school_a = School(name='Alpha Metrics Academy', code='AMA1', is_active=True, subscription_status='active')
    school_b = School(name='Beta Metrics Academy', code='BMA1', is_active=False, subscription_status='trial')
    plan = Plan(name='Growth Dashboard Metrics Plan', price_cents=250000, billing_period='monthly')
    db_session.add_all([platform_user, school_a, school_b, plan])
    db_session.flush()

    db_session.add_all([
        Subscription(school_id=school_a.id, plan_id=plan.id, status='active', amount_cents=250000),
        Subscription(school_id=school_b.id, plan_id=plan.id, status='suspended', amount_cents=250000),
        SupportTicket(school_id=school_a.id, raised_by_email='ops@example.com', subject='Need help', description='Issue', status='open'),
        AuditLog(actor_user_id=platform_user.id, actor_platform=True, action='subscription_activated', target_table='subscriptions', target_id='1', school_id=school_a.id),
        AuditLog(actor_user_id=None, actor_platform=True, action='platform_login_failed', target_table='platform_users', target_id=None, school_id=None, changes={'email': 'blocked@example.com'}, ip='10.10.10.10'),
        AuditLog(actor_user_id=platform_user.id, actor_platform=True, action='impersonation_start', target_table='users', target_id='123', school_id=school_a.id, changes={'impersonated_by': platform_user.id}, ip='10.10.10.20'),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/')

    assert response.status_code == 200
    assert b'Control Plane' in response.data
    assert b'Portfolio Watch' in response.data
    assert b'Platform Dashboard' in response.data
    assert b'Total Schools' in response.data
    assert b'Open Support Tickets' in response.data
    assert b'Subscription Health' in response.data
    assert b'active' in response.data
    assert b'suspended' in response.data
    assert b'Support Snapshot' in response.data
    assert b'Open support queue' in response.data
    assert b'Security Signals' in response.data
    assert b'Failed Platform Logins' in response.data
    assert b'Recent Alert Feed' in response.data
    assert b'platform login failed' in response.data
    assert b'impersonation start' in response.data
    assert b'Alpha Metrics Academy' in response.data
    assert b'Beta Metrics Academy' in response.data


def test_platform_metrics_endpoints_return_summary_and_trends(client, db_session):
    platform_user = PlatformUser(
        email='metrics-api@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Metrics API School', code='MAP1')
    plan = Plan(name='Metrics API Plan', price_cents=12000, billing_period='monthly')
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    db_session.add_all([
        Subscription(school_id=school.id, plan_id=plan.id, status='active', amount_cents=12000),
        SupportTicket(school_id=school.id, raised_by_email='metrics@example.com', subject='Metric', description='Need report', status='open'),
        AuditLog(actor_user_id=platform_user.id, actor_platform=True, action='support_ticket_created', target_table='support_tickets', target_id='1', school_id=school.id),
        AuditLog(actor_user_id=None, actor_platform=True, action='platform_login_failed', target_table='platform_users', target_id=None, school_id=None, changes={'email': 'metrics@example.com'}, ip='172.16.0.10'),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    summary_response = client.get('/platform/metrics/summary?window_days=14')
    trends_response = client.get('/platform/metrics/trends?window_days=30')

    assert summary_response.status_code == 200
    summary_payload = summary_response.get_json()
    assert 'metrics_cards' in summary_payload
    assert any(card['label'] == 'Total Schools' for card in summary_payload['metrics_cards'])
    assert summary_payload['recent_school_rows'][0]['school']['name'] == 'Metrics API School'
    assert summary_payload['security_alerts']['failed_login_count'] >= 1

    assert trends_response.status_code == 200
    trends_payload = trends_response.get_json()
    assert trends_payload['window_days'] == 30
    assert trends_payload['support_tickets_created'] >= 1
    assert len(trends_payload['labels']) == len(trends_payload['series']['schools_created'])
    assert len(trends_payload['labels']) == len(trends_payload['series']['subscriptions_started'])
    assert len(trends_payload['labels']) == len(trends_payload['series']['support_tickets_created'])
    assert len(trends_payload['labels']) == len(trends_payload['series']['audit_events'])


def test_platform_support_ticket_workflow_updates_assignment_status_and_audit(client, db_session):
    platform_user = PlatformUser(
        email='support-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    support_user = PlatformUser(
        email='queue-owner@example.com',
        password_hash=generate_password_hash('secret123'),
        role='support',
        name='Queue Owner',
    )
    school = School(name='Support Workflow School', code='SWF1')
    db_session.add_all([platform_user, support_user, school])
    db_session.flush()
    ticket = SupportTicket(
        school_id=school.id,
        raised_by_email='family@example.com',
        subject='Portal issue',
        description='Cannot log in',
        status='open',
    )
    db_session.add(ticket)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    assign_response = client.post(
        f'/platform/support/{ticket.id}/assign',
        data={'assigned_to_user_id': str(support_user.id)},
        follow_redirects=False,
    )
    status_response = client.post(
        f'/platform/support/{ticket.id}/status',
        data={'status': 'closed'},
        follow_redirects=False,
    )
    list_response = client.get('/platform/support')

    assert assign_response.status_code == 302
    assert status_response.status_code == 302
    db_session.refresh(ticket)
    assert ticket.assigned_to_user_id == support_user.id
    assert ticket.status == 'closed'
    assert list_response.status_code == 200
    assert b'Portal issue' in list_response.data
    assert b'Queue Owner' in list_response.data
    assert b'closed' in list_response.data

    audit_actions = [entry.action for entry in AuditLog.query.filter_by(target_table='support_tickets', target_id=str(ticket.id)).order_by(AuditLog.id.asc()).all()]
    assert 'support_ticket_assigned' in audit_actions
    assert 'support_ticket_status_updated' in audit_actions


def test_platform_support_queue_filters_and_paginates(client, db_session):
    platform_user = PlatformUser(
        email='support-pager@example.com',
        name='Support Pager Admin',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    support_user = PlatformUser(
        email='support-owner@example.com',
        name='Support Owner',
        password_hash=generate_password_hash('secret123'),
        role='support',
    )
    alpha_school = School(name='Alpha Queue School', code='AQS1')
    beta_school = School(name='Beta Queue School', code='BQS1')
    db_session.add_all([platform_user, support_user, alpha_school, beta_school])
    db_session.flush()

    db_session.add_all([
        SupportTicket(
            school_id=alpha_school.id,
            raised_by_email=f'alpha-{index}@example.com',
            subject=f'Billing issue {index:02d}',
            description='Need invoice help',
            status='open',
            created_at=datetime(2026, 4, 2, 9, 0, 0),
        )
        for index in range(27)
    ])
    db_session.add(
        SupportTicket(
            school_id=beta_school.id,
            raised_by_email='beta@example.com',
            subject='Resolved transport question',
            description='Closed already',
            status='closed',
            assigned_to_user_id=support_user.id,
            created_at=datetime(2026, 4, 3, 10, 0, 0),
        )
    )
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    page_one = client.get(f'/platform/support?school_id={alpha_school.id}&status=open&search=Billing&page=1&page_size=10')
    page_two = client.get(f'/platform/support?school_id={alpha_school.id}&status=open&search=Billing&page=2&page_size=10')
    persisted_page = client.get(f'/platform/support?school_id={alpha_school.id}&status=open&search=Billing&page=2')
    filtered_assignment = client.get(f'/platform/support?school_id={beta_school.id}&status=closed&assignment={support_user.id}&search=transport')

    assert page_one.status_code == 200
    assert b'Showing 1-10 of 27 support tickets' in page_one.data
    assert b'Page 1 of 3' in page_one.data
    assert b'Billing issue 00' not in page_one.data
    assert b'page_size=10' in page_one.data
    assert b'Resolved transport question' not in page_one.data

    assert page_two.status_code == 200
    assert b'Showing 11-20 of 27 support tickets' in page_two.data
    assert b'Billing issue 16' in page_two.data

    assert persisted_page.status_code == 200
    assert b'Saved page size: 10' in persisted_page.data
    assert b'title="Using saved preference for support queue page size"' in persisted_page.data
    assert b'Reset View Preferences' in persisted_page.data

    assert filtered_assignment.status_code == 200
    assert b'Resolved transport question' in filtered_assignment.data
    assert b'Support Owner' in filtered_assignment.data
    assert b'Billing issue' not in filtered_assignment.data


def test_platform_plan_create_and_edit_workflow(client, db_session):
    from platform_bp.models import StudentBand

    created_plan_name = 'Operations Plan Workflow'
    updated_plan_name = 'Operations Plus Workflow'

    platform_user = PlatformUser(
        email='plans-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add(platform_user)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    create_page = client.get('/platform/plans/create')
    student_bands = StudentBand.query.order_by(StudentBand.sort_order.asc()).all()
    create_band_prices = {
        f'band_price_{band.id}': f"{49.99 + (index * 30):.2f}"
        for index, band in enumerate(student_bands)
    }
    create_response = client.post(
        '/platform/plans/create',
        data={
            'name': created_plan_name,
            'billing_period': 'monthly',
            'bundle_family': 'combined',
            'module_codes': ['students', 'classes', 'fees', 'finance', 'fleet_transport'],
            **create_band_prices,
        },
        follow_redirects=False,
    )

    assert create_page.status_code == 200
    assert b'Create Plan' in create_page.data
    assert b'Student Band Pricing' in create_page.data
    assert b'Current bundle label' in create_page.data
    assert b'Academic Core' in create_page.data
    assert b'Operations Add-On' in create_page.data
    assert create_response.status_code == 302

    plan = Plan.query.filter_by(name=created_plan_name).first()
    assert plan is not None
    assert plan.price_cents == 4999
    assert plan.bundle_family == 'combined'
    assert plan.features['modules'] == ['students', 'classes', 'fees', 'finance', 'fleet_transport']
    first_band = student_bands[0]
    assert plan.features['band_prices'][first_band.label] == 4999

    edit_page = client.get(f'/platform/plans/{plan.id}/edit')
    edit_band_prices = {
        f'band_price_{band.id}': f"{79.50 + (index * 20):.2f}"
        for index, band in enumerate(student_bands)
    }
    edit_response = client.post(
        f'/platform/plans/{plan.id}/edit',
        data={
            'name': updated_plan_name,
            'billing_period': 'annual',
            'bundle_family': 'academic',
            'module_codes': ['students', 'classes', 'exams', 'attendance', 'inventory_uniform'],
            **edit_band_prices,
        },
        follow_redirects=False,
    )

    assert edit_page.status_code == 200
    assert b'Edit Plan' in edit_page.data
    assert edit_response.status_code == 302

    db_session.refresh(plan)
    assert plan.name == updated_plan_name
    assert plan.price_cents == 7950
    assert plan.billing_period == 'annual'
    assert plan.bundle_family == 'academic'
    assert plan.features['modules'] == ['students', 'classes', 'exams', 'attendance', 'inventory_uniform']
    highest_band = student_bands[-1]
    expected_highest_band_price = int(round((79.50 + ((len(student_bands) - 1) * 20)) * 100))
    assert plan.features['band_prices'][highest_band.label] == expected_highest_band_price

    plans_page = client.get('/platform/plans')
    assert plans_page.status_code == 200
    assert updated_plan_name.encode() in plans_page.data
    assert b'Edit' in plans_page.data
    assert b'1-300' in plans_page.data
    assert b'Academic Bundle' in plans_page.data
    assert b'Operations Add-On' in plans_page.data

    audit_actions = [
        entry.action
        for entry in AuditLog.query.filter_by(target_table='plans', target_id=str(plan.id)).order_by(AuditLog.id.asc()).all()
    ]
    assert audit_actions == ['plan_created', 'plan_updated']


def test_platform_dashboard_surfaces_registry_labeled_entitlement_metrics(client, db_session):
    platform_user = PlatformUser(
        email='dashboard-entitlement-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    configured_school = School(name='Dashboard Configured School', code='DCS1', is_active=True)
    unconfigured_school = School(name='Dashboard Legacy School', code='DLS1', is_active=True)
    configured_plan = Plan(name='Dashboard Configured Plan', price_cents=12000, billing_period='monthly', features={'modules': ['fees', 'finance']})
    legacy_plan = Plan(name='Dashboard Legacy Plan', price_cents=9000, billing_period='monthly')
    db_session.add_all([platform_user, configured_school, unconfigured_school, configured_plan, legacy_plan])
    db_session.flush()
    db_session.add_all([
        Subscription(school_id=configured_school.id, plan_id=configured_plan.id, status='active', amount_cents=configured_plan.price_cents, billing_cycle=configured_plan.billing_period),
        Subscription(school_id=unconfigured_school.id, plan_id=legacy_plan.id, status='active', amount_cents=legacy_plan.price_cents, billing_cycle=legacy_plan.billing_period),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/')

    assert response.status_code == 200
    assert b'Entitlement Mix' in response.data
    assert b'Module Adoption' in response.data
    assert b'Fees Collection And Management' in response.data
    assert b'Accounting Core' in response.data
    assert b'Unconfigured' in response.data


def test_platform_plan_create_rejects_missing_band_price(client, db_session):
    from platform_bp.models import StudentBand

    platform_user = PlatformUser(
        email='plans-validation@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add(platform_user)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)
    client.get('/platform/plans/create')
    student_bands = StudentBand.query.order_by(StudentBand.sort_order.asc()).all()

    response = client.post(
        '/platform/plans/create',
        data={
            'name': 'Broken Plan',
            'billing_period': 'monthly',
            'bundle_family': 'academic',
            'module_codes': ['students'],
            f'band_price_{student_bands[0].id}': '10.00',
            f'band_price_{student_bands[1].id}': '20.00',
            f'band_price_{student_bands[2].id}': '30.00',
            f'band_price_{student_bands[3].id}': '',
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Price is required.' in response.data
    assert Plan.query.filter_by(name='Broken Plan').first() is None


def test_platform_plan_listing_bootstraps_missing_pricing_schema(client, db_session):
    from sqlalchemy import inspect, text

    platform_user = PlatformUser(
        email='plans-bootstrap@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add(platform_user)
    db_session.add(Plan(name='Legacy Plan Bootstrap', price_cents=2500, billing_period='monthly'))
    db_session.commit()

    engine = db_session.get_bind()
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE IF EXISTS plan_band_prices'))
        connection.execute(text('DROP TABLE IF EXISTS plan_modules'))
        connection.execute(text('DROP TABLE IF EXISTS student_bands'))
        connection.execute(text('DROP TABLE IF EXISTS module_catalog'))
        connection.execute(text('DROP INDEX IF EXISTS ix_plans_bundle_family'))
        connection.execute(text('ALTER TABLE plans DROP COLUMN bundle_family'))
        connection.execute(text('ALTER TABLE plans DROP COLUMN pricing_model'))

    _login_platform_admin(client, platform_user.id)
    response = client.get('/platform/plans')

    assert response.status_code == 200
    assert b'Legacy Plan Bootstrap' in response.data

    inspector = inspect(engine)
    plan_columns = {column['name'] for column in inspector.get_columns('plans')}
    assert 'bundle_family' in plan_columns
    assert 'pricing_model' in plan_columns
    assert inspector.has_table('module_catalog') is True
    assert inspector.has_table('student_bands') is True
    assert inspector.has_table('plan_modules') is True
    assert inspector.has_table('plan_band_prices') is True


def test_platform_dashboard_renders_chart_surfaces(client, db_session):
    platform_user = PlatformUser(
        email='chart-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Chart Surface School', code='CHS1')
    plan = Plan(name='Chart Surface Metrics Plan', price_cents=5000, billing_period='monthly')
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    db_session.add_all([
        Subscription(school_id=school.id, plan_id=plan.id, status='active', amount_cents=5000),
        SupportTicket(school_id=school.id, raised_by_email='chart@example.com', subject='Chart test', description='Queue item', status='open'),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/?window_days=14')

    assert response.status_code == 200
    assert b'Activity Trends' in response.data
    assert b'Tenant Mix' in response.data
    assert b'data-platform-trends' in response.data
    assert b'data-platform-mix' in response.data
    assert b'/platform/metrics/summary?window_days=14' in response.data
    assert b'/platform/metrics/trends?window_days=14' in response.data


def test_platform_login_invalid_credentials_shows_error_flash(client, db_session):
    db_session.add(
        PlatformUser(
            email='platform-admin-invalid@example.com',
            password_hash=generate_password_hash('secret123'),
            role='platform_admin',
        )
    )
    db_session.commit()

    response = client.post(
        '/platform/login',
        data={'email': 'platform-admin-invalid@example.com', 'password': 'wrong-pass'},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Invalid credentials' in response.data
    assert b'platform-toast' in response.data
    assert b'data-tone="error"' in response.data

    failed_login_event = AuditLog.query.filter_by(action='platform_login_failed').order_by(AuditLog.id.desc()).first()
    assert failed_login_event is not None
    assert failed_login_event.changes['email'] == 'platform-admin-invalid@example.com'


def test_platform_login_success_records_audit_event(client, db_session):
    user = PlatformUser(
        email='platform-success@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add(user)
    db_session.commit()

    response = client.post(
        '/platform/login',
        data={'email': 'platform-success@example.com', 'password': 'secret123'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    success_event = AuditLog.query.filter_by(action='platform_login_succeeded', target_id=str(user.id)).order_by(AuditLog.id.desc()).first()
    assert success_event is not None
    assert success_event.actor_user_id == user.id


def test_platform_login_rate_limit_and_lockout_create_security_event_and_support_ticket(client, db_session, app):
    app.config['PLATFORM_LOGIN_FAILURE_THRESHOLD'] = 3
    app.config['PLATFORM_LOGIN_FAILURE_WINDOW_MINUTES'] = 30
    app.config['PLATFORM_LOGIN_LOCKOUT_ENABLED'] = True
    app.config['PLATFORM_LOGIN_LOCKOUT_MINUTES'] = 20
    app.config['PLATFORM_SECURITY_AUTO_CREATE_SUPPORT_TICKETS'] = True

    user = PlatformUser(
        email='platform-lockout@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add(user)
    db_session.commit()

    for _ in range(3):
        response = client.post(
            '/platform/login',
            data={'email': 'platform-lockout@example.com', 'password': 'wrong-pass'},
            follow_redirects=True,
        )
        assert response.status_code == 200

    db_session.refresh(user)
    assert user.locked_until is not None
    assert user.failed_login_count >= 3

    blocked_response = client.post(
        '/platform/login',
        data={'email': 'platform-lockout@example.com', 'password': 'secret123'},
        follow_redirects=True,
    )

    assert blocked_response.status_code == 200
    assert b'Account temporarily locked due to repeated failed login attempts. Try again later.' in blocked_response.data

    security_event = SecurityEvent.query.filter_by(event_type='repeated_failed_platform_login').order_by(SecurityEvent.id.desc()).first()
    assert security_event is not None
    assert security_event.status == 'open'
    assert security_event.related_support_ticket_id is not None
    assert security_event.observed_value >= 3

    support_ticket = db_session.get(SupportTicket, security_event.related_support_ticket_id)
    assert support_ticket is not None
    assert support_ticket.subject.startswith('Security alert:')


def test_impersonation_burst_creates_security_event_and_support_ticket(client, db_session, app):
    app.config['PLATFORM_IMPERSONATION_ALERT_THRESHOLD'] = 2
    app.config['PLATFORM_IMPERSONATION_ALERT_WINDOW_MINUTES'] = 60
    app.config['PLATFORM_SECURITY_AUTO_CREATE_SUPPORT_TICKETS'] = True

    platform_user = PlatformUser(
        email='impersonator@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Signal School', code='SIG1')
    db_session.add_all([platform_user, school])
    db_session.flush()
    tenant_user = User(username='tenant-user', StaffID='T900', pwd='plain-pass', access_flag=1, school_id=school.id)
    db_session.add(tenant_user)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    for _ in range(2):
        start_response = client.post(
            '/platform/impersonate/start',
            data={'tenant_user_no': str(tenant_user.userNo)},
            follow_redirects=False,
        )
        assert start_response.status_code == 302
        stop_response = client.post('/platform/impersonate/stop', follow_redirects=False)
        assert stop_response.status_code == 302

    security_event = SecurityEvent.query.filter_by(event_type='platform_impersonation_burst').order_by(SecurityEvent.id.desc()).first()
    assert security_event is not None
    assert security_event.school_id == school.id
    assert security_event.related_support_ticket_id is not None
    assert security_event.observed_value >= 2


def test_platform_security_events_page_supports_filters_acknowledgement_and_csv(client, db_session):
    platform_user = PlatformUser(
        email='security-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='security',
    )
    school = School(name='Security School', code='SEC1')
    db_session.add_all([platform_user, school])
    db_session.flush()
    open_event = SecurityEvent(
        event_type='repeated_failed_platform_login',
        severity='high',
        status='open',
        title='Repeated failed platform login attempts',
        description='Too many failed attempts.',
        signal_key='platform-user:1',
        school_id=school.id,
        threshold_value=5,
        observed_value=7,
    )
    resolved_event = SecurityEvent(
        event_type='platform_impersonation_burst',
        severity='medium',
        status='resolved',
        title='Repeated impersonation activity detected',
        description='Impersonation threshold crossed.',
        signal_key='platform-user:2:school:1',
        school_id=school.id,
        threshold_value=3,
        observed_value=4,
    )
    db_session.add_all([open_event, resolved_event])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    page_response = client.get(f'/platform/security/events?school_id={school.id}&status=open')
    assert page_response.status_code == 200
    assert b'Platform Security Events' in page_response.data
    assert b'Repeated failed platform login attempts' in page_response.data
    assert b'Repeated impersonation activity detected' not in page_response.data
    assert b'Failed Login Threshold' in page_response.data

    acknowledge_response = client.post(
        f'/platform/security/events/{open_event.id}/acknowledge',
        data={'next': '/platform/security/events'},
        follow_redirects=False,
    )
    assert acknowledge_response.status_code == 302
    db_session.refresh(open_event)
    assert open_event.status == 'acknowledged'

    resolve_response = client.post(
        f'/platform/security/events/{open_event.id}/resolve',
        data={'next': '/platform/security/events'},
        follow_redirects=False,
    )
    assert resolve_response.status_code == 302
    db_session.refresh(open_event)
    assert open_event.status == 'resolved'

    csv_response = client.get(f'/platform/security/events/export?school_id={school.id}')
    assert csv_response.status_code == 200
    assert csv_response.headers['Content-Disposition'] == 'attachment; filename=platform-security-events.csv'
    csv_text = csv_response.data.decode('utf-8')
    assert 'created_at,last_seen_at,school_name,school_code,event_type,severity,status,title,threshold_value,observed_value' in csv_text
    assert 'Repeated failed platform login attempts' in csv_text


def test_high_severity_security_event_dispatches_notifications_with_throttling(db_session, app, monkeypatch):
    app.config['PLATFORM_SECURITY_NOTIFICATION_THROTTLE_MINUTES'] = 45
    email_calls = []
    webhook_calls = []

    def fake_send_email_alert(to_email, subject, body, from_email=None):
        email_calls.append({'to_email': to_email, 'subject': subject, 'body': body, 'from_email': from_email})
        return {'ok': True, 'status': 'sent', 'reason': 'smtp-ok'}

    def fake_send_webhook_alert(url, payload, secret_token=None, headers=None, timeout_seconds=10):
        webhook_calls.append({'url': url, 'payload': payload, 'secret_token': secret_token, 'headers': headers, 'timeout_seconds': timeout_seconds})
        return {'ok': True, 'status': 'sent', 'reason': 'webhook-ok', 'response_code': 202, 'response_body': 'accepted'}

    monkeypatch.setattr(security_service, 'send_email_alert', fake_send_email_alert)
    monkeypatch.setattr(security_service, 'send_webhook_alert', fake_send_webhook_alert)

    db_session.add_all([
        SecurityNotificationPreference(
            name='SOC inbox',
            channel='email',
            destination='soc@example.com',
            min_severity='high',
            throttle_minutes=60,
            enabled=True,
        ),
        SecurityNotificationPreference(
            name='SIEM webhook',
            channel='webhook',
            destination='https://hooks.example.test/security',
            min_severity='high',
            throttle_minutes=60,
            enabled=True,
            event_types=['repeated_failed_platform_login'],
            secret_token='secret-token',
        ),
    ])
    db_session.commit()

    event = security_service.create_or_update_security_event(
        event_type='repeated_failed_platform_login',
        signal_key='platform-user:44',
        severity='high',
        title='Repeated failed platform login attempts',
        description='Observed repeated failures.',
        threshold_value=3,
        observed_value=5,
        details={'email': 'soc@example.com'},
        auto_create_ticket=False,
    )

    assert len(email_calls) == 1
    assert len(webhook_calls) == 1
    sent_deliveries = SecurityNotificationDelivery.query.filter_by(security_event_id=event.id, status='sent').all()
    assert len(sent_deliveries) == 2

    security_service.create_or_update_security_event(
        event_type='repeated_failed_platform_login',
        signal_key='platform-user:44',
        severity='critical',
        title='Repeated failed platform login attempts',
        description='Observed repeated failures again.',
        threshold_value=3,
        observed_value=7,
        details={'email': 'soc@example.com'},
        auto_create_ticket=False,
    )

    assert len(email_calls) == 1
    assert len(webhook_calls) == 1
    throttled_deliveries = SecurityNotificationDelivery.query.filter_by(security_event_id=event.id, status='throttled').all()
    assert len(throttled_deliveries) == 2


def test_send_email_alert_uses_implicit_ssl_for_port_465(monkeypatch):
    calls = []

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout=10):
            calls.append(('smtp_ssl_init', host, port, timeout))

        def ehlo(self):
            calls.append(('ehlo',))

        def login(self, user, password):
            calls.append(('login', user, password))

        def send_message(self, message):
            calls.append(('send_message', message['To'], message['Subject']))

        def quit(self):
            calls.append(('quit',))

    def fail_plain_smtp(*args, **kwargs):
        raise AssertionError('Plain SMTP should not be used for implicit SSL configuration')

    monkeypatch.setenv('SMTP_HOST', 'mail.enmail.co')
    monkeypatch.setenv('SMTP_PORT', '465')
    monkeypatch.setenv('SMTP_USE_SSL', '1')
    monkeypatch.setenv('SMTP_USER', 'info@concoctsystem.com')
    monkeypatch.setenv('SMTP_PASS', 'secret-pass')
    monkeypatch.setattr(notification_service.smtplib, 'SMTP_SSL', FakeSMTPSSL)
    monkeypatch.setattr(notification_service.smtplib, 'SMTP', fail_plain_smtp)

    result = notification_service.send_email_alert(
        to_email='security@example.com',
        subject='Security alert',
        body='Body',
        from_email='info@concoctsystem.com',
    )

    assert result['ok'] is True
    assert ('smtp_ssl_init', 'mail.enmail.co', 465, 10) in calls
    assert any(call[0] == 'login' for call in calls)
    assert any(call[0] == 'send_message' for call in calls)


def test_send_webhook_alert_adds_hmac_signature_headers(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 202
        text = 'accepted'
        reason = 'Accepted'

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['kwargs'] = kwargs
        return FakeResponse()

    monkeypatch.setattr(notification_service.requests, 'post', fake_post)

    payload = {
        'event': {
            'id': 77,
            'event_type': 'platform_impersonation_burst',
            'severity': 'high',
        }
    }
    result = notification_service.send_webhook_alert(
        'https://relay.example.test/webhooks/platform/security',
        payload,
        secret_token='shared-secret',
        headers={'X-Custom-Header': 'present'},
        timeout_seconds=12,
    )

    headers = captured['kwargs']['headers']
    assert result['ok'] is True
    assert captured['url'] == 'https://relay.example.test/webhooks/platform/security'
    assert captured['kwargs']['timeout'] == 12
    assert 'data' in captured['kwargs']
    assert 'json' not in captured['kwargs']
    assert headers['X-Custom-Header'] == 'present'
    assert headers['X-Security-Webhook-Token'] == 'shared-secret'
    assert headers['X-Security-Webhook-Signature-Version'] == 'v1'
    assert headers['X-Security-Webhook-Signature'].startswith('sha256=')
    assert notification_service.verify_webhook_signature(
        captured['kwargs']['data'],
        'shared-secret',
        headers['X-Security-Webhook-Signature'],
        headers['X-Security-Webhook-Timestamp'],
    ) is True


def test_verify_webhook_signature_rejects_stale_or_invalid_values():
    signed = notification_service.build_webhook_signature({'event': {'id': 1}}, 'shared-secret', timestamp='1700000000')

    assert notification_service.verify_webhook_signature(
        signed['body'],
        'shared-secret',
        signed['signature'],
        signed['timestamp'],
        tolerance_seconds=60,
        current_time=1700000030,
    ) is True
    assert notification_service.verify_webhook_signature(
        signed['body'],
        'wrong-secret',
        signed['signature'],
        signed['timestamp'],
        tolerance_seconds=60,
        current_time=1700000030,
    ) is False
    assert notification_service.verify_webhook_signature(
        signed['body'],
        'shared-secret',
        signed['signature'],
        signed['timestamp'],
        tolerance_seconds=10,
        current_time=1700000030,
    ) is False


def test_platform_security_notification_preferences_can_be_managed_from_security_page(client, db_session):
    platform_user = PlatformUser(
        email='notify-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='security',
    )
    school = School(name='Notify School', code='NTF1')
    db_session.add_all([platform_user, school])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    create_response = client.post(
        '/platform/security/notifications/preferences',
        data={
            'name': 'SOC Webhook',
            'channel': 'webhook',
            'destination': 'https://hooks.example.test/siem',
            'min_severity': 'critical',
            'throttle_minutes': '90',
            'school_id': str(school.id),
            'event_types': 'platform_impersonation_burst',
            'secret_token': 'abc123',
            'enabled': 'on',
            'next': '/platform/security/events',
        },
        follow_redirects=False,
    )

    assert create_response.status_code == 302
    preference = SecurityNotificationPreference.query.order_by(SecurityNotificationPreference.id.desc()).first()
    assert preference is not None
    assert preference.channel == 'webhook'
    assert preference.destination == 'https://hooks.example.test/siem'
    assert preference.school_id == school.id
    assert preference.event_types == ['platform_impersonation_burst']
    assert preference.enabled is True

    page_response = client.get('/platform/security/events')
    assert page_response.status_code == 200
    assert b'Notification Preferences' in page_response.data
    assert b'SOC Webhook' in page_response.data
    assert b'Recent Notification Delivery' in page_response.data

    toggle_response = client.post(
        f'/platform/security/notifications/preferences/{preference.id}/toggle',
        data={'enabled': '0', 'next': '/platform/security/events'},
        follow_redirects=False,
    )
    assert toggle_response.status_code == 302
    db_session.refresh(preference)
    assert preference.enabled is False


def test_platform_security_events_page_shows_relay_status(client, db_session, monkeypatch):
    platform_user = PlatformUser(
        email='relay-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='security',
    )
    db_session.add(platform_user)
    db_session.commit()

    class FakeRelayResponse:
        status_code = 200
        headers = {'Content-Type': 'application/json'}

        def json(self):
            return {
                'ok': True,
                'forwarding_enabled': False,
                'warning': 'running but downstream SIEM forwarding is disabled',
                'destinations': {'splunk': False, 'sentinel': False},
            }

    monkeypatch.setattr('platform_bp.routes.security.requests.get', lambda *args, **kwargs: FakeRelayResponse())

    _login_platform_admin(client, platform_user.id)
    response = client.get('/platform/security/events')

    assert response.status_code == 200
    assert b'Security Relay Status' in response.data
    assert b'running but downstream SIEM forwarding is disabled' in response.data
    assert b'http://127.0.0.1:8080' in response.data


def test_flash_category_normalization_maps_aliases_to_supported_categories():
    assert normalize_flash_category('danger') == 'error'
    assert normalize_flash_category('success') == 'success'
    assert normalize_flash_category('unexpected') == 'info'
    assert normalize_flash_category(None) == 'info'


def test_suspended_school_session_is_blocked_from_tenant_routes(client, db_session):
    school = School(name='Suspended School', code='SUSP')
    db_session.add(school)
    db_session.flush()

    user = User(
        username='teacher1',
        pwd='plain-pass',
        access_flag=1,
        school_id=school.id,
    )
    db_session.add(user)
    db_session.add(
        Subscription(
            school_id=school.id,
            status='suspended',
        )
    )
    db_session.commit()

    with client.session_transaction() as session:
        session['userNo'] = user.userNo
        session['school_id'] = school.id
        session['username'] = 'teacher1'

    response = client.get('/', follow_redirects=False)

    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_platform_routes_bypass_school_subscription_block(client, db_session):
    school = School(name='Blocked Tenant', code='BLKD')
    platform_user = PlatformUser(
        email='support@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add_all([school, platform_user])
    db_session.commit()
    db_session.add(
        Subscription(school_id=school.id, status='suspended')
    )
    db_session.commit()

    with client.session_transaction() as session:
        session['platform_user_id'] = platform_user.id
        session['userNo'] = 77
        session['school_id'] = school.id

    response = client.get('/platform/schools')

    assert response.status_code == 200
    assert b'Blocked Tenant' in response.data


def test_platform_onboarding_status_route_returns_school_and_subscription(client, db_session):
    platform_user = PlatformUser(
        email='owner@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Onboarded School', code='ONB1')
    plan = Plan(name='Starter Status', price_cents=9900)
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    db_session.add(
        Subscription(
            school_id=school.id,
            plan_id=plan.id,
            status='active',
            started_at=datetime.now(UTC).replace(tzinfo=None),
            billing_cycle='monthly',
            amount_cents=9900,
        )
    )
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get(f'/platform/onboarding/{school.id}/status')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['school']['name'] == 'Onboarded School'
    assert payload['school']['code'] == 'ONB1'
    assert payload['subscription']['status'] == 'active'
    assert payload['subscription']['plan_id'] == plan.id


def test_platform_subscription_routes_manage_lifecycle(client, db_session):
    platform_user = PlatformUser(
        email='billing@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='Billing School', code='BILL1')
    plan_a = Plan(name='Basic', price_cents=5000, billing_period='monthly')
    plan_b = Plan(name='Pro', price_cents=9000, billing_period='annual')
    db_session.add_all([platform_user, school, plan_a, plan_b])
    db_session.flush()

    subscription = Subscription(
        school_id=school.id,
        plan_id=plan_a.id,
        status='active',
        billing_cycle=plan_a.billing_period,
        amount_cents=plan_a.price_cents,
    )
    db_session.add(subscription)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        f'/platform/subscriptions/{subscription.id}/change-plan',
        data={'plan_id': str(plan_b.id)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(subscription)
    assert subscription.plan_id == plan_b.id
    assert subscription.amount_cents == plan_b.price_cents
    assert subscription.billing_cycle == plan_b.billing_period

    response = client.post(
        f'/platform/subscriptions/{subscription.id}/grace-period',
        data={'days': '5'},
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(subscription)
    assert subscription.status == 'grace_period'
    assert subscription.grace_period_ends_at is not None
    assert subscription.grace_period_ends_at >= datetime.now(UTC).replace(tzinfo=None) + timedelta(days=4)

    response = client.post(
        f'/platform/subscriptions/{subscription.id}/suspend',
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(subscription)
    assert subscription.status == 'suspended'
    assert subscription.ended_at is not None

    response = client.post(
        f'/platform/subscriptions/{subscription.id}/activate',
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(subscription)
    assert subscription.status == 'active'
    assert subscription.ended_at is None
    assert subscription.grace_period_ends_at is None

    response = client.post(
        f'/platform/subscriptions/{subscription.id}/cancel',
        follow_redirects=False,
    )
    assert response.status_code == 302
    db_session.refresh(subscription)
    assert subscription.status == 'cancelled'
    assert subscription.ended_at is not None

    audit_actions = [
        entry.action
        for entry in AuditLog.query.filter_by(target_table='subscriptions', target_id=str(subscription.id)).order_by(AuditLog.id.asc()).all()
    ]
    assert audit_actions == [
        'subscription_plan_changed',
        'subscription_grace_period_started',
        'subscription_suspended',
        'subscription_activated',
        'subscription_cancelled',
    ]


def test_platform_admin_cannot_mutate_subscription_controls(client, db_session):
    platform_user = PlatformUser(
        email='subscription-operator@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Guardrail School', code='GRD1')
    plan_a = Plan(name='Guardrail Basic', price_cents=5000, billing_period='monthly')
    plan_b = Plan(name='Guardrail Pro', price_cents=9000, billing_period='annual')
    db_session.add_all([platform_user, school, plan_a, plan_b])
    db_session.flush()
    subscription = Subscription(
        school_id=school.id,
        plan_id=plan_a.id,
        status='active',
        billing_cycle=plan_a.billing_period,
        amount_cents=plan_a.price_cents,
    )
    db_session.add(subscription)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    change_response = client.post(
        f'/platform/subscriptions/{subscription.id}/change-plan',
        data={'plan_id': str(plan_b.id)},
        follow_redirects=False,
    )
    suspend_response = client.post(
        f'/platform/subscriptions/{subscription.id}/suspend',
        follow_redirects=False,
    )

    assert change_response.status_code == 403
    assert suspend_response.status_code == 403


def test_platform_rollout_allowlist_blocks_non_eligible_platform_login(client, db_session, app):
    _reset_platform_access_settings(db_session)
    app.config['PLATFORM_ROLLOUT_MODE'] = 'allowlist'
    app.config['PLATFORM_ROLLOUT_ALLOWED_EMAILS'] = ['approved-operator@example.com']
    app.config['PLATFORM_ROLLOUT_ALLOWED_ROLES'] = []

    db_session.add(
        PlatformUser(
            email='blocked-operator@example.com',
            password_hash=generate_password_hash('secret123'),
            role='platform_admin',
        )
    )
    db_session.commit()

    response = client.post(
        '/platform/login',
        data={'email': 'blocked-operator@example.com', 'password': 'secret123'},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert b'Platform access is not enabled for this account during the current rollout.' in response.data
    with client.session_transaction() as session:
        assert 'platform_user_id' not in session

    app.config['PLATFORM_ROLLOUT_MODE'] = 'open'
    app.config['PLATFORM_ROLLOUT_ALLOWED_EMAILS'] = []
    app.config['PLATFORM_ROLLOUT_ALLOWED_ROLES'] = []
    _reset_platform_access_settings(db_session)


def test_platform_rollout_allowlist_keeps_super_admin_access(client, db_session, app):
    _reset_platform_access_settings(db_session)
    app.config['PLATFORM_ROLLOUT_MODE'] = 'allowlist'
    app.config['PLATFORM_ROLLOUT_ALLOWED_EMAILS'] = []
    app.config['PLATFORM_ROLLOUT_ALLOWED_ROLES'] = []

    db_session.add(
        PlatformUser(
            email='rollout-super-admin@example.com',
            password_hash=generate_password_hash('secret123'),
            role='super_admin',
        )
    )
    db_session.commit()

    response = client.post(
        '/platform/login',
        data={'email': 'rollout-super-admin@example.com', 'password': 'secret123'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/platform/')

    app.config['PLATFORM_ROLLOUT_MODE'] = 'open'
    app.config['PLATFORM_ROLLOUT_ALLOWED_EMAILS'] = []
    app.config['PLATFORM_ROLLOUT_ALLOWED_ROLES'] = []
    _reset_platform_access_settings(db_session)


def test_super_admin_can_update_platform_access_settings_from_ui(client, db_session):
    _reset_platform_access_settings(db_session)
    platform_user = PlatformUser(
        email='access-settings-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    db_session.add(platform_user)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    post_response = client.post(
        '/platform/settings/access/update',
        data={
            'rollout_mode': 'allowlist',
            'allowed_emails': 'billing.one@example.com\nsupport.one@example.com',
            'allowed_roles': ['billing', 'support'],
            'tenant_enforcement_mode': 'audit',
            'tenant_enforcement_notes': 'Audit mode verified in staging.',
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    settings_page = client.get('/platform/settings/access')
    assert settings_page.status_code == 200
    assert b'Current mode: allowlist' in settings_page.data
    assert b'billing.one@example.com' in settings_page.data
    assert b'Current mode: audit' in settings_page.data
    assert b'Audit mode verified in staging.' in settings_page.data

    stored_mode = PlatformSetting.query.filter_by(key='rollout_mode').first()
    stored_roles = PlatformSetting.query.filter_by(key='rollout_allowed_roles').first()
    stored_tenant_mode = PlatformSetting.query.filter_by(key='tenant_enforcement_mode').first()
    assert stored_mode is not None
    assert stored_mode.value_json == 'allowlist'
    assert stored_roles is not None
    assert stored_roles.value_json == ['billing', 'support']
    assert stored_tenant_mode is not None
    assert stored_tenant_mode.value_json == 'audit'

    audit_entry = AuditLog.query.filter_by(action='platform_access_settings_updated').order_by(AuditLog.id.desc()).first()
    assert audit_entry is not None
    assert audit_entry.changes['rollout_mode'] == 'allowlist'
    assert audit_entry.changes['tenant_enforcement_mode'] == 'audit'
    _reset_platform_access_settings(db_session)


def test_platform_admin_cannot_access_platform_access_settings_ui(client, db_session):
    _reset_platform_access_settings(db_session)
    platform_user = PlatformUser(
        email='non-super-settings@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add(platform_user)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/settings/access')

    assert response.status_code == 403


def test_rollout_denied_login_is_visible_in_audit(client, db_session, app):
    from platform_bp.services.access import update_platform_access_settings

    _reset_platform_access_settings(db_session)

    super_admin = PlatformUser(
        email='audit-super-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    blocked_user = PlatformUser(
        email='audit-blocked@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add_all([super_admin, blocked_user])
    db_session.commit()

    update_platform_access_settings(
        rollout_mode='allowlist',
        allowed_emails=['approved-auditor@example.com'],
        allowed_roles=[],
        actor_user_id=super_admin.id,
    )

    denied_response = client.post(
        '/platform/login',
        data={'email': 'audit-blocked@example.com', 'password': 'secret123'},
        follow_redirects=False,
    )
    assert denied_response.status_code == 200
    assert b'Platform access is not enabled for this account during the current rollout.' in denied_response.data

    _login_platform_admin(client, super_admin.id)
    audit_response = client.get('/platform/audit?action=platform_login_rollout_denied')

    assert audit_response.status_code == 200
    assert b'platform_login_rollout_denied' in audit_response.data
    assert b'audit-blocked@example.com' in audit_response.data
    assert b'allowlist' in audit_response.data

    app.config['PLATFORM_ROLLOUT_MODE'] = 'open'
    app.config['PLATFORM_ROLLOUT_ALLOWED_EMAILS'] = []
    app.config['PLATFORM_ROLLOUT_ALLOWED_ROLES'] = []
    _reset_platform_access_settings(db_session)


def test_support_role_can_access_support_queue_but_not_billing_surfaces(client, db_session):
    support_user = PlatformUser(
        email='segmented-support@example.com',
        password_hash=generate_password_hash('secret123'),
        role='support',
    )
    school = School(name='Segmented Support School', code='SGS1')
    db_session.add_all([support_user, school])
    db_session.commit()

    _login_platform_admin(client, support_user.id)

    support_response = client.get('/platform/support')
    subscriptions_response = client.get('/platform/subscriptions')
    schools_response = client.get('/platform/schools')

    assert support_response.status_code == 200
    assert b'Support Tickets' in support_response.data
    assert subscriptions_response.status_code == 403
    assert schools_response.status_code == 403


def test_billing_role_can_access_billing_surfaces_but_not_support_queue(client, db_session):
    billing_user = PlatformUser(
        email='segmented-billing@example.com',
        password_hash=generate_password_hash('secret123'),
        role='billing',
    )
    school = School(name='Segmented Billing School', code='SGB1')
    plan = Plan(name='Segmented Billing Plan', price_cents=18000, billing_period='monthly')
    db_session.add_all([billing_user, school, plan])
    db_session.flush()
    db_session.add(Subscription(school_id=school.id, plan_id=plan.id, status='active', amount_cents=plan.price_cents, billing_cycle=plan.billing_period))
    db_session.commit()

    _login_platform_admin(client, billing_user.id)

    schools_response = client.get('/platform/schools')
    subscriptions_response = client.get('/platform/subscriptions')
    support_response = client.get('/platform/support')

    assert schools_response.status_code == 200
    assert b'Segmented Billing School' in schools_response.data
    assert subscriptions_response.status_code == 200
    assert b'Segmented Billing School' in subscriptions_response.data
    assert b'Read-only billing view' in subscriptions_response.data
    assert support_response.status_code == 403


def test_platform_admin_cannot_access_security_operator_surface(client, db_session):
    platform_user = PlatformUser(
        email='ops-no-security@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add(platform_user)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/security/events')

    assert response.status_code == 403


def test_billing_role_portfolio_scope_limits_school_and_subscription_views(client, db_session):
    billing_user = PlatformUser(
        email='scoped-billing@example.com',
        password_hash=generate_password_hash('secret123'),
        role='billing',
        portfolio_scope={'school_ids': [30101]},
    )
    school_a = School(id=30101, name='Scoped Billing Alpha', code='SBA2')
    school_b = School(id=30102, name='Scoped Billing Beta', code='SBB2')
    plan = Plan(name='Scoped Billing Plan', price_cents=9000, billing_period='monthly')
    db_session.add_all([billing_user, school_a, school_b, plan])
    db_session.flush()
    subscription_a = Subscription(school_id=school_a.id, plan_id=plan.id, status='active', amount_cents=plan.price_cents, billing_cycle=plan.billing_period)
    subscription_b = Subscription(school_id=school_b.id, plan_id=plan.id, status='active', amount_cents=plan.price_cents, billing_cycle=plan.billing_period)
    db_session.add_all([subscription_a, subscription_b])
    db_session.commit()

    _login_platform_admin(client, billing_user.id)

    school_list = client.get('/platform/schools')
    subscriptions_list = client.get('/platform/subscriptions')
    detail_allowed = client.get(f'/platform/subscriptions/{subscription_a.id}')
    detail_blocked = client.get(f'/platform/subscriptions/{subscription_b.id}')

    assert school_list.status_code == 200
    assert b'Scoped Billing Alpha' in school_list.data
    assert b'Scoped Billing Beta' not in school_list.data
    assert subscriptions_list.status_code == 200
    assert b'Scoped Billing Alpha' in subscriptions_list.data
    assert b'Scoped Billing Beta' not in subscriptions_list.data
    assert detail_allowed.status_code == 200
    assert detail_blocked.status_code == 403


def test_support_role_portfolio_scope_limits_queue_and_blocks_cross_school_updates(client, db_session):
    support_user = PlatformUser(
        email='scoped-support@example.com',
        password_hash=generate_password_hash('secret123'),
        role='support',
        portfolio_scope={'school_ids': [30201]},
    )
    school_a = School(id=30201, name='Scoped Support Alpha', code='SSA2')
    school_b = School(id=30202, name='Scoped Support Beta', code='SSB2')
    db_session.add_all([support_user, school_a, school_b])
    db_session.flush()
    ticket_a = SupportTicket(school_id=school_a.id, raised_by_email='alpha@example.com', subject='Alpha issue', description='Scoped issue', status='open')
    ticket_b = SupportTicket(school_id=school_b.id, raised_by_email='beta@example.com', subject='Beta issue', description='Out of scope issue', status='open')
    db_session.add_all([ticket_a, ticket_b])
    db_session.commit()

    _login_platform_admin(client, support_user.id)

    queue_response = client.get('/platform/support')
    update_response = client.post(
        f'/platform/support/{ticket_b.id}/status',
        data={'status': 'closed', 'next': '/platform/support'},
        follow_redirects=False,
    )

    assert queue_response.status_code == 200
    assert b'Alpha issue' in queue_response.data
    assert b'Beta issue' not in queue_response.data
    assert update_response.status_code == 302
    db_session.refresh(ticket_b)
    assert ticket_b.status == 'open'


def test_super_admin_can_edit_platform_user_scope_and_user_list_shows_named_badges(client, db_session):
    super_admin = PlatformUser(
        email='user-editor@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school_a = School(id=30301, name='Scope Edit Alpha', code='SEA3')
    school_b = School(id=30302, name='Scope Edit Beta', code='SEB3')
    target_user = PlatformUser(
        email='scoped-operator@example.com',
        password_hash=generate_password_hash('secret123'),
        role='support',
        assigned_school_id=school_a.id,
        portfolio_scope={'school_ids': [school_a.id]},
    )
    db_session.add_all([super_admin, school_a, school_b, target_user])
    db_session.commit()

    _login_platform_admin(client, super_admin.id)

    edit_page = client.get(f'/platform/users/{target_user.id}/edit')
    assert edit_page.status_code == 200
    assert b'Edit Platform User' in edit_page.data
    assert b'scoped-operator@example.com' in edit_page.data

    response = client.post(
        f'/platform/users/{target_user.id}/edit',
        data={
            'email': 'scoped-operator@example.com',
            'password': '',
            'role': 'security',
            'is_active': 'on',
            'assigned_school': str(school_b.id),
            'portfolio_school_ids': [str(school_b.id)],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Assigned Scope Edit Beta (SEB3)' in response.data
    assert b'Portfolio Scope Edit Beta (SEB3)' in response.data
    assert b'Portfolio 30302' not in response.data

    db_session.refresh(target_user)
    assert target_user.role == 'security'
    assert target_user.assigned_school_id == school_b.id
    assert target_user.portfolio_scope == {'school_ids': [school_b.id]}


def test_platform_user_directory_filters_by_role_status_school_and_search(client, db_session):
    admin = PlatformUser(
        email='directory-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school_a = School(id=30501, name='Filter Alpha', code='FA5')
    school_b = School(id=30502, name='Filter Beta', code='FB5')
    db_session.add_all([admin, school_a, school_b])
    db_session.flush()
    visible_user = PlatformUser(
        email='billing-alpha@example.com',
        password_hash=generate_password_hash('secret123'),
        role='billing',
        is_active=True,
        assigned_school_id=school_a.id,
        created_by=admin.id,
    )
    hidden_user = PlatformUser(
        email='support-beta@example.com',
        password_hash=generate_password_hash('secret123'),
        role='support',
        is_active=False,
        assigned_school_id=school_b.id,
    )
    db_session.add_all([visible_user, hidden_user])
    db_session.commit()

    _login_platform_admin(client, admin.id)

    response = client.get(f'/platform/users?role=billing&status=active&school_id={school_a.id}&q=alpha')

    assert response.status_code == 200
    assert b'billing-alpha@example.com' in response.data
    assert b'support-beta@example.com' not in response.data
    assert b'Last login: Never' in response.data


def test_platform_user_edit_page_shows_recent_audit_history(client, db_session):
    admin = PlatformUser(
        email='history-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    target_user = PlatformUser(
        email='history-target@example.com',
        password_hash=generate_password_hash('secret123'),
        role='support',
        is_active=True,
    )
    db_session.add_all([admin, target_user])
    db_session.flush()
    db_session.add(
        AuditLog(
            actor_user_id=admin.id,
            actor_platform=True,
            action='platform_user_updated',
            target_table='platform_users',
            target_id=str(target_user.id),
            changes={
                'current': {
                    'role': 'support',
                    'is_active': True,
                    'password_reset': False,
                }
            },
        )
    )
    db_session.commit()

    _login_platform_admin(client, admin.id)

    response = client.get(f'/platform/users/{target_user.id}/edit')

    assert response.status_code == 200
    assert b'Recent User Changes' in response.data
    assert b'platform_user_updated' in response.data
    assert b'history-admin@example.com' in response.data


def test_scoped_security_role_limits_events_preferences_deliveries_and_actions(client, db_session):
    security_user = PlatformUser(
        email='scoped-security@example.com',
        password_hash=generate_password_hash('secret123'),
        role='security',
        portfolio_scope={'school_ids': [30401]},
    )
    school_a = School(id=30401, name='Scoped Security Alpha', code='SSA4')
    school_b = School(id=30402, name='Scoped Security Beta', code='SSB4')
    event_a = SecurityEvent(
        event_type='repeated_failed_platform_login',
        severity='high',
        status='open',
        title='Scoped alpha event',
        description='Alpha security event',
        signal_key='alpha-signal',
        school_id=school_a.id,
    )
    event_b = SecurityEvent(
        event_type='platform_impersonation_burst',
        severity='critical',
        status='open',
        title='Scoped beta event',
        description='Beta security event',
        signal_key='beta-signal',
        school_id=school_b.id,
    )
    preference_a = SecurityNotificationPreference(
        name='Alpha SOC',
        channel='email',
        destination='alpha-security@example.com',
        min_severity='high',
        throttle_minutes=30,
        enabled=True,
        school_id=school_a.id,
    )
    preference_b = SecurityNotificationPreference(
        name='Beta SOC',
        channel='email',
        destination='beta-security@example.com',
        min_severity='high',
        throttle_minutes=30,
        enabled=True,
        school_id=school_b.id,
    )
    db_session.add_all([security_user, school_a, school_b, event_a, event_b, preference_a, preference_b])
    db_session.flush()
    delivery_a = SecurityNotificationDelivery(
        security_event_id=event_a.id,
        preference_id=preference_a.id,
        channel='email',
        destination=preference_a.destination,
        status='sent',
        throttle_key='alpha-delivery',
    )
    delivery_b = SecurityNotificationDelivery(
        security_event_id=event_b.id,
        preference_id=preference_b.id,
        channel='email',
        destination=preference_b.destination,
        status='sent',
        throttle_key='beta-delivery',
    )
    db_session.add_all([delivery_a, delivery_b])
    db_session.commit()

    _login_platform_admin(client, security_user.id)

    page_response = client.get('/platform/security/events', follow_redirects=True)
    assert page_response.status_code == 200
    assert b'Scoped Security Alpha (SSA4)' in page_response.data
    assert b'Scoped alpha event' in page_response.data
    assert b'Scoped beta event' not in page_response.data
    assert b'Alpha SOC' in page_response.data
    assert b'Beta SOC' not in page_response.data
    assert b'beta-security@example.com' not in page_response.data

    blocked_ack = client.post(
        f'/platform/security/events/{event_b.id}/acknowledge',
        data={'next': '/platform/security/events'},
        follow_redirects=False,
    )
    assert blocked_ack.status_code == 302
    db_session.refresh(event_b)
    assert event_b.status == 'open'

    create_pref_response = client.post(
        '/platform/security/notifications/preferences',
        data={
            'name': 'Out of scope global',
            'channel': 'email',
            'destination': 'global-security@example.com',
            'min_severity': 'high',
            'throttle_minutes': '15',
            'school_id': '',
            'event_types': '',
            'enabled': 'on',
            'next': '/platform/security/events',
        },
        follow_redirects=True,
    )
    assert create_pref_response.status_code == 200
    assert b'Scoped security operators must choose a school inside their portfolio.' in create_pref_response.data
    assert SecurityNotificationPreference.query.filter_by(name='Out of scope global').count() == 0

    csv_response = client.get('/platform/security/events/export')
    assert csv_response.status_code == 200
    csv_text = csv_response.data.decode('utf-8')
    assert 'Scoped alpha event' in csv_text
    assert 'Scoped beta event' not in csv_text


def test_access_settings_history_page_renders_previous_and_updated_rollout_state(client, db_session):
    _reset_platform_access_settings(db_session)
    super_admin = PlatformUser(
        email='history-super-admin@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    db_session.add(super_admin)
    db_session.commit()

    _login_platform_admin(client, super_admin.id)

    client.post(
        '/platform/settings/access/update',
        data={'rollout_mode': 'open', 'allowed_emails': '', 'allowed_roles': [], 'tenant_enforcement_mode': 'audit', 'tenant_enforcement_notes': 'Audit before enforce'},
        follow_redirects=False,
    )
    client.post(
        '/platform/settings/access/update',
        data={'rollout_mode': 'roles', 'allowed_emails': '', 'allowed_roles': ['security', 'billing'], 'tenant_enforcement_mode': 'enforce', 'tenant_enforcement_notes': 'Signed off for enforce'},
        follow_redirects=False,
    )

    response = client.get('/platform/settings/access')

    assert response.status_code == 200
    assert b'Previous' in response.data
    assert b'Updated' in response.data
    assert b'roles' in response.data
    assert b'security, billing' in response.data
    assert b'Signed off for enforce' in response.data
    _reset_platform_access_settings(db_session)


def test_platform_onboarding_route_provisions_admin_and_default_subscription(client, db_session):
    platform_user = PlatformUser(
        email='ops@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    starter = Plan(name='Starter Onboarding', price_cents=0, billing_period='monthly')
    db_session.add_all([platform_user, starter])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        '/platform/onboarding',
        data={
            'name': 'Northgate School',
            'code': 'ngs-01',
            'timezone': 'Africa/Nairobi',
            'contact_email': 'office@northgate.test',
            'contact_phone': '0700000000',
            'admin_username': 'northgate_admin',
            'admin_password': 'secret123',
            'admin_staff_id': 'ADM009',
        },
        follow_redirects=False,
    )

    redirect_path = urlparse(response.headers['Location']).path
    school_id = int(redirect_path.rstrip('/').split('/')[-2])
    school = db_session.get(School, school_id)
    assert school is not None
    subscription = Subscription.query.filter_by(school_id=school.id).order_by(Subscription.id.desc()).first()
    assert subscription is not None
    assert subscription.status == 'trial'
    tenant_admin = User.query.filter_by(school_id=school.id, username='northgate_admin').first()
    assert tenant_admin is not None
    assert tenant_admin.TA == 1

    assert response.status_code == 302
    assert response.headers['Location'].endswith(f'/platform/onboarding/{school.id}/confirmation')

    confirm_response = client.get(response.headers['Location'])
    assert confirm_response.status_code == 200
    assert b'Onboarding Complete' in confirm_response.data
    assert b'northgate_admin' in confirm_response.data
    assert b'secret123' in confirm_response.data
    assert b'/login' in confirm_response.data
    assert b'NGS01' in confirm_response.data
    assert b'Copy Credentials' in confirm_response.data
    assert b'onboarding-credentials-bundle' in confirm_response.data

    onboarding_actions = [
        entry.action
        for entry in AuditLog.query.filter_by(school_id=school.id).order_by(AuditLog.id.asc()).all()
        if entry.action in {'school_onboarded', 'subscription_provisioned', 'tenant_admin_created'}
    ]
    assert onboarding_actions == [
        'school_onboarded',
        'subscription_provisioned',
        'tenant_admin_created',
    ]


def test_platform_onboarding_route_uses_student_band_pricing(client, db_session):
    from platform_bp.models import PlanBandPrice, StudentBand

    platform_user = PlatformUser(
        email='banded-onboarding@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    plan = Plan(name='Banded Growth', price_cents=10000, billing_period='monthly')
    band_small = StudentBand(label='banded-small', min_students=1, max_students=300, sort_order=10)
    band_medium = StudentBand(label='banded-medium', min_students=301, max_students=700, sort_order=20)
    db_session.add_all([platform_user, plan, band_small, band_medium])
    db_session.flush()
    db_session.add_all([
        PlanBandPrice(plan_id=plan.id, student_band_id=band_small.id, price_cents=10000),
        PlanBandPrice(plan_id=plan.id, student_band_id=band_medium.id, price_cents=22000),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        '/platform/onboarding',
        data={
            'name': 'Banded School',
            'code': 'bs-01',
            'timezone': 'Africa/Nairobi',
            'default_plan_id': str(plan.id),
            'student_count': '500',
            'contact_email': 'office@banded.test',
            'admin_username': 'banded_admin',
            'admin_password': 'secret123',
            'admin_staff_id': 'ADM050',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    redirect_path = urlparse(response.headers['Location']).path
    school_id = int(redirect_path.rstrip('/').split('/')[-2])
    subscription = Subscription.query.filter_by(school_id=school_id).order_by(Subscription.id.desc()).first()

    assert subscription is not None
    assert subscription.amount_cents == 22000
    assert subscription.billing_meta['student_count'] == 500
    assert subscription.billing_meta['student_band_label'] == 'banded-medium'


def test_platform_onboarding_route_resolves_bundle_family_and_billing_period(client, db_session):
    platform_user = PlatformUser(
        email='commercial-onboarding@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    monthly_plan = Plan(
        name='Commercial Monthly Academic',
        price_cents=10000,
        billing_period='monthly',
        bundle_family='academic',
    )
    annual_plan = Plan(
        name='Commercial Annual Academic',
        price_cents=90000,
        billing_period='annual',
        bundle_family='academic',
    )
    db_session.add_all([platform_user, monthly_plan, annual_plan])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.post(
        '/platform/onboarding',
        data={
            'name': 'Commercial Route School',
            'code': 'crs-01',
            'timezone': 'Africa/Nairobi',
            'bundle_family': 'academic',
            'billing_period': 'annual',
            'contact_email': 'office@commercial-route.test',
            'admin_username': 'commercial_admin',
            'admin_password': 'secret123',
            'admin_staff_id': 'ADM060',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    redirect_path = urlparse(response.headers['Location']).path
    school_id = int(redirect_path.rstrip('/').split('/')[-2])
    subscription = Subscription.query.filter_by(school_id=school_id).order_by(Subscription.id.desc()).first()
    selected_plan = db_session.get(Plan, subscription.plan_id) if subscription else None

    assert subscription is not None
    assert selected_plan is not None
    assert selected_plan.bundle_family == 'academic'


def test_platform_pricing_reports_show_bundle_band_module_and_revenue_views(client, db_session):
    from platform_bp.models import PlanBandPrice, StudentBand

    platform_user = PlatformUser(
        email='pricing-reports@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school_one = School(name='Pricing One Academy', code='POA1', is_active=True)
    school_two = School(name='Pricing Legacy Academy', code='PLA1', is_active=True)
    module_students = ModuleCatalog.query.filter_by(code='students').first() or ModuleCatalog(code='students', name='Students Management', family='academic', is_core=True, sort_order=10)
    module_fees = ModuleCatalog.query.filter_by(code='fees').first() or ModuleCatalog(code='fees', name='Fees Collection And Management', family='accounting', is_core=True, sort_order=20)
    band_small = StudentBand(label='pricing-small', min_students=1, max_students=300, sort_order=10)
    band_medium = StudentBand(label='pricing-medium', min_students=301, max_students=700, sort_order=20)
    configured_plan = Plan(name='Pricing Academic Monthly', price_cents=12000, billing_period='monthly', bundle_family='academic', features={'modules': ['students', 'fees']})
    legacy_plan = Plan(name='Pricing Legacy Monthly', price_cents=7000, billing_period='monthly', bundle_family='combined')
    db_session.add_all([platform_user, school_one, school_two, configured_plan, legacy_plan])
    if module_students.id is None:
        db_session.add(module_students)
    if module_fees.id is None:
        db_session.add(module_fees)
    db_session.add_all([band_small, band_medium])
    db_session.flush()
    platform_user.portfolio_scope = {'school_ids': [school_one.id, school_two.id]}
    db_session.add_all([
        PlanModule(plan_id=configured_plan.id, module_id=module_students.id, is_included=True, is_active=True),
        PlanModule(plan_id=configured_plan.id, module_id=module_fees.id, is_included=True, is_active=True),
        PlanBandPrice(plan_id=configured_plan.id, student_band_id=band_small.id, price_cents=12000),
        PlanBandPrice(plan_id=configured_plan.id, student_band_id=band_medium.id, price_cents=24000),
        Subscription(
            school_id=school_one.id,
            plan_id=configured_plan.id,
            status='active',
            amount_cents=12000,
            billing_cycle='monthly',
            billing_meta={'student_count': 180, 'student_band_id': band_small.id, 'student_band_label': band_small.label},
        ),
        Subscription(
            school_id=school_two.id,
            plan_id=legacy_plan.id,
            status='active',
            amount_cents=7000,
            billing_cycle='monthly',
            billing_meta={'student_count': 420, 'student_band_id': band_medium.id, 'student_band_label': band_medium.label},
        ),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/reports/pricing')

    assert response.status_code == 200
    assert b'Pricing Reports' in response.data
    assert b'Schools By Bundle' in response.data
    assert b'Schools By Student Band' in response.data
    assert b'Module Adoption' in response.data
    assert b'Revenue Projection' in response.data
    assert b'Legacy Mapping Review' in response.data
    assert b'Pricing One Academy' in response.data
    assert b'Pricing Legacy Academy' in response.data
    assert b'Pending review' in response.data
    assert b'Students Management' in response.data
    assert b'Fees Collection And Management' in response.data


def test_platform_pricing_reports_csv_exports_flat_pricing_state(client, db_session):
    from platform_bp.models import PlanBandPrice, StudentBand

    platform_user = PlatformUser(
        email='pricing-export@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Pricing Export School', code='PES1', is_active=True)
    band = StudentBand(label='pricing-export-band', min_students=1, max_students=500, sort_order=10)
    plan = Plan(name='Pricing Export Plan', price_cents=15000, billing_period='monthly', bundle_family='academic', features={'modules': ['students']})
    db_session.add_all([platform_user, school, band, plan])
    db_session.flush()
    platform_user.portfolio_scope = {'school_ids': [school.id]}
    db_session.add(PlanBandPrice(plan_id=plan.id, student_band_id=band.id, price_cents=15000))
    db_session.add(
        Subscription(
            school_id=school.id,
            plan_id=plan.id,
            status='active',
            amount_cents=15000,
            billing_cycle='monthly',
            billing_meta={'student_count': 120, 'student_band_id': band.id, 'student_band_label': band.label},
        )
    )
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/reports/pricing/export')

    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('text/csv')
    assert response.headers['Content-Disposition'] == 'attachment; filename=pricing-state-review.csv'
    csv_text = response.data.decode('utf-8')
    assert 'school_id,school_name,school_code,subscription_id,plan_name,effective_status,billing_cycle,bundle_family,student_band_label,student_count,student_count_source,amount_cents,projected_monthly_cents,projected_annual_cents,entitlement_configuration_state,module_codes,module_names,mapping_review_state,mapping_review_label,mapping_review_is_ambiguous,mapping_review_notes,mapping_review_updated_at,mapping_review_actor' in csv_text
    assert 'Pricing Export School' in csv_text
    assert 'pricing-export-band' in csv_text
    assert 'pending_review' not in csv_text
    assert 'auto_mapped' in csv_text


def test_super_admin_can_update_subscription_mapping_review(client, db_session):
    super_admin = PlatformUser(
        email='mapping-review-super@example.com',
        password_hash=generate_password_hash('secret123'),
        role='super_admin',
    )
    school = School(name='Mapping Review School', code='MRS1', is_active=True)
    plan = Plan(name='Mapping Review Legacy Plan', price_cents=9000, billing_period='monthly', bundle_family='combined')
    db_session.add_all([super_admin, school, plan])
    db_session.flush()
    subscription = Subscription(
        school_id=school.id,
        plan_id=plan.id,
        status='active',
        amount_cents=9000,
        billing_cycle='monthly',
        billing_meta={'student_count': 250},
    )
    db_session.add(subscription)
    db_session.commit()

    _login_platform_admin(client, super_admin.id)

    response = client.post(
        f'/platform/subscriptions/{subscription.id}/mapping-review',
        data={
            'mapping_review_status': 'review_required',
            'mapping_review_notes': 'Legacy bundle needs operator follow-up',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    db_session.refresh(subscription)
    assert subscription.billing_meta['mapping_review_status'] == 'review_required'
    assert subscription.billing_meta['mapping_review_notes'] == 'Legacy bundle needs operator follow-up'
    assert subscription.billing_meta['mapping_review_actor_user_id'] == super_admin.id
    assert subscription.billing_meta['mapping_review_updated_at']

    audit_entry = AuditLog.query.filter_by(target_table='subscriptions', target_id=str(subscription.id), action='subscription_mapping_review_updated').order_by(AuditLog.id.desc()).first()
    assert audit_entry is not None
    assert audit_entry.changes['new_mapping_review_status'] == 'review_required'


def test_platform_subscription_pages_render_controls(client, db_session):
    platform_user = PlatformUser(
        email='reviewer@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Controls School', code='CTRL1')
    plan = Plan(name='Starter Controls', price_cents=0)
    db_session.add_all([platform_user, school, plan])
    db_session.flush()
    subscription = Subscription(school_id=school.id, plan_id=plan.id, status='trial', billing_cycle='monthly', amount_cents=0)
    db_session.add(subscription)
    db_session.commit()
    db_session.add(
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_provisioned',
            target_table='subscriptions',
            target_id=str(subscription.id),
            school_id=school.id,
            changes={'status': 'trial', 'plan_id': plan.id},
        )
    )
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    list_response = client.get('/platform/subscriptions')
    detail_response = client.get(f'/platform/subscriptions/{subscription.id}')

    assert list_response.status_code == 200
    assert b'Create Subscription' not in list_response.data
    assert b'Read-only billing view' in list_response.data
    assert b'Lifecycle actions hidden for read-only billing operators' in list_response.data

    assert detail_response.status_code == 200
    assert b'Subscription Detail' in detail_response.data
    assert b'Billing Visibility' in detail_response.data
    assert b'Change Plan' not in detail_response.data
    assert b'Subscription History' in detail_response.data
    assert b'subscription_provisioned' in detail_response.data


def test_platform_audit_page_filters_by_school_target_and_action(client, db_session):
    platform_user = PlatformUser(
        email='auditor@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school_a = School(name='Alpha School', code='ALP1')
    school_b = School(name='Beta School', code='BET1')
    db_session.add_all([platform_user, school_a, school_b])
    db_session.flush()
    db_session.add_all([
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_activated',
            target_table='subscriptions',
            target_id='10',
            school_id=school_a.id,
            changes={'new_status': 'active'},
        ),
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='tenant_admin_created',
            target_table='users',
            target_id='22',
            school_id=school_a.id,
            changes={'username': 'alphaadmin'},
        ),
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_suspended',
            target_table='subscriptions',
            target_id='11',
            school_id=school_b.id,
            changes={'new_status': 'suspended'},
        ),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get(
        f'/platform/audit?school_id={school_a.id}&target_table=subscriptions&action=subscription_activated'
    )

    assert response.status_code == 200
    assert b'Apply Filters' in response.data
    assert b'subscription_activated' in response.data
    assert b'Alpha School' in response.data
    assert b'#10' in response.data
    assert b'#11' not in response.data
    assert b'#22' not in response.data


def test_platform_audit_page_filters_by_date_range_and_shows_school_names(client, db_session):
    platform_user = PlatformUser(
        email='timelens@example.com',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Timeline School', code='TIM1')
    db_session.add_all([platform_user, school])
    db_session.flush()
    db_session.add_all([
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_activated',
            target_table='subscriptions',
            target_id='30',
            school_id=school.id,
            changes={'new_status': 'active'},
            created_at=datetime(2026, 4, 1, 10, 0, 0),
        ),
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_suspended',
            target_table='subscriptions',
            target_id='31',
            school_id=school.id,
            changes={'new_status': 'suspended'},
            created_at=datetime(2026, 4, 2, 10, 0, 0),
        ),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    response = client.get('/platform/audit?start_date=2026-04-02&end_date=2026-04-02')

    assert response.status_code == 200
    assert b'Timeline School' in response.data
    assert b'TIM1' in response.data
    assert b'#31' in response.data
    assert b'#30' not in response.data


def test_platform_audit_page_shows_actor_and_exports_filtered_csv(client, db_session):
    platform_user = PlatformUser(
        email='exporter@example.com',
        name='Ops Exporter',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Export School', code='EXP1')
    db_session.add_all([platform_user, school])
    db_session.flush()
    db_session.add_all([
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_activated',
            target_table='subscriptions',
            target_id='40',
            school_id=school.id,
            changes={'new_status': 'active'},
            created_at=datetime(2026, 4, 2, 12, 0, 0),
        ),
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_cancelled',
            target_table='subscriptions',
            target_id='41',
            school_id=school.id,
            changes={'new_status': 'cancelled'},
            created_at=datetime(2026, 4, 3, 12, 0, 0),
        ),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    page_response = client.get('/platform/audit?school_id={}&action=subscription_activated'.format(school.id))
    csv_response = client.get('/platform/audit/export?school_id={}&action=subscription_activated'.format(school.id))

    assert page_response.status_code == 200
    assert b'Ops Exporter' in page_response.data
    assert b'exporter@example.com' in page_response.data
    assert b'platform_admin' in page_response.data
    assert b'Export CSV' in page_response.data

    assert csv_response.status_code == 200
    assert csv_response.headers['Content-Type'].startswith('text/csv')
    assert 'attachment; filename=platform-audit.csv' == csv_response.headers['Content-Disposition']
    csv_text = csv_response.data.decode('utf-8')
    assert 'school_name,school_code,actor,actor_email,actor_role,ip,action,target_table,target_id,details' in csv_text
    assert 'Export School,EXP1,Ops Exporter,exporter@example.com,platform_admin,,subscription_activated,subscriptions,40,new_status=active' in csv_text
    assert 'subscription_cancelled' not in csv_text


def test_platform_audit_page_filters_by_actor_role_ip_and_paginates(client, db_session):
    platform_user = PlatformUser(
        email='pager@example.com',
        name='Pager Admin',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    support_user = PlatformUser(
        email='supportpager@example.com',
        name='Support Pager',
        password_hash=generate_password_hash('secret123'),
        role='support',
    )
    school = School(name='Paged School', code='PGD1')
    db_session.add_all([platform_user, support_user, school])
    db_session.flush()

    logs = []
    for index in range(27):
        logs.append(
            AuditLog(
                actor_user_id=platform_user.id,
                actor_platform=True,
                action='subscription_activated',
                target_table='subscriptions',
                target_id=str(500 + index),
                school_id=school.id,
                changes={'sequence': index},
                ip='10.0.0.5',
                created_at=datetime(2026, 4, 2, 8, 0, 0),
            )
        )
    logs.append(
        AuditLog(
            actor_user_id=support_user.id,
            actor_platform=True,
            action='subscription_activated',
            target_table='subscriptions',
            target_id='999',
            school_id=school.id,
            changes={'sequence': 999},
            ip='192.168.1.10',
            created_at=datetime(2026, 4, 2, 9, 0, 0),
        )
    )
    db_session.add_all(logs)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    page_one = client.get('/platform/audit?actor_role=platform_admin&ip=10.0.0&page=1&page_size=10')
    page_two = client.get('/platform/audit?actor_role=platform_admin&ip=10.0.0&page=2&page_size=10')
    page_three = client.get('/platform/audit?actor_role=platform_admin&ip=10.0.0&page=3&page_size=10')

    assert page_one.status_code == 200
    assert b'Pager Admin' in page_one.data
    assert b'Page 1 of 3' in page_one.data
    assert b'Showing 1-10 of 27 audit records' in page_one.data
    assert b'10 per page' in page_one.data
    assert b'Support Pager' not in page_one.data
    assert b'#500' not in page_one.data
    assert b'page_size=10' in page_one.data

    assert page_two.status_code == 200
    assert b'Page 2 of 3' in page_two.data
    assert b'Showing 11-20 of 27 audit records' in page_two.data

    assert page_three.status_code == 200
    assert b'Page 3 of 3' in page_three.data
    assert b'Showing 21-27 of 27 audit records' in page_three.data
    assert b'#500' in page_three.data


def test_platform_audit_page_supports_sortable_columns(client, db_session):
    platform_user = PlatformUser(
        email='sorter@example.com',
        name='Sorting Admin',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    alpha_school = School(name='Alpha School', code='ALPSORT1')
    beta_school = School(name='Beta School', code='BETSORT1')
    db_session.add_all([platform_user, alpha_school, beta_school])
    db_session.flush()

    db_session.add_all([
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='zeta_action',
            target_table='subscriptions',
            target_id='701',
            school_id=beta_school.id,
            changes={'sequence': 'late'},
            created_at=datetime(2026, 4, 3, 12, 0, 0),
        ),
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='alpha_action',
            target_table='schools',
            target_id='702',
            school_id=alpha_school.id,
            changes={'sequence': 'early'},
            created_at=datetime(2026, 4, 1, 12, 0, 0),
        ),
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    created_response = client.get('/platform/audit?sort_by=created_at&sort_dir=asc&page_size=100')
    action_response = client.get('/platform/audit/export?sort_by=action&sort_dir=asc')
    school_response = client.get('/platform/audit/export?sort_by=school&sort_dir=asc')
    created_export_response = client.get('/platform/audit/export?sort_by=created_at&sort_dir=asc')

    assert created_response.status_code == 200
    created_text = created_export_response.data.decode('utf-8')
    assert created_text.index(',schools,702,') < created_text.index(',subscriptions,701,')

    assert action_response.status_code == 200
    action_text = action_response.data.decode('utf-8')
    assert action_text.index(',schools,702,') < action_text.index(',subscriptions,701,')

    assert school_response.status_code == 200
    school_text = school_response.data.decode('utf-8')
    assert school_text.index('Alpha School,ALPSORT1') < school_text.index('Beta School,BETSORT1')
    page_html = created_response.data.decode('utf-8')
    assert 'sort_by=action' in page_html
    assert 'sort_by=school&amp;sort_dir=asc' in page_html


def test_platform_audit_page_size_preference_persists_in_session(client, db_session):
    platform_user = PlatformUser(
        email='persistpager@example.com',
        name='Persist Pager',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Persisted Page School', code='PGP1')
    db_session.add_all([platform_user, school])
    db_session.flush()

    db_session.add_all([
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_activated',
            target_table='subscriptions',
            target_id=str(800 + index),
            school_id=school.id,
            changes={'sequence': index},
            created_at=datetime(2026, 4, 2, 10, 0, 0),
        )
        for index in range(30)
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    chosen_size_response = client.get(f'/platform/audit?school_id={school.id}&action=subscription_activated&sort_by=action&sort_dir=asc&page_size=10&page=2')
    persisted_response = client.get(f'/platform/audit?school_id={school.id}&action=subscription_activated&sort_by=action&sort_dir=asc&page=2')
    reset_response = client.get(f'/platform/audit?school_id={school.id}&action=subscription_activated&sort_by=action&sort_dir=asc&page=2&reset_view_preferences=1')
    after_reset_response = client.get(f'/platform/audit?school_id={school.id}&action=subscription_activated&sort_by=action&sort_dir=asc&page=2')

    assert chosen_size_response.status_code == 200
    assert b'Showing 11-20 of 30 audit records' in chosen_size_response.data

    assert persisted_response.status_code == 200
    assert b'Showing 11-20 of 30 audit records' in persisted_response.data
    assert b'10 per page' in persisted_response.data
    assert b'Saved page size: 10' in persisted_response.data
    assert b'title="Using saved preference for audit page size"' in persisted_response.data
    assert b'aria-label="Using saved preference for audit page size: 10 per page"' in persisted_response.data
    assert b'viewBox="0 0 16 16"' in persisted_response.data
    assert b'Reset View Preferences' in persisted_response.data
    assert b'Reset View Preferences clears the saved page-size choice only.' in persisted_response.data
    assert b'action=subscription_activated' in persisted_response.data
    assert b'sort_by=action&amp;sort_dir=desc' in persisted_response.data
    assert b'page=2&amp;reset_view_preferences=1' in persisted_response.data

    assert reset_response.status_code == 200
    assert b'Showing 26-30 of 30 audit records' in reset_response.data
    assert b'action=subscription_activated' in reset_response.data
    assert b'sort_by=action&amp;sort_dir=desc' in reset_response.data
    assert b'Audit view preferences reset.' in reset_response.data
    assert b'Saved page size: 10' not in reset_response.data

    assert after_reset_response.status_code == 200
    assert b'Showing 26-30 of 30 audit records' in after_reset_response.data
    assert b'Saved page size: 10' not in after_reset_response.data


def test_platform_audit_sort_headers_show_direction_tooltips(client, db_session):
    platform_user = PlatformUser(
        email='tooltipsorter@example.com',
        name='Tooltip Sorter',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    db_session.add(platform_user)
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    default_response = client.get('/platform/audit')
    action_sorted_response = client.get('/platform/audit?sort_by=action&sort_dir=asc')

    assert default_response.status_code == 200
    default_html = default_response.data.decode('utf-8')
    assert 'title="Sort ascending"' in default_html
    assert 'aria-label="Sort ascending by action"' in default_html

    assert action_sorted_response.status_code == 200
    sorted_html = action_sorted_response.data.decode('utf-8')
    assert 'title="Sort descending"' in sorted_html
    assert 'aria-label="Sort descending by action"' in sorted_html


def test_platform_audit_reset_does_not_preserve_auto_clamped_page(client, db_session):
    platform_user = PlatformUser(
        email='clampedpager@example.com',
        name='Clamped Pager',
        password_hash=generate_password_hash('secret123'),
        role='platform_admin',
    )
    school = School(name='Clamped Page School', code='CLP1')
    db_session.add_all([platform_user, school])
    db_session.flush()

    db_session.add_all([
        AuditLog(
            actor_user_id=platform_user.id,
            actor_platform=True,
            action='subscription_activated',
            target_table='subscriptions',
            target_id=str(900 + index),
            school_id=school.id,
            changes={'sequence': index},
            created_at=datetime(2026, 4, 2, 11, 0, 0),
        )
        for index in range(30)
    ])
    db_session.commit()

    _login_platform_admin(client, platform_user.id)

    chosen_size_response = client.get(f'/platform/audit?school_id={school.id}&page_size=10&page=99')
    reset_response = client.get(f'/platform/audit?school_id={school.id}&page=99&reset_view_preferences=1')

    assert chosen_size_response.status_code == 200
    assert b'Showing 21-30 of 30 audit records' in chosen_size_response.data

    assert reset_response.status_code == 200
    assert b'Showing 1-25 of 30 audit records' in reset_response.data
    assert b'page=3&amp;reset_view_preferences=1' not in reset_response.data
    assert b'Audit view preferences reset.' in reset_response.data
