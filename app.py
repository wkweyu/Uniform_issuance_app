import os
import pymysql
import traceback
from flask import Flask, render_template, jsonify, session, g, url_for
from datetime import datetime
from extensions import db, migrate, csrf
from config import Config
from core.permissions import login_required, admin_required, super_admin_required
from core.db import get_db_connection
from core.tenancy import load_tenant_context
from core.helpers import format_currency, get_current_term_and_year

# Re-importing services for compat
from blueprints.classes.services import ClassManagementService, ValidationError, PromotionError
from blueprints.fees.services import FeesService, FeesError
from blueprints.exams.services import ExamManagementService, ExamManagementError
from blueprints.finance.services import FinanceService, FinanceError
from blueprints.procurement.services import ProcurementService, ProcurementError

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
    from blueprints.admin.routes import admin_bp
    app.register_blueprint(admin_bp)
    from blueprints.uniforms.routes import uniforms_bp
    app.register_blueprint(uniforms_bp)
    from blueprints.reports.routes import reports_bp
    app.register_blueprint(reports_bp)

    return app

app = create_app()

# Register template filters directly on the app instance
app.jinja_env.filters['currency'] = format_currency

# Register context processor for backward compatibility and global variables
@app.context_processor
def utility_processor():
    def compat_url_for(endpoint, **values):
        # Manual high-priority overrides
        overrides = {
            "login": "auth.login",
            "logout": "auth.logout",
            "index": "index",
            "admin_settings": "admin.admin_settings",
            "manage_users": "admin.manage_users",
            "manage_term_dates": "admin.manage_term_dates",
            "current_term_status": "admin.current_term_status",
            "uniform_dashboard": "uniforms.uniform_dashboard",
            "issue_uniform": "uniforms.issue_uniform",
            "manage_uniform_items": "uniforms.manage_uniform_items",
            "receipt": "uniforms.receipt",
            "reports_dashboard": "reports.reports_dashboard",
            "student_search": "reports.student_search",
            "student_history": "reports.student_history",
            "item_totals": "reports.item_totals",
            "receipts_register": "reports.receipts_register",
        }
        if endpoint in overrides:
            return url_for(overrides[endpoint], **values)

        try:
            return url_for(endpoint, **values)
        except Exception:
            # Fallback mapping logic
            prefixes = {
                'auth': ['login', 'logout', 'reset_password', 'user_profile'],
                'admin': ['admin_settings', 'manage_users', 'manage_term_dates', 'current_term_status'],
                'students': ['admit_student', 'students_list', 'student_profile', 'edit_student', 'toggle_student_status', 'print_admission_form'],
                'classes': ['manage_classes', 'create_class', 'promote_students', 'manage_streams', 'allocate_teacher'],
                'fees': ['fees_dashboard', 'collect_fees', 'manage_fee_structures', 'print_fee_receipt', 'bulk_invoice', 'bulk_debit_term', 'bulk_post_fees', 'admin_fees_rollup'],
                'finance': ['finance_dashboard', 'manage_vouchers', 'manage_budgets', 'trial_balance_report', 'income_statement_report', 'balance_sheet_report'],
                'exams': ['exams_dashboard', 'create_exam', 'marks_entry', 'manage_grading_scales'],
                'procurement': ['procurement_dashboard', 'manage_requisitions', 'create_purchase_order', 'manage_suppliers'],
                'inventory': ['manage_stock', 'stock_report'],
                'transport': ['fleet_dashboard', 'manage_buses', 'record_fuel_invoice', 'service_register', 'manage_transport_routes', 'issue_fuel'],
                'uniforms': ['uniform_dashboard', 'issue_uniform', 'manage_uniform_items', 'receipt'],
                'reports': ['reports_dashboard', 'student_search', 'student_history', 'item_totals', 'receipts_register'],
                'super_admin': ['manage_schools', 'update_school_status', 'update_school_subscription']
            }
            for blueprint, funcs in prefixes.items():
                if endpoint in funcs:
                    try:
                        return url_for(f"{blueprint}.{endpoint}", **values)
                    except Exception:
                        continue
            # Fallback to dead link to avoid crashing templates
            return "#"

    return dict(
        url_for=compat_url_for,
        datetime=datetime,
        now=datetime.utcnow()
    )

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Server Error: {error}")
    app.logger.error(traceback.format_exc())
    return render_template('errors/500.html', error=error), 500

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.before_request
def setup_tenant():
    load_tenant_context()

@app.route('/health')
def health_check():
    health = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database": {"connected": False},
        "ssl": False
    }
    try:
        connection = get_db_connection()
        connection.ping(reconnect=True)
        health["database"]["connected"] = True
        connection.close()
    except Exception as e:
        health["database"]["error"] = str(e)

    return jsonify(health), 200

@app.route('/')
@login_required
def index():
    school_id = g.school_id or 1
    context = {
        'total_students': 0, 'total_staff': 0, 'today_collections': 0,
        'active_buses': 0, 'vouchers_today': 0, 'uniform_issued': 0,
        'term_number': None, 'year': None, 'total_classes': 0
    }

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) AS count FROM studentinfo WHERE school_id = %s", (school_id,))
        context['total_students'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) AS count FROM users WHERE school_id = %s", (school_id,))
        context['total_staff'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) AS count FROM classes WHERE school_id = %s AND is_active = 1", (school_id,))
        context['total_classes'] = cursor.fetchone()['count']

        term_number, year = get_current_term_and_year()
        context['term_number'] = term_number
        context['year'] = year

        cursor.execute("SELECT SUM(total_price) as total FROM uniform_receipts WHERE school_id = %s AND DATE(date_issued) = CURDATE()", (school_id,))
        context['today_collections'] = cursor.fetchone()['total'] or 0

        cursor.execute("SELECT COUNT(*) as count FROM buses WHERE school_id = %s AND active = 1", (school_id,))
        context['active_buses'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM fuel_vouchers WHERE school_id = %s AND DATE(date) = CURDATE()", (school_id,))
        context['vouchers_today'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(DISTINCT receipt_no) as count FROM uniform_receipts WHERE school_id = %s AND term = %s AND yr = %s", (school_id, term_number, year))
        context['uniform_issued'] = cursor.fetchone()['count']

        connection.close()
    except Exception as e:
        app.logger.error(f"Error loading dashboard data: {e}")

    return render_template('index.html', **context)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
