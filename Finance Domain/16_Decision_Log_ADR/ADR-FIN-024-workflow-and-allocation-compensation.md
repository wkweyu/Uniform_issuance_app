# ADR-FIN-024 Workflow and Allocation Compensation

- ADR ID: ADR-FIN-024
- Title: Workflow state model and allocation compensation policy
- Status: Proposed
- Date: 2026-07-19

## Context
Finance workflows and allocation actions span multiple steps and side effects. Partial failures can leave inconsistent business state if not modeled explicitly.

## Decision Drivers
- Preserve financial correctness under failure.
- Support auditable reversals instead of destructive edits.
- Keep operational handling predictable for support teams.

## Options Considered
1. Best-effort updates with manual cleanup.
2. Strict transactional boundaries with explicit compensation events.
3. Hybrid model with selective compensation for high-risk flows.

## Decision
Adopt explicit workflow states and compensation actions for finance operations, with immutable decision logs and linked reversal/compensation records.

## Consequences
- Positive: Better resilience and recoverability with full audit trace.
- Negative: Higher implementation complexity in orchestration logic.

## Affected Requirements
- CAP-FIN-006
- CAP-FIN-010
- BR-FIN-024
- BR-FIN-025
- API-FIN-V1-120
- EVT-FIN-022

## Rollback/Exit Strategy
Disable compensation automations behind feature flags and route failures to manual approval workflows while preserving immutable logs.

## Review Date
2026-10-19
