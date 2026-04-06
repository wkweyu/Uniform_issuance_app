from flask import Blueprint, redirect, url_for, flash, session
from core.permissions import login_required, super_admin_required

super_admin_bp = Blueprint('super_admin', __name__, url_prefix='/super_admin')


def _redirect_to_platform_school_controls(school_id=None):
    if school_id is not None:
        destination = url_for('platform.school_detail', school_id=school_id)
    else:
        destination = url_for('platform.list_schools')

    if session.get('platform_user_id'):
        return redirect(destination)

    flash('School lifecycle controls moved to the platform control plane. Sign in with a platform account to continue.', 'info')
    return redirect(url_for('platform.login', next=destination))

@super_admin_bp.route('/schools', methods=['GET', 'POST'])
@login_required
@super_admin_required
def manage_schools():
    return _redirect_to_platform_school_controls()

@super_admin_bp.route('/schools/<int:school_id>/status', methods=['POST'])
@login_required
@super_admin_required
def update_school_status(school_id):
    return _redirect_to_platform_school_controls(school_id=school_id)

@super_admin_bp.route('/schools/<int:school_id>/subscription', methods=['POST'])
@login_required
@super_admin_required
def update_school_subscription(school_id):
    return _redirect_to_platform_school_controls(school_id=school_id)
