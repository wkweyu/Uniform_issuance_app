from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify, make_response
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.procurement.services import ProcurementService, ProcurementError
from blueprints.finance.services import FinanceService
from decimal import Decimal
from datetime import datetime

procurement_bp = Blueprint('procurement', __name__)

@procurement_bp.route('/admin/procurement/requisitions')
@login_required
@admin_required
def manage_requisitions():
    connection = get_db_connection(); service = ProcurementService(connection)
    reqs = service.get_requisitions()
    connection.close()
    return render_template('manage_requisitions.html', requisitions=reqs)

@procurement_bp.route('/admin/procurement/requisition/create', methods=['GET', 'POST'])
@login_required
def create_requisition():
    connection = get_db_connection(); service = ProcurementService(connection)
    if request.method == 'POST':
        try:
            items = []
            for d, q, p in zip(request.form.getlist('description[]'), request.form.getlist('quantity[]'), request.form.getlist('price[]')):
                if d.strip() and q: items.append({'description': d.strip(), 'quantity': float(q), 'estimated_unit_price': float(p) if p else 0})
            service.create_requisition(int(request.form.get('department_id')), items, session['userNo'], request.form.get('justification'), category=request.form.get('category', 'General'), academic_year_id=int(request.form.get('academic_year_id')) if request.form.get('academic_year_id') else None)
            flash("✓ Requisition submitted.", "success")
            return redirect(url_for('procurement.manage_requisitions'))
        except Exception as e: flash(str(e), "error")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM staffdepts WHERE school_id = %s ORDER BY dept", (service.school_id,))
        depts = cursor.fetchall()
        cursor.execute("SELECT * FROM academic_years WHERE school_id = %s ORDER BY year DESC", (service.school_id,))
        years = cursor.fetchall()
    connection.close()
    return render_template('create_requisition.html', depts=depts, academic_years=years)

@procurement_bp.route('/admin/procurement/requisition/<int:req_id>')
@login_required
@admin_required
def view_requisition(req_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    req = service.get_requisition_details(req_id)
    suppliers = []
    if req and req['status'] == 'APPROVED':
        suppliers = service.get_suppliers()
    connection.close()
    return render_template('view_requisition.html', requisition=req, suppliers=suppliers)

@procurement_bp.route('/admin/procurement/requisition/<int:req_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_requisition(req_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        service.update_requisition_status(req_id, 'APPROVED', session['userNo'])
        flash("✓ Approved.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.view_requisition', req_id=req_id))

@procurement_bp.route('/admin/procurement/requisition/<int:req_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_requisition(req_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        service.update_requisition_status(req_id, 'REJECTED', session['userNo'])
        flash("✓ Rejected.", "warning")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.view_requisition', req_id=req_id))

@procurement_bp.route('/admin/procurement/requisition/<int:req_id>/convert', methods=['POST'])
@login_required
@admin_required
def convert_requisition(req_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        po = service.convert_requisition_to_po(req_id, int(request.form.get('supplier_id')), session['userNo'])
        flash("✓ Converted to PO.", "success")
        return redirect(url_for('procurement.view_purchase_order', po_id=po['id']))
    except Exception as e: flash(str(e), "error"); return redirect(url_for('procurement.view_requisition', req_id=req_id))
    finally: connection.close()

@procurement_bp.route('/admin/procurement/po/<int:po_id>/receive', methods=['GET', 'POST'])
@login_required
@admin_required
def receive_goods(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    if request.method == 'POST':
        try:
            items = [{'po_item_id': int(i_id), 'quantity': float(q)} for i_id, q in zip(request.form.getlist('po_item_id[]'), request.form.getlist('receive_qty[]')) if q and float(q) > 0]
            service.record_grn(po_id, session['userNo'], items, request.form.get('delivery_note_ref'), request.form.get('notes'))
            flash("✓ GRN recorded.", "success")
            return redirect(url_for('procurement.view_purchase_order', po_id=po_id))
        except Exception as e: flash(str(e), "error")
    po = service.get_po_details(po_id)
    connection.close()
    return render_template('receive_goods.html', po=po)

@procurement_bp.route('/admin/procurement/assets')
@login_required
@admin_required
def manage_assets():
    connection = get_db_connection(); service = ProcurementService(connection)
    assets = service.get_assets(request.args)
    connection.close()
    return render_template('manage_assets.html', assets=assets)

@procurement_bp.route('/admin/procurement/asset/register', methods=['GET', 'POST'])
@login_required
@admin_required
def register_asset():
    connection = get_db_connection(); service = ProcurementService(connection)
    if request.method == 'POST':
        try:
            data = {k: v for k, v in request.form.items()}
            data['purchase_value'] = float(data['purchase_value'])
            service.register_asset(data, session['userNo'])
            flash("✓ Asset registered.", "success")
            return redirect(url_for('procurement.manage_assets'))
        except Exception as e: flash(str(e), "error")
    connection.close()
    return render_template('register_asset.html')

@procurement_bp.route('/admin/procurement/asset/<int:asset_id>/update', methods=['POST'])
@login_required
@admin_required
def update_asset(asset_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        service.update_asset_condition(asset_id, {'condition': request.form.get('condition_status'), 'location': request.form.get('location')}, session['userNo'])
        flash("✓ Asset updated.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.manage_assets'))

@procurement_bp.route('/admin/procurement')
@login_required
@admin_required
def procurement_dashboard():
    connection = get_db_connection(); service = ProcurementService(connection)
    pos = service.get_purchase_orders(request.args.get('status'), request.args.get('po_number'), int(request.args.get('supplier_id')) if request.args.get('supplier_id') else None)
    suppliers = service.get_suppliers()
    with connection.cursor() as cursor:
        if service._table_has_column('purchase_orders', 'school_id'):
            cursor.execute("SELECT status, COUNT(*) as count FROM purchase_orders WHERE school_id = %s GROUP BY status", (service.school_id,))
        else:
            cursor.execute("SELECT status, COUNT(*) as count FROM purchase_orders GROUP BY status")
        stats = cursor.fetchall()
    connection.close()
    return render_template('procurement_dashboard.html', pos=pos, suppliers=suppliers, stats=stats)

@procurement_bp.route('/admin/procurement/budgets', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_procurement_budgets():
    connection = get_db_connection(); service = ProcurementService(connection)
    year_id = request.args.get('academic_year_id')
    if not year_id:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM academic_years WHERE is_current = 1 AND school_id = %s LIMIT 1", (service.school_id,))
            ay = cursor.fetchone(); year_id = ay['id'] if ay else 1
    if request.method == 'POST':
        try:
            service.set_budget(request.form.get('department_id'), year_id, request.form.get('category'), Decimal(request.form.get('allocated_amount')))
            flash("✓ Budget updated.", "success")
        except Exception as e: flash(str(e), "error")
    budgets = service.get_budgets(year_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM staffdepts WHERE school_id = %s ORDER BY dept", (service.school_id,))
        depts = cursor.fetchall()
        cursor.execute("SELECT * FROM academic_years WHERE school_id = %s ORDER BY year DESC", (service.school_id,))
        years = cursor.fetchall()
    connection.close()
    return render_template('procurement_budgets.html', budgets=budgets, departments=depts, academic_years=years, current_year_id=int(year_id))

@procurement_bp.route('/admin/procurement/reports/aging')
@login_required
@admin_required
def suppliers_aging_report():
    connection = get_db_connection(); service = ProcurementService(connection)
    data = service.get_suppliers_aging()
    connection.close()
    return render_template('suppliers_aging.html', aging_data=data)

@procurement_bp.route('/admin/procurement/suppliers', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_suppliers():
    connection = get_db_connection(); service = ProcurementService(connection)
    if request.method == 'POST':
        try:
            service.create_supplier(request.form.get('company'), request.form.get('contact_person'), request.form.get('email'), request.form.get('phone'), request.form.get('address'), request.form.get('cert_no',''), request.form.get('pin_no',''))
            flash("✓ Supplier added.", "success")
        except Exception as e: flash(str(e), "error")
    suppliers = service.get_suppliers(active_only=False)
    connection.close()
    return render_template('manage_suppliers.html', suppliers=suppliers)

@procurement_bp.route('/admin/procurement/suppliers/<int:supplier_id>/statement')
@login_required
@admin_required
def vendor_statement(supplier_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    with connection.cursor() as cursor:
        if service._table_has_column('suppliers', 'school_id'):
            cursor.execute("SELECT * FROM suppliers WHERE supplierID = %s AND school_id = %s", (supplier_id, service.school_id))
        else:
            cursor.execute("SELECT * FROM suppliers WHERE supplierID = %s", (supplier_id,))
        supplier = cursor.fetchone()
    if not supplier: flash("Not found", "error"); connection.close(); return redirect(url_for('procurement.manage_suppliers'))
    txns = service.get_vendor_statement(supplier_id, request.args.get('start_date', datetime.now().replace(day=1).strftime('%Y-%m-%d')), request.args.get('end_date', datetime.now().strftime('%Y-%m-%d')))
    connection.close()
    return render_template('vendor_statement.html', supplier=supplier, transactions=txns)

@procurement_bp.route('/admin/procurement/po/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_purchase_order():
    connection = get_db_connection(); service = ProcurementService(connection)
    if request.method == 'POST':
        try:
            items = [{'item_id': int(i_id) if i_id else None, 'description': d.strip(), 'quantity': float(q), 'unit_price': float(p)} for i_id, d, q, p in zip(request.form.getlist('item_id[]'), request.form.getlist('item_description[]'), request.form.getlist('item_qty[]'), request.form.getlist('item_price[]')) if d.strip() and q and p]
            po = service.create_purchase_order(int(request.form.get('supplier_id')), request.form.get('order_date'), items, session['userNo'], request.form.get('notes'))
            flash("✓ PO created.", "success")
            return redirect(url_for('procurement.view_purchase_order', po_id=po['id']))
        except Exception as e: flash(str(e), "error")
    suppliers = service.get_suppliers()
    with connection.cursor() as cursor:
        cursor.execute("SELECT item_id, item_name, current_stock FROM item_stock WHERE school_id = %s ORDER BY item_name", (service.school_id,))
        stock_items = cursor.fetchall()
        cursor.execute("SELECT DISTINCT p.item_name, s.item_id, COALESCE(s.current_stock, 0) as current_stock FROM uniform_prices p LEFT JOIN item_stock s ON p.item_name = s.item_name AND p.school_id = s.school_id WHERE p.school_id = %s ORDER BY p.item_name", (service.school_id,))
        uniform_items = cursor.fetchall()
    connection.close()
    return render_template('create_purchase_order.html', suppliers=suppliers, stock_items=stock_items, uniform_items=uniform_items)

@procurement_bp.route('/admin/procurement/po/<int:po_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_purchase_order(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    if request.method == 'POST':
        try:
            items = [{'item_id': int(i_id) if i_id else None, 'description': d.strip(), 'quantity': float(q), 'unit_price': float(p)} for i_id, d, q, p in zip(request.form.getlist('item_id[]'), request.form.getlist('item_description[]'), request.form.getlist('item_qty[]'), request.form.getlist('item_price[]')) if d.strip() and q and p]
            service.update_purchase_order(po_id, int(request.form.get('supplier_id')), request.form.get('order_date'), items, request.form.get('notes'))
            flash("✓ PO updated.", "success")
            return redirect(url_for('procurement.view_purchase_order', po_id=po_id))
        except Exception as e: flash(str(e), "error")
    po = service.get_po_details(po_id)
    suppliers = service.get_suppliers()
    connection.close()
    return render_template('edit_purchase_order.html', po=po, suppliers=suppliers)

@procurement_bp.route('/admin/procurement/po/<int:po_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_purchase_order(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        service.delete_purchase_order(po_id)
        flash("✓ PO deleted.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.procurement_dashboard'))

@procurement_bp.route('/admin/procurement/po/<int:po_id>/print')
@login_required
@admin_required
def print_purchase_order(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    po = service.get_po_details(po_id)
    connection.close()
    return render_template('print_purchase_order.html', po=po)

@procurement_bp.route('/admin/procurement/po/<int:po_id>/download')
@login_required
@admin_required
def download_purchase_order(po_id):
    # PDF logic...
    return "PO Download Placeholder"

@procurement_bp.route('/admin/procurement/po/<int:po_id>')
@login_required
@admin_required
def view_purchase_order(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    finance_service = FinanceService(connection, service.school_id)
    po = service.get_po_details(po_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM supplier_payments WHERE po_id = %s AND school_id = %s ORDER BY payment_date DESC", (po_id, service.school_id))
        payments = cursor.fetchall()
    accounts = finance_service.get_accounts()
    connection.close()
    return render_template('view_purchase_order.html', po=po, accounts=accounts, payments=payments)

@procurement_bp.route('/admin/procurement/po/<int:po_id>/update_status', methods=['POST'])
@login_required
@admin_required
def update_po_status(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        service.update_po_status(po_id, request.form.get('status'), session['userNo'])
        flash("✓ Status updated.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.view_purchase_order', po_id=po_id))

@procurement_bp.route('/admin/procurement/po/<int:po_id>/pay', methods=['POST'])
@login_required
@admin_required
def record_po_payment(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        service.record_po_payment(po_id, Decimal(request.form.get('amount')), request.form.get('payment_mode'), request.form.get('reference_no'), request.form.get('payment_date'), session['userNo'], int(request.form.get('source_account_id')))
        flash("✓ Payment recorded.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.view_purchase_order', po_id=po_id))
