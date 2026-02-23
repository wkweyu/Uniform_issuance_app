from functools import wraps
from flask import session, request, redirect, url_for, flash, g
from urllib.parse import quote

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            next_url = quote(request.url)
            return redirect(url_for('auth.login', next=next_url))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            next_url = quote(request.url)
            return redirect(url_for('auth.login', next=next_url))
        if not session.get('is_admin', False):
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            next_url = quote(request.url)
            return redirect(url_for('auth.login', next=next_url))
        if not session.get('is_super_admin', False):
            flash("Access denied. Super admin privileges required.", "error")
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
                return redirect(url_for('auth.login', next=quote(request.url)))

            # Simple implementation: admins have all permissions for now
            if session.get('is_admin') or session.get('is_super_admin'):
                return f(*args, **kwargs)

            flash(f"Missing required permission: {permission}", "error")
            return redirect(url_for('index'))
        return decorated_function
    return decorator
