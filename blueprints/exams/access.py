from functools import wraps
from typing import Optional

import pymysql
from flask import abort, current_app, flash, jsonify, redirect, request, session, url_for

from core.db import get_db_connection
from blueprints.exams.audit import record_exam_event
from core.tenancy import get_current_school_id


class ExamAccessError(ValueError):
    """Raised when an examination role or scoped-access operation is invalid."""


class ExamAccessService:
    """Resolve school-scoped examination access using roles and assignments."""

    _OFFICER_PERMISSIONS = {
        "exam.create",
        "exam.open",
        "exam.submit",
        "exam.timetable.manage",
        "exam.lock",
        "exam.unlock",
        "exam.verify",
        "exam.publish",
        "exam.report",
        "exam.analytics",
        "exam.grade.configure",
        "marks.view",
        "report.class",
    }

    def __init__(self, connection, school_id: int, user_id: int):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id
        self.user_id = user_id

    def has_permission(
        self,
        permission: str,
        exam_id: Optional[int] = None,
        class_id: Optional[int] = None,
        subject_id: Optional[int] = None,
        student_id: Optional[str] = None,
    ) -> bool:
        roles = self._get_roles()
        if roles.intersection({"academic_administrator", "system_administrator"}):
            return True
        if "examination_officer" in roles and permission in self._OFFICER_PERMISSIONS:
            return True
        if permission == "exam.report" and "examination_officer" in roles:
            return True
        if not exam_id:
            return False

        if student_id and class_id is None:
            class_id = self._get_student_exam_class(exam_id, student_id)
        if class_id is None:
            return False

        academic_year_id = self._get_exam_class_year(exam_id, class_id)
        if academic_year_id is None:
            return False

        class_teacher = self._is_class_teacher(class_id, academic_year_id)
        if class_teacher and permission in {
            "marks.view",
            "marks.edit",
            "report.class",
            "report.student",
        }:
            return True

        subject_teacher = bool(
            subject_id
            and self._is_subject_teacher(class_id, subject_id, academic_year_id)
        )
        if subject_teacher and permission in {"marks.view", "marks.edit"}:
            return True

        if subject_teacher and permission == "report.subject":
            return True

        return self._has_approved_grant(
            permission,
            exam_id,
            class_id,
            subject_id,
        )

    def _get_roles(self) -> set[str]:
        self.cursor.execute(
            """
            SELECT role_key
            FROM exam_user_roles
            WHERE school_id = %s AND user_id = %s AND is_active = TRUE
            """,
            (self.school_id, self.user_id),
        )
        return {row["role_key"] for row in self.cursor.fetchall()}

    def _get_student_exam_class(self, exam_id: int, student_id: str) -> Optional[int]:
        self.cursor.execute(
            """
            SELECT ca.class_id
            FROM exam_series e
            JOIN exam_classes ec
              ON ec.exam_id = e.id AND ec.school_id = e.school_id
            JOIN class_allocation ca
              ON ca.class_id = ec.class_id
             AND ca.academic_year_id = e.academic_year_id
             AND ca.school_id = e.school_id
            WHERE e.id = %s AND e.school_id = %s
              AND ca.student_id = %s AND ca.is_current = TRUE
            LIMIT 1
            """,
            (exam_id, self.school_id, student_id),
        )
        row = self.cursor.fetchone()
        return row["class_id"] if row else None

    def _get_exam_class_year(self, exam_id: int, class_id: int) -> Optional[int]:
        self.cursor.execute(
            """
            SELECT e.academic_year_id
            FROM exam_series e
            JOIN exam_classes ec
              ON ec.exam_id = e.id AND ec.school_id = e.school_id
            JOIN classes c
              ON c.classID = ec.class_id AND c.school_id = ec.school_id
             AND c.academic_year_id = e.academic_year_id
            WHERE e.id = %s AND ec.class_id = %s AND e.school_id = %s
            """,
            (exam_id, class_id, self.school_id),
        )
        row = self.cursor.fetchone()
        return row["academic_year_id"] if row else None

    def _is_class_teacher(self, class_id: int, academic_year_id: int) -> bool:
        self.cursor.execute(
            """
            SELECT 1
            FROM class_teachers ct
            JOIN classes c ON c.classID = ct.class_id
            WHERE ct.teacher_id = %s AND ct.class_id = %s
              AND ct.academic_year_id = %s AND ct.is_active = TRUE
              AND c.school_id = %s
            LIMIT 1
            """,
            (self.user_id, class_id, academic_year_id, self.school_id),
        )
        return self.cursor.fetchone() is not None

    def _is_subject_teacher(
        self,
        class_id: int,
        subject_id: int,
        academic_year_id: int,
    ) -> bool:
        query_params = (
            self.user_id,
            class_id,
            subject_id,
            academic_year_id,
            self.school_id,
        )
        try:
            self.cursor.execute(
                """
                SELECT 1
                FROM teacher_allocations ta
                JOIN classes c ON c.classID = ta.class_id
                JOIN subjects s ON s.subjectNo = ta.subject_id
                WHERE ta.teacher_id = %s AND ta.class_id = %s
                  AND ta.subject_id = %s AND ta.academic_year_id = %s
                  AND ta.is_active = TRUE
                  AND c.school_id = %s AND s.school_id = %s
                LIMIT 1
                """,
                (*query_params, self.school_id),
            )
        except pymysql.Error:
            self.cursor.execute(
                """
                SELECT 1
                FROM teacher_allocations ta
                JOIN classes c ON c.classID = ta.class_id
                JOIN subjects s ON s.id = ta.subject_id
                WHERE ta.teacher_id = %s AND ta.class_id = %s
                  AND ta.subject_id = %s AND ta.academic_year_id = %s
                  AND ta.is_active = TRUE
                  AND c.school_id = %s AND s.school_id = %s
                LIMIT 1
                """,
                (*query_params, self.school_id),
            )
        return self.cursor.fetchone() is not None

    def _has_approved_grant(
        self,
        permission: str,
        exam_id: int,
        class_id: int,
        subject_id: Optional[int],
    ) -> bool:
        if subject_id is None:
            return False
        self.cursor.execute(
            """
            SELECT 1
            FROM exam_access_grants
            WHERE school_id = %s AND user_id = %s AND exam_id = %s
              AND class_id = %s AND subject_id = %s
              AND permission_key = %s AND status = 'approved'
              AND (expires_at IS NULL OR expires_at > NOW())
            LIMIT 1
            """,
            (
                self.school_id,
                self.user_id,
                exam_id,
                class_id,
                subject_id,
                permission,
            ),
        )
        return self.cursor.fetchone() is not None

    def request_access(
        self,
        exam_id: int,
        class_id: int,
        subject_id: int,
        permission: str,
        reason: str,
    ) -> int:
        allowed_permissions = {"marks.view", "marks.edit"}
        reason = (reason or "").strip()
        if permission not in allowed_permissions:
            raise ExamAccessError("The requested examination permission is invalid.")
        if len(reason) < 10 or len(reason) > 500:
            raise ExamAccessError(
                "Explain the access request in 10 to 500 characters."
            )
        if self._get_exam_class_year(exam_id, class_id) is None:
            raise ExamAccessError("Class is not assigned to this exam in this school.")

        self.cursor.execute(
            """
            SELECT 1
            FROM class_subjects cs
            JOIN classes c ON c.classID = cs.class_id
            WHERE cs.class_id = %s AND cs.subject_id = %s
              AND cs.school_id = %s AND cs.is_active = TRUE
              AND c.school_id = %s
            LIMIT 1
            """,
            (class_id, subject_id, self.school_id, self.school_id),
        )
        if not self.cursor.fetchone():
            raise ExamAccessError("Subject is not assigned to this class.")

        self.connection.begin()
        try:
            self.cursor.execute(
                """
                SELECT id
                FROM exam_access_grants
                WHERE school_id = %s AND user_id = %s AND exam_id = %s
                  AND class_id = %s AND subject_id = %s
                  AND permission_key = %s
                  AND status IN ('requested', 'approved')
                  AND (expires_at IS NULL OR expires_at > NOW())
                LIMIT 1
                FOR UPDATE
                """,
                (
                    self.school_id,
                    self.user_id,
                    exam_id,
                    class_id,
                    subject_id,
                    permission,
                ),
            )
            if self.cursor.fetchone():
                raise ExamAccessError(
                    "An active request or grant already exists for this scope."
                )
            self.cursor.execute(
                """
                INSERT INTO exam_access_grants (
                    school_id, user_id, exam_id, class_id, subject_id,
                    permission_key, status, requested_by, request_reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'requested', %s, %s)
                """,
                (
                    self.school_id,
                    self.user_id,
                    exam_id,
                    class_id,
                    subject_id,
                    permission,
                    self.user_id,
                    reason,
                ),
            )
            grant_id = self.cursor.lastrowid
            record_exam_event(
                self.cursor,
                self.school_id,
                'exam_access_requested',
                'exam_access_grant',
                grant_id,
                actor_user_id=self.user_id,
                new_values={
                    'user_id': self.user_id,
                    'exam_id': exam_id,
                    'class_id': class_id,
                    'subject_id': subject_id,
                    'permission': permission,
                    'status': 'requested',
                },
                reason=reason,
            )
            self.connection.commit()
            return grant_id
        except Exception:
            self.connection.rollback()
            raise

    def review_access_request(
        self,
        grant_id: int,
        decision: str,
        reason: str,
    ) -> bool:
        if decision not in {"approved", "denied", "revoked"}:
            raise ExamAccessError("The access-request decision is invalid.")
        reason = (reason or "").strip()
        if len(reason) < 10 or len(reason) > 500:
            raise ExamAccessError("A review reason of 10 to 500 characters is required.")

        self.connection.begin()
        try:
            self.cursor.execute(
                """
                SELECT id, user_id, exam_id, class_id, subject_id,
                       permission_key, status
                FROM exam_access_grants
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (grant_id, self.school_id),
            )
            grant = self.cursor.fetchone()
            if not grant:
                raise ExamAccessError("Access request not found for this school.")
            allowed_source_states = (
                {"approved"} if decision == "revoked" else {"requested"}
            )
            if grant["status"] not in allowed_source_states:
                raise ExamAccessError(
                    f"Cannot change an access request in state '{grant['status']}'."
                )

            self.cursor.execute(
                """
                UPDATE exam_access_grants
                SET status = %s, reviewed_by = %s, review_reason = %s,
                    reviewed_at = NOW()
                WHERE id = %s AND school_id = %s
                """,
                (
                    decision,
                    self.user_id,
                    reason,
                    grant_id,
                    self.school_id,
                ),
            )
            record_exam_event(
                self.cursor,
                self.school_id,
                f'exam_access_{decision}',
                'exam_access_grant',
                grant_id,
                actor_user_id=self.user_id,
                old_values={'status': grant["status"]},
                new_values={
                    'status': decision,
                    'user_id': grant["user_id"],
                    'exam_id': grant["exam_id"],
                    'class_id': grant["class_id"],
                    'subject_id': grant["subject_id"],
                    'permission': grant["permission_key"],
                },
                reason=reason,
            )
            self.connection.commit()
            return True
        except Exception:
            self.connection.rollback()
            raise


def exam_permission_required(permission: str):
    """Protect a route using tenant, role, and assignment-scoped exam access."""

    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "userNo" not in session:
                return redirect(url_for("auth.login", next=request.url))
            if session.get("is_admin") or session.get("is_super_admin"):
                return view(*args, **kwargs)

            school_id = get_current_school_id()
            user_id = session.get("userNo")
            if not school_id or user_id is None:
                abort(403)

            values = dict(kwargs)
            values.update(request.args.to_dict())
            values.update(request.form.to_dict())
            json_values = request.get_json(silent=True)
            if isinstance(json_values, dict):
                values.update(json_values)

            def optional_int(key):
                value = values.get(key)
                if value in (None, ""):
                    return None
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            connection = get_db_connection()
            try:
                allowed = ExamAccessService(
                    connection,
                    int(school_id),
                    int(user_id),
                ).has_permission(
                    permission,
                    exam_id=optional_int("exam_id"),
                    class_id=optional_int("class_id"),
                    subject_id=optional_int("subject_id"),
                    student_id=(
                        str(values["student_id"])
                        if values.get("student_id") not in (None, "")
                        else None
                    ),
                )
            except pymysql.Error:
                current_app.logger.exception(
                    "Failed to resolve exam permission %s", permission
                )
                abort(503, description="Examination access could not be verified.")
            finally:
                connection.close()

            if not allowed:
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({
                        "success": False,
                        "message": "You are not authorized for this examination data.",
                    }), 403
                flash("You are not authorized for this examination data.", "error")
                return redirect(url_for("index"))
            return view(*args, **kwargs)

        return wrapped

    return decorate
