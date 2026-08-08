# Finance Phase 1 Certification Matrix

## Scope

This matrix certifies the implemented Finance Phase 1 behavior without changing existing Finance Domain architecture, receipt numbering, raw-PyMySQL ledger ownership, or tenant boundaries.

Automated evidence was executed on 2026-08-08:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_blueprint_route_integration.py tests/test_procurement_inventory_isolation.py tests/test_migration_preflight.py
```

Result: `338 passed in 66.10s`.

## Automated Certification

| Area | Status | Evidence |
| --- | --- | --- |
| Cash, M-PESA, cheque, and bank receipt validation | PASS | Payment mode resolution, receiving-account persistence, duplicate/reference validation, and payment input validation in `tests/test_procurement_inventory_isolation.py` |
| Automatic, manual, and mixed allocation | PASS | Manual allocation validation, priority remainder allocation, receipt allocation preview, and posted allocation coverage in both Finance test suites |
| Receipt transfer/reallocation | PASS | `test_fees_service_reallocation_recalculates_both_student_ledger_balances` and tenant-target rejection coverage |
| Receipt reversal/cancellation | PASS | `test_fees_service_void_receipt_records_immutable_lifecycle_snapshot` |
| Receipt repost/archive/reprint | PASS | Repost source-link rollback coverage, archive idempotency, cancelled/archive reprint rejection, and lifecycle route coverage |
| Receipt search/register/journal | PASS | Receipt register date, status, lifecycle, cashier, admission, receipt/reference, and tenant-scope coverage |
| Manual, individual, and bulk invoicing | PASS | Individual/manual and bulk standard/votehead invoice route coverage plus foreign-votehead rejection tests |
| Invoice replacement and student corrections | PASS | Paid-allocation conflict preflight, class/category correction replacement, and replacement-register audit tests |
| Debit notes, credit notes, and refunds | PASS | Debit balance recalculation, credit adjustment linkage, credit-limited refund, and refund over-credit rejection tests |
| Waivers and scholarships | PASS | Individual/group waiver assignment, votehead allocation, revocation adjustment, and tenant-scope coverage |
| Student category, group, class, and stream changes | PASS | Classification replacement preflight and class correction coverage; student context and current class/stream collection filtering are tenant-scoped |
| Student statement and term summary | PASS | Statement ledger classification and student-term summary tenant-scope tests; route and workspace rendering coverage |
| Collections, revenue, lifecycle, and reallocation reports | PASS | Cross-filter summaries for period, class, stream, category, votehead, cashier, mode, and status; lifecycle/reallocation audit report coverage |
| Cashier sessions | PASS | Open float, receipt linkage, expected cash, variance threshold, approval, locking, reopening, audit events, and daily register tests |
| Payment account chain | PASS | Tenant-owned receiving/settlement/clearing/default-GL configuration, inactive-account rejection, audit events, and legacy receiving-only compatibility tests |
| Tenant isolation | PASS | Finance, fees, payment, allocation, receipt, invoice, waiver, statement, report, and account-chain service tests require active-school joins or reject foreign records |
| Audit and correlation IDs | PASS | Lifecycle snapshots, archive/repost links, transfer snapshots, reallocation audit records, payment account events, cashier session events, and correlation report tests |
| Chronological balances and allocation integrity | PASS | Reallocation balance rebuild, debit/credit/refund balance tests, manual allocation limits, duplicate votehead rejection, and payment transaction rollback tests |
| Migration safeguards | PASS | `tests/test_migration_preflight.py`, including cashier-session uniqueness preflight; migrations are idempotent through `ADD ... IF NOT EXISTS`/`CREATE TABLE IF NOT EXISTS` patterns |

## Release-Gate Executions

The following are mandatory before final production sign-off but require a production-like MySQL target and interactive browser environment. They are not automated in the current workspace test fixture and are therefore not marked as passed.

| Gate | Status | Required execution |
| --- | --- | --- |
| Migration rehearsal | NOT EXECUTED | Run migration status/preflight, apply migrations 046 and 047 to a production-like backup, verify migration journal checksums, then perform the documented rollback rehearsal. |
| Browser desktop/tablet smoke tests | NOT EXECUTED | Exercise bursar search, keyboard shortcuts, AJAX error states, receipt print/reprint, lifecycle actions, cashier session open/close/reopen, and account-chain configuration in supported browsers. |
| Printed receipt validation | NOT EXECUTED | Print each payment mode receipt and verify allocation and resolved receiving-account display. |
| Backup and restore rehearsal | NOT EXECUTED | Restore a production-like backup and verify fee ledger, lifecycle, session, and account-chain audit records. |
| Performance sanity check | NOT EXECUTED | Measure student search, receipt posting, statement retrieval, and collection report response times against production-like data. |

## Known Limitations

- Final Finance Phase 1 release certification remains conditional on the release-gate executions above.
- Settlement, clearing, and default GL accounts are configured and validated for bank-reconciliation readiness. No new incompatible GL posting path was introduced; existing Finance Domain journal conventions remain authoritative.