# Implementation Roadmap: School ERP Transformation

This roadmap outlines the steps to implement the suggested improvements and missing features, transforming the current system into a comprehensive, secure, and scalable multi-tenant SaaS School ERP.

---

## Phase 1: Foundation & Security (Weeks 1-4)
*Goal: Resolve technical debt, harden security, and prepare for modular growth.*

### 1.0 Application Core Setup
1.  **Implement `create_app()` Factory**: Refactor `app.py` to move app initialization and configuration into a proper factory function.
2.  **Create `extensions.py`**: Centralize initialization of `db`, `migrate`, `csrf`, and `login_manager` to prevent circular imports.
3.  **Modular Config**: Move database and application configurations into a dedicated `config.py` class structure.
4.  **Service-Oriented Routes**: Ensure routes focus on request handling and delegate business logic entirely to service classes.

### 1.1 Modularization via Blueprints
1.  **Create Directory Structure**: Create a `blueprints/` directory.
2.  **Decouple `app.py`**: To effectively reduce `app.py` from 4,000+ lines to a clean entry point, we will decouple it into **10 specialized blueprints**:
    *   `auth`: Authentication, login, logout, and user session management.
    *   `super_admin`: Platform-level SaaS controls and school onboarding.
    *   `students`: Student admission, profile management, and bulk imports.
    *   `classes`: Class groups, streams, and the promotion engine.
    *   `exams`: Exam series management, grading, and report cards.
    *   `fees`: Fee structures, payments, and student ledgers.
    *   `finance`: General ledger, payment vouchers, and budgeting.
    *   `procurement`: Requisitions, supplier management, and purchase orders.
    *   `fleet`: Bus management, fuel tracking, and service records.
    *   `uniforms`: Uniform issuance, pricing, and stock control.
3.  **Register Blueprints**: Update `app.py` to register these blueprints, significantly reducing its size and complexity.

### 1.2 Unified Data Access (ORM)
1.  **Model Definition**: Complete the transition of all tables in `schema.sql` to SQLAlchemy models in `models.py`.
2.  **Refactor Services**: Update `FeesService`, `ExamManagementService`, etc., to use the ORM instead of raw PyMySQL.
3.  **Audit Queries**: Systematically replace remaining raw SQL strings with SQLAlchemy query builder for better security and maintainability.

### 1.3 Security Hardening
1.  **Password Migration**:
    *   Implement a background task or middleware to upgrade legacy MD5/plain-text hashes to `scrypt` or `bcrypt` upon user login.
    *   Enforce strong password policies.
2.  **CSRF Audit**: Enable CSRF protection globally and carefully implement `X-CSRFToken` headers for all AJAX/Fetch requests.
3.  **Context-Aware Logging**: Integrate a logging framework that captures `school_id` and `user_id` in every log entry for audit trails.

### 1.4 Automatic Multi-Tenant Enforcement
1.  **Tenant Middleware**: Implement a robust middleware to manage `g.school_id` context.
2.  **TenantMixin**: Create a `TenantMixin` for all SQLAlchemy models to ensure `school_id` is always present and indexed.
3.  **Auto-Scoped Queries**: Create a custom SQLAlchemy query class that automatically appends `.filter_by(school_id=g.school_id)` to prevent cross-tenant leakage.
4.  **Forbid Unfiltered Raw Queries**: Establish a policy and audit layer to forbid raw SQL executions that do not include mandatory tenant filters.
5.  **Leakage Testing**: Add a dedicated suite of unit tests specifically designed to detect and prevent cross-tenant data leakage.

### 1.5 Role-Based Access Control (RBAC)
1.  **RBAC Schema**: Implement `roles` and `permissions` tables to decouple authorization from blueprints.
2.  **Permission Decorators**: Create `@permission_required` decorators to control access at a granular level (e.g., `can_edit_fees`, `can_view_exams`).
3.  **Pre-defined Roles**: Seed the system with standard roles: `super_admin`, `school_admin`, `support_staff`, `teacher`, and `accountant`.

### 1.6 Audit Trail System
1.  **Audit Schema**: Create an `audit_logs` table in the database to track relational changes.
2.  **Tracking Metadata**: Record `user_id`, `school_id`, `action` (Create/Update/Delete), `entity_name`, `entity_id`, and a high-resolution `timestamp`.
3.  **Auto-Logging**: Implement a decorator or SQLAlchemy event listener to automatically log sensitive business changes (e.g., fee adjustments, grade changes, user role updates).
4.  **Admin Visibility**: Provide a secure view for super admins to track support staff actions and investigate subscription/billing disputes.

### 1.7 Service Layer Convention
1.  **Strict Architecture**: Enforce a `routes → services → models` flow.
2.  **Decoupled Logic**: Move all validation, data processing, and state-change logic from route handlers into service classes.
3.  **No Direct DB Access**: Forbid routes from accessing the SQLAlchemy session or PyMySQL cursor directly; all data retrieval and persistence must pass through the Service layer.

---

## Phase 2: SaaS Scaling & Onboarding (Weeks 5-6)
*Goal: Streamline school onboarding and subscription management.*

### 2.1 Automated School Onboarding
1.  **Provisioning Engine**: Create a service to provision a new school, including seeding default voteheads, academic years, and the initial admin account.
2.  **Subscription Management**: Enhance middleware to enforce subscription-based access control and manage grace periods.

---

## Phase 3: Core ERP Modules - Part 1 (Weeks 7-11)
*Goal: Implement essential missing features for school operations.*

### 3.1 Attendance Module
1.  **Schema**: Create `attendance` and `attendance_logs` tables.
2.  **Interface**: Build a "Take Attendance" UI for teachers (mobile-responsive).
3.  **Reporting**: Daily/Monthly attendance summaries for parents and administration.

### 3.2 Timetable Management
1.  **Constraints Engine**: Build a logic layer to prevent teacher or room double-booking.
2.  **Generator**: Drag-and-drop UI for creating weekly class schedules.
3.  **Views**: Personal timetables for students and teachers.

### 3.3 Communication Suite (SMS/Email)
1.  **Integration**: Connect with a gateway (e.g., Africa's Talking, Twilio).
2.  **Automated Alerts**:
    *   Fee payment confirmations.
    *   Absence notifications.
    *   Exam result releases.

---

## Phase 4: Core ERP Modules - Part 2 (Weeks 12-16)
*Goal: Financial and Administrative completeness.*

### 4.1 HR & Payroll
1.  **Staff Management**: Track contracts, qualifications, and leave balances.
2.  **Payroll Engine**: Automated monthly salary generation considering allowances and deductions.
3.  **Integration**: Automatic posting of payroll expenses to the General Ledger.

### 4.2 Library Management
1.  **Cataloging**: ISBN integration for quick book entry.
2.  **Circulation**: Track issues, returns, and automatic fine calculation.

---

## Phase 5: Portals & Analytics (Weeks 17+)
*Goal: Stakeholder engagement and data-driven decisions.*

### 5.1 Parent/Student Portal
1.  **Dashboard**: View-only access to marks, attendance, and fee statements.
2.  **Online Payments**: Integrate checkout for fees (Stripe, M-Pesa, etc.).

### 5.2 Executive Analytics
1.  **Performance Charts**: Visual trends for enrollment, revenue, and academic performance across terms/years.
2.  **Predictive Alerts**: Identification of students at risk of dropout or academic failure.
