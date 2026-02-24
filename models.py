from extensions import db
from datetime import datetime
from flask import g

class TenantMixin:
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), index=True, default=lambda: getattr(g, 'school_id', None))

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

class StudentInfo(db.Model, TenantMixin):
    __tablename__ = 'studentinfo'
    AdmNo = db.Column(db.String(20), primary_key=True)
    FName = db.Column(db.String(255), nullable=False)
    MName = db.Column(db.String(255))
    SName = db.Column(db.String(255))
    Sex = db.Column(db.String(10))
    DoB = db.Column(db.Date)
    Date_Adm = db.Column(db.Date)
    category = db.Column(db.String(50))
    stream = db.Column(db.String(50))
    parentID = db.Column(db.Integer)

class Class(db.Model, TenantMixin):
    __tablename__ = 'classes'
    classID = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(50))
    display_name = db.Column(db.String(100))
    academic_year_id = db.Column(db.Integer)
    class_group = db.Column(db.String(50))
    stream_code = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)

class AcademicYear(db.Model, TenantMixin):
    __tablename__ = 'academic_years'
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(100))
    is_current = db.Column(db.Boolean, default=False)

class UniformPrice(db.Model, TenantMixin):
    __tablename__ = 'uniform_prices'
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(255))
    class_group = db.Column(db.String(255))
    price = db.Column(db.Numeric(10, 2))
    stock = db.Column(db.Integer, default=0)

class UniformReceipt(db.Model, TenantMixin):
    __tablename__ = 'uniform_receipts'
    id = db.Column(db.Integer, primary_key=True)
    receipt_no = db.Column(db.String(20))
    admno = db.Column(db.String(20))
    item_name = db.Column(db.String(255))
    quantity = db.Column(db.Integer)
    unit_price = db.Column(db.Numeric(10, 2))
    total_price = db.Column(db.Numeric(10, 2))
    term = db.Column(db.Integer)
    yr = db.Column(db.Integer)
    date_issued = db.Column(db.DateTime, default=datetime.utcnow)
    issued_by = db.Column(db.Integer)

class TermDate(db.Model, TenantMixin):
    __tablename__ = 'uniform_term_dates'
    id = db.Column(db.Integer, primary_key=True)
    term_number = db.Column(db.Integer)
    year = db.Column(db.Integer)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_current = db.Column(db.Boolean, default=False)
