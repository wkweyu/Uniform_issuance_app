# CAP-FIN-011: Audit and Compliance

## Purpose
Guarantee complete, immutable, and exportable evidence trails for financial operations and approvals.

## Owner
- Primary: Compliance Lead
- Secondary: Platform Audit Lead

## Business Goal
Satisfy internal and external audit requirements with tamper-evident, searchable records.

## Stakeholders
- Auditors
- Compliance
- Finance Manager
- Security Team

## Dependencies
- CAP-FIN-001
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-007
- CAP-FIN-012

## Business Rules
- BR-FIN-018
- BR-FIN-019
- BR-FIN-020

## Workflows
- WF-FIN-016 Evidence Capture
- WF-FIN-017 Audit Export
- WF-FIN-018 Retention and Archive

## Database Objects
- DB-FIN-032 AuditEvent
- DB-FIN-033 EvidenceAttachment
- DB-FIN-034 AuditExportJob

## Services and Use Cases
- AuditEvidenceService
- ComplianceExportService
- RetentionPolicyService

## Events
- EVT-FIN-017 AuditEvidenceCaptured
- EVT-FIN-018 RetentionPolicyExecuted

## API Endpoints
- API-FIN-V1-050 GET /api/v1/audit/events
- API-FIN-V1-051 POST /api/v1/audit/exports
- API-FIN-V1-052 GET /api/v1/audit/evidence/{id}

## Permissions
- PERM-FIN-050 ViewAudit
- PERM-FIN-051 ExportAudit
- PERM-FIN-052 ViewSensitiveEvidence

## Notifications
- NOTIF-FIN-015 Audit export ready
- NOTIF-FIN-016 Compliance retention failure

## Reports
- REP-FIN-010 Audit Trail Register
- REP-FIN-014 Compliance Exceptions

## KPIs
- KPI-FIN-013 Audit coverage ratio
- KPI-FIN-014 Evidence retrieval SLA adherence

## Performance Targets
- PERF-FIN-011 audit query under 3s
- PERF-FIN-012 audit export under 60s for standard window

## Security Requirements
- SEC-FIN-004
- SEC-FIN-012

## Acceptance Criteria
- AC-FIN-050
- AC-FIN-051
- AC-FIN-052

## Test Cases
- TEST-FIN-050
- TEST-FIN-051
- TEST-FIN-052

## Migration Notes
Bridge existing audit_logs and audit_records streams into unified audit event envelope.

## Open Risks
- RISK-FIN-009
- RISK-FIN-010

## ADR Links
- ADR-FIN-011 Audit envelope schema
- ADR-FIN-012 Retention tier policy
