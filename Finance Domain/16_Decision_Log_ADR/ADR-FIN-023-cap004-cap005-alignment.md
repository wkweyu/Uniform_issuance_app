# ADR-FIN-023: CAP-FIN-004 and CAP-FIN-005 Scope Alignment

- ADR ID: ADR-FIN-023
- Status: Proposed
- Date: 2026-07-19

## Context
CAP-FIN-004 was seeded with broad payment services scope. Wave 4 introduces CAP-FIN-005 for payment channel services, creating potential overlap.

## Decision
- CAP-FIN-004 = Payment Operations orchestration (capture, reconciliation control, payment state lifecycle).
- CAP-FIN-005 = Payment Channel Services (rail-specific adapters, settlement behaviors, channel fee policies).

## Rationale
- Preserves seeded IDs and workshop continuity.
- Avoids renumbering churn in traceability rows.
- Supports clearer ownership split between operations and channel integrations.

## Consequences
- Update all references in workshop materials to reflect final split.
- Ensure API and workflow ownership maps to the new boundary.

## Affected IDs
- CAP-FIN-004
- CAP-FIN-005
- WF-FIN-010..012
- WF-FIN-034..035
- API-FIN-V1-030..032
- API-FIN-V1-110..111

## Review Trigger
- If settlement and reconciliation responsibilities converge in implementation.
