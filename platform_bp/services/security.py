import csv
from datetime import datetime, timedelta
from io import StringIO

from flask import current_app, has_request_context, request, session
from sqlalchemy import or_

from extensions import db

from ..models import (
    AuditLog,
    PlatformUser,
    SecurityEvent,
    SecurityNotificationDelivery,
    SecurityNotificationPreference,
    utc_now,
)
from .audit import log as audit_log
from .notifications import send_email_alert, send_webhook_alert


VALID_SECURITY_EVENT_STATUSES = {'open', 'acknowledged', 'resolved'}
VALID_SECURITY_EVENT_SEVERITIES = {'low', 'medium', 'high', 'critical'}
VALID_SECURITY_EVENT_SORT_COLUMNS = {'last_seen_at', 'created_at', 'severity', 'status'}
VALID_SECURITY_EVENT_SORT_DIRECTIONS = {'asc', 'desc'}
VALID_NOTIFICATION_CHANNELS = {'email', 'webhook'}
VALID_NOTIFICATION_DELIVERY_STATUSES = {'sent', 'failed', 'throttled', 'skipped'}
SEVERITY_RANKS = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}


def get_security_policy():
    return {
        'login_failure_threshold': current_app.config.get('PLATFORM_LOGIN_FAILURE_THRESHOLD', 5),
        'login_failure_window_minutes': current_app.config.get('PLATFORM_LOGIN_FAILURE_WINDOW_MINUTES', 15),
        'login_lockout_enabled': current_app.config.get('PLATFORM_LOGIN_LOCKOUT_ENABLED', True),
        'login_lockout_minutes': current_app.config.get('PLATFORM_LOGIN_LOCKOUT_MINUTES', 15),
        'impersonation_threshold': current_app.config.get('PLATFORM_IMPERSONATION_ALERT_THRESHOLD', 3),
        'impersonation_window_minutes': current_app.config.get('PLATFORM_IMPERSONATION_ALERT_WINDOW_MINUTES', 60),
        'auto_create_support_tickets': current_app.config.get('PLATFORM_SECURITY_AUTO_CREATE_SUPPORT_TICKETS', True),
        'notification_minimum_severities': current_app.config.get('PLATFORM_SECURITY_NOTIFY_SEVERITIES', ['high', 'critical']),
        'notification_default_throttle_minutes': current_app.config.get('PLATFORM_SECURITY_NOTIFICATION_THROTTLE_MINUTES', 30),
        'notification_webhook_timeout_seconds': current_app.config.get('PLATFORM_SECURITY_WEBHOOK_TIMEOUT_SECONDS', 10),
        'email_alerts_enabled': current_app.config.get('PLATFORM_SECURITY_EMAIL_ALERTS_ENABLED', True),
        'webhook_alerts_enabled': current_app.config.get('PLATFORM_SECURITY_WEBHOOK_ALERTS_ENABLED', True),
    }


def _normalize_email(email):
    normalized = (email or '').strip().lower()
    return normalized or None


def _normalize_channel(channel):
    normalized = (channel or '').strip().lower()
    return normalized or None


def _normalize_event_types(event_types):
    if not event_types:
        return []
    if isinstance(event_types, str):
        raw_values = event_types.split(',')
    else:
        raw_values = event_types
    normalized = []
    for value in raw_values:
        clean_value = (value or '').strip().lower()
        if clean_value and clean_value not in normalized:
            normalized.append(clean_value)
    return normalized


def _normalize_severity(severity):
    normalized = (severity or '').strip().lower()
    return normalized if normalized in VALID_SECURITY_EVENT_SEVERITIES else 'high'


def _severity_rank(severity):
    return SEVERITY_RANKS.get((severity or '').strip().lower(), 0)


def _event_is_notifiable(event):
    policy = get_security_policy()
    allowed_severities = {
        _normalize_severity(value)
        for value in policy['notification_minimum_severities']
    }
    return event.severity in allowed_severities


def _safe_response_text(text):
    return (text or '')[:1000]


def _recent_failed_login_logs(window_start):
    return (
        AuditLog.query
        .filter(AuditLog.action == 'platform_login_failed')
        .filter(AuditLog.created_at >= window_start)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .all()
    )


def _count_failed_login_signals(email, ip_address, actor_user_id, window_start):
    email = _normalize_email(email)
    email_count = 0
    ip_count = 0
    user_count = 0

    for log in _recent_failed_login_logs(window_start):
        log_email = _normalize_email((log.changes or {}).get('email'))
        if email and log_email == email:
            email_count += 1
        if ip_address and log.ip == ip_address:
            ip_count += 1
        if actor_user_id and log.actor_user_id == actor_user_id:
            user_count += 1

    return {
        'email_count': email_count,
        'ip_count': ip_count,
        'user_count': user_count,
        'observed_count': max(email_count, ip_count, user_count),
    }


def _build_login_signal_key(email, user, ip_address):
    if user is not None:
        return f'platform-user:{user.id}'
    if email:
        return f'email:{email}'
    return f'ip:{ip_address or "unknown"}'


def _select_login_observed_count(counts, email, user):
    if user is not None or email:
        return max(counts['email_count'], counts['user_count'])
    return max(counts['ip_count'], counts['observed_count'])


def _merge_details(existing_details, new_details):
    merged = dict(existing_details or {})
    merged.update(new_details or {})
    return merged


def _record_notification_delivery(
    *,
    security_event_id,
    preference_id,
    channel,
    destination,
    status,
    throttle_key,
    status_reason=None,
    response_code=None,
    response_body=None,
    delivered_at=None,
):
    delivery = SecurityNotificationDelivery(
        security_event_id=security_event_id,
        preference_id=preference_id,
        channel=channel,
        destination=destination,
        status=status,
        status_reason=status_reason,
        response_code=response_code,
        response_body=_safe_response_text(response_body),
        throttle_key=throttle_key,
        delivered_at=delivered_at,
    )
    db.session.add(delivery)
    db.session.commit()
    return delivery


def _build_notification_payload(event):
    return {
        'event': {
            'id': event.id,
            'event_type': event.event_type,
            'severity': event.severity,
            'status': event.status,
            'title': event.title,
            'description': event.description,
            'school_id': event.school_id,
            'signal_key': event.signal_key,
            'threshold_value': event.threshold_value,
            'observed_value': event.observed_value,
            'occurrence_count': event.occurrence_count,
            'support_ticket_id': event.related_support_ticket_id,
            'first_seen_at': event.first_seen_at.isoformat() if event.first_seen_at else None,
            'last_seen_at': event.last_seen_at.isoformat() if event.last_seen_at else None,
            'details': event.details or {},
        }
    }


def _build_email_subject(event):
    return f'[{event.severity.upper()}] Security alert: {event.title}'


def _build_email_body(event):
    return (
        f'Security event: {event.title}\n'
        f'Severity: {event.severity}\n'
        f'Status: {event.status}\n'
        f'Event type: {event.event_type}\n'
        f'Signal key: {event.signal_key}\n'
        f'School ID: {event.school_id or "Platform"}\n'
        f'Observed value: {event.observed_value or "n/a"}\n'
        f'Threshold value: {event.threshold_value or "n/a"}\n'
        f'Occurrence count: {event.occurrence_count}\n'
        f'Support ticket: {event.related_support_ticket_id or "none"}\n\n'
        f'{event.description or ""}'
    )


def build_notification_preferences_query(enabled_only=None):
    query = SecurityNotificationPreference.query
    if enabled_only is True:
        query = query.filter(SecurityNotificationPreference.enabled.is_(True))
    elif enabled_only is False:
        query = query.filter(SecurityNotificationPreference.enabled.is_(False))
    return query.order_by(
        SecurityNotificationPreference.enabled.desc(),
        SecurityNotificationPreference.channel.asc(),
        SecurityNotificationPreference.created_at.desc(),
        SecurityNotificationPreference.id.desc(),
    )


def list_notification_preferences(enabled_only=None):
    return build_notification_preferences_query(enabled_only=enabled_only).all()


def list_recent_notification_deliveries(limit=20):
    return (
        SecurityNotificationDelivery.query
        .order_by(SecurityNotificationDelivery.attempted_at.desc(), SecurityNotificationDelivery.id.desc())
        .limit(limit)
        .all()
    )


def create_notification_preference(
    *,
    channel,
    destination,
    min_severity='high',
    throttle_minutes=None,
    school_id=None,
    event_types=None,
    name=None,
    enabled=True,
    secret_token=None,
    custom_headers=None,
    created_by_user_id=None,
):
    normalized_channel = _normalize_channel(channel)
    if normalized_channel not in VALID_NOTIFICATION_CHANNELS:
        raise ValueError('Invalid notification channel')

    normalized_destination = (destination or '').strip()
    if not normalized_destination:
        raise ValueError('Notification destination is required')
    if normalized_channel == 'email' and '@' not in normalized_destination:
        raise ValueError('Email destination must be a valid email address')
    if normalized_channel == 'webhook' and not normalized_destination.startswith(('http://', 'https://')):
        raise ValueError('Webhook destination must start with http:// or https://')

    normalized_school_id = school_id if school_id not in ('', None) else None
    if normalized_school_id is not None:
        normalized_school_id = int(normalized_school_id)

    effective_throttle_minutes = throttle_minutes or get_security_policy()['notification_default_throttle_minutes']
    preference = SecurityNotificationPreference(
        name=(name or '').strip() or None,
        channel=normalized_channel,
        destination=normalized_destination,
        min_severity=_normalize_severity(min_severity),
        school_id=normalized_school_id,
        event_types=_normalize_event_types(event_types),
        throttle_minutes=max(int(effective_throttle_minutes), 1),
        enabled=bool(enabled),
        secret_token=(secret_token or '').strip() or None,
        custom_headers=custom_headers or None,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(preference)
    db.session.commit()
    audit_log(
        actor_user_id=created_by_user_id,
        action='security_notification_preference_created',
        target_table='security_notification_preferences',
        target_id=preference.id,
        school_id=preference.school_id,
        changes={
            'channel': preference.channel,
            'destination': preference.destination,
            'min_severity': preference.min_severity,
            'event_types': preference.event_types or [],
            'throttle_minutes': preference.throttle_minutes,
            'enabled': preference.enabled,
        },
    )
    return preference


def toggle_notification_preference(preference_id, enabled, actor_user_id=None):
    preference = db.session.get(SecurityNotificationPreference, preference_id)
    if preference is None:
        raise ValueError('Notification preference not found')

    preference.enabled = bool(enabled)
    db.session.commit()
    audit_log(
        actor_user_id=actor_user_id,
        action='security_notification_preference_updated',
        target_table='security_notification_preferences',
        target_id=preference.id,
        school_id=preference.school_id,
        changes={'enabled': preference.enabled},
    )
    return preference


def _preference_matches_event(preference, event):
    if not preference.enabled:
        return False
    if preference.school_id is not None and preference.school_id != event.school_id:
        return False
    if _severity_rank(event.severity) < _severity_rank(preference.min_severity):
        return False

    scoped_event_types = _normalize_event_types(preference.event_types)
    if scoped_event_types and event.event_type not in scoped_event_types:
        return False
    return True


def _build_throttle_key(preference, event):
    school_fragment = event.school_id if event.school_id is not None else 'platform'
    return f'{preference.id}:{event.event_type}:{school_fragment}:{event.signal_key}'


def _is_delivery_throttled(preference, event):
    window_start = utc_now() - timedelta(minutes=preference.throttle_minutes or 0)
    recent_delivery = (
        SecurityNotificationDelivery.query
        .filter(SecurityNotificationDelivery.preference_id == preference.id)
        .filter(SecurityNotificationDelivery.throttle_key == _build_throttle_key(preference, event))
        .filter(SecurityNotificationDelivery.status == 'sent')
        .filter(SecurityNotificationDelivery.attempted_at >= window_start)
        .order_by(SecurityNotificationDelivery.attempted_at.desc(), SecurityNotificationDelivery.id.desc())
        .first()
    )
    return recent_delivery is not None


def dispatch_security_notifications(event):
    policy = get_security_policy()
    if not _event_is_notifiable(event):
        return []

    preferences = list_notification_preferences(enabled_only=True)
    deliveries = []
    payload = _build_notification_payload(event)

    for preference in preferences:
        if not _preference_matches_event(preference, event):
            continue
        if preference.channel == 'email' and not policy['email_alerts_enabled']:
            continue
        if preference.channel == 'webhook' and not policy['webhook_alerts_enabled']:
            continue

        throttle_key = _build_throttle_key(preference, event)
        if _is_delivery_throttled(preference, event):
            deliveries.append(
                _record_notification_delivery(
                    security_event_id=event.id,
                    preference_id=preference.id,
                    channel=preference.channel,
                    destination=preference.destination,
                    status='throttled',
                    throttle_key=throttle_key,
                    status_reason=f'Suppressed duplicate notification within {preference.throttle_minutes} minutes',
                )
            )
            continue

        if preference.channel == 'email':
            result = send_email_alert(
                to_email=preference.destination,
                subject=_build_email_subject(event),
                body=_build_email_body(event),
                from_email=current_app.config.get('PLATFORM_SECURITY_ALERT_EMAIL_FROM'),
            )
        else:
            result = send_webhook_alert(
                preference.destination,
                payload,
                secret_token=preference.secret_token,
                headers=preference.custom_headers or None,
                timeout_seconds=policy['notification_webhook_timeout_seconds'],
            )

        deliveries.append(
            _record_notification_delivery(
                security_event_id=event.id,
                preference_id=preference.id,
                channel=preference.channel,
                destination=preference.destination,
                status='sent' if result.get('ok') else 'failed',
                throttle_key=throttle_key,
                status_reason=result.get('reason'),
                response_code=result.get('response_code'),
                response_body=result.get('response_body'),
                delivered_at=utc_now() if result.get('ok') else None,
            )
        )

    return deliveries


def _create_support_ticket_for_security_event(event):
    from .support import create_support_ticket

    ticket = create_support_ticket(
        school_id=event.school_id,
        email='security-monitor@platform.local',
        subject=f'Security alert: {event.title}',
        description=event.description or event.title,
        actor_user_id=session.get('platform_user_id') if has_request_context() else None,
    )
    event.related_support_ticket_id = ticket.id
    db.session.commit()
    audit_log(
        actor_user_id=session.get('platform_user_id') if has_request_context() else None,
        action='security_event_support_ticket_created',
        target_table='security_events',
        target_id=event.id,
        school_id=event.school_id,
        changes={'support_ticket_id': ticket.id, 'event_type': event.event_type},
    )


def create_or_update_security_event(
    *,
    event_type,
    signal_key,
    severity,
    title,
    description,
    school_id=None,
    related_audit_log_id=None,
    threshold_value=None,
    observed_value=None,
    details=None,
    auto_create_ticket=None,
):
    now = utc_now()
    event = (
        SecurityEvent.query
        .filter_by(event_type=event_type, signal_key=signal_key)
        .order_by(SecurityEvent.id.desc())
        .first()
    )
    is_new = event is None

    if event is None:
        event = SecurityEvent(
            event_type=event_type,
            severity=severity,
            status='open',
            title=title,
            description=description,
            signal_key=signal_key,
            school_id=school_id,
            related_audit_log_id=related_audit_log_id,
            threshold_value=threshold_value,
            observed_value=observed_value,
            details=details,
            first_seen_at=now,
            last_seen_at=now,
            occurrence_count=1,
        )
        db.session.add(event)
    else:
        if event.status in {'acknowledged', 'resolved'}:
            event.status = 'open'
            event.acknowledged_at = None
            event.acknowledged_by_user_id = None
            event.resolved_at = None
            event.resolved_by_user_id = None
        event.severity = severity
        event.title = title
        event.description = description
        event.school_id = school_id if school_id is not None else event.school_id
        event.related_audit_log_id = related_audit_log_id or event.related_audit_log_id
        event.threshold_value = threshold_value
        event.observed_value = observed_value
        event.details = _merge_details(event.details, details)
        event.last_seen_at = now
        event.occurrence_count = (event.occurrence_count or 0) + 1

    db.session.commit()

    audit_log(
        actor_user_id=session.get('platform_user_id') if has_request_context() else None,
        action='security_event_created' if is_new else 'security_event_updated',
        target_table='security_events',
        target_id=event.id,
        school_id=event.school_id,
        changes={
            'event_type': event.event_type,
            'severity': event.severity,
            'status': event.status,
            'observed_value': event.observed_value,
            'threshold_value': event.threshold_value,
        },
    )

    if auto_create_ticket is None:
        auto_create_ticket = get_security_policy()['auto_create_support_tickets']
    if auto_create_ticket and event.related_support_ticket_id is None:
        _create_support_ticket_for_security_event(event)

    dispatch_security_notifications(event)

    return event


def handle_platform_login_success(user):
    user.failed_login_count = 0
    user.last_failed_login_at = None
    user.locked_until = None
    db.session.commit()
    audit_log(
        actor_user_id=user.id,
        action='platform_login_succeeded',
        target_table='platform_users',
        target_id=user.id,
        school_id=user.assigned_school_id,
        changes={'email': user.email, 'role': user.role},
    )


def handle_platform_rollout_denied(user, access_settings):
    audit_log(
        actor_user_id=user.id,
        action='platform_login_rollout_denied',
        target_table='platform_users',
        target_id=user.id,
        school_id=user.assigned_school_id,
        changes={
            'email': user.email,
            'role': user.role,
            'rollout_mode': access_settings.get('rollout_mode'),
            'allowed_roles': access_settings.get('allowed_roles') or [],
            'allowed_emails': access_settings.get('allowed_emails') or [],
        },
    )


def _record_login_blocked(email, user, action, message, observed_value):
    audit_log(
        actor_user_id=user.id if user else None,
        action=action,
        target_table='platform_users',
        target_id=user.id if user else None,
        school_id=user.assigned_school_id if user else None,
        changes={
            'email': _normalize_email(email),
            'message': message,
            'observed_value': observed_value,
        },
    )


def check_platform_login_guard(email, user):
    policy = get_security_policy()
    now = utc_now()
    ip_address = request.remote_addr if has_request_context() else None

    if user is not None and user.locked_until and user.locked_until > now:
        message = 'Account temporarily locked due to repeated failed login attempts. Try again later.'
        _record_login_blocked(email, user, 'platform_login_locked_out', message, user.failed_login_count or 0)
        return False, message

    window_start = now - timedelta(minutes=policy['login_failure_window_minutes'])
    counts = _count_failed_login_signals(_normalize_email(email), ip_address, user.id if user else None, window_start)
    observed_count = _select_login_observed_count(counts, email, user)
    if observed_count >= policy['login_failure_threshold']:
        message = 'Too many login attempts. Try again later.'
        _record_login_blocked(email, user, 'platform_login_rate_limited', message, observed_count)
        return False, message

    return True, None


def handle_platform_login_failure(email, user=None):
    policy = get_security_policy()
    now = utc_now()
    normalized_email = _normalize_email(email)
    ip_address = request.remote_addr if has_request_context() else None

    audit_entry = audit_log(
        actor_user_id=user.id if user else None,
        action='platform_login_failed',
        target_table='platform_users',
        target_id=user.id if user else None,
        school_id=user.assigned_school_id if user else None,
        changes={'email': normalized_email},
    )

    if user is not None:
        window_open = user.last_failed_login_at and user.last_failed_login_at >= now - timedelta(minutes=policy['login_failure_window_minutes'])
        user.failed_login_count = (user.failed_login_count + 1) if window_open else 1
        user.last_failed_login_at = now
        if policy['login_lockout_enabled'] and user.failed_login_count >= policy['login_failure_threshold']:
            user.locked_until = now + timedelta(minutes=policy['login_lockout_minutes'])
        db.session.commit()

    window_start = now - timedelta(minutes=policy['login_failure_window_minutes'])
    counts = _count_failed_login_signals(normalized_email, ip_address, user.id if user else None, window_start)
    observed_count = _select_login_observed_count(counts, normalized_email, user)
    if observed_count >= policy['login_failure_threshold']:
        lockout_applied = bool(user is not None and user.locked_until and user.locked_until > now)
        description = (
            f'Repeated failed platform login attempts detected for {normalized_email or "unknown identity"}. '
            f'Observed {observed_count} failures in the last {policy["login_failure_window_minutes"]} minutes.'
        )
        if lockout_applied:
            description += f' Temporary lockout applied until {user.locked_until}.'
        create_or_update_security_event(
            event_type='repeated_failed_platform_login',
            signal_key=_build_login_signal_key(normalized_email, user, ip_address),
            severity='high' if lockout_applied else 'medium',
            title='Repeated failed platform login attempts',
            description=description,
            school_id=user.assigned_school_id if user else None,
            related_audit_log_id=audit_entry.id,
            threshold_value=policy['login_failure_threshold'],
            observed_value=observed_count,
            details={
                'email': normalized_email,
                'ip_address': ip_address,
                'email_count': counts['email_count'],
                'ip_count': counts['ip_count'],
                'user_count': counts['user_count'],
                'lockout_applied': lockout_applied,
                'locked_until': user.locked_until.isoformat() if lockout_applied else None,
            },
        )


def process_impersonation_signal(actor_user_id, target_user_id, school_id, audit_entry_id=None):
    policy = get_security_policy()
    window_start = utc_now() - timedelta(minutes=policy['impersonation_window_minutes'])
    recent_count = (
        AuditLog.query
        .filter(AuditLog.action == 'impersonation_start')
        .filter(AuditLog.actor_user_id == actor_user_id)
        .filter(AuditLog.created_at >= window_start)
        .count()
    )
    if recent_count < policy['impersonation_threshold']:
        return None

    return create_or_update_security_event(
        event_type='platform_impersonation_burst',
        signal_key=f'platform-user:{actor_user_id}:school:{school_id or "platform"}',
        severity='high',
        title='Repeated impersonation activity detected',
        description=(
            f'Platform user {actor_user_id} started impersonation {recent_count} times in the last '
            f'{policy["impersonation_window_minutes"]} minutes.'
        ),
        school_id=school_id,
        related_audit_log_id=audit_entry_id,
        threshold_value=policy['impersonation_threshold'],
        observed_value=recent_count,
        details={
            'actor_user_id': actor_user_id,
            'target_user_id': target_user_id,
            'window_minutes': policy['impersonation_window_minutes'],
        },
    )


def acknowledge_security_event(event_id, actor_user_id=None):
    event = db.session.get(SecurityEvent, event_id)
    if event is None:
        raise ValueError('Security event not found')

    event.status = 'acknowledged'
    event.acknowledged_at = utc_now()
    event.acknowledged_by_user_id = actor_user_id
    db.session.commit()
    audit_log(
        actor_user_id=actor_user_id,
        action='security_event_acknowledged',
        target_table='security_events',
        target_id=event.id,
        school_id=event.school_id,
        changes={'status': event.status},
    )
    return event


def resolve_security_event(event_id, actor_user_id=None):
    event = db.session.get(SecurityEvent, event_id)
    if event is None:
        raise ValueError('Security event not found')

    event.status = 'resolved'
    event.resolved_at = utc_now()
    event.resolved_by_user_id = actor_user_id
    db.session.commit()
    audit_log(
        actor_user_id=actor_user_id,
        action='security_event_resolved',
        target_table='security_events',
        target_id=event.id,
        school_id=event.school_id,
        changes={'status': event.status},
    )
    return event


def build_security_events_query(
    school_id=None,
    school_ids=None,
    status=None,
    severity=None,
    event_type=None,
    search=None,
    start_date=None,
    end_date=None,
    sort_by='last_seen_at',
    sort_dir='desc',
):
    query = SecurityEvent.query

    if school_ids is not None:
        scoped_ids = [int(item) for item in school_ids]
        if not scoped_ids:
            return query.filter(SecurityEvent.id == -1)
        query = query.filter(SecurityEvent.school_id.in_(scoped_ids))
    if school_id is not None:
        query = query.filter(SecurityEvent.school_id == school_id)
    if status in VALID_SECURITY_EVENT_STATUSES:
        query = query.filter(SecurityEvent.status == status)
    if severity in VALID_SECURITY_EVENT_SEVERITIES:
        query = query.filter(SecurityEvent.severity == severity)
    if event_type:
        query = query.filter(SecurityEvent.event_type == event_type)
    if search:
        search_like = f'%{search.strip()}%'
        query = query.filter(
            or_(
                SecurityEvent.title.ilike(search_like),
                SecurityEvent.description.ilike(search_like),
                SecurityEvent.signal_key.ilike(search_like),
            )
        )
    if start_date is not None:
        query = query.filter(SecurityEvent.created_at >= start_date)
    if end_date is not None:
        query = query.filter(SecurityEvent.created_at < end_date + timedelta(days=1))

    effective_sort_by = sort_by if sort_by in VALID_SECURITY_EVENT_SORT_COLUMNS else 'last_seen_at'
    effective_sort_dir = sort_dir if sort_dir in VALID_SECURITY_EVENT_SORT_DIRECTIONS else 'desc'
    sort_column = getattr(SecurityEvent, effective_sort_by)
    if effective_sort_dir == 'asc':
        return query.order_by(sort_column.asc(), SecurityEvent.id.asc())
    return query.order_by(sort_column.desc(), SecurityEvent.id.desc())


def list_security_events(
    school_id=None,
    school_ids=None,
    status=None,
    severity=None,
    event_type=None,
    search=None,
    start_date=None,
    end_date=None,
    sort_by='last_seen_at',
    sort_dir='desc',
    page=None,
    per_page=None,
    limit=None,
):
    query = build_security_events_query(
        school_id=school_id,
        school_ids=school_ids,
        status=status,
        severity=severity,
        event_type=event_type,
        search=search,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    if limit is None and page is not None and per_page is not None:
        offset = max(page - 1, 0) * per_page
        query = query.offset(offset).limit(per_page)
    elif limit is not None:
        query = query.limit(limit)

    return query.all()


def export_security_events_csv(events, school_lookup):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'created_at',
        'last_seen_at',
        'school_name',
        'school_code',
        'event_type',
        'severity',
        'status',
        'title',
        'threshold_value',
        'observed_value',
        'occurrence_count',
        'support_ticket_id',
        'description',
    ])
    for event in events:
        school = school_lookup.get(event.school_id or 0)
        writer.writerow([
            event.created_at.isoformat() if event.created_at else '',
            event.last_seen_at.isoformat() if event.last_seen_at else '',
            school['name'] if school else 'Platform',
            school['code'] if school else '',
            event.event_type,
            event.severity,
            event.status,
            event.title,
            event.threshold_value or '',
            event.observed_value or '',
            event.occurrence_count or 0,
            event.related_support_ticket_id or '',
            event.description or '',
        ])
    return output.getvalue()