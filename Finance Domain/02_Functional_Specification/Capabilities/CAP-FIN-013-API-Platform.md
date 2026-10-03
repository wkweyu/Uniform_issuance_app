# CAP-FIN-013: API Platform

## Purpose
Govern finance API lifecycle, compatibility, and contract quality across internal and external consumers.

## Owner
- Primary: API Platform Lead
- Secondary: Finance Integration Architect

## Business Goal
Protect consuming clients from breaking changes while enabling safe, incremental API evolution.

## Stakeholders
- Integrations Team
- Mobile/Web Clients
- Finance Operations
- Support
- Security

## Dependencies
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-007
- CAP-FIN-017

## Business Rules
- BR-FIN-045
- BR-FIN-046

## Workflows
- WF-FIN-042 API Version Lifecycle
- WF-FIN-043 Deprecation and Sunset

## Database Objects
- DB-FIN-083 ApiContractRegistry
- DB-FIN-084 ApiCompatibilityPolicy
- DB-FIN-085 ApiDeprecationNotice
- DB-FIN-086 ApiConsumerEnrollment

## Services and Use Cases
- ApiContractRegistryService
- ApiCompatibilityValidator
- ApiDeprecationService
- ApiUsageTelemetryService

## Events
- EVT-FIN-037 ApiContractDeprecated

## API Endpoints
- API-FIN-V1-150 GET /api/v1/contracts
- API-FIN-V1-151 POST /api/v1/contracts/{id}/deprecate
- API-FIN-V1-155 POST /api/v1/contracts/{id}/compatibility-check

## Permissions
- PERM-FIN-150 ManageApiContracts
- PERM-FIN-151 PublishDeprecationNotice
- PERM-FIN-154 ViewApiUsageTelemetry

## Notifications
- NOTIF-FIN-033 API deprecation notice
- NOTIF-FIN-041 Breaking change policy violation alert

## Reports
- REP-FIN-039 API Version Adoption Mix
- REP-FIN-040 API Compatibility Exception Register

## KPIs
- KPI-FIN-038 Deprecated-version usage decay rate
- KPI-FIN-039 Contract compliance pass rate

## Performance Targets
- PERF-FIN-027 contract lookup and compatibility check under 200ms p95

## Security Requirements
- SEC-FIN-026

## Acceptance Criteria
- AC-FIN-150: Breaking changes are blocked unless introduced under a new major version.
- AC-FIN-151: Deprecation notices include sunset date and impacted consumer report.
- AC-FIN-152: Compatibility checks are executable before release promotion.

## Test Cases
- TEST-FIN-150 Deprecation notice publication and consumer impact report
- TEST-FIN-151 Major-version boundary enforcement for breaking changes
- TEST-FIN-152 Compatibility gate evaluation during release workflow

## Migration Notes
- Keep existing endpoints stable under current path while registering contracts in platform registry.
- Enforce compatibility checks in warn-only mode before hard blocking.

## Open Risks
- RISK-FIN-025: Undocumented consumers may be impacted by deprecations.
- RISK-FIN-026: Missing schema governance can create silent contract drift.

## ADR Links
- ADR-FIN-028 API versioning and sunset governance

