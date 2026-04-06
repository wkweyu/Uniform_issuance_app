from flask import render_template, request, redirect, url_for, session
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash
from core.flash_messages import flash_message
from ..decorators import platform_required, platform_rollout_allows
from ..models import PlatformUser
from ..services.audit import log as audit_log
from ..services.audit import list_logs
from ..services.access import (
    available_platform_roles,
    describe_user_school_scope,
    get_platform_access_settings,
    portfolio_school_ids_from_scope,
)
from ..services.security import (
    check_platform_login_guard,
    handle_platform_rollout_denied,
    handle_platform_login_failure,
    handle_platform_login_success,
    process_impersonation_signal,
)


def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        from platform_bp.models import PlatformUser

        normalized_email = (email or '').strip().lower()
        user = PlatformUser.query.filter_by(email=normalized_email).first()
        allowed, blocked_message = check_platform_login_guard(normalized_email, user)
        if not allowed:
            flash_message(blocked_message, 'error')
            return render_template('platform/login.html')

        if user and user.password_hash and check_password_hash(user.password_hash, password):
            if not platform_rollout_allows(user):
                handle_platform_rollout_denied(user, get_platform_access_settings())
                flash_message('Platform access is not enabled for this account during the current rollout.', 'error')
                return render_template('platform/login.html')
            session['platform_user_id'] = user.id
            try:
                from platform_bp.models import db
                user.last_login_at = db.func.current_timestamp()
                db.session.commit()
            except Exception:
                db.session.rollback()
            try:
                handle_platform_login_success(user)
            except Exception:
                from platform_bp.models import db
                db.session.rollback()
            return redirect(url_for('platform.index'))
        try:
            handle_platform_login_failure(normalized_email, user=user)
        except Exception:
            from platform_bp.models import db
            db.session.rollback()
        flash_message('Invalid credentials', 'error')
    return render_template('platform/login.html')


def logout():
    platform_user_id = session.get('platform_user_id')
    if platform_user_id:
        user = PlatformUser.query.get(platform_user_id)
        try:
            audit_log(
                actor_user_id=platform_user_id,
                action='platform_logout',
                target_table='platform_users',
                target_id=platform_user_id,
                school_id=user.assigned_school_id if user else None,
            )
        except Exception:
            from app import db
            db.session.rollback()
    session.pop('platform_user_id', None)
    return redirect(url_for('platform.login'))


def _load_school_directory():
    from app import School

    schools = School.query.order_by(School.name.asc()).all()
    return schools, {school.id: school for school in schools}


def _normalize_email(value):
    return (value or '').strip().lower()


def _validate_password_policy(password):
    if not password:
        return True, None
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter."
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number."
    return True, None


def _parse_user_scope_form(schools):
    valid_school_ids = {school.id for school in schools}
    assigned_school_value = request.form.get('assigned_school') or None
    assigned_school_id = None
    if assigned_school_value:
        try:
            assigned_school_id = int(assigned_school_value)
        except (TypeError, ValueError):
            raise ValueError('Assigned school is invalid.')
        if assigned_school_id not in valid_school_ids:
            raise ValueError('Assigned school is invalid.')

    portfolio_school_ids = []
    for raw_school_id in request.form.getlist('portfolio_school_ids'):
        if raw_school_id in (None, ''):
            continue
        try:
            school_id = int(raw_school_id)
        except (TypeError, ValueError):
            raise ValueError('Portfolio scope contains an invalid school.')
        if school_id not in valid_school_ids:
            raise ValueError('Portfolio scope contains an invalid school.')
        if school_id not in portfolio_school_ids:
            portfolio_school_ids.append(school_id)

    portfolio_scope = {'school_ids': portfolio_school_ids} if portfolio_school_ids else None
    return assigned_school_id, portfolio_scope


def _user_matches_filters(user, *, role_filter=None, status_filter=None, school_filter=None, search=None):
    if role_filter and user.role != role_filter:
        return False
    if status_filter == 'active' and not user.is_active:
        return False
    if status_filter == 'inactive' and user.is_active:
        return False
    if school_filter is not None:
        scoped_school_ids = portfolio_school_ids_from_scope(user.portfolio_scope)
        if user.assigned_school_id != school_filter and school_filter not in scoped_school_ids:
            return False
    if search:
        haystacks = [
            (user.email or '').lower(),
            (user.name or '').lower(),
            (user.role or '').lower(),
        ]
        if not any(search in haystack for haystack in haystacks):
            return False
    return True


def _build_user_list_context():
    users = PlatformUser.query.order_by(PlatformUser.email.asc()).all()
    schools, school_lookup = _load_school_directory()

    role_filter = (request.args.get('role') or '').strip().lower() or None
    status_filter = (request.args.get('status') or '').strip().lower() or None
    school_filter = request.args.get('school_id', type=int)
    search = (request.args.get('q') or '').strip().lower() or None

    filtered_users = [
        user for user in users
        if _user_matches_filters(
            user,
            role_filter=role_filter,
            status_filter=status_filter,
            school_filter=school_filter,
            search=search,
        )
    ]
    user_scope_lookup = {user.id: describe_user_school_scope(user, school_lookup) for user in filtered_users}
    creator_ids = [user.created_by for user in filtered_users if user.created_by]
    creator_lookup = {
        creator.id: creator
        for creator in PlatformUser.query.filter(PlatformUser.id.in_(creator_ids)).all()
    } if creator_ids else {}
    return {
        'users': filtered_users,
        'schools': schools,
        'school_lookup': school_lookup,
        'user_scope_lookup': user_scope_lookup,
        'creator_lookup': creator_lookup,
        'filters': {
            'role': role_filter or '',
            'status': status_filter or '',
            'school_id': school_filter,
            'q': request.args.get('q', '').strip(),
        },
        'role_options': available_platform_roles(),
    }


def _render_user_form(*, template_user=None, schools=None):
    schools = schools or _load_school_directory()[0]
    selected_portfolio_school_ids = portfolio_school_ids_from_scope(getattr(template_user, 'portfolio_scope', None)) if template_user else []
    recent_audit_logs = list_logs(target_table='platform_users', target_id=template_user.id, limit=10) if template_user else []
    actor_ids = [log.actor_user_id for log in recent_audit_logs if log.actor_user_id]
    actor_lookup = {
        actor.id: actor
        for actor in PlatformUser.query.filter(PlatformUser.id.in_(actor_ids)).all()
    } if actor_ids else {}
    return render_template(
        'platform/users_create.html',
        role_options=available_platform_roles(),
        schools=schools,
        editing_user=template_user,
        selected_portfolio_school_ids=selected_portfolio_school_ids,
        recent_audit_logs=recent_audit_logs,
        audit_actor_lookup=actor_lookup,
    )


@platform_required(permission='user_admin')
def list_users():
    return render_template('platform/users_list.html', **_build_user_list_context())


@platform_required(role='super_admin')
def create_user():
    schools, _ = _load_school_directory()

    if request.method == 'POST':
        email = _normalize_email(request.form.get('email'))
        password = request.form.get('password')
        role = request.form.get('role', 'support')
        from ..models import PlatformUser
        if PlatformUser.query.filter_by(email=email).first():
            flash_message('User exists', 'warning')
            return redirect(url_for('platform.create_user'))
        if not email:
            flash_message('Email is required', 'warning')
            return _render_user_form(schools=schools)
        if not password:
            flash_message('Password is required', 'warning')
            return _render_user_form(schools=schools)
        try:
            assigned_school_id, portfolio_scope = _parse_user_scope_form(schools)
        except ValueError as exc:
            flash_message(str(exc), 'warning')
            return _render_user_form(schools=schools)

        is_valid_pw, pw_error = _validate_password_policy(password)
        if not is_valid_pw:
            flash_message(pw_error, 'warning')
            return _render_user_form(schools=schools)

        pw_hash = generate_password_hash(password)
        user = PlatformUser(
            email=email,
            password_hash=pw_hash,
            role=role,
            assigned_school_id=assigned_school_id,
            portfolio_scope=portfolio_scope,
            is_active=True,
            created_by=session.get('platform_user_id'),
        )
        from app import db
        db.session.add(user)
        db.session.commit()
        audit_log(
            actor_user_id=session.get('platform_user_id'),
            action='platform_user_created',
            target_table='platform_users',
            target_id=user.id,
            school_id=user.assigned_school_id,
            changes={
                'email': user.email,
                'role': user.role,
                'assigned_school_id': user.assigned_school_id,
                'portfolio_scope': user.portfolio_scope or {},
            },
        )
        flash_message('User created', 'success')
        return redirect(url_for('platform.list_users'))
    return _render_user_form(schools=schools)


@platform_required(role='super_admin')
def edit_user(user_id):
    from app import db

    user = db.session.get(PlatformUser, user_id)
    if user is None:
        flash_message('User not found', 'warning')
        return redirect(url_for('platform.list_users'))

    schools, _ = _load_school_directory()
    if request.method == 'POST':
        email = _normalize_email(request.form.get('email'))
        password = request.form.get('password')
        role = request.form.get('role', user.role)
        is_active = request.form.get('is_active') == 'on'

        if not email:
            flash_message('Email is required', 'warning')
            return _render_user_form(template_user=user, schools=schools)

        existing_user = PlatformUser.query.filter(PlatformUser.email == email, PlatformUser.id != user.id).first()
        if existing_user is not None:
            flash_message('Another user already uses that email address', 'warning')
            return _render_user_form(template_user=user, schools=schools)

        try:
            assigned_school_id, portfolio_scope = _parse_user_scope_form(schools)
        except ValueError as exc:
            flash_message(str(exc), 'warning')
            return _render_user_form(template_user=user, schools=schools)

        if password:
            is_valid_pw, pw_error = _validate_password_policy(password)
            if not is_valid_pw:
                flash_message(pw_error, 'warning')
                return _render_user_form(template_user=user, schools=schools)

        mfa_enabled = request.form.get('mfa_enabled') == 'on'

        previous_state = {
            'email': user.email,
            'role': user.role,
            'is_active': user.is_active,
            'mfa_enabled': user.mfa_enabled,
            'assigned_school_id': user.assigned_school_id,
            'portfolio_scope': user.portfolio_scope or {},
        }

        user.email = email
        user.role = role
        user.is_active = is_active
        user.mfa_enabled = mfa_enabled
        user.assigned_school_id = assigned_school_id
        user.portfolio_scope = portfolio_scope
        if password:
            user.password_hash = generate_password_hash(password)

        db.session.commit()
        audit_log(
            actor_user_id=session.get('platform_user_id'),
            action='platform_user_updated',
            target_table='platform_users',
            target_id=user.id,
            school_id=user.assigned_school_id,
            changes={
                'previous': previous_state,
                'current': {
                    'email': user.email,
                    'role': user.role,
                    'is_active': user.is_active,
                    'assigned_school_id': user.assigned_school_id,
                    'portfolio_scope': user.portfolio_scope or {},
                    'password_reset': bool(password),
                },
            },
        )
        flash_message('User updated', 'success')
        return redirect(url_for('platform.list_users'))

    return _render_user_form(template_user=user, schools=schools)


@platform_required(permission='tenant_search')
def start_impersonation():
    tenant_user_no = request.form.get('tenant_user_no')
    if not tenant_user_no:
        flash_message('Missing tenant user id', 'warning')
        return redirect(url_for('platform.list_users'))
    from app import User
    from extensions import db
    tenant = db.session.get(User, int(tenant_user_no))
    if not tenant:
        flash_message('Tenant user not found', 'warning')
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
        audit_entry = audit_log(actor_user_id=original_platform_id, action='impersonation_start', target_table='users', target_id=tenant.userNo, school_id=tenant.school_id, changes={'impersonated_by': original_platform_id})
        process_impersonation_signal(original_platform_id, tenant.userNo, tenant.school_id, audit_entry_id=audit_entry.id)
    except Exception:
        pass

    flash_message(f'Impersonating user {tenant.username}', 'info')
    return redirect(url_for('platform.index'))


@platform_required(permission='tenant_search')
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

    flash_message('Stopped impersonation', 'info')
    return redirect(url_for('platform.list_users'))


def register_routes(bp):
    bp.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    bp.add_url_rule('/logout', endpoint='logout', view_func=logout)
    bp.add_url_rule('/users', endpoint='list_users', view_func=list_users)
    bp.add_url_rule('/users/create', endpoint='create_user', view_func=create_user, methods=['GET', 'POST'])
    bp.add_url_rule('/users/<int:user_id>/edit', endpoint='edit_user', view_func=edit_user, methods=['GET', 'POST'])
    bp.add_url_rule('/impersonate/start', endpoint='start_impersonation', view_func=start_impersonation, methods=['POST'])
    bp.add_url_rule('/impersonate/stop', endpoint='stop_impersonation', view_func=stop_impersonation, methods=['POST'])
