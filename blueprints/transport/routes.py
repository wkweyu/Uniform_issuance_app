from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.transport.services import TransportService
from datetime import datetime

transport_bp = Blueprint('transport', __name__)


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


def _parse_float(value, field_name, default=None):
    if value in (None, ''):
        if default is not None:
            return float(default)
        raise ValueError(f"{field_name} is required and must be a valid number.")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")

@transport_bp.route('/fleet/fleet_dashboard')
@login_required
def fleet_dashboard():
    connection = get_db_connection(); service = TransportService(connection)
    try:
        buses = service.get_buses()
        stats = service.get_fleet_dashboard_summary()
        return render_template('fleet_dashboard.html', buses=buses, stats=stats)
    finally: connection.close()

@transport_bp.route('/fleet/buses', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_buses():
    connection = get_db_connection(); service = TransportService(connection)
    if request.method == 'POST':
        try:
            data = {
                'reg_no': _required_text(request.form.get('reg_no'), 'reg_no').upper(),
                'model': request.form.get('model') or request.form.get('make'),
                'capacity': _required_int(request.form.get('capacity'), 'capacity'),
                'current_mileage': _required_int(request.form.get('current_mileage'), 'current_mileage'),
                'driver_name': request.form.get('driver_name')
            }
            service.add_bus(data)
            flash("Bus added successfully.", "success")
        except ValueError as e: flash(str(e), "error")
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
                'reg_no': _required_text(request.form.get('reg_no'), 'reg_no').upper(),
                'model': request.form.get('model') or request.form.get('make'),
                'capacity': _required_int(request.form.get('capacity'), 'capacity'),
                'current_mileage': _required_int(request.form.get('current_mileage'), 'current_mileage'),
                'driver_name': request.form.get('driver_name')
            }
            service.update_bus(bus_id, data)
            flash("Bus updated successfully.", "success")
            return redirect(url_for('transport.manage_buses'))
        except ValueError as e: flash(str(e), "error")
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
        flash("Bus deleted.", "success")
    except ValueError as e: flash(str(e), "error")
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
                'bus_id': _required_int(request.form.get('bus_id'), 'bus_id'),
                'service_date': _required_text(request.form.get('service_date'), 'service_date'),
                'service_type': _required_text(request.form.get('service_type'), 'service_type'),
                'description': request.form.get('description'),
                'cost': _parse_float(request.form.get('cost'), 'cost'),
                'garage_name': request.form.get('garage_name'),
                'mileage_at_service': _required_int(request.form.get('mileage_at_service'), 'mileage_at_service')
            }
            service.record_service(data)
            flash("Service record saved.", "success")
            return redirect(url_for('transport.service_register'))
        except ValueError as e: flash(str(e), "error")
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
    return render_template('service_register.html', services=history)

@transport_bp.route('/fleet/issue_fuel', methods=['GET', 'POST'])
@login_required
def issue_fuel():
    connection = get_db_connection(); service = TransportService(connection)
    if request.method == 'POST':
        try:
            qty = _parse_float(request.form.get('quantity'), 'quantity')
            price = _parse_float(request.form.get('unit_price'), 'unit_price')
            data = {
                'bus_id': _required_int(request.form.get('bus_id'), 'bus_id'),
                'date_issued': _required_text(request.form.get('date_issued'), 'date_issued'),
                'fuel_type': _required_text(request.form.get('fuel_type'), 'fuel_type'),
                'quantity': qty,
                'unit_price': price,
                'total_cost': qty * price,
                'current_mileage': _required_int(request.form.get('current_mileage'), 'current_mileage'),
                'issued_by': session['userNo']
            }
            voucher_no = service.issue_fuel(data)
            flash(f"Fuel issued. Voucher: {voucher_no}", "success")
            return redirect(url_for('transport.print_voucher', voucher_no=voucher_no))
        except ValueError as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")

    buses = service.get_buses()
    connection.close()
    return render_template('issue_fuel.html', buses=buses)

@transport_bp.route('/fleet/print_voucher/<voucher_no>')
@login_required
def print_voucher(voucher_no):
    connection = get_db_connection(); service = TransportService(connection)
    voucher = service.get_fuel_voucher_for_print(voucher_no)
    connection.close()
    return render_template('print_fuel_voucher.html', voucher=voucher)

@transport_bp.route("/fuel/voucher_register", methods=['GET', 'POST'])
@login_required
def voucher_register():
    connection = get_db_connection(); service = TransportService(connection)
    date_from = request.args.get('date_from') or request.args.get('start_date') or ''
    date_to = request.args.get('date_to') or request.args.get('end_date') or ''
    filters = {
        'reg_no': request.args.get('registration_no', ''),
        'driver_name': request.args.get('driver_name', ''),
        'voucher_no': request.args.get('voucher_no', ''),
    }
    vouchers = service.get_fuel_vouchers(date_from or None, date_to or None)
    connection.close()
    return render_template(
        'fuel_voucher_register.html',
        vouchers=vouchers,
        filters=filters,
        date_from=date_from,
        date_to=date_to,
    )

@transport_bp.route('/fleet/routes', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_transport_routes():
    connection = get_db_connection(); service = TransportService(connection)
    if request.method == 'POST':
        try:
            data = {
                'name': _required_text(request.form.get('name'), 'name'),
                'amount': _parse_float(request.form.get('amount', 0), 'amount', default=0),
                'description': request.form.get('description', '').strip()
            }
            service.add_route(data)
            flash("Route added.", "success")
        except ValueError as e: flash(str(e), "error")
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
        flash("Route deleted.", "success")
    except ValueError as e: flash(str(e), "error")
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
    reminders = []
    # Logic for reminders (e.g. mileage > threshold)
    connection.close()
    return render_template('service_reminders.html', reminders=reminders)

@transport_bp.route('/fleet/record_fuel_invoice', methods=['GET', 'POST'])
@login_required
@admin_required
def record_fuel_invoice():
    # Implementation details from app.py refactored
    return render_template('record_fuel_invoice.html')

# ... more routes ...
