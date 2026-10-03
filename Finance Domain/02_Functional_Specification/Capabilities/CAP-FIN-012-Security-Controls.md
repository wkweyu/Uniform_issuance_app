# CAP-FIN-012: Security Controls

## Purpose
Enforce high-risk financial controls and segregation-of-duties protections across finance operations.

## Owner
- Primary: Security Lead
- Secondary: Finance Controls Lead

## Business Goal
Reduce fraud and operational risk through preventive, detective, and approval-based controls.

## Stakeholders
- Security Team
- Finance Manager
- Principal
- Compliance
- Internal Audit

## Dependencies
- CAP-FIN-001
- CAP-FIN-007
- CAP-FIN-010
- CAP-FIN-011

## Business Rules
- BR-FIN-021
- BR-FIN-022
- BR-FIN-023

## Workflows
- WF-FIN-019 Step-up Authentication
- WF-FIN-020 Dual Approval Enforcement
- WF-FIN-021 Control Exception Escalation

## Database Objects
- DB-FIN-035 ControlPolicy
- DB-FIN-036 StepUpChallenge
- DB-FIN-037 SoDViolationLog

## Services and Use Cases
- SecurityControlService
- StepUpAuthService
- SoDPolicyService
- ControlExceptionService

## Events
- EVT-FIN-019 StepUpChallengeIssued
- EVT-FIN-020 SoDViolationDetected

## API Endpoints
- API-FIN-V1-060 POST /api/v1/security/step-up/challenge
- API-FIN-V1-061 POST /api/v1/security/control-evaluate
- API-FIN-V1-062 GET /api/v1/security/violations

## Permissions
- PERM-FIN-060 ConfigureControls
- PERM-FIN-061 ApproveHighRiskAction
- PERM-FIN-062 ViewSecurityViolations

## Notifications
- NOTIF-FIN-017 High-risk action challenge
- NOTIF-FIN-018 SoD violation alert

## Reports
- REP-FIN-015 Security Control Effectiveness
- REP-FIN-016 SoD Violations Register

## KPIs
- KPI-FIN-015 Step-up success rate
- KPI-FIN-016 SoD violation closure time

## Performance Targets
- PERF-FIN-013 step-up challenge issuance under 1s
- PERF-FIN-014 control evaluation under 300ms

## Security Requirements
- SEC-FIN-001
- SEC-FIN-005
- SEC-FIN-013

## Acceptance Criteria
- AC-FIN-060
- AC-FIN-061
- AC-FIN-062

## Test Cases
- TEST-FIN-060
- TEST-FIN-061
- TEST-FIN-062

## Migration Notes
Introduce sidecar control evaluation before hard-fail enforcement mode in production.

## Open Risks
- RISK-FIN-011
- RISK-FIN-012

## ADR Links
- ADR-FIN-013 Step-up policy thresholds
- ADR-FIN-014 SoD enforcement model
