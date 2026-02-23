from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.inventory.services import InventoryService
from blueprints.classes.services import ClassManagementService
from datetime import datetime

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/admin/add_uniform_item', methods=['POST'])
@login_required
@admin_required
def add_uniform_item():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        service.add_uniform_item(request.form.get('item_name').strip(), request.form.getlist('class_groups[]'))
        flash("✅ Item added.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(request.referrer or url_for('index'))

@inventory_bp.route('/admin/delete_uniform_item', methods=['POST'])
@login_required
@admin_required
def delete_uniform_item():
    connection = get_db_connection(); service = InventoryService(connection)
    try:
        data = request.get_json()
        service.delete_uniform_item(data.get('item_name'))
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500
    finally: connection.close()

@inventory_bp.route('/manage_stock', methods=['GET', 'POST'])
@login_required
def manage_stock():
    connection = get_db_connection(); service = InventoryService(connection)
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add_stock':
                service.adjust_stock(request.form.get('item_name'), int(request.form.get('quantity', 0)), 'PURCHASE', session['userNo'], f"Purchased from {request.form.get('supplier', '')}", request.form.get('purchase_ref', ''))
            elif action == 'adjust_stock':
                service.adjust_stock(request.form.get('item_name'), int(request.form.get('new_quantity', 0)), 'ADJUSTMENT', session['userNo'], request.form.get('reason', ''))
            flash("✅ Stock updated.", "success")
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

    with connection.cursor() as cursor:
        cursor.execute("SELECT DISTINCT item_name FROM uniform_prices WHERE school_id = %s", (service.school_id,))
        items = cursor.fetchall()
    connection.close()
    return render_template('stock_ledger.html', items=items, ledger_data=ledger_data, selected_item=item_name)
