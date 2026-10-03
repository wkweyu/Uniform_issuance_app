# ADR-FIN-026 Integration Contract Governance

- ADR ID: ADR-FIN-026
- Title: Integration contract governance and replay boundaries
- Status: Proposed
- Date: 2026-07-19

## Context
Finance integrations rely on external systems with variable reliability and changing payload contracts.

## Decision Drivers
- Standardize provider onboarding.
- Enforce idempotency and schema validation.
- Provide safe replay and dead-letter handling.

## Options Considered
1. Provider-specific direct integrations in each capability.
2. Central integration hub with governed contracts.
3. Managed integration platform without domain-level controls.

## Decision
Adopt a central integration hub that enforces contract validation, idempotency keys, and replay through controlled operations.

## Consequences
- Positive: Reduced integration drift and faster provider onboarding.
- Negative: Extra platform layer and governance process overhead.

## Affected Requirements
- CAP-FIN-008
- CAP-FIN-017
- BR-FIN-027
- BR-FIN-029
- API-FIN-V1-149
- EVT-FIN-024

## Rollback/Exit Strategy
Temporarily bypass hub for specific providers via explicit exception approvals while preserving delivery logs for reconciliation.

## Review Date
2026-10-19
