# ADR-FIN-025 Scheduler Lease and Retry Model

- ADR ID: ADR-FIN-025
- Title: Scheduler topology, lease model, and bounded retry policy
- Status: Proposed
- Date: 2026-07-19

## Context
Recurring finance jobs must run once per schedule in multi-node deployments while handling transient failures safely.

## Decision Drivers
- Prevent duplicate execution.
- Ensure recoverability without runaway retries.
- Keep operational observability clear.

## Options Considered
1. Single-node scheduler with no leasing.
2. Distributed scheduler with DB-backed leases and retry policies.
3. External scheduler service with minimal in-app controls.

## Decision
Use distributed scheduling with database-backed execution leases, bounded retry thresholds, and failure incident records.

## Consequences
- Positive: Reliable multi-node behavior and controlled recovery.
- Negative: Additional DB contention and lease-tuning overhead.

## Affected Requirements
- CAP-FIN-016
- BR-FIN-033
- BR-FIN-034
- API-FIN-V1-146
- EVT-FIN-028

## Rollback/Exit Strategy
Fallback to single active scheduler node with monitor-only mode for non-critical jobs until lease stability is restored.

## Review Date
2026-10-19
