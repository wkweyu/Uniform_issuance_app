# Finance Phase 1 RC1 Release Notes

Release: Finance Phase 1 RC1

Date: 2026-08-08

## New Features

- Tenant-scoped bursar workspace with student context, payment posting, allocation preview, recent receipt actions, and keyboard-assisted cashier workflows.
- Automatic, manual, and mixed votehead allocation with reusable tenant-scoped templates and server-side live outstanding-balance validation.
- Audited receipt lifecycle management: printing/reprinting, cancellation/reversal, transfer/reallocation, archive, and repost with correlation links and immutable history.
- Cashier session controls for opening float, expected cash, counted cash, variance approval, session locking, reopening, and session reporting.
- Payment-mode account-chain configuration for receiving, settlement, clearing, and default GL accounts, including account-chain reconciliation visibility.
- Debit notes, credit notes, refunds, waivers, scholarships, individual/bulk invoicing, classification-driven invoice replacement, student statements, term summaries, and Finance reports.
- CSV exports for collection, revenue, ledger, receipt lifecycle, reallocation, invoice replacement, waiver, and receipt-register reports.

## Business Improvements

- Fee reports use tenant-owned period and dependent selectors, and exports reuse the same filtered data as their screen reports.
- Receipt detail and printed output include resolved receiving-account information and votehead allocation detail.
- Receipt transfer and correction paths rebuild chronological balances while retaining the immutable original audit chain.

## Bug Fixes

- Hardened report filter validation and tenant-scoped joins for receipt lifecycle, reallocation, revenue, ledger, invoice replacement, waiver, and receipt-register reporting.
- Added reconciliation variance visibility between completed fee receipts and configured receiving-account GL movement.

## Database Changes

- `044_fee_refunds.sql`: fee refund support.
- `045_fee_invoice_replacement_class_audit.sql`: classification-change invoice audit support.
- `046_cashier_session_completion.sql`: cashier-session completion and control support.
- `047_payment_mode_account_chain.sql`: settlement, clearing, default-GL account-chain fields and configuration events.

## Migration Notes

1. Back up the target database.
2. Run `python migrate_db.py --status` with target database environment variables.
3. Apply pending migrations with `python migrate_db.py` only after reviewing status and backup evidence.
4. Rerun `--status`; all applied files must show `APPLIED` with matching checksums.
5. Retain migration output, backup identifier, and post-migration health-check evidence in the release record.

## Deployment Notes

- The release has automated regression and migration-preflight evidence, but production deployment remains conditional on an approved target, a production-like migration rehearsal, backup/restore validation, browser/tablet smoke tests, and post-deployment health checks.
- The existing GitHub workflow publishes the container image on `main`; it does not deploy to a production environment.

## Known Limitations

- Physical receipt printing and supported-browser/tablet validation are pending target-environment UAT.
- Production data-volume response-time acceptance thresholds have not yet been recorded.
- The unrelated root-suite attendance/tenancy fixture and platform UI assertion failures are recorded as TD-005; they do not affect the Finance RC1 regression result.

## Breaking Changes

None intended. Existing raw-PyMySQL fee-ledger ownership, tenant boundaries, receipt numbering, audit history, and reversal-only correction policy remain unchanged.