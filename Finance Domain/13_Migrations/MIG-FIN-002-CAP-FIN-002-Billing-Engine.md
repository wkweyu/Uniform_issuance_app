# MIG-FIN-002 Billing Engine Schema

- Migration ID: MIG-FIN-002
- Capability: CAP-FIN-002
- Owner: Billing Engineering Lead
- Date: 2026-07-22
- Wave: Wave-1

## Objective
Introduce canonical billing tables for invoices, plans, and credit/debit notes that replace legacy fee_structures and student_billing tables.

## Change Type
- Additive schema + Dual-write

## Database Objects
- DB-FIN-013 InvoiceHeader
- DB-FIN-014 InvoiceLine
- DB-FIN-015 BillingPlan
- DB-FIN-016 RecurringSchedule
- DB-FIN-017 DebitNote
- DB-FIN-018 CreditNote
- DB-FIN-019 InstallmentPlan

## Steps
1. Create `v002__billing_engine_schema.sql` — tables with tenant_id, FK to AcademicYear/Term/Votehead.
2. Backfill InvoiceHeader and InvoiceLine from existing invoices/fees tables using ETL script.
3. Validate invoice count and total amount match between legacy and canonical tables.
4. Enable dual-write: new billing operations write to both legacy and canonical.
5. Shift read path to canonical InvoiceHeader after parity confirmation.
6. Decommission legacy write path after two-sprint stability window.

## Rollback Plan
Disable dual-write; all reads revert to legacy tables. Drop canonical tables if needed — no side effects.

## Validation
- Data parity checks: invoice count and sum(amount) per student per term match legacy.
- Tenant isolation checks: tenant_id non-null on all rows.
- Accounting integrity checks: sum of InvoiceLine amounts equals InvoiceHeader total.

## Risks
- RISK-FIN-004: Backfill may miss edge-case invoices from historical bulk imports.
