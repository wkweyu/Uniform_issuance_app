from flask import flash, g, redirect, request, session, url_for
from platform_bp.config.modules import blueprint_module_codes, module_label, path_prefix_module_codes


SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}

# Cache for user module permissions (cleared each request via before_request)
_user_module_cache = {}


def get_user_allowed_modules(user_id, school_id):
    """Return set of module codes the user is granted, or None if no rows exist."""
    cache_key = (user_id, school_id)
    if cache_key in _user_module_cache:
        return _user_module_cache[cache_key]

    from core.db import get_db_connection
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT module_code, can_write FROM user_module_access "
                "WHERE user_id = %s AND school_id = %s",
                (user_id, school_id),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    if not rows:
        result = set()  # No entries = blocked from all modules
    else:
        result = {r['module_code'] for r in rows}

    _user_module_cache[cache_key] = result
    return result


class TenantContextError(RuntimeError):
    """Raised when a tenant-scoped operation runs without an active school context."""


def get_current_school_id(required=False):
    """Return the current tenant's school_id from session or request context."""
    school_id = session.get("school_id")
    if required and not school_id:
        raise TenantContextError("Tenant context is required for this operation.")
    return school_id


def require_current_school_id():
    """Return the current school_id or raise if no tenant context is active."""
    return get_current_school_id(required=True)


def get_current_school(required=False):
    """Resolve the active School model for the current tenant context."""
    school_id = get_current_school_id(required=required)
    if not school_id:
        return None

    if getattr(g, "current_school", None) and g.current_school.id == school_id:
        return g.current_school

    from models import School

    school = School.query.filter_by(id=school_id).first()
    g.current_school = school
    if required and not school:
        raise TenantContextError("Active school could not be resolved.")
    return school


def get_current_subscription(school_id=None):
    """Resolve the current subscription for a school using the existing control-plane tables."""
    resolved_school_id = school_id or get_current_school_id()
    if not resolved_school_id:
        return None

    if getattr(g, "current_subscription", None) and g.current_subscription.school_id == resolved_school_id:
        return g.current_subscription

    try:
        from platform_bp.services.subscriptions import get_subscription_by_school
    except Exception:
        return None

    subscription = get_subscription_by_school(resolved_school_id)
    g.current_subscription = subscription
    return subscription


def get_current_entitled_module_codes(subscription=None):
    resolved_subscription = subscription if subscription is not None else getattr(g, 'current_subscription', None)
    cache_key = getattr(resolved_subscription, 'id', None)

    if getattr(g, 'current_entitled_module_subscription_id', object()) == cache_key:
        return getattr(g, 'current_entitled_module_codes', None)

    try:
        from platform_bp.services.subscriptions import get_subscription_entitled_module_codes
    except Exception:
        g.current_entitled_module_codes = None
        g.current_entitled_module_subscription_id = cache_key
        return None

    entitled_module_codes = get_subscription_entitled_module_codes(
        subscription=resolved_subscription,
        school_id=resolved_subscription.school_id if resolved_subscription is not None else get_current_school_id(),
    )
    g.current_entitled_module_codes = entitled_module_codes
    g.current_entitled_module_subscription_id = cache_key
    return entitled_module_codes


def get_required_module_code_for_request():
    blueprint = request.blueprint or ''
    module_codes_by_blueprint = blueprint_module_codes()
    if blueprint in module_codes_by_blueprint:
        return module_codes_by_blueprint[blueprint]
    request_path = request.path or ''
    for prefix, module_code in path_prefix_module_codes():
        if request_path.startswith(prefix):
            return module_code
    return None


def get_required_access_tier_for_request():
    return 'read' if request.method in SAFE_METHODS else 'write'


def get_school_access_state(school=None, subscription=None):
    """Return the effective school access state using school and subscription lifecycle data."""
    resolved_school = school or get_current_school()
    if not resolved_school:
        return None

    resolved_subscription = subscription if subscription is not None else get_current_subscription(resolved_school.id)
    if resolved_subscription is not None:
        return resolved_subscription.effective_status

    if not resolved_school.is_active:
        return 'inactive'

    if resolved_school.subscription_end:
        from datetime import UTC, datetime

        today = datetime.now(UTC).date()
        if resolved_school.subscription_end < today:
            return 'expired'

    return resolved_school.subscription_status or 'active'


def get_tenant_enforcement_settings():
    try:
        from platform_bp.services.access import get_tenant_enforcement_settings as get_settings
    except Exception:
        return {'mode': 'enforce', 'notes': ''}
    try:
        return get_settings()
    except Exception:
        return {'mode': 'enforce', 'notes': ''}


def _record_tenant_enforcement_event(action, *, school, subscription, reason, required_module_code=None, required_access_tier=None, access_state=None, enforcement_mode=None):
    try:
        from platform_bp.services.audit import log as audit_log
    except Exception:
        return None

    return audit_log(
        actor_user_id=None,
        action=action,
        target_table='subscriptions' if subscription is not None else 'schools',
        target_id=(subscription.id if subscription is not None else school.id if school is not None else None),
        school_id=school.id if school is not None else None,
        changes={
            'reason': reason,
            'request_path': request.path,
            'request_method': request.method,
            'required_module_code': required_module_code,
            'required_access_tier': required_access_tier,
            'access_state': access_state,
            'enforcement_mode': enforcement_mode,
            'tenant_user_no': session.get('userNo'),
        },
    )


def _apply_tenant_enforcement(reason, *, school, subscription, access_state, required_module_code=None, required_access_tier=None, flash_message=None, flash_category='error', redirect_target=None, clear_session=False):
    enforcement_mode = get_tenant_enforcement_settings().get('mode', 'enforce')
    if enforcement_mode == 'open':
        return None
    if enforcement_mode == 'audit':
        _record_tenant_enforcement_event(
            'tenant_enforcement_observed',
            school=school,
            subscription=subscription,
            reason=reason,
            required_module_code=required_module_code,
            required_access_tier=required_access_tier,
            access_state=access_state,
            enforcement_mode=enforcement_mode,
        )
        return None

    _record_tenant_enforcement_event(
        'tenant_enforcement_blocked',
        school=school,
        subscription=subscription,
        reason=reason,
        required_module_code=required_module_code,
        required_access_tier=required_access_tier,
        access_state=access_state,
        enforcement_mode=enforcement_mode,
    )
    if clear_session:
        session.clear()
    if flash_message:
        flash(flash_message, flash_category)
    return redirect(redirect_target or url_for('index'))


def resolve_school_request_access():
    """Enforce subscription state for authenticated school requests."""
    endpoint = request.endpoint or ''
    if endpoint in {'static', 'health_check'}:
        return None

    if endpoint.startswith('auth.') or endpoint.startswith('super_admin.') or endpoint.startswith('platform.'):
        return None

    if 'userNo' not in session or not session.get('school_id'):
        return None

    # Application owner / super-admin bypasses all subscription & module enforcement
    if session.get('is_super_admin', False):
        return None

    school = get_current_school(required=True)
    subscription = get_current_subscription(school.id)
    access_state = get_school_access_state(school=school, subscription=subscription)
    g.subscription = subscription
    g.subscription_state = access_state

    enforcement_mode = get_tenant_enforcement_settings().get('mode', 'enforce')
    g.tenant_enforcement_mode = enforcement_mode

    if enforcement_mode == 'open':
        return None

    if access_state in {'suspended', 'expired', 'archived', 'cancelled', 'inactive'}:
        return _apply_tenant_enforcement(
            'subscription_inactive',
            school=school,
            subscription=subscription,
            access_state=access_state,
            flash_message='Your school subscription is not active. Please contact support or renew access.',
            flash_category='error',
            redirect_target=url_for('auth.login'),
            clear_session=True,
        )

    required_module_code = get_required_module_code_for_request()
    required_access_tier = get_required_access_tier_for_request()
    entitlement_summary = get_current_entitled_module_codes(subscription=subscription)

    if access_state == 'grace_period' and required_module_code:
        from platform_bp.services.subscriptions import build_subscription_entitlement_summary

        entitlement_view = build_subscription_entitlement_summary(subscription=subscription)
        if entitlement_view['is_configured']:
            if required_module_code not in entitlement_view['read_module_codes']:
                label = module_label(required_module_code)
                return _apply_tenant_enforcement(
                    'module_excluded',
                    school=school,
                    subscription=subscription,
                    access_state=access_state,
                    required_module_code=required_module_code,
                    required_access_tier=required_access_tier,
                    flash_message=f'Your current subscription does not include the {label} module.',
                    flash_category='error',
                    redirect_target=url_for('index'),
                )
            if required_access_tier == 'write' and required_module_code not in entitlement_view['write_module_codes']:
                label = module_label(required_module_code)
                return _apply_tenant_enforcement(
                    'grace_period_module_read_only',
                    school=school,
                    subscription=subscription,
                    access_state=access_state,
                    required_module_code=required_module_code,
                    required_access_tier=required_access_tier,
                    flash_message=f'Your school is in a grace period. The {label} module is available read-only until billing is resolved.',
                    flash_category='warning',
                    redirect_target=request.referrer or url_for('index'),
                )

    if access_state == 'grace_period' and required_access_tier == 'write':
        return _apply_tenant_enforcement(
            'grace_period_write_blocked',
            school=school,
            subscription=subscription,
            access_state=access_state,
            required_module_code=required_module_code,
            required_access_tier=required_access_tier,
            flash_message='Your school is in a grace period. Write operations are temporarily disabled until billing is resolved.',
            flash_category='warning',
            redirect_target=request.referrer or url_for('index'),
        )

    if required_module_code:
        if entitlement_summary is not None and required_module_code not in entitlement_summary:
            label = module_label(required_module_code)
            return _apply_tenant_enforcement(
                'module_excluded',
                school=school,
                subscription=subscription,
                access_state=access_state,
                required_module_code=required_module_code,
                required_access_tier=required_access_tier,
                flash_message=f'Your current subscription does not include the {label} module.',
                flash_category='error',
                redirect_target=url_for('index'),
            )

    # ── User-level module access control ──
    # Super-admin already bypassed above. For all other users,
    # check the user_module_access table. No entries = no access.
    if required_module_code:
        user_id = session.get('userNo')
        school_id = session.get('school_id')
        if user_id and school_id:
            allowed = get_user_allowed_modules(user_id, school_id)
            if required_module_code not in allowed:
                label = module_label(required_module_code)
                flash(f'You do not have access to the {label} module. Contact your administrator.', 'error')
                return redirect(url_for('index'))

    return None


def filter_by_school(query, model=None, school_id=None):
    """Apply a school_id filter to a SQLAlchemy query for tenant-scoped models."""
    resolved_school_id = school_id or require_current_school_id()
    resolved_model = model
    if resolved_model is None and getattr(query, "column_descriptions", None):
        resolved_model = query.column_descriptions[0].get("entity")

    if resolved_model is None or not hasattr(resolved_model, "school_id"):
        raise TenantContextError("filter_by_school requires a tenant-scoped model.")

    return query.filter(resolved_model.school_id == resolved_school_id)


def load_tenant_context():
    """Load tenant data for the current request without silently defaulting a school."""
    _user_module_cache.clear()
    g.school_id = session.get("school_id")
    g.current_school = None
    g.current_subscription = None
    g.subscription = None
    g.subscription_state = None
    g.current_entitled_module_codes = None
    g.current_entitled_module_subscription_id = object()
