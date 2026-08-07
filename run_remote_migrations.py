import argparse
import sys
import pymysql
import os
import glob
import re
import config


CREATE_TABLE_RE = re.compile(r'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?(?P<table>\w+)`?\s*\((?P<body>.*)\)\s*(ENGINE|DEFAULT|CHARSET|COLLATE|$)', re.IGNORECASE | re.DOTALL)
COLUMN_DEF_RE = re.compile(r'^`(?P<name>[^`]+)`\s+(?P<type>[A-Z]+(?:\s*\([^)]*\))?(?:\s+UNSIGNED)?)', re.IGNORECASE)
FK_RE = re.compile(r'FOREIGN\s+KEY\s*\(`(?P<local>[^`]+)`\)\s+REFERENCES\s+`(?P<ref_table>[^`]+)`\s*\(`(?P<ref_column>[^`]+)`\)', re.IGNORECASE)


def _normalize_column_type(column_type):
    normalized = re.sub(r'\s+', ' ', (column_type or '').strip().lower())
    normalized = re.sub(
        r'\b(tinyint|smallint|mediumint|int|bigint)\s*\(\d+\)',
        r'\1',
        normalized,
    )
    return normalized


def _strip_sql_comments(sql_content):
    cleaned_lines = []
    for raw_line in sql_content.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith('--') or stripped.startswith('#'):
            continue
        cleaned_lines.append(raw_line)
    return '\n'.join(cleaned_lines)


def _split_sql_statements(sql_content):
    return [statement.strip() for statement in _strip_sql_comments(sql_content).split(';') if statement.strip()]


def _is_ignorable_migration_error(error):
    error_code = error.args[0] if error.args else None
    error_message = error.args[1] if len(error.args) > 1 else str(error)
    if error_code in [1050, 1060, 1061, 1091, 1826]:
        return True
    if error_code == 1005 and 'Duplicate key on write or update' in error_message:
        return True
    return False


def _is_character_type(column_type):
    return _normalize_column_type(column_type).startswith(('char', 'varchar', 'text'))


def _get_live_column_metadata(cursor, table_name, column_name, database_name):
    cursor.execute(
        """
        SELECT COLUMN_TYPE, DATA_TYPE, CHARACTER_SET_NAME, COLLATION_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (database_name, table_name, column_name),
    )
    return cursor.fetchone()


def _parse_create_table_statement(statement):
    match = CREATE_TABLE_RE.search(statement)
    if not match:
        return None, {}, []

    table_name = match.group('table')
    body = match.group('body')
    column_types = {}
    foreign_keys = []

    for raw_line in body.splitlines():
        line = raw_line.strip().rstrip(',')
        if not line:
            continue
        column_match = COLUMN_DEF_RE.match(line)
        if column_match:
            column_types[column_match.group('name')] = column_match.group('type')
            continue
        fk_match = FK_RE.search(line)
        if fk_match:
            foreign_keys.append(fk_match.groupdict())

    return table_name, column_types, foreign_keys


def _preflight_foreign_keys(cursor, file_path, statement, database_name, planned_tables=None):
    table_name, column_types, foreign_keys = _parse_create_table_statement(statement)
    if not table_name or not foreign_keys:
        return

    table_charset_match = re.search(r'CHARSET\s*=\s*(\w+)', statement, re.IGNORECASE)
    table_collation_match = re.search(r'COLLATE\s*=\s*(\w+)', statement, re.IGNORECASE)
    table_charset = table_charset_match.group(1) if table_charset_match else None
    table_collation = table_collation_match.group(1) if table_collation_match else None

    for foreign_key in foreign_keys:
        local_column = foreign_key['local']
        ref_table = foreign_key['ref_table']
        ref_column = foreign_key['ref_column']
        local_column_type = column_types.get(local_column)
        if not local_column_type:
            raise RuntimeError(
                f"could not determine local type for {table_name}.{local_column}"
            )

        live_reference = _get_live_column_metadata(cursor, ref_table, ref_column, database_name)
        planned_reference_type = (planned_tables or {}).get(ref_table, {}).get(ref_column)
        if not live_reference and not planned_reference_type:
            raise RuntimeError(
                f"referenced column {ref_table}.{ref_column} does not exist in database {database_name}"
            )

        normalized_local = _normalize_column_type(local_column_type)
        reference_type = live_reference['COLUMN_TYPE'] if live_reference else planned_reference_type
        normalized_reference = _normalize_column_type(reference_type)
        if normalized_local != normalized_reference:
            raise RuntimeError(
                f"foreign key type mismatch for {table_name}.{local_column} ({local_column_type}) -> {ref_table}.{ref_column} ({reference_type})"
            )

        if _is_character_type(local_column_type) and live_reference:
            if table_charset and live_reference['CHARACTER_SET_NAME'] and table_charset.lower() != live_reference['CHARACTER_SET_NAME'].lower():
                raise RuntimeError(
                    f"foreign key charset mismatch for {table_name}.{local_column} ({table_charset}) -> {ref_table}.{ref_column} ({live_reference['CHARACTER_SET_NAME']})"
                )
            if table_collation and live_reference['COLLATION_NAME'] and table_collation.lower() != live_reference['COLLATION_NAME'].lower():
                raise RuntimeError(
                    f"foreign key collation mismatch for {table_name}.{local_column} ({table_collation}) -> {ref_table}.{ref_column} ({live_reference['COLLATION_NAME']})"
                )


def _preflight_fee_payment_reference_uniqueness(cursor, file_path):
    """Ensure migration 041 can add its tenant-scoped receipt-reference key."""
    if os.path.basename(file_path) != '041_tenant_scoped_fee_payment_references.sql':
        return

    cursor.execute("""
        SELECT school_id, payment_mode, reference_number, COUNT(*) AS duplicate_count
        FROM fee_payments
        WHERE reference_number IS NOT NULL AND TRIM(reference_number) <> ''
        GROUP BY school_id, payment_mode, reference_number
        HAVING COUNT(*) > 1
        LIMIT 5
    """)
    duplicates = cursor.fetchall()
    if not duplicates:
        return

    examples = ', '.join(
        f"school {row['school_id']} / {row['payment_mode']} / {row['reference_number']} ({row['duplicate_count']})"
        for row in duplicates
    )
    raise RuntimeError(
        'duplicate fee payment references block migration 041: '
        f'{examples}'
    )


def _preflight_cashier_session_open_uniqueness(cursor, file_path):
    """Ensure migration 043 can add its single-open-session guard."""
    if os.path.basename(file_path) != '043_cashier_session_open_guard.sql':
        return

    cursor.execute("""
        SELECT school_id, cashier_user_id, COUNT(*) AS duplicate_count
        FROM cashier_sessions
        WHERE status = 'OPEN'
        GROUP BY school_id, cashier_user_id
        HAVING COUNT(*) > 1
        LIMIT 5
    """)
    duplicates = cursor.fetchall()
    if not duplicates:
        return

    examples = ', '.join(
        f"school {row['school_id']} / cashier {row['cashier_user_id']} ({row['duplicate_count']})"
        for row in duplicates
    )
    raise RuntimeError(
        'duplicate open cashier sessions block migration 043: '
        f'{examples}'
    )


def _get_connection_settings():
    """Resolve migration credentials from explicit environment variables or Config."""
    settings = getattr(config, 'Config', config)
    return {
        'host': os.environ.get('DB_HOST') or getattr(settings, 'DB_HOST', 'localhost'),
        'port': int(os.environ.get('DB_PORT') or getattr(settings, 'DB_PORT', 3306)),
        'user': os.environ.get('DB_USER') or getattr(settings, 'DB_USER', 'root'),
        'password': os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS') or getattr(settings, 'DB_PASSWORD', ''),
        'database': os.environ.get('DB_NAME') or getattr(settings, 'DB_NAME', 'schoolmngt'),
        'ssl_ca': os.environ.get('DB_SSL_CA') or getattr(settings, 'DB_SSL_CA', None),
    }


def run_migrations(preflight_only=False):
    # Connection details: prefer environment variables, then central config
    connection_settings = _get_connection_settings()
    DB_HOST = connection_settings['host']
    DB_PORT = connection_settings['port']
    DB_USER = connection_settings['user']
    DB_PASSWORD = connection_settings['password']
    DB_NAME = connection_settings['database']

    ssl_config = None
    configured_ca_path = connection_settings['ssl_ca']
    default_skysql_ca_path = os.path.join(os.getcwd(), 'globalsignrootca.pem')
    ca_path = configured_ca_path or (default_skysql_ca_path if 'skysql.com' in DB_HOST.lower() else None)
    if ca_path and os.path.exists(ca_path):
        ssl_config = {'ca': ca_path, 'check_hostname': False}
        print(f"DEBUG: Using SSL certificate at {ca_path}")
    elif configured_ca_path:
        print(f"WARNING: configured DB_SSL_CA was not found at {configured_ca_path}.")
    elif 'skysql.com' in DB_HOST.lower():
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

    had_errors = False
    planned_tables = {}

    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        # Get all migration files in order
        migration_files = sorted(glob.glob('migrations/*.sql'))
        
        for file_path in migration_files:
            mode_label = "Preflighting" if preflight_only else "Running migration"
            print(f"{mode_label}: {file_path}")
            with open(file_path, 'r') as f:
                sql_content = f.read()
            
            statements = _split_sql_statements(sql_content)
            
            for stmt in statements:
                try:
                    table_name, column_types, _ = _parse_create_table_statement(stmt)
                    if table_name:
                        planned_tables[table_name] = column_types
                    _preflight_fee_payment_reference_uniqueness(cursor, file_path)
                    _preflight_cashier_session_open_uniqueness(cursor, file_path)
                    _preflight_foreign_keys(cursor, file_path, stmt, DB_NAME, planned_tables)
                    if preflight_only:
                        continue
                    cursor.execute(stmt)
                    # print(f"  OK: {stmt[:50]}...")
                except RuntimeError as e:
                    print(f"  PRECHECK FAILED in {file_path}: {e}")
                    connection.close()
                    return False
                except (pymysql.err.InternalError, pymysql.err.OperationalError) as e:
                    if _is_ignorable_migration_error(e):
                        # print(f"  Skipped (already applied): {e.args[1]}")
                        pass
                    else:
                        print(f"  ERROR in {file_path}: {e}")
                        had_errors = True
                except Exception as e:
                    print(f"  CRITICAL ERROR in {file_path}: {e}")
                    had_errors = True

    connection.close()
    if preflight_only:
        print("Migration preflight completed.")
    else:
        print("Migration process completed.")
    return not had_errors


def parse_args():
    parser = argparse.ArgumentParser(description="Run or preflight SQL migrations against the configured database.")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Inspect foreign-key compatibility without executing any migration statements.",
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    success = run_migrations(preflight_only=args.preflight_only)
    sys.exit(0 if success else 1)
