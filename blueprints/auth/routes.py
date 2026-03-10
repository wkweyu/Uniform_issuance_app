from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from datetime import datetime, timedelta
from .services import AuthService

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'userNo' in session:
        return redirect(url_for('index'))

    next_url = request.args.get('next')

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
