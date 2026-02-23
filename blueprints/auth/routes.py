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
