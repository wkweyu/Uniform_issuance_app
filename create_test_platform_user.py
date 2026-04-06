from app import create_app
from extensions import db
from platform_bp.models import PlatformUser
from werkzeug.security import generate_password_hash

app = create_app()
with app.app_context():
    # Try to create tables if they don't exist (using SQLAlchemy create_all as a shortcut for tests)
    try:
        db.create_all()
    except Exception as e:
        print(f"Warning during create_all: {e}")

    email = "admin@skooltrack.pro"
    user = PlatformUser.query.filter_by(email=email).first()
    if not user:
        user = PlatformUser(
            name="Super Admin",
            email=email,
            password_hash=generate_password_hash("Admin123"),
            role="super_admin",
            is_active=True
        )
        db.session.add(user)
        db.session.commit()
        print(f"Created platform user: {email}")
    else:
        print(f"Platform user {email} already exists")
