from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from .services import SuperAdminService
from core.permissions import login_required, super_admin_required

super_admin_bp = Blueprint('super_admin', __name__, url_prefix='/super_admin')

@super_admin_bp.route('/schools', methods=['GET', 'POST'])
@login_required
@super_admin_required
def manage_schools():
    service = SuperAdminService()
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        code = (request.form.get('code') or '').strip()
        sub_end = request.form.get('subscription_end')
        is_active = bool(request.form.get('is_active'))

        if not name or not code:
            flash("Name and code are required.", "error")
        elif service.get_school_by_code(code):
            flash("School code already exists.", "error")
        else:
            try:
                end_date = datetime.strptime(sub_end, "%Y-%m-%d").date() if sub_end else None
                service.create_school(name, code, end_date, is_active)
                flash("School created successfully.", "success")
            except Exception as e: flash(str(e), "error")

    schools = service.get_all_schools()
    return render_template('super_admin_schools.html', schools=schools)

@super_admin_bp.route('/schools/<int:school_id>/status', methods=['POST'])
@login_required
@super_admin_required
def update_school_status(school_id):
    service = SuperAdminService()
    action = request.form.get('action')
    active = (action == 'activate')
    service.update_school_status(school_id, active)
    flash("School status updated.", "success")
    return redirect(url_for('super_admin.manage_schools'))

@super_admin_bp.route('/schools/<int:school_id>/subscription', methods=['POST'])
@login_required
@super_admin_required
def update_school_subscription(school_id):
    service = SuperAdminService()
    sub_end = request.form.get('subscription_end')
    try:
        end_date = datetime.strptime(sub_end, "%Y-%m-%d").date() if sub_end else None
        service.update_school_subscription(school_id, end_date)
        flash("Subscription updated.", "success")
    except Exception as e: flash(str(e), "error")
    return redirect(url_for('super_admin.manage_schools'))
