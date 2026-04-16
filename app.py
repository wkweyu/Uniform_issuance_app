import os
import pymysql
from flask import Flask, render_template, jsonify, session, g, flash
from datetime import datetime
import pymysql
from extensions import db, migrate, csrf
from models import School, SchoolSettings, UniformPrice, User
from config import Config
from core.permissions import login_required, admin_required, super_admin_required, tenant_required
from core.db import get_db_connection
from core.tenancy import load_tenant_context, resolve_school_request_access

# Re-importing services for compat (though many are now in blueprints)
from blueprints.classes.services import ClassManagementService, ValidationError, PromotionError
from blueprints.fees.services import FeesService, FeesError
from blueprints.exams.services import ExamManagementService, ExamManagementError
from blueprints.finance.services import FinanceService, FinanceError
from blueprints.procurement.services import ProcurementService, ProcurementError
from blueprints.dashboard.services import DashboardService

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Register Blueprints
    from blueprints.auth.routes import auth_bp
    app.register_blueprint(auth_bp)
    from blueprints.super_admin.routes import super_admin_bp
    app.register_blueprint(super_admin_bp)
    from blueprints.students.routes import students_bp
    app.register_blueprint(students_bp)
    from blueprints.classes.routes import classes_bp
    app.register_blueprint(classes_bp)
    from blueprints.fees.routes import fees_bp
    app.register_blueprint(fees_bp)
    from blueprints.finance.routes import finance_bp
    app.register_blueprint(finance_bp)
    from blueprints.exams.routes import exams_bp
    app.register_blueprint(exams_bp)
    from blueprints.procurement.routes import procurement_bp
    app.register_blueprint(procurement_bp)
    from blueprints.inventory.routes import inventory_bp
    app.register_blueprint(inventory_bp)
    from blueprints.transport.routes import transport_bp
    app.register_blueprint(transport_bp)
    from blueprints.farm.routes import farm_bp
    app.register_blueprint(farm_bp)
    from blueprints.payroll.routes import payroll_bp
    app.register_blueprint(payroll_bp)
    from blueprints.attendance.routes import attendance_bp
    app.register_blueprint(attendance_bp)
    from platform_bp import init_platform
    init_platform(app, url_prefix='/platform')

    # Context processor for backward compatibility in templates
    @app.context_processor
    def utility_processor():
        from flask import url_for, current_app

        def compat_url_for(endpoint, **values):
            # Auth
            if endpoint == "login":
                return url_for("auth.login", **values)
            if endpoint == "logout":
                return url_for("auth.logout", **values)
            # Super Admin
            if endpoint == "super_admin":
                return url_for("super_admin.super_admin_index", **values)
            if endpoint == "manage_schools":
                return url_for("platform.list_schools", **values)
            if endpoint == "update_school_status":
                return url_for("super_admin.update_school_status", **values)
            if endpoint == "update_school_subscription":
                return url_for("super_admin.update_school_subscription", **values)
            if endpoint == "admin_settings":
                return url_for("auth.admin_settings", **values)
            if endpoint == "school_profile":
                return url_for("auth.school_profile", **values)
            # Students
            if endpoint == "admit_student":
                return url_for("students.admit_student", **values)
            if endpoint == "students_list":
                return url_for("students.students_list", **values)
            if endpoint == "student_profile":
                return url_for("students.student_profile", **values)
            if endpoint == "edit_student":
                return url_for("students.edit_student", **values)
            if endpoint == "toggle_student_status":
                return url_for("students.toggle_student_status", **values)
            if endpoint == "print_admission_form":
                return url_for("students.print_admission_form", **values)
            # Fees
            if endpoint == "fees_dashboard":
                return url_for("fees.fees_dashboard", **values)
            if endpoint == "collect_fees":
                return url_for("fees.collect_fees", **values)
            if endpoint == "print_fee_receipt":
                return url_for("fees.print_fee_receipt", **values)
            # Finance
            if endpoint == "finance_dashboard":
                return url_for("finance.finance_dashboard", **values)
            
            # Platform & Uniform
            if endpoint == "platform.login":
                return url_for("platform.login", **values)
            if endpoint == "issue_uniform":
                return url_for("inventory.issue_uniform", **values)
            if endpoint == "receipt":
                return url_for("inventory.receipt", **values)
            if endpoint == "print_receipt":
                return url_for("inventory.print_receipt", **values)
            if endpoint == "submit_issuance":
                return url_for("inventory.submit_issuance", **values)
            if endpoint == "manage_uniform_items":
                return url_for("inventory.manage_uniform_items", **values)
            if endpoint == "manage_users":
                return url_for("auth.manage_users", **values)
            if endpoint == "report_issued_summary":
                return url_for("inventory.report_issued_summary", **values)
            if endpoint == "items_totals_report":
                return url_for("inventory.items_totals_report", **values)
            if endpoint == "receipts_register_report":
                return url_for("inventory.receipts_register_report", **values)
            if endpoint == "manage_term_dates":
                return url_for("inventory.manage_term_dates", **values)
            if endpoint == "student_search":
                return url_for("students.admit_student", **values) # Mapping to admission search as fallback
            if endpoint == "attendance_dashboard":
                return url_for("attendance.attendance_dashboard", **values)
            if endpoint == "take_attendance":
                return url_for("attendance.take_attendance", **values)
            if endpoint == "attendance_report":
                return url_for("attendance.attendance_report", **values)
                                
            # Add more as needed by templates

            try:
                if endpoint == 'uniform_dashboard': 
                    return url_for('inventory.manage_stock', **values) # Point to stock as a dashboard
                return url_for(endpoint, **values)
            except Exception:
                # Fallback: try resolving endpoint under all registered blueprints
                for blueprint in current_app.blueprints.keys():
                    try:
                        return url_for(f"{blueprint}.{endpoint}", **values)
                    except Exception:
                        continue
                return url_for(endpoint, **values)

        return dict(url_for=compat_url_for, datetime=datetime)

    @app.context_processor
    def inject_school_branding():
        """Make school name, logo, and contact info available in all templates."""
        defaults = {
            'school_name': 'SkoolTrack Pro',
            'school_logo': None,
            'school_address': '',
            'school_phone': '',
            'school_email': '',
            'school_website': '',
            'school_currency': 'KES',
            'school_motto': '',
        }
        school_id = session.get('school_id')
        if not school_id:
            return {'school': type('obj', (object,), defaults)()}

        # Cache in session to avoid DB hit on every request
        cached = session.get('_school_settings')
        if cached:
            return {'school': type('obj', (object,), cached)()}

        try:
            from core.db import get_db_connection
            import pymysql
            conn = get_db_connection()
            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(
                    "SELECT school_name, logo, address, phone, email, website, currency "
                    "FROM school_settings WHERE school_id = %s", (school_id,))
                row = cur.fetchone()
            conn.close()
            if row:
                defaults['school_name'] = row['school_name'] or session.get('school_name', 'SkoolTrack Pro')
                defaults['school_logo'] = row['logo'] or None
                defaults['school_address'] = row['address'] or ''
                defaults['school_phone'] = row['phone'] or ''
                defaults['school_email'] = row['email'] or ''
                defaults['school_website'] = row['website'] or ''
                defaults['school_currency'] = row['currency'] or 'KES'
            session['_school_settings'] = defaults
        except Exception:
            pass

        return {'school': type('obj', (object,), defaults)()}

    return app


# Create the Flask application instance
app = create_app()


@app.template_filter('currency')
def currency_filter(value):
    if value is None:
        return "$0.00"
    try:
        if hasattr(value, 'amount'):
            value = float(str(value))
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return f"${value}"


@app.before_request
def setup_tenant():
    load_tenant_context()
    return resolve_school_request_access()


@app.route('/health')
def health_check():
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            cursor.fetchone()
        connection.close()
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat()
        }), 200
    except pymysql.MySQLError as error:
        return jsonify({
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(error)
        }), 503


@app.route('/')
@login_required
@tenant_required
def index():
    connection = None
    dashboard = {}
    term_number = None
    year = None
    term_start = None
    term_end = None
    try:
        connection = get_db_connection()
        # Fetch current term
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                "SELECT term_number, year, start_date, end_date FROM uniform_term_dates "
                "WHERE CURDATE() BETWEEN start_date AND end_date AND school_id = %s LIMIT 1",
                (g.school_id,),
            )
            term_row = cursor.fetchone()
            if term_row:
                term_number = term_row['term_number']
                year = term_row['year']
                term_start = str(term_row['start_date'])
                term_end = str(term_row['end_date'])

        service = DashboardService(connection, school_id=g.school_id)
        dashboard = service.get_full_dashboard(term_start=term_start, term_end=term_end)
    except pymysql.MySQLError as error:
        app.logger.error("Database connection/query failed on index: %s", error)
        flash("Database is temporarily unavailable. Please verify database credentials/account status.", "error")
    finally:
        if connection:
            connection.close()

    return render_template(
        'index.html',
        d=dashboard,
        term_number=term_number,
        year=year,
    )


# ------------------------------------------------------------------
# Events CRUD
# ------------------------------------------------------------------
@app.route('/events/add', methods=['POST'])
@login_required
@admin_required
@tenant_required
def add_event():
    from flask import request, redirect, url_for
    connection = None
    try:
        connection = get_db_connection()
        service = DashboardService(connection, school_id=g.school_id)
        service.add_event(
            title=request.form['title'],
            event_date=request.form['event_date'],
            event_type=request.form.get('event_type', 'other'),
            description=request.form.get('description', ''),
            end_date=request.form.get('end_date') or None,
            created_by=session.get('userNo'),
        )
        flash('Event added.', 'success')
    except Exception as e:
        app.logger.error("Failed to add event: %s", e)
        flash('Failed to add event.', 'error')
    finally:
        if connection:
            connection.close()
    return redirect(url_for('index'))


@app.route('/events/<int:event_id>/delete', methods=['POST'])
@login_required
@admin_required
@tenant_required
def delete_event(event_id):
    from flask import redirect, url_for
    connection = None
    try:
        connection = get_db_connection()
        service = DashboardService(connection, school_id=g.school_id)
        service.delete_event(event_id)
        flash('Event deleted.', 'success')
    except Exception as e:
        app.logger.error("Failed to delete event: %s", e)
        flash('Failed to delete event.', 'error')
    finally:
        if connection:
            connection.close()
    return redirect(url_for('index'))


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=True)


application = app
