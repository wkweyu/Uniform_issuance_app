# CAP-FIN-002: Billing Engine

## Purpose
Generate and maintain billable charges across all billing dimensions and charge cycles.

## Owner
- Primary: Finance Product Owner
- Secondary: Billing Technical Lead

## Business Goal
Provide accurate, configurable, and repeatable billing for school-specific programs and student obligations.

## Stakeholders
- Bursar
- Admissions
- Transport Office
- Hostel Admin
- Exams Office
- Parents

## Dependencies
- CAP-FIN-001
- CAP-FIN-003
- CAP-FIN-010
- CAP-FIN-016
- CAP-FIN-017

## Business Rules
- BR-FIN-004
- BR-FIN-005
- BR-FIN-007
- BR-FIN-011
- BR-FIN-012

## Workflows
- WF-FIN-004 Bulk Billing Run
- WF-FIN-005 Student-specific Billing
- WF-FIN-006 Credit and Debit Note Issuance

## Database Objects
- DB-FIN-013 InvoiceHeader
- DB-FIN-014 InvoiceLine
- DB-FIN-015 BillingPlan
- DB-FIN-016 RecurringSchedule
- DB-FIN-017 DebitNote
- DB-FIN-018 CreditNote
- DB-FIN-019 InstallmentPlan

## Services and Use Cases
- BillingRunService
- InvoiceService
- RecurringChargeService
- NoteManagementService

## Events
- EVT-FIN-001 InvoiceCreated
- EVT-FIN-002 InvoicePosted
- EVT-FIN-012 BillingRunCompleted

## API Endpoints
- API-FIN-V1-010 POST /api/v1/invoices/generate
- API-FIN-V1-011 POST /api/v1/invoices/regenerate
- API-FIN-V1-012 POST /api/v1/invoices/notes

## Permissions
- PERM-FIN-010 CreateInvoice
- PERM-FIN-011 RegenerateInvoice
- PERM-FIN-012 IssueCreditDebitNote

## Notifications
- NOTIF-FIN-001 Invoice published
- NOTIF-FIN-011 Billing failure alert

## Reports
- REP-FIN-001 Billing Register
- REP-FIN-013 Invoice Variance Report

## KPIs
- KPI-FIN-003 Billing completion rate
- KPI-FIN-004 Regeneration frequency

## Performance Targets
- PERF-FIN-006 bulk billing batch throughput target
- PERF-FIN-002 statement generation dependency target

## Security Requirements
- SEC-FIN-007 note issuance approval and traceability

## Acceptance Criteria
- AC-FIN-010
- AC-FIN-011
- AC-FIN-012

## Test Cases
- TEST-FIN-010
- TEST-FIN-011
- TEST-FIN-012
- TEST-FIN-013

## Migration Notes
Dual-write invoice references to legacy structures during transition; switch read models after parity signoff.

## Open Risks
- RISK-FIN-001
- RISK-FIN-004

## ADR Links
- ADR-FIN-003 Billing scope hierarchy
- ADR-FIN-004 Credit and debit note behavior
