import json
from typing import Any, Optional


def record_exam_event(
    cursor,
    school_id: int,
    event_key: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    old_values: Optional[Any] = None,
    new_values: Optional[Any] = None,
    reason: Optional[str] = None,
) -> None:
    """Write an exam audit event using the caller's transaction."""
    if not school_id or not event_key or not entity_type:
        raise ValueError("Exam audit events require a school, event, and entity.")
    cursor.execute(
        """
        INSERT INTO exam_audit_events (
            school_id, actor_user_id, event_key, entity_type, entity_id,
            old_values, new_values, reason
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            school_id,
            actor_user_id,
            event_key,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            json.dumps(old_values, default=str) if old_values is not None else None,
            json.dumps(new_values, default=str) if new_values is not None else None,
            reason,
        ),
    )
