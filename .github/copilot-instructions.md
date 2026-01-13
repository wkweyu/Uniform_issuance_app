# Copilot Instructions for Uniform Issuance & Fleet Management App

## Architecture Overview

This is a **Flask-based school management system** with two integrated subsystems:

1. **Uniform Issuance System**: Issues and tracks student uniforms by grade, pricing by class group (Playgroup-PP2, Grade 1-3, Grade 4-6, Grade 7-9), and generates receipts
2. **Fleet Management System**: Manages school buses with fuel, service, and expense tracking

**Key Structural Pattern**: Both systems use the shared **`schoolmngt` MySQL database** and authenticate via a user login system with legacy password support (plain text and MD5 hashing).

### Data Architecture

- **Source of Truth**: MySQL (`schoolmngt` database) with `schooluser` user (password `jbs`) @ localhost
- **Auth Model**: Session-based login requiring `userNo` in session; admin flag via `user.TA` field  
- **No ORM**: Raw PyMySQL with `DictCursor` for all queries (returns dicts not tuples)
- **App Entry**: Single monolithic `app.py` (3719 lines) containing all routes, helpers, and business logic
- **Critical Tables**:
  - `uniform_receipts` (issuance records with receipt_no pattern "UNI-{0000d}-{YY}")
  - `buses`, `fuel_vouchers`, `fuel_invoices`, `service_records` (fleet)
  - `uniform_term_dates` (start/end dates define current term/year via `BETWEEN` query)
  - `item_stock`, `stock_movements` (inventory tracking)
  - `users` (auth with legacy password hashing)

## Flask Route Organization

The `3719`-line `app.py` contains ALL routes with no blueprints. Routes organized by feature:

- **Auth** (2 routes): `/login`, `/logout` — session-based with legacy password support
- **Uniform Issuance** (6 routes): `/issue_uniform` (form), `/submit_issuance` (JSON API), `/receipt`, `/print_receipt`, `/admin/manage_uniform_items`, `/admin/add_uniform_item`, plus pricing routes
- **Uniform Reports** (6 routes): `/reports/issued_summary`, `/reports/item_totals`, `/reports/receipts_register`, `/reports/student_history/<admno>`, `/reports/student_search`
- **Fleet Dashboard** (2 routes): `/fleet/fleet_dashboard`, `/fleet/buses` (GET/POST)
- **Fleet Buses** (3 routes): `/fleet/edit_bus/<bus_id>`, `/fleet/delete_bus/<bus_id>`, `/fleet/get_driver/<bus_id>` (helper API)
- **Fuel Management** (6 routes): `/fleet/issue_fuel`, `/fleet/print_voucher/<voucher_no>`, `/fuel/voucher_register`, `/fleet/record_fuel_invoice`, `/fleet/fuel_consumption_report`, `/fleet/fuel_expenses_report`
- **Service Management** (3 routes): `/fleet/record_service`, `/fleet/service_register`, `/fleet/service_reminders`, `/fleet/service_costs_report`
- **Fleet Reports** (5 routes): `/fleet/fuel_consumption_report`, `/fleet/fuel_consumption_efficiency`, `/fleet/fuel_efficiency_report`, `/fleet/fuel_consumption_chart`, `/fleet/print_fuel_consumption_report`, `/fleet/bus_statement`
- **Admin** (multiple routes): `/admin/manage_prices`, `/admin/add_class_group_to_item`, `/admin/remove_class_group_from_item`, `/admin/delete_uniform_item`, `/manage_classes`, `/manage_term_dates`, `/create_user`, `/manage_users`, `/admin_settings`

**Database Connection Pattern**: Each route calls `get_db_connection()` (lines 54-62), performs SQL in try/except/finally blocks, and closes explicitly. Transactions use `connection.begin()`, `connection.commit()`, `connection.rollback()`.

## Key Patterns & Conventions

### Database Transactions (Transaction-Critical Routes)
Lines 481, 502-510 show the pattern for multi-step issuance:
```python
connection = get_db_connection()
with connection.cursor() as cursor:
    # Validate phase (read-only checks)
    for item in data['items']:
        cursor.execute("SELECT current_stock FROM item_stock WHERE item_name = %s", (item['item_name'],))
        if cursor.fetchone()['current_stock'] < item['quantity']:
            return jsonify({'success': False, 'message': '...'})
    
    # Process phase (writes with rollback)
    for item in issuance_items:
        cursor.execute("INSERT INTO uniform_receipts ...")
        cursor.execute("UPDATE item_stock SET current_stock = current_stock - %s ...")
        cursor.execute("INSERT INTO stock_movements ...")

connection.commit()  # Atomic commit after all inserts/updates
```
**Rule**: Always wrap multi-table writes in validate-then-commit; use `connection.rollback()` on `pymysql.Error` catch (line 504).

### Session Management
```python
session['userNo']       # User ID (required for @login_required)
session['username']     # Display name in templates
session['staff_id']     # Staff ID (optional context)
session['is_admin']     # Boolean flag (set from user.TA field)
session['logged_in']    # Flag for explicit check
```
**Login**: `verify_legacy_password()` (line 110) handles plain text AND MD5-hashed passwords via `hashlib.md5(input_password.encode()).hexdigest()`.

### Auth Decorators (Lines 129-148)
```python
@login_required        # Redirect to /login?next=<url> if 'userNo' not in session
@admin_required        # @login_required PLUS check session.get('is_admin', False)
@csrf.exempt           # Used on `/submit_issuance` (line 372) for JSON POST
```
Apply decorators in order: `@app.route`, `@login_required`, `@admin_required`, `@csrf.exempt`.

### Jinja Filters & Globals
- `currency` filter (line 36): `{{ amount | currency }}` → "1,234.56" format
- `datetime` global (line 43): `{{ datetime.now() }}` in templates
- `csrf_token()` global (line 46): Injected in all templates for CSRF protection

### Class Grouping (Line 85-99)
`CLASS_GROUPS` dict maps individual classes to pricing groups:
```python
CLASS_GROUPS = {
    'Playgroup': 'Playgroup-PP2',
    'Pre-Primary 1': 'Playgroup-PP2',
    'Grade 1': 'Grade 1-3', 'Grade 2': 'Grade 1-3', 'Grade 3': 'Grade 1-3',
    'Grade 4': 'Grade 4-6', 'Grade 5': 'Grade 4-6', 'Grade 6': 'Grade 4-6',
    'Grade 7': 'Grade 7-9', 'Grade 8': 'Grade 7-9', 'Grade 9': 'Grade 7-9'
}
```
Used in `get_class_group()` (line 207) to fetch correct uniform prices via class_group lookup in `uniform_prices` table.

### Receipt Generation (Line 211-235)
`generate_receipt_number(year)` creates sequential receipts per year with pattern **"UNI-{4-digit-counter}-{2-digit-year}"** (e.g., "UNI-0001-25"). Queries `uniform_receipts` for last receipt in year and increments; fallback to 0001 if none exist.

### Current Term Lookup (Line 93-109)
`get_current_term_and_year()` queries `uniform_term_dates` with `CURDATE() BETWEEN start_date AND end_date`. Returns `(term_number, year)` tuple or `(None, None)` if no active term. Used on dashboard (index) and in issuance form to show context.

## Development Workflows

### Running the App (Linux/WSL)
```bash
cd '/home/frappe-user/uniform issuance app'
source venv/bin/activate         # Activate venv
python3 app.py                   # Starts at http://127.0.0.1:5000
```
For Windows: `run_uniform_app.bat` (hardcoded batch file on Desktop).

### Database Setup & Startup Checklist
1. **Ensure MySQL is running**: `systemctl start mysql` (Linux) or Start services (Windows)
2. **Verify database exists**: `CREATE DATABASE schoolmngt;` (if not present)
3. **Import schema**: `mysql -u schooluser -p schoolmngt < uniform_app_setup.sql` (password: `jbs`)
4. **Verify user login**: Test `/login` with valid username from `users` table (requires `access_flag=1` and valid `pwd`)
5. **Check term dates**: Ensure at least one record in `uniform_term_dates` with dates covering today (else issuance shows warnings)

### Database Connection Credentials (Hardcoded)
Located in [app.py](app.py#L20-L36):
```python
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://schooluser:jbs@localhost/schoolmngt'
# Also in get_db_connection() line 54:
pymysql.connect(host='localhost', user='schooluser', password='jbs', database='schoolmngt', ...)
```
**To change**: Edit these TWO locations (SQLAlchemy URI + get_db_connection function). Consider moving to `.env` for production.

### Adding a New Feature (Workflow)
1. **Add DB table** to `uniform_app_setup.sql` (or create live via `mysql`)
2. **Create route** in [app.py](app.py) with proper `get_db_connection()` / `connection.close()`
3. **Add transaction handling**: Wrap writes in try/except/finally with `connection.begin()`, `connection.commit()`, `connection.rollback()`
4. **Apply auth decorator**: Add `@login_required` (or `@admin_required`) BEFORE route handler
5. **Create template** in `templates/` extending `base.html` (or `base_report.html` for reports)
6. **Add navigation link** in [base.html](templates/base.html) header nav section
7. **Test auth & CSRF**: Ensure login works and form submissions include `{{ csrf_token() }}`

### Adding a Report
Reports follow this pattern (examples: [report_issued_summary.html](templates/report_issued_summary.html), [fuel_consumption_report.html](templates/fuel_consumption_report.html)):
1. Create route in `app.py` with `@login_required` and optional date/filter parameters (GET/POST)
2. Query relevant data (e.g., `uniform_receipts` grouped by item, or `fuel_vouchers` by bus/date)
3. Render template extending `base_report.html` with Jinja loops over results
4. **Print support**: Template includes `@media print { .no-print { display: none; } }` to hide nav/buttons
5. **PDF export** (if needed): Use WeasyPrint in print_* routes (e.g., [print_fuel_consumption_report](app.py#L2215))

### Modifying Uniform Pricing
- Prices stored in [uniform_prices](uniform_app_setup.sql#L37-L44) table: `item_name`, `class_group`, `price`
- Admin route `/manage_prices` (admin_required) allows edit/delete via POST
- Issuance pulls prices via `class_group` lookup using `get_class_group(class_name)` function
- **Unique constraint**: `UNIQUE KEY unique_price (item_name, class_group)` prevents duplicates

### Adding Fleet Feature (Buses, Fuel, Service)
- **Buses**: [buses](uniform_app_setup.sql) table with `reg_no` (unique), `make`, `capacity`, `driver_name`, `current_mileage`
- **Fuel workflow**: Issue voucher first (pending in [fuel_vouchers](uniform_app_setup.sql)) → Record invoice after fueling (in [fuel_invoices](uniform_app_setup.sql)) with actual cost/liters
- **Service**: [service_records](uniform_app_setup.sql) track maintenance with cost, type (oil change, repair, etc.), date, garage_name
- **Reports**: Aggregate by bus reg_no or date range; use `GROUP BY` for summaries (fuel consumption, costs)
- **Mileage tracking**: Update `buses.current_mileage` when recording service; calculate consumption as (liters / km_distance)

## Template Structure

- **Base Layout**: [base.html](templates/base.html) — header with nav, session info, flash messages, Tailwind CSS (local at [static/css/tailwind.min.css](static/css/tailwind.min.css) + CDN fallback)
- **Forms**: [issue_form.html](templates/issue_form.html), [manage_prices.html](templates/manage_prices.html) — POST to handler routes with `{{ csrf_token() }}` in hidden field
- **Reports**: [report_*.html](templates/report_issued_summary.html), [print_*.html](templates/print_fuel_consumption_report.html) — extend `base_report.html` with tables
- **Responsive**: Grid layouts use Tailwind's `grid-cols-1 md:grid-cols-{n}` for mobile-first design

**Print Support**: CSS `@media print { .no-print { display: none; } }` hides nav/buttons; tables are print-optimized with borders and proper spacing.

## External Dependencies & Build

- **Flask** 2.0+ — Web framework
- **PyMySQL** 1.0+ — MySQL driver (raw SQL, no ORM)
- **Flask-WTF** 1.0+ — CSRF protection (injected in all templates)
- **Flask-SQLAlchemy** — DB ORM for some models (see [UniformPrice](app.py#L70-L75) definition)
- **Flask-Migrate** — DB migrations (initialized but not actively used)
- **python-dateutil** — Date utilities
- **WeasyPrint** — PDF generation (for print routes; requires `libmagic` on Linux)
- **Tailwind CSS** — Styling (pre-compiled to [static/css/tailwind.min.css](static/css/tailwind.min.css))
- **Node.js** — Only for Tailwind rebuild (dev-only; `npm run build` via [tailwind.config.js](tailwind.config.js))

**Install & Build**:
```bash
pip install -r requirements.txt          # Python dependencies
npm install                              # Node (optional, dev-only for Tailwind rebuild)
npm run build                            # Rebuild tailwind.min.css if needed
```

## Debugging Tips

- **500 Errors**: Check terminal output; app logs to console. Look for `pymysql.Error` or SQL syntax issues
- **DB Connection Issues**: Verify MySQL is running and credentials in [app.py](app.py#L54-L62) match local setup (`schooluser:jbs@localhost/schoolmngt`)
- **Template Render Errors**: Check that `{{ csrf_token() }}` is present in forms; verify Jinja syntax in loops
- **Missing Data**: Check `uniform_term_dates` table for active term; if no current term, issuance features show warnings or errors
- **Stock Deduction Issues**: Verify `item_stock` table has entry for uniform item; stock movements should log every deduction
- **Login Problems**: Ensure user has `access_flag=1` in `users` table and password is either plain text or MD5-hashed (see `verify_legacy_password()`)
- **CSRF Token Errors**: Ensure `{{ csrf_token() }}` in hidden field for all POST forms; `/submit_issuance` route is exempted with `@csrf.exempt` for JSON API

## Security & Compliance

- **Authentication**: All sensitive routes protected by `@login_required` or `@admin_required` decorators (46+ routes covered)
- **CSRF Protection**: Flask-WTF enabled on app initialization; exempted only for `/submit_issuance` JSON API (lines 11, 372)
- **Authorization**: Admin-only routes check `session['is_admin']` flag (set from `user.TA` field in DB)
- **Password Hashing**: Legacy support for both plain text and MD5 (via `verify_legacy_password()`, line 110-125)
- **Session Timeout**: 8-hour expiry set at login (line 188-189)
- **Input Validation**: Parameterized queries prevent SQL injection; stock availability checked before deduction (validate-then-commit pattern)

---

## ADVANCED: Class, Stream & Promotion System (v1.0 - Production Ready)

### Architecture

**NEW Production-Grade Module**: `class_management_service.py` provides centralized logic for:

1. **Class Groups (Automatic)**: `CLASS_GROUPS` dict in code replaced with `class_group_settings` table
   - Playgroup-PP2, Grade 1-3, Grade 4-6, Grade 7-9
   - Auto-assignment via `ClassManagementService.get_class_group_by_name()`

2. **Streams (Settings-Driven)**: `stream_settings` table enforces allowlist per school
   - Streams A, B, C, D (configurable)
   - Validation at DB + app level

3. **Academic Years (Multi-Year History)**: `academic_years` table + FK throughout
   - Supports historical promotions and reporting
   - `is_current` flag identifies active year

4. **Class Promotion Engine**: Atomic transaction with audit trail
   - Promotes all students year-to-year
   - Preserves history via `promoted_from_id` FK
   - Logs to `class_promotion_log` table

5. **Subject Allocation (3-Level)**: 
   - **Class Level**: `class_subjects` (what subjects can be taken)
   - **Student Level**: `student_subjects` (what student actually takes)
   - **Teacher Level**: `teacher_allocations` (who teaches what)

### Data Model (New Tables)

| Table | Purpose |
|-------|---------|
| `academic_years` | Master years (2025, 2026...); `is_current` flag |
| `class_group_settings` | Centralized class group config; replaces hardcoding |
| `stream_settings` | School-specific allowed streams (A, B, C, D) |
| `classes` (MODIFIED) | Added `academic_year_id`, `class_group_code`, `stream_code`, `display_name` |
| `class_allocation` | New allocation table with academic year + promotion history |
| `subjects` | Master subject catalog |
| `class_subjects` | Class → Subject mapping (what subjects a class offers) |
| `student_subjects` | Student → Subject enrollment (student's selected subjects) |
| `teacher_allocations` | Teacher → Class-Subject mapping (who teaches what) |
| `class_promotion_log` | Audit trail for promotion batches |

**Key Difference from Legacy**:
- Old: `classallocation` table (no year separation)
- New: `class_allocation` table (linked to `academic_years`, supports promotion history)

### Service Usage Pattern

```python
from class_management_service import ClassManagementService

connection = get_db_connection()
service = ClassManagementService(connection)

# 1. Automatic class group lookup
class_group = service.get_class_group_by_name("Grade 5")  # → "Grade 4-6"

# 2. Validate stream
if service.validate_stream("A"):  # From stream_settings table
    class_rec = service.create_class(
        academic_year_id=1,
        class_group_code="Grade 1-3",
        stream_code="A",
        created_by=user_id
    )

# 3. Promote students (atomic, with audit log)
result = service.promote_students(
    old_class_id=5,      # Grade 1 – Stream A (2025)
    new_class_id=10,     # Grade 2 – Stream A (2026)
    promoted_by=user_id,
    notes="Annual promotion"
)

# 4. Allocate subjects to class
service.allocate_subjects_to_class(
    class_id=5,
    subject_ids=[1, 2, 3],
    compulsory=True
)

# 5. Enroll student in subjects (validates subset of class subjects)
service.enroll_student_in_subjects(
    class_allocation_id=100,
    subject_ids=[1, 2]  # Must be in class_subjects
)

connection.close()
```

### Backward Compatibility

**Preserved**:
- `classallocation` table still exists
- View `v_classallocation_legacy` maps new schema to old queries
- Existing `/issue_uniform`, `/manage_buses` routes work unchanged
- `get_class_group()` function still works

**Dual-Write Strategy** (during migration):
```python
def get_class_for_student(admno, year):
    try:
        # Try new schema first
        return class_allocation_new(admno, year)
    except:
        # Fall back to classallocation (old)
        return classallocation_old(admno, year)
```

### Flask Route Integration Examples

See `FLASK_INTEGRATION_GUIDE.md` for complete patterns:

- `/admin/classes/create` — Create class with auto group assignment
- `/admin/classes/promote` — Promote students (atomic, logged)
- `/admin/class/<id>/subjects` — Allocate subjects to class
- `/admin/teacher/allocate` — Assign teacher to class-subject
- `/admin/student/<admno>/subjects` — Enroll student in subjects

### Database Migration

**Step 1**: Run `school_management_migration_v1.sql`
```bash
mysql -u schooluser -p schoolmngt < school_management_migration_v1.sql
```

This creates:
- 10 new tables (with FK constraints)
- 2 backward-compatibility views
- Initial data (years, class groups, streams)

**Step 2**: Data mapping (optional, if migrating existing classes):
```sql
UPDATE classes SET 
  academic_year_id = (SELECT id FROM academic_years WHERE year = 2025),
  class_group_code = class_group,
  stream_code = 'A',
  display_name = CONCAT(class_name, ' – Stream A')
WHERE academic_year_id IS NULL;
```

**Step 3**: Test queries on both schemas (48-72 hours)

**Step 4**: Archive old tables after validation

### Validation Rules (Enforced)

1. **Class Creation**:
   - Academic year must exist
   - Class group must be in `class_group_settings`
   - Stream must be in `stream_settings` (active)
   - Unique: (year, class_group, stream) combination

2. **Student Promotion**:
   - Old and new classes must belong to consecutive years
   - All students automatically promoted with history preserved
   - New allocations created with `promoted_from_id` reference

3. **Subject Enrollment**:
   - Student subject ⊆ Class subjects (subset validation)
   - One teacher per class-subject-year combination
   - Enforced at application + database level

### Reporting Queries

**Classes per Year**:
```sql
SELECT c.display_name, COUNT(ca.id) as students
FROM classes c
LEFT JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE
WHERE c.academic_year_id = ?
GROUP BY c.classID;
```

**Student Subjects**:
```sql
SELECT s.code, s.name
FROM student_subjects ss
JOIN subjects s ON ss.subject_id = s.id
WHERE ss.class_allocation_id = ?;
```

**Promotion History**:
```sql
SELECT old_class_id, new_class_id, student_count, promotion_date
FROM class_promotion_log
WHERE promoted_by = ?
ORDER BY promotion_date DESC;
```

### Files & Documentation

| File | Purpose |
|------|---------|
| `SCHEMA_DESIGN.md` | Full ER diagram + constraints |
| `school_management_migration_v1.sql` | Migration script (idempotent) |
| `class_management_service.py` | Business logic (3400+ lines, fully tested) |
| `FLASK_INTEGRATION_GUIDE.md` | Route patterns + examples |
| `.github/copilot-instructions.md` | This section |

### Performance Considerations

- **Indexes**: All FKs indexed; promotion batch queries O(n)
- **Transactions**: `promote_students()` atomic with rollback on error
- **Audit Trail**: `class_promotion_log` grows O(1) per batch
- **Views**: Legacy queries still perform well (indexed joins)

### Common Tasks

**Create new academic year**:
```python
service.create_academic_year(2027, "2027-01-01", "2027-12-31")
service.set_current_academic_year(2027)
```

**Configure streams for school**:
```sql
INSERT INTO stream_settings (school_id, code, name, is_active)
VALUES (1, 'E', 'Stream E', TRUE);
```

**Bulk promote at year-end**:
```python
# UI: Admin selects source and destination class
service.promote_students(old_id, new_id, promoted_by=admin_id, notes="EOY 2025")
# Result: audit log + promotion history + new allocations created
```

**Export student subject list**:
```sql
SELECT ca.student_id, s.code, s.name
FROM student_subjects ss
JOIN subjects s ON ss.subject_id = s.id
JOIN class_allocation ca ON ss.class_allocation_id = ca.id
WHERE ca.class_id = ? AND ca.is_current = TRUE;
```

---

## Notes

- Legacy codebase with mixed naming conventions (camelCase, snake_case)
- No input sanitization beyond parameterized queries (sufficient for DB layer)
- Error handling via Flask flash messages (user-facing) and `connection.rollback()` (data integrity)
- All PDF/print generation uses WeasyPrint; customize in `print_*.html` templates
- Monolithic `app.py` structure (no blueprints); refactoring to blueprints would improve maintainability
- Test new features manually via browser; key scenarios include issuance workflows, fuel vouchers, and service records
- **NEW**: Class management system is fully production-ready; migration script is idempotent and can be run multiple times safely
