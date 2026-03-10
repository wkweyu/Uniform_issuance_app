from datetime import datetime
from app import db


class Plan(db.Model):
    __tablename__ = 'plans'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    billing_period = db.Column(db.String(32), nullable=False, default='monthly')
    features = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'))
    status = db.Column(db.String(32), default='active')
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    renewal_date = db.Column(db.DateTime, nullable=True)
    billing_meta = db.Column(db.JSON)


class PlatformUser(db.Model):
    __tablename__ = 'platform_users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(64), nullable=False)
    assigned_school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    def is_super_admin(self):
        return self.role == 'super_admin'


class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'))
    raised_by_email = db.Column(db.String(255))
    subject = db.Column(db.String(255))
    description = db.Column(db.Text)
    status = db.Column(db.String(32), default='open')
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('platform_users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
