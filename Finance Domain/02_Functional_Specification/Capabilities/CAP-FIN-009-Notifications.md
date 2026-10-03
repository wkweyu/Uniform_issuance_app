# CAP-FIN-009: Notifications

## Purpose
Publish finance event communications to configured channels with preference and compliance controls.

## Owner
- Primary: Communications Platform Lead
- Secondary: Collections Operations Lead

## Business Goal
Improve collection outcomes and stakeholder transparency with timely, policy-safe communications.

## Stakeholders
- Parents
- Bursar
- Finance Manager
- Support
- Compliance

## Dependencies
- CAP-FIN-003
- CAP-FIN-004
- CAP-FIN-010
- CAP-FIN-017
- CAP-FIN-018

## Business Rules
- BR-FIN-043
- BR-FIN-044

## Workflows
- WF-FIN-040 Event Notification Dispatch
- WF-FIN-041 Reminder Campaign Schedule

## Database Objects
- DB-FIN-064 NotificationTemplate
- DB-FIN-065 NotificationPreference
- DB-FIN-066 NotificationDispatchLog

## Services and Use Cases
- NotificationTemplateService
- NotificationDispatchService
- ReminderCampaignService
- PreferenceEnforcementService

## Events
- EVT-FIN-035 NotificationDispatched
- EVT-FIN-036 ReminderCampaignCompleted

## API Endpoints
- API-FIN-V1-140 POST /api/v1/notifications/send
- API-FIN-V1-141 POST /api/v1/notifications/campaigns/run

## Permissions
- PERM-FIN-140 ManageTemplates
- PERM-FIN-141 SendCampaign

## Notifications
- NOTIF-FIN-031 Fee due reminder
- NOTIF-FIN-032 Outstanding escalation reminder

## Reports
- REP-FIN-030 Notification Delivery Performance

## KPIs
- KPI-FIN-028 Delivery success rate
- KPI-FIN-029 Reminder conversion rate

## Performance Targets
- PERF-FIN-026 event-triggered dispatch enqueue under 500ms p95

## Security Requirements
- SEC-FIN-025

## Acceptance Criteria
- AC-FIN-140
- AC-FIN-141

## Test Cases
- TEST-FIN-140
- TEST-FIN-141

## Migration Notes
Retain current SMS/email pathways while introducing event-driven dispatch and template approval controls.

## Open Risks
- RISK-FIN-024

## ADR Links
- ADR-FIN-028 Notification template governance
- ADR-FIN-029 Campaign suppression policy
