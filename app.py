import os
import pymysql
from flask import Flask, render_template, jsonify, session, g
from datetime import datetime
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
        from flask import url_for
        def compat_url_for(endpoint, **values):
            # Auth
            if endpoint == "login": return url_for("auth.login", **values)
            if endpoint == "logout": return url_for("auth.logout", **values)
            # Super Admin
            if endpoint == "super_admin": return url_for("super_admin.super_admin_index", **values)
            if endpoint == "manage_schools": return url_for("super_admin.manage_schools", **values)
            if endpoint == "update_school_status": return url_for("super_admin.update_school_status", **values)
            if endpoint == "update_school_subscription": return url_for("super_admin.update_school_subscription", **values)
            # Students
            if endpoint == "admit_student": return url_for("students.admit_student", **values)
            if endpoint == "students_list": return url_for("students.students_list", **values)
            if endpoint == "student_profile": return url_for("students.student_profile", **values)
            if endpoint == "edit_student": return url_for("students.edit_student", **values)
            if endpoint == "toggle_student_status": return url_for("students.toggle_student_status", **values)
            if endpoint == "print_admission_form": return url_for("students.print_admission_form", **values)
            # Fees
            if endpoint == "fees_dashboard": return url_for("fees.fees_dashboard", **values)
            if endpoint == "collect_fees": return url_for("fees.collect_fees", **values)
            if endpoint == "print_fee_receipt": return url_for("fees.print_fee_receipt", **values)
            # Finance
            if endpoint == "finance_dashboard": return url_for("finance.finance_dashboard", **values)
            # Add more as needed by templates

            try:
                return url_for(endpoint, **values)
            except:
                # Fallback mapping logic
                prefixes = {
                    'students': ['admit_student', 'students_list', 'student_profile', 'edit_student', 'api_search_students'],
                    'classes': ['manage_classes', 'create_class', 'promote_students'],
                    'fees': ['fees_dashboard', 'collect_fees', 'manage_fee_structures'],
                    'finance': ['finance_dashboard', 'manage_vouchers'],
                    'exams': ['exams_dashboard', 'create_exam', 'marks_entry'],
                    'procurement': ['procurement_dashboard', 'manage_requisitions'],
                    'inventory': ['manage_stock', 'stock_report'],
                    'transport': ['fleet_dashboard', 'manage_buses']
                }
                for blueprint, funcs in prefixes.items():
                    if endpoint in funcs:
                        return url_for(f"{blueprint}.{endpoint}", **values)
                return url_for(endpoint, **values)
        return dict(url_for=compat_url_for)

    return app

app = create_app()

@app.before_request
def setup_tenant():
    load_tenant_context()

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route('/')
@login_required
def index():
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1

    # Dashboard summary logic
    cursor.execute("SELECT COUNT(*) AS count FROM studentinfo WHERE school_id = %s", (school_id,))
    total_students = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) AS count FROM users WHERE school_id = %s", (school_id,))
    total_staff = cursor.fetchone()['count']

    connection.close()
    return render_template('index.html', total_students=total_students, total_staff=total_staff)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
