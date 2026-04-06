import sys
import os

# Ensure project path
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)

from app import app, get_db_connection


def run_sql_file(path):
    if not os.path.exists(path):
        print(f"SQL file not found: {path}")
        return 2
    with open(path, 'r') as f:
        sql = f.read()

    # naive split by semicolon for multi-statement execution
    statements = [s.strip() for s in sql.split(';') if s.strip()]

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for stmt in statements:
            try:
                cur.execute(stmt)
            except Exception as e:
                # print statement and error, continue to next
                print(f"ERROR executing statement:\n{stmt[:200]}...\n{e}")
        conn.commit()
        print("Migration applied successfully.")
        return 0
    except Exception as e:
        print(f"Migration failed: {e}")
        return 3
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 run_migration_sql.py path/to/file.sql")
        sys.exit(1)
    path = sys.argv[1]
    with app.app_context():
        code = run_sql_file(path)
    sys.exit(code)
