import pymysql
import os
import glob
import re
import config

def run_migrations():
    # Connection details: prefer environment variables, then central config
    DB_HOST = os.environ.get('DB_HOST', getattr(config, 'DB_HOST', 'localhost'))
    DB_PORT = int(os.environ.get('DB_PORT', getattr(config, 'DB_PORT', 3306)))
    DB_USER = os.environ.get('DB_USER', getattr(config, 'DB_USER', 'root'))
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS', getattr(config, 'DB_PASSWORD', ''))
    DB_NAME = os.environ.get('DB_NAME', getattr(config, 'DB_NAME', 'schoolmngt'))

    ssl_config = None
    ca_path = os.path.join(os.getcwd(), 'globalsignrootca.pem')
    if os.path.exists(ca_path):
        ssl_config = {'ca': ca_path, 'check_hostname': False}
        print(f"DEBUG: Using SSL certificate at {ca_path}")
    else:
        print("WARNING: globalsignrootca.pem not found, SSL might fail.")

    try:
        connection = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            ssl=ssl_config,
            autocommit=True
        )
        print(f"Connected to {DB_HOST}")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    with connection.cursor() as cursor:
        # Get all migration files in order
        migration_files = sorted(glob.glob('migrations/*.sql'))
        
        for file_path in migration_files:
            print(f"Running migration: {file_path}")
            with open(file_path, 'r') as f:
                sql_content = f.read()
            
            # Remove comments and split by semicolon
            # This is a naive split, but usually works for simple migrations
            # Better: split by semicolon only if not inside quotes, but we'll try simple first.
            statements = sql_content.split(';')
            
            for statement in statements:
                stmt = statement.strip()
                if not stmt:
                    continue
                
                try:
                    cursor.execute(stmt)
                    # print(f"  OK: {stmt[:50]}...")
                except pymysql.err.InternalError as e:
                    # Ignore "Duplicate column name" (1060) and "Table already exists" (1050)
                    # and "Duplicate key name" (1061), "Can't DROP; check that column/key exists" (1091)
                    if e.args[0] in [1060, 1050, 1061, 1091]:
                        # print(f"  Skipped (already applied): {e.args[1]}")
                        pass
                    else:
                        print(f"  ERROR in {file_path}: {e}")
                except Exception as e:
                    print(f"  CRITICAL ERROR in {file_path}: {e}")

    connection.close()
    print("Migration process completed.")

if __name__ == "__main__":
    run_migrations()
