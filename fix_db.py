import pymysql
import os

# Database details
DB_HOST = os.environ.get('DB_HOST', 'serverless-eu-west-3.sysp0000.db1.skysql.com')
DB_USER = os.environ.get('DB_USER', 'dbpwf28831395')
DB_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS', '4FjBYp4aP0p3g{cx5?GCHbs')
DB_NAME = os.environ.get('DB_NAME', 'schoolmngt')
DB_PORT = int(os.environ.get('DB_PORT', 4018))

def fix_database():
    print(f"Connecting to fix database: {DB_NAME}...")
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT
        )
        
        with conn.cursor() as cursor:
            # 1. Fix password column length for modern hashes
            print("Fixing users table password column length...")
            cursor.execute("ALTER TABLE users MODIFY COLUMN pwd VARCHAR(255);")
            
            # 2. Add 'active' column to buses if missing (requested by index route)
            print("Checking buses table for 'active' column...")
            try:
                cursor.execute("SELECT active FROM buses LIMIT 1")
            except:
                print("Adding 'active' column to buses...")
                cursor.execute("ALTER TABLE buses ADD COLUMN active TINYINT(1) DEFAULT 1;")

            # 3. Add 'is_admin' related field if missing (TA)
            print("Checking users table for 'TA' column...")
            try:
                cursor.execute("SELECT TA FROM users LIMIT 1")
            except:
                print("Adding 'TA' column to users...")
                cursor.execute("ALTER TABLE users ADD COLUMN TA INT(1) DEFAULT 0;")
            
            conn.commit()
            print("✔️ Database fixes applied successfully!")
            
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    fix_database()
