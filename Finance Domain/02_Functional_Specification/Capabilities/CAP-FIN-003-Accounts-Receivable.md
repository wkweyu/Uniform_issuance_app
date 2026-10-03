# CAP-FIN-003: Accounts Receivable

## Purpose
Maintain receivables subledger, balances, allocations, statements, and aging.

## Owner
- Primary: AR Product Lead
- Secondary: Finance Services Lead

## Business Goal
Ensure accurate outstanding balances and transparent receivables lifecycle by student and school.

## Stakeholders
- Bursar
- Finance Manager
- Parent
- Principal
- Auditor

## Dependencies
- CAP-FIN-001
- CAP-FIN-002
- CAP-FIN-004
- CAP-FIN-005
- CAP-FIN-007

## Business Rules
- BR-FIN-002
- BR-FIN-003
- BR-FIN-004
- BR-FIN-005
- BR-FIN-008

## Workflows
- WF-FIN-007 Payment Allocation
- WF-FIN-008 Statement Generation
- WF-FIN-009 Aging Computation

## Database Objects
- DB-FIN-020 ARLedgerEntry
- DB-FIN-021 AllocationEntry
- DB-FIN-022 StatementSnapshot
- DB-FIN-023 AgingBucketSummary

## Services and Use Cases
- ARPostingService
- AllocationService
- StatementService
- AgingService

## Events
- EVT-FIN-003 PaymentReceived
- EVT-FIN-004 ReceiptIssued
- EVT-FIN-007 LedgerPosted
- EVT-FIN-008 StatementGenerated

## API Endpoints
- API-FIN-V1-020 POST /api/v1/payments
- API-FIN-V1-021 GET /api/v1/statements/{admno}
- API-FIN-V1-022 GET /api/v1/aging

## Permissions
- PERM-FIN-020 ReceivePayment
- PERM-FIN-021 ReallocatePayment
- PERM-FIN-022 ViewStatement
- PERM-FIN-023 ReverseReceipt

## Notifications
- NOTIF-FIN-002 Receipt issued
- NOTIF-FIN-003 Outstanding reminder
- NOTIF-FIN-008 Statement available

## Reports
- REP-FIN-002 Receipts Register
- REP-FIN-003 Aging Report
- REP-FIN-004 Defaulters List

## KPIs
- KPI-FIN-005 Collection rate
- KPI-FIN-006 DSO proxy by term
- KPI-FIN-007 Allocation exception rate

## Performance Targets
- PERF-FIN-001 receive payment under 2s p95
- PERF-FIN-002 statement generation under 3s
- PERF-FIN-004 collections report under 5s

## Security Requirements
- SEC-FIN-001
- SEC-FIN-003
- SEC-FIN-004

## Acceptance Criteria
- AC-FIN-020
- AC-FIN-021
- AC-FIN-022
- AC-FIN-023

## Test Cases
- TEST-FIN-020
- TEST-FIN-021
- TEST-FIN-022
- TEST-FIN-023
- TEST-FIN-024

## Migration Notes
Keep existing fees endpoints stable and move internals to AR service facade; enforce strict journal linkage in phased mode.

## Open Risks
- RISK-FIN-005
- RISK-FIN-006

## ADR Links
- ADR-FIN-005 Allocation priority strategy
- ADR-FIN-006 Statement snapshot policy
