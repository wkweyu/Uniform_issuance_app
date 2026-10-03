# REL-FIN-WAVE1: Finance Domain — Wave 1 Release Notes (Financial Foundation)

- Release ID: REL-FIN-WAVE1
- Wave: Wave-1 (P0 Core Finance Foundation)
- Status: Approved
- Approval Date: 2026-07-20
- Approved By: Finance-Domain-Lead
- Target Delivery: Pending engineering sprint scheduling

---

## Scope Summary

Wave 1 establishes the financial foundation layer — the capabilities required to receive, post, report, and audit financial transactions. All 10 release items in this wave are P0 and carry Approved status.

---

## Capability Releases

### CAP-FIN-001 Financial Setup
- **REL-FIN-001** — BR-FIN-006: Period lock enforcement active on all posting endpoints.
- Test: TEST-FIN-001
- Security: SEC-FIN-002
- ADR: ADR-FIN-001

### CAP-FIN-002 Billing Engine
- **REL-FIN-002** — BR-FIN-007: Invoice regeneration requires version trace and superseded linkage.
- Test: TEST-FIN-011
- ADR: ADR-FIN-003

### CAP-FIN-003 Accounts Receivable
- **REL-FIN-003** — BR-FIN-005: Every payment must allocate to one or more invoice lines.
- **REL-FIN-004** — BR-FIN-003: Corrections require reversal entries; no destructive ledger edits.
- Tests: TEST-FIN-020, TEST-FIN-022
- ADR: ADR-FIN-005

### CAP-FIN-004 Payment Operations
- **REL-FIN-005** — BR-FIN-013: External callback payloads pass signature and timestamp validation before state transition.
- **REL-FIN-006** — BR-FIN-014: Reconciliation exception opened on payment amount or reference mismatch.
- Tests: TEST-FIN-030, TEST-FIN-032
- Security: SEC-FIN-008
- ADR: ADR-FIN-007

### CAP-FIN-007 General Ledger
- **REL-FIN-007** — BR-FIN-016: Unbalanced journal submission rejected with rule violation.
- **REL-FIN-008** — BR-FIN-017: Reversal journals preserve link to original and cannot reverse an already reversed journal.
- Tests: TEST-FIN-040, TEST-FIN-042
- Security: SEC-FIN-011
- ADR: ADR-FIN-009

### CAP-FIN-011 Audit and Compliance
- **REL-FIN-009** — BR-FIN-019: Audit export is access-controlled and watermark-stamped with request metadata.
- Test: TEST-FIN-050
- Security: SEC-FIN-012
- ADR: ADR-FIN-011

### CAP-FIN-012 Security Controls
- **REL-FIN-010** — BR-FIN-022: Same actor cannot both initiate and approve restricted dual-approval actions.
- Test: TEST-FIN-061
- Security: SEC-FIN-013
- ADR: ADR-FIN-013

---

## API Changes

- API-FIN-V1-002 POST /api/v1/finance/setup/period-lock
- API-FIN-V1-020 POST /api/v1/payments
- API-FIN-V1-030 POST /api/v1/payments/callbacks/{provider}
- API-FIN-V1-040 POST /api/v1/gl/journals/post
- API-FIN-V1-051 POST /api/v1/audit/exports
- API-FIN-V1-061 POST /api/v1/security/control-evaluate

---

## Data and Migration Notes

- `uniform_receipts`, `finance_transactions`, and `finance_ledger_entries` must be wrapped behind canonical AR and GL facades before go-live.
- Period lock enforcement requires `uniform_term_dates` or equivalent lock table active with current-term records.
- Audit export table must be bootstrapped before CAP-FIN-011 routes are activated.
- All journal inserts must reference a valid `school_id` and posting period.

---

## Risk Notes

- RISK-FIN-001: Configuration drift if period lock is not enforced on all posting paths simultaneously.
- RISK-FIN-007: Callback replay attacks if idempotency keys are not enforced from day one.
- RISK-FIN-008: Ledger imbalance if legacy posting code bypasses new journal validation service.
- RISK-FIN-009: Compliance gap if audit export is not activated before first finance audit window.

---

## Known Issues / Pre-conditions

- ADR-FIN-023 (CAP-FIN-004/005 scope alignment) must be approved before Wave 2 begins.
- Wave 1 does not include allocation engine (CAP-FIN-006) — payments are posted but auto-allocation is a Wave 2 item.
- Parent portal (CAP-FIN-014) and analytics (CAP-FIN-015) are Wave 3; no dependency on Wave 1 for those.

---

## Post-Release Monitoring

| Control | Target |
|---------|--------|
| PERF-FIN-001 | Receive payment end-to-end < 2s p95 |
| PERF-FIN-002 | Student statement generation < 3s |
| PERF-FIN-009 | Journal posting < 2s p95 |
| SEC-FIN-002 | Period lock enforcement rate = 100% |
| SEC-FIN-011 | Immutable journal chain integrity |
| KPI-FIN-001 | Setup change lead time |
| KPI-FIN-005 | Collection rate |
| KPI-FIN-011 | Journal balance exception rate (target: 0%) |
| KPI-FIN-013 | Audit coverage ratio |

---

## Traceability Links

| REL ID | TRACE ID | Requirement | Test |
|--------|----------|-------------|------|
| REL-FIN-001 | TRACE-FIN-001 | BR-FIN-006 | TEST-FIN-001 |
| REL-FIN-002 | TRACE-FIN-002 | BR-FIN-007 | TEST-FIN-011 |
| REL-FIN-003 | TRACE-FIN-003 | BR-FIN-005 | TEST-FIN-020 |
| REL-FIN-004 | TRACE-FIN-004 | BR-FIN-003 | TEST-FIN-022 |
| REL-FIN-005 | TRACE-FIN-005 | BR-FIN-013 | TEST-FIN-030 |
| REL-FIN-006 | TRACE-FIN-006 | BR-FIN-014 | TEST-FIN-032 |
| REL-FIN-007 | TRACE-FIN-007 | BR-FIN-016 | TEST-FIN-040 |
| REL-FIN-008 | TRACE-FIN-008 | BR-FIN-017 | TEST-FIN-042 |
| REL-FIN-009 | TRACE-FIN-009 | BR-FIN-019 | TEST-FIN-050 |
| REL-FIN-010 | TRACE-FIN-010 | BR-FIN-022 | TEST-FIN-061 |

---

## Signoff

| Role | Name | Status | Date |
|------|------|--------|------|
| Finance Domain Lead | TBD | Approved | 2026-07-20 |
| Engineering Lead | TBD | Pending | — |
| QA Lead | TBD | Pending | — |
| Compliance Lead | TBD | Pending | — |
| Security Lead | TBD | Pending | — |
