"""Transactional examination workflow transitions."""

from typing import Optional

import pymysql

from blueprints.exams.audit import record_exam_event


class ExamWorkflowError(ValueError):
    """Raised when an exam workflow transition is invalid."""


class ExamWorkflowService:
    """Move one exam through its controlled school-scoped lifecycle."""

    TRANSITIONS = {
        "draft": {"marks_open"},
        "marks_open": {"submitted"},
        "submitted": {"verified"},
        "verified": {"moderation", "approved"},
        "moderation": {"verified"},
        "approved": {"published"},
        "published": {"locked"},
        "locked": {"published"},
    }
    PERMISSIONS = {
        "marks_open": "exam.open",
        "submitted": "exam.submit",
        "verified": "exam.verify",
        "moderation": "exam.moderate",
        "approved": "exam.approve",
        "published": "exam.publish",
        "locked": "exam.lock",
    }
    ACTOR_COLUMNS = {
        "submitted": ("submitted_by", "submitted_at"),
        "verified": ("verified_by", "verified_at"),
        "approved": ("approved_by", "approved_at"),
        "published": ("published_by", "published_at"),
    }

    def __init__(self, connection, school_id: int):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id

    @classmethod
    def permission_for_transition(
        cls,
        target_status: str,
        current_status: Optional[str] = None,
    ) -> str:
        if current_status == "locked" and target_status == "published":
            return "exam.unlock"
        try:
            return cls.PERMISSIONS[target_status]
        except KeyError as exc:
            raise ExamWorkflowError("Unsupported examination workflow state.") from exc

    def transition(
        self,
        exam_id: int,
        target_status: str,
        actor_user_id: int,
        *,
        reason: Optional[str] = None,
    ) -> str:
        if target_status not in self.PERMISSIONS:
            raise ExamWorkflowError("Unsupported examination workflow state.")
        reason = (reason or "").strip()
        if target_status in {"moderation", "approved", "published", "locked"} and len(reason) < 10:
            raise ExamWorkflowError(
                "Provide a reason of at least 10 characters for this workflow action."
            )
        if len(reason) > 500:
            raise ExamWorkflowError("Workflow reason cannot exceed 500 characters.")

        self.connection.begin()
        try:
            self.cursor.execute(
                """
                SELECT id, workflow_status, is_locked
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamWorkflowError("Exam series not found for this school.")
            old_status = exam.get("workflow_status") or (
                "locked" if exam.get("is_locked") else "marks_open"
            )
            if target_status not in self.TRANSITIONS.get(old_status, set()):
                raise ExamWorkflowError(
                    f"Cannot transition exam from {old_status} to {target_status}."
                )

            assignments = ["workflow_status = %s", "workflow_updated_at = NOW()"]
            values = [target_status]
            actor_columns = self.ACTOR_COLUMNS.get(target_status)
            if actor_columns:
                assignments.extend(
                    [f"{actor_columns[0]} = %s", f"{actor_columns[1]} = NOW()"]
                )
                values.append(actor_user_id)
            if target_status in {"locked", "published"}:
                assignments.append("is_locked = %s")
                values.append(target_status == "locked")
            values.extend([exam_id, self.school_id])
            self.cursor.execute(
                f"""
                UPDATE exam_series
                SET {', '.join(assignments)}
                WHERE id = %s AND school_id = %s
                """,
                tuple(values),
            )
            record_exam_event(
                self.cursor,
                self.school_id,
                f"exam_workflow_{target_status}",
                "exam_series",
                exam_id,
                actor_user_id=actor_user_id,
                old_values={"workflow_status": old_status},
                new_values={"workflow_status": target_status},
                reason=reason or None,
            )
            self.connection.commit()
            return target_status
        except Exception:
            self.connection.rollback()
            raise
