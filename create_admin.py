import os
import pymysql
import urllib.parse as urlparse
from werkzeug.security import generate_password_hash
import config

# Fetch DB credentials from environment
DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('DB_HOST')

if DATABASE_URL and '://' in DATABASE_URL:
    # Handle mysql://user:pass@host:port/dbname
    url = urlparse.urlparse(DATABASE_URL)
    DB_HOST = url.hostname
    DB_USER = url.username
    DB_PASSWORD = url.password
    DB_NAME = url.path.lstrip('/')
    DB_PORT = url.port or 3306
else:
    # Prefer environment variables; fall back to central config defaults
    DB_HOST = os.environ.get('DB_HOST', getattr(config, 'DB_HOST', 'localhost'))
    DB_USER = os.environ.get('DB_USER', getattr(config, 'DB_USER', 'root'))
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS', getattr(config, 'DB_PASSWORD', ''))
    DB_NAME = os.environ.get('DB_NAME', getattr(config, 'DB_NAME', 'schoolmngt'))
    DB_PORT = int(os.environ.get('DB_PORT', getattr(config, 'DB_PORT', 3306)))

def create_admin():
    if not DB_HOST or DB_HOST == 'localhost' and 'RENDER' in os.environ:
        print("ERROR: DB_HOST is not set correctly for Render environment.")
        return

    print(f"Connecting to {DB_HOST} on port {DB_PORT} as {DB_USER}...")
    try:
        # Enable SSL for SkySQL with CA cert
        ssl_config = None
        if 'skysql.com' in DB_HOST.lower():
            ca_path = os.path.join(os.path.dirname(__file__), 'globalsignrootca.pem')
            if os.path.exists(ca_path):
                ssl_config = {'ca': ca_path, 'check_hostname': False}
            else:
                ssl_config = True

        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            ssl=ssl_config
        )
        
        with conn.cursor() as cursor:
            username = "admin"
            password = "admin_password123" # CHANGE THIS LATER
            hashed_pw = generate_password_hash(password)
            
            # Check if user exists
            cursor.execute("SELECT userNo FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                print(f"User '{username}' already exists.")
                return

            # Insert admin user
            # access_flag=1 (Active), TA=1 (Admin)
            sql = """
                INSERT INTO users (username, pwd, access_flag, TA, StaffID) 
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (username, hashed_pw, 1, 1, 'ADMIN-001'))
            conn.commit()
            print(f"SUCCESS: Admin user '{username}' created with password '{password}'")
            
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    create_admin()
