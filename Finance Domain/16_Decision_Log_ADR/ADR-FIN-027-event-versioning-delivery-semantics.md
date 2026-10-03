# ADR-FIN-027 Event Versioning and Delivery Semantics

- ADR ID: ADR-FIN-027
- Title: Event contract versioning, outbox publishing, and delivery guarantees
- Status: Proposed
- Date: 2026-07-19

## Context
Decoupled finance capabilities require predictable event contracts and delivery semantics to avoid downstream breakage.

## Decision Drivers
- Preserve atomicity between state changes and event publication.
- Support backward-compatible event evolution.
- Maintain replay safety.

## Options Considered
1. Direct publish without outbox and best-effort retries.
2. Transactional outbox with versioned envelopes and bounded retries.
3. Synchronous service coupling without domain events.

## Decision
Use transactional outbox, versioned event envelopes, and bounded retry/dead-letter policies with controlled replay scopes.

## Consequences
- Positive: Stronger consistency and safer asynchronous processing.
- Negative: Additional operational components and observability demands.

## Affected Requirements
- CAP-FIN-018
- BR-FIN-030
- BR-FIN-031
- API-FIN-V1-152
- EVT-FIN-026

## Rollback/Exit Strategy
Switch consumers to legacy synchronous paths per capability while keeping outbox writes enabled for audit continuity.

## Review Date
2026-10-19
