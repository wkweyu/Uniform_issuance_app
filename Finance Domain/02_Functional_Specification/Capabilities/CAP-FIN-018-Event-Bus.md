# CAP-FIN-018: Event Bus

## Purpose
Provide reliable, ordered, and observable finance event distribution for decoupled domain collaboration.

## Owner
- Primary: Eventing Platform Lead
- Secondary: Finance Domain Architect

## Business Goal
Enable event-driven scale while preserving financial correctness, traceability, and replayability.

## Stakeholders
- Finance Domain Teams
- Integrations Team
- Reporting Team
- Operations
- Security

## Dependencies
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-016
- CAP-FIN-017

## Business Rules
- BR-FIN-030
- BR-FIN-031

## Workflows
- WF-FIN-031 Domain Event Publication
- WF-FIN-032 Subscription Processing and Retry
- WF-FIN-033 Replay from Checkpoint

## Database Objects
- DB-FIN-079 EventOutbox
- DB-FIN-080 EventDeliveryCursor
- DB-FIN-081 EventReplayRequest
- DB-FIN-082 EventSchemaRegistry

## Services and Use Cases
- EventPublisherService
- EventOutboxRelayService
- SubscriptionDispatchService
- EventReplayOrchestrator

## Events
- EVT-FIN-026 EventReplayRequested
- EVT-FIN-038 EventPublicationLagExceeded
- EVT-FIN-039 EventSchemaValidationFailed

## API Endpoints
- API-FIN-V1-152 POST /api/v1/events/replay
- API-FIN-V1-153 GET /api/v1/events/subscriptions/health
- API-FIN-V1-154 GET /api/v1/events/outbox/lag

## Permissions
- PERM-FIN-152 ReplayDomainEvents
- PERM-FIN-153 ViewEventHealth

## Notifications
- NOTIF-FIN-039 Event subscriber lag alert
- NOTIF-FIN-040 Event schema break warning

## Reports
- REP-FIN-037 Event Throughput and Lag Report
- REP-FIN-038 Event Replay Activity Register

## KPIs
- KPI-FIN-036 End-to-end event delivery latency
- KPI-FIN-037 Event subscriber success rate

## Performance Targets
- PERF-FIN-029 outbox relay latency under 1s p95

## Security Requirements
- SEC-FIN-019
- SEC-FIN-021

## Acceptance Criteria
- AC-FIN-090: Event publication uses transactional outbox to avoid lost updates.
- AC-FIN-091: Subscriber retries are bounded and dead-lettered on terminal failure.
- AC-FIN-092: Replay supports scoped time-window and tenant filters.

## Test Cases
- TEST-FIN-090 Outbox exactly-once relay behavior under crash recovery
- TEST-FIN-091 Subscriber retry and dead-letter routing
- TEST-FIN-092 Replay consistency against source aggregates

## Migration Notes
- Introduce outbox tables alongside existing synchronous side effects.
- Replace direct cross-module calls with event subscriptions in staged cutovers.

## Open Risks
- RISK-FIN-037: Unversioned event contracts can break downstream consumers.
- RISK-FIN-038: Subscriber lag growth may impact near-real-time processes.

## ADR Links
- ADR-FIN-027 Event versioning and delivery semantics

