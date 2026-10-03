# CAP-FIN-001: Financial Setup

## Purpose
Centralize and govern financial configuration used by all downstream finance capabilities.

## Owner
- Primary: Finance Product Owner
- Secondary: Finance Engineering Lead

## Business Goal
Eliminate configuration drift and enforce policy-consistent billing and posting behavior across schools.

## Stakeholders
- Bursar
- Finance Manager
- Principal
- School Admin
- Compliance
- Support

## Dependencies
- CAP-FIN-008
- CAP-FIN-010
- CAP-FIN-011
- CAP-FIN-012

## Business Rules
- BR-FIN-001
- BR-FIN-006
- BR-FIN-009
- BR-FIN-010

## Workflows
- WF-FIN-001 Maintain Financial Calendar
- WF-FIN-002 Maintain Voteheads
- WF-FIN-003 Period Lock and Unlock

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

## Services and Use Cases
- SetupPolicyService
- CalendarService
- VoteheadService
- PeriodLockService
- ReceiptSeriesService

## Events
- EVT-FIN-009 FinancialPeriodLocked
- EVT-FIN-010 FinancialPolicyChanged
- EVT-FIN-011 ReceiptSeriesUpdated

## API Endpoints
- API-FIN-V1-001 GET /api/v1/finance/setup
- API-FIN-V1-002 POST /api/v1/finance/setup/period-lock
- API-FIN-V1-003 POST /api/v1/finance/setup/voteheads

## Permissions
- PERM-FIN-001 ViewSetup
- PERM-FIN-002 EditSetup
- PERM-FIN-003 LockPeriod
- PERM-FIN-004 UnlockPeriod

## Notifications
- NOTIF-FIN-009 Financial period lock notice
- NOTIF-FIN-010 Policy change alert

## Reports
- REP-FIN-011 Setup Audit Register
- REP-FIN-012 Lock and Unlock History

## KPIs
- KPI-FIN-001 Setup change lead time
- KPI-FIN-002 Lock override rate

## Performance Targets
- PERF-FIN-003 search configuration under 500ms p95
- PERF-FIN-005 lock action under 2s p95

## Security Requirements
- SEC-FIN-002
- SEC-FIN-006

## Acceptance Criteria
- AC-FIN-001
- AC-FIN-002
- AC-FIN-003

## Test Cases
- TEST-FIN-001
- TEST-FIN-002
- TEST-FIN-003
- TEST-FIN-004

## Migration Notes
Start with compatibility wrappers; preserve existing setup routes while writing setup changes to canonical config objects.

## Open Risks
- RISK-FIN-001
- RISK-FIN-003

## ADR Links
- ADR-FIN-001 Immutable config audit
- ADR-FIN-002 Effective dating policy
