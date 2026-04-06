# Phase 8: SaaS Control Plane Go-Live

Status: Ready for execution
Date: April 5, 2026

Phase 8 is the operational rollout phase for the SaaS control plane. The application code, permissions model, staged rollout controls, and portfolio scoping are already implemented. This phase closes the remaining deployment gap with a concrete staging and production runbook.

## Scope

This phase covers:

- staged deployment verification for `/platform/*`
- rollout-mode validation through the access settings UI
- operator smoke testing with a real platform account
- go-live signoff and rollback preparation

This phase does not introduce new billing or tenancy features. It packages the implemented control-plane work into a repeatable operational release process.

## Preconditions

- Database migrations for platform tables and access settings are already applied.
- At least one `super_admin` platform operator exists.
- The Flask app can start successfully in the target environment.
- SMTP and external SIEM credentials are configured if those integrations are expected to be live.

## Pre-Deployment

1. Confirm the app starts in the target environment.
   Command:
   ```bash
   cd '/home/frappe-user/uniform issuance app'
   source venv/bin/activate
   python3 app.py
   ```

2. Verify the regression baseline.
   Command:
   ```bash
   "/home/frappe-user/uniform issuance app/venv/bin/python" -m pytest tests/test_platform_routes.py tests/test_tenancy.py
   ```

3. Confirm a platform operator credential set exists for rollout testing.
   Minimum recommended roles:
   - `super_admin`
   - `security`
   - `billing`
   - `support`

4. Record rollback inputs before deployment.
   Capture:
   - current git revision
   - deployment timestamp
   - last known-good release target
   - latest database backup location

## Smoke Test

Run the dedicated control-plane smoke test after deployment to staging and again in production.

Command:
```bash
cd '/home/frappe-user/uniform issuance app'
source venv/bin/activate
python3 platform_smoke_tests.py \
  --base-url http://127.0.0.1:5000 \
  --email '<super-admin-email>' \
  --password '<super-admin-password>'
```

The smoke test verifies:

- platform login form and CSRF rendering
- unauthenticated redirects to `/platform/login`
- successful platform login
- dashboard and metrics endpoints
- schools, subscriptions, support, audit, security, access settings, and users pages
- CSV exports for schools, subscriptions, audit, and security events
- logout and session teardown

## Staging Validation

1. Log in at `/platform/login` with a staging `super_admin`.
2. Open `/platform/settings/access` and verify the rollout mode matches the intended staging posture.
3. Confirm `/platform/users` shows operator scope badges, filters, and edit history.
4. Confirm `/platform/security/events` loads and respects security operator portfolio scoping.
5. Confirm `/platform/subscriptions` and `/platform/schools` load with expected tenant visibility.
6. Confirm `/platform/audit` shows recent rollout and operator-management events.
7. Run the smoke script above and save the output to the release record.

Recommended evidence to keep:

- smoke test output
- screenshot of rollout settings page
- screenshot of security events page
- screenshot of user directory showing operator scope badges

## Production Rollout

1. Deploy the approved release.
2. Log in with the production `super_admin`.
3. Keep rollout mode restricted at first:
   - `roles` with a limited operator set, or
   - `allowlist` with named operator emails
4. Run `platform_smoke_tests.py` against production.
5. Validate recent audit events for:
   - `platform_login_succeeded`
   - `platform_access_settings_updated`
   - `platform_user_updated`
   - `platform_login_rollout_denied` if allowlist testing is part of launch
6. Expand rollout mode only after smoke tests and audit review pass.

## Role-Specific Checks

After the super-admin smoke run, validate at least one scoped operator account per functional area:

1. Billing operator:
   - can view scoped schools and subscriptions
   - cannot access support or security surfaces

2. Support operator:
   - can view and update scoped tickets
   - cannot access billing or security surfaces

3. Security operator:
   - can view scoped events and notification preferences
   - cannot access out-of-scope schools or global notification scope when portfolio-limited

## Rollback

Rollback trigger examples:

- platform login failure for known-good operator accounts
- broken dashboard or metrics responses
- access settings page failing to load or save
- scoped operators seeing data outside their portfolio

Rollback steps:

1. Revert the deployment target to the last known-good release.
2. Restore the latest backup if a migration-related issue occurred.
3. Re-run `platform_smoke_tests.py` against the restored environment.
4. Confirm `/platform/login` and `/platform/settings/access` are healthy before re-opening access.

## Signoff

Phase 8 is complete when all of the following are true:

- platform regression suite passed before deployment
- smoke test passed in the target environment
- rollout settings reviewed by the release owner
- scoped-role validation completed for billing, support, and security
- rollback data recorded
- deployment evidence attached to the release record

## Deliverables

- `platform_smoke_tests.py`
- this runbook
- saved smoke-test output from staging and production