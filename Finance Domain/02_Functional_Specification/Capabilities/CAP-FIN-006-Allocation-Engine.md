# CAP-FIN-006: Allocation Engine

## Purpose
Allocate payments to invoices and voteheads using deterministic, policy-driven strategies.

## Owner
- Primary: AR Platform Lead
- Secondary: Finance Services Architect

## Business Goal
Reduce manual reconciliation effort and enforce consistent allocation outcomes.

## Stakeholders
- Bursar
- Finance Manager
- Auditor
- Support

## Dependencies
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-007

## Business Rules
- BR-FIN-038
- BR-FIN-039
- BR-FIN-040

## Workflows
- WF-FIN-036 Auto Allocation
- WF-FIN-037 Manual Reallocation with Approval

## Database Objects
- DB-FIN-058 AllocationPolicySet
- DB-FIN-059 AllocationDecision
- DB-FIN-060 ReallocationRequest

## Services and Use Cases
- AllocationPolicyResolver
- AllocationPreviewService
- AllocationApplyService
- ReallocationService

## Events
- EVT-FIN-032 AllocationDecisionApplied
- EVT-FIN-033 ReallocationRequested

## API Endpoints
- API-FIN-V1-120 POST /api/v1/allocations/preview
- API-FIN-V1-121 POST /api/v1/allocations/apply

## Permissions
- PERM-FIN-120 ApplyAllocation
- PERM-FIN-121 ReallocateWithApproval

## Notifications
- NOTIF-FIN-029 Reallocation approval requested

## Reports
- REP-FIN-026 Allocation Exceptions Register

## KPIs
- KPI-FIN-026 First-pass allocation rate

## Performance Targets
- PERF-FIN-024 allocation preview under 1s p95

## Security Requirements
- SEC-FIN-023

## Acceptance Criteria
- AC-FIN-120
- AC-FIN-121
- AC-FIN-122

## Test Cases
- TEST-FIN-120
- TEST-FIN-121
- TEST-FIN-122

## Migration Notes
Use shadow-allocation mode first to compare old vs new allocation decisions before enforcing the new engine.

## Open Risks
- RISK-FIN-022

## ADR Links
- ADR-FIN-024 Allocation precedence policy
- ADR-FIN-025 Reallocation approval thresholds
