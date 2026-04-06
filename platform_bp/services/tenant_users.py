from sqlalchemy import or_

from models import User


def search_tenant_users(query, limit=50):
    normalized_query = (query or '').strip()
    if not normalized_query:
        return []

    user_query = User.query.with_entities(
        User.userNo,
        User.username,
        User.StaffID,
        User.school_id,
    )

    if normalized_query.isdigit():
        return user_query.filter(User.userNo == int(normalized_query)).limit(limit).all()

    like_term = f"%{normalized_query}%"
    return user_query.filter(
        or_(
            User.username.like(like_term),
            User.StaffID.like(like_term),
        )
    ).limit(limit).all()