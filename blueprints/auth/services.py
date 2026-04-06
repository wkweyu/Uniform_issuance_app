from flask import session, current_app, flash
from datetime import UTC, datetime, timedelta
from models import User, School
from .utils import verify_legacy_password
from platform_bp.services.subscriptions import get_subscription_by_school

class AuthService:
    def authenticate(self, school_code, username, password):
        if not school_code:
            return None, "School code is required."

        school = School.query.filter_by(code=school_code).first()
        if not school:
            return None, "Invalid school code."

        today = datetime.now(UTC).date()
        subscription = get_subscription_by_school(school.id)
        effective_status = subscription.effective_status if subscription else None

        if not school.is_active:
            return None, "School is inactive or subscription has expired."

        if subscription and not subscription.allows_login:
            return None, f"School subscription is {effective_status.replace('_', ' ')}. Please contact support."

        if not subscription and school.subscription_end and school.subscription_end < today:
            return None, "School is inactive or subscription has expired."

        user = User.query.filter_by(username=username, school_id=school.id).first()

        if not user or user.access_flag != 1:
            return None, "Invalid username or password."

        if not verify_legacy_password(password, user.pwd, user.userNo):
            return None, "Invalid username or password."

        return user, school

    def get_users(self, school_id):
        from models import User
        return User.query.filter_by(school_id=school_id).all()

    def create_user(self, school_id, username, password, staff_id, access_flag=1, is_admin=False):
        from models import User, db
        from .utils import hash_password
        
        if User.query.filter_by(username=username, school_id=school_id).first():
            raise Exception("Username already exists in this school.")
            
        user = User(
            username=username,
            pwd=hash_password(password),
            access_flag=access_flag,
            TA=1 if is_admin else 0,
            StaffID=staff_id,
            school_id=school_id
        )
        db.session.add(user)
        db.session.commit()
        return user

    def delete_user(self, user_id, school_id):
        from models import User, db
        user = User.query.filter_by(userNo=user_id, school_id=school_id).first()
        if user:
            db.session.delete(user)
            db.session.commit()
            return True
        return False
