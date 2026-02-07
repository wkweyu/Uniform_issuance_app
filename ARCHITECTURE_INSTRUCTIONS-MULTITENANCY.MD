Copilot Task — STRICT Multi-Tenant Refactor for Monolithic Flask app.py

You are modifying an existing PRODUCTION Flask + SQLAlchemy application.

IMPORTANT CONTEXT:

ALL models, routes, and logic are inside ONE file: app.py

The system currently supports only ONE school

It already has live features (fees, students, finance, reports)

We are converting to MULTI-TENANT SaaS

We MUST NOT break existing functionality

❗ HARD RULES (NEVER VIOLATE)

You MUST:

DO NOT rewrite the application

DO NOT split files

DO NOT refactor unrelated code

DO NOT bulk edit

DO NOT modify multiple models at once

DO NOT auto-replace all queries

ONLY change what is explicitly requested

AFTER each step → STOP

AFTER each step → list modified lines/files

Always preserve backward compatibility

If unsure → ask, do not guess.

🎯 FINAL GOAL

Convert app.py into a multi-tenant SaaS where:

multiple schools share same database

each record belongs to a school

login requires school code

data is isolated per school

no cross-school data leaks

🔵 PHASE 0 — AUDIT FIRST (MANDATORY)

Before writing any code:

Scan entire app.py

List ALL:

SQLAlchemy models

tables

routes performing queries

Output them grouped by:

Students

Fees

Payments

Finance

Reports

Auth

DO NOT change code yet.

STOP after listing.

🔵 PHASE 1 — Foundation Only

Create ONLY:

School model

Add:

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    code = db.Column(db.String(20), unique=True, index=True)
    is_active = db.Column(db.Boolean, default=True)
    subscription_end = db.Column(db.Date)


Generate migration.

Do not touch other models.

STOP.

🔵 PHASE 2 — Authentication

Modify ONLY login logic:

add school_code field

find school first

authenticate user inside that school

store:

session["school_id"]


Do not change other routes.

STOP.

🔵 PHASE 3 — Tenant Middleware

Add:

current_school_id() helper

before_request hook

g.school_id

Do not modify models yet.

STOP.

🔵 PHASE 4 — Model Migration (ONE MODEL AT A TIME)

For each model listed in Phase 0:

When instructed:

ONLY modify that single model:

Add:

school_id = db.Column(db.Integer, db.ForeignKey("school.id"), index=True)


Create migration:

default existing rows → school_id=1

Update ONLY that model’s queries to:

.filter_by(school_id=g.school_id)


DO NOT modify other models yet.

STOP.

Repeat per model.

🔵 PHASE 5 — Reports & Aggregations (CRITICAL)

Audit ALL:

summaries

totals

statements

balance sheets

exports

Ensure EVERY query filters by school_id.

Reports MUST NEVER aggregate across schools.

Modify one report at a time.

STOP after each.

🔵 PHASE 6 — Admin SaaS Controls

Add:

super admin routes

create school

set subscription

activate/deactivate

Do not mix with school routes.

🔒 SAFETY REQUIREMENTS

Never allow:

Model.query.all()


Always:

Model.query.filter_by(school_id=g.school_id)


Never expose cross-tenant data.

🔴 GENERATION RULE

When I request a step:

ONLY implement that step.

NEVER continue automatically.

NEVER modify unrelated sections of app.py.

END

 forces full audit first
✔ prevents missed tables
✔ prevents silent data leaks
✔ avoids mass edits
✔ guarantees step-by-step
✔ safest possible approach

This is exactly how a senior backend engineer would migrate a live ERP.

If you'd like, next I can:
👉 help you execute Phase 0 (audit) and list every model + route in your app.py so you know exactly what must be migrated.

Is this conversation helpful so far?
Want to upload more files? Try Plus for free. Your upload limit will reset tomorrow after 9:01 AM.
Try Plus free




