from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from datetime import datetime
from decimal import Decimal
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.finance.services import FinanceService
from blueprints.procurement.services import ProcurementService

finance_bp = Blueprint('finance', __name__)

@finance_bp.route('/admin/finance')
@finance_bp.route('/admin/finance/dashboard')
@login_required
@admin_required
def finance_dashboard():
    connection = get_db_connection()
    service = FinanceService(connection)
    try:
        stats = service.get_dashboard_summary()
        accounts = service.get_accounts()
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT ft.*, SUM(le.debit) as total_debit, SUM(le.credit) as total_credit, u.username as created_by_name
                FROM finance_transactions ft
                JOIN finance_ledger_entries le ON ft.id = le.transaction_id
                LEFT JOIN users u ON ft.created_by = u.userNo
                WHERE ft.school_id = %s
                GROUP BY ft.id
                ORDER BY ft.id DESC LIMIT 10
            """, (service.school_id,))
            recent_txns = cursor.fetchall()
        return render_template('finance_dashboard.html', stats=stats, accounts=accounts, recent_txns=recent_txns)
    finally:
        connection.close()

@finance_bp.route('/admin/finance/vouchers', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_vouchers():
    connection = get_db_connection()
    service = FinanceService(connection)
    proc_service = ProcurementService(connection, service.school_id)

    if request.method == 'POST':
        try:
            service.create_voucher(
                payee=request.form.get('payee_name'),
                amount=Decimal(request.form.get('amount') or 0),
                mode=request.form.get('payment_mode', 'CASH'),
                account_id=int(request.form.get('account_id')),
                cheque_no=request.form.get('cheque_no', ''),
                description=request.form.get('description'),
                user_id=session['userNo'],
                supplier_id=int(request.form.get('supplier_id')) if request.form.get('supplier_id') else None,
                po_id=int(request.form.get('po_id')) if request.form.get('po_id') else None,
                vat=Decimal(request.form.get('vat_amount') or 0),
                wht=Decimal(request.form.get('wht_amount') or 0)
            )
            flash("✓ Voucher created and submitted for verification.", "success")
        except Exception as e:
            flash(str(e), "error")

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                v.*, u.username as created_by_name, a.name as account_name, s.company as supplier_name, po.po_number, 'VOUCHER' as source_type
            FROM finance_payment_vouchers v
            LEFT JOIN users u ON v.created_by = u.userNo
            LEFT JOIN finance_accounts a ON v.account_id = a.id
            LEFT JOIN suppliers s ON v.supplier_id = s.supplierID
            LEFT JOIN purchase_orders po ON v.po_id = po.id
            WHERE v.school_id = %s
            ORDER BY v.created_at DESC
        """, (service.school_id,))
        vouchers = cursor.fetchall()

        cursor.execute("SELECT id, po_number, supplier_id, total_amount FROM purchase_orders WHERE payment_status != 'PAID' AND status = 'RECEIVED' AND school_id = %s", (service.school_id,))
        pending_pos = cursor.fetchall()

    accounts = service.get_accounts()
    suppliers = proc_service.get_suppliers(active_only=False)
    connection.close()
    return render_template('manage_vouchers.html', vouchers=vouchers, accounts=accounts, suppliers=suppliers, pending_pos=pending_pos)

@finance_bp.route('/admin/finance/vouchers/<int:voucher_id>/verify', methods=['POST'])
@login_required
@admin_required
def verify_voucher(voucher_id):
    connection = get_db_connection()
    service = FinanceService(connection)
    try:
        service.verify_voucher(voucher_id, session['userNo'])
        flash("✓ Voucher verified successfully.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('finance.manage_vouchers'))

@finance_bp.route('/admin/finance/vouchers/<int:voucher_id>/authorize', methods=['POST'])
@login_required
@admin_required
def authorize_voucher(voucher_id):
    connection = get_db_connection()
    service = FinanceService(connection)
    try:
        service.authorize_voucher(voucher_id, session['userNo'], int(request.form.get('source_account_id')) if request.form.get('source_account_id') else None)
        flash("✓ Voucher authorized and posted to ledger.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('finance.manage_vouchers'))

@finance_bp.route('/admin/finance/vouchers/<int:voucher_id>/print_cheque')
@login_required
@admin_required
def print_cheque(voucher_id):
    connection = get_db_connection()
    service = FinanceService(connection)
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM finance_payment_vouchers WHERE id = %s AND school_id = %s", (voucher_id, service.school_id))
        voucher = cursor.fetchone()
    if voucher:
        voucher['amount_in_words'] = service.amount_to_words(voucher['amount'])
    connection.close()
    return render_template('print_cheque.html', voucher=voucher)

@finance_bp.route('/admin/finance/vouchers/<int:voucher_id>/print')
@login_required
@admin_required
def print_payment_voucher(voucher_id):
    connection = get_db_connection()
    service = FinanceService(connection)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT v.*, a.name as account_name, u1.username as created_by_name, u2.username as verified_by_name, u3.username as authorized_by_name, po.po_number
            FROM finance_payment_vouchers v
            LEFT JOIN finance_accounts a ON v.account_id = a.id
            LEFT JOIN users u1 ON v.created_by = u1.userNo
            LEFT JOIN users u2 ON v.verified_by = u2.userNo
            LEFT JOIN users u3 ON v.authorized_by = u3.userNo
            LEFT JOIN purchase_orders po ON v.po_id = po.id
            WHERE v.id = %s AND v.school_id = %s
        """, (voucher_id, service.school_id))
        voucher = cursor.fetchone()
    if not voucher: flash("Voucher not found.", "error"); connection.close(); return redirect(url_for('finance.manage_vouchers'))
    amount_in_words = service.amount_to_words(voucher['amount'])
    connection.close()
    return render_template('print_payment_voucher.html', voucher=voucher, amount_in_words=amount_in_words)

@finance_bp.route('/admin/finance/budgets', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_budgets():
    connection = get_db_connection()
    service = FinanceService(connection)
    if request.method == 'POST':
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO finance_budgets (account_id, annual_amount, fiscal_year, created_by, school_id)
                    VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE annual_amount = %s
                """, (int(request.form.get('account_id')), Decimal(request.form.get('amount')), int(request.form.get('fiscal_year')), session['userNo'], service.school_id, Decimal(request.form.get('amount'))))
            connection.commit()
            flash("✓ Budget updated.", "success")
        except Exception as e: flash(str(e), "error")

    with connection.cursor() as cursor:
        cursor.execute("SELECT b.*, a.name as account_name, a.code as account_code FROM finance_budgets b JOIN finance_accounts a ON b.account_id = a.id WHERE b.school_id = %s ORDER BY b.fiscal_year DESC, a.code ASC", (service.school_id,))
        budgets = cursor.fetchall()
    accounts = service.get_accounts()
    connection.close()
    return render_template('manage_budgets.html', budgets=budgets, accounts=accounts)

@finance_bp.route('/admin/finance/reports/trial_balance')
@login_required
@admin_required
def trial_balance_report():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection(); service = FinanceService(connection)
    data = service.get_trial_balance(date)
    connection.close()
    return render_template('report_trial_balance.html', data=data, date=date)

@finance_bp.route('/admin/finance/reports/income_statement')
@login_required
@admin_required
def income_statement_report():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-01'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection(); service = FinanceService(connection)
    try:
        data = service.get_income_statement(start_date, end_date)
        return render_template('report_income_statement.html', data=data, start_date=start_date, end_date=end_date)
    finally: connection.close()

@finance_bp.route('/admin/finance/reports/balance_sheet')
@login_required
@admin_required
def balance_sheet_report():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection(); service = FinanceService(connection)
    try:
        data = service.get_balance_sheet(date)
        return render_template('report_balance_sheet.html', data=data, date=date)
    finally: connection.close()
