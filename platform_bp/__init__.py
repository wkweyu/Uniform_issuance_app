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
        from .routes import users, schools, plans, subscriptions, support, audit, tenant_user_search, onboarding  # noqa
        for mod in (users, schools, plans, subscriptions, support, audit, tenant_user_search, onboarding):
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
