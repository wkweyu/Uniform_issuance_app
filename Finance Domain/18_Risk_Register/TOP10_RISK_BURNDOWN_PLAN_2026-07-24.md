# Top-10 Risk Burn-down Plan

Date: 2026-07-24
Scope: Highest-priority Open risks from RISK_REGISTER_TEMPLATE.csv
Method: PriorityScore = Severity + Likelihood + Impact (Low=1, Medium=2, High=3, Critical=4)

## Top-10 Risks (Prioritized)

| Rank | Risk ID | Capability | Score | Owner | Target Date |
|---|---|---|---:|---|---|
| 1 | RISK-FIN-006 | CAP-FIN-008 | 9 | Security Lead | 2026-08-29 |
| 2 | RISK-FIN-035 | CAP-FIN-017 | 9 | Integrations Platform Lead | 2026-09-19 |
| 3 | RISK-FIN-027 | CAP-FIN-014 | 9 | Security Lead | 2026-10-03 |
| 4 | RISK-FIN-005 | CAP-FIN-003 | 8 | AR Engineering Lead | 2026-08-22 |
| 5 | RISK-FIN-010 | CAP-FIN-011 | 8 | Finance Engineering Lead | 2026-09-05 |
| 6 | RISK-FIN-024 | CAP-FIN-009 | 8 | Communications Platform Lead | 2026-09-05 |
| 7 | RISK-FIN-021 | CAP-FIN-005 | 8 | Payments Integrations Product Lead | 2026-09-12 |
| 8 | RISK-FIN-015 | CAP-FIN-017 | 8 | Integrations Platform Lead | 2026-09-19 |
| 9 | RISK-FIN-017 | CAP-FIN-018 | 8 | Eventing Platform Lead | 2026-09-19 |
| 10 | RISK-FIN-037 | CAP-FIN-018 | 8 | Eventing Platform Lead | 2026-09-19 |

## Action Pack

1. RISK-FIN-006
- Mitigation action: Add tenant-scoped integration tests to every reporting query path and enforce query review gate before release.
- Evidence required: passing multi-tenant report test suite + review checklist attached to release item.

2. RISK-FIN-035
- Mitigation action: Introduce mandatory contract tests for partner adapters and 60-second health degradation alerting.
- Evidence required: CI contract test run history + alert simulation output.

3. RISK-FIN-027
- Mitigation action: Implement adversarial relationship-mapping tests and mandatory security review prior to parent launch.
- Evidence required: signed security review + failing/then-passing adversarial test cases.

4. RISK-FIN-005
- Mitigation action: Run reversal chain integrity audit and normalize orphan references before AR migration cutover.
- Evidence required: reconciliation report showing zero orphan reversal links.

5. RISK-FIN-010
- Mitigation action: Execute production-scale trigger load tests and implement async outbox fallback if throughput target fails.
- Evidence required: load test benchmark report against PERF threshold.

6. RISK-FIN-024
- Mitigation action: Enforce suppression and consent checks before any reminder dispatch.
- Evidence required: compliance test report proving opted-out recipients are blocked.

7. RISK-FIN-021
- Mitigation action: Auto-create settlement exception cases on mismatch and enforce manual resolution SLA.
- Evidence required: runbook entry + sample mismatch case lifecycle evidence.

8. RISK-FIN-015
- Mitigation action: Wrap current MPESA/email integrations with adapter contracts before interface changes.
- Evidence required: adapter contract test matrix with backward-compatibility pass.

9. RISK-FIN-017
- Mitigation action: Enforce event schema registry and prohibit breaking changes without new event type.
- Evidence required: schema registry policy + CI enforcement logs.

10. RISK-FIN-037
- Mitigation action: Add consumer compatibility tests before producer event schema cutover.
- Evidence required: producer-consumer contract verification report per deployment.

## 30-Day Burn-down Milestones

- By 2026-08-29: Close or downgrade RISK-FIN-005 and RISK-FIN-006.
- By 2026-09-12: Close or downgrade RISK-FIN-010, RISK-FIN-024, RISK-FIN-021.
- By 2026-09-19: Close or downgrade RISK-FIN-035, RISK-FIN-015, RISK-FIN-017, RISK-FIN-037.
- By 2026-10-03: Close or downgrade RISK-FIN-027.

## Expected Readiness Impact

- CAP-FIN-003, CAP-FIN-008, CAP-FIN-009, CAP-FIN-011, CAP-FIN-014, CAP-FIN-017, CAP-FIN-018 should improve recommendation status once open-risk counts reduce and evidence is attached.
- Program target: reduce open risks from 31 to <= 21 in next cycle, then rerun readiness scorecard.
