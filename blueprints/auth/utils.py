from functools import wraps
from flask import session, request, redirect, url_for, flash
from urllib.parse import quote
from werkzeug.security import check_password_hash
import hashlib

def verify_legacy_password(input_password, stored_password, user_id=None):
    if not stored_password:
        return False
    try:
        if check_password_hash(stored_password, input_password):
            return True
    except ValueError:
        pass
    md5_hash = hashlib.md5(input_password.encode()).hexdigest()
    if stored_password == md5_hash:
        return True
    if stored_password == input_password:
        return True
    return False

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
