from functools import wraps
from flask import session, request, redirect, url_for, g
from urllib.parse import quote
from core.flash_messages import flash_message
from core.tenancy import get_current_school_id


def _redirect_to_login():
    next_url = quote(request.url)
    return redirect(url_for('auth.login', next=next_url))


def _ensure_tenant_session():
    school_id = get_current_school_id()
    if not school_id:
        session.clear()
        flash_message("Your school session has expired. Please log in again.", "error")
        return None
    g.school_id = school_id
    return school_id

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            return _redirect_to_login()
        return f(*args, **kwargs)
    return decorated


def tenant_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            return _redirect_to_login()
        if _ensure_tenant_session() is None:
            return _redirect_to_login()
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            return _redirect_to_login()
        if _ensure_tenant_session() is None:
            return _redirect_to_login()
        if not session.get('is_admin', False):
            flash_message("Access denied. Admin privileges required.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            return _redirect_to_login()
        if _ensure_tenant_session() is None:
            return _redirect_to_login()
        if not session.get('is_super_admin', False):
            flash_message("Access denied. Super admin privileges required.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def permission_required(permission):
    """
    Check if the user has a specific permission.
    Currently uses is_admin as a proxy, but ready for full RBAC.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'userNo' not in session:
                return _redirect_to_login()
            if _ensure_tenant_session() is None:
                return _redirect_to_login()

            # Simple implementation: admins have all permissions for now
            if session.get('is_admin') or session.get('is_super_admin'):
                return f(*args, **kwargs)

            flash_message(f"Missing required permission: {permission}", "error")
            return redirect(url_for('index'))
        return decorated_function
    return decorator
