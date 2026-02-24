import os
import urllib.parse as urlparse
from pathlib import Path

# Load .env file if present (for local development). Production should set real env vars.
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except Exception:
    pass

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your_secret_key_please_change_in_production')

    # Database configuration
    DB_HOST = os.environ.get('DB_HOST', 'localhost').strip()
    _db_port_env = os.environ.get('DB_PORT', '3306').strip()
    try:
        DB_PORT = int(_db_port_env)
    except ValueError:
        DB_PORT = 3306

    DB_USER = os.environ.get('DB_USER', '').strip()
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '').strip()
    DB_NAME = os.environ.get('DB_NAME', '').strip()

    quoted_password = urlparse.quote_plus(DB_PASSWORD)
    DEFAULT_DB_URI = f"mysql+pymysql://{DB_USER}:{quoted_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    if 'skysql.com' in DB_HOST.lower():
        ca_path = os.path.join(os.path.dirname(__file__), 'globalsignrootca.pem')
        if os.path.exists(ca_path):
            separator = '&' if '?' in DEFAULT_DB_URI else '?'
            DEFAULT_DB_URI += f"{separator}ssl_ca={ca_path}"

    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", DEFAULT_DB_URI)
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    elif SQLALCHEMY_DATABASE_URI.startswith("mysql://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("mysql://", "mysql+pymysql://", 1)

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None  # CSRF token doesn't expire
