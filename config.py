import os
import urllib.parse as urlparse
from pathlib import Path

# Load .env file if present (for local development). Production should set real env vars.
def _load_local_env():
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        return

    try:
        dotenv_module = __import__('dotenv')
        dotenv_module.load_dotenv(env_path)
        return
    except Exception:
        pass

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _normalize_sqlalchemy_uri(database_uri):
    if database_uri.startswith("postgres://"):
        return database_uri.replace("postgres://", "postgresql://", 1)
    if database_uri.startswith("mysql://"):
        return database_uri.replace("mysql://", "mysql+pymysql://", 1)
    return database_uri


def _parse_connection_settings(database_uri):
    parsed = urlparse.urlparse(database_uri)
    query = urlparse.parse_qs(parsed.query)
    return {
        'host': parsed.hostname,
        'port': parsed.port,
        'user': urlparse.unquote(parsed.username or '') if parsed.username else None,
        'password': urlparse.unquote(parsed.password or '') if parsed.password else None,
        'database': parsed.path.lstrip('/') or None,
        'ssl_ca': query.get('ssl_ca', [None])[0],
    }


_load_local_env()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your_secret_key_please_change_in_production')
    PLATFORM_ROLLOUT_MODE = (os.environ.get('PLATFORM_ROLLOUT_MODE') or 'open').strip().lower()
    PLATFORM_ROLLOUT_ALLOWED_EMAILS = [
        email.strip().lower()
        for email in (os.environ.get('PLATFORM_ROLLOUT_ALLOWED_EMAILS') or '').split(',')
        if email.strip()
    ]
    PLATFORM_ROLLOUT_ALLOWED_ROLES = [
        role.strip().lower()
        for role in (os.environ.get('PLATFORM_ROLLOUT_ALLOWED_ROLES') or '').split(',')
        if role.strip()
    ]
    TENANT_ENFORCEMENT_MODE = (os.environ.get('TENANT_ENFORCEMENT_MODE') or 'enforce').strip().lower()
    TENANT_ENFORCEMENT_NOTES = (os.environ.get('TENANT_ENFORCEMENT_NOTES') or '').strip()

    # Database configuration
    _env_db_host = os.environ.get('DB_HOST')
    _env_db_port = os.environ.get('DB_PORT')
    _env_db_user = os.environ.get('DB_USER')
    _env_db_password = os.environ.get('DB_PASSWORD')
    _env_db_name = os.environ.get('DB_NAME')

    DB_HOST = _env_db_host or 'localhost'
    DB_PORT = int(_env_db_port or 3306)
    DB_USER = _env_db_user or ''
    DB_PASSWORD = _env_db_password or ''
    DB_NAME = _env_db_name or ''

    quoted_password = urlparse.quote_plus(DB_PASSWORD)
    DEFAULT_DB_URI = f"mysql+pymysql://{DB_USER}:{quoted_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    if 'skysql.com' in DB_HOST.lower():
        ca_path = os.path.join(os.path.dirname(__file__), 'globalsignrootca.pem')
        if os.path.exists(ca_path):
            separator = '&' if '?' in DEFAULT_DB_URI else '?'
            DEFAULT_DB_URI += f"{separator}ssl_ca={ca_path}"

    SQLALCHEMY_DATABASE_URI = _normalize_sqlalchemy_uri(os.environ.get("SQLALCHEMY_DATABASE_URI", DEFAULT_DB_URI))
    _parsed_db_settings = _parse_connection_settings(SQLALCHEMY_DATABASE_URI)

    DB_HOST = _env_db_host or _parsed_db_settings['host'] or DB_HOST
    DB_PORT = int(_env_db_port or _parsed_db_settings['port'] or DB_PORT)
    DB_USER = _env_db_user or _parsed_db_settings['user'] or DB_USER
    DB_PASSWORD = _env_db_password or _parsed_db_settings['password'] or DB_PASSWORD
    DB_NAME = _env_db_name or _parsed_db_settings['database'] or DB_NAME
    DB_SSL_CA = os.environ.get('DB_SSL_CA') or _parsed_db_settings['ssl_ca']

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None  # CSRF token doesn't expire
