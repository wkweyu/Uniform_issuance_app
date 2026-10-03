# CAP-FIN-007: General Ledger

## Purpose
Enforce strict double-entry accounting and guarantee integrity of financial statements.

## Owner
- Primary: Finance Architecture Lead
- Secondary: GL Engineering Lead

## Business Goal
Ensure every financial event posts balanced journals and supports trusted trial balance and balance sheet outputs.

## Stakeholders
- Finance Manager
- Auditor
- Principal
- Board
- Compliance

## Dependencies
- CAP-FIN-002
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-011
- CAP-FIN-012

## Business Rules
- BR-FIN-002
- BR-FIN-003
- BR-FIN-016
- BR-FIN-017

## Workflows
- WF-FIN-013 Journal Posting
- WF-FIN-014 Journal Reversal
- WF-FIN-015 Period Close Validation

## Database Objects
- DB-FIN-028 JournalHeader
- DB-FIN-029 JournalLine
- DB-FIN-030 AccountMaster
- DB-FIN-031 TrialBalanceSnapshot

## Services and Use Cases
- GLPostingService
- JournalValidationService
- TrialBalanceService
- CloseReadinessService

## Events
- EVT-FIN-007 LedgerPosted
- EVT-FIN-015 JournalReversalPosted
- EVT-FIN-016 TrialBalanceGenerated

## API Endpoints
- API-FIN-V1-040 POST /api/v1/gl/journals/post
- API-FIN-V1-041 POST /api/v1/gl/journals/reverse
- API-FIN-V1-042 GET /api/v1/gl/trial-balance

## Permissions
- PERM-FIN-040 PostJournal
- PERM-FIN-041 ReverseJournal
- PERM-FIN-042 ViewTrialBalance

## Notifications
- NOTIF-FIN-013 Journal posting failed
- NOTIF-FIN-014 Period close blocked

## Reports
- REP-FIN-007 Trial Balance
- REP-FIN-008 Balance Sheet
- REP-FIN-009 Journal Exception Register

## KPIs
- KPI-FIN-011 Journal balance exception rate
- KPI-FIN-012 Close readiness score

## Performance Targets
- PERF-FIN-009 journal posting under 2s p95
- PERF-FIN-010 trial balance generation under 5s for current-term scope

## Security Requirements
- SEC-FIN-010
- SEC-FIN-011

## Acceptance Criteria
- AC-FIN-040
- AC-FIN-041
- AC-FIN-042

## Test Cases
- TEST-FIN-040
- TEST-FIN-041
- TEST-FIN-042
- TEST-FIN-043

## Migration Notes
Map existing finance_transactions and finance_ledger_entries into canonical JournalHeader and JournalLine contracts before hard cutover.

## Open Risks
- RISK-FIN-005
- RISK-FIN-008

## ADR Links
- ADR-FIN-009 Journal schema canonicalization
- ADR-FIN-010 Reversal reference policy
