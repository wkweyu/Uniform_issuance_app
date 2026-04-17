"""Payroll blueprint routes — Kenyan-compliant payroll management."""

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, jsonify,
)
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.payroll.services import PayrollService, PayrollError
from decimal import Decimal, InvalidOperation
from datetime import datetime

payroll_bp = Blueprint('payroll', __name__, url_prefix='/payroll')


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _dec(value, field, default=None):
    if value in (None, ''):
        if default is not None:
            return Decimal(str(default))
        raise ValueError(f"{field} is required.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid number.")


def _service():
    conn = get_db_connection()
    return conn, PayrollService(conn)


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

@payroll_bp.route('/dashboard')
@login_required
def dashboard():
    conn, svc = _service()
    try:
        stats = svc.get_dashboard_stats()
        runs = svc.get_payroll_runs()
        return render_template('payroll/dashboard.html', stats=stats, runs=runs)
    finally:
        conn.close()


# ------------------------------------------------------------------
# Employees
# ------------------------------------------------------------------

@payroll_bp.route('/employees')
@login_required
def employees():
    conn, svc = _service()
    try:
        emps = svc.get_employees(active_only=False)
        return render_template('payroll/employees.html', employees=emps)
    finally:
        conn.close()


@payroll_bp.route('/employees/new', methods=['GET', 'POST'])
@admin_required
def employee_new():
    conn, svc = _service()
    try:
        if request.method == 'POST':
            try:
                emp_id = svc.create_employee(
                    staff_id=request.form['staff_id'],
                    basic_salary=_dec(request.form.get('basic_salary'), 'Basic salary'),
                    salary_source=request.form.get('salary_source', 'school'),
                    govt_salary_pct=_dec(request.form.get('govt_salary_pct'), 'Govt %', default=0),
                    kra_pin=request.form.get('kra_pin', '').strip() or None,
                    nhif_no=request.form.get('nhif_no', '').strip() or None,
                    nssf_no=request.form.get('nssf_no', '').strip() or None,
                    bank_name=request.form.get('bank_name', '').strip() or None,
                    bank_branch=request.form.get('bank_branch', '').strip() or None,
                    bank_account=request.form.get('bank_account', '').strip() or None,
                    effective_from=request.form.get('effective_from') or None,
                )
                flash('Employee added to payroll.', 'success')
                return redirect(url_for('payroll.employee_detail', employee_id=emp_id))
            except (PayrollError, ValueError) as e:
                flash(str(e), 'error')

        available_staff = svc.get_staff_not_on_payroll()
        return render_template('payroll/employee_form.html',
                               employee=None, staff_list=available_staff)
    finally:
        conn.close()


@payroll_bp.route('/employees/<int:employee_id>')
@login_required
def employee_detail(employee_id):
    conn, svc = _service()
    try:
        emp = svc.get_employee(employee_id)
        return render_template('payroll/employee_detail.html', employee=emp)
    finally:
        conn.close()


@payroll_bp.route('/employees/<int:employee_id>/edit', methods=['GET', 'POST'])
@admin_required
def employee_edit(employee_id):
    conn, svc = _service()
    try:
        if request.method == 'POST':
            try:
                svc.update_employee(
                    employee_id,
                    basic_salary=_dec(request.form.get('basic_salary'), 'Basic salary'),
                    salary_source=request.form.get('salary_source', 'school'),
                    govt_salary_pct=_dec(request.form.get('govt_salary_pct'), 'Govt %', default=0),
                    kra_pin=request.form.get('kra_pin', '').strip() or None,
                    nhif_no=request.form.get('nhif_no', '').strip() or None,
                    nssf_no=request.form.get('nssf_no', '').strip() or None,
                    bank_name=request.form.get('bank_name', '').strip() or None,
                    bank_branch=request.form.get('bank_branch', '').strip() or None,
                    bank_account=request.form.get('bank_account', '').strip() or None,
                    effective_from=request.form.get('effective_from') or None,
                )
                flash('Employee updated.', 'success')
                return redirect(url_for('payroll.employee_detail', employee_id=employee_id))
            except (PayrollError, ValueError) as e:
                flash(str(e), 'error')

        emp = svc.get_employee(employee_id)
        return render_template('payroll/employee_form.html', employee=emp, staff_list=[])
    finally:
        conn.close()


@payroll_bp.route('/employees/<int:employee_id>/components', methods=['GET', 'POST'])
@admin_required
def employee_components(employee_id):
    conn, svc = _service()
    try:
        if request.method == 'POST':
            try:
                components = []
                comp_ids = request.form.getlist('component_id[]')
                amounts = request.form.getlist('amount[]')
                is_pcts = request.form.getlist('is_percent[]')
                modes = request.form.getlist('mode[]')
                for i, cid in enumerate(comp_ids):
                    components.append({
                        'component_id': int(cid),
                        'amount': Decimal(amounts[i]) if amounts[i] else Decimal('0'),
                        'is_percent': is_pcts[i] == '1' if i < len(is_pcts) else False,
                        'mode': modes[i] if i < len(modes) else 'auto',
                    })
                svc.set_employee_components(employee_id, components)
                flash('Components updated.', 'success')
                return redirect(url_for('payroll.employee_detail', employee_id=employee_id))
            except (PayrollError, ValueError) as e:
                flash(str(e), 'error')

        emp = svc.get_employee(employee_id)
        all_components = svc.get_components()
        return render_template('payroll/employee_components.html',
                               employee=emp, all_components=all_components)
    finally:
        conn.close()


@payroll_bp.route('/employees/<int:employee_id>/history')
@login_required
def employee_history(employee_id):
    conn, svc = _service()
    try:
        emp = svc._assert_employee_belongs(employee_id)
        svc.cursor.execute(
            "SELECT * FROM payroll_employee_history WHERE employee_id = %s ORDER BY changed_at DESC",
            (employee_id,),
        )
        history = svc.cursor.fetchall()
        return render_template('payroll/employee_history.html', employee=emp, history=history)
    finally:
        conn.close()


@payroll_bp.route('/employees/<int:employee_id>/payslips')
@login_required
def employee_payslips(employee_id):
    conn, svc = _service()
    try:
        emp = svc._assert_employee_belongs(employee_id)
        svc.cursor.execute(
            "SELECT pl.*, pr.pay_period, pr.status "
            "FROM payroll_lines pl "
            "JOIN payroll_runs pr ON pl.run_id = pr.id "
            "WHERE pl.employee_id = %s AND pr.school_id = %s "
            "ORDER BY pr.pay_period DESC",
            (employee_id, svc.school_id),
        )
        payslips = svc.cursor.fetchall()
        return render_template('payroll/employee_payslips.html', employee=emp, payslips=payslips)
    finally:
        conn.close()


# ------------------------------------------------------------------
# Adjustments
# ------------------------------------------------------------------

@payroll_bp.route('/adjustments')
@login_required
def adjustments():
    conn, svc = _service()
    try:
        pending = request.args.get('pending') == '1'
        adjs = svc.get_adjustments(pending_only=pending)
        return render_template('payroll/adjustments.html', adjustments=adjs, pending=pending)
    finally:
        conn.close()


@payroll_bp.route('/adjustments/new', methods=['GET', 'POST'])
@admin_required
def adjustment_new():
    conn, svc = _service()
    try:
        if request.method == 'POST':
            try:
                svc.create_adjustment(
                    employee_id=int(request.form['employee_id']),
                    adj_type=request.form['type'],
                    name=request.form['name'].strip(),
                    amount=_dec(request.form.get('amount'), 'Amount'),
                    is_taxable=request.form.get('is_taxable') == '1',
                    is_recurring=request.form.get('is_recurring') == '1',
                    recur_until=request.form.get('recur_until') or None,
                    notes=request.form.get('notes', '').strip() or None,
                )
                flash('Adjustment created.', 'success')
                return redirect(url_for('payroll.adjustments'))
            except (PayrollError, ValueError) as e:
                flash(str(e), 'error')

        employees = svc.get_employees()
        return render_template('payroll/adjustment_form.html', employees=employees)
    finally:
        conn.close()


@payroll_bp.route('/adjustments/<int:adj_id>/delete', methods=['POST'])
@admin_required
def adjustment_delete(adj_id):
    conn, svc = _service()
    try:
        svc.delete_adjustment(adj_id)
        flash('Adjustment deleted.', 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.adjustments'))


# ------------------------------------------------------------------
# Payroll Runs
# ------------------------------------------------------------------

@payroll_bp.route('/runs')
@login_required
def runs():
    conn, svc = _service()
    try:
        all_runs = svc.get_payroll_runs()
        return render_template('payroll/runs.html', runs=all_runs)
    finally:
        conn.close()


@payroll_bp.route('/runs/new', methods=['POST'])
@admin_required
def run_create():
    conn, svc = _service()
    try:
        pay_period = request.form['pay_period']
        run_id = svc.create_payroll_run(pay_period)
        flash(f'Payroll run {pay_period} created as draft.', 'success')
        return redirect(url_for('payroll.run_detail', run_id=run_id))
    except PayrollError as e:
        flash(str(e), 'error')
        return redirect(url_for('payroll.runs'))
    finally:
        conn.close()


@payroll_bp.route('/runs/<int:run_id>')
@login_required
def run_detail(run_id):
    conn, svc = _service()
    try:
        run = svc.get_payroll_run(run_id)
        return render_template('payroll/run_detail.html', run=run)
    finally:
        conn.close()


@payroll_bp.route('/runs/<int:run_id>/generate', methods=['POST'])
@admin_required
def run_generate(run_id):
    conn, svc = _service()
    try:
        result = svc.generate_payroll(run_id)
        flash(f"Payroll generated for {result['employee_count']} employees. "
              f"Total gross: {result['total_gross']}, Net: {result['total_net']}", 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.run_detail', run_id=run_id))


@payroll_bp.route('/runs/<int:run_id>/approve', methods=['POST'])
@admin_required
def run_approve(run_id):
    conn, svc = _service()
    try:
        svc.approve_payroll(run_id)
        flash('Payroll approved.', 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.run_detail', run_id=run_id))


@payroll_bp.route('/runs/<int:run_id>/post', methods=['POST'])
@admin_required
def run_post(run_id):
    conn, svc = _service()
    try:
        txn_id = svc.post_to_gl(run_id)
        flash(f'Payroll posted to GL (transaction #{txn_id}).', 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.run_detail', run_id=run_id))


@payroll_bp.route('/runs/<int:run_id>/reverse', methods=['POST'])
@admin_required
def run_reverse(run_id):
    conn, svc = _service()
    try:
        svc.reverse_payroll(run_id)
        flash('Payroll reversed.', 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.run_detail', run_id=run_id))


@payroll_bp.route('/runs/<int:run_id>/payslip/<int:employee_id>')
@login_required
def payslip(run_id, employee_id):
    conn, svc = _service()
    try:
        slip = svc.get_payslip(run_id, employee_id)
        run = svc._assert_run_belongs(run_id)
        return render_template('payroll/payslip.html', slip=slip, run=run)
    finally:
        conn.close()


# ------------------------------------------------------------------
# Reports
# ------------------------------------------------------------------

@payroll_bp.route('/reports/statutory/<int:run_id>')
@login_required
def report_statutory(run_id):
    conn, svc = _service()
    try:
        run = svc._assert_run_belongs(run_id)
        data = svc.get_statutory_report(run_id)
        return render_template('payroll/report_statutory.html', run=run, data=data)
    finally:
        conn.close()


@payroll_bp.route('/reports/government/<int:run_id>')
@login_required
def report_government(run_id):
    conn, svc = _service()
    try:
        run = svc._assert_run_belongs(run_id)
        data = svc.get_government_payroll_report(run_id)
        return render_template('payroll/report_government.html', run=run, data=data)
    finally:
        conn.close()


@payroll_bp.route('/reports/p9/<int:employee_id>')
@login_required
def report_p9(employee_id):
    conn, svc = _service()
    try:
        emp = svc.get_employee(employee_id)
        year = int(request.args.get('year', datetime.now().year))
        data = svc.get_p9_data(employee_id, year)
        return render_template('payroll/report_p9.html', employee=emp, data=data, year=year)
    finally:
        conn.close()


@payroll_bp.route('/reports/reconciliation/<int:run_id>')
@login_required
def report_reconciliation(run_id):
    conn, svc = _service()
    try:
        recon = svc.get_payroll_vs_gl_reconciliation(run_id)
        return render_template('payroll/report_reconciliation.html', recon=recon)
    finally:
        conn.close()


@payroll_bp.route('/reports/audit/<int:run_id>')
@login_required
def report_audit(run_id):
    conn, svc = _service()
    try:
        run = svc._assert_run_belongs(run_id)
        data = svc.get_payroll_audit_report(run_id)
        return render_template('payroll/report_audit.html', run=run, data=data)
    finally:
        conn.close()


# ------------------------------------------------------------------
# Settings (Statutory Rates & GL Mapping)
# ------------------------------------------------------------------

@payroll_bp.route('/settings')
@admin_required
def settings():
    conn, svc = _service()
    try:
        rates = svc.get_statutory_rates()
        gl_mappings = svc.get_gl_mappings()
        components = svc.get_components(active_only=False)
        statutory_formulas = svc.get_statutory_formulas()
        return render_template('payroll/settings.html', rates=rates, gl_mappings=gl_mappings,
                               components=components, statutory_formulas=statutory_formulas)
    finally:
        conn.close()


# ------------------------------------------------------------------
# Salary Components CRUD
# ------------------------------------------------------------------

@payroll_bp.route('/components/add', methods=['POST'])
@admin_required
def component_add():
    conn, svc = _service()
    try:
        svc.add_component(
            code=request.form['code'],
            name=request.form['name'],
            comp_type=request.form['type'],
            calculation_type=request.form.get('calculation_type', 'fixed'),
            is_taxable='is_taxable' in request.form,
            sort_order=int(request.form.get('sort_order', 50)),
            formula_expression=request.form.get('formula_expression', '').strip() or None,
        )
        flash('Component added.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.settings') + '#components')


@payroll_bp.route('/components/<int:component_id>/edit', methods=['POST'])
@admin_required
def component_edit(component_id):
    conn, svc = _service()
    try:
        svc.update_component(
            component_id=component_id,
            name=request.form['name'],
            comp_type=request.form['type'],
            calculation_type=request.form.get('calculation_type', 'fixed'),
            is_taxable='is_taxable' in request.form,
            sort_order=int(request.form.get('sort_order', 50)),
            formula_expression=request.form.get('formula_expression', '').strip() or None,
        )
        flash('Component updated.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.settings') + '#components')


@payroll_bp.route('/components/<int:component_id>/toggle', methods=['POST'])
@admin_required
def component_toggle(component_id):
    conn, svc = _service()
    try:
        new_state = svc.toggle_component(component_id)
        flash(f'Component {"activated" if new_state else "deactivated"}.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.settings') + '#components')


@payroll_bp.route('/components/<int:component_id>/delete', methods=['POST'])
@admin_required
def component_delete(component_id):
    conn, svc = _service()
    try:
        svc.delete_component(component_id)
        flash('Component deleted.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.settings') + '#components')


@payroll_bp.route('/settings/rates', methods=['POST'])
@admin_required
def settings_rates():
    conn, svc = _service()
    try:
        rate_type = request.form['rate_type']
        bands = []
        band_froms = request.form.getlist('band_from[]')
        band_tos = request.form.getlist('band_to[]')
        rate_vals = request.form.getlist('rate[]')
        fixed_amounts = request.form.getlist('fixed_amount[]')
        eff_froms = request.form.getlist('effective_from[]')
        eff_tos = request.form.getlist('effective_to[]')
        for i in range(len(band_froms)):
            bands.append({
                'band_from': band_froms[i],
                'band_to': band_tos[i],
                'rate': rate_vals[i],
                'fixed_amount': fixed_amounts[i] if i < len(fixed_amounts) else '0',
                'effective_from': eff_froms[i] if i < len(eff_froms) else '2025-01-01',
                'effective_to': eff_tos[i] if i < len(eff_tos) else None,
            })
        svc.update_statutory_rates(rate_type, bands)
        flash(f'{rate_type} rates updated.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.settings'))


@payroll_bp.route('/settings/gl-mapping', methods=['POST'])
@admin_required
def settings_gl_mapping():
    conn, svc = _service()
    try:
        mapping_key = request.form['mapping_key']
        account_id = int(request.form['account_id'])
        svc.update_gl_mapping(mapping_key, account_id)
        flash('GL mapping updated.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.settings'))


@payroll_bp.route('/settings/statutory-formula/<int:formula_id>/edit', methods=['POST'])
@admin_required
def settings_statutory_formula_edit(formula_id):
    conn, svc = _service()
    try:
        svc.update_statutory_formula(
            formula_id=formula_id,
            label=request.form['label'],
            computation=request.form['computation'],
            flat_rate_expr=request.form.get('flat_rate_expr', '').strip() or None,
            input_variable=request.form.get('input_variable', 'gross'),
            employer_match='employer_match' in request.form,
            employer_expr=request.form.get('employer_expr', '').strip() or None,
            pre_tax_deductions=request.form.get('pre_tax_deductions', '').strip() or None,
            pension_cap=request.form.get('pension_cap') or None,
            mortgage_cap=request.form.get('mortgage_cap') or None,
            personal_relief=request.form.get('personal_relief') or None,
        )
        flash('Statutory formula updated.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.settings') + '#statutory-formulas')


# ==================================================================
# PHASE B: Voteheads & Funds
# ==================================================================

@payroll_bp.route('/voteheads')
@admin_required
def voteheads():
    conn, svc = _service()
    try:
        items = svc.get_voteheads()
        return render_template('payroll/voteheads.html', voteheads=items)
    finally:
        conn.close()


@payroll_bp.route('/voteheads/new', methods=['POST'])
@admin_required
def votehead_create():
    conn, svc = _service()
    try:
        svc.create_votehead(
            code=request.form['code'].strip().upper(),
            name=request.form['name'].strip(),
            category=request.form.get('category', 'other'),
        )
        flash('Votehead created.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.voteheads'))


@payroll_bp.route('/funds')
@admin_required
def funds():
    conn, svc = _service()
    try:
        items = svc.get_funds()
        return render_template('payroll/funds.html', funds=items)
    finally:
        conn.close()


@payroll_bp.route('/funds/new', methods=['POST'])
@admin_required
def fund_create():
    conn, svc = _service()
    try:
        svc.create_fund(
            code=request.form['code'].strip().upper(),
            name=request.form['name'].strip(),
            fund_type=request.form.get('fund_type', 'general'),
        )
        flash('Fund created.', 'success')
    except (PayrollError, ValueError) as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.funds'))


@payroll_bp.route('/runs/<int:run_id>/voteheads', methods=['GET', 'POST'])
@admin_required
def run_voteheads(run_id):
    conn, svc = _service()
    try:
        if request.method == 'POST':
            try:
                allocations = []
                line_ids = request.form.getlist('line_id[]')
                votehead_ids = request.form.getlist('votehead_id[]')
                fund_ids = request.form.getlist('fund_id[]')
                amounts = request.form.getlist('alloc_amount[]')
                for i in range(len(line_ids)):
                    allocations.append({
                        'payroll_line_id': int(line_ids[i]),
                        'votehead_id': int(votehead_ids[i]),
                        'fund_id': int(fund_ids[i]) if fund_ids[i] else None,
                        'amount': Decimal(amounts[i]),
                    })
                svc.set_votehead_allocations(run_id, allocations)
                flash('Votehead allocations saved.', 'success')
                return redirect(url_for('payroll.run_detail', run_id=run_id))
            except (PayrollError, ValueError) as e:
                flash(str(e), 'error')

        run = svc.get_payroll_run(run_id)
        existing = svc.get_votehead_allocations(run_id)
        all_voteheads = svc.get_voteheads()
        all_funds = svc.get_funds()
        return render_template('payroll/votehead_allocation.html',
                               run=run, allocations=existing,
                               voteheads=all_voteheads, funds=all_funds)
    finally:
        conn.close()


@payroll_bp.route('/reports/voteheads/<int:run_id>')
@login_required
def report_voteheads(run_id):
    conn, svc = _service()
    try:
        run = svc._assert_run_belongs(run_id)
        data = svc.get_votehead_report(run_id)
        return render_template('payroll/report_voteheads.html', run=run, data=data)
    finally:
        conn.close()


@payroll_bp.route('/reports/fund/<int:run_id>')
@login_required
def report_fund(run_id):
    conn, svc = _service()
    try:
        run = svc._assert_run_belongs(run_id)
        data = svc.get_fund_payroll_report(run_id)
        return render_template('payroll/report_fund.html', run=run, data=data)
    finally:
        conn.close()


@payroll_bp.route('/reports/fund-annual')
@login_required
def report_fund_annual():
    conn, svc = _service()
    try:
        year = int(request.args.get('year', datetime.now().year))
        data = svc.get_payroll_by_fund_annual(year)
        budget_vs_actual = svc.get_budget_vs_actual(year)
        return render_template('payroll/report_fund_annual.html',
                               year=year, data=data, budget_vs_actual=budget_vs_actual)
    finally:
        conn.close()


# ==================================================================
# PHASE B: Payment Batching
# ==================================================================

@payroll_bp.route('/runs/<int:run_id>/payments')
@login_required
def run_payments(run_id):
    conn, svc = _service()
    try:
        run = svc._assert_run_belongs(run_id)
        grouped = svc.get_payment_advice_grouped(run_id)
        return render_template('payroll/payment_advice.html', run=run, grouped=grouped)
    finally:
        conn.close()


@payroll_bp.route('/runs/<int:run_id>/generate-payments', methods=['POST'])
@admin_required
def run_generate_payments(run_id):
    conn, svc = _service()
    try:
        batch_id = svc.generate_payment_advice(run_id)
        flash(f'Payment advice generated (Batch: {batch_id}).', 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.run_payments', run_id=run_id))


@payroll_bp.route('/runs/<int:run_id>/mark-batch-paid', methods=['POST'])
@admin_required
def run_mark_batch_paid(run_id):
    conn, svc = _service()
    try:
        batch_id = request.form['batch_id']
        payment_ref = request.form.get('payment_ref', '').strip() or None
        payment_date = request.form.get('payment_date') or None
        count = svc.mark_batch_paid(batch_id, payment_ref, payment_date)
        flash(f'{count} payments marked as paid.', 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.run_payments', run_id=run_id))


@payroll_bp.route('/runs/<int:run_id>/delete-payments', methods=['POST'])
@admin_required
def run_delete_payments(run_id):
    conn, svc = _service()
    try:
        count = svc.delete_payment_batch(run_id)
        flash(f'{count} pending payments deleted.', 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.run_payments', run_id=run_id))


# ==================================================================
# PHASE B: Bulk Employee Operations
# ==================================================================

@payroll_bp.route('/employees/bulk-edit', methods=['GET', 'POST'])
@admin_required
def employees_bulk_edit():
    conn, svc = _service()
    try:
        if request.method == 'POST':
            try:
                changes = []
                emp_ids = request.form.getlist('employee_id[]')
                salaries = request.form.getlist('new_salary[]')
                eff_dates = request.form.getlist('effective_from[]')
                for i, eid in enumerate(emp_ids):
                    sal = salaries[i].strip() if i < len(salaries) else ''
                    if sal:
                        changes.append({
                            'employee_id': int(eid),
                            'basic_salary': Decimal(sal),
                            'effective_from': eff_dates[i] if i < len(eff_dates) and eff_dates[i] else datetime.now().strftime('%Y-%m-%d'),
                        })
                count = svc.bulk_update_employees(changes)
                flash(f'{count} employees updated.', 'success')
                return redirect(url_for('payroll.employees'))
            except (PayrollError, ValueError) as e:
                flash(str(e), 'error')

        emps = svc.get_employees(active_only=True)
        return render_template('payroll/bulk_edit.html', employees=emps)
    finally:
        conn.close()


@payroll_bp.route('/employees/import', methods=['GET', 'POST'])
@admin_required
def employees_import():
    conn, svc = _service()
    try:
        if request.method == 'POST':
            import csv
            import io

            file = request.files.get('csv_file')
            if not file:
                flash('No file selected.', 'error')
                return redirect(url_for('payroll.employees_import'))

            stream = io.StringIO(file.stream.read().decode('utf-8'))
            reader = csv.DictReader(stream)
            rows = list(reader)
            result = svc.import_employees_from_csv(rows)
            flash(f"Import complete: {result['created']} created, {result['skipped']} skipped.", 'success')
            if result['errors']:
                for err in result['errors'][:10]:
                    flash(err, 'warning')
            return redirect(url_for('payroll.employees'))

        return render_template('payroll/employee_import.html')
    finally:
        conn.close()


# ==================================================================
# PHASE B: Enhanced post_to_gl with votehead support
# ==================================================================

@payroll_bp.route('/runs/<int:run_id>/post-with-voteheads', methods=['POST'])
@admin_required
def run_post_with_voteheads(run_id):
    conn, svc = _service()
    try:
        txn_id = svc.post_to_gl_with_voteheads(run_id)
        flash(f'Payroll posted to GL with votehead allocations (transaction #{txn_id}).', 'success')
    except PayrollError as e:
        flash(str(e), 'error')
    finally:
        conn.close()
    return redirect(url_for('payroll.run_detail', run_id=run_id))
