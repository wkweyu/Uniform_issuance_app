from datetime import datetime, timedelta

from extensions import db
from ..models import AuditLog, PlatformUser
from flask import has_request_context, request, session
from sqlalchemy import case, or_


def log(actor_user_id=None, action=None, target_table=None, target_id=None, school_id=None, changes=None):
    resolved_actor = actor_user_id
    if resolved_actor is None and has_request_context():
        resolved_actor = session.get('platform_user_id')

    entry = AuditLog(
        actor_user_id=resolved_actor,
        actor_platform=True,
        action=action,
        target_table=target_table,
        target_id=str(target_id) if target_id is not None else None,
        school_id=school_id,
        changes=changes,
        ip=request.remote_addr if has_request_context() else None,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def _apply_sorting(query, sort_by='created_at', sort_dir='desc'):
    from models import School

    direction = 'asc' if sort_dir == 'asc' else 'desc'

    if sort_by == 'action':
        primary = AuditLog.action.asc() if direction == 'asc' else AuditLog.action.desc()
        secondary = AuditLog.created_at.asc() if direction == 'asc' else AuditLog.created_at.desc()
        return query.order_by(primary, secondary, AuditLog.id.desc())

    if sort_by == 'school':
        query = query.outerjoin(School, AuditLog.school_id == School.id)
        school_name = School.name.asc() if direction == 'asc' else School.name.desc()
        created_at = AuditLog.created_at.asc() if direction == 'asc' else AuditLog.created_at.desc()
        return query.order_by(
            case((AuditLog.school_id.is_(None), 1), else_=0).asc(),
            school_name,
            created_at,
            AuditLog.id.desc(),
        )

    primary = AuditLog.created_at.asc() if direction == 'asc' else AuditLog.created_at.desc()
    secondary = AuditLog.id.asc() if direction == 'asc' else AuditLog.id.desc()
    return query.order_by(primary, secondary)


def _reason_code_filter_clause(reason_code):
    return or_(
        AuditLog.changes['suspension_reason_code'].as_string() == reason_code,
        AuditLog.changes['cancellation_reason_code'].as_string() == reason_code,
    )


def build_logs_query(target_table=None, target_id=None, school_id=None, school_ids=None, action=None, actor_role=None, ip=None, reason_code=None, start_date=None, end_date=None, sort_by='created_at', sort_dir='desc'):
    query = AuditLog.query
    if actor_role is not None:
        query = query.outerjoin(PlatformUser, AuditLog.actor_user_id == PlatformUser.id)
    if target_table is not None:
        query = query.filter_by(target_table=target_table)
    if target_id is not None:
        query = query.filter_by(target_id=str(target_id))
    if school_id is not None:
        query = query.filter_by(school_id=school_id)
    elif school_ids:
        query = query.filter(AuditLog.school_id.in_(school_ids))
    if action is not None:
        query = query.filter_by(action=action)
    if actor_role is not None:
        query = query.filter(PlatformUser.role == actor_role)
    if ip is not None:
        query = query.filter(AuditLog.ip.ilike(f"%{ip}%"))
    if reason_code is not None:
        query = query.filter(_reason_code_filter_clause(reason_code))
    if start_date is not None:
        query = query.filter(AuditLog.created_at >= start_date)
    if end_date is not None:
        query = query.filter(AuditLog.created_at < end_date + timedelta(days=1))
    return _apply_sorting(query, sort_by=sort_by, sort_dir=sort_dir)


def list_logs(target_table=None, target_id=None, school_id=None, school_ids=None, action=None, actor_role=None, ip=None, reason_code=None, start_date=None, end_date=None, sort_by='created_at', sort_dir='desc', limit=50, page=None, per_page=None):
    query = build_logs_query(
        target_table=target_table,
        target_id=target_id,
        school_id=school_id,
        school_ids=school_ids,
        action=action,
        actor_role=actor_role,
        ip=ip,
        reason_code=reason_code,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    if page is not None and per_page is not None:
        offset = max(page - 1, 0) * per_page
        return query.offset(offset).limit(per_page).all()
    if limit is not None:
        return query.limit(limit).all()
    return query.all()
