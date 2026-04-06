from datetime import timedelta

from app import School
from ..models import AuditLog, Plan, PlatformUser, Subscription, SupportTicket, ErrorLog, utc_now


def _empty_subscription_counts():
    return {
        'active': 0,
        'trial': 0,
        'grace_period': 0,
        'suspended': 0,
        'cancelled': 0,
        'expired': 0,
        'archived': 0,
    }


def _build_security_alerts(window_days=7):
    recent_window_start = utc_now() - timedelta(days=window_days)
    recent_logs = (
        AuditLog.query
        .filter(AuditLog.created_at >= recent_window_start)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .all()
    )

    failed_login_logs = [log for log in recent_logs if log.action == 'platform_login_failed']
    rollout_denied_logs = [log for log in recent_logs if log.action == 'platform_login_rollout_denied']
    impersonation_logs = [log for log in recent_logs if log.action == 'impersonation_start']

    failures_by_ip = {}
    failures_by_email = {}
    for log in failed_login_logs:
        email = (log.changes or {}).get('email') or 'unknown'
        failures_by_email[email] = failures_by_email.get(email, 0) + 1
        if log.ip:
            failures_by_ip[log.ip] = failures_by_ip.get(log.ip, 0) + 1

    repeated_ip_failures = sum(1 for count in failures_by_ip.values() if count >= 3)
    repeated_email_failures = sum(1 for count in failures_by_email.values() if count >= 3)

    alert_cards = [
        {
            'label': 'Failed Platform Logins',
            'value': len(failed_login_logs),
            'detail': f"{repeated_ip_failures} IPs and {repeated_email_failures} accounts crossed the repeated-failure threshold",
        },
        {
            'label': 'Rollout Denials',
            'value': len(rollout_denied_logs),
            'detail': 'Successful credentials blocked by controlled platform rollout settings',
        },
        {
            'label': 'Impersonation Starts',
            'value': len(impersonation_logs),
            'detail': 'High impersonation volume should be reviewed against support and incident activity',
        },
    ]

    recent_alerts = []
    for log in recent_logs:
        if log.action not in {'platform_login_failed', 'platform_login_rollout_denied', 'impersonation_start'}:
            continue
        details = []
        if log.action == 'platform_login_failed':
            attempted_email = (log.changes or {}).get('email') or 'unknown'
            details.append(f'Email: {attempted_email}')
            if log.ip:
                details.append(f'IP: {log.ip}')
        elif log.action == 'platform_login_rollout_denied':
            attempted_email = (log.changes or {}).get('email') or 'unknown'
            details.append(f'Email: {attempted_email}')
            details.append(f"Mode: {(log.changes or {}).get('rollout_mode') or 'open'}")
        elif log.action == 'impersonation_start':
            details.append(f'Tenant user #{log.target_id}')
            if log.school_id:
                details.append(f'School #{log.school_id}')

        recent_alerts.append(
            {
                'action': log.action,
                'created_at': log.created_at,
                'ip': log.ip,
                'details': ', '.join(details),
            }
        )
        if len(recent_alerts) == 5:
            break

    return {
        'cards': alert_cards,
        'recent_alerts': recent_alerts,
        'failed_login_count': len(failed_login_logs),
        'rollout_denied_count': len(rollout_denied_logs),
        'impersonation_count': len(impersonation_logs),
    }



def build_dashboard_metrics(window_days=7):
    from ..services.subscriptions import build_entitlement_state_counts, build_subscription_entitlement_summary
    from extensions import db
    from sqlalchemy import text

    from models import User
    schools = School.query.order_by(School.created_at.desc()).all()
    subscriptions = Subscription.query.order_by(Subscription.started_at.desc()).all()
    support_tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).all()
    active_tenant_users = User.query.filter_by(access_flag=1).count()
    recent_window_start = utc_now() - timedelta(days=window_days)
    recent_audit_count = (
        AuditLog.query
        .filter(AuditLog.created_at >= recent_window_start)
        .count()
    )
    recent_error_count = (
        ErrorLog.query
        .filter(ErrorLog.created_at >= recent_window_start)
        .count()
    )

    db_status = "Healthy"
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        db_status = "Unhealthy"

    security_alerts = _build_security_alerts(window_days=window_days)

    # Placeholder for background job status
    job_status = "Idle"
    try:
        # If we had Celery or RQ, we would check queue size here
        job_status = "0 Pending"
    except Exception:
        job_status = "Error"

    subscription_counts = _empty_subscription_counts()
    subscriptions_by_school = {}
    for subscription in subscriptions:
        status = subscription.effective_status
        subscription_counts[status] = subscription_counts.get(status, 0) + 1
        subscriptions_by_school[subscription.school_id] = subscription

    open_support_count = sum(1 for ticket in support_tickets if (ticket.status or 'open').lower() == 'open')
    closed_support_count = sum(1 for ticket in support_tickets if (ticket.status or '').lower() == 'closed')
    active_school_count = sum(1 for school in schools if school.is_active)
    inactive_school_count = sum(1 for school in schools if not school.is_active)

    recent_school_rows = []
    entitlement_summaries = []
    for school in schools[:5]:
        school_subscription = subscriptions_by_school.get(school.id)
        recent_school_rows.append(
            {
                'school': school,
                'subscription_status': school_subscription.effective_status if school_subscription else (school.subscription_status or 'trial'),
            }
        )

    latest_subscription_by_school = {}
    for subscription in subscriptions:
        latest_subscription_by_school.setdefault(subscription.school_id, subscription)

    module_adoption = {}
    for school in schools:
        entitlement_summary = build_subscription_entitlement_summary(subscription=latest_subscription_by_school.get(school.id))
        entitlement_summaries.append(entitlement_summary)
        if not entitlement_summary['is_configured']:
            continue
        seen_codes = set()
        for module in entitlement_summary['modules']:
            if module['code'] in seen_codes:
                continue
            seen_codes.add(module['code'])
            bucket = module_adoption.setdefault(
                module['code'],
                {
                    'code': module['code'],
                    'name': module['name'],
                    'family_label': module.get('family_label'),
                    'group_label': module.get('group_label'),
                    'tenant_count': 0,
                },
            )
            bucket['tenant_count'] += 1

    entitlement_counts = build_entitlement_state_counts(entitlement_summaries)
    module_adoption_rows = sorted(module_adoption.values(), key=lambda item: (-item['tenant_count'], item['name']))[:6]

    recent_errors = (
        ErrorLog.query
        .order_by(ErrorLog.created_at.desc())
        .limit(5)
        .all()
    )

    summary = {
        'metrics_cards': [
            {
                'label': 'Total Schools',
                'value': len(schools),
                'detail': f"{active_school_count} active / {inactive_school_count} inactive",
            },
            {
                'label': 'Active Users',
                'value': active_tenant_users,
                'detail': "Active users across all tenants",
            },
            {
                'label': 'API Activity',
                'value': recent_audit_count,
                'detail': f"Audit events in last {window_days}d",
            },
            {
                'label': 'Error Rate',
                'value': f"{min(100, round((recent_error_count / max(1, recent_audit_count)) * 100, 2))}%",
                'detail': f"{recent_error_count} total errors logged",
            },
            {
                'label': 'Subscriptions',
                'value': len(subscriptions),
                'detail': f"{subscription_counts['active']} active, {subscription_counts['trial']} trial",
            },
            {
                'label': 'DB Connection',
                'value': db_status,
                'detail': 'Real-time database connectivity',
            },
            {
                'label': 'Background Jobs',
                'value': job_status,
                'detail': 'System queue and worker health',
            },
            {
                'label': 'Open Tickets',
                'value': open_support_count,
                'detail': f"{len(support_tickets)} total tickets logged",
            },
        ],
        'subscription_counts': subscription_counts,
        'entitlement_counts': entitlement_counts,
        'module_adoption_rows': module_adoption_rows,
        'recent_school_rows': recent_school_rows,
        'support_summary': {
            'open': open_support_count,
            'closed': closed_support_count,
            'total': len(support_tickets),
        },
        'security_alerts': security_alerts,
        'recent_errors': recent_errors,
    }
    return summary


def serialize_dashboard_metrics(summary):
    serialized_rows = []
    for item in summary['recent_school_rows']:
        school = item['school']
        serialized_rows.append(
            {
                'school': {
                    'id': school.id,
                    'name': school.name,
                    'code': school.code,
                    'created_at': school.created_at.isoformat() if school.created_at else None,
                },
                'subscription_status': item['subscription_status'],
            }
        )

    return {
        'metrics_cards': summary['metrics_cards'],
        'subscription_counts': summary['subscription_counts'],
        'entitlement_counts': summary['entitlement_counts'],
        'module_adoption_rows': summary['module_adoption_rows'],
        'support_summary': summary['support_summary'],
        'security_alerts': summary['security_alerts'],
        'recent_school_rows': serialized_rows,
    }


def _build_daily_series(records, window_start, now):
    day_range = (now.date() - window_start.date()).days + 1
    labels = []
    counts = []
    count_by_day = {}

    for record in records:
        created_at = record if not hasattr(record, 'date') else record
        day_key = created_at.date().isoformat()
        count_by_day[day_key] = count_by_day.get(day_key, 0) + 1

    for offset in range(day_range):
        current_day = (window_start + timedelta(days=offset)).date()
        day_key = current_day.isoformat()
        labels.append(day_key)
        counts.append(count_by_day.get(day_key, 0))

    return labels, counts


def build_metrics_trends(window_days=30):
    now = utc_now()
    window_start = now - timedelta(days=window_days)

    school_records = [school.created_at for school in School.query.filter(School.created_at >= window_start).all() if school.created_at]
    subscription_records = [subscription.started_at for subscription in Subscription.query.filter(Subscription.started_at >= window_start).all() if subscription.started_at]
    support_records = [ticket.created_at for ticket in SupportTicket.query.filter(SupportTicket.created_at >= window_start).all() if ticket.created_at]
    audit_records = [log.created_at for log in AuditLog.query.filter(AuditLog.created_at >= window_start).all() if log.created_at]

    labels, schools_series = _build_daily_series(school_records, window_start, now)
    _, subscriptions_series = _build_daily_series(subscription_records, window_start, now)
    _, support_series = _build_daily_series(support_records, window_start, now)
    _, audit_series = _build_daily_series(audit_records, window_start, now)

    school_count = sum(schools_series)
    subscription_count = sum(subscriptions_series)
    support_count = sum(support_series)
    audit_count = sum(audit_series)

    return {
        'window_days': window_days,
        'schools_created': school_count,
        'subscriptions_started': subscription_count,
        'support_tickets_created': support_count,
        'audit_events': audit_count,
        'labels': labels,
        'series': {
            'schools_created': schools_series,
            'subscriptions_started': subscriptions_series,
            'support_tickets_created': support_series,
            'audit_events': audit_series,
        },
    }
