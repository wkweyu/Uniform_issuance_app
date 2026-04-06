Platform Control Plane
======================

Overview
--------
`platform_bp` provides the SaaS control plane mounted at `/platform`.

Current scope
-------------
- school CRUD and onboarding
- plans and subscription lifecycle operations
- subscription pricing now resolves active enrolled student counts from the Students module, preferring current class allocations with legacy allocation fallback
- super-admin guarded school activation, subscription assignment, and lifecycle controls
- persisted platform rollout settings UI at `/platform/settings/access`
- staged operator segmentation for billing-only and support-only control-plane access
- rollout settings history panels with previous-versus-updated state on the access settings page
- optional school portfolio scoping for platform operators through `assigned_school_id` and `portfolio_scope`
- editable platform-user scope assignments after creation through the platform user directory
- filterable platform-user directory with last-login visibility and recent per-user audit history
- platform users, login, and impersonation
- support ticket queue with assignment and status transitions
- audit logging and audit review
- dashboard metrics cards plus JSON metrics endpoints

Quick registration
------------------
In `app.py` or your app factory call:

```py
from platform_bp import init_platform
init_platform(app, url_prefix='/platform')
```

Key files
---------
- `platform_bp/models.py`: platform ORM models
- `platform_bp/decorators.py`: route protection
- `platform_bp/middleware.py`: platform middleware hook
- `platform_bp/routes/`: platform HTTP routes
- `platform_bp/services/onboarding.py`: onboarding provisioning
- `platform_bp/services/subscriptions.py`: subscription lifecycle logic
- `platform_bp/services/support.py`: support queue workflow
- `platform_bp/services/audit.py`: audit logging and queries
- `platform_bp/services/metrics.py`: dashboard summaries and trend windows
- `platform_smoke_tests.py`: executable rollout smoke test for `/platform/*`
- `PHASE8_CONTROL_PLANE_GO_LIVE.md`: control-plane staging and production go-live runbook

Metrics endpoints
-----------------
- `/platform/metrics/summary?window_days=7`
- `/platform/metrics/trends?window_days=30`

Rollout checklist
-----------------
1. Run the SaaS/platform migrations in staging.
2. Seed at least one `platform_admin` or `super_admin`.
3. Verify onboarding, subscriptions, support queue, audit log, and dashboard metrics in staging.
4. Validate impersonation audit events and suspended-school enforcement.
5. Restrict `/platform` to platform users only before production exposure.
6. Roll out behind a feature flag or limited operator group if needed.
7. Run `platform_smoke_tests.py` and capture the output for staging and production signoff.

Rollout controls
----------------
- `PLATFORM_ROLLOUT_MODE=open`: allow all authenticated platform users.
- `PLATFORM_ROLLOUT_MODE=allowlist`: allow only `super_admin` plus emails in `PLATFORM_ROLLOUT_ALLOWED_EMAILS` or roles in `PLATFORM_ROLLOUT_ALLOWED_ROLES`.
- `PLATFORM_ROLLOUT_MODE=roles`: allow only `super_admin` plus roles in `PLATFORM_ROLLOUT_ALLOWED_ROLES`.
- `PLATFORM_ROLLOUT_ALLOWED_EMAILS`: comma-separated email allowlist for controlled launch.
- `PLATFORM_ROLLOUT_ALLOWED_ROLES`: comma-separated role allowlist for controlled launch.
- `TENANT_ENFORCEMENT_MODE`: `open`, `audit`, or `enforce` for staged tenant subscription and entitlement blocking.
- `TENANT_ENFORCEMENT_NOTES`: operator notes or rollout signoff text for the current tenant enforcement mode.
- The same rollout settings can now be changed in the control plane without editing environment variables through `/platform/settings/access`.

Privilege boundaries
--------------------
- `platform_admin` keeps broad operational access across billing, support, audit, onboarding, and plan management, but not the dedicated security surface.
- `security` is a dedicated operator role for the security events surface and notification preferences.
- `billing` and legacy `account_manager` roles are limited to school, subscription, plan, and audit review surfaces.
- `support` is limited to the support queue plus dashboard visibility.
- `super_admin` is required for school creation, school activation/deactivation, subscription window changes, subscription assignment, subscription lifecycle mutations, and platform rollout settings.
- Successful credential checks that are denied by rollout gating are logged as `platform_login_rollout_denied` audit events.

Portfolio scoping
-----------------
- `assigned_school_id` provides a fixed single-school scope for an operator.
- `portfolio_scope` can store `school_ids` to limit billing, support, and security operators to a defined set of schools.
- Existing platform users can be edited after creation so scope assignments, role, and activation state can be updated without recreating the account.
- The platform user directory renders assigned-school and portfolio scope as school-name badges instead of raw ids.
- The platform user directory can be filtered by search, role, status, and school scope, and edit pages include recent `platform_user_*` audit history for the selected operator.
- Billing-scoped users are filtered on school lists, subscription lists, subscription detail, and audit views.
- Support-scoped users are filtered on support queue lists and blocked from mutating tickets outside their school portfolio.
- Security-scoped users are filtered on security event lists, exports, notification preferences, and delivery history, and they cannot acknowledge, resolve, or configure notifications outside their portfolio.

Notes
-----
- `School` is defined in `models.py` and reused here.
- Models use the shared application `db` instance.
- Remaining production readiness work is operational: staged verification, access review, and rollout control.
