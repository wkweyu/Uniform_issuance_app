from flask import render_template
from ..decorators import platform_required


@platform_required(role='platform_admin')
def view_audit():
    from ..models import AuditLog
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template('platform/audit_list.html', logs=logs)


def register_routes(bp):
    bp.add_url_rule('/audit', endpoint='view_audit', view_func=view_audit)
