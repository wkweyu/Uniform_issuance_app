import pymysql
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from core.tenancy import require_current_school_id
from blueprints.farm.services import FarmManagementService, BusinessOperationsService
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
    service = FarmManagementService(connection)
    try:
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
    connection.close()
    return render_template('farm/units.html', units=units)


@farm_bp.route('/locations', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_locations():
    connection = get_db_connection()
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
    connection.close()
    return render_template('farm/locations.html', units=units, locations=locations)


@farm_bp.route('/pos', methods=['GET', 'POST'])
@login_required
def pos_sales():
    connection = get_db_connection()
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
    connection.close()
    return render_template('farm/pos.html', units=units)


@farm_bp.route('/production', methods=['GET', 'POST'])
@login_required
def record_production():
    connection = get_db_connection()
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
    connection.close()
    return render_template('farm/production_form.html', activities=activities)


@farm_bp.route('/sales', methods=['GET', 'POST'])
@login_required
def record_sale():
    connection = get_db_connection()
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
    connection.close()
    return render_template('farm/sales_form.html', activities=activities)


@farm_bp.route('/expenses', methods=['GET', 'POST'])
@login_required
def farm_expenses():
    connection = get_db_connection()
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
    connection.close()
    return render_template('farm/expense_form.html', activities=activities)


@farm_bp.route('/expenses/approvals', methods=['GET', 'POST'])
@login_required
@admin_required
def approve_expenses():
    connection = get_db_connection()
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
        cursor.execute("SELECT *, name as unit_name FROM income_expenses WHERE status = 'PENDING' AND school_id = %s", (school_id,))
        pending = cursor.fetchall()

    connection.close()
    return render_template('farm/expense_approvals.html', pending_expenses=pending)
