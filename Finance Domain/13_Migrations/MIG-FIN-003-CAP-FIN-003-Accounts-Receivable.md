# MIG-FIN-003 Accounts Receivable Schema

- Migration ID: MIG-FIN-003
- Capability: CAP-FIN-003
- Owner: AR Engineering Lead
- Date: 2026-07-22
- Wave: Wave-1

## Objective
Establish canonical AR ledger, allocation, statement snapshot, and aging tables as the authoritative receivables subledger.

## Change Type
- Additive schema + Dual-write

## Database Objects
- DB-FIN-020 ARLedgerEntry
- DB-FIN-021 AllocationEntry
- DB-FIN-022 StatementSnapshot
- DB-FIN-023 AgingBucketSummary

## Steps
1. Create `v003__ar_schema.sql` — ARLedgerEntry linked to InvoiceHeader and PaymentTransaction via FKs.
2. Backfill ARLedgerEntry from existing finance_transactions and finance_ledger_entries tables.
3. Verify per-student outstanding balance matches legacy system for all active students.
4. Enable dual-write on payment receipt and reversal paths.
5. Shift statement generation to read from ARLedgerEntry after balance parity confirmation.
6. Run aging computation against canonical tables; compare to legacy aging report output.

## Rollback Plan
Disable canonical write path; revert statement generation to legacy queries. Drop tables — additive only.

## Validation
- Data parity checks: per-student balance from ARLedgerEntry matches legacy outstanding balance.
- Tenant isolation checks: all ledger entries carry tenant_id.
- Accounting integrity checks: sum(debit) - sum(credit) per student = reported outstanding balance.

## Risks
- RISK-FIN-005: Historical reversal entries may have inconsistent references in legacy data.
- RISK-FIN-006: Allocation backfill ordering is sensitive to payment date sequencing.
