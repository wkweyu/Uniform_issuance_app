# 📘 Payroll Module Implementation Guide (Phase 1 Extension)

## 🎯 Objective

Implement a **lightweight, audit-compliant payroll system** integrated into the existing modular Flask ERP architecture.

This payroll module must:

* Reuse existing **Finance (GL), Users, Tenancy, and Audit systems**
* Follow the **Service Layer architecture**
* Be **IPSAS-aligned**
* Support **Kenyan statutory compliance (PAYE, NHIF, NSSF)**
* Avoid building a full HR system (keep it lean and focused)

---

# 🧱 1. Architecture Alignment (MANDATORY)

## Follow existing patterns:

```
blueprints/payroll/
   routes.py
   services.py
   models.py
   templates/payroll/

core/
   helpers.py
   tenancy.py
   audit.py
   decorators.py
```

## Rules:

* ❌ No business logic in routes
* ✅ All logic in `services.py`
* ✅ All queries scoped by `school_id`
* ✅ Use existing `FinanceService.post_journal()`
* ✅ Use `@audit_log` on all mutations

---

# 🧩 2. Data Models

## Employee Payroll Profile

```python
class EmployeePayrollProfile(db.Model, TenantMixin):
    id
    employee_id
    pay_structure_id
    basic_salary
    bank_account
    tax_pin
    nhif_number
    nssf_number
    salary_source  # government / school / mixed
    fund_id
    is_active
```

---

## Pay Structure (Reusable Templates)

```python
class PayStructure(db.Model, TenantMixin):
    id
    name
```

```python
class PayStructureItem(db.Model, TenantMixin):
    id
    structure_id
    type  # earning / deduction
    name  # Basic, House Allowance, PAYE
    calculation_type  # fixed / percentage / formula / manual
    value
```

---

## Payroll Run

```python
class PayrollRun(db.Model, TenantMixin):
    id
    period_month
    period_year
    total_gross
    total_deductions
    total_net
    status  # draft / approved / posted
```

---

## Payroll Line

```python
class PayrollLine(db.Model, TenantMixin):
    id
    payroll_run_id
    employee_id
    gross_pay
    total_deductions
    net_pay
    breakdown_json  # snapshot for audit
```

---

# ⚙️ 3. Payroll Processing Logic (Service Layer)

## Class Definition

```python
class PayrollService:
```

---

## Step 1: Create Payroll Run

```python
def create_run(month, year)
```

* Initialize with status = `draft`

---

## Step 2: Generate Payroll

```python
def generate_payroll(run_id)
```

### Flow:

1. Fetch all active employees
2. Load their pay structures
3. Compute earnings
4. Compute deductions
5. Store payroll lines

---

## Step 3: Earnings Calculation

```python
gross = sum(earnings)
```

---

## Step 4: Deductions Logic

### Support:

* PAYE (formula-based)
* NHIF (banded)
* NSSF (fixed/percentage)
* Manual deductions

---

## Kenyan Compliance Logic

### PAYE (simplified progressive)

Implement in:

```
core/tax.py
```

---

### NHIF Bands

Use configurable table (DO NOT hardcode)

---

### NSSF

Tier I / Tier II (configurable)

---

## Step 5: Net Pay

```python
net = gross - deductions
```

---

## Step 6: Approval

```python
def approve_run(run_id)
```

* Locks payroll
* Prevents edits

---

## Step 7: Posting to Ledger

```python
def post_to_ledger(run_id)
```

---

# 💰 4. Accounting Integration (CRITICAL)

## A. Salary Recognition

| Account            | Debit | Credit |
| ------------------ | ----- | ------ |
| Salaries Expense   | ✔     |        |
| PAYE Payable       |       | ✔      |
| NHIF Payable       |       | ✔      |
| NSSF Payable       |       | ✔      |
| Net Salary Payable |       | ✔      |

---

## B. Salary Payment

| Account            | Debit | Credit |
| ------------------ | ----- | ------ |
| Net Salary Payable | ✔     |        |
| Bank               |       | ✔      |

---

## C. Statutory Remittance

| Account      | Debit | Credit |
| ------------ | ----- | ------ |
| PAYE Payable | ✔     |        |
| Bank         |       | ✔      |

---

## Implementation

Use existing:

```python
FinanceService.post_journal(entries)
```

---

# 🏛 5. IPSAS + Fund Accounting

Each payroll line must include:

```python
fund_id
salary_source
```

---

## Government Salary Scenario

### When earned:

| Account               | Debit | Credit |
| --------------------- | ----- | ------ |
| Salaries Expense      | ✔     |        |
| Government Receivable |       | ✔      |

---

### When received:

| Account               | Debit | Credit |
| --------------------- | ----- | ------ |
| Bank                  | ✔     |        |
| Government Receivable |       | ✔      |

---

# 📊 6. Reports (MANDATORY)

## Core Reports

* Payroll Summary
* Payslips
* Deduction Reports
* Payroll Journal Report
* Staff Cost Report
* Government Payroll Report

---

## 🇰🇪 P9 Form (VERY IMPORTANT)

### Requirement:

Generate annual tax report per employee.

### Fields:

* Gross Pay
* Taxable Pay
* PAYE deducted
* Reliefs

---

## Implementation:

```python
def generate_p9(employee_id, year)
```

Output:

* PDF
* Exportable

---

# 📥📤 7. Import / Export

## Import

Support CSV upload:

* Employee payroll profiles
* Pay structures

```python
def import_payroll_profiles(file)
```

---

## Export

```python
def export_payroll_run(run_id)
```

Formats:

* CSV
* Excel

---

# 🔐 8. Audit & Controls

Mandatory:

* ✔ Approval before posting
* ✔ No edits after posting
* ✔ Reversal instead of delete
* ✔ Audit logs via `@audit_log`
* ✔ Payslip snapshot stored

---

# 🧠 9. Design Principles

## DO:

* Use Finance module for accounting
* Keep payroll configurable
* Use service layer strictly
* Support multi-tenancy

---

## DO NOT:

* Build full HR system
* Hardcode tax logic
* Mix payroll with fees
* Allow edits after posting

---

# 🚀 10. Implementation Order (Copilot Execution Plan)

1. Create models
2. Build PayrollService
3. Implement tax utilities (`core/tax.py`)
4. Build payroll run logic
5. Integrate Finance posting
6. Add approval workflow
7. Build reports (start with summary)
8. Add P9 generator
9. Add import/export
10. Add UI routes/templates

---

# ✅ Final Outcome

A **lean, powerful payroll engine** that:

* Integrates with Finance
* Supports Kenyan compliance
* Produces audit-ready reports
* Aligns with IPSAS
* Scales across tenants

---

**End of Implementation Guide**

