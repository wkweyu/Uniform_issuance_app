import os
from datetime import datetime
from urllib.parse import urlencode, urlparse

import requests
from flask import current_app, flash, make_response, render_template, request, session, url_for, redirect, abort

from ..decorators import get_current_platform_user, platform_required
from ..models import SecurityNotificationPreference
from ..services.access import describe_user_school_scope, filter_school_collection_for_user, get_portfolio_school_ids, school_in_portfolio
from ..services.security import (
    VALID_SECURITY_EVENT_SORT_COLUMNS,
    VALID_SECURITY_EVENT_SORT_DIRECTIONS,
    acknowledge_security_event,
    build_security_events_query,
    create_notification_preference,
    export_security_events_csv,
    get_security_policy,
    list_security_events as list_security_event_rows,
    list_notification_preferences,
    list_recent_notification_deliveries,
    resolve_security_event,
    toggle_notification_preference,
)


PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
PAGE_SIZE_SESSION_KEY = 'platform_security_page_size'


def _get_relay_status():
    relay_url = (
        current_app.config.get('PLATFORM_SECURITY_RELAY_URL')
        or os.environ.get('PLATFORM_SECURITY_RELAY_URL')
        or 'http://127.0.0.1:8080'
    ).rstrip('/')
    health_url = f'{relay_url}/health'
    try:
        response = requests.get(
            health_url,
            timeout=float(current_app.config.get('PLATFORM_SECURITY_RELAY_HEALTH_TIMEOUT_SECONDS', 3)),
        )
        payload = response.json() if response.headers.get('Content-Type', '').startswith('application/json') else {}
        return {
            'configured': True,
            'relay_url': relay_url,
            'health_url': health_url,
            'reachable': response.status_code == 200,
            'ok': bool(payload.get('ok')) if isinstance(payload, dict) else False,
            'forwarding_enabled': bool(payload.get('forwarding_enabled')) if isinstance(payload, dict) else False,
            'warning': payload.get('warning') if isinstance(payload, dict) else None,
            'destinations': payload.get('destinations') if isinstance(payload, dict) else None,
            'status_code': response.status_code,
            'error': None,
        }
    except Exception as exc:
        return {
            'configured': True,
            'relay_url': relay_url,
            'health_url': health_url,
            'reachable': False,
            'ok': False,
            'forwarding_enabled': False,
            'warning': 'relay health endpoint is unreachable',
            'destinations': None,
            'status_code': None,
            'error': str(exc),
        }


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
    return value if value in VALID_SECURITY_EVENT_SORT_COLUMNS else 'last_seen_at'


def _parse_sort_dir(value):
    return value if value in VALID_SECURITY_EVENT_SORT_DIRECTIONS else 'desc'


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


def _safe_security_return_target(target):
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and parsed.path.startswith('/platform/security/events')


def _security_redirect_target():
    target = request.form.get('next') or request.args.get('next')
    if _safe_security_return_target(target):
        return target
    return url_for('platform.list_security_events')


def _visible_notification_preferences(preferences, scoped_school_ids):
    if scoped_school_ids is None:
        return preferences
    scoped_set = set(scoped_school_ids)
    return [preference for preference in preferences if preference.school_id in scoped_set]


def _visible_recent_deliveries(deliveries, delivery_events, delivery_preferences, scoped_school_ids):
    if scoped_school_ids is None:
        return deliveries

    scoped_set = set(scoped_school_ids)
    visible = []
    for delivery in deliveries:
        event = delivery_events.get(delivery.security_event_id)
        preference = delivery_preferences.get(delivery.preference_id)
        school_id = event.school_id if event is not None else preference.school_id if preference is not None else None
        if school_id in scoped_set:
            visible.append(delivery)
    return visible


def _assert_scoped_school_access(user, school_id, message):
    if not school_in_portfolio(user, school_id):
        raise PermissionError(message)


def _scoped_event_or_error(event_id):
    from extensions import db
    from ..models import SecurityEvent

    event = db.session.get(SecurityEvent, event_id)
    if event is None:
        raise ValueError('Security event not found')
    _assert_scoped_school_access(get_current_platform_user(), event.school_id, 'Security event is outside your portfolio scope.')
    return event


def _scoped_preference_or_error(preference_id):
    from extensions import db

    preference = db.session.get(SecurityNotificationPreference, preference_id)
    if preference is None:
        raise ValueError('Notification preference not found')
    _assert_scoped_school_access(get_current_platform_user(), preference.school_id, 'Notification preference is outside your portfolio scope.')
    return preference


def _get_security_context():
    from app import School
    from ..models import SecurityEvent, SecurityNotificationPreference, SecurityNotificationDelivery
    current_user = get_current_platform_user()
    scoped_school_ids = get_portfolio_school_ids(current_user)

    reset_view_preferences = request.args.get('reset_view_preferences') == '1'
    if reset_view_preferences:
        session.pop(PAGE_SIZE_SESSION_KEY, None)
        flash('Security event view preferences reset.', 'info')

    requested_page_size = request.args.get('page_size')
    if requested_page_size is not None:
        per_page = _parse_page_size(requested_page_size)
        session[PAGE_SIZE_SESSION_KEY] = per_page
    else:
        per_page = _parse_page_size(session.get(PAGE_SIZE_SESSION_KEY))
    saved_page_size = _parse_page_size(session.get(PAGE_SIZE_SESSION_KEY))

    school_id = request.args.get('school_id', type=int)
    if school_id is not None and not school_in_portfolio(current_user, school_id):
        abort(403)
    status = request.args.get('status') or None
    severity = request.args.get('severity') or None
    event_type = request.args.get('event_type') or None
    search = request.args.get('search') or None
    start_date_raw = request.args.get('start_date') or None
    end_date_raw = request.args.get('end_date') or None
    sort_by = _parse_sort_by(request.args.get('sort_by'))
    sort_dir = _parse_sort_dir(request.args.get('sort_dir'))
    requested_page = request.args.get('page', type=int)
    start_date = _parse_date(start_date_raw)
    end_date = _parse_date(end_date_raw)

    query = build_security_events_query(
        school_id=school_id,
        school_ids=scoped_school_ids,
        status=status,
        severity=severity,
        event_type=event_type,
        search=search,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    total_count = query.count()
    total_pages = max((total_count + per_page - 1) // per_page, 1)
    current_page = min(max(requested_page or 1, 1), total_pages)

    events = list_security_event_rows(
        school_id=school_id,
        school_ids=scoped_school_ids,
        status=status,
        severity=severity,
        event_type=event_type,
        search=search,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=current_page,
        per_page=per_page,
    )

    all_schools = School.query.order_by(School.name.asc()).all()
    schools = filter_school_collection_for_user(current_user, all_schools)
    school_lookup = {
        school.id: {'name': school.name, 'code': school.code}
        for school in all_schools
    }
    event_types = [
        row[0]
        for row in build_security_events_query(school_ids=scoped_school_ids)
        .with_entities(SecurityEvent.event_type)
        .distinct()
        .order_by(SecurityEvent.event_type.asc())
        .all()
    ]

    filters = {
        'school_id': school_id,
        'status': status,
        'severity': severity,
        'event_type': event_type,
        'search': search,
        'start_date': start_date_raw,
        'end_date': end_date_raw,
        'page_size': per_page,
        'sort_by': sort_by,
        'sort_dir': sort_dir,
    }
    base_params = {key: value for key, value in filters.items() if value not in (None, '')}
    reset_params = {key: value for key, value in base_params.items() if key != 'page_size'}
    reset_params['reset_view_preferences'] = 1
    if requested_page is not None:
        reset_params['page'] = current_page

    page_links = []
    if total_pages > 1:
        start_page = max(1, current_page - 2)
        end_page = min(total_pages, current_page + 2)
        for page_number in range(start_page, end_page + 1):
            query_params = base_params.copy()
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
        prev_params = base_params.copy()
        prev_params['page'] = current_page - 1
        prev_url = f"?{_build_query_string(prev_params)}"
    if current_page < total_pages:
        next_params = base_params.copy()
        next_params['page'] = current_page + 1
        next_url = f"?{_build_query_string(next_params)}"

    current_query = base_params.copy()
    current_query['page'] = current_page
    current_view_path = f"{url_for('platform.list_security_events')}?{_build_query_string(current_query)}"

    policy = get_security_policy()
    status_counts = {
        'open': build_security_events_query(school_ids=scoped_school_ids, status='open').count(),
        'acknowledged': build_security_events_query(school_ids=scoped_school_ids, status='acknowledged').count(),
        'resolved': build_security_events_query(school_ids=scoped_school_ids, status='resolved').count(),
    }
    preferences = _visible_notification_preferences(list_notification_preferences(), scoped_school_ids)
    preference_lookup = {preference.id: preference for preference in preferences}
    deliveries = list_recent_notification_deliveries(limit=100)
    delivery_event_ids = [delivery.security_event_id for delivery in deliveries]
    delivery_events = {
        event.id: event
        for event in SecurityEvent.query.filter(SecurityEvent.id.in_(delivery_event_ids)).all()
    } if delivery_event_ids else {}
    deliveries = _visible_recent_deliveries(deliveries, delivery_events, preference_lookup, scoped_school_ids)[:20]

    sort_urls = {
        'last_seen_at': _build_sort_url(base_params, 'last_seen_at', sort_by, sort_dir),
        'created_at': _build_sort_url(base_params, 'created_at', sort_by, sort_dir),
        'severity': _build_sort_url(base_params, 'severity', sort_by, sort_dir),
        'status': _build_sort_url(base_params, 'status', sort_by, sort_dir),
    }

    return {
        'events': events,
        'schools': schools,
        'school_lookup': school_lookup,
        'event_types': event_types,
        'filters': filters,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'policy': policy,
        'status_counts': status_counts,
        'notification_preferences': preferences,
        'notification_preference_counts': {
            'enabled': sum(1 for preference in preferences if preference.enabled),
            'disabled': sum(1 for preference in preferences if not preference.enabled),
            'email': sum(1 for preference in preferences if preference.channel == 'email'),
            'webhook': sum(1 for preference in preferences if preference.channel == 'webhook'),
        },
        'relay_status': _get_relay_status(),
        'recent_deliveries': deliveries,
        'delivery_event_lookup': delivery_events,
        'delivery_preference_lookup': preference_lookup,
        'sort_urls': sort_urls,
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
        'view_preferences': {
            'saved_page_size': saved_page_size,
            'has_saved_page_size_badge': saved_page_size != DEFAULT_PAGE_SIZE,
        },
        'export_query_string': _build_query_string(base_params),
        'reset_preferences_query_string': _build_query_string(reset_params),
        'current_view_path': current_view_path,
        'security_scope': describe_user_school_scope(current_user, {school.id: school for school in all_schools}),
    }


@platform_required(permission='security_access')
def list_security_events():
    return render_template('platform/security_events.html', **_get_security_context())


@platform_required(permission='security_access')
def export_security_events():
    context = _get_security_context()
    events = list_security_event_rows(
        school_id=context['filters']['school_id'],
        school_ids=[badge['id'] for badge in context['security_scope']['effective_badges']] if not context['security_scope']['is_unrestricted'] else None,
        status=context['filters']['status'],
        severity=context['filters']['severity'],
        event_type=context['filters']['event_type'],
        search=context['filters']['search'],
        start_date=_parse_date(context['filters']['start_date']),
        end_date=_parse_date(context['filters']['end_date']),
        sort_by=context['filters']['sort_by'],
        sort_dir=context['filters']['sort_dir'],
        limit=None,
    )
    response = make_response(export_security_events_csv(events, context['school_lookup']))
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=platform-security-events.csv'
    return response


@platform_required(permission='security_access')
def acknowledge_event(event_id):
    try:
        _scoped_event_or_error(event_id)
        acknowledge_security_event(event_id, actor_user_id=session.get('platform_user_id'))
        flash('Security event acknowledged.', 'success')
    except (ValueError, PermissionError) as exc:
        flash(str(exc), 'error')
    return redirect(_security_redirect_target())


@platform_required(permission='security_access')
def resolve_event(event_id):
    try:
        _scoped_event_or_error(event_id)
        resolve_security_event(event_id, actor_user_id=session.get('platform_user_id'))
        flash('Security event resolved.', 'success')
    except (ValueError, PermissionError) as exc:
        flash(str(exc), 'error')
    return redirect(_security_redirect_target())


@platform_required(permission='security_access')
def create_notification_preference_route():
    try:
        current_user = get_current_platform_user()
        school_id = request.form.get('school_id') or None
        if get_portfolio_school_ids(current_user) is not None and not school_id:
            raise PermissionError('Scoped security operators must choose a school inside their portfolio.')
        if school_id:
            _assert_scoped_school_access(current_user, school_id, 'Selected school is outside your portfolio scope.')
        enabled = request.form.get('enabled') == 'on'
        create_notification_preference(
            channel=request.form.get('channel'),
            destination=request.form.get('destination'),
            min_severity=request.form.get('min_severity'),
            throttle_minutes=request.form.get('throttle_minutes') or None,
            school_id=school_id,
            event_types=request.form.get('event_types'),
            name=request.form.get('name'),
            enabled=enabled,
            secret_token=request.form.get('secret_token'),
            created_by_user_id=session.get('platform_user_id'),
        )
        flash('Notification preference saved.', 'success')
    except (ValueError, PermissionError) as exc:
        flash(str(exc), 'error')
    return redirect(_security_redirect_target())


@platform_required(permission='security_access')
def toggle_notification_preference_route(preference_id):
    try:
        _scoped_preference_or_error(preference_id)
        enabled = request.form.get('enabled') == '1'
        toggle_notification_preference(preference_id, enabled, actor_user_id=session.get('platform_user_id'))
        flash('Notification preference updated.', 'success')
    except (ValueError, PermissionError) as exc:
        flash(str(exc), 'error')
    return redirect(_security_redirect_target())


def register_routes(bp):
    bp.add_url_rule('/security/events', endpoint='list_security_events', view_func=list_security_events)
    bp.add_url_rule('/security/events/export', endpoint='export_security_events', view_func=export_security_events)
    bp.add_url_rule('/security/events/<int:event_id>/acknowledge', endpoint='acknowledge_security_event_route', view_func=acknowledge_event, methods=['POST'])
    bp.add_url_rule('/security/events/<int:event_id>/resolve', endpoint='resolve_security_event_route', view_func=resolve_event, methods=['POST'])
    bp.add_url_rule('/security/notifications/preferences', endpoint='create_security_notification_preference_route', view_func=create_notification_preference_route, methods=['POST'])
    bp.add_url_rule('/security/notifications/preferences/<int:preference_id>/toggle', endpoint='toggle_security_notification_preference_route', view_func=toggle_notification_preference_route, methods=['POST'])