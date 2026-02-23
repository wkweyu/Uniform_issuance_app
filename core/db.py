import pymysql
from flask import current_app

def get_db_connection():
    """Create a new database connection using current app config."""
    config = current_app.config
    connection = pymysql.connect(
        host=config.get('DB_HOST', 'localhost'),
        user=config.get('DB_USER'),
        password=config.get('DB_PASSWORD'),
        database=config.get('DB_NAME'),
        port=int(config.get('DB_PORT', 3306)),
        cursorclass=pymysql.cursors.DictCursor
    )
    return connection
