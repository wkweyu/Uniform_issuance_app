# MIG-FIN-007 Security Controls Schema

- Migration ID: MIG-FIN-007
- Capability: CAP-FIN-012
- Owner: Security Engineering Lead
- Date: 2026-07-22
- Wave: Wave-1

## Objective
Create canonical control policy, step-up challenge, and SoD violation log tables to enforce and record high-risk finance control gates.

## Change Type
- Additive schema

## Database Objects
- DB-FIN-035 ControlPolicy
- DB-FIN-036 StepUpChallenge
- DB-FIN-037 SoDViolationLog

## Steps
1. Create `v007__security_controls_schema.sql`.
2. Seed ControlPolicy from existing security configuration (refund thresholds, high-risk action types).
3. Add step-up challenge enforcement to refund and reversal endpoints (sidecar evaluation mode first).
4. Enable SoDViolationLog writes when dual-approval violations are detected.
5. Run SoD detection scan against existing user-permission assignments and log detected violations.
6. Switch enforcement mode from warn-only to hard-fail after two-sprint baseline period.

## Rollback Plan
Switch enforcement back to warn-only mode; SoDViolationLog entries are preserved for audit. ControlPolicy can be reset to previous thresholds.

## Validation
- Data parity checks: ControlPolicy thresholds match current security configuration values.
- Tenant isolation checks: tenant_id on all ControlPolicy and SoDViolationLog rows.
- Accounting integrity checks: every high-risk operation above threshold has a linked StepUpChallenge record.

## Risks
- RISK-FIN-011: False-positive SoD violations from legacy over-permissioned roles may generate noise.
- RISK-FIN-012: Step-up latency under load must be validated before hard-fail enforcement is enabled.
