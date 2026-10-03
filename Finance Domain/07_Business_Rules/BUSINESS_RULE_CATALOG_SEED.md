# Business Rule Catalog Seed

## Rule Template
- Rule ID: BR-FIN-###
- Statement:
- Scope:
- Priority:
- Effective Date:
- Override Policy:
- Audit Requirement: AUD-FIN-###
- Acceptance: AC-FIN-###
- Tests: TEST-FIN-###

## Seed Rules (Core)
1. BR-FIN-001 Receipt numbers are unique within a school and financial year.
2. BR-FIN-002 Posted journals cannot be edited.
3. BR-FIN-003 Corrections require reversal entries.
4. BR-FIN-004 Outstanding balance equals debits minus credits.
5. BR-FIN-005 Every payment allocates to one or more invoice lines.
6. BR-FIN-006 No posting into locked financial periods.
7. BR-FIN-007 Invoice regeneration requires superseded linkage.
8. BR-FIN-008 Payment reference uniqueness is per school and rail.

## Governance
- Rule precedence conflicts require ADR-FIN entry.
- Approved rules must be linked to traceability and tests.
