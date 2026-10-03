# CAP-FIN-017: Integration Hub

## Purpose
Provide a governed boundary for inbound and outbound finance integrations with idempotency, schema validation, and delivery guarantees.

## Owner
- Primary: Integrations Platform Lead
- Secondary: Finance Domain Architect

## Business Goal
Standardize external system interactions to reduce integration defects and accelerate partner onboarding.

## Stakeholders
- Integrations Team
- Finance Operations
- Vendor Management
- Support
- Security

## Dependencies
- CAP-FIN-005
- CAP-FIN-009
- CAP-FIN-012
- CAP-FIN-018

## Business Rules
- BR-FIN-027
- BR-FIN-029

## Workflows
- WF-FIN-028 Partner Onboarding and Credential Exchange
- WF-FIN-029 Inbound Callback Validation and Mapping
- WF-FIN-030 Outbound Delivery with Retry and Dead-Letter

## Database Objects
- DB-FIN-075 IntegrationEndpoint
- DB-FIN-076 IntegrationCredentialRef
- DB-FIN-077 IntegrationDeliveryLog
- DB-FIN-078 IntegrationDeadLetter

## Services and Use Cases
- IntegrationRegistryService
- IntegrationInboundGateway
- IntegrationOutboundDispatcher
- IntegrationReplayService

## Events
- EVT-FIN-024 IntegrationDeliveryFailed
- EVT-FIN-025 IntegrationReplayCompleted

## API Endpoints
- API-FIN-V1-148 POST /api/v1/integrations/inbound/{provider}
- API-FIN-V1-149 POST /api/v1/integrations/outbound/replay
- API-FIN-V1-150 GET /api/v1/integrations/deliveries

## Permissions
- PERM-FIN-148 ManageIntegrations
- PERM-FIN-149 ReplayIntegrationEvents
- PERM-FIN-150 ViewIntegrationLogs

## Notifications
- NOTIF-FIN-037 Partner callback signature failure
- NOTIF-FIN-038 Dead-letter queue threshold reached

## Reports
- REP-FIN-035 Integration Reliability Dashboard
- REP-FIN-036 Partner SLA Compliance Register

## KPIs
- KPI-FIN-034 First-attempt delivery success
- KPI-FIN-035 Mean time to recover failed integrations

## Performance Targets
- PERF-FIN-028 inbound validation and enqueue under 400ms p95

## Security Requirements
- SEC-FIN-017
- SEC-FIN-018

## Acceptance Criteria
- AC-FIN-080: Inbound payloads failing signature or schema checks are rejected and logged.
- AC-FIN-081: Outbound deliveries are idempotent with replay-safe deduplication keys.
- AC-FIN-082: Operators can replay failed deliveries with full traceability.

## Test Cases
- TEST-FIN-080 Idempotent callback processing with duplicate payloads
- TEST-FIN-081 Signature and schema validation failure paths
- TEST-FIN-082 Dead-letter replay and reconciliation validation

## Migration Notes
- Wrap direct third-party calls behind integration endpoint definitions.
- Phase migration provider-by-provider with observable cutover metrics.

## Open Risks
- RISK-FIN-035: Partner API changes without notice may break payload mappings.
- RISK-FIN-036: Credential rotation failures may cause prolonged delivery outages.

## ADR Links
- ADR-FIN-026 Integration contract governance model

