import os
from playwright.sync_api import sync_playwright
from app import create_app
from extensions import db
from platform_bp.models import PlatformUser, Plan
from werkzeug.security import generate_password_hash
import time

def setup_test_db():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['TESTING'] = True

    with app.app_context():
        db.create_all()
        # Seed a super admin
        if not PlatformUser.query.filter_by(email="admin@skooltrack.pro").first():
            user = PlatformUser(
                name="Super Admin",
                email="admin@skooltrack.pro",
                password_hash=generate_password_hash("Admin123"),
                role="super_admin",
                is_active=True
            )
            db.session.add(user)
            db.session.commit()
    return app

def run_verification():
    app = setup_test_db()

    # Start the Flask app in the background
    import threading
    def run_app():
        app.run(port=5001, debug=False, use_reloader=False)

    thread = threading.Thread(target=run_app)
    thread.daemon = True
    thread.start()

    time.sleep(2) # Wait for server to start

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # 1. Login
            page.goto("http://127.0.0.1:5001/platform/login")
            page.fill('input[name="email"]', "admin@skooltrack.pro")
            page.fill('input[name="password"]', "Admin123")
            page.click('button[type="submit"]')

            # 2. Dashboard
            page.wait_for_url("**/platform/")
            page.screenshot(path="dashboard_verification.png", full_page=True)
            print("Dashboard screenshot saved")

            # 3. Operators List
            page.goto("http://127.0.0.1:5001/platform/users")
            page.screenshot(path="operators_list_verification.png", full_page=True)
            print("Operators list screenshot saved")

            # 4. Create User (Check Roles and Password Policy)
            page.goto("http://127.0.0.1:5001/platform/users/create")
            page.screenshot(path="create_user_verification.png", full_page=True)
            print("Create user screenshot saved")

        finally:
            browser.close()
            if os.path.exists("test.db"):
                os.remove("test.db")

if __name__ == "__main__":
    run_verification()
