import pymysql
import os
import glob
import config

def migrate_db():
    # Enable SSL for SkySQL
    ssl_config = None
    ca_path = os.path.join(os.path.dirname(__file__), 'globalsignrootca.pem')
    if os.path.exists(ca_path):
        ssl_config = {'ca': ca_path, 'check_hostname': False}
    else:
        ssl_config = True

    print("Connecting to cloud database...")
    DB_HOST = os.environ.get('DB_HOST', getattr(config, 'DB_HOST', 'localhost'))
    DB_PORT = int(os.environ.get('DB_PORT', getattr(config, 'DB_PORT', 3306)))
    DB_USER = os.environ.get('DB_USER', getattr(config, 'DB_USER', 'root'))
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS', getattr(config, 'DB_PASSWORD', ''))
    DB_NAME = os.environ.get('DB_NAME', getattr(config, 'DB_NAME', 'schoolmngt'))

    connection = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
        ssl=ssl_config,
        autocommit=True
    )

    try:
        with connection.cursor() as cursor:
            # First run schema.sql if it's new
            if os.path.exists('schema.sql'):
                print("Running schema.sql...")
                try:
                    with open('schema.sql', 'r') as f:
                        sql_script = f.read()
                    for statement in sql_script.split(';'):
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)
                    print("✔️ schema.sql completed.")
                except Exception as e:
                    print(f"⚠️ schema.sql had issues (might already be applied): {e}")

            # Now run all migrations in order
            migration_files = sorted(glob.glob('migrations/*.sql'))
            for mig_file in migration_files:
                print(f"Running migration: {mig_file}...")
                with open(mig_file, 'r') as f:
                    sql_script = f.read()
                
                # Split statements and execute one by one
                statements = sql_script.split(';')
                for statement in statements:
                    statement = statement.strip()
                    if not statement:
                        continue
                    
                    try:
                        cursor.execute(statement)
                        # print(f"  ✔️ Executed statement.")
                    except pymysql.err.InternalError as e:
                        if 'Duplicate column name' in str(e) or 'already exists' in str(e) or 'Duplicate key name' in str(e) or 'Duplicate entry' in str(e):
                            # print(f"  ⏭️ Skipping statement (already applied).")
                            pass
                        else:
                            print(f"  ❌ Error in statement: {e}")
                    except pymysql.err.OperationalError as e:
                        if 'Duplicate column name' in str(e) or 'already exists' in str(e) or 'Duplicate key name' in str(e):
                             # print(f"  ⏭️ Skipping statement (already applied).")
                             pass
                        else:
                            print(f"  ❌ Error in statement: {e}")
                    except Exception as e:
                        print(f"  ❌ Unexpected error in statement: {e}")
                
                print(f"✔️ Finished processing {mig_file}")

        print("\n✅ All database migrations completed.")
    finally:
        connection.close()

if __name__ == "__main__":
    migrate_db()
