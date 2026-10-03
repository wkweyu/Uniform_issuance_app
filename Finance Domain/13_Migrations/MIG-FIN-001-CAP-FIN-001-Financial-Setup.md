# MIG-FIN-001 Financial Setup Schema

- Migration ID: MIG-FIN-001
- Capability: CAP-FIN-001
- Owner: Finance Engineering Lead
- Date: 2026-07-22
- Wave: Wave-1

## Objective
Create and populate canonical financial configuration tables referenced by all downstream capabilities.

## Change Type
- Additive schema

## Database Objects
- DB-FIN-001 AcademicYear
- DB-FIN-002 Term
- DB-FIN-003 FeeCategory
- DB-FIN-004 Votehead
- DB-FIN-005 BankAccount
- DB-FIN-006 PaymentMethod
- DB-FIN-007 ReceiptSeries
- DB-FIN-008 AllocationPolicy
- DB-FIN-009 PenaltyPolicy
- DB-FIN-010 FinancialPolicy
- DB-FIN-011 PeriodLock
- DB-FIN-012 ExchangeRate

## Steps
1. Create migration script `v001__financial_setup_schema.sql`.
2. Add tables with FK constraints, unique indexes, and audit columns (created_by, updated_by, created_at, updated_at, tenant_id).
3. Seed initial AcademicYear and Term rows from existing data source.
4. Seed ReceiptSeries with current receipt prefix and counter values.
5. Run data parity check between legacy config and new tables.
6. Enable application compatibility wrapper to read from new tables.
7. Run dual-read smoke test (compare legacy vs canonical for 100 random config queries).
8. Decommission legacy config reads after two-sprint stability window.

## Rollback Plan
Drop migration tables; existing application reads remain on legacy tables. No data loss — additive only.

## Validation
- Data parity checks: compare AcademicYear/Term count and IDs against legacy academic calendar.
- Tenant isolation checks: all rows must carry non-null tenant_id.
- Accounting integrity checks: PeriodLock records match current lock state in legacy system.

## Risks
- RISK-FIN-001: Configuration drift if legacy and canonical tables are both written during transition.
