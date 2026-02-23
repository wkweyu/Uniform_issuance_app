from flask import session, current_app, flash
from datetime import datetime, timedelta
from models import User, School
from .utils import verify_legacy_password

class AuthService:
    def authenticate(self, school_code, username, password):
        if not school_code:
            return None, "School code is required."

        school = School.query.filter_by(code=school_code).first()
        if not school:
            return None, "Invalid school code."

        today = datetime.utcnow().date()
        if not school.is_active or (school.subscription_end and school.subscription_end < today):
            return None, "School is inactive or subscription has expired."

        user = User.query.filter_by(username=username, school_id=school.id).first()

        if not user or user.access_flag != 1:
            return None, "Invalid username or password."

        if not verify_legacy_password(password, user.pwd, user.userNo):
            return None, "Invalid username or password."

        return user, school
