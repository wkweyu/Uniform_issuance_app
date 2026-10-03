# ADR-FIN-030 KPI and Forecast Governance Model

- ADR ID: ADR-FIN-030
- Title: KPI definition control and forecast reproducibility standards
- Status: Proposed
- Date: 2026-07-19

## Context
Analytics outputs influence financial decisions and require transparent formulas, source lineage, and reproducible forecast runs.

## Decision Drivers
- Ensure KPI consistency across teams.
- Enable reproducible forecast audits.
- Limit sensitive data exposure in analytics outputs.

## Options Considered
1. Ad-hoc KPI/forecast logic per report.
2. Central KPI registry with versioned forecast run metadata.
3. Outsource forecasting without internal lineage controls.

## Decision
Use centralized KPI definitions, enforce source and cadence metadata, and persist model version plus input snapshots for each forecast run.

## Consequences
- Positive: Higher trust and auditability of analytics decisions.
- Negative: Additional governance overhead for metric/model updates.

## Affected Requirements
- CAP-FIN-015
- BR-FIN-049
- BR-FIN-050
- API-FIN-V1-171
- EVT-FIN-039

## Rollback/Exit Strategy
Revert to descriptive analytics only and suspend forecast publishing while model lineage issues are corrected.

## Review Date
2026-10-19
