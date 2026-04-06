from datetime import UTC, datetime
from extensions import db


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


class Plan(db.Model):
    __tablename__ = 'plans'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    billing_period = db.Column(db.String(32), nullable=False, default='monthly')
    bundle_family = db.Column(db.String(32), nullable=False, default='combined', index=True)
    pricing_model = db.Column(db.String(32), nullable=False, default='student_band')
    features = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utc_now)


class ModuleCatalog(db.Model):
    __tablename__ = 'module_catalog'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    family = db.Column(db.String(32), nullable=False, index=True)
    is_core = db.Column(db.Boolean, nullable=False, default=False)
    is_addon = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=utc_now)


class StudentBand(db.Model):
    __tablename__ = 'student_bands'
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(64), nullable=False, unique=True, index=True)
    min_students = db.Column(db.Integer, nullable=False)
    max_students = db.Column(db.Integer, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)


class PlanModule(db.Model):
    __tablename__ = 'plan_modules'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False, index=True)
    module_id = db.Column(db.Integer, db.ForeignKey('module_catalog.id'), nullable=False, index=True)
    is_included = db.Column(db.Boolean, nullable=False, default=True)
    addon_price_cents = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    __table_args__ = (db.UniqueConstraint('plan_id', 'module_id', name='uq_plan_module'),)


class PlanBandPrice(db.Model):
    __tablename__ = 'plan_band_prices'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False, index=True)
    student_band_id = db.Column(db.Integer, db.ForeignKey('student_bands.id'), nullable=False, index=True)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    currency = db.Column(db.String(16), nullable=False, default='KES')
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)
    __table_args__ = (db.UniqueConstraint('plan_id', 'student_band_id', name='uq_plan_band_price'),)


class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'))
    status = db.Column(db.String(32), default='active')
    billing_cycle = db.Column(db.String(32), nullable=False, default='monthly')
    amount_cents = db.Column(db.Integer, nullable=False, default=0)
    payment_reference = db.Column(db.String(128), nullable=True)
    started_at = db.Column(db.DateTime, default=utc_now)
    renewal_date = db.Column(db.DateTime, nullable=True)
    trial_ends_at = db.Column(db.DateTime, nullable=True)
    grace_period_ends_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    billing_meta = db.Column(db.JSON)

    @property
    def effective_status(self):
        now = utc_now()
        raw_status = (self.status or 'active').lower()

        if raw_status in {'cancelled', 'archived', 'expired', 'suspended'}:
            return raw_status
        if self.archived_at and self.archived_at <= now:
            return 'archived'
        if self.ended_at and self.ended_at <= now:
            return raw_status if raw_status in {'cancelled', 'expired'} else 'expired'
        if self.grace_period_ends_at and self.grace_period_ends_at > now:
            return 'grace_period'
        if self.trial_ends_at and self.trial_ends_at > now and raw_status in {'trial', 'active'}:
            return 'trial'
        return raw_status or 'active'

    @property
    def allows_login(self):
        return self.effective_status in {'trial', 'active', 'grace_period'}

    @property
    def allows_writes(self):
        return self.effective_status in {'trial', 'active'}


class PlatformUser(db.Model):
    __tablename__ = 'platform_users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(64), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    assigned_school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    portfolio_scope = db.Column(db.JSON, nullable=True)
    mfa_enabled = db.Column(db.Boolean, nullable=False, default=False)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    last_failed_login_at = db.Column(db.DateTime, nullable=True)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    last_login_at = db.Column(db.DateTime, nullable=True)

    def is_super_admin(self):
        return self.role == 'super_admin'


class PlatformSetting(db.Model):
    __tablename__ = 'platform_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), nullable=False, unique=True, index=True)
    value_json = db.Column(db.JSON, nullable=False)
    updated_by_user_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'))
    raised_by_email = db.Column(db.String(255))
    subject = db.Column(db.String(255))
    description = db.Column(db.Text)
    status = db.Column(db.String(32), default='open')
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('platform_users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, nullable=True)
    actor_platform = db.Column(db.Boolean, default=True)
    action = db.Column(db.String(255))
    target_table = db.Column(db.String(255))
    target_id = db.Column(db.String(255))
    school_id = db.Column(db.Integer, nullable=True)
    changes = db.Column(db.JSON)
    ip = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=utc_now)


class SecurityEvent(db.Model):
    __tablename__ = 'security_events'
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(128), nullable=False, index=True)
    severity = db.Column(db.String(32), nullable=False, default='medium', index=True)
    status = db.Column(db.String(32), nullable=False, default='open', index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    signal_key = db.Column(db.String(255), nullable=False, index=True)
    school_id = db.Column(db.Integer, nullable=True, index=True)
    related_audit_log_id = db.Column(db.Integer, nullable=True)
    related_support_ticket_id = db.Column(db.Integer, nullable=True)
    threshold_value = db.Column(db.Integer, nullable=True)
    observed_value = db.Column(db.Integer, nullable=True)
    occurrence_count = db.Column(db.Integer, nullable=False, default=1)
    details = db.Column(db.JSON)
    first_seen_at = db.Column(db.DateTime, default=utc_now)
    last_seen_at = db.Column(db.DateTime, default=utc_now, index=True)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    acknowledged_by_user_id = db.Column(db.Integer, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


class SecurityNotificationPreference(db.Model):
    __tablename__ = 'security_notification_preferences'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=True)
    channel = db.Column(db.String(32), nullable=False, index=True)
    destination = db.Column(db.String(512), nullable=False)
    min_severity = db.Column(db.String(32), nullable=False, default='high')
    school_id = db.Column(db.Integer, nullable=True, index=True)
    event_types = db.Column(db.JSON)
    throttle_minutes = db.Column(db.Integer, nullable=False, default=30)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    secret_token = db.Column(db.String(255), nullable=True)
    custom_headers = db.Column(db.JSON)
    created_by_user_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


class SecurityNotificationDelivery(db.Model):
    __tablename__ = 'security_notification_deliveries'
    id = db.Column(db.Integer, primary_key=True)
    security_event_id = db.Column(db.Integer, nullable=False, index=True)
    preference_id = db.Column(db.Integer, nullable=False, index=True)
    channel = db.Column(db.String(32), nullable=False, index=True)
    destination = db.Column(db.String(512), nullable=False)
    status = db.Column(db.String(32), nullable=False, index=True)
    status_reason = db.Column(db.Text, nullable=True)
    response_code = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    throttle_key = db.Column(db.String(255), nullable=False, index=True)
    attempted_at = db.Column(db.DateTime, default=utc_now, index=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
