from flask import g, request, session


def register_platform_middleware(app):
    @app.before_request
    def resolve_platform_context():
        # Set a platform-specific context if platform_user is logged in
        g.platform_user_id = session.get('platform_user_id')
        # For tenant resolution prefer session school_id (existing app behavior)
        g.current_school_id = session.get('school_id')

        # Optionally allow X-School-ID header for platform API calls
        header_school = request.headers.get('X-School-ID')
        if header_school and header_school.isdigit():
            g.current_school_id = int(header_school)
