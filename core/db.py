import pymysql
from pathlib import Path
from flask import current_app


def _get_ssl_config(config):
    ca_path = config.get('DB_SSL_CA')
    if ca_path and Path(ca_path).exists():
        return {'ca': ca_path, 'check_hostname': False}

    db_host = (config.get('DB_HOST') or '').lower()
    default_ca = Path(current_app.root_path) / 'globalsignrootca.pem'
    if 'skysql.com' in db_host and default_ca.exists():
        return {'ca': str(default_ca), 'check_hostname': False}

    return None


def get_db_connection():
    """Create a new database connection using current app config."""
    config = current_app.config
    connection = pymysql.connect(
        host=config.get('DB_HOST', 'localhost'),
        user=config.get('DB_USER'),
        password=config.get('DB_PASSWORD'),
        database=config.get('DB_NAME'),
        port=int(config.get('DB_PORT', 3306)),
        ssl=_get_ssl_config(config),
        cursorclass=pymysql.cursors.DictCursor
    )
    return connection
