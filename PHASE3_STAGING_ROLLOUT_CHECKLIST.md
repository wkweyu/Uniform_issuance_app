# Phase 3 Staging and Rollout Checklist

This checklist closes the remaining non-code Phase 3 items for the multi-tenant SaaS rollout.

## 1. Staging Verification

- Confirm the app health endpoint returns HTTP 200 before operator sign-in:
  - `/health`
- Confirm latest migrations are applied in staging.
- Verify platform login at `/platform/login` with a dedicated non-production platform operator account.
- Confirm the smoke account credentials and MFA expectation are recorded in the staging runbook before testing begins.
- Run the platform smoke path end-to-end:
  - onboard a school
  - review onboarding status
  - change subscription plan
  - suspend and restore a subscription
  - create a support ticket from `/platform/support/create`
  - assign and close the ticket from `/platform/support`
  - open dashboard summary and trends endpoints
- Confirm tenant login still works for an active school and is blocked for a suspended school.
- Review platform audit entries for onboarding, subscription, impersonation, and support actions.
- Check that dashboard cards, support queue filters, and pagination render correctly on desktop and mobile widths.

## 2. Data and Safety Checks

- Validate at least one school on each expected subscription state used by ops: `trial`, `active`, `grace_period`, `suspended`.
- Confirm `school_id` is present and enforced on new tenant-scoped writes.
- Review a sample of recent control-plane changes in `/platform/audit` for correct actor, school, and action values.
- Confirm support tickets without assignees remain visible and can be filtered as `Unassigned`.
- Verify dashboard metrics endpoints return HTTP 200 and JSON payloads:
  - `/platform/metrics/summary`
  - `/platform/metrics/trends`

## 3. Rollout Steps

- Deploy to staging and complete the verification checklist above.
- Record the smoke-test school, operator account, and support ticket subject used during staging verification.
- Capture a staging signoff from platform operations or engineering owner.
- Deploy to production behind the agreed maintenance window or low-traffic period.
- Perform a canary verification with one internal tenant first:
  - platform login
  - school onboarding status view
  - subscription update
  - support queue action
  - audit log review
- Expand access to the full operator group after canary checks pass.

## 4. Monitoring After Release

- Watch application logs for tenant resolution failures, auth failures, and database errors.
- Check support ticket creation and assignment within the first hour after release.
- Confirm dashboard trend data populates for the active window.
- Review subscription lifecycle actions in audit logs during the first day.
- Confirm no unexpected tenant cross-visibility is reported.

## 5. Signoff Artifacts

- Record deployment date/time.
- Record staging verifier and production approver.
- Record migration version or commit SHA deployed.
- Record the smoke-test operator account and ticket ID used during validation.
- Record rollback command or deployment target needed to restore previous release.
- Record any post-release issues and their disposition.

## 6. Cleanup

- Close or archive any smoke-test support tickets created during staging and production canary checks.
- Remove or rotate any temporary smoke-test credentials that should not persist after signoff.
- Remove any temporary review schools, subscriptions, and plans created solely for rollout validation after audit evidence is captured.
- Preserve audit evidence needed for signoff before deleting temporary data.

## Exit Criteria

Phase 3 is operationally complete when:

- staging verification is signed off
- production deploy is completed
- canary checks pass
- no tenant isolation regressions are observed
- platform operators can use dashboard, subscriptions, audit, and support queue workflows successfully
