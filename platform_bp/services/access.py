from __future__ import annotations

from typing import Iterable

from flask import current_app

from extensions import db
from sqlalchemy.exc import SQLAlchemyError

from ..models import PlatformSetting
from .audit import log as audit_log


ROLLOUT_MODE_SETTING_KEY = 'rollout_mode'
ROLLOUT_ALLOWED_EMAILS_SETTING_KEY = 'rollout_allowed_emails'
ROLLOUT_ALLOWED_ROLES_SETTING_KEY = 'rollout_allowed_roles'
TENANT_ENFORCEMENT_MODE_SETTING_KEY = 'tenant_enforcement_mode'
TENANT_ENFORCEMENT_NOTES_SETTING_KEY = 'tenant_enforcement_notes'
PLATFORM_ACCESS_SETTING_KEYS = (
    ROLLOUT_MODE_SETTING_KEY,
    ROLLOUT_ALLOWED_EMAILS_SETTING_KEY,
    ROLLOUT_ALLOWED_ROLES_SETTING_KEY,
    TENANT_ENFORCEMENT_MODE_SETTING_KEY,
    TENANT_ENFORCEMENT_NOTES_SETTING_KEY,
)
VALID_ROLLOUT_MODES = {'open', 'allowlist', 'roles'}
VALID_TENANT_ENFORCEMENT_MODES = {'open', 'audit', 'enforce'}

ROLE_LABELS = {
    'super_admin': 'Super Admin',
    'platform_admin': 'Platform Admin',
    'security': 'Security Operator',
    'billing': 'Billing Operator',
    'account_manager': 'Account Manager',
    'support': 'Support Admin',
    'marketers': 'Marketer',
    'viewer': 'Viewer',
}

PERMISSION_LABELS = {
    'dashboard': 'Dashboard and metrics',
    'billing_access': 'School, subscription, plan, and audit review',
    'subscription_write': 'Subscription and school billing mutations',
    'support_access': 'Support queue access',
    'support_write': 'Support assignment and status updates',
    'audit_access': 'Audit log review and export',
    'security_access': 'Security events and notification controls',
    'tenant_search': 'Tenant user search and impersonation',
    'onboarding_manage': 'School onboarding workflow',
    'plans_write': 'Plan creation and editing',
    'user_admin': 'Platform user directory access',
    'platform_settings': 'Platform rollout and segmentation settings',
    'portfolio_scope': 'School portfolio scoping',
}

ROLE_CAPABILITIES = {
    'super_admin': {'all'},
    'platform_admin': {
        'dashboard',
        'billing_access',
        'support_access',
        'support_write',
        'audit_access',
        'tenant_search',
        'onboarding_manage',
        'plans_write',
        'user_admin',
    },
    'security': {'dashboard', 'security_access'},
    'billing': {'dashboard', 'billing_access', 'audit_access'},
    'account_manager': {'dashboard', 'billing_access', 'audit_access'},
    'support': {'dashboard', 'support_access', 'support_write'},
    'marketers': {'dashboard', 'billing_access'},
    'viewer': {'dashboard'},
}


def normalize_role_name(role: str | None) -> str:
    return (role or '').strip().lower()


def role_label(role: str | None) -> str:
    normalized_role = normalize_role_name(role)
    return ROLE_LABELS.get(normalized_role, normalized_role.replace('_', ' ').title() if normalized_role else 'Unknown')


def available_platform_roles(include_super_admin: bool = True) -> list[dict[str, str]]:
    ordered_roles = ['super_admin', 'platform_admin', 'security', 'billing', 'account_manager', 'support', 'marketers', 'viewer']
    if not include_super_admin:
        ordered_roles = [role for role in ordered_roles if role != 'super_admin']
    return [{'value': role, 'label': role_label(role)} for role in ordered_roles]


def _normalize_school_ids(values) -> list[int]:
    normalized_ids = []
    if values is None:
        return normalized_ids
    raw_values = values if isinstance(values, (list, tuple, set)) else [values]
    for raw_value in raw_values:
        try:
            school_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if school_id > 0 and school_id not in normalized_ids:
            normalized_ids.append(school_id)
    return normalized_ids


def _normalize_string_list(values: Iterable[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = values.replace('\n', ',').split(',')
    else:
        raw_values = list(values)
    normalized = []
    for raw_value in raw_values:
        value = str(raw_value).strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_rollout_mode(value: str | None) -> str:
    normalized = (value or 'open').strip().lower()
    return normalized if normalized in VALID_ROLLOUT_MODES else 'open'


def _normalize_tenant_enforcement_mode(value: str | None) -> str:
    normalized = (value or 'enforce').strip().lower()
    return normalized if normalized in VALID_TENANT_ENFORCEMENT_MODES else 'enforce'


def _config_access_settings() -> dict[str, list[str] | str]:
    return {
        'rollout_mode': _normalize_rollout_mode(current_app.config.get('PLATFORM_ROLLOUT_MODE')),
        'allowed_emails': _normalize_string_list(current_app.config.get('PLATFORM_ROLLOUT_ALLOWED_EMAILS', [])),
        'allowed_roles': _normalize_string_list(current_app.config.get('PLATFORM_ROLLOUT_ALLOWED_ROLES', [])),
        'tenant_enforcement_mode': _normalize_tenant_enforcement_mode(current_app.config.get('TENANT_ENFORCEMENT_MODE')),
        'tenant_enforcement_notes': (current_app.config.get('TENANT_ENFORCEMENT_NOTES') or '').strip(),
    }


def get_platform_access_settings() -> dict[str, list[str] | str]:
    settings = _config_access_settings()
    try:
        stored_settings = PlatformSetting.query.filter(PlatformSetting.key.in_(PLATFORM_ACCESS_SETTING_KEYS)).all()
    except SQLAlchemyError:
        return settings

    for item in stored_settings:
        if item.key == ROLLOUT_MODE_SETTING_KEY:
            settings['rollout_mode'] = _normalize_rollout_mode(item.value_json if isinstance(item.value_json, str) else None)
        elif item.key == ROLLOUT_ALLOWED_EMAILS_SETTING_KEY:
            settings['allowed_emails'] = _normalize_string_list(item.value_json)
        elif item.key == ROLLOUT_ALLOWED_ROLES_SETTING_KEY:
            settings['allowed_roles'] = _normalize_string_list(item.value_json)
        elif item.key == TENANT_ENFORCEMENT_MODE_SETTING_KEY:
            settings['tenant_enforcement_mode'] = _normalize_tenant_enforcement_mode(item.value_json if isinstance(item.value_json, str) else None)
        elif item.key == TENANT_ENFORCEMENT_NOTES_SETTING_KEY:
            settings['tenant_enforcement_notes'] = (item.value_json or '').strip() if isinstance(item.value_json, str) else ''
    return settings


def get_tenant_enforcement_settings() -> dict[str, str]:
    settings = get_platform_access_settings()
    return {
        'mode': settings.get('tenant_enforcement_mode', 'enforce'),
        'notes': settings.get('tenant_enforcement_notes', ''),
    }


def platform_user_has_permission(user, permission: str | None) -> bool:
    if permission is None:
        return user is not None
    if user is None:
        return False
    role_name = normalize_role_name(getattr(user, 'role', None))
    capabilities = ROLE_CAPABILITIES.get(role_name, set())
    if 'all' in capabilities:
        return True
    return permission in capabilities


def get_portfolio_school_ids(user) -> list[int] | None:
    if user is None:
        return None
    if getattr(user, 'is_super_admin', None) and user.is_super_admin():
        return None

    scoped_ids = []
    if getattr(user, 'assigned_school_id', None):
        scoped_ids.append(int(user.assigned_school_id))

    portfolio_scope = getattr(user, 'portfolio_scope', None)
    if isinstance(portfolio_scope, dict):
        if portfolio_scope.get('all_schools'):
            return None
        scoped_ids.extend(_normalize_school_ids(portfolio_scope.get('school_ids')))
        scoped_ids.extend(_normalize_school_ids(portfolio_scope.get('schools')))
    elif isinstance(portfolio_scope, list):
        scoped_ids.extend(_normalize_school_ids(portfolio_scope))

    deduped_ids = []
    for school_id in scoped_ids:
        if school_id not in deduped_ids:
            deduped_ids.append(school_id)
    return deduped_ids or None


def school_in_portfolio(user, school_id) -> bool:
    scoped_school_ids = get_portfolio_school_ids(user)
    if scoped_school_ids is None:
        return True
    try:
        normalized_school_id = int(school_id)
    except (TypeError, ValueError):
        return False
    return normalized_school_id in scoped_school_ids


def filter_school_collection_for_user(user, schools):
    scoped_school_ids = get_portfolio_school_ids(user)
    if scoped_school_ids is None:
        return schools
    scoped_set = set(scoped_school_ids)
    return [school for school in schools if getattr(school, 'id', None) in scoped_set]


def portfolio_school_ids_from_scope(portfolio_scope) -> list[int]:
    if isinstance(portfolio_scope, dict):
        scoped_ids = []
        scoped_ids.extend(_normalize_school_ids(portfolio_scope.get('school_ids')))
        scoped_ids.extend(_normalize_school_ids(portfolio_scope.get('schools')))
        deduped_ids = []
        for school_id in scoped_ids:
            if school_id not in deduped_ids:
                deduped_ids.append(school_id)
        return deduped_ids
    if isinstance(portfolio_scope, list):
        return _normalize_school_ids(portfolio_scope)
    return []


def _school_badge(school_id, school_lookup):
    try:
        normalized_school_id = int(school_id)
    except (TypeError, ValueError):
        return None

    school = school_lookup.get(normalized_school_id)
    if school is None:
        return {
            'id': normalized_school_id,
            'name': f'School #{normalized_school_id}',
            'code': None,
            'label': f'School #{normalized_school_id}',
            'missing': True,
        }

    if isinstance(school, dict):
        school_name = school.get('name')
        school_code = school.get('code')
    else:
        school_name = getattr(school, 'name', None)
        school_code = getattr(school, 'code', None)
    label = school_name or f'School #{normalized_school_id}'
    if school_code:
        label = f'{label} ({school_code})'
    return {
        'id': normalized_school_id,
        'name': school_name or label,
        'code': school_code,
        'label': label,
        'missing': False,
    }


def describe_user_school_scope(user, school_lookup):
    assigned_badge = _school_badge(getattr(user, 'assigned_school_id', None), school_lookup)
    explicit_portfolio_ids = portfolio_school_ids_from_scope(getattr(user, 'portfolio_scope', None))

    portfolio_badges = []
    for school_id in explicit_portfolio_ids:
        badge = _school_badge(school_id, school_lookup)
        if badge is not None:
            portfolio_badges.append(badge)

    effective_scope_ids = get_portfolio_school_ids(user)
    effective_badges = []
    if effective_scope_ids is not None:
        for school_id in effective_scope_ids:
            badge = _school_badge(school_id, school_lookup)
            if badge is not None:
                effective_badges.append(badge)

    unrestricted = effective_scope_ids is None
    return {
        'assigned_school': assigned_badge,
        'portfolio_badges': portfolio_badges,
        'effective_badges': effective_badges,
        'is_unrestricted': unrestricted,
        'has_scope': bool(assigned_badge or portfolio_badges or unrestricted),
    }


def role_capability_rows() -> list[dict[str, object]]:
    rows = []
    for role in ['super_admin', 'platform_admin', 'security', 'billing', 'account_manager', 'support', 'marketers', 'viewer']:
        capabilities = ROLE_CAPABILITIES.get(role, set())
        labels = ['All platform capabilities'] if 'all' in capabilities else [PERMISSION_LABELS[capability] for capability in capabilities if capability in PERMISSION_LABELS]
        rows.append(
            {
                'role': role,
                'label': role_label(role),
                'capability_labels': sorted(labels),
            }
        )
    return rows


def update_platform_access_settings(*, rollout_mode: str, allowed_emails, allowed_roles, tenant_enforcement_mode=None, tenant_enforcement_notes=None, actor_user_id=None):
    previous_settings = get_platform_access_settings()
    normalized_mode = _normalize_rollout_mode(rollout_mode)
    normalized_emails = _normalize_string_list(allowed_emails)
    normalized_roles = [role for role in _normalize_string_list(allowed_roles) if role in {item['value'] for item in available_platform_roles(include_super_admin=False)}]
    normalized_tenant_mode = _normalize_tenant_enforcement_mode(tenant_enforcement_mode or previous_settings.get('tenant_enforcement_mode'))
    normalized_tenant_notes = (tenant_enforcement_notes if tenant_enforcement_notes is not None else previous_settings.get('tenant_enforcement_notes') or '').strip()

    setting_values = {
        ROLLOUT_MODE_SETTING_KEY: normalized_mode,
        ROLLOUT_ALLOWED_EMAILS_SETTING_KEY: normalized_emails,
        ROLLOUT_ALLOWED_ROLES_SETTING_KEY: normalized_roles,
        TENANT_ENFORCEMENT_MODE_SETTING_KEY: normalized_tenant_mode,
        TENANT_ENFORCEMENT_NOTES_SETTING_KEY: normalized_tenant_notes,
    }
    for key, value in setting_values.items():
        setting = PlatformSetting.query.filter_by(key=key).first()
        if setting is None:
            setting = PlatformSetting(key=key, value_json=value, updated_by_user_id=actor_user_id)
            db.session.add(setting)
        else:
            setting.value_json = value
            setting.updated_by_user_id = actor_user_id
    db.session.commit()
    audit_log(
        actor_user_id=actor_user_id,
        action='platform_access_settings_updated',
        target_table='platform_settings',
        target_id='rollout_access',
        changes={
            'rollout_mode': normalized_mode,
            'allowed_emails': normalized_emails,
            'allowed_roles': normalized_roles,
            'tenant_enforcement_mode': normalized_tenant_mode,
            'tenant_enforcement_notes': normalized_tenant_notes,
            'previous_settings': previous_settings,
            'new_settings': {
                'rollout_mode': normalized_mode,
                'allowed_emails': normalized_emails,
                'allowed_roles': normalized_roles,
                'tenant_enforcement_mode': normalized_tenant_mode,
                'tenant_enforcement_notes': normalized_tenant_notes,
            },
        },
    )
    return get_platform_access_settings()
