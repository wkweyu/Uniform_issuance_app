from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.farm.services import FarmManagementService
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
        activities = service.get_activities()
        # default summary for the current month
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
        summary = service.get_financial_summary(start_date=start_date)
        return render_template('farm/dashboard.html', activities=activities, summary=summary)
    finally:
        connection.close()

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
            flash("Production recorded successfully.", "success")
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
