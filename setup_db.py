import os
import pymysql
import urllib.parse as urlparse

# Fetch DB credentials from environment
DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('DB_HOST')

if DATABASE_URL and '://' in DATABASE_URL:
    url = urlparse.urlparse(DATABASE_URL)
    DB_HOST = url.hostname
    DB_USER = url.username
    DB_PASSWORD = url.password
    DB_NAME = url.path.lstrip('/')
    DB_PORT = url.port or 3306
else:
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_USER = os.environ.get('DB_USER', 'schooluser')
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS', 'jbs')
    DB_NAME = os.environ.get('DB_NAME', 'schoolmngt')
    DB_PORT = int(os.environ.get('DB_PORT', 3306))

def setup_database():
    print(f"Connecting to {DB_HOST} on port {DB_PORT} as {DB_USER}...")
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS
        )
        
        # Files to run in order
        sql_files = ['uniform_app_setup.sql', 'school_management_migration_v1.sql']
        
        with conn.cursor() as cursor:
            for sql_file in sql_files:
                if os.path.exists(sql_file):
                    print(f"Executing {sql_file}...")
                    with open(sql_file, 'r', encoding='utf-8') as f:
                        sql_content = f.read()
                        # Remove comments and empty lines to avoid issues
                        cursor.execute(sql_content)
                    print(f"Successfully executed {sql_file}")
                else:
                    print(f"Warning: {sql_file} not found, skipping.")
            
            conn.commit()
            print("✔️ Database setup successfully completed!")
            
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    setup_database()
