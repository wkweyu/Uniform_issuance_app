import pymysql
import os
import glob
import argparse
import config


class MigrationError(RuntimeError):
    """Raised when one or more database migration statements fail."""


SCHEMA_MIGRATION_NAME = 'schema.sql'


def _ensure_migration_journal(cursor):
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_name VARCHAR(255) NOT NULL PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )


def _migration_is_applied(cursor, migration_name):
    cursor.execute(
        'SELECT migration_name FROM schema_migrations WHERE migration_name = %s',
        (migration_name,),
    )
    return cursor.fetchone() is not None


def _record_migration(cursor, migration_name):
    cursor.execute(
        'INSERT INTO schema_migrations (migration_name) VALUES (%s)',
        (migration_name,),
    )


def _get_database_connection():
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

    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
        ssl=ssl_config,
        autocommit=True
    )


def get_migration_status():
    connection = _get_database_connection()
    try:
        with connection.cursor() as cursor:
            _ensure_migration_journal(cursor)
            migration_names = [SCHEMA_MIGRATION_NAME]
            migration_names.extend(sorted(glob.glob('migrations/*.sql')))

            status = []
            for migration_name in migration_names:
                status.append({
                    'migration_name': migration_name,
                    'is_applied': _migration_is_applied(cursor, migration_name),
                })
            return status
    finally:
        connection.close()


def migrate_db(continue_on_error=False):
    connection = _get_database_connection()
    try:
        with connection.cursor() as cursor:
            errors = []
            _ensure_migration_journal(cursor)

            # First run schema.sql if it's new
            if os.path.exists(SCHEMA_MIGRATION_NAME) and not _migration_is_applied(cursor, SCHEMA_MIGRATION_NAME):
                print("Running schema.sql...")
                try:
                    with open(SCHEMA_MIGRATION_NAME, 'r') as f:
                        sql_script = f.read()
                    for statement in sql_script.split(';'):
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)
                    print("✔️ schema.sql completed.")
                    _record_migration(cursor, SCHEMA_MIGRATION_NAME)
                except Exception as exc:
                    errors.append((SCHEMA_MIGRATION_NAME, str(exc)))
                    print(f"❌ schema.sql failed: {exc}")
                    if not continue_on_error:
                        raise MigrationError('schema.sql failed') from exc
            elif os.path.exists(SCHEMA_MIGRATION_NAME):
                print("Skipping applied schema.sql")

            # Now run all migrations in order
            migration_files = sorted(glob.glob('migrations/*.sql'))
            for mig_file in migration_files:
                if _migration_is_applied(cursor, mig_file):
                    print(f"Skipping applied migration: {mig_file}")
                    continue

                print(f"Running migration: {mig_file}...")
                with open(mig_file, 'r') as f:
                    sql_script = f.read()

                # Split statements and execute one by one
                statements = sql_script.split(';')
                migration_failed = False
                for statement in statements:
                    statement = statement.strip()
                    if not statement:
                        continue

                    try:
                        cursor.execute(statement)
                        # print(f"  ✔️ Executed statement.")
                    except pymysql.err.InternalError as exc:
                        if 'Duplicate column name' in str(exc) or 'already exists' in str(exc) or 'Duplicate key name' in str(exc) or 'Duplicate entry' in str(exc):
                            # print(f"  ⏭️ Skipping statement (already applied).")
                            pass
                        else:
                            migration_failed = True
                            errors.append((mig_file, str(exc)))
                            print(f"  ❌ Error in statement: {exc}")
                            if not continue_on_error:
                                raise MigrationError(f'Migration failed: {mig_file}') from exc
                    except pymysql.err.OperationalError as exc:
                        if 'Duplicate column name' in str(exc) or 'already exists' in str(exc) or 'Duplicate key name' in str(exc):
                             # print(f"  ⏭️ Skipping statement (already applied).")
                             pass
                        else:
                            migration_failed = True
                            errors.append((mig_file, str(exc)))
                            print(f"  ❌ Error in statement: {exc}")
                            if not continue_on_error:
                                raise MigrationError(f'Migration failed: {mig_file}') from exc
                    except Exception as exc:
                        migration_failed = True
                        errors.append((mig_file, str(exc)))
                        print(f"  ❌ Unexpected error in statement: {exc}")
                        if not continue_on_error:
                            raise MigrationError(f'Migration failed: {mig_file}') from exc

                if migration_failed:
                    print(f"❌ Migration was not recorded: {mig_file}")
                else:
                    print(f"✔️ Finished processing {mig_file}")
                    _record_migration(cursor, mig_file)

        if errors:
            raise MigrationError(f'{len(errors)} migration statement(s) failed.')
        print("\n✅ All database migrations completed.")
    finally:
        connection.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run ordered database migrations.')
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        '--continue-on-error', action='store_true',
        help='Process all migrations for diagnostics, then exit with failure if any statement failed.',
    )
    action_group.add_argument(
        '--status', action='store_true',
        help='List applied and pending schema files without executing migrations.',
    )
    args = parser.parse_args()
    if args.status:
        for migration in get_migration_status():
            state = 'APPLIED' if migration['is_applied'] else 'PENDING'
            print(f"{state:7} {migration['migration_name']}")
    else:
        migrate_db(continue_on_error=args.continue_on_error)
