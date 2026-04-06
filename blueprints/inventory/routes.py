from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from extensions import csrf
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.inventory.services import InventoryService
from blueprints.classes.services import ClassManagementService
from datetime import datetime

inventory_bp = Blueprint('inventory', __name__)


def _required_text(value, field_name):
    parsed = (value or '').strip()
    if not parsed:
        raise ValueError(f"{field_name} is required.")
    return parsed


def _required_int(value, field_name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} is required and must be a valid integer.")


def _parse_float(value, field_name, default=0):
    try:
        return float(value if value not in (None, '') else default)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")

@inventory_bp.route('/admin/add_uniform_item', methods=['POST'])
@login_required
@admin_required
def add_uniform_item():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        service.add_uniform_item(_required_text(request.form.get('item_name'), 'item_name'), request.form.getlist('class_groups[]'))
        flash("Item added.", "success")
    except ValueError as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(request.referrer or url_for('index'))

@inventory_bp.route('/admin/delete_uniform_item', methods=['POST'])
@login_required
@admin_required
def delete_uniform_item():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        data = request.get_json(silent=True) or {}
        if not data.get('item_name'):
            return jsonify({'success': False, 'message': 'item_name is required.'}), 400
        service.delete_uniform_item(data.get('item_name'))
        return jsonify({'success': True})
    except ValueError as e: return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500
    finally: connection.close()

@inventory_bp.route('/manage_uniform_items', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_uniform_items():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        if request.method == 'POST':
            item_name = request.form.get('item_name')
            class_group = request.form.get('class_group')
            price = _parse_float(request.form.get('price', 0), 'price')
            service.update_price(item_name, class_group, price)
            flash(f"Price updated for {item_name} ({class_group}).", "success")

        prices = service.get_all_prices()
        class_groups = service.get_class_groups()

        return render_template('manage_prices.html', prices=prices, class_groups=class_groups)
    except ValueError as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('inventory.manage_stock'))
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('inventory.manage_stock'))
    finally: connection.close()

@inventory_bp.route('/admin/term_dates', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_term_dates():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add':
                service.add_term_date(
                    request.form.get('term_number'),
                    request.form.get('year'),
                    request.form.get('start_date'),
                    request.form.get('end_date')
                )
                flash("Term dates added.", "success")
            elif action == 'delete':
                service.delete_term_date(request.form.get('term_id'))
                flash("Term deleted.", "success")

        terms = service.get_all_term_dates()
        return render_template('manage_term_dates.html', term_dates=terms, now=datetime.now())
    finally: connection.close()

@inventory_bp.route('/manage_stock', methods=['GET', 'POST'])
@login_required
def manage_stock():
    connection = get_db_connection(); service = InventoryService(connection)
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add_stock':
                service.adjust_stock(request.form.get('item_name'), _required_int(request.form.get('quantity', 0), 'quantity'), 'PURCHASE', session['userNo'], f"Purchased from {request.form.get('supplier', '')}", request.form.get('purchase_ref', ''))
            elif action == 'adjust_stock':
                service.adjust_stock(request.form.get('item_name'), _required_int(request.form.get('new_quantity', 0), 'new_quantity'), 'ADJUSTMENT', session['userNo'], request.form.get('reason', ''))
            flash("Stock updated.", "success")
        except ValueError as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")

    items = service.get_stock_levels()
    connection.close()
    return render_template('manage_stock.html', items=items)

@inventory_bp.route('/stock_report')
@login_required
def stock_report():
    connection = get_db_connection(); service = InventoryService(connection)
    movements = service.get_stock_movements(request.args.get('start_date'), request.args.get('end_date'))
    connection.close()
    return render_template('stock_report.html', movements=movements)

@inventory_bp.route('/print_stock_levels')
@login_required
def print_stock_levels():
    connection = get_db_connection(); service = InventoryService(connection)
    items = service.get_stock_levels()
    connection.close()
    return render_template('print_stock_levels.html', items=items, now=datetime.now())

@inventory_bp.route('/stock_ledger')
@login_required
def stock_ledger():
    connection = get_db_connection(); service = InventoryService(connection)
    item_name = request.args.get('item_name')
    ledger_data = service.get_stock_ledger(item_name, request.args.get('date_from'), request.args.get('date_to')) if item_name else []

    # Calculate running balance
    running_balance = 0
    for row in ledger_data:
        if row['movement_type'] == 'ISSUANCE': running_balance -= row['quantity']
        elif row['movement_type'] in ('PURCHASE', 'RETURN'): running_balance += row['quantity']
        elif row['movement_type'] == 'ADJUSTMENT': running_balance = row['new_stock']
        row['running_balance'] = running_balance

    items = service.get_item_name_options()
    connection.close()
    return render_template('stock_ledger.html', items=items, ledger_data=ledger_data, selected_item=item_name)

@inventory_bp.route('/issue_uniform', methods=['GET', 'POST'])
@login_required
def issue_uniform():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        # Check for search by AdmNo
        admno = request.args.get('admno')
        student = service.get_student_by_admno(admno) if admno else None
        
        # Get items for issuance
        items = service.get_stock_levels() if student else []
        
        # Get term info
        term_info = service.get_current_term()
        
        return render_template('issue_form.html', student=student, items=items, term=term_info)
    finally: connection.close()

@inventory_bp.route('/submit_issuance', methods=['POST'])
@login_required
@csrf.exempt
def submit_issuance():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        data = request.get_json(silent=True) or {}
        admno = (data.get('admno') or '').strip()
        items = data.get('items')
        if not admno:
            return jsonify({'success': False, 'message': 'Student admission number is required.'}), 400
        if not isinstance(items, list) or not items:
            return jsonify({'success': False, 'message': 'At least one issuance item is required.'}), 400
        receipt_no = f"UNI-{datetime.now().strftime('%m%d%H%M')}-{admno[-2:]}" # Simple generated ref, adjust logic as needed
        total_amount = 0
        
        success = service.process_issuance(admno, items, session['userNo'], receipt_no, total_amount)
        if success:
            return jsonify({'success': True, 'receipt_no': receipt_no})
        return jsonify({'success': False, 'message': "Failed to process issuance"})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally: connection.close()

@inventory_bp.route('/receipt/<receipt_no>')
@login_required
def receipt(receipt_no):
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        receipt_data = service.get_receipt_details(receipt_no)
        if not receipt_data:
            flash("Receipt not found.", "error")
            return redirect(url_for('inventory.manage_stock'))
        return render_template('receipt.html', receipt=receipt_data)
    finally: connection.close()

@inventory_bp.route('/print_receipt/<receipt_no>')
@login_required
def print_receipt(receipt_no):
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        receipt_data = service.get_receipt_details(receipt_no)
        if not receipt_data:
            flash("Receipt not found.", "error")
            return redirect(url_for('inventory.manage_stock'))
        return render_template('print_receipt.html', receipt=receipt_data, now=datetime.now())
    finally: connection.close()

# Uniform Reports
@inventory_bp.route('/reports/issued_summary')
@login_required
def report_issued_summary():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        report_data = service.get_issued_summary(start_date, end_date)
        return render_template('report_issued_summary.html', items=report_data, start_date=start_date, end_date=end_date)
    finally: connection.close()

@inventory_bp.route('/reports/item_totals')
@login_required
def items_totals_report():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        report_data = service.get_items_totals(start_date, end_date)
        return render_template('report_item_totals.html', items=report_data, start_date=start_date, end_date=end_date)
    finally: connection.close()

@inventory_bp.route('/reports/receipts_register')
@login_required
def receipts_register_report():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        report_data = service.get_receipts_register(start_date, end_date)
        return render_template('report_receipts_register.html', receipts=report_data, start_date=start_date, end_date=end_date)
    finally: connection.close()
