from flask import render_template, request


def tenant_user_search():
    q = request.args.get('q', '').strip()
    results = []
    if q:
        # search by userNo or username or StaffID
        if q.isdigit():
            from app import db
            results = db.session.execute(
                "SELECT userNo, username, StaffID, school_id FROM users WHERE userNo = :id LIMIT 50",
                {'id': int(q)}
            ).fetchall()
        else:
            like = f"%{q}%"
            from app import db
            results = db.session.execute(
                "SELECT userNo, username, StaffID, school_id FROM users WHERE username LIKE :like OR StaffID LIKE :like LIMIT 50",
                {'like': like}
            ).fetchall()
    return render_template('platform/tenant_user_search.html', q=q, results=results)


def register_routes(bp):
    bp.add_url_rule('/tenant-users/search', endpoint='tenant_user_search', view_func=tenant_user_search, methods=['GET'])
