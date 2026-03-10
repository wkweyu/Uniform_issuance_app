from flask import render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from ..decorators import platform_required
from ..services.audit import log as audit_log


def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        # Use SQLAlchemy for dev/test compatibility
        from flask import current_app
        from platform_bp.models import PlatformUser, db
        user = PlatformUser.query.filter_by(email=email).first()
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            session['platform_user_id'] = user.id
            try:
                user.last_login_at = db.func.current_timestamp()
                db.session.commit()
            except Exception:
                db.session.rollback()
            return redirect(url_for('platform.index'))
        flash('Invalid credentials', 'danger')
    return render_template('platform/login.html')


def logout():
    session.pop('platform_user_id', None)
    return redirect(url_for('platform.login'))


@platform_required(role='platform_admin')
def list_users():
    users = PlatformUser.query.all()
    return render_template('platform/users_list.html', users=users)


@platform_required(role='platform_admin')
def create_user():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'support')
        assigned_school = request.form.get('assigned_school') or None
        from ..models import PlatformUser
        if PlatformUser.query.filter_by(email=email).first():
            flash('User exists', 'warning')
            return redirect(url_for('platform.create_user'))
        pw_hash = generate_password_hash(password)
        user = PlatformUser(email=email, password_hash=pw_hash, role=role, assigned_school_id=assigned_school)
        from app import db
        db.session.add(user)
        db.session.commit()
        flash('User created', 'success')
        return redirect(url_for('platform.list_users'))
    return render_template('platform/users_create.html')


@platform_required(role='platform_admin')
def start_impersonation():
    tenant_user_no = request.form.get('tenant_user_no')
    if not tenant_user_no:
        flash('Missing tenant user id', 'warning')
        return redirect(url_for('platform.list_users'))
    from app import User
    tenant = User.query.get(int(tenant_user_no))
    if not tenant:
        flash('Tenant user not found', 'warning')
        return redirect(url_for('platform.list_users'))

    original_platform_id = session.get('platform_user_id')
    # store original platform id to restore later
    session['original_platform_user_id'] = original_platform_id
    session['platform_impersonation'] = True

    # set tenant session values used by the app
    session['userNo'] = tenant.userNo
    session['school_id'] = tenant.school_id

    # audit log
    try:
        audit_log(actor_user_id=original_platform_id, action='impersonation_start', target_table='users', target_id=tenant.userNo, school_id=tenant.school_id, changes={'impersonated_by': original_platform_id})
    except Exception:
        pass

    flash(f'Impersonating user {tenant.username}', 'info')
    return redirect(url_for('platform.index'))


@platform_required(role='platform_admin')
def stop_impersonation():
    original = session.pop('original_platform_user_id', None)
    session.pop('platform_impersonation', None)
    # clear tenant session context
    tenant_user_no = session.pop('userNo', None)
    session.pop('school_id', None)

    # restore platform session if possible
    if original:
        session['platform_user_id'] = original

    # audit log
    try:
        audit_log(actor_user_id=original, action='impersonation_stop', target_table='users', target_id=tenant_user_no, school_id=None, changes={'restored_platform_user': original})
    except Exception:
        pass

    flash('Stopped impersonation', 'info')
    return redirect(url_for('platform.list_users'))


def register_routes(bp):
    bp.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    bp.add_url_rule('/logout', endpoint='logout', view_func=logout)
    bp.add_url_rule('/users', endpoint='list_users', view_func=list_users)
    bp.add_url_rule('/users/create', endpoint='create_user', view_func=create_user, methods=['GET', 'POST'])
    bp.add_url_rule('/impersonate/start', endpoint='start_impersonation', view_func=start_impersonation, methods=['POST'])
    bp.add_url_rule('/impersonate/stop', endpoint='stop_impersonation', view_func=stop_impersonation, methods=['POST'])
