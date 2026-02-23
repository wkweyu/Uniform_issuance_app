from extensions import db
from datetime import datetime

class TenantMixin:
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), index=True)

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(20), unique=True, index=True)
    is_active = db.Column(db.Boolean, default=True)
    subscription_end = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
