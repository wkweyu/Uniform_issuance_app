from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.transport.services import TransportService
from datetime import datetime

transport_bp = Blueprint('transport', __name__)

@transport_bp.route('/fleet/fleet_dashboard')
@login_required
def fleet_dashboard():
    connection = get_db_connection(); service = TransportService(connection)
    try:
        buses = service.get_buses()
        # Summary calculations could be in service
        return render_template('fleet_dashboard.html', buses=buses)
    finally: connection.close()

@transport_bp.route('/fleet/buses', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_buses():
    connection = get_db_connection(); service = TransportService(connection)
    if request.method == 'POST':
        try:
            data = {
                'reg_no': request.form.get('reg_no').strip().upper(),
                'model': request.form.get('model'),
                'capacity': int(request.form.get('capacity')),
                'current_mileage': int(request.form.get('current_mileage')),
                'driver_name': request.form.get('driver_name')
            }
            service.add_bus(data)
            flash("✅ Bus added successfully.", "success")
        except Exception as e: flash(str(e), "error")

    buses = service.get_buses()
    connection.close()
    return render_template('manage_buses.html', buses=buses)

@transport_bp.route('/fleet/edit_bus/<int:bus_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_bus(bus_id):
    connection = get_db_connection(); service = TransportService(connection)
    if request.method == 'POST':
        try:
            data = {
                'reg_no': request.form.get('reg_no').strip().upper(),
                'model': request.form.get('model'),
                'capacity': int(request.form.get('capacity')),
                'current_mileage': int(request.form.get('current_mileage')),
                'driver_name': request.form.get('driver_name')
            }
            service.update_bus(bus_id, data)
            flash("✅ Bus updated successfully.", "success")
            return redirect(url_for('transport.manage_buses'))
        except Exception as e: flash(str(e), "error")

    bus = service.get_bus_by_id(bus_id)
    connection.close()
    return render_template('edit_bus.html', bus=bus)

@transport_bp.route('/fleet/delete_bus/<int:bus_id>', methods=['POST'])
@login_required
@admin_required
def delete_bus(bus_id):
    connection = get_db_connection(); service = TransportService(connection)
    try:
        service.delete_bus(bus_id)
        flash("✅ Bus deleted.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('transport.manage_buses'))

@transport_bp.route('/fleet/record_service', methods=['GET', 'POST'])
@login_required
def record_service():
    connection = get_db_connection(); service = TransportService(connection)
    if request.method == 'POST':
        try:
            data = {
                'bus_id': int(request.form.get('bus_id')),
                'service_date': request.form.get('service_date'),
                'service_type': request.form.get('service_type'),
                'description': request.form.get('description'),
                'cost': float(request.form.get('cost')),
                'garage_name': request.form.get('garage_name'),
                'mileage_at_service': int(request.form.get('mileage_at_service'))
            }
            service.record_service(data)
            flash("✅ Service record saved.", "success")
            return redirect(url_for('transport.service_register'))
        except Exception as e: flash(str(e), "error")

    buses = service.get_buses()
    connection.close()
    return render_template('record_service.html', buses=buses)

@transport_bp.route('/fleet/service_register')
@login_required
def service_register():
    connection = get_db_connection(); service = TransportService(connection)
    history = service.get_service_history()
    connection.close()
    return render_template('service_register.html', history=history)

@transport_bp.route('/fleet/issue_fuel', methods=['GET', 'POST'])
@login_required
def issue_fuel():
    connection = get_db_connection(); service = TransportService(connection)
    if request.method == 'POST':
        try:
            qty = float(request.form.get('quantity'))
            price = float(request.form.get('unit_price'))
            data = {
                'bus_id': int(request.form.get('bus_id')),
                'date_issued': request.form.get('date_issued'),
                'fuel_type': request.form.get('fuel_type'),
                'quantity': qty,
                'unit_price': price,
                'total_cost': qty * price,
                'current_mileage': int(request.form.get('current_mileage')),
                'issued_by': session['userNo']
            }
            voucher_no = service.issue_fuel(data)
            flash(f"✅ Fuel issued. Voucher: {voucher_no}", "success")
            return redirect(url_for('transport.print_voucher', voucher_no=voucher_no))
        except Exception as e: flash(str(e), "error")

    buses = service.get_buses()
    connection.close()
    return render_template('issue_fuel.html', buses=buses)

@transport_bp.route('/fleet/print_voucher/<voucher_no>')
@login_required
def print_voucher(voucher_no):
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT v.*, b.reg_no, u.username as issuer FROM fuel_vouchers v JOIN buses b ON v.bus_id = b.id JOIN users u ON v.issued_by = u.userNo WHERE v.voucher_no = %s AND v.school_id = %s", (voucher_no, g.school_id))
        voucher = cursor.fetchone()
    connection.close()
    return render_template('print_fuel_voucher.html', voucher=voucher)

@transport_bp.route("/fuel/voucher_register", methods=['GET', 'POST'])
@login_required
def voucher_register():
    connection = get_db_connection(); service = TransportService(connection)
    vouchers = service.get_fuel_vouchers(request.args.get('start_date'), request.args.get('end_date'))
    connection.close()
    return render_template('voucher_register.html', vouchers=vouchers)

@transport_bp.route('/fleet/routes', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_transport_routes():
    connection = get_db_connection(); service = TransportService(connection)
    if request.method == 'POST':
        try:
            data = {
                'name': request.form.get('name').strip(),
                'amount': float(request.form.get('amount', 0)),
                'description': request.form.get('description', '').strip()
            }
            service.add_route(data)
            flash("✅ Route added.", "success")
        except Exception as e: flash(str(e), "error")

    routes = service.get_routes()
    connection.close()
    return render_template('manage_routes.html', routes=routes)

@transport_bp.route('/fleet/delete_route/<int:route_id>', methods=['POST'])
@login_required
@admin_required
def delete_route(route_id):
    connection = get_db_connection(); service = TransportService(connection)
    try:
        service.delete_route(route_id)
        flash("✅ Route deleted.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('transport.manage_transport_routes'))

@transport_bp.route('/fleet/get_driver/<int:bus_id>')
@login_required
def get_driver(bus_id):
    connection = get_db_connection(); service = TransportService(connection)
    bus = service.get_bus_by_id(bus_id)
    connection.close()
    return jsonify({'driver_name': bus['driver_name'] if bus else ''})

@transport_bp.route('/fleet/service_reminders')
@login_required
def service_reminders():
    connection = get_db_connection(); service = TransportService(connection)
    buses = service.get_buses()
    # Logic for reminders (e.g. mileage > threshold)
    connection.close()
    return render_template('service_reminders.html', buses=buses)

@transport_bp.route('/fleet/record_fuel_invoice', methods=['GET', 'POST'])
@login_required
@admin_required
def record_fuel_invoice():
    # Implementation details from app.py refactored
    return render_template('record_fuel_invoice.html')

# ... more routes ...
