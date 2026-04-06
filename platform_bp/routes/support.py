from urllib.parse import urlencode, urlparse

from flask import render_template, request, redirect, session, url_for
from extensions import db
from core.flash_messages import flash_message
from ..decorators import get_current_platform_user, platform_required
from ..services.access import filter_school_collection_for_user, get_portfolio_school_ids, school_in_portfolio
from ..services.support import (
    VALID_SUPPORT_STATUSES,
    VALID_SUPPORT_SORT_COLUMNS,
    assign_support_ticket,
    build_support_tickets_query,
    create_support_ticket,
    list_support_tickets,
    update_support_ticket_status,
)


PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
PAGE_SIZE_SESSION_KEY = 'platform_support_page_size'
SORT_DIRECTIONS = {'asc', 'desc'}


def _parse_page_size(value):
    if value is None:
        return DEFAULT_PAGE_SIZE
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return parsed if parsed in PAGE_SIZE_OPTIONS else DEFAULT_PAGE_SIZE


def _parse_sort_by(value):
    return value if value in VALID_SUPPORT_SORT_COLUMNS else 'created_at'


def _parse_sort_dir(value):
    return value if value in SORT_DIRECTIONS else 'desc'


def _build_query_string(params):
    return urlencode({key: value for key, value in params.items() if value not in (None, '')})


def _build_sort_url(base_params, sort_by, current_sort_by, current_sort_dir):
    next_dir = 'asc'
    if current_sort_by == sort_by and current_sort_dir == 'asc':
        next_dir = 'desc'
    query_params = base_params.copy()
    query_params['sort_by'] = sort_by
    query_params['sort_dir'] = next_dir
    query_params['page'] = 1
    return f"?{_build_query_string(query_params)}"


def _get_sort_tooltip(sort_by, current_sort_by, current_sort_dir):
    next_dir = 'asc'
    if current_sort_by == sort_by and current_sort_dir == 'asc':
        next_dir = 'desc'
    return 'Sort ascending' if next_dir == 'asc' else 'Sort descending'


def _is_safe_support_return_target(target):
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and parsed.path.startswith('/platform/support')


def _support_redirect_target():
    target = request.form.get('next') or request.args.get('next')
    if _is_safe_support_return_target(target):
        return target
    return url_for('platform.list_tickets')


def _get_support_context():
    from app import School
    from ..models import PlatformUser

    reset_view_preferences = request.args.get('reset_view_preferences') == '1'
    if reset_view_preferences:
        session.pop(PAGE_SIZE_SESSION_KEY, None)
        flash_message('Support queue view preferences reset.', 'info')

    requested_page_size = request.args.get('page_size')
    if requested_page_size is not None:
        per_page = _parse_page_size(requested_page_size)
        session[PAGE_SIZE_SESSION_KEY] = per_page
    else:
        per_page = _parse_page_size(session.get(PAGE_SIZE_SESSION_KEY))
    saved_page_size = _parse_page_size(session.get(PAGE_SIZE_SESSION_KEY))

    school_id = request.args.get('school_id', type=int)
    status = request.args.get('status') or None
    assignment = request.args.get('assignment') or None
    search = request.args.get('search') or None
    sort_by = _parse_sort_by(request.args.get('sort_by'))
    sort_dir = _parse_sort_dir(request.args.get('sort_dir'))
    requested_page = request.args.get('page', type=int)

    current_user = get_current_platform_user()
    scoped_school_ids = get_portfolio_school_ids(current_user)

    query = build_support_tickets_query(
        school_id=school_id,
        school_ids=scoped_school_ids,
        status=status,
        assignment=assignment,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    total_count = query.count()
    reset_total_pages = max((total_count + DEFAULT_PAGE_SIZE - 1) // DEFAULT_PAGE_SIZE, 1)
    page = requested_page or 1
    if reset_view_preferences and requested_page is not None and (requested_page < 1 or requested_page > reset_total_pages):
        page = 1
    total_pages = max((total_count + per_page - 1) // per_page, 1)
    current_page = min(max(page, 1), total_pages)

    tickets = list_support_tickets(
        school_id=school_id,
        school_ids=scoped_school_ids,
        status=status,
        assignment=assignment,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=current_page,
        per_page=per_page,
    )
    schools = filter_school_collection_for_user(current_user, School.query.order_by(School.name.asc()).all())
    schools_by_id = {school.id: school for school in schools}
    assignees = PlatformUser.query.order_by(PlatformUser.email.asc()).all()
    assignees_by_id = {user.id: user for user in assignees}

    filters = {
        'school_id': school_id,
        'status': status,
        'assignment': assignment,
        'search': search,
        'page_size': per_page,
        'sort_by': sort_by,
        'sort_dir': sort_dir,
    }
    pagination_params = {key: value for key, value in filters.items() if value not in (None, '')}
    sort_params = pagination_params.copy()
    reset_params = {
        key: value
        for key, value in filters.items()
        if key != 'page_size' and value not in (None, '')
    }
    if requested_page is not None and requested_page == current_page and current_page <= reset_total_pages:
        reset_params['page'] = current_page
    reset_params['reset_view_preferences'] = 1

    page_links = []
    if total_pages > 1:
        start_page = max(1, current_page - 2)
        end_page = min(total_pages, current_page + 2)
        for page_number in range(start_page, end_page + 1):
            query_params = pagination_params.copy()
            query_params['page'] = page_number
            page_links.append(
                {
                    'number': page_number,
                    'url': f"?{_build_query_string(query_params)}",
                    'is_current': page_number == current_page,
                }
            )

    prev_url = None
    next_url = None
    if current_page > 1:
        prev_params = pagination_params.copy()
        prev_params['page'] = current_page - 1
        prev_url = f"?{_build_query_string(prev_params)}"
    if current_page < total_pages:
        next_params = pagination_params.copy()
        next_params['page'] = current_page + 1
        next_url = f"?{_build_query_string(next_params)}"

    current_query_params = pagination_params.copy()
    current_query_params['page'] = current_page
    current_view_path = f"{url_for('platform.list_tickets')}?{_build_query_string(current_query_params)}"

    sort_urls = {
        'created_at': {
            'url': _build_sort_url(sort_params, 'created_at', sort_by, sort_dir),
            'title': _get_sort_tooltip('created_at', sort_by, sort_dir),
        },
        'school': {
            'url': _build_sort_url(sort_params, 'school', sort_by, sort_dir),
            'title': _get_sort_tooltip('school', sort_by, sort_dir),
        },
        'status': {
            'url': _build_sort_url(sort_params, 'status', sort_by, sort_dir),
            'title': _get_sort_tooltip('status', sort_by, sort_dir),
        },
        'subject': {
            'url': _build_sort_url(sort_params, 'subject', sort_by, sort_dir),
            'title': _get_sort_tooltip('subject', sort_by, sort_dir),
        },
    }

    return {
        'tickets': tickets,
        'schools': schools,
        'schools_by_id': schools_by_id,
        'assignees': assignees,
        'assignees_by_id': assignees_by_id,
        'statuses': sorted(VALID_SUPPORT_STATUSES),
        'assignment_options': [
            {'value': 'unassigned', 'label': 'Unassigned'},
            *[
                {
                    'value': str(user.id),
                    'label': f"{user.name or user.email} ({user.role})",
                }
                for user in assignees
            ],
        ],
        'filters': filters,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'view_preferences': {
            'saved_page_size': saved_page_size,
            'has_saved_page_size_badge': saved_page_size != DEFAULT_PAGE_SIZE,
        },
        'sorting': {
            'sort_by': sort_by,
            'sort_dir': sort_dir,
            'sort_urls': sort_urls,
        },
        'pagination': {
            'current_page': current_page,
            'per_page': per_page,
            'total_count': total_count,
            'total_pages': total_pages,
            'page_links': page_links,
            'prev_url': prev_url,
            'next_url': next_url,
            'start_index': 0 if total_count == 0 else ((current_page - 1) * per_page) + 1,
            'end_index': min(current_page * per_page, total_count),
        },
        'reset_preferences_query_string': _build_query_string(reset_params),
        'current_view_path': current_view_path,
    }


@platform_required(permission='support_access')
def list_tickets():
    return render_template('platform/support_list.html', **_get_support_context())


@platform_required(permission='support_access')
def create_ticket():
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        if not school_in_portfolio(get_current_platform_user(), school_id):
            flash_message('You do not have access to create tickets for that school.', 'error')
            return redirect(url_for('platform.list_tickets'))
        email = request.form.get('email')
        subject = request.form.get('subject')
        description = request.form.get('description')
        create_support_ticket(
            school_id=school_id,
            email=email,
            subject=subject,
            description=description,
            actor_user_id=session.get('platform_user_id'),
        )
        flash_message('Ticket created', 'success')
        return redirect(url_for('platform.list_tickets'))

    from app import School

    schools = filter_school_collection_for_user(get_current_platform_user(), School.query.order_by(School.name.asc()).all())
    return render_template('platform/support_create.html', schools=schools)


@platform_required(permission='support_write')
def assign_ticket(ticket_id):
    from ..models import SupportTicket

    ticket = db.session.get(SupportTicket, ticket_id)
    if ticket is None:
        flash_message('Support ticket not found', 'error')
        return redirect(_support_redirect_target())
    if not school_in_portfolio(get_current_platform_user(), ticket.school_id):
        flash_message('You do not have access to update that support ticket.', 'error')
        return redirect(_support_redirect_target())

    assigned_to_user_id = request.form.get('assigned_to_user_id', type=int)
    try:
        assign_support_ticket(ticket_id, assigned_to_user_id, actor_user_id=session.get('platform_user_id'))
    except ValueError as exc:
        flash_message(str(exc), 'error')
        return redirect(_support_redirect_target())

    flash_message('Ticket assigned', 'success')
    return redirect(_support_redirect_target())


@platform_required(permission='support_write')
def update_ticket_status(ticket_id):
    from ..models import SupportTicket

    ticket = db.session.get(SupportTicket, ticket_id)
    if ticket is None:
        flash_message('Support ticket not found', 'error')
        return redirect(_support_redirect_target())
    if not school_in_portfolio(get_current_platform_user(), ticket.school_id):
        flash_message('You do not have access to update that support ticket.', 'error')
        return redirect(_support_redirect_target())

    status = request.form.get('status')
    try:
        update_support_ticket_status(ticket_id, status, actor_user_id=session.get('platform_user_id'))
    except ValueError as exc:
        flash_message(str(exc), 'error')
        return redirect(_support_redirect_target())

    flash_message('Ticket status updated', 'success')
    return redirect(_support_redirect_target())


def register_routes(bp):
    bp.add_url_rule('/support', endpoint='list_tickets', view_func=list_tickets)
    bp.add_url_rule('/support/create', endpoint='create_ticket', view_func=create_ticket, methods=['GET', 'POST'])
    bp.add_url_rule('/support/<int:ticket_id>/assign', endpoint='assign_ticket', view_func=assign_ticket, methods=['POST'])
    bp.add_url_rule('/support/<int:ticket_id>/status', endpoint='update_ticket_status', view_func=update_ticket_status, methods=['POST'])
