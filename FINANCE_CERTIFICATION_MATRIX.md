# Finance Certification Matrix

Release candidate: Finance Phase 1 RC1

Tester: Automated regression suite / Lead ERP Finance Engineer

Certification date: 2026-08-08

Status definitions: `PASS` means automated evidence passed. `PENDING TARGET VALIDATION` means the scenario requires a production-like database, supported browser, printer, or approved deployment target and was not simulated by the repository tests.

| Feature | Scenario | Expected Result | Actual Result | Status | Tester | Date |
| --- | --- | --- | --- | --- | --- | --- |
| Cashier session | Open session and opening float | One tenant-scoped open session is created with an opening float and audit event. | Atomic open-session and duplicate-open rejection tests pass. | PASS | Automated suite | 2026-08-08 |
| Cashier session | Cash receipt linkage and running totals | Completed cash receipts link to the open session and determine expected cash. | Posting lock and session-register scope tests pass. | PASS | Automated suite | 2026-08-08 |
| Cashier session | Counted cash, variance, approval, reopen | Variance requires a reason, approval is audited, and reopening requires an audited reason. | Close, approval, lock, and reopen tests pass. | PASS | Automated suite | 2026-08-08 |
| Payment account chain | Cash, M-PESA, bank transfer, and cheque configuration | Active tenant-owned receiving account resolves with optional settlement, clearing, and default GL accounts. | Configuration, inactive account handling, tenant rejection, and audit event tests pass. | PASS | Automated suite | 2026-08-08 |
| Payment account chain | Reconciliation readiness | Completed fee receipts reconcile against receiving-account GL movement and expose settlement/clearing movement. | Tenant/date-scoped reconciliation route and service tests pass. | PASS | Automated suite | 2026-08-08 |
| Receipt processing | Manual, M-PESA, bank, and cheque receipt | A configured mode, valid reference, amount, tenant student, term, and account chain are required. | Payment validation and configured-account tests pass. | PASS | Automated suite | 2026-08-08 |
| Receipt processing | Automatic, manual, and mixed allocation | Manual lines cannot duplicate, exceed outstanding, or exceed receipt total; remainder follows priority allocation. | Allocation validation and workspace-preview tests pass. | PASS | Automated suite | 2026-08-08 |
| Receipt lifecycle | Reprint, transfer, reversal, archive, and repost | Immutable source history, allocation detail, actor/reason, original/replacement links, and correlation IDs remain traceable. | Lifecycle snapshot, route, archive/repost rollback, transfer, and correlation tests pass. | PASS | Automated suite | 2026-08-08 |
| Receipt discovery | Receipt search, register, and journal | Date, receipt/reference, admission, status, event, cashier, period, and tenant filters return only authorized records. | Register and report filter tests pass. | PASS | Automated suite | 2026-08-08 |
| Billing | Manual, individual, bulk, and replacement invoice | Tenant-scoped charges are posted idempotently; unsafe paid-allocation replacement is blocked. | Invoice, custom-votehead, bulk, preflight, and replacement tests pass. | PASS | Automated suite | 2026-08-08 |
| Financial corrections | Debit, credit, refund, waiver, and scholarship | Corrections preserve ledger/audit history and enforce available credit, votehead, category, and tenant constraints. | Debit/credit/refund and waiver/revocation/group tests pass. | PASS | Automated suite | 2026-08-08 |
| Student classification | Category, group, class, and stream | Current-term classification changes are validated and create linked invoice corrections where permitted. | Classification preflight and class correction tests pass. | PASS | Automated suite | 2026-08-08 |
| Statements | Student statement, ledger, and term summary | Ledger events classify correctly and student/term reads stay tenant-scoped. | Statement and term-summary service/route tests pass. | PASS | Automated suite | 2026-08-08 |
| Reports | Collections, receipt, revenue, ledger, lifecycle, reallocation, replacement, waiver, cashier, and reconciliation | Filters, grouping, tenant boundaries, empty result behavior, and CSV output agree with their HTML queries. | Report query/filter/export tests pass. | PASS | Automated suite | 2026-08-08 |
| Security | Permissions, tenant isolation, audit trail, correlation IDs | Privileged actions require authorization; cross-tenant data cannot be selected or mutated. | Route permission and tenant-scoping tests pass. | PASS | Automated suite | 2026-08-08 |
| Accounting | Allocation integrity, chronological balances, and outstanding balance | Reallocations rebuild both students' balances; corrections and failed posts are atomic. | Balance-rebuild, rollback, manual-allocation, and refund tests pass. | PASS | Automated suite | 2026-08-08 |
| Migration | Preflight and idempotency | Pending migration files are syntactically/preflight validated and schema safeguards are checked. | Migration preflight suite passes. | PASS | Automated suite | 2026-08-08 |
| Migration | Production-like apply, rollback, backup, and restore | Migration journal, data integrity, and restoration are verified against an approved target copy. | No target database is available in this workspace. | PENDING TARGET VALIDATION | Release Manager | Pending |
| User acceptance | Bursar, accountant, principal, and auditor workflows | Supported browsers validate daily collections, corrections, reports, audit trails, and printed receipts. | Requires interactive UAT users, browser/tablet devices, and printer output. | PENDING TARGET VALIDATION | UAT Team | Pending |
| Deployment | Rehearsal and post-deployment verification | Approved target deploys the RC image; health and smoke checks pass. | Repository has image-publish automation but no configured deployment target. | PENDING TARGET VALIDATION | Operations | Pending |