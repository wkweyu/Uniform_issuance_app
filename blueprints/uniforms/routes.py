from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from core.permissions import login_required, admin_required
from core.db import get_db_connection
from core.helpers import get_current_term_and_year, generate_receipt_number, get_class_name
from datetime import datetime

uniforms_bp = Blueprint('uniforms', __name__)

@uniforms_bp.route('/uniform_dashboard')
@login_required
def uniform_dashboard():
    return render_template('uniform_dashboard.html')

@uniforms_bp.route('/issue_uniform', methods=['GET', 'POST'])
@login_required
def issue_uniform():
    if request.method == 'GET':
        return render_template('issue_search.html')

    admno = request.form.get('admno')
    if not admno:
        flash('Please enter an admission number', 'error')
        return redirect(url_for('uniforms.issue_uniform'))

    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1

    try:
        cursor.execute("SELECT * FROM studentinfo WHERE AdmNo = %s AND school_id = %s", (admno, school_id))
        student = cursor.fetchone()
        if not student:
            flash(f"Student {admno} not found", "error")
            return redirect(url_for('uniforms.issue_uniform'))

        term, year = get_current_term_and_year()
        class_name = get_class_name(cursor, admno, year)

        # Get items for this class group
        from core.helpers import CLASS_GROUPS
        class_group = CLASS_GROUPS.get(class_name, 'Other')
        cursor.execute("SELECT * FROM uniform_prices WHERE class_group = %s AND school_id = %s", (class_group, school_id))
        items = cursor.fetchall()

        return render_template('issue_form.html', student=student, items=items, term=term, year=year, class_name=class_name)
    finally:
        connection.close()

@uniforms_bp.route('/submit_issuance', methods=['POST'])
@login_required
def submit_issuance():
    admno = request.form.get('admno')
    term, year = get_current_term_and_year()
    school_id = g.school_id or 1

    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        items_data = request.form.getlist('items[]')
        quantities = request.form.getlist('quantities[]')
        prices = request.form.getlist('prices[]')

        receipt_no = generate_receipt_number(year, school_id)

        for i in range(len(items_data)):
            if int(quantities[i]) > 0:
                cursor.execute("""
                    INSERT INTO uniform_receipts (receipt_no, admno, item_name, quantity, unit_price, total_price, term, yr, date_issued, issued_by, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
                """, (receipt_no, admno, items_data[i], quantities[i], prices[i], float(quantities[i])*float(prices[i]), term, year, session['userNo'], school_id))

                # Update stock
                cursor.execute("UPDATE uniform_prices SET stock = stock - %s WHERE item_name = %s AND school_id = %s", (quantities[i], items_data[i], school_id))

        connection.commit()
        flash(f"Uniform issued successfully. Receipt: {receipt_no}", "success")
        return redirect(url_for('uniforms.receipt', receipt_no=receipt_no))
    except Exception as e:
        connection.rollback()
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('uniforms.issue_uniform'))
    finally:
        connection.close()

@uniforms_bp.route('/receipt/<receipt_no>')
@login_required
def receipt(receipt_no):
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1
    cursor.execute("""
        SELECT r.*, s.FName, s.SName
        FROM uniform_receipts r
        JOIN studentinfo s ON r.admno = s.AdmNo
        WHERE r.receipt_no = %s AND r.school_id = %s
    """, (receipt_no, school_id))
    items = cursor.fetchall()
    connection.close()
    return render_template('receipt.html', items=items, receipt_no=receipt_no)

@uniforms_bp.route('/manage_uniform_items', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_uniform_items():
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1

    if request.method == 'POST':
        item_name = request.form.get('item_name')
        price = request.form.get('price')
        class_group = request.form.get('class_group')

        cursor.execute("""
            INSERT INTO uniform_prices (item_name, price, class_group, school_id)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE price = %s
        """, (item_name, price, class_group, school_id, price))
        connection.commit()
        flash("Item updated.", "success")

    cursor.execute("SELECT * FROM uniform_prices WHERE school_id = %s", (school_id,))
    items = cursor.fetchall()
    connection.close()
    return render_template('manage_uniform_items.html', items=items)
