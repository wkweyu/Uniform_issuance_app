# Finance Phase 1 RC1 Release Checklist

Release candidate: Finance Phase 1 RC1

Certification date: 2026-08-08

Release scope: Existing tenant-scoped Finance Phase 1 capabilities only. No feature, schema, API, ledger, allocation, receipt-numbering, audit-model, or workflow redesign is included in this certification batch.

## Business Features

| Check | Status | Evidence |
| --- | --- | --- |
| Bursar workspace and student context | PASS | Route/template regression coverage includes student context, safe AJAX failures, receipts, alerts, and cashier shortcuts. |
| Receipt posting and allocation | PASS | Automated coverage includes automatic, manual, mixed, partial, remainder-priority, duplicate votehead, and over-allocation rejection paths. |
| Receipt lifecycle and correction | PASS | Cancellation, reversal, archive, repost, transfer, reprint, immutable snapshots, and correlation links are covered. |
| Billing, corrections, waivers, refunds, and classification | PASS | Invoice, replacement, debit/credit, refund, waiver/revocation, group waiver, and classification preflight coverage passes. |
| Cashier sessions | PASS | Open, close, expected cash, variance, approval, locking, reopening, session register, and audit events are covered. |
| Payment account chain | PASS | Tenant-scoped receiving, settlement, clearing, and default-GL configuration plus account activity validation and audit events are covered. |

## Reports

| Check | Status | Evidence |
| --- | --- | --- |
| Collections, receipt register, journal, revenue, ledger, lifecycle, reallocation, invoice replacement, and waiver reports | PASS | Route and service coverage validates filters, tenant-owned selectors, accounting-period rules, lifecycle data, and empty-safe result paths. |
| CSV exports | PASS | Collection, revenue, ledger, lifecycle, reallocation, replacement, waiver, and receipt-register export response contracts are covered. |
| Print layouts | PENDING TARGET VALIDATION | Browser and physical-printer validation is required for each supported payment mode. |
| Pagination and production-size response time | PENDING TARGET VALIDATION | Requires production-like data volume and browser execution. |

## Testing And Security

| Check | Status | Evidence |
| --- | --- | --- |
| Finance regression suite | PASS | `366 passed` on 2026-08-08: `tests/test_blueprint_route_integration.py`, `tests/test_procurement_inventory_isolation.py`, and `tests/test_migration_preflight.py`. |
| Tenant isolation | PASS | Service and route tests verify school-scoped joins, selectors, foreign-record rejection, and report filters. |
| Audit and correlation identity | PASS | Lifecycle, reallocation, archive/repost, cashier-session, and payment-account event coverage passes. |
| Diff hygiene | PASS | `git diff --check` passed for the Finance Phase 1 release batch. |
| Browser, tablet, and accessibility validation | PENDING TARGET VALIDATION | Must be completed in supported browsers with the UAT environment. |

## Operations And Deployment

| Check | Status | Required closure |
| --- | --- | --- |
| Migration preflight and idempotency unit checks | PASS | `tests/test_migration_preflight.py` passes. |
| Production-like migration rehearsal | PENDING RELEASE GATE | Run `migrate_db.py --status`, apply pending migrations to a restored production-like backup, rerun status, and retain the migration journal output. |
| Rollback rehearsal | PENDING RELEASE GATE | Restore the rehearsal backup; verify ledger, receipt lifecycle, cashier-session, and payment-account records. |
| Backup and restore rehearsal | PENDING RELEASE GATE | Record backup creation, restore completion, and post-restore integrity queries in the release record. |
| Deployment rehearsal and post-deployment health check | PENDING RELEASE GATE | Deploy to the approved target, run `/health`, execute smoke scenarios, and record the image/version and timestamp. |

## Sign-off

Finance Phase 1 RC1 is ready for UAT after the pending target-environment release gates are executed and recorded. It is not certified for production deployment until those gates pass.

| Role | Name | Decision | Date | Evidence reference |
| --- | --- | --- | --- | --- |
| Lead ERP Finance Engineer | Pending | Pending | Pending | FINANCE_CERTIFICATION_MATRIX.md |
| Finance Product Owner | Pending | Pending | Pending | UAT record |
| Operations / Release Manager | Pending | Pending | Pending | Deployment rehearsal record |