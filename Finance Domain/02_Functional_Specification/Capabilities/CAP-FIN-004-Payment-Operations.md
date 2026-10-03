# CAP-FIN-004: Payment Operations

## Purpose
Provide a unified payment operations orchestration layer for capture, validation, reconciliation, and state transitions.

## Owner
- Primary: Payment Product Lead
- Secondary: Integrations Lead

## Business Goal
Standardize payment processing behavior across channels while preserving strict controls and traceability.

## Stakeholders
- Bursar
- Parents
- Finance Manager
- Integrations Team
- Support

## Dependencies
- CAP-FIN-003
- CAP-FIN-007
- CAP-FIN-010
- CAP-FIN-017
- CAP-FIN-018

## Business Rules
- BR-FIN-008
- BR-FIN-013
- BR-FIN-014
- BR-FIN-015

## Workflows
- WF-FIN-010 Receive External Callback
- WF-FIN-011 Manual Cash Entry
- WF-FIN-012 Reconciliation Exception Resolution

## Database Objects
- DB-FIN-024 PaymentTransaction
- DB-FIN-025 PaymentRailReference
- DB-FIN-026 ReconciliationCase
- DB-FIN-027 SettlementBatch

## Services and Use Cases
- PaymentOrchestratorService
- CallbackValidationService
- ReconciliationService
- SettlementService

## Events
- EVT-FIN-003 PaymentReceived
- EVT-FIN-013 PaymentCallbackValidated
- EVT-FIN-014 ReconciliationCaseOpened

## API Endpoints
- API-FIN-V1-030 POST /api/v1/payments/callbacks/{provider}
- API-FIN-V1-031 POST /api/v1/payments/manual
- API-FIN-V1-032 GET /api/v1/payments/reconciliation-cases

## Permissions
- PERM-FIN-030 CapturePayment
- PERM-FIN-031 ResolveReconciliationCase
- PERM-FIN-032 OverridePaymentMatch

## Notifications
- NOTIF-FIN-004 MPESA payment received
- NOTIF-FIN-005 Cheque bounced
- NOTIF-FIN-012 Reconciliation exception assigned

## Reports
- REP-FIN-005 Payment Method Distribution
- REP-FIN-006 Unreconciled Payments

## KPIs
- KPI-FIN-008 Payment success rate
- KPI-FIN-009 Auto-match ratio
- KPI-FIN-010 Reconciliation turnaround time

## Performance Targets
- PERF-FIN-007 callback processing under 1.5s p95
- PERF-FIN-008 reconciliation worklist refresh under 2s p95

## Security Requirements
- SEC-FIN-008
- SEC-FIN-009

## Acceptance Criteria
- AC-FIN-030
- AC-FIN-031
- AC-FIN-032

## Test Cases
- TEST-FIN-030
- TEST-FIN-031
- TEST-FIN-032
- TEST-FIN-033

## Migration Notes
Maintain existing MPESA reconciliation routes while introducing provider-agnostic adapters and callback policies.

## Open Risks
- RISK-FIN-004
- RISK-FIN-007

## ADR Links
- ADR-FIN-007 Payment idempotency contract
- ADR-FIN-008 Provider adapter interface
- ADR-FIN-023 CAP-004 and CAP-005 scope alignment
