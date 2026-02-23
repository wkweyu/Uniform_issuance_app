from models import School
from extensions import db
from datetime import datetime
from core.audit import audit_log

class SuperAdminService:
    @audit_log('create_school')
    def create_school(self, name, code, subscription_end_date, is_active):
        school = School(
            name=name,
            code=code,
            is_active=is_active,
            subscription_end=subscription_end_date
        )
        db.session.add(school)
        db.session.commit()
        return school

    @audit_log('update_school_status')
    def update_school_status(self, school_id, active):
        school = School.query.get(school_id)
        if school:
            school.is_active = active
            db.session.commit()
        return school

    @audit_log('update_school_subscription')
    def update_school_subscription(self, school_id, end_date):
        school = School.query.get(school_id)
        if school:
            school.subscription_end = end_date
            db.session.commit()
        return school

    def get_all_schools(self):
        return School.query.order_by(School.created_at.desc()).all()

    def get_school_by_code(self, code):
        return School.query.filter_by(code=code).first()
