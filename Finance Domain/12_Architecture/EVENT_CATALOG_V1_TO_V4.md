# Event Catalog v1-v4

## Core Lifecycle Events
- EVT-FIN-001 InvoiceCreated
- EVT-FIN-002 InvoicePosted
- EVT-FIN-003 PaymentReceived
- EVT-FIN-004 ReceiptIssued
- EVT-FIN-005 ReceiptReversed
- EVT-FIN-006 RefundApproved
- EVT-FIN-007 LedgerPosted
- EVT-FIN-008 StatementGenerated

## Financial Configuration and Billing Events
- EVT-FIN-009 FinancialPeriodLocked
- EVT-FIN-010 FinancialPolicyChanged
- EVT-FIN-011 ReceiptSeriesUpdated
- EVT-FIN-012 BillingRunCompleted

## Payment and GL Reliability Events
- EVT-FIN-013 PaymentCallbackValidated
- EVT-FIN-014 ReconciliationCaseOpened
- EVT-FIN-015 JournalReversalPosted
- EVT-FIN-016 TrialBalanceGenerated

## Audit and Security Events
- EVT-FIN-017 AuditEvidenceCaptured
- EVT-FIN-018 RetentionPolicyExecuted
- EVT-FIN-019 StepUpChallengeIssued
- EVT-FIN-020 SoDViolationDetected

## Workflow and Integration Reliability Events
- EVT-FIN-021 WorkflowStepAssigned
- EVT-FIN-022 WorkflowEscalated
- EVT-FIN-023 WorkflowCompleted
- EVT-FIN-024 IntegrationHealthDegraded
- EVT-FIN-025 IntegrationRecovered

## Event Bus and Scheduler Events
- EVT-FIN-026 DeadLetterThresholdBreached
- EVT-FIN-027 ConsumerLagBreached
- EVT-FIN-028 ScheduledJobStarted
- EVT-FIN-029 ScheduledJobCompleted

## Channel, Reporting, API, Parent, Analytics Events
- EVT-FIN-030 ChannelSettlementSynced
- EVT-FIN-031 ChannelFeePolicyChanged
- EVT-FIN-032 AllocationDecisionApplied
- EVT-FIN-033 ReallocationRequested
- EVT-FIN-034 ReportExportCompleted
- EVT-FIN-035 NotificationDispatched
- EVT-FIN-036 ReminderCampaignCompleted
- EVT-FIN-037 ApiContractDeprecated
- EVT-FIN-038 ParentFinanceAccessed
- EVT-FIN-039 ForecastRunCompleted

## Mandatory Event Contract Fields
For each EVT-FIN entry, document:
- Producer
- Consumers
- Payload schema
- Retry policy
- Idempotency key
- Audit linkage (AUD-FIN)
- Test linkage (TEST-FIN)
