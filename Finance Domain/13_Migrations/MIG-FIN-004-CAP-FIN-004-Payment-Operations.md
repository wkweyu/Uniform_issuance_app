# MIG-FIN-004 Payment Operations Schema

- Migration ID: MIG-FIN-004
- Capability: CAP-FIN-004
- Owner: Payments Engineering Lead
- Date: 2026-07-22
- Wave: Wave-1

## Objective
Introduce canonical payment, reconciliation, and settlement tables to replace ad-hoc mpesa_transactions and payment_logs structures.

## Change Type
- Additive schema + Dual-write

## Database Objects
- DB-FIN-024 PaymentTransaction
- DB-FIN-025 PaymentRailReference
- DB-FIN-026 ReconciliationCase
- DB-FIN-027 SettlementBatch

## Steps
1. Create `v004__payment_operations_schema.sql` with idempotency key unique index on (school_id, rail, reference).
2. Backfill PaymentTransaction from existing mpesa_transactions and cash_payments tables.
3. Verify payment count and total amounts match legacy by rail and date range.
4. Enable dual-write on all inbound callback and manual payment endpoints.
5. Shift reconciliation read path to ReconciliationCase.
6. Decommission legacy write paths after two-sprint stability window.

## Rollback Plan
Remove dual-write toggle; all operations revert to legacy tables. Canonical tables dropped — no FK deps yet.

## Validation
- Data parity checks: payment count and sum(amount) per rail per day match legacy.
- Tenant isolation checks: tenant_id present on all PaymentTransaction rows.
- Accounting integrity checks: each PaymentTransaction references an ARLedgerEntry debit.

## Risks
- RISK-FIN-007: MPESA callback duplicates in legacy data may create phantom rows during backfill.
