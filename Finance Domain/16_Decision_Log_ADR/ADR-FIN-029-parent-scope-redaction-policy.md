# ADR-FIN-029 Parent Scope Authorization and Redaction Policy

- ADR ID: ADR-FIN-029
- Title: Parent finance access scope and document redaction enforcement
- Status: Proposed
- Date: 2026-07-19

## Context
Parent self-service must expose finance information while preventing cross-student data leakage and over-disclosure.

## Decision Drivers
- Enforce relationship-based access controls.
- Protect sensitive fields in downloadable artifacts.
- Maintain full access auditability.

## Options Considered
1. Broad parent account access with minimal filtering.
2. Relationship-scoped access with redaction and audit logs.
3. No document downloads from parent portal.

## Decision
Apply strict relationship-scoped authorization, policy-driven redaction for exports/downloads, and full access event logging.

## Consequences
- Positive: Reduced privacy risk and stronger compliance posture.
- Negative: More complex authorization and cache invalidation logic.

## Affected Requirements
- CAP-FIN-014
- BR-FIN-047
- BR-FIN-048
- API-FIN-V1-160
- EVT-FIN-038

## Rollback/Exit Strategy
Disable parent document downloads and keep view-only scoped access while redaction controls are remediated.

## Review Date
2026-10-19
