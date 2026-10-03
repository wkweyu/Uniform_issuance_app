# MIG-FIN-006 Audit and Compliance Schema

- Migration ID: MIG-FIN-006
- Capability: CAP-FIN-011
- Owner: Compliance Engineering Lead
- Date: 2026-07-22
- Wave: Wave-1

## Objective
Introduce canonical audit event and evidence tables providing immutable, tenant-isolated audit trails for all finance operations.

## Change Type
- Additive schema

## Database Objects
- DB-FIN-032 AuditEvent
- DB-FIN-033 EvidenceAttachment
- DB-FIN-034 AuditExportJob

## Steps
1. Create `v006__audit_compliance_schema.sql` — AuditEvent with append-only enforcement (no UPDATE/DELETE permissions granted to app role).
2. Add write triggers on PaymentTransaction, JournalHeader, and PeriodLock to emit AuditEvent rows.
3. Backfill AuditEvent from existing audit_logs for last 24 months.
4. Validate AuditEvent count and actor fields match legacy audit_logs for a sampled date range.
5. Enable compliance export path from AuditEvent.
6. Enforce retention policy on AuditEvent (archive rows older than configured retention window).

## Rollback Plan
Remove triggers; revert compliance export to legacy audit_logs queries. AuditEvent table can be dropped — no consumer FKs yet.

## Validation
- Data parity checks: AuditEvent count for sampled payment and reversal operations matches legacy audit_logs.
- Tenant isolation checks: tenant_id non-null on all rows; cross-tenant query returns zero rows.
- Accounting integrity checks: every PaymentTransaction and JournalHeader has at least one linked AuditEvent.

## Risks
- RISK-FIN-009: Backfill may not recover actor attribution for entries older than 24 months in legacy logs.
- RISK-FIN-010: Trigger overhead on high-volume payment tables must be load-tested.
