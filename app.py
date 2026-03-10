import os
import pymysql
from flask import Flask, render_template, jsonify, session, g, flash
from datetime import datetime
import pymysql
from extensions import db, migrate, csrf
from config import Config
from core.permissions import login_required, admin_required, super_admin_required
from core.db import get_db_connection
from core.tenancy import load_tenant_context

# Re-importing services for compat (though many are now in blueprints)
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
                return url_for("super_admin.manage_schools", **values)
            if endpoint == "update_school_status":
                return url_for("super_admin.update_school_status", **values)
            if endpoint == "update_school_subscription":
                return url_for("super_admin.update_school_subscription", **values)
            if endpoint == "admin_settings":
                return url_for("super_admin.manage_schools", **values)
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
                return url_for("auth.login", **values)
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
def index():
    connection = None
    total_students = 0
    total_staff = 0
    today_collections = 0
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        school_id = g.school_id or 1

        cursor.execute("SELECT COUNT(*) AS count FROM studentinfo WHERE school_id = %s", (school_id,))
        total_students = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) AS count FROM users WHERE school_id = %s", (school_id,))
        total_staff = cursor.fetchone()['count']

        cursor.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM fee_collections
            WHERE school_id = %s AND DATE(collection_date) = CURDATE()
            """,
            (school_id,)
        )
        today_collections = cursor.fetchone()['total']
    except pymysql.MySQLError as error:
        app.logger.error("Database connection/query failed on index: %s", error)
        flash("Database is temporarily unavailable. Please verify database credentials/account status.", "error")
    finally:
        if connection:
            connection.close()

    return render_template(
        'index.html',
        total_students=total_students,
        total_staff=total_staff,
        today_collections=today_collections
    )


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=True)


application = app
