# ADR-FIN-028 API Versioning and Sunset Governance

- ADR ID: ADR-FIN-028
- Title: Breaking-change governance and API deprecation policy
- Status: Proposed
- Date: 2026-07-19

## Context
Finance APIs are consumed by multiple clients and integrations, requiring strict compatibility controls during evolution.

## Decision Drivers
- Prevent unplanned consumer breakage.
- Provide measurable deprecation progress.
- Enforce release-time compatibility checks.

## Options Considered
1. In-place API changes with release notes only.
2. Major-version path for breaking changes with enforced deprecation windows.
3. Frozen API surface with no breaking evolution.

## Decision
Require major-version increments for breaking changes, publish deprecation notices with sunset dates, and gate release on compatibility checks.

## Consequences
- Positive: Better consumer stability and controlled migrations.
- Negative: Version proliferation and support overhead for legacy endpoints.

## Affected Requirements
- CAP-FIN-009
- CAP-FIN-013
- BR-FIN-045
- BR-FIN-046
- API-FIN-V1-151
- EVT-FIN-037

## Rollback/Exit Strategy
Pause deprecation enforcement and extend sunset windows for affected consumers while preserving telemetry and notices.

## Review Date
2026-10-19
