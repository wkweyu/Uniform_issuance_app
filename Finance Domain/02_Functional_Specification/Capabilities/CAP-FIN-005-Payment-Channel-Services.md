# CAP-FIN-005: Payment Channel Services

## Purpose
Manage rail-specific behavior for CASH, BANK, MPESA, CARD, EFT, and gateway channels.

## Owner
- Primary: Payments Integrations Product Lead
- Secondary: Integration Reliability Lead

## Business Goal
Enable channel-agnostic core payment processing while isolating rail-specific policies and settlement logic.

## Stakeholders
- Bursar
- Finance Operations
- Integrations Team
- Support
- Vendor Management

## Dependencies
- CAP-FIN-004
- CAP-FIN-017
- CAP-FIN-018

## Business Rules
- BR-FIN-036
- BR-FIN-037

## Workflows
- WF-FIN-034 Channel Settlement Sync
- WF-FIN-035 Channel Exception Handling

## Database Objects
- DB-FIN-055 ChannelProfile
- DB-FIN-056 ChannelSettlement
- DB-FIN-057 ChannelFeePolicy

## Services and Use Cases
- ChannelAdapterService
- ChannelSettlementService
- ChannelPolicyService
- ChannelExceptionService

## Events
- EVT-FIN-030 ChannelSettlementSynced
- EVT-FIN-031 ChannelFeePolicyChanged

## API Endpoints
- API-FIN-V1-110 POST /api/v1/payment-channels/{channel}/sync
- API-FIN-V1-111 GET /api/v1/payment-channels/settlements

## Permissions
- PERM-FIN-110 ManageChannelPolicy
- PERM-FIN-111 ViewChannelSettlement

## Notifications
- NOTIF-FIN-028 Settlement mismatch alert

## Reports
- REP-FIN-025 Channel Settlement Reconciliation

## KPIs
- KPI-FIN-025 Channel settlement accuracy

## Performance Targets
- PERF-FIN-023 settlement sync under 10s for standard batch

## Security Requirements
- SEC-FIN-022

## Acceptance Criteria
- AC-FIN-110
- AC-FIN-111

## Test Cases
- TEST-FIN-110
- TEST-FIN-111

## Migration Notes
Begin by wrapping existing MPESA and bank flows in adapter contracts, then extend to card and EFT channels.

## Open Risks
- RISK-FIN-021

## ADR Links
- ADR-FIN-017 Adapter interface contract
- ADR-FIN-018 Provider fallback strategy
- ADR-FIN-023 CAP-004 and CAP-005 scope alignment
