from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g
from core.permissions import login_required
from core.db import get_db_connection

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/reports/dashboard')
@login_required
def reports_dashboard():
    return render_template('reports_dashboard.html')

@reports_bp.route('/reports/student_history/<int:admno>')
@login_required
def student_history(admno):
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1
    cursor.execute("SELECT * FROM uniform_receipts WHERE admno = %s AND school_id = %s", (admno, school_id))
    history = cursor.fetchall()
    connection.close()
    return render_template('report_student_history.html', history=history, admno=admno)

@reports_bp.route('/reports/item_totals')
@login_required
def item_totals():
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1
    cursor.execute("""
        SELECT item_name, SUM(quantity) as total_qty, SUM(total_price) as total_val
        FROM uniform_receipts
        WHERE school_id = %s
        GROUP BY item_name
    """, (school_id,))
    totals = cursor.fetchall()
    connection.close()
    return render_template('report_item_totals.html', totals=totals)

@reports_bp.route('/reports/receipts_register')
@login_required
def receipts_register():
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1
    cursor.execute("SELECT * FROM uniform_receipts WHERE school_id = %s ORDER BY date_issued DESC", (school_id,))
    receipts = cursor.fetchall()
    connection.close()
    return render_template('report_receipts_register.html', receipts=receipts)

@reports_bp.route("/reports/student_search", methods=["GET", "POST"])
@login_required
def student_search():
    results = []
    search_term = ""
    if request.method == "POST":
        search_term = request.form.get("search_term", "").strip()
        if not search_term:
            flash("Please enter an admission number or student name.", "error")
            return redirect(url_for("reports.student_search"))

        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            school_id = g.school_id or 1
            # Note: adjusted table names to match common patterns if different
            cursor.execute("""
                SELECT DISTINCT s.AdmNo, s.FName, s.MName, s.SName,
                                 c.class_name
                FROM studentinfo s
                LEFT JOIN class_allocation a ON s.AdmNo = a.student_id AND s.school_id = a.school_id
                LEFT JOIN classes c ON a.class_id = c.classID AND a.school_id = c.school_id
                WHERE (s.AdmNo LIKE %s
                     OR CONCAT(s.FName, ' ', COALESCE(s.MName, ''), ' ', s.SName) LIKE %s)
                  AND s.school_id = %s
                ORDER BY s.FName, s.SName
                LIMIT 50
            """, (f"%{search_term}%", f"%{search_term}%", school_id))
            results = cursor.fetchall()
        finally:
            connection.close()

    return render_template("report_student_search.html", results=results, search_term=search_term)
