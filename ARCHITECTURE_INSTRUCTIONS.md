🚀 Copilot Task — Convert Existing Flask School App to Multi-Tenant SaaS (SAFE REFACTOR)

You are modifying an existing, working Flask + MySQL School Management System.

The system currently:

supports only ONE school

contains hardcoded configurations

uses a single database

already has students, fees, finance, admissions, etc.

You must convert it into a multi-tenant SaaS system.

❗ CRITICAL RULES (MANDATORY)

You MUST follow these strictly:

DO NOT rewrite the application

DO NOT delete existing logic

DO NOT rename existing tables unless necessary

DO NOT break existing routes

DO NOT refactor everything at once

ONLY make incremental changes

Use database migrations only (Flask-Migrate)

Add new layers around existing code

Maintain backward compatibility

Assume production data exists

If a change could break current features, create a wrapper or extension instead.

🎯 Final Goal

Transform system into:

Multi-tenant SaaS where:

many schools share same app URL

each school has isolated data

login requires:

school code

username

password

I (system owner) control:

onboarding

subscriptions

activation/deactivation

existing single-school data continues working

✅ IMPLEMENTATION PLAN (FOLLOW EXACT ORDER)

When generating code, ONLY implement ONE STEP at a time.

STEP 1 — Create School Model ONLY

Generate:

SQLAlchemy model

migration

no other changes

Model:

class School(db.Model):
    __tablename__ = "schools"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(20), unique=True, index=True)
    is_active = db.Column(db.Boolean, default=True)
    subscription_end = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


Rules:

code must be auto-generated

do NOT touch other tables yet

STOP after generating this step.

STEP 2 — Add school_id to Users ONLY

Modify ONLY User model:

Add:

school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), index=True)


Requirements:

create migration

set default school_id = 1 for existing users

do not modify other models

STOP.

STEP 3 — Modify Login Flow ONLY

Update login to:

Fields:

school_code

username

password

Logic:

find school by code

check active + subscription

authenticate user within that school only

Example query:

User.query.filter_by(
    username=form.username.data,
    school_id=school.id
).first()


Store:

session["school_id"]


Do not change anything else.

STOP.

STEP 4 — Add Tenant Helper + Middleware

Create:

app/tenant.py


Functions:

def current_school_id():
    return session.get("school_id")


Add request hook:

@app.before_request


Purpose:

enforce tenant isolation

Do NOT modify models yet.

STOP.

STEP 5 — Gradually Add school_id to Business Tables

When asked later, modify ONE model at a time:

Examples:

Student

Fees

Payments

Classes

Voteheads

Structures

Rules:

add school_id FK

create migration

set existing rows → school_id=1

update queries to filter by school_id

NEVER change multiple models at once

STEP 6 — Create Super Admin Panel

Create new blueprint:

/admin


Features:

create school

auto-generate code

activate/deactivate

set subscription dates

view schools list

This admin must NOT belong to any tenant.

STEP 7 — Replace Hardcoding

Move hardcoded:

voteheads

terms

settings

Into database tables.

Never hardcode again.

🔒 DATA SAFETY RULES

All queries MUST include:

.filter_by(school_id=current_school_id())


Never allow cross-school reads.

🧠 CODING STANDARDS

Use:

Flask blueprints

SQLAlchemy ORM

service layer

migrations

small commits

no inline SQL

Avoid:

global state

hardcoded values

full rewrites

❗ GENERATION RULE

When I ask for code:

Only generate code for the current step I request.

Never regenerate entire project.