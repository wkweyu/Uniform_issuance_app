# CAP-FIN-010: Workflow Engine

## Purpose
Coordinate multi-step finance processes with explicit states, approvals, retries, SLAs, and compensating actions.

## Owner
- Primary: Finance Orchestration Product Lead
- Secondary: Platform Workflow Architect

## Business Goal
Eliminate ad-hoc, manual process handling by formalizing finance workflows as governed state machines.

## Stakeholders
- Bursar
- Finance Manager
- Approvers
- Compliance Team
- Support

## Dependencies
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-011
- CAP-FIN-016
- CAP-FIN-018

## Business Rules
- BR-FIN-024
- BR-FIN-025

## Workflows
- WF-FIN-022 Payment Reversal Approval Workflow
- WF-FIN-023 Invoice Waiver Workflow
- WF-FIN-024 Settlement Exception Escalation

## Database Objects
- DB-FIN-067 WorkflowDefinition
- DB-FIN-068 WorkflowInstance
- DB-FIN-069 WorkflowStepExecution
- DB-FIN-070 WorkflowApprovalRecord

## Services and Use Cases
- WorkflowDefinitionService
- WorkflowInstanceService
- WorkflowStepExecutor
- WorkflowEscalationService

## Events
- EVT-FIN-022 WorkflowStepTimedOut
- EVT-FIN-023 WorkflowInstanceCompleted

## API Endpoints
- API-FIN-V1-142 POST /api/v1/workflows/instances
- API-FIN-V1-143 POST /api/v1/workflows/instances/{instance_id}/actions
- API-FIN-V1-144 GET /api/v1/workflows/instances/{instance_id}

## Permissions
- PERM-FIN-142 StartWorkflow
- PERM-FIN-143 ApproveWorkflowStep
- PERM-FIN-144 ViewWorkflowTrail

## Notifications
- NOTIF-FIN-033 Approval task assigned
- NOTIF-FIN-034 Workflow SLA breach alert

## Reports
- REP-FIN-031 Workflow SLA Compliance Register
- REP-FIN-032 Approval Cycle Time Report

## KPIs
- KPI-FIN-030 Workflow completion within SLA
- KPI-FIN-031 Average approval turnaround time

## Performance Targets
- PERF-FIN-027 workflow state transition under 250ms p95

## Security Requirements
- SEC-FIN-014

## Acceptance Criteria
- AC-FIN-070: Workflow definitions are versioned and immutable once active.
- AC-FIN-071: Timeout, retry, and escalation policies execute without manual intervention.
- AC-FIN-072: Every state transition is auditable with actor, timestamp, and reason.

## Test Cases
- TEST-FIN-070 Workflow timeout and escalation handling
- TEST-FIN-071 Approval action authorization boundaries
- TEST-FIN-072 Workflow history reconstruction integrity

## Migration Notes
- Convert existing manual approval procedures into first-class workflow definitions.
- Map current open approval items into workflow instances with preserved provenance.

## Open Risks
- RISK-FIN-019: Poorly modeled states may cause hidden dead-ends.
- RISK-FIN-020: Escalation misconfiguration may generate notification noise.

## ADR Links
- ADR-FIN-024 Workflow state model and compensation strategy

