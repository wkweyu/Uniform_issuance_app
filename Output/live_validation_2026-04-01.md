# Live Validation Report

Timestamp: 2026-04-01T19:27:47Z

## Migration Status

- Remote migration runner completed successfully against the configured database after idempotent DDL handling and SQL comment parsing were fixed.
- Database host: dionysus.hostns.io
- Database name: u80655_schoolmngt

## Application Smoke Test

### First startup attempt

- Temporary server port: 5011
- Result: partial startup success, but database health failed
- `GET /health` -> `503`
- `GET /login` -> `200`
- `HEAD /platform/schools` -> `302 Location: /platform/login`
- `HEAD /` -> `302 Location: /login?next=...`
- Health response body:

```json
{"error":"(1698, \"Access denied for user 'frappe-user'@'localhost'\")","status":"unhealthy","timestamp":"2026-04-01T22:25:21.344943"}
```

Interpretation: the first background app process was not using the same effective remote DB settings as the migration shell, so it fell back to a local credential path.

### Explicit remote-backed startup

- Temporary server port: 5012
- Remote DB settings were injected explicitly for the process
- `GET /health` -> `200`
- `GET /login` -> `200`
- `HEAD /platform/schools` -> `302 Location: /platform/login`
- `HEAD /` -> `302 Location: /login?next=http%253A//127.0.0.1%253A5012/`

Interpretation: the live DB-backed app path is healthy when started with the remote database environment applied explicitly.

## Schema Snapshot

### Overview

- Total tables: 301
- Sample tables:
  - academic_years
  - acadgroups
  - acc_arrears
  - acc_assets
  - acc_balances
  - acc_bank_account
  - acc_budget
  - acc_cashbook
  - acc_client
  - acc_commits
  - acc_currency
  - acc_delpay
  - acc_delpv
  - acc_delsales
  - acc_deposits
  - acc_d_commits
  - acc_expense
  - acc_fdiscounts
  - acc_fees
  - acc_fees_overpayment
  - acc_fse
  - acc_fse_details
  - acc_gl
  - acc_gl_cat
  - acc_gl_department

### Row Counts

- `schools`: 2
- `school_settings`: 2
- `subscriptions`: 0
- `platform_users`: 0

### Focused SaaS Tables

#### `schools`

| Column | Type | Nullable | Key |
|---|---|---|---|
| id | int(11) | NO | PRI |
| name | varchar(255) | NO | |
| code | varchar(20) | YES | UNI |
| email | varchar(255) | YES | |
| phone | varchar(64) | YES | |
| address | varchar(255) | YES | |
| city | varchar(128) | YES | |
| country | varchar(128) | YES | |
| logo | varchar(255) | YES | |
| subscription_plan | varchar(64) | YES | |
| subscription_status | varchar(32) | NO | |
| subscription_start | date | YES | |
| is_active | tinyint(1) | YES | |
| subscription_end | date | YES | |
| created_at | datetime | YES | |

#### `school_settings`

| Column | Type | Nullable | Key |
|---|---|---|---|
| id | int(11) | NO | PRI |
| school_id | int(11) | NO | UNI |
| school_name | varchar(255) | YES | |
| logo | varchar(255) | YES | |
| address | varchar(255) | YES | |
| email | varchar(255) | YES | |
| phone | varchar(64) | YES | |
| website | varchar(255) | YES | |
| timezone | varchar(64) | NO | |
| currency | varchar(16) | NO | |
| grading_system | varchar(64) | YES | |
| report_template | varchar(128) | YES | |
| created_at | datetime | NO | |
| updated_at | datetime | NO | |

#### `subscriptions`

| Column | Type | Nullable | Key |
|---|---|---|---|
| id | int(11) | NO | PRI |
| school_id | int(11) | NO | MUL |
| plan_id | int(11) | NO | MUL |
| status | varchar(32) | YES | |
| billing_cycle | varchar(32) | NO | |
| amount_cents | int(11) | NO | |
| payment_reference | varchar(128) | YES | |
| trial_ends_at | datetime | YES | |
| grace_period_ends_at | datetime | YES | |
| ended_at | datetime | YES | |
| archived_at | datetime | YES | |
| started_at | datetime | YES | |
| renewal_date | datetime | YES | |
| billing_meta | longtext | YES | |

#### `platform_users`

| Column | Type | Nullable | Key |
|---|---|---|---|
| id | int(11) | NO | PRI |
| name | varchar(255) | YES | |
| email | varchar(255) | NO | UNI |
| password_hash | varchar(255) | NO | |
| role | varchar(64) | NO | |
| is_active | tinyint(1) | NO | |
| assigned_school_id | int(11) | YES | MUL |
| portfolio_scope | longtext | YES | |
| mfa_enabled | tinyint(1) | NO | |
| created_by | int(11) | YES | |
| created_at | datetime | YES | |
| last_login_at | datetime | YES | |

#### `users`

| Column | Type | Nullable | Key |
|---|---|---|---|
| userNo | int(11) | NO | PRI |
| StaffID | varchar(6) | YES | |
| username | varchar(32) | YES | |
| pwd | varchar(32) | YES | |
| domainID | int(11) | YES | |
| access_flag | tinyint(4) | YES | |
| dateReg | varchar(32) | YES | |
| RegStaffID | varchar(6) | YES | |
| TA | int(1) | YES | |
| _date | timestamp | YES | |
| school_id | int(11) | NO | MUL |

#### `studentinfo`

| Column | Type | Nullable | Key |
|---|---|---|---|
| AdmNo | int(11) | NO | PRI |
| parentID | varchar(128) | YES | |
| index_no | varchar(24) | YES | |
| pwd | varchar(32) | NO | |
| SName | varchar(64) | YES | |
| MName | varchar(64) | YES | |
| FName | varchar(64) | YES | |
| Sex | varchar(1) | YES | |
| state | varchar(32) | YES | |
| DoB | varchar(16) | YES | |
| Religion | varchar(32) | YES | |
| passport | varchar(16) | YES | |
| Date_Adm | varchar(64) | YES | |
| email | varchar(128) | YES | |
| transfered | varchar(128) | YES | |
| blocked | varchar(8) | NO | |
| boarding | varchar(8) | NO | |
| notes | text | YES | |
| _date | timestamp | NO | |
| upi | varchar(32) | NO | |
| fingerprint1 | text | YES | |
| fingerprint2 | text | YES | |
| regno | varchar(32) | YES | UNI |
| birth | varchar(32) | NO | |
| nhif | varchar(128) | YES | |
| category | varchar(32) | YES | |
| alt_contact | varchar(64) | YES | |
| stream | varchar(16) | YES | |
| route_id | int(11) | YES | |
| student_group_id | int(11) | YES | |
| school_id | int(11) | NO | MUL |

## Notes

- The live schema now contains the expanded SaaS columns and `school_settings` table expected by the migration set.
- `subscriptions` and `platform_users` are present but currently empty in the live database snapshot.
- If the application should always target the remote DB in this environment, the startup path should be aligned so `get_db_connection()` receives the same DB settings used by the migration runner without requiring explicit inline environment overrides.