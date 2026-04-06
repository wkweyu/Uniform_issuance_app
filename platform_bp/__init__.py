from flask import Blueprint
import traceback


def init_platform(app, url_prefix='/platform'):
    """Register the platform blueprint with the app.

    This creates a fresh Blueprint, registers routes by calling each route
    module's `register_routes(bp)` function, then registers the blueprint
    with the Flask app. Creating the blueprint here avoids decorator-time
    registration issues during module import.
    """
    bp = Blueprint('platform', __name__, template_folder='templates', static_folder='../static')

    # Import route modules and have them attach their routes to `bp`.
    try:
        from .routes import users, schools, plans, subscriptions, support, audit, security, tenant_user_search, onboarding, access_settings, reports  # noqa
        for mod in (users, schools, plans, subscriptions, support, audit, security, tenant_user_search, onboarding, access_settings, reports):
            try:
                if hasattr(mod, 'register_routes'):
                    mod.register_routes(bp)
            except Exception as e:
                print(f"WARNING: failed to register routes from module {mod}: {e}")
                traceback.print_exc()
    except Exception as e:
        print(f"WARNING: Could not import platform routes: {e}")
        traceback.print_exc()

    # Now register the blueprint with the app
    app.register_blueprint(bp, url_prefix=url_prefix)

    # Optionally register platform-specific middleware here if desired
    try:
        from .middleware import register_platform_middleware
        register_platform_middleware(app)
    except Exception as e:
        print(f"WARNING: Could not register platform middleware: {e}")

    @app.context_processor
    def inject_platform_access_context():
        from .decorators import get_current_platform_user
        from .services.access import platform_user_has_permission, role_label

        current_user = get_current_platform_user()
        
        def is_saas_user():
            # A user is a SaaS user if they are logged in as a platform operator
            return current_user is not None

        return {
            'platform_current_user': current_user,
            'platform_has_permission': lambda permission: platform_user_has_permission(current_user, permission),
            'platform_role_label': role_label,
            'platform_is_saas_user': is_saas_user,
        }
