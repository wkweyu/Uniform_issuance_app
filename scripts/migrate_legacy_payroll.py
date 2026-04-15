#!/usr/bin/env python3
"""
Legacy Payroll Data Migration Script
=====================================
Migrates data from legacy tables (acc_salary, acc_payslip, acc_payslip_entry, staff)
into the new payroll schema (payroll_employees, payroll_runs, payroll_lines, etc.)

Usage:
    python scripts/migrate_legacy_payroll.py --dry-run
    python scripts/migrate_legacy_payroll.py --commit --school-id 1

Environment:
    Reads DB credentials from .env or environment variables.
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

logger = logging.getLogger('legacy_migration')

ZERO = Decimal('0.00')

# Map legacy payslip entry IDs to new component codes
LEGACY_ENTRY_MAP = {
    # acc_payslip_entry.entry → payroll_components.code
    'HOUSE ALLOWANCE': 'HOUSE_ALLOW',
    'RISK ALLOWANCE': 'OTHER_ALLOW',
    'RESPONSIBILITY ALLOWANCE': 'RESPONSIBILITY',
    'GRATUITY': 'OTHER_ALLOW',
    'SHIF': 'SHIF',
    'NSSF': 'NSSF',
    'ADVANCE SALARY': 'ADVANCE',
    'LOAN': 'LOAN',
    'OTHER ALLOWANCES': 'OTHER_ALLOW',
    'OTHER DEDUCTIONS': 'OTHER_DED',
    'PAYE': 'PAYE',
    'HOUSING LEVY': 'HOUSING_LEVY',
    'WAUMINI SACCO': 'SACCO',
}

# Entries that are earnings (onSalary=1 in legacy)
EARNING_ENTRIES = {
    'HOUSE ALLOWANCE', 'RISK ALLOWANCE', 'RESPONSIBILITY ALLOWANCE',
    'GRATUITY', 'OTHER ALLOWANCES',
}


def get_connection():
    """Get database connection from environment."""
    from dotenv import load_dotenv
    load_dotenv()

    return pymysql.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'schoolmngt'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def migrate_employees(cursor, school_id, dry_run=True):
    """
    Migrate staff records into payroll_employees.
    Maps:
        staff.staffID → payroll_employees.staff_id
        staff.kraPin_no → kra_pin
        staff.bankAcc → bank_account
        staff.bankID → bank_name
        staff.istsc='TSC' → salary_source='government'
    """
    logger.info("--- Migrating Employees ---")

    # Get staff not already in payroll_employees
    cursor.execute(
        "SELECT s.* FROM staff s "
        "LEFT JOIN payroll_employees pe ON s.staffID = pe.staff_id AND pe.school_id = %s "
        "WHERE pe.id IS NULL AND s.transfered != 'YES'",
        (school_id,),
    )
    staff_records = cursor.fetchall()
    logger.info(f"Found {len(staff_records)} staff not yet on payroll.")

    # Try to get basic salary from most recent acc_salary record
    cursor.execute(
        "SELECT staffID, MAX(amount) AS latest_salary "
        "FROM acc_salary "
        "WHERE mode = 'salary' OR code = 'salary' "
        "GROUP BY staffID"
    )
    salary_lookup = {r['staffID']: Decimal(str(r['latest_salary'])) for r in cursor.fetchall()}

    created = 0
    skipped = 0
    for s in staff_records:
        staff_id = s['staffID']
        basic_salary = salary_lookup.get(staff_id, ZERO)
        if basic_salary <= ZERO:
            logger.warning(f"  SKIP {staff_id}: no salary data found.")
            skipped += 1
            continue

        salary_source = 'government' if s.get('istsc') == 'TSC' else 'school'

        if not dry_run:
            cursor.execute(
                "INSERT INTO payroll_employees "
                "(school_id, staff_id, basic_salary, salary_source, kra_pin, "
                " bank_name, bank_account, is_active, effective_from, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, 0)",
                (school_id, staff_id, basic_salary, salary_source,
                 s.get('kraPin_no') or None,
                 s.get('bankID') or None,
                 s.get('bankAcc') or None,
                 date.today().isoformat()),
            )
            created += 1
        else:
            logger.info(f"  [DRY] Would create employee: {staff_id}, salary={basic_salary}, source={salary_source}")
            created += 1

    logger.info(f"Employees: {created} created, {skipped} skipped (no salary data).")
    return created, skipped


def migrate_employee_components(cursor, school_id, dry_run=True):
    """
    Migrate legacy payslip entries into payroll_employee_components.
    Uses latest payslip amounts per staff member.
    """
    logger.info("--- Migrating Employee Components ---")

    # Get component code mapping for this school
    cursor.execute(
        "SELECT id, code FROM payroll_components WHERE school_id = %s",
        (school_id,),
    )
    comp_lookup = {r['code']: r['id'] for r in cursor.fetchall()}

    if not comp_lookup:
        logger.warning("No payroll components found. Run the app first to seed defaults.")
        return 0

    # Get payroll employee IDs
    cursor.execute(
        "SELECT id, staff_id FROM payroll_employees WHERE school_id = %s",
        (school_id,),
    )
    emp_lookup = {r['staff_id']: r['id'] for r in cursor.fetchall()}

    # Get entry definitions
    cursor.execute("SELECT * FROM acc_payslip_entry")
    entry_defs = {r['payslipEntryID']: r for r in cursor.fetchall()}

    # Get latest payslip amounts per staff (most recent paidFor)
    cursor.execute(
        "SELECT staffID, payslipEntryID, amount "
        "FROM acc_payslip ap "
        "WHERE paidFor = ("
        "    SELECT MAX(paidFor) FROM acc_payslip WHERE staffID = ap.staffID"
        ") AND amount > 0"
    )
    latest_entries = cursor.fetchall()

    # Group by staff
    staff_entries = defaultdict(list)
    for row in latest_entries:
        staff_entries[row['staffID']].append(row)

    total_components = 0
    for staff_id, entries in staff_entries.items():
        emp_id = emp_lookup.get(staff_id)
        if not emp_id:
            continue

        for entry in entries:
            entry_def = entry_defs.get(entry['payslipEntryID'])
            if not entry_def:
                continue

            entry_name = entry_def['entry']
            comp_code = LEGACY_ENTRY_MAP.get(entry_name)
            if not comp_code:
                logger.warning(f"  No mapping for entry '{entry_name}', skipping.")
                continue

            comp_id = comp_lookup.get(comp_code)
            if not comp_id:
                continue

            amount = Decimal(str(entry['amount']))
            is_earning = entry_name in EARNING_ENTRIES

            if not dry_run:
                try:
                    cursor.execute(
                        "INSERT INTO payroll_employee_components "
                        "(employee_id, component_id, amount, is_percent, mode, is_active) "
                        "VALUES (%s, %s, %s, 0, 'manual', 1) "
                        "ON DUPLICATE KEY UPDATE amount = %s",
                        (emp_id, comp_id, amount, amount),
                    )
                    total_components += 1
                except Exception as e:
                    logger.error(f"  Error for {staff_id}/{comp_code}: {e}")
            else:
                logger.info(f"  [DRY] {staff_id} → {comp_code}={amount}")
                total_components += 1

    logger.info(f"Components: {total_components} mapped.")
    return total_components


def migrate_historical_payroll(cursor, school_id, dry_run=True):
    """
    Reconstruct historical payroll runs from acc_salary + acc_payslip data.
    Groups by paidFor (month) to create payroll_runs + payroll_lines.
    """
    logger.info("--- Migrating Historical Payroll Data ---")

    # Get payroll employee IDs
    cursor.execute(
        "SELECT id, staff_id FROM payroll_employees WHERE school_id = %s",
        (school_id,),
    )
    emp_lookup = {r['staff_id']: r['id'] for r in cursor.fetchall()}

    # Get entry definitions for deduction identification
    cursor.execute("SELECT * FROM acc_payslip_entry")
    entry_defs = {r['payslipEntryID']: r for r in cursor.fetchall()}

    # Get distinct pay periods from acc_salary
    cursor.execute(
        "SELECT DISTINCT paidFor FROM acc_salary WHERE paidFor != '' ORDER BY paidFor"
    )
    periods = [r['paidFor'] for r in cursor.fetchall()]
    logger.info(f"Found {len(periods)} historical pay periods.")

    runs_created = 0
    lines_created = 0

    for period in periods:
        # Normalize period format: legacy may be 'January 2025' or '2025-01'
        pay_period = _normalize_period(period)
        if not pay_period:
            logger.warning(f"  Cannot parse period '{period}', skipping.")
            continue

        # Check if run already exists
        cursor.execute(
            "SELECT id FROM payroll_runs WHERE school_id = %s AND pay_period = %s",
            (school_id, pay_period),
        )
        if cursor.fetchone():
            continue  # Skip already-migrated periods

        # Get salary records for this period
        cursor.execute(
            "SELECT staffID, amount FROM acc_salary WHERE paidFor = %s",
            (period,),
        )
        salary_records = cursor.fetchall()

        # Get payslip entries for this period
        cursor.execute(
            "SELECT staffID, payslipEntryID, amount FROM acc_payslip WHERE paidFor = %s AND amount > 0",
            (period,),
        )
        payslip_records = cursor.fetchall()

        # Group payslip entries by staff
        staff_payslip = defaultdict(list)
        for r in payslip_records:
            staff_payslip[r['staffID']].append(r)

        if not salary_records:
            continue

        if dry_run:
            logger.info(f"  [DRY] Would create run for {pay_period} with {len(salary_records)} staff")
            runs_created += 1
            lines_created += len(salary_records)
            continue

        # Create payroll run as historical (status='posted' since it's past)
        try:
            cursor.execute(
                "INSERT INTO payroll_runs "
                "(school_id, pay_period, status, created_at) "
                "VALUES (%s, %s, 'posted', NOW())",
                (school_id, pay_period),
            )
        except pymysql.IntegrityError:
            continue  # Duplicate period

        run_id = cursor.lastrowid
        runs_created += 1

        run_totals = {k: ZERO for k in (
            'total_gross', 'total_net', 'total_paye', 'total_shif',
            'total_nssf', 'total_housing_levy', 'total_employer_nssf',
            'total_employer_housing_levy')}

        for sal in salary_records:
            staff_id = sal['staffID']
            emp_id = emp_lookup.get(staff_id)
            if not emp_id:
                continue

            basic_salary = Decimal(str(sal['amount']))
            entries = staff_payslip.get(staff_id, [])

            # Parse deductions from payslip entries
            paye = ZERO
            shif = ZERO
            nssf_ee = ZERO
            hl_ee = ZERO
            gross = basic_salary

            # Sum earnings from payslip
            for ent in entries:
                edef = entry_defs.get(ent['payslipEntryID'])
                if not edef:
                    continue
                amt = Decimal(str(ent['amount']))
                if edef.get('onSalary') == 1:
                    gross += amt  # Earning additions
                else:
                    # Deductions
                    name = edef['entry']
                    if name == 'PAYE':
                        paye = amt
                    elif name == 'SHIF':
                        shif = amt
                    elif name == 'NSSF':
                        nssf_ee = amt
                    elif name == 'HOUSING LEVY':
                        hl_ee = amt

            # Estimate employer contributions
            nssf_er = nssf_ee  # employer typically matches
            hl_er = hl_ee

            total_deductions = paye + shif + nssf_ee + hl_ee
            net_pay = gross - total_deductions

            # Build a minimal breakdown
            breakdown = {
                'earnings': [{'code': 'BASIC', 'amount': str(basic_salary), 'mode': 'migrated'}],
                'statutory': [
                    {'code': 'PAYE', 'amount': str(paye), 'mode': 'migrated'},
                    {'code': 'SHIF', 'amount': str(shif), 'mode': 'migrated'},
                    {'code': 'NSSF', 'employee': str(nssf_ee), 'employer': str(nssf_er), 'mode': 'migrated'},
                    {'code': 'HOUSING_LEVY', 'employee': str(hl_ee), 'employer': str(hl_er), 'mode': 'migrated'},
                ],
                'deductions': [],
                'adjustments': [],
            }

            # Add earning entries from payslip
            for ent in entries:
                edef = entry_defs.get(ent['payslipEntryID'])
                if edef and edef.get('onSalary') == 1:
                    breakdown['earnings'].append({
                        'code': LEGACY_ENTRY_MAP.get(edef['entry'], 'OTHER'),
                        'name': edef['entry'],
                        'amount': str(ent['amount']),
                        'mode': 'migrated',
                    })

            try:
                cursor.execute(
                    "INSERT INTO payroll_lines "
                    "(run_id, employee_id, salary_source, govt_salary_pct, basic_salary, "
                    " gross_pay, taxable_income, paye, shif, nssf_employee, nssf_employer, "
                    " housing_levy_employee, housing_levy_employer, total_deductions, net_pay, "
                    " breakdown_json) "
                    "VALUES (%s, %s, 'school', 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (run_id, emp_id, basic_salary, gross, gross,
                     paye, shif, nssf_ee, nssf_er, hl_ee, hl_er,
                     total_deductions, net_pay, json.dumps(breakdown, default=str)),
                )
                lines_created += 1
            except Exception as e:
                logger.error(f"  Error inserting line for {staff_id}/{pay_period}: {e}")
                continue

            run_totals['total_gross'] += gross
            run_totals['total_net'] += net_pay
            run_totals['total_paye'] += paye
            run_totals['total_shif'] += shif
            run_totals['total_nssf'] += nssf_ee
            run_totals['total_housing_levy'] += hl_ee
            run_totals['total_employer_nssf'] += nssf_er
            run_totals['total_employer_housing_levy'] += hl_er

        # Update run totals
        cursor.execute(
            "UPDATE payroll_runs SET "
            "total_gross = %s, total_net = %s, total_paye = %s, total_shif = %s, "
            "total_nssf = %s, total_housing_levy = %s, total_employer_nssf = %s, "
            "total_employer_housing_levy = %s "
            "WHERE id = %s",
            (*[run_totals[k] for k in (
                'total_gross', 'total_net', 'total_paye', 'total_shif',
                'total_nssf', 'total_housing_levy', 'total_employer_nssf',
                'total_employer_housing_levy')], run_id),
        )

    logger.info(f"Historical: {runs_created} runs, {lines_created} lines.")
    return runs_created, lines_created


def migrate_paye_formula(cursor, school_id, dry_run=True):
    """
    Migrate legacy PAYE formula as a reference record.
    Does NOT overwrite current rates — logs for comparison.
    """
    logger.info("--- Checking Legacy PAYE Formula ---")
    cursor.execute("SELECT * FROM acc_paye_formula ORDER BY `_from`")
    rows = cursor.fetchall()

    if not rows:
        logger.info("  No legacy PAYE formula found.")
        return

    for r in rows:
        logger.info(
            f"  Legacy band: {r['_from']:>12,.0f} – {r['_to']:>12,.0f} @ {r['value']}%"
        )

    logger.info("  Current statutory rates preserved. Legacy formula logged for reference only.")


def _normalize_period(period_str: str) -> str:
    """Convert legacy period format to YYYY-MM."""
    # Already in YYYY-MM format
    if len(period_str) == 7 and period_str[4] == '-':
        return period_str

    # Try 'Month YYYY' format
    months = {
        'january': '01', 'february': '02', 'march': '03', 'april': '04',
        'may': '05', 'june': '06', 'july': '07', 'august': '08',
        'september': '09', 'october': '10', 'november': '11', 'december': '12',
    }
    parts = period_str.strip().lower().split()
    if len(parts) == 2 and parts[0] in months:
        return f"{parts[1]}-{months[parts[0]]}"

    # Try 'YYYY-MM-DD' format
    if len(period_str) >= 7 and period_str[:4].isdigit():
        return period_str[:7]

    return None


def main():
    parser = argparse.ArgumentParser(description='Migrate legacy payroll data')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Preview changes without writing (default)')
    parser.add_argument('--commit', action='store_true',
                        help='Actually write changes to database')
    parser.add_argument('--school-id', type=int, required=True,
                        help='School ID to migrate data for')
    parser.add_argument('--skip-employees', action='store_true',
                        help='Skip employee migration')
    parser.add_argument('--skip-components', action='store_true',
                        help='Skip component migration')
    parser.add_argument('--skip-history', action='store_true',
                        help='Skip historical payroll migration')
    args = parser.parse_args()

    dry_run = not args.commit

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%H:%M:%S',
    )

    logger.info("=" * 60)
    logger.info(f"Legacy Payroll Migration {'(DRY RUN)' if dry_run else '(COMMIT MODE)'}")
    logger.info(f"School ID: {args.school_id}")
    logger.info("=" * 60)

    conn = get_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    try:
        if not args.skip_employees:
            migrate_employees(cursor, args.school_id, dry_run)

        if not args.skip_components:
            migrate_employee_components(cursor, args.school_id, dry_run)

        if not args.skip_history:
            migrate_historical_payroll(cursor, args.school_id, dry_run)

        migrate_paye_formula(cursor, args.school_id, dry_run)

        if not dry_run:
            conn.commit()
            logger.info("\n*** COMMITTED all changes ***")
        else:
            conn.rollback()
            logger.info("\n*** DRY RUN complete — no changes written ***")
            logger.info("Run with --commit to apply changes.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()

    logger.info("Done.")


if __name__ == '__main__':
    main()
