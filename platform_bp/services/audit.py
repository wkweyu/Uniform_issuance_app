from app import db
from ..models import AuditLog
from flask import request


def log(actor_user_id=None, action=None, target_table=None, target_id=None, school_id=None, changes=None):
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_platform=True,
        action=action,
        target_table=target_table,
        target_id=str(target_id) if target_id is not None else None,
        school_id=school_id,
        changes=changes,
        ip=request.remote_addr if request else None,
    )
    db.session.add(entry)
    db.session.commit()
    return entry
