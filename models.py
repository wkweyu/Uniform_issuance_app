from extensions import db
from datetime import UTC, datetime


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


class TenantMixin:
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), index=True)


class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(20), unique=True, index=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(128), nullable=True)
    country = db.Column(db.String(128), nullable=True)
    logo = db.Column(db.String(255), nullable=True)
    subscription_plan = db.Column(db.String(64), nullable=True)
    subscription_status = db.Column(db.String(32), nullable=False, default='trial')
    subscription_start = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    subscription_end = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=utc_now)
    settings = db.relationship('SchoolSettings', back_populates='school', uselist=False, cascade='all, delete-orphan')

    @property
    def school_name(self):
        return self.name


class User(db.Model, TenantMixin):
    __tablename__ = 'users'
    userNo = db.Column(db.Integer, primary_key=True)
    StaffID = db.Column(db.String(6))
    username = db.Column(db.String(32))
    pwd = db.Column(db.String(32), default='123456')
    domainID = db.Column(db.Integer)
    access_flag = db.Column(db.SmallInteger, default=1)
    dateReg = db.Column(db.String(32))
    RegStaffID = db.Column(db.String(6))
    TA = db.Column(db.SmallInteger, default=0)
    _date = db.Column(db.DateTime)


class UniformPrice(db.Model, TenantMixin):
    __tablename__ = 'uniform_prices'
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(255))
    class_group = db.Column(db.String(255))
    price = db.Column(db.Numeric(10, 2))


class SchoolSettings(db.Model):
    __tablename__ = 'school_settings'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False, unique=True, index=True)
    school_name = db.Column(db.String(255), nullable=True)
    logo = db.Column(db.String(255), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(64), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    timezone = db.Column(db.String(64), nullable=False, default='UTC')
    currency = db.Column(db.String(16), nullable=False, default='USD')
    grading_system = db.Column(db.String(64), nullable=True)
    report_template = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)
    school = db.relationship('School', back_populates='settings')
