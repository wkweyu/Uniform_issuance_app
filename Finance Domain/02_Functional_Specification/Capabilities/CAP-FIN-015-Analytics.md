# CAP-FIN-015: Analytics

## Purpose
Provide decision-grade finance insights, trends, and forecasting beyond static operational reports.

## Owner
- Primary: Finance Analytics Lead
- Secondary: Data Science Platform Lead

## Business Goal
Improve planning, intervention design, and recovery outcomes through reliable KPI and forecast intelligence.

## Stakeholders
- Finance Manager
- Principal
- Board
- Collections Team
- Reporting and Data Teams

## Dependencies
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-007
- CAP-FIN-008
- CAP-FIN-018

## Business Rules
- BR-FIN-049
- BR-FIN-050

## Workflows
- WF-FIN-046 KPI Pipeline Refresh
- WF-FIN-047 Forecast Generation

## Database Objects
- DB-FIN-091 KpiDefinition
- DB-FIN-092 KpiSnapshot
- DB-FIN-093 ForecastModelRun
- DB-FIN-094 ForecastInputSnapshot

## Services and Use Cases
- KpiComputationService
- ForecastExecutionService
- AnalyticsQueryService
- ForecastGovernanceService

## Events
- EVT-FIN-039 ForecastRunCompleted

## API Endpoints
- API-FIN-V1-170 GET /api/v1/analytics/kpis
- API-FIN-V1-171 GET /api/v1/analytics/forecast
- API-FIN-V1-172 POST /api/v1/analytics/forecast/run

## Permissions
- PERM-FIN-170 ViewAnalytics
- PERM-FIN-171 ManageForecastModel

## Notifications
- NOTIF-FIN-035 KPI anomaly alert
- NOTIF-FIN-043 Forecast model drift alert

## Reports
- REP-FIN-043 Collections Forecast Dashboard
- REP-FIN-044 Payment Behavior Segmentation

## KPIs
- KPI-FIN-042 Forecast accuracy
- KPI-FIN-043 Collection uplift from interventions

## Performance Targets
- PERF-FIN-029 analytics KPI dashboard load under 3s p95

## Security Requirements
- SEC-FIN-028

## Acceptance Criteria
- AC-FIN-170: KPI definitions declare formula, source, and refresh cadence before activation.
- AC-FIN-171: Forecast outputs persist model version and input snapshot references.
- AC-FIN-172: Sensitive identifiers in analytics exports are masked by policy.

## Test Cases
- TEST-FIN-170 Forecast run metadata and snapshot persistence
- TEST-FIN-171 KPI computation consistency against canonical posting sources
- TEST-FIN-172 Analytics export masking and scope validation

## Migration Notes
- Build KPI and forecast pipelines from canonical finance events and read models.
- Run analytics in shadow mode against current reporting outputs before adoption.

## Open Risks
- RISK-FIN-029: Data-quality issues in source events may degrade forecast reliability.
- RISK-FIN-030: Model drift may mislead interventions if monitoring is weak.

## ADR Links
- ADR-FIN-030 KPI and forecast governance model

