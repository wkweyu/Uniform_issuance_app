# Implementation Roadmap: School ERP Transformation

This roadmap outlines the steps to implement the suggested improvements and missing features, transforming the current system into a comprehensive, secure, and scalable multi-tenant SaaS School ERP.

---

## Phase 1: Foundation & Security (Weeks 1-3)
*Goal: Resolve technical debt, harden security, and prepare for modular growth.*

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

---

## Phase 2: Enhanced Multi-tenancy (Weeks 4-5)
*Goal: Automate tenant isolation and scaling.*

### 2.1 Global Tenant Scoping
1.  **SQLAlchemy Query Filters**: Implement a custom Base Query class in SQLAlchemy that automatically appends `.filter_by(school_id=g.school_id)` to all queries.
2.  **Automated Onboarding**:
    *   Create a script/route to provision a new school (seeds default voteheads, academic years, and admin user).
3.  **Subscription Middleware**: Enhance the `load_tenant_context` to block access if a school's subscription has expired.

---

## Phase 3: Core ERP Modules - Part 1 (Weeks 6-10)
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

## Phase 4: Core ERP Modules - Part 2 (Weeks 11-15)
*Goal: Financial and Administrative completeness.*

### 4.1 HR & Payroll
1.  **Staff Management**: Track contracts, qualifications, and leave balances.
2.  **Payroll Engine**: Automated monthly salary generation considering allowances and deductions.
3.  **Integration**: Automatic posting of payroll expenses to the General Ledger.

### 4.2 Library Management
1.  **Cataloging**: ISBN integration for quick book entry.
2.  **Circulation**: Track issues, returns, and automatic fine calculation.

---

## Phase 5: Portals & Analytics (Weeks 16+)
*Goal: Stakeholder engagement and data-driven decisions.*

### 5.1 Parent/Student Portal
1.  **Dashboard**: View-only access to marks, attendance, and fee statements.
2.  **Online Payments**: Integrate checkout for fees (Stripe, M-Pesa, etc.).

### 5.2 Executive Analytics
1.  **Performance Charts**: Visual trends for enrollment, revenue, and academic performance across terms/years.
2.  **Predictive Alerts**: Identification of students at risk of dropout or academic failure.
