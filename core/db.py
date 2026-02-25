import pymysql
from flask import current_app
from core.errors import DatabaseConnectionError

def get_db_connection():
    """Create a new database connection using current app config."""
    config = current_app.config
    try:
        connection = pymysql.connect(
            host=config.get('DB_HOST', 'localhost'),
            user=config.get('DB_USER'),
            password=config.get('DB_PASSWORD'),
            database=config.get('DB_NAME'),
            port=int(config.get('DB_PORT', 3306)),
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10
        )
        return connection
    except pymysql.Error as e:
        error_msg = str(e)
        if "account is locked" in error_msg.lower():
            raise DatabaseConnectionError("Database account is currently locked by the hosting provider. Please contact your administrator.") from e
        raise DatabaseConnectionError(f"Database connection error: {error_msg}") from e
