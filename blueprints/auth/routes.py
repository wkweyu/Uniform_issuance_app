from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from datetime import datetime, timedelta
from .utils import verify_legacy_password

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    from models import User, School

    if 'userNo' in session:
        return redirect(url_for('index'))

    next_url = request.args.get('next')

    if request.method == 'POST':
        school_code = request.form.get('school_code')
        username = request.form.get('username')
        password = request.form.get('password')

        if not school_code:
            flash("School code is required.", "error")
            return redirect(url_for('auth.login'))

        school = School.query.filter_by(code=school_code).first()
        if not school:
            flash("Invalid school code.", "error")
            return redirect(url_for('auth.login'))

        today = datetime.utcnow().date()
        if not school.is_active or (school.subscription_end and school.subscription_end < today):
            flash("School is inactive or subscription has expired.", "error")
            return redirect(url_for('auth.login'))

        user = User.query.filter_by(username=username, school_id=school.id).first()

        if not user or user.access_flag != 1:
            flash("Invalid username or password.", "error")
            return redirect(url_for('auth.login'))

        if not verify_legacy_password(password, user.pwd, user.userNo):
            flash("Invalid username or password.", "error")
            return redirect(url_for('auth.login'))

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

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('auth.login'))
