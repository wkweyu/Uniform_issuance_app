from sqlalchemy import or_

from extensions import db

from ..models import SupportTicket
from .audit import log as audit_log


VALID_SUPPORT_STATUSES = {'open', 'in_progress', 'closed'}
VALID_SUPPORT_SORT_COLUMNS = {'created_at', 'status', 'school', 'subject'}
VALID_SUPPORT_SORT_DIRECTIONS = {'asc', 'desc'}


def build_support_tickets_query(
    school_id=None,
    school_ids=None,
    status=None,
    assignment=None,
    search=None,
    sort_by='created_at',
    sort_dir='desc',
):
    from app import School

    query = SupportTicket.query.outerjoin(School, School.id == SupportTicket.school_id)

    if school_id:
        query = query.filter(SupportTicket.school_id == school_id)
    elif school_ids:
        query = query.filter(SupportTicket.school_id.in_(school_ids))

    normalized_status = (status or '').strip().lower()
    if normalized_status in VALID_SUPPORT_STATUSES:
        query = query.filter(SupportTicket.status == normalized_status)

    normalized_assignment = (assignment or '').strip().lower()
    if normalized_assignment == 'unassigned':
        query = query.filter(SupportTicket.assigned_to_user_id.is_(None))
    elif normalized_assignment:
        try:
            assigned_to_user_id = int(normalized_assignment)
        except ValueError:
            assigned_to_user_id = None
        if assigned_to_user_id is not None:
            query = query.filter(SupportTicket.assigned_to_user_id == assigned_to_user_id)

    normalized_search = (search or '').strip()
    if normalized_search:
        search_like = f"%{normalized_search}%"
        query = query.filter(
            or_(
                SupportTicket.subject.ilike(search_like),
                SupportTicket.description.ilike(search_like),
                SupportTicket.raised_by_email.ilike(search_like),
                School.name.ilike(search_like),
                School.code.ilike(search_like),
            )
        )

    effective_sort_by = sort_by if sort_by in VALID_SUPPORT_SORT_COLUMNS else 'created_at'
    effective_sort_dir = sort_dir if sort_dir in VALID_SUPPORT_SORT_DIRECTIONS else 'desc'

    if effective_sort_by == 'school':
        order_column = School.name
    else:
        order_column = getattr(SupportTicket, effective_sort_by)

    if effective_sort_dir == 'asc':
        query = query.order_by(order_column.asc(), SupportTicket.created_at.asc(), SupportTicket.id.asc())
    else:
        query = query.order_by(order_column.desc(), SupportTicket.created_at.desc(), SupportTicket.id.desc())

    return query


def list_support_tickets(
    school_id=None,
    school_ids=None,
    status=None,
    assignment=None,
    search=None,
    sort_by='created_at',
    sort_dir='desc',
    page=None,
    per_page=None,
    limit=None,
):
    query = build_support_tickets_query(
        school_id=school_id,
        school_ids=school_ids,
        status=status,
        assignment=assignment,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    if limit is None and page is not None and per_page is not None:
        offset = max(page - 1, 0) * per_page
        query = query.offset(offset).limit(per_page)
    elif limit is not None:
        query = query.limit(limit)

    return query.all()


def create_support_ticket(school_id, email, subject, description, actor_user_id=None):
    ticket = SupportTicket(
        school_id=school_id,
        raised_by_email=email,
        subject=subject,
        description=description,
        status='open',
    )
    db.session.add(ticket)
    db.session.commit()
    audit_log(
        actor_user_id=actor_user_id,
        action='support_ticket_created',
        target_table='support_tickets',
        target_id=ticket.id,
        school_id=ticket.school_id,
        changes={
            'subject': ticket.subject,
            'status': ticket.status,
        },
    )
    return ticket


def assign_support_ticket(ticket_id, assigned_to_user_id, actor_user_id=None):
    ticket = db.session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise ValueError('Support ticket not found')

    ticket.assigned_to_user_id = assigned_to_user_id
    if ticket.status in (None, 'open'):
        ticket.status = 'in_progress'
    db.session.commit()
    audit_log(
        actor_user_id=actor_user_id,
        action='support_ticket_assigned',
        target_table='support_tickets',
        target_id=ticket.id,
        school_id=ticket.school_id,
        changes={
            'assigned_to_user_id': assigned_to_user_id,
            'status': ticket.status,
        },
    )
    return ticket


def update_support_ticket_status(ticket_id, status, actor_user_id=None):
    normalized_status = (status or '').strip().lower()
    if normalized_status not in VALID_SUPPORT_STATUSES:
        raise ValueError('Invalid support ticket status')

    ticket = db.session.get(SupportTicket, ticket_id)
    if ticket is None:
        raise ValueError('Support ticket not found')

    ticket.status = normalized_status
    db.session.commit()
    audit_log(
        actor_user_id=actor_user_id,
        action='support_ticket_status_updated',
        target_table='support_tickets',
        target_id=ticket.id,
        school_id=ticket.school_id,
        changes={
            'status': ticket.status,
        },
    )
    return ticket
