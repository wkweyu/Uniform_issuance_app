# Implement SaaS Multitenancy Control Plane

Purpose
-------
Add a secure, production-grade control plane (platform) to the existing Flask + MySQL school management app. The control plane provides tenant (school) lifecycle and platform-level features while preserving and maintaining all existing tenant modules.

Constraints
-----------
- Do NOT break or require changes to existing tenant modules' runtime behavior.
- The app will keep a shared database; tenant isolation is enforced by `school_id` on tenant data.
- New code should live under a new blueprint named `platform` (or `platform_bp`) and new package `platform/`.

High-level Architecture
-----------------------
- Platform blueprint: independent Flask blueprint mounted at `/platform` (or configurable prefix).
- Shared MySQL database. Tenant isolation uses `school_id` in all applicable tables.
- Middleware resolves current tenant for tenant-facing endpoints and enforces filtering for queries.
- Platform users and admin features are separate from tenant users.

Control Plane Features (Overview)
---------------------------------
- School management (CRUD + metadata)
- Plans and pricing (CRUD)
- Subscriptions and billing metadata
- Platform users with RBAC (roles: `super_admin`, `platform_admin`, `support`, `account_manager`)
- Support tickets tied to schools
- Audit logs for all write actions
- School onboarding wizard (initial setup flow)
- Impersonation (admin logs and audit trail)
- Usage and metrics dashboard

Security Requirements
---------------------
- Hash platform user passwords with `bcrypt` (work factor configurable).
- Role-Based Access Control (RBAC) for platform routes.
- Tenant isolation enforced at application layer and validated in queries.
- Audit trail for every mutation including impersonation events.
- Never expose cross-tenant data to users without explicit platform-level access.

Database Models (suggested)
---------------------------
Minimal fields are listed — extend as needed.

- `schools` (School)
	- `id` (PK), `name`, `code`, `timezone`, `status`, `created_at`, `metadata` (json)

- `plans` (Plan)
	- `id`, `name`, `price_cents`, `billing_period` (monthly/annual), `features` (json), `created_at`

- `subscriptions` (Subscription)
	- `id`, `school_id` (FK->schools.id), `plan_id`, `status`, `started_at`, `renewal_date`, `billing_meta` (json)

- `platform_users` (PlatformUser)
	- `id`, `email` (unique), `password_hash`, `role`, `assigned_school_id` (nullable, for account_manager), `created_by`, `created_at`, `last_login_at`

- `support_tickets` (SupportTicket)
	- `id`, `school_id`, `raised_by_email`, `subject`, `description`, `status`, `assigned_to_user_id`, `created_at`, `updated_at`

- `audit_logs` (AuditLog)
	- `id`, `actor_user_id` (nullable), `actor_platform` (boolean), `action`, `target_table`, `target_id`, `school_id` (nullable), `changes` (json), `ip`, `created_at`

Notes
-----
- Add indexes for `school_id` on tables used in tenant queries.
- Use `unique` constraints where applicable (e.g., `plans.name`).

Coding Rules & Patterns
-----------------------
- Reuse existing authentication/session logic where appropriate; keep tenant and platform auth separate.
- Implement decorators:
	- `@platform_required` — restrict to platform users.
	- `@tenant_required` — restrict to tenant-scoped users (existing behavior).
- Keep business logic modular: controllers (routes), services (business rules), models, templates.
- Avoid duplicating tenant logic; call into existing services where possible.
- Maintain backward compatibility by adding non-breaking migrations and feature flags during rollout.

Routing and Blueprint
---------------------
- Create `platform` blueprint (e.g., `platform/__init__.py`) and register at app initialization:

	- `platform/schools.py` → school CRUD
	- `platform/plans.py` → plan CRUD
	- `platform/subscriptions.py` → subscription management
	- `platform/users.py` → platform user management + roles
	- `platform/support.py` → support tickets
	- `platform/audit.py` → audit log viewer (admin only)

Middleware & Tenant Resolution
-----------------------------
- Implement middleware that sets `g.current_school_id` for tenant routes. Resolution order may be: subdomain → header `X-School-ID` → session.
- Example pseudo-code (flask):

```py
def tenant_middleware(app):
		@app.before_request
		def resolve_tenant():
				# prefer subdomain, then header, then session
				school_id = resolve_from_subdomain() or request.headers.get('X-School-ID') or session.get('school_id')
				g.current_school_id = int(school_id) if school_id else None

				# optionally reject tenant-less requests to tenant endpoints
```

- Add SQL helper utilities that automatically inject `school_id` into `WHERE` clauses or use ORM-level filters.

Decorators
----------
- `@platform_required`: verify platform user session + role checks.
- `@tenant_required`: verify `g.current_school_id` and that the logged-in user is authorized for that tenant.

Example decorator sketch:

```py
def platform_required(role=None):
		def decorator(fn):
				@wraps(fn)
				def wrapper(*args, **kwargs):
						if 'platform_user_id' not in session:
								return redirect(url_for('platform.login'))
						user = load_platform_user(session['platform_user_id'])
						if role and user.role != role:
								abort(403)
						return fn(*args, **kwargs)
				return wrapper
		return decorator
```

Impersonation
-------------
- Allow `super_admin` or `platform_admin` to impersonate a tenant user for support, with strict logging.
- Log impersonation start/end in `audit_logs` with `impersonation=true` metadata and store `original_user_id` in session only for duration.

Audit Logging
-------------
- Centralize audit logging via a service `audit.log(actor_id, action, target_table, target_id, school_id, changes)`.
- Log all writes: create, update, delete; include diffs in `changes` JSON.

Migrations & Backward Compatibility
----------------------------------
- Add `school_id` to existing tenant tables using safe, non-blocking migrations:
	1. Create nullable `school_id` column.
	2. Backfill values via map or admin tool.
	3. Add NOT NULL constraint and index once backfilled.
- Avoid downtime by using per-table migration steps and monitoring long-running ALTERs.

Implementation Plan (step-by-step)
---------------------------------
1. Create `platform/` package with blueprint scaffolding and route stubs.
2. Add DB models and initial migrations for `schools`, `plans`, `subscriptions`, `platform_users`, `support_tickets`, `audit_logs`.
3. Implement platform auth (bcrypt), login, and RBAC.
4. Implement middleware and `@platform_required` decorator.
5. Implement school CRUD + onboarding wizard (forms + templates).
6. Implement plans and subscription management (non-billing first: metadata only).
7. Implement platform users management + impersonation with audit logging.
8. Add support ticket flow and linking to tenant records.
9. Add usage/metrics collection endpoints (simple counters + dashboard views).
10. Add tests, security review, and staging rollout.

Deliverables
------------
- `platform/models.py` (or package models)
- `migrations/` (alembic/SQL migration scripts)
- `platform/routes/*.py` (CRUD + admin views)
- `platform/decorators.py` (`platform_required`, `tenant_required`)
- `platform/services/*.py` (onboarding, billing metadata, audit)
- Admin templates under `templates/platform/`
- Example middleware and documentation in `platform/README.md`

Testing & Rollout
-----------------
- Deploy to staging behind feature flag.
- Run data migrations with backfill in staging first.
- Test: school onboarding, platform login, impersonation, RBAC checks, audit logs.
- Rollout to production with a canary group of schools if feasible.

Notes & Recommendations
-----------------------
- Keep platform and tenant authentication separate to reduce risk of accidental cross-privileges.
- For billing or payments, integrate a third-party provider and store only billing metadata in `subscriptions`.
- Consider rate-limiting platform endpoints and adding SSO for platform users.

Example quick schema (SQL)
```sql
CREATE TABLE schools (
	id INT AUTO_INCREMENT PRIMARY KEY,
	name VARCHAR(255) NOT NULL,
	code VARCHAR(64) UNIQUE,
	timezone VARCHAR(64),
	status VARCHAR(32) DEFAULT 'active',
	metadata JSON,
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE platform_users (
	id INT AUTO_INCREMENT PRIMARY KEY,
	email VARCHAR(255) NOT NULL UNIQUE,
	password_hash VARCHAR(255) NOT NULL,
	role VARCHAR(32) NOT NULL,
	assigned_school_id INT NULL,
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

If you want, I can now:
- generate the `platform/` package scaffold and route stubs, or
- create the first migrations and model files for `schools` and `platform_users`.

Which of these should I implement first?
