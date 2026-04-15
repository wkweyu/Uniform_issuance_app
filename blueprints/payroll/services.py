"""
Kenyan-compliant Payroll Service.

Handles employee payroll profiles, payroll run lifecycle (draft → generated →
approved → posted → reversed), statutory deduction computation, GL posting,
adjustments, and reporting.  All data is scoped by school_id.
"""

import json
import logging
import pymysql
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from flask import request, session

from core.tenancy import require_current_school_id
from core.tax import (
    compute_housing_levy,
    compute_nssf_separate,
    compute_paye,
    compute_shif,
    compute_taxable_income,
)

ZERO = Decimal('0.00')
logger = logging.getLogger(__name__)


class PayrollError(Exception):
    """Domain error raised by PayrollService."""


class PayrollService:
    """Tenant-scoped payroll service using raw PyMySQL."""

    def __init__(self, connection, school_id=None):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id or require_current_school_id()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _audit(self, entity_type: str, entity_id: int, action: str,
               old_values: Any = None, new_values: Any = None):
        """Append an immutable audit log entry."""
        try:
            performed_by = session.get('userNo', 0)
            ip = request.remote_addr if request else None
        except RuntimeError:
            performed_by = 0
            ip = None
        self.cursor.execute(
            "INSERT INTO payroll_audit_logs "
            "(school_id, entity_type, entity_id, action, old_values, new_values, performed_by, ip_address) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (self.school_id, entity_type, entity_id, action,
             json.dumps(old_values, default=str) if old_values else None,
             json.dumps(new_values, default=str) if new_values else None,
             performed_by, ip),
        )

    def _assert_employee_belongs(self, employee_id: int) -> dict:
        self.cursor.execute(
            "SELECT * FROM payroll_employees WHERE id = %s AND school_id = %s",
            (employee_id, self.school_id),
        )
        row = self.cursor.fetchone()
        if not row:
            raise PayrollError("Employee not found for this school.")
        return row

    def _assert_run_belongs(self, run_id: int) -> dict:
        self.cursor.execute(
            "SELECT * FROM payroll_runs WHERE id = %s AND school_id = %s",
            (run_id, self.school_id),
        )
        row = self.cursor.fetchone()
        if not row:
            raise PayrollError("Payroll run not found for this school.")
        return row

    def _ensure_school_rates(self):
        """Copy template rates (school_id=0) to this school if not present."""
        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM payroll_statutory_rates WHERE school_id = %s",
            (self.school_id,),
        )
        if self.cursor.fetchone()['cnt'] == 0:
            self.cursor.execute(
                "INSERT INTO payroll_statutory_rates "
                "(school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from, effective_to) "
                "SELECT %s, rate_type, band_from, band_to, rate, fixed_amount, effective_from, effective_to "
                "FROM payroll_statutory_rates WHERE school_id = 0",
                (self.school_id,),
            )
            self.connection.commit()

    def _ensure_school_components(self):
        """Seed default payroll components for this school if none exist."""
        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM payroll_components WHERE school_id = %s",
            (self.school_id,),
        )
        if self.cursor.fetchone()['cnt'] > 0:
            return

        defaults = [
            # Earnings
            ('Basic Salary',           'BASIC',        'earning',   'fixed',   1, 0, 1),
            ('House Allowance',        'HOUSE_ALLOW',  'earning',   'fixed',   1, 0, 2),
            ('Transport Allowance',    'TRANSPORT',    'earning',   'fixed',   0, 0, 3),
            ('Responsibility Allow.',  'RESPONSIBILITY','earning',  'fixed',   0, 0, 4),
            ('Other Allowances',       'OTHER_ALLOW',  'earning',   'fixed',   0, 0, 5),
            # Statutory deductions
            ('PAYE',                   'PAYE',         'statutory', 'formula', 0, 1, 10),
            ('SHIF',                   'SHIF',         'statutory', 'formula', 0, 1, 11),
            ('NSSF',                   'NSSF',         'statutory', 'formula', 0, 1, 12),
            ('Housing Levy',           'HOUSING_LEVY', 'statutory', 'formula', 0, 1, 13),
            # Voluntary deductions
            ('Salary Advance',         'ADVANCE',      'deduction', 'manual',  0, 0, 20),
            ('Loan Repayment',         'LOAN',         'deduction', 'manual',  0, 0, 21),
            ('Sacco Contribution',     'SACCO',        'deduction', 'manual',  0, 0, 22),
            ('Other Deductions',       'OTHER_DED',    'deduction', 'manual',  0, 0, 23),
        ]
        for name, code, ctype, calc_type, is_taxable, is_statutory, sort_order in defaults:
            self.cursor.execute(
                "INSERT INTO payroll_components "
                "(school_id, name, code, type, calculation_type, is_taxable, is_statutory, sort_order) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (self.school_id, name, code, ctype, calc_type, is_taxable, is_statutory, sort_order),
            )
        self.connection.commit()

    def _ensure_gl_mapping(self):
        """Create default GL accounts and mapping for this school if missing."""
        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM payroll_gl_mapping WHERE school_id = %s",
            (self.school_id,),
        )
        if self.cursor.fetchone()['cnt'] > 0:
            return

        # Define accounts to create / find
        account_defs = [
            ('5101', 'Basic Salary Expense',            'EXPENSE'),
            ('5102', 'Allowances Expense',              'EXPENSE'),
            ('5103', 'Employer NSSF Expense',           'EXPENSE'),
            ('5104', 'Employer Housing Levy Expense',   'EXPENSE'),
            ('2110', 'PAYE Payable',                    'LIABILITY'),
            ('2111', 'SHIF Payable',                    'LIABILITY'),
            ('2112', 'NSSF Payable',                    'LIABILITY'),
            ('2113', 'Housing Levy Payable',            'LIABILITY'),
            ('2114', 'Net Salary Payable',              'LIABILITY'),
            ('1400', 'Government Salary Receivable',    'ASSET'),
        ]

        account_ids = {}
        for code, name, acct_type in account_defs:
            # Check if account already exists for this school
            self.cursor.execute(
                "SELECT id FROM finance_accounts WHERE code = %s AND school_id = %s",
                (code, self.school_id),
            )
            row = self.cursor.fetchone()
            if row:
                account_ids[code] = row['id']
            else:
                self.cursor.execute(
                    "INSERT INTO finance_accounts (code, name, type, school_id) "
                    "VALUES (%s, %s, %s, %s)",
                    (code, name, acct_type, self.school_id),
                )
                account_ids[code] = self.cursor.lastrowid

        # Insert mapping
        mapping = {
            'salary_expense':           account_ids['5101'],
            'allowances_expense':       account_ids['5102'],
            'employer_nssf_expense':    account_ids['5103'],
            'employer_hl_expense':      account_ids['5104'],
            'paye_payable':             account_ids['2110'],
            'shif_payable':             account_ids['2111'],
            'nssf_payable':             account_ids['2112'],
            'housing_levy_payable':     account_ids['2113'],
            'net_pay_payable':          account_ids['2114'],
            'govt_receivable':          account_ids['1400'],
        }
        for key, acct_id in mapping.items():
            self.cursor.execute(
                "INSERT INTO payroll_gl_mapping (school_id, mapping_key, account_id) "
                "VALUES (%s, %s, %s)",
                (self.school_id, key, acct_id),
            )
        self.connection.commit()

    # ------------------------------------------------------------------
    # Statutory rates
    # ------------------------------------------------------------------

    def get_statutory_rates(self, rate_type: str = None) -> List[Dict]:
        self._ensure_school_rates()
        sql = "SELECT * FROM payroll_statutory_rates WHERE school_id = %s"
        params = [self.school_id]
        if rate_type:
            sql += " AND rate_type = %s"
            params.append(rate_type)
        sql += " ORDER BY rate_type, band_from"
        self.cursor.execute(sql, params)
        return self.cursor.fetchall()

    def update_statutory_rates(self, rate_type: str, bands: List[Dict]):
        self._ensure_school_rates()
        self.cursor.execute(
            "DELETE FROM payroll_statutory_rates WHERE school_id = %s AND rate_type = %s",
            (self.school_id, rate_type),
        )
        for b in bands:
            self.cursor.execute(
                "INSERT INTO payroll_statutory_rates "
                "(school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from, effective_to) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (self.school_id, rate_type,
                 b['band_from'], b['band_to'], b['rate'], b.get('fixed_amount', 0),
                 b['effective_from'], b.get('effective_to')),
            )
        self._audit('statutory_rates', 0, 'updated', new_values={'rate_type': rate_type, 'bands': bands})
        self.connection.commit()

    def _load_rates_for_computation(self):
        """Load statutory rates structured for the tax engine."""
        self._ensure_school_rates()
        self.cursor.execute(
            "SELECT * FROM payroll_statutory_rates WHERE school_id = %s "
            "AND (effective_to IS NULL OR effective_to >= CURDATE()) "
            "ORDER BY rate_type, band_from",
            (self.school_id,),
        )
        rows = self.cursor.fetchall()
        rates = {'paye': [], 'shif': [], 'nssf_employee': [], 'nssf_employer': [],
                 'housing_levy_employee': [], 'housing_levy_employer': [], 'personal_relief': ZERO}
        for r in rows:
            rt = r['rate_type']
            if rt == 'personal_relief':
                rates['personal_relief'] = Decimal(str(r['fixed_amount']))
            elif rt in rates:
                rates[rt].append({
                    'band_from': Decimal(str(r['band_from'])),
                    'band_to': Decimal(str(r['band_to'])),
                    'rate': Decimal(str(r['rate'])),
                })
        return rates

    # ------------------------------------------------------------------
    # GL Mapping
    # ------------------------------------------------------------------

    def get_gl_mappings(self) -> List[Dict]:
        self._ensure_gl_mapping()
        self.cursor.execute(
            "SELECT m.*, a.code AS account_code, a.name AS account_name "
            "FROM payroll_gl_mapping m "
            "JOIN finance_accounts a ON m.account_id = a.id "
            "WHERE m.school_id = %s ORDER BY m.mapping_key",
            (self.school_id,),
        )
        return self.cursor.fetchall()

    def update_gl_mapping(self, mapping_key: str, account_id: int):
        self._ensure_gl_mapping()
        self.cursor.execute(
            "UPDATE payroll_gl_mapping SET account_id = %s "
            "WHERE school_id = %s AND mapping_key = %s",
            (account_id, self.school_id, mapping_key),
        )
        self._audit('gl_mapping', 0, 'updated', new_values={'key': mapping_key, 'account_id': account_id})
        self.connection.commit()

    def _gl_map(self) -> Dict[str, int]:
        """Return {mapping_key: account_id} dict."""
        self._ensure_gl_mapping()
        self.cursor.execute(
            "SELECT mapping_key, account_id FROM payroll_gl_mapping WHERE school_id = %s",
            (self.school_id,),
        )
        return {r['mapping_key']: r['account_id'] for r in self.cursor.fetchall()}

    # ------------------------------------------------------------------
    # Components
    # ------------------------------------------------------------------

    def get_components(self, active_only: bool = True) -> List[Dict]:
        self._ensure_school_components()
        sql = "SELECT * FROM payroll_components WHERE school_id = %s"
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY sort_order"
        self.cursor.execute(sql, (self.school_id,))
        return self.cursor.fetchall()

    # ------------------------------------------------------------------
    # Employee Management
    # ------------------------------------------------------------------

    def get_employees(self, active_only: bool = True) -> List[Dict]:
        sql = ("SELECT pe.*, s.surname, s.firstname, s.initials, s.phone1, s.phone2 "
               "FROM payroll_employees pe "
               "LEFT JOIN staff s ON pe.staff_id = s.staffID "
               "WHERE pe.school_id = %s")
        if active_only:
            sql += " AND pe.is_active = 1"
        sql += " ORDER BY s.surname, s.firstname"
        self.cursor.execute(sql, (self.school_id,))
        return self.cursor.fetchall()

    def get_employee(self, employee_id: int) -> Dict:
        emp = self._assert_employee_belongs(employee_id)
        # Attach components
        self.cursor.execute(
            "SELECT pec.*, pc.name, pc.code, pc.type, pc.calculation_type, pc.is_statutory "
            "FROM payroll_employee_components pec "
            "JOIN payroll_components pc ON pec.component_id = pc.id "
            "WHERE pec.employee_id = %s ORDER BY pc.sort_order",
            (employee_id,),
        )
        emp['components'] = self.cursor.fetchall()
        # Attach pending adjustments
        self.cursor.execute(
            "SELECT * FROM payroll_adjustments "
            "WHERE employee_id = %s AND applied = 0 AND school_id = %s "
            "ORDER BY created_at DESC",
            (employee_id, self.school_id),
        )
        emp['pending_adjustments'] = self.cursor.fetchall()
        return emp

    def get_staff_not_on_payroll(self) -> List[Dict]:
        """Return staff records that don't have a payroll profile yet."""
        self.cursor.execute(
            "SELECT s.* FROM staff s "
            "LEFT JOIN payroll_employees pe ON s.staffID = pe.staff_id AND pe.school_id = %s "
            "WHERE pe.id IS NULL "
            "ORDER BY s.surname, s.firstname",
            (self.school_id,),
        )
        return self.cursor.fetchall()

    def create_employee(self, staff_id: str, basic_salary: Decimal, salary_source: str = 'school',
                        govt_salary_pct: Decimal = ZERO, kra_pin: str = None,
                        nhif_no: str = None, nssf_no: str = None,
                        bank_name: str = None, bank_branch: str = None, bank_account: str = None,
                        effective_from: str = None) -> int:
        if not effective_from:
            effective_from = date.today().isoformat()
        created_by = session.get('userNo', 0)
        try:
            self.cursor.execute(
                "INSERT INTO payroll_employees "
                "(school_id, staff_id, basic_salary, salary_source, govt_salary_pct, "
                " kra_pin, nhif_no, nssf_no, bank_name, bank_branch, bank_account, "
                " effective_from, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (self.school_id, staff_id, basic_salary, salary_source, govt_salary_pct,
                 kra_pin, nhif_no, nssf_no, bank_name, bank_branch, bank_account,
                 effective_from, created_by),
            )
            emp_id = self.cursor.lastrowid
            self._audit('payroll_employee', emp_id, 'created',
                        new_values={'staff_id': staff_id, 'basic_salary': str(basic_salary)})
            self.connection.commit()
            return emp_id
        except pymysql.IntegrityError:
            self.connection.rollback()
            raise PayrollError(f"Staff {staff_id} already has a payroll profile.")

    def update_employee(self, employee_id: int, **fields):
        emp = self._assert_employee_belongs(employee_id)
        trackable = ('basic_salary', 'salary_source', 'govt_salary_pct', 'kra_pin',
                     'nhif_no', 'nssf_no', 'bank_name', 'bank_branch', 'bank_account',
                     'is_active', 'effective_from')
        sets = []
        params = []
        changed_by = session.get('userNo', 0)
        for field in trackable:
            if field in fields and fields[field] is not None:
                old_val = str(emp.get(field, ''))
                new_val = str(fields[field])
                if old_val != new_val:
                    sets.append(f"{field} = %s")
                    params.append(fields[field])
                    # Record history for salary/source changes
                    if field in ('basic_salary', 'salary_source', 'govt_salary_pct'):
                        self.cursor.execute(
                            "INSERT INTO payroll_employee_history "
                            "(employee_id, field_changed, old_value, new_value, effective_from, changed_by) "
                            "VALUES (%s, %s, %s, %s, %s, %s)",
                            (employee_id, field, old_val, new_val,
                             fields.get('effective_from', date.today().isoformat()), changed_by),
                        )
        if not sets:
            return
        params.append(employee_id)
        self.cursor.execute(
            f"UPDATE payroll_employees SET {', '.join(sets)} WHERE id = %s", params
        )
        self._audit('payroll_employee', employee_id, 'edited',
                     old_values={k: str(emp.get(k)) for k in fields if k in trackable},
                     new_values={k: str(v) for k, v in fields.items() if k in trackable})
        self.connection.commit()

    def set_employee_components(self, employee_id: int, components: List[Dict]):
        """
        Bulk set components for an employee.
        components: [{'component_id': int, 'amount': Decimal, 'is_percent': bool, 'mode': str}, ...]
        """
        self._assert_employee_belongs(employee_id)
        self.cursor.execute(
            "DELETE FROM payroll_employee_components WHERE employee_id = %s",
            (employee_id,),
        )
        for c in components:
            self.cursor.execute(
                "INSERT INTO payroll_employee_components "
                "(employee_id, component_id, amount, is_percent, mode, is_active) "
                "VALUES (%s, %s, %s, %s, %s, 1)",
                (employee_id, c['component_id'], c.get('amount', 0),
                 1 if c.get('is_percent') else 0, c.get('mode', 'auto')),
            )
        self._audit('payroll_employee', employee_id, 'components_updated',
                     new_values={'count': len(components)})
        self.connection.commit()

    # ------------------------------------------------------------------
    # Adjustments
    # ------------------------------------------------------------------

    def get_adjustments(self, employee_id: int = None, run_id: int = None,
                        pending_only: bool = False) -> List[Dict]:
        sql = ("SELECT pa.*, pe.staff_id, s.surname, s.firstname "
               "FROM payroll_adjustments pa "
               "JOIN payroll_employees pe ON pa.employee_id = pe.id "
               "LEFT JOIN staff s ON pe.staff_id = s.staffID "
               "WHERE pa.school_id = %s")
        params: list = [self.school_id]
        if employee_id:
            sql += " AND pa.employee_id = %s"
            params.append(employee_id)
        if run_id:
            sql += " AND pa.run_id = %s"
            params.append(run_id)
        if pending_only:
            sql += " AND pa.applied = 0"
        sql += " ORDER BY pa.created_at DESC"
        self.cursor.execute(sql, params)
        return self.cursor.fetchall()

    def create_adjustment(self, employee_id: int, adj_type: str, name: str,
                          amount: Decimal, is_taxable: bool = False,
                          is_recurring: bool = False, recur_until: str = None,
                          notes: str = None) -> int:
        self._assert_employee_belongs(employee_id)
        created_by = session.get('userNo', 0)
        self.cursor.execute(
            "INSERT INTO payroll_adjustments "
            "(school_id, employee_id, type, name, amount, is_taxable, "
            " is_recurring, recur_until, created_by, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (self.school_id, employee_id, adj_type, name, amount, int(is_taxable),
             int(is_recurring), recur_until, created_by, notes),
        )
        adj_id = self.cursor.lastrowid
        self._audit('payroll_adjustment', adj_id, 'created',
                     new_values={'employee_id': employee_id, 'type': adj_type, 'amount': str(amount)})
        self.connection.commit()
        return adj_id

    def delete_adjustment(self, adjustment_id: int):
        self.cursor.execute(
            "SELECT * FROM payroll_adjustments WHERE id = %s AND school_id = %s",
            (adjustment_id, self.school_id),
        )
        adj = self.cursor.fetchone()
        if not adj:
            raise PayrollError("Adjustment not found.")
        if adj['applied']:
            raise PayrollError("Cannot delete an already-applied adjustment.")
        self.cursor.execute("DELETE FROM payroll_adjustments WHERE id = %s", (adjustment_id,))
        self._audit('payroll_adjustment', adjustment_id, 'deleted',
                     old_values={'name': adj['name'], 'amount': str(adj['amount'])})
        self.connection.commit()

    # ------------------------------------------------------------------
    # Payroll Run Lifecycle
    # ------------------------------------------------------------------

    def get_payroll_runs(self) -> List[Dict]:
        self.cursor.execute(
            "SELECT * FROM payroll_runs WHERE school_id = %s ORDER BY pay_period DESC",
            (self.school_id,),
        )
        return self.cursor.fetchall()

    def get_payroll_run(self, run_id: int) -> Dict:
        run = self._assert_run_belongs(run_id)
        self.cursor.execute(
            "SELECT pl.*, pe.staff_id, s.surname, s.firstname "
            "FROM payroll_lines pl "
            "JOIN payroll_employees pe ON pl.employee_id = pe.id "
            "LEFT JOIN staff s ON pe.staff_id = s.staffID "
            "WHERE pl.run_id = %s ORDER BY s.surname, s.firstname",
            (run_id,),
        )
        run['lines'] = self.cursor.fetchall()
        return run

    def create_payroll_run(self, pay_period: str) -> int:
        """Create a new draft payroll run for the given period (YYYY-MM)."""
        # Validate format
        try:
            datetime.strptime(pay_period, '%Y-%m')
        except ValueError:
            raise PayrollError("Invalid pay period format. Use YYYY-MM.")

        try:
            self.cursor.execute(
                "INSERT INTO payroll_runs (school_id, pay_period, status) VALUES (%s, %s, 'draft')",
                (self.school_id, pay_period),
            )
            run_id = self.cursor.lastrowid
            self._audit('payroll_run', run_id, 'created', new_values={'pay_period': pay_period})
            self.connection.commit()
            return run_id
        except pymysql.IntegrityError:
            self.connection.rollback()
            raise PayrollError(f"A payroll run for {pay_period} already exists.")

    def generate_payroll(self, run_id: int) -> Dict:
        """
        Generate payroll calculations for all active employees.
        This is the CORE computation method.
        """
        run = self._assert_run_belongs(run_id)
        if run['status'] not in ('draft', 'generated'):
            raise PayrollError(f"Cannot generate: run is '{run['status']}'. Must be draft or generated.")

        # Clear any previously generated lines for re-generation
        self.cursor.execute("DELETE FROM payroll_lines WHERE run_id = %s", (run_id,))
        # Reset previously applied adjustments for this run
        self.cursor.execute(
            "UPDATE payroll_adjustments SET applied = 0, run_id = NULL "
            "WHERE run_id = %s AND school_id = %s",
            (run_id, self.school_id),
        )

        rates = self._load_rates_for_computation()
        self._ensure_school_components()

        # Load employees
        employees = self.get_employees(active_only=True)
        if not employees:
            raise PayrollError("No active employees found.")

        # Load all employee components in one query
        emp_ids = [e['id'] for e in employees]
        placeholders = ','.join(['%s'] * len(emp_ids))
        self.cursor.execute(
            f"SELECT pec.*, pc.code, pc.type, pc.calculation_type, pc.is_taxable, pc.is_statutory "
            f"FROM payroll_employee_components pec "
            f"JOIN payroll_components pc ON pec.component_id = pc.id "
            f"WHERE pec.employee_id IN ({placeholders}) AND pec.is_active = 1 "
            f"ORDER BY pc.sort_order",
            emp_ids,
        )
        all_components = self.cursor.fetchall()
        comp_by_emp = {}
        for c in all_components:
            comp_by_emp.setdefault(c['employee_id'], []).append(c)

        # Load pending adjustments
        self.cursor.execute(
            "SELECT * FROM payroll_adjustments "
            "WHERE school_id = %s AND applied = 0 "
            "AND (is_recurring = 1 OR run_id IS NULL) "
            "AND (recur_until IS NULL OR recur_until >= CURDATE())",
            (self.school_id,),
        )
        all_adjustments = self.cursor.fetchall()
        adj_by_emp = {}
        for a in all_adjustments:
            adj_by_emp.setdefault(a['employee_id'], []).append(a)

        # Totals for run
        run_totals = {k: ZERO for k in (
            'total_gross', 'total_net', 'total_paye', 'total_shif',
            'total_nssf', 'total_housing_levy', 'total_employer_nssf',
            'total_employer_housing_levy')}

        generated_by = session.get('userNo', 0)

        for emp in employees:
            emp_id = emp['id']
            basic_salary = Decimal(str(emp['basic_salary']))
            components = comp_by_emp.get(emp_id, [])
            adjustments = adj_by_emp.get(emp_id, [])

            # --- Build breakdown ---
            breakdown = {'earnings': [], 'deductions': [], 'statutory': [], 'adjustments': []}

            # Sum earning components
            gross = ZERO
            for c in components:
                if c['type'] == 'earning':
                    if c['code'] == 'BASIC':
                        amt = basic_salary
                    elif c['is_percent']:
                        amt = Decimal(str(c['amount'])) * basic_salary / Decimal('100')
                    else:
                        amt = Decimal(str(c['amount']))
                    breakdown['earnings'].append({
                        'code': c['code'], 'name': c.get('name', c['code']),
                        'amount': str(amt), 'mode': c.get('mode', 'auto'),
                    })
                    gross += amt

            # Apply earning adjustments
            for adj in adjustments:
                if adj['type'] == 'earning':
                    amt = Decimal(str(adj['amount']))
                    gross += amt
                    breakdown['adjustments'].append({
                        'id': adj['id'], 'name': adj['name'], 'type': 'earning',
                        'amount': str(amt), 'is_taxable': bool(adj['is_taxable']),
                    })

            # --- Statutory deductions ---
            # Check for manual/override modes on statutory components
            stat_modes = {}
            for c in components:
                if c['is_statutory'] and c['code'] in ('PAYE', 'SHIF', 'NSSF', 'HOUSING_LEVY'):
                    stat_modes[c['code']] = {
                        'mode': c.get('mode', 'auto'),
                        'amount': Decimal(str(c['amount'])),
                    }

            # SHIF
            if stat_modes.get('SHIF', {}).get('mode') == 'manual':
                shif = stat_modes['SHIF']['amount']
            else:
                shif_rate = rates['shif'][0]['rate'] if rates['shif'] else Decimal('2.75')
                shif = compute_shif(gross, shif_rate)
                if stat_modes.get('SHIF', {}).get('mode') == 'override' and stat_modes['SHIF']['amount'] > ZERO:
                    shif = stat_modes['SHIF']['amount']

            # NSSF
            if stat_modes.get('NSSF', {}).get('mode') == 'manual':
                nssf_ee = stat_modes['NSSF']['amount']
                nssf_er = nssf_ee  # employer matches
            else:
                nssf_ee, nssf_er = compute_nssf_separate(
                    gross, rates['nssf_employee'], rates['nssf_employer'])
                if stat_modes.get('NSSF', {}).get('mode') == 'override' and stat_modes['NSSF']['amount'] > ZERO:
                    nssf_ee = stat_modes['NSSF']['amount']
                    nssf_er = nssf_ee

            # Housing Levy
            if stat_modes.get('HOUSING_LEVY', {}).get('mode') == 'manual':
                hl_ee = stat_modes['HOUSING_LEVY']['amount']
                hl_er = hl_ee
            else:
                hl_ee_rate = rates['housing_levy_employee'][0]['rate'] if rates['housing_levy_employee'] else Decimal('1.5')
                hl_er_rate = rates['housing_levy_employer'][0]['rate'] if rates['housing_levy_employer'] else Decimal('1.5')
                hl_ee, hl_er = compute_housing_levy(gross, hl_ee_rate, hl_er_rate)
                if stat_modes.get('HOUSING_LEVY', {}).get('mode') == 'override' and stat_modes['HOUSING_LEVY']['amount'] > ZERO:
                    hl_ee = stat_modes['HOUSING_LEVY']['amount']
                    hl_er = hl_ee

            # Taxable income
            taxable = compute_taxable_income(gross, shif, nssf_ee, hl_ee)

            # PAYE
            if stat_modes.get('PAYE', {}).get('mode') == 'manual':
                paye = stat_modes['PAYE']['amount']
            else:
                paye = compute_paye(taxable, rates['paye'], rates['personal_relief'])
                if stat_modes.get('PAYE', {}).get('mode') == 'override' and stat_modes['PAYE']['amount'] > ZERO:
                    paye = stat_modes['PAYE']['amount']

            breakdown['statutory'] = [
                {'code': 'PAYE', 'amount': str(paye), 'mode': stat_modes.get('PAYE', {}).get('mode', 'auto')},
                {'code': 'SHIF', 'amount': str(shif), 'mode': stat_modes.get('SHIF', {}).get('mode', 'auto')},
                {'code': 'NSSF', 'employee': str(nssf_ee), 'employer': str(nssf_er),
                 'mode': stat_modes.get('NSSF', {}).get('mode', 'auto')},
                {'code': 'HOUSING_LEVY', 'employee': str(hl_ee), 'employer': str(hl_er),
                 'mode': stat_modes.get('HOUSING_LEVY', {}).get('mode', 'auto')},
            ]

            # Voluntary deductions
            vol_deductions = ZERO
            for c in components:
                if c['type'] == 'deduction' and not c['is_statutory']:
                    amt = Decimal(str(c['amount']))
                    if amt > ZERO:
                        vol_deductions += amt
                        breakdown['deductions'].append({
                            'code': c['code'], 'name': c.get('name', c['code']),
                            'amount': str(amt), 'mode': c.get('mode', 'auto'),
                        })

            # Deduction adjustments
            for adj in adjustments:
                if adj['type'] == 'deduction':
                    amt = Decimal(str(adj['amount']))
                    vol_deductions += amt
                    breakdown['adjustments'].append({
                        'id': adj['id'], 'name': adj['name'], 'type': 'deduction',
                        'amount': str(amt),
                    })

            total_deductions = paye + shif + nssf_ee + hl_ee + vol_deductions
            net_pay = gross - total_deductions

            # Insert payroll line
            self.cursor.execute(
                "INSERT INTO payroll_lines "
                "(run_id, employee_id, salary_source, govt_salary_pct, basic_salary, "
                " gross_pay, taxable_income, paye, shif, nssf_employee, nssf_employer, "
                " housing_levy_employee, housing_levy_employer, total_deductions, net_pay, breakdown_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, emp_id, emp['salary_source'], emp['govt_salary_pct'],
                 basic_salary, gross, taxable, paye, shif, nssf_ee, nssf_er,
                 hl_ee, hl_er, total_deductions, net_pay,
                 json.dumps(breakdown, default=str)),
            )

            # Mark adjustments as applied
            for adj in adjustments:
                self.cursor.execute(
                    "UPDATE payroll_adjustments SET applied = 1, run_id = %s WHERE id = %s",
                    (run_id, adj['id']),
                )

            # Accumulate run totals
            run_totals['total_gross'] += gross
            run_totals['total_net'] += net_pay
            run_totals['total_paye'] += paye
            run_totals['total_shif'] += shif
            run_totals['total_nssf'] += nssf_ee
            run_totals['total_housing_levy'] += hl_ee
            run_totals['total_employer_nssf'] += nssf_er
            run_totals['total_employer_housing_levy'] += hl_er

        # Update run
        self.cursor.execute(
            "UPDATE payroll_runs SET status = 'generated', "
            "total_gross = %s, total_net = %s, total_paye = %s, total_shif = %s, "
            "total_nssf = %s, total_housing_levy = %s, total_employer_nssf = %s, "
            "total_employer_housing_levy = %s, generated_by = %s, generated_at = NOW() "
            "WHERE id = %s",
            (*[run_totals[k] for k in (
                'total_gross', 'total_net', 'total_paye', 'total_shif',
                'total_nssf', 'total_housing_levy', 'total_employer_nssf',
                'total_employer_housing_levy')],
             generated_by, run_id),
        )

        self._audit('payroll_run', run_id, 'generated',
                     new_values={'employees': len(employees), **{k: str(v) for k, v in run_totals.items()}})
        self.connection.commit()

        return {'run_id': run_id, 'employee_count': len(employees), **{k: str(v) for k, v in run_totals.items()}}

    def approve_payroll(self, run_id: int):
        run = self._assert_run_belongs(run_id)
        if run['status'] != 'generated':
            raise PayrollError(f"Cannot approve: run status is '{run['status']}'. Must be 'generated'.")
        approved_by = session.get('userNo', 0)
        self.cursor.execute(
            "UPDATE payroll_runs SET status = 'approved', approved_by = %s, approved_at = NOW() "
            "WHERE id = %s",
            (approved_by, run_id),
        )
        self._audit('payroll_run', run_id, 'approved')
        self.connection.commit()

    def post_to_gl(self, run_id: int) -> int:
        """Post approved payroll to the General Ledger."""
        run = self._assert_run_belongs(run_id)
        if run['status'] != 'approved':
            raise PayrollError(f"Cannot post: run status is '{run['status']}'. Must be 'approved'.")

        gl_map = self._gl_map()

        # Get lines grouped by salary source
        self.cursor.execute(
            "SELECT * FROM payroll_lines WHERE run_id = %s", (run_id,),
        )
        lines = self.cursor.fetchall()
        if not lines:
            raise PayrollError("No payroll lines to post.")

        # Aggregate by salary source
        agg = {'school': {}, 'government': {}, 'mixed': {}}
        fields = ('gross_pay', 'paye', 'shif', 'nssf_employee', 'nssf_employer',
                  'housing_levy_employee', 'housing_levy_employer', 'net_pay')
        for src in agg:
            agg[src] = {f: ZERO for f in fields}

        for line in lines:
            src = line['salary_source']
            if src == 'mixed':
                govt_pct = Decimal(str(line['govt_salary_pct'])) / Decimal('100')
                school_pct = Decimal('1') - govt_pct
                for f in fields:
                    val = Decimal(str(line[f]))
                    agg['school'][f] += val * school_pct
                    agg['government'][f] += val * govt_pct
            else:
                for f in fields:
                    agg[src][f] += Decimal(str(line[f]))

        # Build GL entries
        entries = []
        pay_period = run['pay_period']

        def _add(account_key, debit=ZERO, credit=ZERO, note=''):
            acct_id = gl_map.get(account_key)
            if not acct_id:
                raise PayrollError(f"GL mapping missing for '{account_key}'. Configure in Payroll Settings.")
            if debit > ZERO or credit > ZERO:
                entries.append({
                    'account_id': acct_id,
                    'debit': float(debit),
                    'credit': float(credit),
                    'note': note,
                })

        # School-paid portion
        school = agg['school']
        if school['gross_pay'] > ZERO:
            _add('salary_expense', debit=school['gross_pay'], note=f'Salary expense {pay_period}')
            _add('employer_nssf_expense', debit=school['nssf_employer'], note=f'Employer NSSF {pay_period}')
            _add('employer_hl_expense', debit=school['housing_levy_employer'], note=f'Employer HL {pay_period}')

        # Government-paid portion
        govt = agg['government']
        if govt['gross_pay'] > ZERO:
            _add('govt_receivable', debit=govt['gross_pay'] + govt['nssf_employer'] + govt['housing_levy_employer'],
                 note=f'Govt salary receivable {pay_period}')

        # Credit side (combined — payable accounts don't split by source)
        total_paye = agg['school']['paye'] + agg['government']['paye']
        total_shif = agg['school']['shif'] + agg['government']['shif']
        total_nssf = (agg['school']['nssf_employee'] + agg['government']['nssf_employee'] +
                      agg['school']['nssf_employer'] + agg['government']['nssf_employer'])
        total_hl = (agg['school']['housing_levy_employee'] + agg['government']['housing_levy_employee'] +
                    agg['school']['housing_levy_employer'] + agg['government']['housing_levy_employer'])
        total_net = agg['school']['net_pay'] + agg['government']['net_pay']

        _add('paye_payable', credit=total_paye, note=f'PAYE payable {pay_period}')
        _add('shif_payable', credit=total_shif, note=f'SHIF payable {pay_period}')
        _add('nssf_payable', credit=total_nssf, note=f'NSSF payable {pay_period}')
        _add('housing_levy_payable', credit=total_hl, note=f'Housing levy payable {pay_period}')
        _add('net_pay_payable', credit=total_net, note=f'Net salary payable {pay_period}')

        # Post via FinanceService
        from blueprints.finance.services import FinanceService
        finance = FinanceService(self.connection, self.school_id)
        posted_by = session.get('userNo', 0)
        txn_id = finance.record_transaction(
            date=f"{pay_period}-28",  # Last working day of month
            reference=f"PAY-{pay_period}",
            description=f"Payroll for {pay_period}",
            entries=entries,
            user_id=posted_by,
        )

        self.cursor.execute(
            "UPDATE payroll_runs SET status = 'posted', gl_transaction_id = %s, "
            "posted_by = %s, posted_at = NOW() WHERE id = %s",
            (txn_id, posted_by, run_id),
        )
        self._audit('payroll_run', run_id, 'posted', new_values={'gl_transaction_id': txn_id})
        self.connection.commit()
        return txn_id

    def reverse_payroll(self, run_id: int):
        """Reverse a posted payroll run."""
        run = self._assert_run_belongs(run_id)
        if run['status'] != 'posted':
            raise PayrollError(f"Cannot reverse: run status is '{run['status']}'. Must be 'posted'.")
        if run['is_reversed']:
            raise PayrollError("This run has already been reversed.")

        # Create reversing GL entry
        from blueprints.finance.services import FinanceService
        finance = FinanceService(self.connection, self.school_id)
        reversed_by = session.get('userNo', 0)

        # Fetch original GL entries and flip them
        self.cursor.execute(
            "SELECT account_id, debit, credit, note FROM finance_ledger_entries "
            "WHERE transaction_id = %s AND school_id = %s",
            (run['gl_transaction_id'], self.school_id),
        )
        original_entries = self.cursor.fetchall()
        reversal_entries = []
        for e in original_entries:
            reversal_entries.append({
                'account_id': e['account_id'],
                'debit': float(e['credit']),  # flip
                'credit': float(e['debit']),  # flip
                'note': f"REVERSAL: {e['note'] or ''}",
            })

        rev_txn_id = finance.record_transaction(
            date=datetime.now().strftime('%Y-%m-%d'),
            reference=f"REV-PAY-{run['pay_period']}",
            description=f"Reversal of payroll {run['pay_period']}",
            entries=reversal_entries,
            user_id=reversed_by,
        )

        # Update run
        self.cursor.execute(
            "UPDATE payroll_runs SET status = 'reversed', is_reversed = 1, "
            "reversal_gl_transaction_id = %s, reversed_by = %s, reversed_at = NOW() "
            "WHERE id = %s",
            (rev_txn_id, reversed_by, run_id),
        )

        # Unmark recurring adjustments so they can be re-applied
        self.cursor.execute(
            "UPDATE payroll_adjustments SET applied = 0, run_id = NULL "
            "WHERE run_id = %s AND is_recurring = 1 AND school_id = %s",
            (run_id, self.school_id),
        )

        self._audit('payroll_run', run_id, 'reversed',
                     new_values={'reversal_gl_transaction_id': rev_txn_id})
        self.connection.commit()

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def get_payslip(self, run_id: int, employee_id: int) -> Dict:
        self._assert_run_belongs(run_id)
        self.cursor.execute(
            "SELECT pl.*, pe.staff_id, pe.kra_pin, pe.nhif_no, pe.nssf_no, "
            "pe.bank_name, pe.bank_branch, pe.bank_account, "
            "s.surname, s.firstname, s.initials, s.natID_ppNo "
            "FROM payroll_lines pl "
            "JOIN payroll_employees pe ON pl.employee_id = pe.id "
            "LEFT JOIN staff s ON pe.staff_id = s.staffID "
            "WHERE pl.run_id = %s AND pl.employee_id = %s",
            (run_id, employee_id),
        )
        slip = self.cursor.fetchone()
        if not slip:
            raise PayrollError("Payslip not found.")
        if slip.get('breakdown_json'):
            slip['breakdown'] = json.loads(slip['breakdown_json'])
        return slip

    def get_payroll_summary(self, run_id: int) -> Dict:
        run = self.get_payroll_run(run_id)
        employee_count = len(run.get('lines', []))
        return {
            'run': run,
            'employee_count': employee_count,
            'avg_gross': Decimal(str(run['total_gross'])) / max(employee_count, 1),
            'avg_net': Decimal(str(run['total_net'])) / max(employee_count, 1),
        }

    def get_statutory_report(self, run_id: int, deduction_type: str = None) -> List[Dict]:
        """Per-employee statutory deduction report for a run."""
        self._assert_run_belongs(run_id)
        self.cursor.execute(
            "SELECT pl.employee_id, pe.staff_id, pe.kra_pin, pe.nhif_no, pe.nssf_no, "
            "s.surname, s.firstname, "
            "pl.gross_pay, pl.paye, pl.shif, pl.nssf_employee, pl.nssf_employer, "
            "pl.housing_levy_employee, pl.housing_levy_employer, pl.net_pay "
            "FROM payroll_lines pl "
            "JOIN payroll_employees pe ON pl.employee_id = pe.id "
            "LEFT JOIN staff s ON pe.staff_id = s.staffID "
            "WHERE pl.run_id = %s ORDER BY s.surname",
            (run_id,),
        )
        return self.cursor.fetchall()

    def get_government_payroll_report(self, run_id: int) -> List[Dict]:
        self._assert_run_belongs(run_id)
        self.cursor.execute(
            "SELECT pl.*, pe.staff_id, s.surname, s.firstname "
            "FROM payroll_lines pl "
            "JOIN payroll_employees pe ON pl.employee_id = pe.id "
            "LEFT JOIN staff s ON pe.staff_id = s.staffID "
            "WHERE pl.run_id = %s AND pl.salary_source IN ('government','mixed') "
            "ORDER BY s.surname",
            (run_id,),
        )
        return self.cursor.fetchall()

    def get_p9_data(self, employee_id: int, year: int) -> List[Dict]:
        """Monthly summaries for P9 tax certificate."""
        self._assert_employee_belongs(employee_id)
        self.cursor.execute(
            "SELECT pr.pay_period, pl.gross_pay, pl.taxable_income, pl.paye, "
            "pl.shif, pl.nssf_employee, pl.housing_levy_employee, pl.net_pay "
            "FROM payroll_lines pl "
            "JOIN payroll_runs pr ON pl.run_id = pr.id "
            "WHERE pl.employee_id = %s AND pr.school_id = %s "
            "AND pr.pay_period LIKE %s AND pr.status IN ('posted','reversed') "
            "AND pr.is_reversed = 0 "
            "ORDER BY pr.pay_period",
            (employee_id, self.school_id, f"{year}-%"),
        )
        return self.cursor.fetchall()

    def get_payroll_audit_report(self, run_id: int) -> List[Dict]:
        self.cursor.execute(
            "SELECT * FROM payroll_audit_logs "
            "WHERE school_id = %s AND entity_type = 'payroll_run' AND entity_id = %s "
            "ORDER BY performed_at",
            (self.school_id, run_id),
        )
        return self.cursor.fetchall()

    def get_payroll_vs_gl_reconciliation(self, run_id: int) -> Dict:
        """Compare payroll run totals against posted GL entries."""
        run = self._assert_run_belongs(run_id)
        if not run.get('gl_transaction_id'):
            return {'posted': False, 'run': run, 'gl_entries': []}

        self.cursor.execute(
            "SELECT le.*, a.code, a.name AS account_name "
            "FROM finance_ledger_entries le "
            "JOIN finance_accounts a ON le.account_id = a.id "
            "WHERE le.transaction_id = %s AND le.school_id = %s",
            (run['gl_transaction_id'], self.school_id),
        )
        gl_entries = self.cursor.fetchall()

        gl_total_debit = sum(Decimal(str(e['debit'])) for e in gl_entries)
        gl_total_credit = sum(Decimal(str(e['credit'])) for e in gl_entries)

        payroll_total = (Decimal(str(run['total_gross'])) +
                         Decimal(str(run['total_employer_nssf'])) +
                         Decimal(str(run['total_employer_housing_levy'])))

        return {
            'posted': True,
            'run': run,
            'gl_entries': gl_entries,
            'gl_total_debit': gl_total_debit,
            'gl_total_credit': gl_total_credit,
            'payroll_total_expense': payroll_total,
            'balanced': gl_total_debit == gl_total_credit,
            'matches': abs(gl_total_debit - payroll_total) < Decimal('0.02'),
        }

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def get_dashboard_stats(self) -> Dict:
        """Summary statistics for the payroll dashboard."""
        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM payroll_employees WHERE school_id = %s AND is_active = 1",
            (self.school_id,),
        )
        active_employees = self.cursor.fetchone()['cnt']

        self.cursor.execute(
            "SELECT * FROM payroll_runs WHERE school_id = %s ORDER BY pay_period DESC LIMIT 1",
            (self.school_id,),
        )
        latest_run = self.cursor.fetchone()

        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM payroll_adjustments "
            "WHERE school_id = %s AND applied = 0",
            (self.school_id,),
        )
        pending_adjustments = self.cursor.fetchone()['cnt']

        return {
            'active_employees': active_employees,
            'latest_run': latest_run,
            'pending_adjustments': pending_adjustments,
        }
