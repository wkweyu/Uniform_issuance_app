from functools import wraps
from flask import abort, g, session, redirect, url_for
from extensions import db
from .services.access import get_platform_access_settings, platform_user_has_permission


def get_current_platform_user():
    if getattr(g, 'platform_user_loaded', False):
        return g.platform_current_user

    from .models import PlatformUser

    user_id = session.get('platform_user_id')
    if not user_id:
        g.platform_current_user = None
        g.platform_user_loaded = True
        return None
    g.platform_current_user = db.session.get(PlatformUser, user_id)
    g.platform_user_loaded = True
    return g.platform_current_user


def platform_rollout_allows(user):
    if user is None:
        return False
    if getattr(user, 'is_super_admin', None) and user.is_super_admin():
        return True

    access_settings = get_platform_access_settings()
    rollout_mode = access_settings['rollout_mode']
    if rollout_mode == 'open':
        return True

    allowed_emails = set(access_settings['allowed_emails'])
    allowed_roles = set(access_settings['allowed_roles'])
    email = (getattr(user, 'email', None) or '').strip().lower()
    role_name = (getattr(user, 'role', None) or '').strip().lower()

    if rollout_mode == 'allowlist':
        return email in allowed_emails or role_name in allowed_roles
    if rollout_mode == 'roles':
        return role_name in allowed_roles
    return True


def platform_required(role=None, permission=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_platform_user()
            if not user:
                return redirect(url_for('platform.login'))
            if not platform_rollout_allows(user):
                abort(403)
            if role and user.role != role and not user.is_super_admin():
                abort(403)
            if permission and not platform_user_has_permission(user, permission):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def tenant_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Ensure a tenant (school) is selected in session
        if 'school_id' not in session and not session.get('platform_user_id'):
            return redirect(url_for('platform.login'))
        return fn(*args, **kwargs)
    return wrapper
