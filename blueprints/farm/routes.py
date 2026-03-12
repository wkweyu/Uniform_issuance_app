from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.farm.services import FarmManagementService
from datetime import datetime
from decimal import Decimal

farm_bp = Blueprint('farm', __name__, url_prefix='/farm')

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
                activity_id=int(request.form.get('activity_id')),
                quantity=Decimal(request.form.get('quantity', 0)),
                spoilage=Decimal(request.form.get('spoilage', 0)),
                internal=Decimal(request.form.get('internal', 0)),
                recorded_by=session['userNo'],
                notes=request.form.get('notes', '')
            )
            flash("✅ Production recorded successfully.", "success")
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
                activity_id=int(request.form.get('activity_id')),
                customer=request.form.get('customer'),
                quantity=Decimal(request.form.get('quantity', 0)),
                unit_price=Decimal(request.form.get('unit_price', 0)),
                recorded_by=session['userNo']
            )
            flash("✅ Sale recorded and receipt generated.", "success")
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
                activity_id=int(request.form.get('activity_id')),
                category=request.form.get('category'),
                amount=Decimal(request.form.get('amount', 0)),
                description=request.form.get('description'),
                recorded_by=session['userNo']
            )
            flash("✅ Expense request submitted for approval.", "success")
        except Exception as e:
            flash(f"Error: {str(e)}", "error")
            
    activities = service.get_activities()
    connection.close()
    return render_template('farm/expense_form.html', activities=activities)
