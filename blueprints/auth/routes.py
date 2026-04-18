from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from core.permissions import login_required, admin_required, super_admin_required
from datetime import datetime, timedelta
from .services import AuthService
import os

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'userNo' in session:
        return redirect(url_for('index'))

    next_url = request.args.get('next')
    # Only allow relative paths for next_url
    if next_url and not next_url.startswith('/'):
        next_url = None

    if request.method == 'POST':
        service = AuthService()
        school_code = request.form.get('school_code')
        username = request.form.get('username')
        password = request.form.get('password')

        user, school_or_error = service.authenticate(school_code, username, password)

        if user:
            school = school_or_error
            session['userNo'] = user.userNo
            session['username'] = user.username
            session['staff_id'] = user.StaffID
            session['is_admin'] = bool(user.TA)
            session['is_super_admin'] = bool(user.TA == 2)
            session['school_id'] = school.id
            session['school_code'] = school.code
            session['school_name'] = school.name
            session['logged_in'] = True
            session.permanent = True
            current_app.permanent_session_lifetime = timedelta(hours=8)
            flash(f"Welcome {user.username}", "success")
            return redirect(next_url or url_for('index'))
        else:
            flash(school_or_error, "error")
            return redirect(url_for('auth.login', next=next_url))

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('auth.login'))

@auth_bp.route('/admin_settings')
@login_required
@admin_required
def admin_settings():
    """School-level admin settings hub page."""
    return render_template('admin_settings.html')


@auth_bp.route('/school_profile', methods=['GET', 'POST'])
@login_required
@admin_required
def school_profile():
    """Edit school name, logo, contact details."""
    from core.db import get_db_connection
    import pymysql
    school_id = session.get('school_id')
    connection = get_db_connection()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # Ensure school_settings row exists
            cursor.execute("SELECT * FROM school_settings WHERE school_id = %s", (school_id,))
            settings = cursor.fetchone()
            if not settings:
                cursor.execute(
                    "INSERT INTO school_settings (school_id, school_name) "
                    "SELECT id, name FROM schools WHERE id = %s", (school_id,))
                connection.commit()
                cursor.execute("SELECT * FROM school_settings WHERE school_id = %s", (school_id,))
                settings = cursor.fetchone()

            if request.method == 'POST':
                school_name = request.form.get('school_name', '').strip()
                address = request.form.get('address', '').strip()
                phone = request.form.get('phone', '').strip()
                email = request.form.get('email', '').strip()
                website = request.form.get('website', '').strip()
                motto = request.form.get('motto', '').strip()
                currency = request.form.get('currency', 'KES').strip()

                logo_path = settings.get('logo') or ''

                # Handle logo upload
                logo_file = request.files.get('logo')
                if logo_file and logo_file.filename:
                    allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
                    ext = logo_file.filename.rsplit('.', 1)[-1].lower() if '.' in logo_file.filename else ''
                    if ext not in allowed:
                        flash('Invalid image format. Use PNG, JPG, GIF, WebP, or SVG.', 'error')
                        return redirect(url_for('auth.school_profile'))
                    # Limit to 2MB
                    logo_file.seek(0, 2)
                    size = logo_file.tell()
                    logo_file.seek(0)
                    if size > 2 * 1024 * 1024:
                        flash('Logo must be under 2 MB.', 'error')
                        return redirect(url_for('auth.school_profile'))

                    filename = f"school_{school_id}_logo.{ext}"
                    upload_dir = os.path.join(current_app.static_folder, 'uploads', 'logos')
                    os.makedirs(upload_dir, exist_ok=True)
                    save_path = os.path.join(upload_dir, filename)
                    logo_file.save(save_path)
                    logo_path = f"uploads/logos/{filename}"

                cursor.execute(
                    "UPDATE school_settings SET school_name=%s, address=%s, phone=%s, "
                    "email=%s, website=%s, logo=%s, currency=%s WHERE school_id=%s",
                    (school_name, address, phone, email, website, logo_path, currency, school_id))
                # Also update schools.name for session consistency
                cursor.execute("UPDATE schools SET name=%s WHERE id=%s", (school_name, school_id))
                connection.commit()

                # Update session cache
                session['school_name'] = school_name
                session.pop('_school_settings', None)  # clear cached settings

                flash('School profile updated.', 'success')
                return redirect(url_for('auth.school_profile'))

        return render_template('school_profile.html', settings=settings)
    finally:
        connection.close()


@auth_bp.route('/manage_users', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_users():
    service = AuthService()
    school_id = session.get('school_id')
    
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'create':
                service.create_user(
                    school_id=school_id,
                    username=request.form.get('username'),
                    password=request.form.get('password'),
                    staff_id=request.form.get('staff_id'),
                    is_admin=bool(request.form.get('is_admin'))
                )
                flash("User created successfully.", "success")
            elif action == 'delete':
                user_id = request.form.get('user_id')
                service.delete_user(user_id, school_id)
                flash("User deleted successfully.", "success")
        except Exception as e:
            flash(str(e), "error")
            
    users = service.get_users(school_id)
    return render_template('manage_users.html', users=users)


@auth_bp.route('/manage_users/<int:user_id>/modules', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_user_modules(user_id):
    """Assign module-level access to a school user."""
    from core.db import get_db_connection
    from platform_bp.config.modules import MODULE_CATALOG

    school_id = session.get('school_id')
    service = AuthService()

    # Verify user belongs to this school
    from models import User
    target_user = User.query.filter_by(userNo=user_id, school_id=school_id).first()
    if not target_user:
        flash("User not found.", "error")
        return redirect(url_for('auth.manage_users'))

    if request.method == 'POST':
        selected_modules = request.form.getlist('modules')
        connection = get_db_connection()
        try:
            with connection.cursor() as cursor:
                # Clear existing grants
                cursor.execute(
                    "DELETE FROM user_module_access WHERE user_id = %s AND school_id = %s",
                    (user_id, school_id),
                )
                # Insert new grants
                for code in selected_modules:
                    cursor.execute(
                        "INSERT INTO user_module_access (user_id, school_id, module_code, granted_by) "
                        "VALUES (%s, %s, %s, %s)",
                        (user_id, school_id, code, session.get('userNo')),
                    )
            connection.commit()
            flash(f"Module access updated for {target_user.username}.", "success")
        except Exception as e:
            connection.rollback()
            flash(f"Error updating module access: {e}", "error")
        finally:
            connection.close()
        return redirect(url_for('auth.manage_user_modules', user_id=user_id))

    # GET: load current grants
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT module_code FROM user_module_access WHERE user_id = %s AND school_id = %s",
                (user_id, school_id),
            )
            granted = {r['module_code'] for r in cursor.fetchall()}
    finally:
        connection.close()

    modules = [
        {**m, 'granted': m['code'] in granted}
        for m in MODULE_CATALOG
    ]

    return render_template(
        'manage_user_modules.html',
        target_user=target_user,
        modules=modules,
        granted_count=len(granted),
    )
