from functools import wraps
from flask import session, redirect, url_for, abort


def platform_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # defer imports to avoid circular import during package initialization
            from .models import PlatformUser
            user_id = session.get('platform_user_id')
            if not user_id:
                return redirect(url_for('platform.login'))
            user = PlatformUser.query.get(user_id)
            if not user:
                return redirect(url_for('platform.login'))
            if role and user.role != role and not user.is_super_admin():
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
