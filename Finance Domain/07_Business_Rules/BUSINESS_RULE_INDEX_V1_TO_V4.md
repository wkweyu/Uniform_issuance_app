# Business Rule Index v1-v4

## Financial Integrity Rules
- BR-FIN-001 Receipt number uniqueness by school and year
- BR-FIN-002 Posted journals are immutable
- BR-FIN-003 Corrections use reversals only
- BR-FIN-004 Outstanding balance = debits - credits
- BR-FIN-005 Payments allocate to invoice lines
- BR-FIN-006 Locked periods block posting

## Billing and Payment Controls
- BR-FIN-007 Invoice regeneration with superseded linkage
- BR-FIN-008 Payment reference uniqueness by rail and school
- BR-FIN-011 Credit notes limit policy
- BR-FIN-012 Recurring charge policy windows
- BR-FIN-013 Callback signature and timestamp validation
- BR-FIN-014 Reconciliation exception opening rule
- BR-FIN-015 Manual override reason and approval

## GL and Audit Controls
- BR-FIN-016 Balanced journal requirement
- BR-FIN-017 Reversal linkage and non-double-reversal
- BR-FIN-018 Audit evidence minimum content
- BR-FIN-019 Audit export access and watermarking
- BR-FIN-020 Retention execution evidence

## Security and SoD Controls
- BR-FIN-021 Step-up authentication for high-risk actions
- BR-FIN-022 Initiator/approver separation for dual control
- BR-FIN-023 Emergency bypass policy governance

## Workflow and Integration Rules
- BR-FIN-024 Workflow definition version binding
- BR-FIN-025 Workflow escalation on SLA breach
- BR-FIN-026 Workflow completion immutability
- BR-FIN-027 Adapter health/timeout contract
- BR-FIN-028 Secret rotation without downtime
- BR-FIN-029 Incident opening on failure thresholds

## Eventing and Scheduler Rules
- BR-FIN-030 Outbox atomic publish rule
- BR-FIN-031 Authorized and rate-limited replay
- BR-FIN-032 Consumer offset rewind governance
- BR-FIN-033 Job dependency enforcement
- BR-FIN-034 Close-window lock requirement
- BR-FIN-035 Retry threshold to actionable ticket rule

## Remaining Domain Rules
- BR-FIN-036 Settlement reconciliation before closure
- BR-FIN-037 Channel fee policy effective-date approval
- BR-FIN-038 Deterministic allocation output
- BR-FIN-039 Approved immutable manual reallocation linkage
- BR-FIN-040 Allocation cap by unapplied amount
- BR-FIN-041 Scoped report export watermarking
- BR-FIN-042 Versioned report definition governance
- BR-FIN-043 Notification template activation approval
- BR-FIN-044 Campaign preference suppression enforcement
- BR-FIN-045 Breaking API changes require major version
- BR-FIN-046 API deprecation notice window requirement
- BR-FIN-047 Parent access scoped to authorized relationships
- BR-FIN-048 Parent document redaction policy
- BR-FIN-049 KPI formula/source/cadence declaration
- BR-FIN-050 Forecast model and input snapshot trace
