from flask import render_template, request, redirect, url_for, flash
from ..decorators import platform_required


@platform_required(role='platform_admin')
def list_plans():
    from ..models import Plan
    plans = Plan.query.order_by(Plan.name).all()
    return render_template('platform/plans_list.html', plans=plans)


@platform_required(role='platform_admin')
def create_plan():
    if request.method == 'POST':
        name = request.form.get('name')
        price = int(float(request.form.get('price', 0)) * 100)
        billing = request.form.get('billing_period', 'monthly')
        from ..models import Plan
        if Plan.query.filter_by(name=name).first():
            flash('Plan exists', 'warning')
            return redirect(url_for('platform.create_plan'))
        plan = Plan(name=name, price_cents=price, billing_period=billing)
        from app import db
        db.session.add(plan)
        db.session.commit()
        flash('Plan created', 'success')
        return redirect(url_for('platform.list_plans'))
    return render_template('platform/plans_create.html')


def register_routes(bp):
    bp.add_url_rule('/plans', endpoint='list_plans', view_func=list_plans)
    bp.add_url_rule('/plans/create', endpoint='create_plan', view_func=create_plan, methods=['GET', 'POST'])
