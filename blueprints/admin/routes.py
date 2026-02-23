from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g
from core.permissions import login_required, admin_required
from core.db import get_db_connection

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/settings')
@login_required
@admin_required
def admin_settings():
    return render_template('admin_settings.html')

@admin_bp.route('/admin/term_dates', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_term_dates():
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1

    if request.method == 'POST':
        term_number = request.form.get('term_number')
        year = request.form.get('year')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        is_current = 1 if request.form.get('is_current') else 0

        if is_current:
            cursor.execute("UPDATE uniform_term_dates SET is_current = 0 WHERE school_id = %s", (school_id,))

        cursor.execute("""
            INSERT INTO uniform_term_dates (term_number, year, start_date, end_date, is_current, school_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (term_number, year, start_date, end_date, is_current, school_id))
        connection.commit()
        flash("Term dates saved successfully.", "success")

    cursor.execute("SELECT * FROM uniform_term_dates WHERE school_id = %s ORDER BY year DESC, term_number DESC", (school_id,))
    terms = cursor.fetchall()
    connection.close()
    return render_template('manage_term_dates.html', terms=terms)

@admin_bp.route('/current_term_status')
@login_required
def current_term_status():
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1
    cursor.execute("SELECT * FROM uniform_term_dates WHERE is_current = 1 AND school_id = %s", (school_id,))
    current_term = cursor.fetchone()
    connection.close()
    return render_template('current_term.html', current_term=current_term)

@admin_bp.route('/admin/manage_users', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_users():
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1

    if request.method == 'POST':
        username = request.form.get('username')
        staff_id = request.form.get('staff_id')
        password = request.form.get('password')
        is_admin = 1 if request.form.get('is_admin') else 0

        # Simple user creation for now, should use hashing in production
        cursor.execute("""
            INSERT INTO users (username, StaffID, pwd, TA, school_id, access_flag)
            VALUES (%s, %s, %s, %s, %s, 1)
        """, (username, staff_id, password, is_admin, school_id))
        connection.commit()
        flash("User created successfully.", "success")

    cursor.execute("SELECT * FROM users WHERE school_id = %s", (school_id,))
    users = cursor.fetchall()
    connection.close()
    return render_template('manage_users.html', users=users)
