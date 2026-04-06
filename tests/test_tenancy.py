import pytest
from flask import session

from core.permissions import tenant_required
from core.tenancy import (
    TenantContextError,
    filter_by_school,
    get_current_school,
    get_current_school_id,
    get_required_access_tier_for_request,
    get_required_module_code_for_request,
    load_tenant_context,
    require_current_school_id,
    resolve_school_request_access,
)
from models import School, User
from platform_bp.models import AuditLog, Plan, PlatformSetting, Subscription


def _reset_tenant_enforcement(app, db_session):
    app.config['TENANT_ENFORCEMENT_MODE'] = 'enforce'
    app.config['TENANT_ENFORCEMENT_NOTES'] = ''
    PlatformSetting.query.filter(PlatformSetting.key.in_(['tenant_enforcement_mode', 'tenant_enforcement_notes'])).delete(synchronize_session=False)
    db_session.commit()


def test_get_current_school_id_from_session(app):
    with app.test_request_context('/'):
        session['school_id'] = 9
        assert get_current_school_id() == 9
        assert require_current_school_id() == 9


def test_require_current_school_id_raises_without_context(app):
    with app.test_request_context('/'):
        with pytest.raises(TenantContextError):
            require_current_school_id()


def test_get_current_school_loads_active_school(app, db_session):
    school = School(name='Tenant School', code='TENANT1')
    db_session.add(school)
    db_session.commit()

    with app.test_request_context('/'):
        session['school_id'] = school.id
        current_school = get_current_school(required=True)
        assert current_school is not None
        assert current_school.id == school.id
        assert current_school.code == 'TENANT1'


def test_filter_by_school_scopes_query(app, db_session):
    school_a = School(name='School A', code='SCHA')
    school_b = School(name='School B', code='SCHB')
    db_session.add_all([school_a, school_b])
    db_session.commit()

    db_session.add_all([
        User(username='teacher_a', school_id=school_a.id, access_flag=1),
        User(username='teacher_b', school_id=school_b.id, access_flag=1),
    ])
    db_session.commit()

    with app.test_request_context('/'):
        session['school_id'] = school_b.id
        users = filter_by_school(User.query).all()
        assert len(users) == 1
        assert users[0].username == 'teacher_b'


def test_tenant_required_redirects_without_school_context(app):
    @tenant_required
    def protected():
        return 'ok'

    with app.test_request_context('/protected'):
        session['userNo'] = 1
        response = protected()
        assert response.status_code == 302
        assert '/login' in response.location


def test_tenant_required_allows_valid_school_context(app):
    @tenant_required
    def protected():
        return 'ok'

    with app.test_request_context('/protected'):
        session['userNo'] = 1
        session['school_id'] = 7
        assert protected() == 'ok'


def test_module_entitlement_gate_redirects_when_plan_excludes_requested_module(client, db_session):
    school = School(name='Academic Tenant', code='ACAD1', is_active=True)
    plan = Plan(name='Academic Only', price_cents=0, features={'modules': ['students', 'classes']})
    db_session.add_all([school, plan])
    db_session.flush()
    db_session.add(
        Subscription(
            school_id=school.id,
            plan_id=plan.id,
            status='active',
            amount_cents=0,
            billing_cycle='monthly',
        )
    )
    db_session.commit()

    with client.session_transaction() as session_state:
        session_state['userNo'] = 1
        session_state['school_id'] = school.id
        session_state['is_admin'] = True
        session_state['logged_in'] = True

    response = client.get('/admin/fees', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/')


def test_module_entitlement_gate_allows_included_module(client, db_session, monkeypatch):
    import blueprints.classes.routes as classes_routes

    school = School(name='Classes Tenant', code='CLS1', is_active=True)
    plan = Plan(name='Classes Enabled', price_cents=0, features={'modules': ['classes']})
    db_session.add_all([school, plan])
    db_session.flush()
    db_session.add(
        Subscription(
            school_id=school.id,
            plan_id=plan.id,
            status='active',
            amount_cents=0,
            billing_cycle='monthly',
        )
    )
    db_session.commit()

    class DummyConnection:
        def close(self):
            return None

    class DummyClassService:
        def __init__(self, connection):
            self.connection = connection
            self.school_id = school.id

        def update_class(self, class_id, class_name, class_group, stream_code):
            return None

    monkeypatch.setattr(classes_routes, 'get_db_connection', lambda: DummyConnection())
    monkeypatch.setattr(classes_routes, 'ClassManagementService', DummyClassService)
    monkeypatch.setattr(classes_routes, 'render_template', lambda *args, **kwargs: 'ok')

    with client.session_transaction() as session_state:
        session_state['userNo'] = 1
        session_state['school_id'] = school.id
        session_state['is_admin'] = True
        session_state['logged_in'] = True

    response = client.post(
        '/admin/classes/1/edit',
        data={'class_name': 'Grade 1', 'stream_code': 'A', 'class_group': 'Grade 1-3'},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.get_json()['success'] is True


def test_module_resolution_falls_back_to_path_prefix_without_blueprint(app):
    with app.test_request_context('/fleet/fleet_dashboard', method='GET'):
        assert get_required_module_code_for_request() == 'fleet_transport'
        assert get_required_access_tier_for_request() == 'read'

    with app.test_request_context('/submit_issuance', method='POST'):
        assert get_required_module_code_for_request() == 'inventory_uniform'
        assert get_required_access_tier_for_request() == 'write'


def test_grace_period_allows_module_reads_but_blocks_writes(app, db_session):
    school = School(name='Grace Classes Tenant', code='GCT1', is_active=True)
    plan = Plan(name='Grace Classes Plan', price_cents=0, features={'modules': ['classes']})
    db_session.add_all([school, plan])
    db_session.flush()
    db_session.add(
        Subscription(
            school_id=school.id,
            plan_id=plan.id,
            status='grace_period',
            amount_cents=0,
            billing_cycle='monthly',
        )
    )
    db_session.commit()

    with app.test_request_context('/admin/manage_classes', method='GET'):
        session['userNo'] = 1
        session['school_id'] = school.id
        session['is_admin'] = True
        session['logged_in'] = True
        load_tenant_context()
        assert resolve_school_request_access() is None

    with app.test_request_context('/admin/classes/1/edit', method='POST'):
        session['userNo'] = 1
        session['school_id'] = school.id
        session['is_admin'] = True
        session['logged_in'] = True
        load_tenant_context()
        response = resolve_school_request_access()
        assert response is not None
        assert response.status_code == 302
        assert response.location.endswith('/')


def test_tenant_enforcement_audit_mode_allows_request_and_logs_observation(app, db_session):
    _reset_tenant_enforcement(app, db_session)
    app.config['TENANT_ENFORCEMENT_MODE'] = 'audit'

    school = School(name='Audit Tenant', code='AUD1', is_active=True)
    plan = Plan(name='Audit Academic Plan', price_cents=0, features={'modules': ['classes']})
    db_session.add_all([school, plan])
    db_session.flush()
    db_session.add(
        Subscription(
            school_id=school.id,
            plan_id=plan.id,
            status='active',
            amount_cents=0,
            billing_cycle='monthly',
        )
    )
    db_session.commit()

    with app.test_request_context('/admin/fees', method='GET'):
        session['userNo'] = 1
        session['school_id'] = school.id
        session['is_admin'] = True
        session['logged_in'] = True
        load_tenant_context()
        response = resolve_school_request_access()

        assert response is None

    audit_entry = AuditLog.query.filter_by(action='tenant_enforcement_observed', school_id=school.id).order_by(AuditLog.id.desc()).first()
    assert audit_entry is not None
    assert audit_entry.changes['reason'] == 'module_excluded'
    assert audit_entry.changes['enforcement_mode'] == 'audit'
    assert audit_entry.changes['required_module_code'] == 'fees'

    _reset_tenant_enforcement(app, db_session)


def test_tenant_enforcement_enforce_mode_blocks_request_and_logs_event(app, db_session):
    _reset_tenant_enforcement(app, db_session)

    school = School(name='Blocked Tenant', code='BLK1', is_active=True)
    plan = Plan(name='Blocked Academic Plan', price_cents=0, features={'modules': ['classes']})
    db_session.add_all([school, plan])
    db_session.flush()
    db_session.add(
        Subscription(
            school_id=school.id,
            plan_id=plan.id,
            status='active',
            amount_cents=0,
            billing_cycle='monthly',
        )
    )
    db_session.commit()

    with app.test_request_context('/admin/fees', method='GET'):
        session['userNo'] = 1
        session['school_id'] = school.id
        session['is_admin'] = True
        session['logged_in'] = True
        load_tenant_context()
        response = resolve_school_request_access()

        assert response is not None
        assert response.status_code == 302
        assert response.location.endswith('/')

    audit_entry = AuditLog.query.filter_by(action='tenant_enforcement_blocked', school_id=school.id).order_by(AuditLog.id.desc()).first()
    assert audit_entry is not None
    assert audit_entry.changes['reason'] == 'module_excluded'
    assert audit_entry.changes['enforcement_mode'] == 'enforce'
    assert audit_entry.changes['required_module_code'] == 'fees'

    _reset_tenant_enforcement(app, db_session)