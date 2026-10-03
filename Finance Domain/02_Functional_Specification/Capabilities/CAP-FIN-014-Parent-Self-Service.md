# CAP-FIN-014: Parent Self-Service

## Purpose
Provide secure parent-facing access to statements, balances, receipts, and payment confirmations.

## Owner
- Primary: Parent Experience Product Lead
- Secondary: Finance Channels Lead

## Business Goal
Reduce in-person and manual bursary requests by enabling trusted self-service finance operations.

## Stakeholders
- Parents/Guardians
- Bursar
- Finance Manager
- Support
- Security and Compliance

## Dependencies
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-008
- CAP-FIN-009
- CAP-FIN-012

## Business Rules
- BR-FIN-047
- BR-FIN-048

## Workflows
- WF-FIN-044 Parent Statement Access
- WF-FIN-045 Parent Payment Confirmation Retrieval

## Database Objects
- DB-FIN-087 ParentFinanceSession
- DB-FIN-088 ParentAccessGrant
- DB-FIN-089 ParentStatementCache
- DB-FIN-090 ParentDocumentDownloadLog

## Services and Use Cases
- ParentFinanceAccessService
- ParentStatementService
- ParentReceiptService
- ParentScopeAuthorizationService

## Events
- EVT-FIN-038 ParentFinanceAccessed

## API Endpoints
- API-FIN-V1-160 GET /api/v1/parent/finance/statement
- API-FIN-V1-161 GET /api/v1/parent/finance/receipts
- API-FIN-V1-162 GET /api/v1/parent/finance/balance-summary

## Permissions
- PERM-FIN-160 ParentViewFinance
- PERM-FIN-161 ParentDownloadReceipt

## Notifications
- NOTIF-FIN-034 Statement available to parent
- NOTIF-FIN-042 Parent failed access challenge alert

## Reports
- REP-FIN-041 Parent Finance Self-Service Usage
- REP-FIN-042 Parent Access Exception Register

## KPIs
- KPI-FIN-040 Parent self-service adoption rate
- KPI-FIN-041 Parent finance request deflection rate

## Performance Targets
- PERF-FIN-028 parent statement view under 2s p95

## Security Requirements
- SEC-FIN-027

## Acceptance Criteria
- AC-FIN-160: Parent access is strictly limited to authorized student relationships.
- AC-FIN-161: Downloaded finance documents enforce redaction and scope policies.
- AC-FIN-162: Access attempts are auditable with session, actor, and scope metadata.

## Test Cases
- TEST-FIN-160 Authorized-scope statement access only
- TEST-FIN-161 Cross-student access denial and audit capture
- TEST-FIN-162 Receipt download redaction and watermark behavior

## Migration Notes
- Start by exposing read-only statement and receipt flows through a scoped API facade.
- Maintain current portal routes while progressively routing data to canonical finance read models.

## Open Risks
- RISK-FIN-027: Relationship-mapping defects could expose unauthorized finance data.
- RISK-FIN-028: Cached artifacts may leak stale or over-broad scope data if invalidation fails.

## ADR Links
- ADR-FIN-029 Parent scope authorization and redaction policy

