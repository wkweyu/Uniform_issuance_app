import os
import pymysql
from werkzeug.security import generate_password_hash

# Fetch DB credentials from environment or use defaults
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_USER = os.environ.get('DB_USER', 'schooluser')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'jbs')
DB_NAME = os.environ.get('DB_NAME', 'schoolmngt')
DB_PORT = int(os.environ.get('DB_PORT', 3306))

def create_admin():
    print(f"Connecting to {DB_HOST}...")
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT
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
