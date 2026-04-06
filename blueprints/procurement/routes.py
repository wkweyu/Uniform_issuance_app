from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify, make_response
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.procurement.services import ProcurementService, ProcurementError
from blueprints.finance.services import FinanceService
from decimal import Decimal, InvalidOperation
from datetime import datetime

procurement_bp = Blueprint('procurement', __name__)


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


def _optional_int(value, field_name):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid integer.")


def _parse_decimal(value, field_name, default=None):
    if value in (None, ''):
        if default is not None:
            return Decimal(str(default))
        raise ValueError(f"{field_name} is required and must be a valid number.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")


def _parse_float(value, field_name, default=None):
    if value in (None, ''):
        if default is not None:
            return float(default)
        raise ValueError(f"{field_name} is required and must be a valid number.")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")


def _build_requisition_items(form):
    items = []
    for index, (description, quantity, price) in enumerate(
        zip(form.getlist('description[]'), form.getlist('quantity[]'), form.getlist('price[]')),
        start=1,
    ):
        if (description or '').strip() and quantity:
            items.append({
                'description': description.strip(),
                'quantity': _parse_float(quantity, f'quantity[{index}]'),
                'estimated_unit_price': _parse_float(price, f'price[{index}]', default=0),
            })
    return items


def _build_grn_items(form):
    items = []
    for index, (po_item_id, quantity) in enumerate(
        zip(form.getlist('po_item_id[]'), form.getlist('receive_qty[]')),
        start=1,
    ):
        if quantity and _parse_float(quantity, f'receive_qty[{index}]') > 0:
            items.append({
                'po_item_id': _required_int(po_item_id, f'po_item_id[{index}]'),
                'quantity': _parse_float(quantity, f'receive_qty[{index}]'),
            })
    return items


def _build_purchase_order_items(form):
    items = []
    for index, (item_id, description, quantity, price) in enumerate(
        zip(
            form.getlist('item_id[]'),
            form.getlist('item_description[]'),
            form.getlist('item_qty[]'),
            form.getlist('item_price[]'),
        ),
        start=1,
    ):
        if (description or '').strip() and quantity and price:
            items.append({
                'item_id': _optional_int(item_id, f'item_id[{index}]'),
                'description': description.strip(),
                'quantity': _parse_float(quantity, f'item_qty[{index}]'),
                'unit_price': _parse_float(price, f'item_price[{index}]'),
            })
    return items

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
            items = _build_requisition_items(request.form)
            service.create_requisition(
                _required_int(request.form.get('department_id'), 'department_id'),
                items,
                session['userNo'],
                request.form.get('justification'),
                category=request.form.get('category', 'General'),
                academic_year_id=_optional_int(request.form.get('academic_year_id'), 'academic_year_id'),
            )
            flash("Requisition submitted.", "success")
            return redirect(url_for('procurement.manage_requisitions'))
        except (ValueError, ProcurementError) as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")

    depts = service.get_departments()
    years = service.get_academic_years()
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
        flash("Approved.", "success")
    except ProcurementError as e: flash(str(e), "error")
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
        flash("Rejected.", "warning")
    except ProcurementError as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.view_requisition', req_id=req_id))

@procurement_bp.route('/admin/procurement/requisition/<int:req_id>/convert', methods=['POST'])
@login_required
@admin_required
def convert_requisition(req_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        po = service.convert_requisition_to_po(req_id, _required_int(request.form.get('supplier_id'), 'supplier_id'), session['userNo'])
        flash("Converted to PO.", "success")
        return redirect(url_for('procurement.view_purchase_order', po_id=po['id']))
    except (ValueError, ProcurementError) as e: flash(str(e), "error"); return redirect(url_for('procurement.view_requisition', req_id=req_id))
    except Exception as e: flash(str(e), "error"); return redirect(url_for('procurement.view_requisition', req_id=req_id))
    finally: connection.close()

@procurement_bp.route('/admin/procurement/po/<int:po_id>/receive', methods=['GET', 'POST'])
@login_required
@admin_required
def receive_goods(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    if request.method == 'POST':
        try:
            items = _build_grn_items(request.form)
            service.record_grn(po_id, session['userNo'], items, request.form.get('delivery_note_ref'), request.form.get('notes'))
            flash("GRN recorded.", "success")
            return redirect(url_for('procurement.view_purchase_order', po_id=po_id))
        except (ValueError, ProcurementError) as e: flash(str(e), "error")
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
            data['purchase_value'] = _parse_float(data.get('purchase_value'), 'purchase_value')
            service.register_asset(data, session['userNo'])
            flash("Asset registered.", "success")
            return redirect(url_for('procurement.manage_assets'))
        except (ValueError, ProcurementError) as e: flash(str(e), "error")
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
        flash("Asset updated.", "success")
    except ProcurementError as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.manage_assets'))

@procurement_bp.route('/admin/procurement')
@login_required
@admin_required
def procurement_dashboard():
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        pos = service.get_purchase_orders(request.args.get('status'), request.args.get('po_number'), _optional_int(request.args.get('supplier_id'), 'supplier_id'))
    except ValueError as e:
        flash(str(e), 'error')
        pos = []
    suppliers = service.get_suppliers()
    stats = service.get_purchase_order_status_counts()
    connection.close()
    return render_template('procurement_dashboard.html', pos=pos, suppliers=suppliers, stats=stats)

@procurement_bp.route('/admin/procurement/budgets', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_procurement_budgets():
    connection = get_db_connection(); service = ProcurementService(connection)
    year_id = request.args.get('academic_year_id')
    if not year_id:
        year_id = service.get_current_academic_year_id() or 1
    current_year_id = int(year_id)
    if request.method == 'POST':
        try:
            service.set_budget(
                _required_int(request.form.get('department_id'), 'department_id'),
                current_year_id,
                request.form.get('category'),
                _parse_decimal(request.form.get('allocated_amount'), 'allocated_amount'),
            )
            flash("Budget updated.", "success")
        except (ValueError, ProcurementError) as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")
    budgets = service.get_budgets(year_id)
    depts = service.get_departments()
    years = service.get_academic_years()
    connection.close()
    return render_template('procurement_budgets.html', budgets=budgets, departments=depts, academic_years=years, current_year_id=current_year_id)

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
            flash("Supplier added.", "success")
        except ProcurementError as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")
    suppliers = service.get_suppliers(active_only=False)
    connection.close()
    return render_template('manage_suppliers.html', suppliers=suppliers)

@procurement_bp.route('/admin/procurement/suppliers/<int:supplier_id>/statement')
@login_required
@admin_required
def vendor_statement(supplier_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    supplier = service.get_supplier_by_id(supplier_id)
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
            items = _build_purchase_order_items(request.form)
            po = service.create_purchase_order(_required_int(request.form.get('supplier_id'), 'supplier_id'), request.form.get('order_date'), items, session['userNo'], request.form.get('notes'))
            flash("PO created.", "success")
            return redirect(url_for('procurement.view_purchase_order', po_id=po['id']))
        except (ValueError, ProcurementError) as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")
    suppliers = service.get_suppliers()
    stock_items = service.get_stock_items()
    uniform_items = service.get_uniform_items_with_stock()
    connection.close()
    return render_template('create_purchase_order.html', suppliers=suppliers, stock_items=stock_items, uniform_items=uniform_items)

@procurement_bp.route('/admin/procurement/po/<int:po_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_purchase_order(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    if request.method == 'POST':
        try:
            items = _build_purchase_order_items(request.form)
            service.update_purchase_order(po_id, _required_int(request.form.get('supplier_id'), 'supplier_id'), request.form.get('order_date'), items, request.form.get('notes'))
            flash("PO updated.", "success")
            return redirect(url_for('procurement.view_purchase_order', po_id=po_id))
        except (ValueError, ProcurementError) as e: flash(str(e), "error")
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
        flash("PO deleted.", "success")
    except ProcurementError as e: flash(str(e), "error")
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
    payments = service.get_purchase_order_payments(po_id)
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
        flash("Status updated.", "success")
    except ProcurementError as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.view_purchase_order', po_id=po_id))

@procurement_bp.route('/admin/procurement/po/<int:po_id>/pay', methods=['POST'])
@login_required
@admin_required
def record_po_payment(po_id):
    connection = get_db_connection(); service = ProcurementService(connection)
    try:
        source_account_id = _required_int(request.form.get('source_account_id'), 'source_account_id')
        service.record_po_payment(po_id, _parse_decimal(request.form.get('amount'), 'amount'), request.form.get('payment_mode'), request.form.get('reference_no'), request.form.get('payment_date'), session['userNo'], source_account_id)
        flash("Payment recorded.", "success")
    except (ValueError, ProcurementError) as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('procurement.view_purchase_order', po_id=po_id))
