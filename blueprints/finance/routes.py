from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from datetime import datetime
from decimal import Decimal, InvalidOperation
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.finance.services import FinanceService, FinanceError
from blueprints.procurement.services import ProcurementService

finance_bp = Blueprint('finance', __name__)


def _parse_required_int(value, field_name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} is required and must be a valid integer.")


def _parse_optional_int(value, field_name):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid integer.")


def _parse_decimal(value, field_name, default='0'):
    try:
        return Decimal(value if value not in (None, '') else default)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")

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
        recent_txns = service.get_recent_transactions(limit=10)
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
                amount=_parse_decimal(request.form.get('amount'), 'amount'),
                mode=request.form.get('payment_mode', 'CASH'),
                account_id=_parse_required_int(request.form.get('account_id'), 'account_id'),
                cheque_no=request.form.get('cheque_no', ''),
                description=request.form.get('description'),
                user_id=session['userNo'],
                supplier_id=_parse_optional_int(request.form.get('supplier_id'), 'supplier_id'),
                po_id=_parse_optional_int(request.form.get('po_id'), 'po_id'),
                vat=_parse_decimal(request.form.get('vat_amount'), 'vat_amount'),
                wht=_parse_decimal(request.form.get('wht_amount'), 'wht_amount')
            )
            flash("Voucher created and submitted for verification.", "success")
        except (ValueError, FinanceError) as e:
            flash(str(e), "error")
        except Exception as e:
            flash(str(e), "error")

    pending_pos = service.get_pending_purchase_orders()
    vouchers = service.get_vouchers()
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
        flash("Voucher verified successfully.", "success")
    except FinanceError as e: flash(str(e), "error")
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
        source_account_id = request.form.get('source_account_id')
        service.authorize_voucher(
            voucher_id,
            session['userNo'],
            _parse_optional_int(source_account_id, 'source_account_id'),
        )
        flash("Voucher authorized and posted to ledger.", "success")
    except (ValueError, FinanceError) as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('finance.manage_vouchers'))

@finance_bp.route('/admin/finance/vouchers/<int:voucher_id>/print_cheque')
@login_required
@admin_required
def print_cheque(voucher_id):
    connection = get_db_connection()
    service = FinanceService(connection)
    voucher = service.get_voucher_for_cheque(voucher_id)
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
    voucher = service.get_voucher_for_print(voucher_id)
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
            service.upsert_budget(
                account_id=_parse_required_int(request.form.get('account_id'), 'account_id'),
                annual_amount=_parse_decimal(request.form.get('amount'), 'amount'),
                fiscal_year=_parse_required_int(request.form.get('fiscal_year'), 'fiscal_year'),
                created_by=session['userNo'],
            )
            flash("Budget updated.", "success")
        except (ValueError, FinanceError) as e:
            flash(str(e), "error")
        except Exception as e: flash(str(e), "error")

    budgets = service.get_budgets()
    accounts = service.get_accounts()
    connection.close()
    return render_template('manage_budgets.html', budgets=budgets, accounts=accounts)


@finance_bp.route('/admin/finance/payment-mode-accounts', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_payment_mode_receiving_accounts():
    connection = get_db_connection()
    service = FinanceService(connection)
    try:
        if request.method == 'POST':
            service.configure_payment_mode_receiving_account(
                payment_mode=request.form.get('payment_mode'),
                account_id=_parse_required_int(request.form.get('account_id'), 'account_id'),
                configured_by=session['userNo'],
                is_active=request.form.get('is_active') == 'on',
            )
            flash('Receiving account configuration saved.', 'success')

        return render_template(
            'manage_payment_mode_receiving_accounts.html',
            mappings=service.get_payment_mode_receiving_accounts(),
            accounts=service.get_accounts(),
            payment_modes=('CASH', 'MPESA', 'BANK_TRANSFER', 'CHEQUE'),
        )
    except (ValueError, FinanceError) as e:
        flash(str(e), 'error')
        return redirect(url_for('finance.manage_payment_mode_receiving_accounts'))
    finally:
        connection.close()


@finance_bp.route('/admin/finance/cashier-sessions', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_cashier_sessions():
    connection = get_db_connection()
    service = FinanceService(connection)
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            cashier_user_id = session['userNo']
            if action == 'open':
                service.open_cashier_session(cashier_user_id, opened_by=session['userNo'])
                flash('Cashier session opened.', 'success')
            elif action == 'close':
                result = service.close_cashier_session(
                    session_id=_parse_required_int(request.form.get('session_id'), 'session_id'),
                    cashier_user_id=cashier_user_id,
                    actual_cash=_parse_decimal(request.form.get('actual_cash'), 'actual_cash'),
                    closed_by=session['userNo'],
                    notes=request.form.get('notes', ''),
                )
                message = f"Session closed. Expected: {result['expected_cash']:.2f}; variance: {result['variance']:.2f}."
                if result['status'] == 'PENDING_APPROVAL':
                    message += ' Supervisor approval is required.'
                flash(message, 'success')
            elif action == 'approve':
                service.approve_cashier_session_variance(
                    _parse_required_int(request.form.get('session_id'), 'session_id'), session['userNo']
                )
                flash('Cashier-session variance approved.', 'success')
            else:
                raise ValueError('Unknown cashier-session action.')
            return redirect(url_for('finance.manage_cashier_sessions'))

        return render_template(
            'manage_cashier_sessions.html',
            open_session=service.get_open_cashier_session(session['userNo']),
            sessions=service.get_cashier_sessions(),
        )
    except (ValueError, FinanceError) as e:
        flash(str(e), 'error')
        return redirect(url_for('finance.manage_cashier_sessions'))
    finally:
        connection.close()


@finance_bp.route('/admin/finance/reports/cashier-sessions')
@login_required
@admin_required
def cashier_session_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status = request.args.get('status')
    cashier_user_id = _parse_optional_int(request.args.get('cashier_user_id'), 'cashier_user_id')
    connection = get_db_connection()
    service = FinanceService(connection)
    try:
        records = service.get_cashier_session_register(start_date, end_date, status, cashier_user_id)
        return render_template(
            'cashier_session_report.html', records=records, start_date=start_date or '',
            end_date=end_date or '', status=status or '', cashier_user_id=cashier_user_id or '',
        )
    finally:
        connection.close()

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
