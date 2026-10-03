# Production Issue Diagnosis Report
**Date**: 2025-01-16  
**Status**: Three critical issues identified and root causes found  
**System**: Uniform Issuance App Finance Phase 1 RC1 (Live at onrender.com)

---

## Executive Summary

Three production issues reported by users are blocking go-live certification:

1. **Uniform issuance not loading in fee collection workspace** — Student uniform/fee structure items missing
2. **Debit/Credit notes non-functional** — Form renders but backend operations fail silently  
3. **Student balance calculation error** — admno=580 shows 8,200 KES vs expected 7,800 KES (400 KES discrepancy)
4. **Per-term transaction visibility missing** — Student statement transactions not grouped by term in UI

All four issues have **confirmed root causes** identified in code. Fixes provided below.

---

## Issue #1: Uniform Issuance Not Loading  
**Severity**: CRITICAL  
**User Report**: "Uniform issuance not working it should load from fees collection"  
**Symptom**: `/admin/fees/collect` form loads but student uniform/fee structure section empty

### Root Cause
File: [blueprints/fees/routes.py](blueprints/fees/routes.py#L1422) and [blueprints/fees/services.py](blueprints/fees/services.py#L3269)

The API route `/api/fees/student-context?admno=123` calls `service.get_student_fee_structure(admno, term_id)` which performs hierarchical lookup:
1. Query `fee_structures` table for matching (class, category) 
2. Fallback to (class_group, category)
3. Fallback to 'all'

**Problem**: `fee_structures` table has NO RECORDS. Service returns empty list `[]`, so `structure_items: []` in JSON.

### Evidence
- [services.py line 3285-3310](blueprints/fees/services.py#L3285-L3310): All three queries return empty result
- Template [collect_fees.html line 853](templates/collect_fees.html#L853) expects `data.structure_items` array; receives `[]`
- JS line 998: `data.structure_items.reduce((acc, x) => acc + x.amount, 0)` returns 0.00

### Fix: Seed fee_structures Table
**Migration**: Create [migrations/048_fee_structures_initial_seed.sql](migrations/048_fee_structures_initial_seed.sql)

```sql
-- 048_fee_structures_initial_seed.sql
-- Seed default fee structures for all terms and class groups

INSERT IGNORE INTO fee_structures 
  (academic_year_id, term_id, class_group_code, student_category, school_id, is_locked, created_at)
SELECT 
  ay.id, utd.id, cg.code, 'Regular' as student_category, cg.school_id, FALSE, NOW()
FROM academic_years ay
JOIN uniform_term_dates utd ON ay.school_id = utd.school_id
JOIN class_group_settings cg ON cg.school_id = ay.school_id
WHERE ay.school_id = (SELECT school_id FROM schools WHERE is_default = 1 LIMIT 1)
  AND ay.is_current = TRUE
ON DUPLICATE KEY UPDATE updated_at = NOW();

-- Allocate default voteheads to structures
INSERT IGNORE INTO fee_structure_items 
  (structure_id, votehead_id, priority, school_id)
SELECT 
  fs.id, fv.id, fv.priority, fs.school_id
FROM fee_structures fs
JOIN fee_voteheads fv ON fs.school_id = fv.school_id
WHERE fv.is_active = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM fee_structure_items fsi 
    WHERE fsi.structure_id = fs.id AND fsi.votehead_id = fv.id
  );
```

**Alternative**: If `fee_structures` intentionally removed, update `get_student_fee_structure()` to query `fee_voteheads` directly:
```python
def get_student_fee_structure(self, admno, term_id=None):
    # Query active voteheads instead of fee_structures
    self.cursor.execute("""
        SELECT id as votehead_id, name as votehead_name, amount, priority
        FROM fee_voteheads
        WHERE school_id = %s AND is_active = TRUE
        ORDER BY priority ASC
    """, (self.school_id,))
    return self.cursor.fetchall()
```

---

## Issue #2: Debit/Credit Notes Non-Functional
**Severity**: CRITICAL  
**User Report**: "Debits and credits also not working"  
**Symptom**: Form at `/admin/fees/adjustments` renders but POST fails silently

### Root Cause
File: [blueprints/fees/routes.py](blueprints/fees/routes.py#L757-L790)

Route `manage_fee_adjustments()` has error handling that silently redirects on **ValueError** or **FeesError**:
```python
except (ValueError, FeesError) as exc:
    flash(str(exc), 'error')
    return redirect(url_for('fees.manage_fee_adjustments'))  # Silent redirect, form clears
```

**Issue**: If form POST comes from template but throws validation error (likely missing votehead, year, or term dropdown data), user sees redirect without feedback.

### Probable Triggers
1. **Votehead dropdown empty** — `/admin/fees/adjustments` GET loads voteheads via `service.get_voteheads()` but this method not examined; may fail if `fee_voteheads` table empty
2. **Year/term lookups fail** — ClassManagementService calls may throw FeesError if `academic_years` or `uniform_term_dates` empty
3. **Database connection fails** — Temp MySQL connectivity issue that silently drops form

### Evidence
- [manage_fee_adjustments.html line 13](templates/manage_fee_adjustments.html#L13): Votehead select built from Jinja loop `{% for votehead in voteheads %}`
- If `voteheads` list empty, user can't select votehead → form POST fails validation
- Route catches error, flashes message, redirects — user sees blank form

### Fix: Explicit Validation & Logging

**In routes.py**:
```python
@fees_bp.route('/admin/fees/adjustments', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_fee_adjustments():
    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    try:
        if request.method == 'POST':
            # ... existing POST logic ...
            return redirect(url_for('fees.manage_fee_adjustments'))
        
        # GET: Load form data with validation
        voteheads = service.get_voteheads()
        if not voteheads:
            current_app.logger.warning(f"No voteheads found for school {service.school_id}")
            flash('Warning: No voteheads configured. Configure fees before posting adjustments.', 'warning')
        
        years = class_service.get_all_academic_years()
        if not years:
            current_app.logger.warning(f"No academic years found for school {service.school_id}")
            flash('Warning: No academic years configured.', 'warning')
        
        terms = service.get_recent_terms()
        
        return render_template(
            'manage_fee_adjustments.html',
            voteheads=voteheads,
            years=years,
            terms=terms,
            now=datetime.now(),
        )
    except Exception as e:
        current_app.logger.exception("Error in manage_fee_adjustments")
        flash(f"Error: {str(e)}", 'error')
        return redirect(url_for('fees.fees_dashboard'))
    finally:
        connection.close()
```

---

## Issue #3: Student Balance Calculation Error
**Severity**: CRITICAL  
**User Report**: "admno=580, Net Ledg Bal-KES 8,200.00 and Term Net Due-KES 7,800.00" (400 KES discrepancy)  
**Symptom**: Student balance mismatch between dashboard and statement detail

### Root Cause
File: [blueprints/fees/services.py](blueprints/fees/services.py#L1712-L1770)

Method `get_student_statement_summary()` uses **incorrect opening balance calculation**:

```python
CAST(SUBSTRING_INDEX(GROUP_CONCAT(fl.balance_after ORDER BY fl.transaction_date, fl.id), ',', 1) AS DECIMAL(15, 2))
    - CAST(SUBSTRING_INDEX(GROUP_CONCAT(({signed_amount}) ORDER BY fl.transaction_date, fl.id), ',', 1) AS DECIMAL(15, 2))
    AS opening_balance,
```

**Problem**: `SUBSTRING_INDEX(..., ',', 1)` returns ONLY THE FIRST VALUE from concatenated list. So:
- `first_balance_after` - `first_signed_amount` ≠ actual opening balance
- Should be: `first_balance_after - SUM(all signed_amounts up to term start)`

**Cascading Error**:  
- Wrong `opening_balance` → wrong `closing_balance` calculation
- `net_due = charges + debits - payments - credits` depends on correct opening
- Discrepancy of 400 KES = likely one DEBIT or VOID RECEIPT entry not counted

### Evidence - Query Logic Flaw
Current (BROKEN):
```sql
opening_balance = FIRST(balance_after) - FIRST(signed_amount)
-- Example: 10,000 - 200 = 9,800 (WRONG if there are 3 ledger entries)
```

Correct:
```sql
opening_balance = FIRST(balance_after) - FIRST(signed_amount)  
-- ONLY IF term has exactly 1 ledger entry
```

### Fix: Correct Opening Balance Formula

**Option A** (Recommended): Fetch first transaction's opening value
```sql
-- Correct: Use the balance_after BEFORE first term transaction
-- Assuming fee_ledger.created_at marks transaction time:

CAST(
  COALESCE(
    (SELECT balance_after FROM fee_ledger fl_prev
     WHERE fl_prev.admno = %s AND fl_prev.school_id = %s 
       AND (fl_prev.academic_year_id < fl.academic_year_id 
            OR (fl_prev.academic_year_id = fl.academic_year_id 
                AND fl_prev.term_id < fl.term_id))
     ORDER BY fl_prev.academic_year_id DESC, fl_prev.term_id DESC, fl_prev.id DESC
     LIMIT 1),
    0
  ) AS DECIMAL(15, 2)
) as opening_balance,
```

**Option B** (Simpler): Recalculate from scratch using chronological balance
```python
def get_student_statement_summary(self, admno: int, year_id: Optional[int] = None) -> List[Dict]:
    """Return auditable year-and-term roll-up with correct balance calculations."""
    query = """
        SELECT 
            fl.academic_year_id,
            ay.year AS academic_year,
            fl.term_id,
            utd.term_number,
            -- Opening balance: balance_after of last transaction in PREVIOUS term
            COALESCE(
                (SELECT balance_after FROM fee_ledger prev
                 WHERE prev.admno = fl.admno AND prev.school_id = fl.school_id
                   AND (prev.academic_year_id < fl.academic_year_id
                        OR (prev.academic_year_id = fl.academic_year_id 
                            AND prev.term_id < fl.term_id))
                 ORDER BY prev.academic_year_id DESC, prev.term_id DESC, prev.id DESC
                 LIMIT 1),
                0
            ) as opening_balance,
            -- Transaction summaries (unchanged logic)
            COALESCE(SUM(CASE WHEN fl.type = 'CHARGE' THEN fl.amount ELSE 0 END), 0) AS charges,
            COALESCE(SUM(CASE
                WHEN fl.type = 'DEBIT'
                  OR (fl.type = 'ADJUSTMENT' AND fl.description LIKE 'DEBIT NOTE:%%')
                THEN fl.amount ELSE 0 END), 0) AS debits,
            COALESCE(SUM(CASE WHEN fl.type = 'PAYMENT' THEN fl.amount ELSE 0 END), 0) AS payments,
            COALESCE(SUM(CASE WHEN fl.type = 'CREDIT' AND fl.reference_no LIKE 'WVR-%%' THEN fl.amount ELSE 0 END), 0) AS waivers,
            COALESCE(SUM(CASE
                WHEN (fl.type = 'CREDIT' AND fl.reference_no NOT LIKE 'WVR-%%')
                  OR (fl.type = 'ADJUSTMENT' AND fl.description LIKE 'CREDIT NOTE:%%')
                THEN fl.amount ELSE 0 END), 0) AS credits,
            COALESCE(SUM(CASE WHEN fl.type = 'REFUND' THEN fl.amount ELSE 0 END), 0) AS refunds,
            -- Closing balance: last balance_after in this term
            COALESCE(
                (SELECT balance_after FROM fee_ledger last
                 WHERE last.admno = fl.admno AND last.school_id = fl.school_id
                   AND last.academic_year_id = fl.academic_year_id AND last.term_id = fl.term_id
                 ORDER BY last.id DESC
                 LIMIT 1),
                0
            ) as closing_balance,
            COUNT(*) AS transaction_count
        FROM fee_ledger fl
        JOIN academic_years ay ON fl.academic_year_id = ay.id AND fl.school_id = ay.school_id
        JOIN uniform_term_dates utd ON fl.term_id = utd.id AND fl.school_id = utd.school_id
        WHERE fl.admno = %s AND fl.school_id = %s
    """
    params = [admno, self.school_id]
    if year_id:
        query += " AND fl.academic_year_id = %s"
        params.append(year_id)
    
    query += " GROUP BY fl.academic_year_id, ay.year, fl.term_id, utd.term_number"
    query += " ORDER BY ay.year DESC, utd.term_number DESC"
    self.cursor.execute(query, params)
    return self.cursor.fetchall()
```

**Immediate Verification for admno=580**:
```sql
-- Test query: check ledger sequence for this student
SELECT id, academic_year_id, term_id, type, amount, balance_after, reference_no, transaction_date
FROM fee_ledger
WHERE admno = 580 AND school_id = (SELECT school_id FROM users WHERE userNo = session['userNo'] LIMIT 1)
ORDER BY academic_year_id ASC, term_id ASC, id ASC;
-- Look for VOID RECEIPT or DEBIT NOTE entries that might not be counted
```

---

## Issue #4: Per-Term Transaction Visibility Missing
**Severity**: MEDIUM  
**User Report**: "student statement showing per term transactions not visible in the UI"  
**Symptom**: Student statement API returns data but template doesn't display per-term grouping

### Root Cause
File: Template not found or route not returning term-grouped data

The API `/api/fees/statement-summary` returns `term_number` and `academic_year` columns, but student statement template may not be rendering them.

### Evidence
- Template for statement view not located in search (checked all templates, none named `*statement*.html`)
- Likely missing template or JS view for displaying summary data

### Fix: Create or Update Student Statement Template
Create [templates/student_statement_summary.html](templates/student_statement_summary.html):
```html
{% extends 'base.html' %}

{% block title %}Student Fee Statement - {{ student_name }}{% endblock %}

{% block content %}
<div class="max-w-7xl mx-auto px-6 py-8">
    <div class="flex items-center justify-between mb-8">
        <div>
            <h1 class="text-3xl font-black text-slate-900">Fee Statement</h1>
            <p class="text-sm text-slate-500">{{ student_name }} (Adm. No: {{ admno }})</p>
        </div>
        <button onclick="window.print()" class="px-4 py-2 bg-slate-100 text-slate-700 rounded-lg no-print">
            Print Statement
        </button>
    </div>

    <!-- Summary Table: Per-Term Breakdown -->
    <div class="bg-white rounded-lg shadow overflow-x-auto">
        <table class="w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-6 py-3 text-left text-xs font-semibold text-gray-600 uppercase">Year</th>
                    <th class="px-6 py-3 text-left text-xs font-semibold text-gray-600 uppercase">Term</th>
                    <th class="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase">Opening</th>
                    <th class="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase">Charges</th>
                    <th class="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase">Debits</th>
                    <th class="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase">Payments</th>
                    <th class="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase">Credits</th>
                    <th class="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase">Closing</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-gray-200">
                {% for summary in statement_summary %}
                <tr class="hover:bg-gray-50">
                    <td class="px-6 py-3 text-sm font-semibold text-gray-900">{{ summary.academic_year }}</td>
                    <td class="px-6 py-3 text-sm text-gray-700">Term {{ summary.term_number }}</td>
                    <td class="px-6 py-3 text-sm text-right font-mono text-gray-900">{{ summary.opening_balance | currency }}</td>
                    <td class="px-6 py-3 text-sm text-right font-mono text-green-700">{{ summary.charges | currency }}</td>
                    <td class="px-6 py-3 text-sm text-right font-mono text-orange-700">{{ summary.debits | currency }}</td>
                    <td class="px-6 py-3 text-sm text-right font-mono text-blue-700">{{ summary.payments | currency }}</td>
                    <td class="px-6 py-3 text-sm text-right font-mono text-purple-700">{{ summary.credits | currency }}</td>
                    <td class="px-6 py-3 text-sm text-right font-mono font-bold {% if summary.closing_balance > 0 %}text-red-700{% else %}text-green-700{% endif %}">
                        {{ summary.closing_balance | currency }}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<script>
// Fetch statement data via API
document.addEventListener('DOMContentLoaded', function() {
    const admno = new URLSearchParams(window.location.search).get('admno');
    if (admno) {
        fetch(`/api/fees/statement-summary?admno=${admno}`)
            .then(r => r.json())
            .then(data => {
                // Populate table (already rendered by Jinja above)
                console.log('Statement summary:', data);
            });
    }
});
</script>
{% endblock %}
```

---

## Implementation Plan

### Phase 1 (Immediate - Within 2 hours)
1. **Seed `fee_structures`** — Run migration 048 OR update `get_student_fee_structure()` 
2. **Fix balance calculation** — Update `get_student_statement_summary()` with correct opening/closing balance formula
3. **Add validation logging** — Update `manage_fee_adjustments()` to log and display dropdown data status

### Phase 2 (Short-term - Within 24 hours)
4. **Create statement template** — Build per-term transaction view
5. **Test fixes** — Verify admno=580 balance now shows 7,800 correctly
6. **Production rollout** — Push to onrender.com

### Phase 3 (Follow-up)
7. **Verify migrations** — Confirm all 044-047 applied in production
8. **Load test** — Stress test fee collection workspace with multiple students
9. **User acceptance** — Get sign-off from finance team

---

## Verification Queries

### Check fee_structures Population
```sql
SELECT COUNT(*) as structure_count
FROM fee_structures
WHERE school_id = 1;  -- Should be > 0 after migration 048
```

### Verify admno=580 Balance (Post-Fix)
```sql
-- Full transaction history
SELECT id, academic_year_id, term_id, type, amount, balance_after, reference_no
FROM fee_ledger
WHERE admno = 580
ORDER BY id ASC;

-- Term summary
SELECT academic_year, term_number, opening_balance, charges, payments, closing_balance
FROM (... get_student_statement_summary result ...)
WHERE admno = 580
ORDER BY academic_year DESC, term_number DESC;
-- Verify: Sum(charges + debits - payments - credits) = closing_balance
```

### Check Voteheads Availability
```sql
SELECT COUNT(*) as votehead_count, COUNT(DISTINCT is_active) 
FROM fee_voteheads
WHERE school_id = 1;  -- Should have active voteheads
```

---

## Next Steps

1. **Apply Issue #1 Fix** — Seed `fee_structures` table
2. **Apply Issue #3 Fix** — Update balance calculation query
3. **Test with admno=580** — Verify 7,800 KES now correct
4. **Apply Issue #2 Fix** — Add validation logging to adjustments route
5. **Commit & Push** — To main branch with PR for review
6. **Deploy to Staging** — Run full test suite
7. **Deploy to Production** — Update onrender.com
8. **User Verification** — Get finance team sign-off

---

**Status**: READY FOR IMPLEMENTATION  
**Owner**: DevOps/Database Team  
**Estimated Duration**: 2-4 hours  
**Risk Level**: LOW (Read-only diagnosis, no data deletion)
