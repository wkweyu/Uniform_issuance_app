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
            if endpoint == "admin_settings": return url_for("super_admin.super_admin_index", **values) 
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

# Create the Flask application instance
app = create_app()

# ============================================================
# FIX 1: Register the missing currency template filter
# ============================================================
@app.template_filter('currency')
def currency_filter(value):
    """
    Custom Jinja2 filter to format numbers as currency.
    Usage in templates: {{ amount|currency }}
    """
    if value is None:
        return "$0.00"
    try:
        # Handle different numeric types (Decimal, float, int, string)
        if hasattr(value, 'amount'):  # For Decimal objects from SQLAlchemy
            value = float(str(value))
        # Convert to float and format with 2 decimal places and thousand separators
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        # If conversion fails, return the original value with a dollar sign
        return f"${value}"

# ============================================================
# Request Hooks and Routes
# ============================================================
@app.before_request
def setup_tenant():
    """Load tenant context before each request."""
    load_tenant_context()

@app.route('/health')
def health_check():
    """
    Health check endpoint for Render.
    Returns 200 OK if the app is running properly.
    """
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }), 200

@app.route('/')
@login_required
def index():
    """Main dashboard route."""
    connection = get_db_connection()
    cursor = connection.cursor()
    school_id = g.school_id or 1

    # Dashboard summary logic
    cursor.execute("SELECT COUNT(*) AS count FROM studentinfo WHERE school_id = %s", (school_id,))
    total_students = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) AS count FROM users WHERE school_id = %s", (school_id,))
    total_staff = cursor.fetchone()['count']
    
    # Get today's collections for the currency filter demo
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total 
        FROM fee_collections 
        WHERE school_id = %s AND DATE(collection_date) = CURDATE()
    """, (school_id,))
    today_collections = cursor.fetchone()['total']

    connection.close()
    
    return render_template(
        'index.html', 
        total_students=total_students, 
        total_staff=total_staff,
        today_collections=today_collections
    )

# ============================================================
# For local development only
# This block is NOT used when running on Render with Gunicorn
# ============================================================
if __name__ == "__main__":
    # Get port from environment variable (for Render compatibility) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    # Run the app
    app.run(
        host="0.0.0.0", 
        port=port, 
        debug=True  # Enable debug mode for local development
    )

# ============================================================
# For Gunicorn (production on Render)
# Some WSGI servers look for 'application' instead of 'app'
# ============================================================
# This ensures compatibility with various WSGI servers
application = app
