import csv
from datetime import datetime
from io import StringIO
from urllib.parse import urlencode

from flask import flash, make_response, render_template, request, session
from extensions import db
from ..decorators import get_current_platform_user, platform_required
from ..services.access import get_portfolio_school_ids
from ..services.audit import build_logs_query, list_logs
from ..services.subscriptions import get_enforcement_reason_options, get_reason_label


PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
PAGE_SIZE_SESSION_KEY = 'platform_audit_page_size'
SORTABLE_COLUMNS = {'created_at', 'action', 'school'}
SORT_DIRECTIONS = {'asc', 'desc'}


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None


def _parse_page_size(value):
    if value is None:
        return DEFAULT_PAGE_SIZE
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return parsed if parsed in PAGE_SIZE_OPTIONS else DEFAULT_PAGE_SIZE


def _parse_sort_by(value):
    return value if value in SORTABLE_COLUMNS else 'created_at'


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


def _get_audit_context():
    from models import School
    from ..models import AuditLog, PlatformUser

    reset_view_preferences = request.args.get('reset_view_preferences') == '1'
    if reset_view_preferences:
        session.pop(PAGE_SIZE_SESSION_KEY, None)
        flash('Audit view preferences reset.', 'info')

    requested_page_size = request.args.get('page_size')
    if requested_page_size is not None:
        per_page = _parse_page_size(requested_page_size)
        session[PAGE_SIZE_SESSION_KEY] = per_page
    else:
        per_page = _parse_page_size(session.get(PAGE_SIZE_SESSION_KEY))
    saved_page_size = _parse_page_size(session.get(PAGE_SIZE_SESSION_KEY))
    school_id = request.args.get('school_id', type=int)
    target_table = request.args.get('target_table') or None
    action = request.args.get('action') or None
    reason_code = (request.args.get('reason_code') or '').strip() or None
    actor_role = request.args.get('actor_role') or None
    ip = request.args.get('ip') or None
    start_date_raw = request.args.get('start_date') or None
    end_date_raw = request.args.get('end_date') or None
    sort_by = _parse_sort_by(request.args.get('sort_by'))
    sort_dir = _parse_sort_dir(request.args.get('sort_dir'))
    requested_page = request.args.get('page', type=int)
    start_date = _parse_date(start_date_raw)
    end_date = _parse_date(end_date_raw)

    scoped_school_ids = get_portfolio_school_ids(get_current_platform_user())
    if scoped_school_ids and school_id and school_id not in scoped_school_ids:
        school_id = -1

    query = build_logs_query(
        school_id=school_id,
        school_ids=scoped_school_ids,
        target_table=target_table,
        action=action,
        reason_code=reason_code,
        actor_role=actor_role,
        ip=ip,
        start_date=start_date,
        end_date=end_date,
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
    logs = list_logs(
        school_id=school_id,
        school_ids=scoped_school_ids,
        target_table=target_table,
        action=action,
        reason_code=reason_code,
        actor_role=actor_role,
        ip=ip,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=current_page,
        per_page=per_page,
    )
    school_query = School.query
    if scoped_school_ids:
        school_query = school_query.filter(School.id.in_(scoped_school_ids))
    schools = school_query.order_by(School.name.asc()).all()
    school_lookup = {
        school.id: {
            'name': school.name,
            'code': school.code,
        }
        for school in schools
    }
    platform_users = PlatformUser.query.order_by(PlatformUser.email.asc()).all()
    actor_lookup = {
        user.id: {
            'name': user.name or user.email,
            'email': user.email,
            'role': user.role,
        }
        for user in platform_users
    }
    actor_roles = sorted({user.role for user in platform_users if user.role})
    target_tables = [
        row[0]
        for row in db.session.query(AuditLog.target_table)
        .filter(AuditLog.target_table.isnot(None))
        .distinct()
        .order_by(AuditLog.target_table.asc())
        .all()
    ]
    actions = [
        row[0]
        for row in db.session.query(AuditLog.action)
        .filter(AuditLog.action.isnot(None))
        .distinct()
        .order_by(AuditLog.action.asc())
        .all()
    ]
    filters = {
        'school_id': school_id,
        'target_table': target_table,
        'action': action,
        'reason_code': reason_code,
        'actor_role': actor_role,
        'ip': ip,
        'start_date': start_date_raw,
        'end_date': end_date_raw,
        'page_size': per_page,
        'sort_by': sort_by,
        'sort_dir': sort_dir,
    }
    export_params = {key: value for key, value in filters.items() if value not in (None, '')}
    pagination_params = export_params.copy()
    sort_params = export_params.copy()
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

    sort_urls = {
        'created_at': {
            'url': _build_sort_url(sort_params, 'created_at', sort_by, sort_dir),
            'title': _get_sort_tooltip('created_at', sort_by, sort_dir),
        },
        'action': {
            'url': _build_sort_url(sort_params, 'action', sort_by, sort_dir),
            'title': _get_sort_tooltip('action', sort_by, sort_dir),
        },
        'school': {
            'url': _build_sort_url(sort_params, 'school', sort_by, sort_dir),
            'title': _get_sort_tooltip('school', sort_by, sort_dir),
        },
    }

    return {
        'logs': logs,
        'schools': schools,
        'school_lookup': school_lookup,
        'actor_lookup': actor_lookup,
        'actor_roles': actor_roles,
        'target_tables': target_tables,
        'actions': actions,
        'enforcement_reason_options': get_enforcement_reason_options(),
        'reason_label': get_reason_label,
        'filters': filters,
        'export_query_string': _build_query_string(export_params),
        'reset_preferences_query_string': _build_query_string(reset_params),
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
    }


@platform_required(permission='audit_access')
def view_audit():
    return render_template('platform/audit_list.html', **_get_audit_context())


@platform_required(permission='audit_access')
def export_audit_csv():
    context = _get_audit_context()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['created_at', 'school_name', 'school_code', 'actor', 'actor_email', 'actor_role', 'ip', 'action', 'target_table', 'target_id', 'details'])

    full_logs = list_logs(
        school_id=context['filters']['school_id'],
        school_ids=get_portfolio_school_ids(get_current_platform_user()),
        target_table=context['filters']['target_table'],
        action=context['filters']['action'],
        reason_code=context['filters']['reason_code'],
        actor_role=context['filters']['actor_role'],
        ip=context['filters']['ip'],
        start_date=_parse_date(context['filters']['start_date']),
        end_date=_parse_date(context['filters']['end_date']),
        sort_by=context['filters']['sort_by'],
        sort_dir=context['filters']['sort_dir'],
        limit=None,
    )

    for log in full_logs:
        school = context['school_lookup'].get(log.school_id or 0)
        actor = context['actor_lookup'].get(log.actor_user_id or 0)
        writer.writerow([
            log.created_at.isoformat() if log.created_at else '',
            school['name'] if school else 'Platform',
            school['code'] if school else '',
            actor['name'] if actor else ('Platform user' if log.actor_platform and log.actor_user_id else 'System'),
            actor['email'] if actor else '',
            actor['role'] if actor else '',
            log.ip or '',
            log.action or '',
            log.target_table or '',
            log.target_id or '',
            '; '.join(f"{key}={value}" for key, value in (log.changes or {}).items()),
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=platform-audit.csv'
    return response


def register_routes(bp):
    bp.add_url_rule('/audit', endpoint='view_audit', view_func=view_audit)
    bp.add_url_rule('/audit/export', endpoint='export_audit_csv', view_func=export_audit_csv)
