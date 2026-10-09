import pymysql
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from core.tenancy import require_current_school_id
from blueprints.farm.services import FarmManagementService, BusinessOperationsService, PricingService
from datetime import datetime
from decimal import Decimal, InvalidOperation

farm_bp = Blueprint('farm', __name__, url_prefix='/farm')


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


def _parse_decimal(value, field_name, default=None):
    if value in (None, ''):
        if default is not None:
            return Decimal(str(default))
        raise ValueError(f"{field_name} is required and must be a valid number.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")


@farm_bp.route('/dashboard')
@login_required
def dashboard():
    connection = get_db_connection()
    try:
        service = FarmManagementService(connection)
        units = service.get_business_units()
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
        summary = service.get_financial_summary(start_date=start_date)
        return render_template('farm/dashboard.html', activities=units, summary=summary, units=units)
    finally:
        connection.close()


@farm_bp.route('/units', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_units():
    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        if request.method == 'POST':
            try:
                name = _required_text(request.form.get('name'), 'Business Unit Name')
                type_code = request.form.get('type_code', 'AGRICULTURE')
                revenue_gl = request.form.get('revenue_gl', '')
                expense_gl = request.form.get('expense_gl', '')

                service.create_business_unit(
                    name=name,
                    type_code=type_code,
                    revenue_gl=revenue_gl,
                    expense_gl=expense_gl
                )
                flash("Business unit created successfully.", "success")
            except ValueError as e:
                flash(f"Error: {str(e)}", "error")
            except Exception as e:
                flash(f"Error: {str(e)}", "error")
            return redirect(url_for('farm.manage_units'))

        units = service.get_business_units(active_only=False)
        return render_template('farm/units.html', units=units)
    finally:
        connection.close()


@farm_bp.route('/locations', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_locations():
    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        if request.method == 'POST':
            try:
                unit_id = _required_int(request.form.get('business_unit_id'), 'Business Unit')
                name = _required_text(request.form.get('name'), 'Location Name')
                type_code = request.form.get('location_type_code', 'STORE')

                service.create_location(business_unit_id=unit_id, name=name, location_type_code=type_code)
                flash("Inventory store/location created successfully.", "success")
            except ValueError as e:
                flash(f"Error: {str(e)}", "error")
            except Exception as e:
                flash(f"Error: {str(e)}", "error")
            return redirect(url_for('farm.manage_locations'))

        units = service.get_business_units()
        locations = service.get_locations()
        return render_template('farm/locations.html', units=units, locations=locations)
    finally:
        connection.close()


@farm_bp.route('/pos', methods=['GET', 'POST'])
@login_required
def pos_sales():
    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        if request.method == 'POST':
            try:
                unit_id = _required_int(request.form.get('business_unit_id'), 'Business Unit')
                customer_name = _required_text(request.form.get('customer_name'), 'Customer Name')
                customer_type = request.form.get('customer_type', 'EXTERNAL')
                student_adm = request.form.get('student_adm_no', '').strip() or None
                item_name = _required_text(request.form.get('item_name'), 'Item Name')
                quantity = _parse_decimal(request.form.get('quantity'), 'Quantity')
                unit_price = _parse_decimal(request.form.get('unit_price'), 'Unit Price')

                res = service.record_pos_sale(
                    business_unit_id=unit_id,
                    items=[{'item_name': item_name, 'quantity': quantity, 'unit_price': unit_price}],
                    customer_type=customer_type,
                    customer_name=customer_name,
                    user_id=session['userNo'],
                    student_adm_no=student_adm
                )
                flash(f"POS sale completed. Receipt #{res['receipt_no']} created.", "success")
            except ValueError as e:
                flash(f"Error: {str(e)}", "error")
            except Exception as e:
                flash(f"Error: {str(e)}", "error")
            return redirect(url_for('farm.pos_sales'))

        units = service.get_business_units()
        locations = service.get_locations()
        active_shift = service.get_active_cashier_shift(session['userNo'])
        return render_template('farm/pos.html', units=units, locations=locations, active_shift=active_shift)
    finally:
        connection.close()


# --- BACKEND REST APIs FOR POS GRID & SHIFT MANAGEMENT ---

@farm_bp.route('/api/shift/open', methods=['POST'])
@login_required
def api_open_shift():
    data = request.get_json() or request.form
    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        unit_id = _required_int(data.get('business_unit_id'), 'Business Unit')
        location_id = _required_int(data.get('location_id'), 'Location')
        opening_bal = _parse_decimal(data.get('opening_balance', 0), 'Opening Balance', default=0)
        terminal = data.get('terminal_code', 'POS-01')

        res = service.open_cashier_shift(
            user_id=session['userNo'],
            business_unit_id=unit_id,
            location_id=location_id,
            opening_balance=opening_bal,
            terminal_code=terminal
        )
        return jsonify({'status': 'success', 'data': res})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    finally:
        connection.close()


@farm_bp.route('/api/shift/close', methods=['POST'])
@login_required
def api_close_shift():
    data = request.get_json() or request.form
    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        session_id = _required_int(data.get('cashier_session_id'), 'Shift Session ID')
        closing_bal = _parse_decimal(data.get('closing_balance', 0), 'Closing Balance', default=0)

        if service.close_cashier_shift(session_id, closing_bal, session['userNo']):
            return jsonify({'status': 'success', 'message': 'Shift closed.'})
        return jsonify({'status': 'error', 'message': 'Failed to close shift.'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    finally:
        connection.close()


@farm_bp.route('/api/shift/current', methods=['GET'])
@login_required
def api_current_shift():
    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        shift = service.get_active_cashier_shift(session['userNo'])
        return jsonify({'status': 'success', 'shift': shift})
    finally:
        connection.close()


@farm_bp.route('/api/items/search', methods=['GET'])
@login_required
def api_search_items():
    query_term = request.args.get('q', '').strip()
    location_id = request.args.get('location_id', type=int)
    if not query_term:
        return jsonify({'status': 'success', 'items': []})

    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        items = service.search_items(query_term, location_id)
        return jsonify({'status': 'success', 'items': items})
    finally:
        connection.close()


@farm_bp.route('/api/customers/student', methods=['GET'])
@login_required
def api_search_student():
    query_term = request.args.get('q', '').strip()
    if not query_term:
        return jsonify({'status': 'success', 'students': []})

    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        students = service.lookup_student(query_term)
        return jsonify({'status': 'success', 'students': students})
    finally:
        connection.close()


@farm_bp.route('/api/customers/staff', methods=['GET'])
@login_required
def api_search_staff():
    query_term = request.args.get('q', '').strip()
    if not query_term:
        return jsonify({'status': 'success', 'staff': []})

    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        staff = service.lookup_staff(query_term)
        return jsonify({'status': 'success', 'staff': staff})
    finally:
        connection.close()


@farm_bp.route('/api/pos/checkout', methods=['POST'])
@login_required
def api_pos_checkout():
    data = request.get_json() or {}
    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        unit_id = _required_int(data.get('business_unit_id'), 'Business Unit')
        location_id = data.get('location_id')
        session_id = data.get('cashier_session_id')
        customer_type = data.get('customer_type', 'EXTERNAL')
        customer_name = _required_text(data.get('customer_name'), 'Customer Name')
        student_adm = data.get('student_adm_no')
        payment_method = data.get('payment_method', 'CASH')
        amount_tendered = _parse_decimal(data.get('amount_tendered', 0), 'Amount Tendered', default=0)
        items = data.get('items', [])

        if not isinstance(items, list) or not items:
            return jsonify({'status': 'error', 'message': 'Sales cart is empty.'}), 400

        res = service.execute_pos_checkout(
            cashier_session_id=session_id,
            user_id=session['userNo'],
            business_unit_id=unit_id,
            items=items,
            customer_type=customer_type,
            customer_name=customer_name,
            student_adm_no=student_adm,
            payment_method=payment_method,
            amount_tendered=amount_tendered,
            location_id=location_id
        )
        return jsonify({'status': 'success', 'data': res})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    finally:
        connection.close()


@farm_bp.route('/production', methods=['GET', 'POST'])
@login_required
def record_production():
    connection = get_db_connection()
    try:
        service = FarmManagementService(connection)
        if request.method == 'POST':
            try:
                service.record_production(
                    activity_id=_required_int(request.form.get('activity_id'), 'activity_id'),
                    quantity=_parse_decimal(request.form.get('quantity'), 'quantity'),
                    spoilage=_parse_decimal(request.form.get('spoilage'), 'spoilage', default=0),
                    internal=_parse_decimal(request.form.get('internal'), 'internal', default=0),
                    recorded_by=session['userNo'],
                    notes=request.form.get('notes', '')
                )
                flash("Production batch recorded successfully.", "success")
            except ValueError as e:
                flash(f"Error: {str(e)}", "error")
            except Exception as e:
                flash(f"Error: {str(e)}", "error")
            return redirect(url_for('farm.dashboard'))

        activities = service.get_activities()
        return render_template('farm/production_form.html', activities=activities)
    finally:
        connection.close()


@farm_bp.route('/sales', methods=['GET', 'POST'])
@login_required
def record_sale():
    connection = get_db_connection()
    try:
        service = FarmManagementService(connection)
        if request.method == 'POST':
            try:
                service.record_sale(
                    activity_id=_required_int(request.form.get('activity_id'), 'activity_id'),
                    customer=_required_text(request.form.get('customer'), 'customer'),
                    quantity=_parse_decimal(request.form.get('quantity'), 'quantity'),
                    unit_price=_parse_decimal(request.form.get('unit_price'), 'unit_price'),
                    recorded_by=session['userNo']
                )
                flash("Sale recorded and receipt generated.", "success")
            except ValueError as e:
                flash(f"Error: {str(e)}", "error")
            except Exception as e:
                flash(f"Error: {str(e)}", "error")
            return redirect(url_for('farm.dashboard'))

        activities = service.get_activities()
        return render_template('farm/sales_form.html', activities=activities)
    finally:
        connection.close()


@farm_bp.route('/expenses', methods=['GET', 'POST'])
@login_required
def farm_expenses():
    connection = get_db_connection()
    try:
        service = FarmManagementService(connection)
        if request.method == 'POST':
            try:
                service.request_expense(
                    activity_id=_required_int(request.form.get('activity_id'), 'activity_id'),
                    category=_required_text(request.form.get('category'), 'category'),
                    amount=_parse_decimal(request.form.get('amount'), 'amount'),
                    description=_required_text(request.form.get('description'), 'description'),
                    recorded_by=session['userNo']
                )
                flash("Expense request submitted for approval.", "success")
            except ValueError as e:
                flash(f"Error: {str(e)}", "error")
            except Exception as e:
                flash(f"Error: {str(e)}", "error")

        activities = service.get_activities()
        return render_template('farm/expense_form.html', activities=activities)
    finally:
        connection.close()


@farm_bp.route('/expenses/approvals', methods=['GET', 'POST'])
@login_required
@admin_required
def approve_expenses():
    connection = get_db_connection()
    try:
        service = BusinessOperationsService(connection)
        if request.method == 'POST':
            expense_id = _required_int(request.form.get('expense_id'), 'Expense ID')
            if service.approve_expense(expense_id, session['userNo']):
                flash("Expense approved and enqueued for accounting posting.", "success")
            else:
                flash("Failed to approve expense.", "error")
            return redirect(url_for('farm.approve_expenses'))

        # Fetch pending expenses
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        school_id = require_current_school_id()
        try:
            cursor.execute("SELECT be.*, bu.name as unit_name FROM business_expenses be JOIN business_units bu ON be.business_unit_id = bu.id WHERE be.status = 'REQUESTED' AND be.school_id = %s", (school_id,))
            pending = cursor.fetchall()
        except pymysql.Error:
            cursor.execute("SELECT ie.*, ia.name as unit_name FROM income_expenses ie JOIN income_activities ia ON ie.activity_id = ia.id WHERE ie.status = 'PENDING' AND ie.school_id = %s", (school_id,))
            pending = cursor.fetchall()

        return render_template('farm/expense_approvals.html', pending_expenses=pending)
    finally:
        connection.close()
