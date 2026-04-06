from datetime import datetime

from extensions import db

from .audit import log as audit_log


def parse_optional_date(value):
    cleaned = (value or '').strip()
    if not cleaned:
        return None
    return datetime.strptime(cleaned, '%Y-%m-%d').date()


def latest_subscriptions_by_school_ids(school_ids):
    from ..models import Subscription
    from .subscriptions import refresh_subscription_pricing

    if not school_ids:
        return {}

    subscriptions = (
        Subscription.query
        .filter(Subscription.school_id.in_(school_ids))
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
        .all()
    )

    latest = {}
    for subscription in subscriptions:
        latest.setdefault(subscription.school_id, subscription)
    for school_id, subscription in list(latest.items()):
        latest[school_id] = refresh_subscription_pricing(subscription, reason='portfolio_view')
    return latest


def create_school(name, code, timezone='UTC', is_active=True, subscription_end=None, actor_user_id=None):
    from app import School, SchoolSettings

    school = School(
        name=(name or '').strip(),
        code=(code or '').strip(),
        is_active=bool(is_active),
        subscription_end=subscription_end,
    )
    db.session.add(school)
    db.session.flush()
    db.session.add(
        SchoolSettings(
            school_id=school.id,
            school_name=school.name,
            timezone=(timezone or 'UTC').strip() or 'UTC',
        )
    )
    db.session.commit()

    audit_log(
        actor_user_id=actor_user_id,
        action='school_created',
        target_table='schools',
        target_id=school.id,
        school_id=school.id,
        changes={
            'name': school.name,
            'code': school.code,
            'is_active': school.is_active,
            'subscription_end': school.subscription_end.isoformat() if school.subscription_end else None,
        },
    )
    return school


def set_school_active(school, is_active, actor_user_id=None):
    previous = bool(school.is_active)
    school.is_active = bool(is_active)
    db.session.commit()

    audit_log(
        actor_user_id=actor_user_id,
        action='school_status_updated',
        target_table='schools',
        target_id=school.id,
        school_id=school.id,
        changes={
            'old_is_active': previous,
            'new_is_active': school.is_active,
        },
    )
    return school


def set_school_subscription_end(school, subscription_end, actor_user_id=None):
    previous = school.subscription_end.isoformat() if school.subscription_end else None
    school.subscription_end = subscription_end
    db.session.commit()

    audit_log(
        actor_user_id=actor_user_id,
        action='school_subscription_window_updated',
        target_table='schools',
        target_id=school.id,
        school_id=school.id,
        changes={
            'old_subscription_end': previous,
            'new_subscription_end': school.subscription_end.isoformat() if school.subscription_end else None,
        },
    )
    return school