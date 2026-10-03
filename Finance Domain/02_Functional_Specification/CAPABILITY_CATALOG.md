# Capability Catalog

This catalog is the authoritative list of Finance Domain capabilities and starter ownership structure.

## Capability List
- CAP-FIN-001 Financial Setup
- CAP-FIN-002 Billing Engine
- CAP-FIN-003 Accounts Receivable
- CAP-FIN-004 Payment Operations
- CAP-FIN-005 Payment Channel Services
- CAP-FIN-006 Allocation Engine
- CAP-FIN-007 General Ledger
- CAP-FIN-008 Reporting
- CAP-FIN-009 Notifications
- CAP-FIN-010 Workflow Engine
- CAP-FIN-011 Audit and Compliance
- CAP-FIN-012 Security Controls
- CAP-FIN-013 API Platform
- CAP-FIN-014 Parent Self-Service
- CAP-FIN-015 Analytics
- CAP-FIN-016 Automation Scheduler
- CAP-FIN-017 Integration Hub
- CAP-FIN-018 Event Bus

## Delivery Priority Bands
- P0: CAP-FIN-001, CAP-FIN-002, CAP-FIN-003, CAP-FIN-004, CAP-FIN-007, CAP-FIN-011, CAP-FIN-012
- P1: CAP-FIN-005, CAP-FIN-006, CAP-FIN-008, CAP-FIN-009, CAP-FIN-010, CAP-FIN-017, CAP-FIN-018
- P2: CAP-FIN-013, CAP-FIN-014, CAP-FIN-015, CAP-FIN-016

## Lifecycle States
Each capability progresses through:
1. Designed
2. Database ready
3. Backend implemented
4. API complete
5. UI complete
6. Tested
7. Production ready
8. Optimized
9. Enterprise grade

## Scope Alignment Note
- ADR-FIN-023 defines the split between CAP-FIN-004 and CAP-FIN-005.
- CAP-FIN-004 owns payment operations orchestration.
- CAP-FIN-005 owns rail-specific channel behavior and settlement.
