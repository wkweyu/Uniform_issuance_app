from flask import flash, redirect, render_template, request, session, url_for

from ..decorators import platform_required
from ..services.access import (
    available_platform_roles,
    get_platform_access_settings,
    role_capability_rows,
    update_platform_access_settings,
)
from ..services.audit import list_logs


@platform_required(permission='platform_settings')
def view_access_settings():
    settings = get_platform_access_settings()
    return render_template(
        'platform/access_settings.html',
        settings=settings,
        role_rows=role_capability_rows(),
        rollout_role_options=available_platform_roles(include_super_admin=False),
        rollout_audit_logs=list_logs(action='platform_access_settings_updated', limit=8),
        rollout_denied_logs=list_logs(action='platform_login_rollout_denied', limit=8),
        tenant_enforcement_logs=list_logs(action='tenant_enforcement_blocked', limit=8),
        tenant_enforcement_observed_logs=list_logs(action='tenant_enforcement_observed', limit=8),
    )


@platform_required(permission='platform_settings')
def update_access_settings():
    rollout_mode = request.form.get('rollout_mode')
    allowed_emails = request.form.get('allowed_emails') or ''
    allowed_roles = request.form.getlist('allowed_roles')
    update_platform_access_settings(
        rollout_mode=rollout_mode,
        allowed_emails=allowed_emails,
        allowed_roles=allowed_roles,
        tenant_enforcement_mode=request.form.get('tenant_enforcement_mode'),
        tenant_enforcement_notes=request.form.get('tenant_enforcement_notes') or '',
        actor_user_id=session.get('platform_user_id'),
    )
    flash('Platform rollout settings updated.', 'success')
    return redirect(url_for('platform.view_access_settings'))


def register_routes(bp):
    bp.add_url_rule('/settings/access', endpoint='view_access_settings', view_func=view_access_settings)
    bp.add_url_rule('/settings/access/update', endpoint='update_access_settings', view_func=update_access_settings, methods=['POST'])