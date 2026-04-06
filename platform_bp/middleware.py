import traceback
from flask import g, request, session, current_app


def register_platform_middleware(app):
    @app.before_request
    def resolve_platform_context():
        # Set a platform-specific context if platform_user is logged in
        g.platform_user_id = session.get('platform_user_id')
        g.platform_current_user = None
        g.platform_user_loaded = False
        # For tenant resolution prefer session school_id (existing app behavior)
        g.current_school_id = session.get('school_id')

        # Optionally allow X-School-ID header for platform API calls
        header_school = request.headers.get('X-School-ID')
        if header_school and header_school.isdigit():
            g.current_school_id = int(header_school)

    @app.teardown_request
    def log_errors_to_db(exception):
        if exception:
            try:
                from .models import ErrorLog, db
                from flask import has_request_context

                school_id = g.get('school_id') or session.get('school_id')
                user_id = session.get('userNo')
                platform_user_id = session.get('platform_user_id')

                log_entry = ErrorLog(
                    school_id=school_id,
                    user_id=user_id,
                    platform_user_id=platform_user_id,
                    endpoint=request.endpoint,
                    method=request.method,
                    error_message=str(exception),
                    stack_trace=traceback.format_exc(),
                    request_data=request.get_json(silent=True) or request.form.to_dict() or None,
                    ip_address=request.remote_addr,
                    user_agent=request.user_agent.string,
                )
                db.session.add(log_entry)
                db.session.commit()
            except Exception as e:
                # Fallback if DB logging fails - don't want to cause another 500
                current_app.logger.error(f"Failed to log error to DB: {e}")
