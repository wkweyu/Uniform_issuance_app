# CAP-FIN-016: Automation Scheduler

## Purpose
Run time-based finance jobs reliably for reminders, reconciliations, accruals, and periodic controls.

## Owner
- Primary: Platform Automation Lead
- Secondary: Finance Operations Lead

## Business Goal
Ensure predictable execution of recurring finance operations without operator dependency.

## Stakeholders
- Bursar
- Finance Operations
- Support
- Compliance

## Dependencies
- CAP-FIN-009
- CAP-FIN-010
- CAP-FIN-017
- CAP-FIN-018

## Business Rules
- BR-FIN-033
- BR-FIN-034

## Workflows
- WF-FIN-025 Nightly Reconciliation Trigger
- WF-FIN-026 Reminder Campaign Dispatch Trigger
- WF-FIN-027 Month-End Close Preparatory Jobs

## Database Objects
- DB-FIN-071 ScheduledJobDefinition
- DB-FIN-072 ScheduledJobRun
- DB-FIN-073 JobExecutionLease
- DB-FIN-074 JobFailureIncident

## Services and Use Cases
- JobDefinitionService
- JobDispatcherService
- JobRunCoordinator
- JobFailureRecoveryService

## Events
- EVT-FIN-027 ScheduledJobStarted
- EVT-FIN-028 ScheduledJobFailed
- EVT-FIN-029 ScheduledJobCompleted

## API Endpoints
- API-FIN-V1-145 POST /api/v1/scheduler/jobs
- API-FIN-V1-146 POST /api/v1/scheduler/jobs/{job_id}/run
- API-FIN-V1-147 GET /api/v1/scheduler/runs

## Permissions
- PERM-FIN-145 ManageScheduledJobs
- PERM-FIN-146 RunScheduledJobs
- PERM-FIN-147 ViewSchedulerRuns

## Notifications
- NOTIF-FIN-035 Scheduled job failure alert
- NOTIF-FIN-036 Scheduler backlog warning

## Reports
- REP-FIN-033 Scheduler Reliability Report
- REP-FIN-034 Job Failure Heatmap

## KPIs
- KPI-FIN-032 Scheduled job success rate
- KPI-FIN-033 On-time execution rate

## Performance Targets
- PERF-FIN-021 trigger-to-start latency under 60s p95

## Security Requirements
- SEC-FIN-020

## Acceptance Criteria
- AC-FIN-100: Jobs run once per schedule despite multi-node deployment.
- AC-FIN-101: Retry and dead-letter policies are configurable by job class.
- AC-FIN-102: Failure incidents carry tenant, correlation, and remediation metadata.

## Test Cases
- TEST-FIN-100 Multi-node lease contention and single-run guarantee
- TEST-FIN-101 Retry exhaustion and failure incident generation
- TEST-FIN-102 Backfill run behavior for missed schedules

## Migration Notes
- Move cron-like scripts into scheduler job definitions with run metadata persistence.
- Maintain a temporary dual-run window and compare outcomes before cutover.

## Open Risks
- RISK-FIN-033: Clock skew across nodes may produce duplicate dispatch attempts.
- RISK-FIN-034: Unbounded retries can starve critical queues.

## ADR Links
- ADR-FIN-025 Scheduler topology and lease model

