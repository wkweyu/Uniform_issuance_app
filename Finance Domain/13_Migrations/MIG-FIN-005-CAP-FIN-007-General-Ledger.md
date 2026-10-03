# MIG-FIN-005 General Ledger Schema

- Migration ID: MIG-FIN-005
- Capability: CAP-FIN-007
- Owner: Finance Architecture Lead
- Date: 2026-07-22
- Wave: Wave-1

## Objective
Establish canonical double-entry GL tables and migrate existing finance_transactions into balanced journal entries.

## Change Type
- Additive schema + Backfill + Dual-write

## Database Objects
- DB-FIN-028 JournalHeader
- DB-FIN-029 JournalLine
- DB-FIN-030 AccountMaster
- DB-FIN-031 TrialBalanceSnapshot

## Steps
1. Create `v005__general_ledger_schema.sql` — enforce (sum of debit = sum of credit) check constraint per JournalHeader via trigger.
2. Seed AccountMaster from existing chart-of-accounts configuration.
3. Backfill JournalHeader/JournalLine from finance_transactions using canonical mapping rules.
4. Validate TrialBalance from canonical GL matches legacy trial balance report for current term.
5. Enable dual-write: every payment, reversal, and billing event writes a canonical journal.
6. Shift trial balance and balance sheet reports to canonical GL after parity confirmation.

## Rollback Plan
Disable dual-write trigger; revert reports to legacy queries. Canonical GL tables can be dropped — no consumer FKs yet.

## Validation
- Data parity checks: canonical trial balance totals match legacy trial balance by account code.
- Tenant isolation checks: all journal entries carry tenant_id.
- Accounting integrity checks: every JournalHeader has debit_total = credit_total; no orphan JournalLines.

## Risks
- RISK-FIN-008: Legacy transactions may lack account code mappings, requiring manual resolution before backfill.
