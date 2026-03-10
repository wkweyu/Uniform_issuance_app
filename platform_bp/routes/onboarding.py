from flask import render_template, request, redirect, url_for, flash
from ..services.onboarding import onboard_school, get_onboarding_status
from ..decorators import platform_required


@platform_required(role='platform_admin')
def onboarding_wizard():
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        timezone = request.form.get('timezone') or 'UTC'
        default_plan = request.form.get('default_plan') or None
        school, subscription = onboard_school(name, code, timezone, default_plan)
        flash('School onboarded', 'success')
        return redirect(url_for('platform.list_schools'))
    return render_template('platform/onboarding.html')


def register_routes(bp):
    bp.add_url_rule('/onboarding', endpoint='onboarding_wizard', view_func=onboarding_wizard, methods=['GET', 'POST'])
