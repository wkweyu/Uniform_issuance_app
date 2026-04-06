from flask import abort, render_template, request, redirect, session, url_for, flash
from ..config.modules import family_label, module_definition, module_group_label
from ..decorators import platform_required
from ..services.audit import log as audit_log
from ..services.pricing_catalog import (
    bundle_family_options,
    default_module_codes_for_bundle,
    ensure_pricing_catalog_seeded,
    pricing_features_snapshot,
)


def _parse_price_cents(raw_value):
    cleaned = (raw_value or '').strip()
    if not cleaned:
        raise ValueError('Price is required.')
    try:
        price_cents = int(round(float(cleaned) * 100))
    except (TypeError, ValueError):
        raise ValueError('Price must be a valid number.')
    if price_cents < 0:
        raise ValueError('Price cannot be negative.')
    return price_cents


def _parse_band_prices(student_bands):
    first_band_price = None
    band_price_map = {}
    for band in student_bands:
        price_cents = _parse_price_cents(request.form.get(f'band_price_{band.id}'))
        band_price_map[band.id] = price_cents
        if first_band_price is None:
            first_band_price = price_cents
    return band_price_map, first_band_price or 0


def _save_plan_pricing(db, plan, selected_module_codes, module_lookup, student_bands, band_price_map):
    from ..models import PlanBandPrice, PlanModule

    PlanModule.query.filter_by(plan_id=plan.id).delete()
    PlanBandPrice.query.filter_by(plan_id=plan.id).delete()

    for code in selected_module_codes:
        module = module_lookup.get(code)
        if module is None:
            continue
        db.session.add(
            PlanModule(
                plan_id=plan.id,
                module_id=module.id,
                is_included=True,
                addon_price_cents=0 if module.is_addon else None,
            )
        )

    for band in student_bands:
        db.session.add(
            PlanBandPrice(
                plan_id=plan.id,
                student_band_id=band.id,
                price_cents=band_price_map.get(band.id, 0),
            )
        )


def _plan_form_context(plan=None, form_data=None, student_bands=None, modules=None, selected_module_codes=None, band_price_map=None):
    source = form_data or {}
    resolved_bundle = source.get('bundle_family', getattr(plan, 'bundle_family', 'academic') if plan else 'academic')
    normalized_modules = []
    for module in (modules or []):
        registry_item = module_definition(module.code) or {}
        normalized_modules.append(
            {
                'code': module.code,
                'name': registry_item.get('name', module.name),
                'family': registry_item.get('family', module.family),
                'family_label': family_label(registry_item.get('family', module.family)),
                'group_label': module_group_label(module.code) or ('Add-On' if module.is_addon else 'Core'),
                'is_addon': module.is_addon,
            }
        )
    return {
        'plan': plan,
        'bundle_family_options': bundle_family_options(),
        'student_bands': student_bands or [],
        'bundle_family_label': family_label(resolved_bundle),
        'core_modules': [module for module in normalized_modules if not module['is_addon']],
        'addon_modules': [module for module in normalized_modules if module['is_addon']],
        'selected_module_codes': selected_module_codes if selected_module_codes is not None else default_module_codes_for_bundle(resolved_bundle),
        'band_price_map': band_price_map or {},
        'form_values': {
            'name': source.get('name', getattr(plan, 'name', '') if plan else ''),
            'billing_period': source.get('billing_period', getattr(plan, 'billing_period', 'monthly') if plan else 'monthly'),
            'bundle_family': resolved_bundle,
        },
    }


@platform_required(permission='billing_access')
def list_plans():
    from app import db
    from ..models import ModuleCatalog, Plan, PlanBandPrice, PlanModule, StudentBand

    ensure_pricing_catalog_seeded(db.session)
    plans = Plan.query.order_by(Plan.name).all()
    plan_ids = [plan.id for plan in plans]
    modules = ModuleCatalog.query.order_by(ModuleCatalog.sort_order.asc(), ModuleCatalog.name.asc()).all()
    student_bands = StudentBand.query.filter_by(is_active=True).order_by(StudentBand.sort_order.asc()).all()
    module_lookup = {module.id: module for module in modules}
    plan_modules = PlanModule.query.filter(PlanModule.plan_id.in_(plan_ids)).all() if plan_ids else []
    plan_band_prices = PlanBandPrice.query.filter(PlanBandPrice.plan_id.in_(plan_ids)).all() if plan_ids else []

    modules_by_plan = {}
    for item in plan_modules:
        module = module_lookup.get(item.module_id)
        if module is None:
            continue
        registry_item = module_definition(module.code) or {}
        modules_by_plan.setdefault(item.plan_id, []).append(
            {
                'code': module.code,
                'name': registry_item.get('name', module.name),
                'family': registry_item.get('family', module.family),
                'family_label': family_label(registry_item.get('family', module.family)),
                'group_label': module_group_label(module.code) or ('Add-On' if module.is_addon else 'Core'),
            }
        )

    band_prices_by_plan = {}
    for item in plan_band_prices:
        band_prices_by_plan.setdefault(item.plan_id, {})[item.student_band_id] = item.price_cents

    bundle_family_labels = {plan.id: family_label(plan.bundle_family) for plan in plans}

    return render_template(
        'platform/plans_list.html',
        plans=plans,
        student_bands=student_bands,
        modules_by_plan=modules_by_plan,
        band_prices_by_plan=band_prices_by_plan,
        bundle_family_labels=bundle_family_labels,
    )


@platform_required(permission='plans_write')
def create_plan():
    from app import db
    from ..models import ModuleCatalog, Plan, StudentBand

    ensure_pricing_catalog_seeded(db.session)
    modules = ModuleCatalog.query.filter_by(is_active=True).order_by(ModuleCatalog.sort_order.asc(), ModuleCatalog.name.asc()).all()
    student_bands = StudentBand.query.filter_by(is_active=True).order_by(StudentBand.sort_order.asc()).all()
    module_lookup = {module.code: module for module in modules}

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        billing = (request.form.get('billing_period') or 'monthly').strip() or 'monthly'
        bundle_family = (request.form.get('bundle_family') or 'academic').strip() or 'academic'
        selected_module_codes = request.form.getlist('module_codes')
        form_data = {
            'name': name,
            'billing_period': billing,
            'bundle_family': bundle_family,
        }

        if not name:
            flash('Plan name is required.', 'error')
            return render_template('platform/plans_form.html', mode='create', **_plan_form_context(form_data=form_data, student_bands=student_bands, modules=modules, selected_module_codes=selected_module_codes))
        if Plan.query.filter_by(name=name).first():
            flash('A plan with that name already exists.', 'warning')
            return render_template('platform/plans_form.html', mode='create', **_plan_form_context(form_data=form_data, student_bands=student_bands, modules=modules, selected_module_codes=selected_module_codes))
        if not selected_module_codes:
            flash('Select at least one module for the plan.', 'error')
            return render_template('platform/plans_form.html', mode='create', **_plan_form_context(form_data=form_data, student_bands=student_bands, modules=modules, selected_module_codes=selected_module_codes))

        try:
            band_price_map, first_band_price = _parse_band_prices(student_bands)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('platform/plans_form.html', mode='create', **_plan_form_context(form_data=form_data, student_bands=student_bands, modules=modules, selected_module_codes=selected_module_codes))

        plan = Plan(
            name=name,
            price_cents=first_band_price,
            billing_period=billing,
            bundle_family=bundle_family,
            pricing_model='student_band',
        )
        db.session.add(plan)
        db.session.flush()
        plan.features = pricing_features_snapshot(bundle_family, selected_module_codes, band_price_map, student_bands)
        _save_plan_pricing(db, plan, selected_module_codes, module_lookup, student_bands, band_price_map)
        db.session.commit()
        audit_log(
            actor_user_id=session.get('platform_user_id'),
            action='plan_created',
            target_table='plans',
            target_id=plan.id,
            changes={
                'name': plan.name,
                'price_cents': plan.price_cents,
                'billing_period': plan.billing_period,
                'bundle_family': plan.bundle_family,
                'module_codes': selected_module_codes,
            },
        )
        flash('Plan created', 'success')
        return redirect(url_for('platform.list_plans'))
    return render_template('platform/plans_form.html', mode='create', **_plan_form_context(student_bands=student_bands, modules=modules))


@platform_required(permission='plans_write')
def edit_plan(plan_id):
    from app import db
    from ..models import ModuleCatalog, Plan, PlanBandPrice, PlanModule, StudentBand

    ensure_pricing_catalog_seeded(db.session)
    modules = ModuleCatalog.query.filter_by(is_active=True).order_by(ModuleCatalog.sort_order.asc(), ModuleCatalog.name.asc()).all()
    student_bands = StudentBand.query.filter_by(is_active=True).order_by(StudentBand.sort_order.asc()).all()
    module_lookup = {module.code: module for module in modules}
    module_id_lookup = {module.id: module.code for module in modules}

    plan = db.session.get(Plan, plan_id)
    if plan is None:
        abort(404)

    existing_plan_modules = PlanModule.query.filter_by(plan_id=plan.id).all()
    existing_band_prices = PlanBandPrice.query.filter_by(plan_id=plan.id).all()
    selected_module_codes = [module_id_lookup.get(item.module_id) for item in existing_plan_modules if module_id_lookup.get(item.module_id)]
    if not selected_module_codes:
        selected_module_codes = default_module_codes_for_bundle(plan.bundle_family)
    band_price_map = {row.student_band_id: f"{((row.price_cents or 0) / 100):.2f}" for row in existing_band_prices}
    if not band_price_map:
        band_price_map = {band.id: f"{((plan.price_cents or 0) / 100):.2f}" for band in student_bands}

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        billing = (request.form.get('billing_period') or 'monthly').strip() or 'monthly'
        bundle_family = (request.form.get('bundle_family') or 'academic').strip() or 'academic'
        selected_module_codes = request.form.getlist('module_codes')
        form_data = {
            'name': name,
            'billing_period': billing,
            'bundle_family': bundle_family,
        }

        if not name:
            flash('Plan name is required.', 'error')
            return render_template('platform/plans_form.html', mode='edit', **_plan_form_context(plan=plan, form_data=form_data, student_bands=student_bands, modules=modules, selected_module_codes=selected_module_codes, band_price_map=band_price_map))

        duplicate = Plan.query.filter(Plan.name == name, Plan.id != plan.id).first()
        if duplicate is not None:
            flash('A plan with that name already exists.', 'warning')
            return render_template('platform/plans_form.html', mode='edit', **_plan_form_context(plan=plan, form_data=form_data, student_bands=student_bands, modules=modules, selected_module_codes=selected_module_codes, band_price_map=band_price_map))
        if not selected_module_codes:
            flash('Select at least one module for the plan.', 'error')
            return render_template('platform/plans_form.html', mode='edit', **_plan_form_context(plan=plan, form_data=form_data, student_bands=student_bands, modules=modules, selected_module_codes=selected_module_codes, band_price_map=band_price_map))

        try:
            band_price_map_raw, first_band_price = _parse_band_prices(student_bands)
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('platform/plans_form.html', mode='edit', **_plan_form_context(plan=plan, form_data=form_data, student_bands=student_bands, modules=modules, selected_module_codes=selected_module_codes, band_price_map=band_price_map))

        old_values = {
            'name': plan.name,
            'price_cents': plan.price_cents,
            'billing_period': plan.billing_period,
            'bundle_family': plan.bundle_family,
        }
        plan.name = name
        plan.price_cents = first_band_price
        plan.billing_period = billing
        plan.bundle_family = bundle_family
        plan.pricing_model = 'student_band'
        plan.features = pricing_features_snapshot(bundle_family, selected_module_codes, band_price_map_raw, student_bands)
        _save_plan_pricing(db, plan, selected_module_codes, module_lookup, student_bands, band_price_map_raw)
        db.session.commit()
        audit_log(
            actor_user_id=session.get('platform_user_id'),
            action='plan_updated',
            target_table='plans',
            target_id=plan.id,
            changes={
                **old_values,
                'new_name': plan.name,
                'new_price_cents': plan.price_cents,
                'new_billing_period': plan.billing_period,
                'new_bundle_family': plan.bundle_family,
                'module_codes': selected_module_codes,
            },
        )
        flash('Plan updated', 'success')
        return redirect(url_for('platform.list_plans'))

    return render_template(
        'platform/plans_form.html',
        mode='edit',
        **_plan_form_context(
            plan=plan,
            student_bands=student_bands,
            modules=modules,
            selected_module_codes=selected_module_codes,
            band_price_map=band_price_map,
        ),
    )


def register_routes(bp):
    bp.add_url_rule('/plans', endpoint='list_plans', view_func=list_plans)
    bp.add_url_rule('/plans/create', endpoint='create_plan', view_func=create_plan, methods=['GET', 'POST'])
    bp.add_url_rule('/plans/<int:plan_id>/edit', endpoint='edit_plan', view_func=edit_plan, methods=['GET', 'POST'])
