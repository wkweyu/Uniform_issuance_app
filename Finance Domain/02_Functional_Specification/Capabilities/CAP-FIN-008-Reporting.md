# CAP-FIN-008: Reporting

## Purpose
Deliver trusted finance operational and compliance reports from canonical posting sources.

## Owner
- Primary: Reporting Product Lead
- Secondary: Data Platform Lead

## Business Goal
Replace fragmented report logic with governed read models and consistent export controls.

## Stakeholders
- Bursar
- Finance Manager
- Principal
- Board
- Auditors

## Dependencies
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-006
- CAP-FIN-007
- CAP-FIN-011

## Business Rules
- BR-FIN-041
- BR-FIN-042

## Workflows
- WF-FIN-038 Report Build
- WF-FIN-039 Report Export and Share

## Database Objects
- DB-FIN-061 ReportDefinition
- DB-FIN-062 ReportSnapshot
- DB-FIN-063 ReportExportLog

## Services and Use Cases
- ReportQueryService
- ReportSnapshotService
- ReportExportService
- ReportAccessPolicyService

## Events
- EVT-FIN-034 ReportExportCompleted

## API Endpoints
- API-FIN-V1-130 GET /api/v1/reports/{report_id}
- API-FIN-V1-131 POST /api/v1/reports/{report_id}/export

## Permissions
- PERM-FIN-130 ViewReport
- PERM-FIN-131 ExportReport

## Notifications
- NOTIF-FIN-030 Report export ready

## Reports
- REP-FIN-027 Collections Dashboard Feed
- REP-FIN-028 Defaulters Portfolio
- REP-FIN-029 Forecast Input Pack

## KPIs
- KPI-FIN-027 Report freshness SLA

## Performance Targets
- PERF-FIN-025 standard report render under 5s

## Security Requirements
- SEC-FIN-024

## Acceptance Criteria
- AC-FIN-130
- AC-FIN-131

## Test Cases
- TEST-FIN-130
- TEST-FIN-131

## Migration Notes
Progressively repoint existing report templates to canonical read models while retaining output parity checks.

## Open Risks
- RISK-FIN-023

## ADR Links
- ADR-FIN-026 Report model versioning policy
- ADR-FIN-027 Export watermarking standard
