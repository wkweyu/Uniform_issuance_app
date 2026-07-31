import pymysql
import os
import glob
import argparse
import hashlib
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
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS schema_migration_checksums (
            migration_name VARCHAR(255) NOT NULL PRIMARY KEY,
            checksum CHAR(64) NOT NULL,
            recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (migration_name) REFERENCES schema_migrations(migration_name)
        )
        '''
    )


def _migration_is_applied(cursor, migration_name):
    return _get_applied_migration(cursor, migration_name) is not None


def _get_applied_migration(cursor, migration_name):
    cursor.execute(
        '''
        SELECT migrations.migration_name, checksums.checksum
        FROM schema_migrations AS migrations
        LEFT JOIN schema_migration_checksums AS checksums
          ON checksums.migration_name = migrations.migration_name
        WHERE migrations.migration_name = %s
        ''',
        (migration_name,),
    )
    return cursor.fetchone()


def _record_migration(cursor, migration_name, sql_script):
    cursor.execute(
        'INSERT INTO schema_migrations (migration_name) VALUES (%s)',
        (migration_name,),
    )
    cursor.execute(
        'INSERT INTO schema_migration_checksums (migration_name, checksum) VALUES (%s, %s)',
        (migration_name, _calculate_checksum(sql_script)),
    )


def _calculate_checksum(sql_script):
    return hashlib.sha256(sql_script.encode('utf-8')).hexdigest()


def _get_migration_files():
    migration_files = []
    if os.path.exists(SCHEMA_MIGRATION_NAME):
        migration_files.append(SCHEMA_MIGRATION_NAME)
    migration_files.extend(sorted(glob.glob('migrations/*.sql')))
    return migration_files


def _require_matching_checksum(cursor, migration_name, sql_script):
    applied_migration = _get_applied_migration(cursor, migration_name)
    if applied_migration is None:
        return False
    if not applied_migration.get('checksum'):
        raise MigrationError(
            f'Applied migration has no checksum and cannot be verified: {migration_name}'
        )
    if applied_migration['checksum'] != _calculate_checksum(sql_script):
        raise MigrationError(f'Applied migration checksum differs from the current file: {migration_name}')
    return True


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
            status = []
            for migration_name in _get_migration_files():
                with open(migration_name, 'r') as migration_file:
                    sql_script = migration_file.read()
                applied_migration = _get_applied_migration(cursor, migration_name)
                if applied_migration is None:
                    state = 'PENDING'
                elif not applied_migration.get('checksum'):
                    state = 'UNVERIFIED'
                elif applied_migration['checksum'] != _calculate_checksum(sql_script):
                    state = 'DRIFTED'
                else:
                    state = 'APPLIED'
                status.append({
                    'migration_name': migration_name,
                    'state': state,
                })
            return status
    finally:
        connection.close()


def backfill_migration_checksums():
    connection = _get_database_connection()
    try:
        with connection.cursor() as cursor:
            _ensure_migration_journal(cursor)
            backfilled_migrations = []
            for migration_name in _get_migration_files():
                with open(migration_name, 'r') as migration_file:
                    sql_script = migration_file.read()
                applied_migration = _get_applied_migration(cursor, migration_name)
                if applied_migration is None or applied_migration.get('checksum'):
                    continue
                cursor.execute(
                    'INSERT INTO schema_migration_checksums (migration_name, checksum) VALUES (%s, %s)',
                    (migration_name, _calculate_checksum(sql_script)),
                )
                backfilled_migrations.append(migration_name)
            return backfilled_migrations
    finally:
        connection.close()


def migrate_db(continue_on_error=False):
    connection = _get_database_connection()
    try:
        with connection.cursor() as cursor:
            errors = []
            _ensure_migration_journal(cursor)

            # First run schema.sql if it's new
            if os.path.exists(SCHEMA_MIGRATION_NAME):
                with open(SCHEMA_MIGRATION_NAME, 'r') as schema_file:
                    schema_script = schema_file.read()
                schema_is_applied = _require_matching_checksum(
                    cursor,
                    SCHEMA_MIGRATION_NAME,
                    schema_script,
                )
            else:
                schema_is_applied = False

            if os.path.exists(SCHEMA_MIGRATION_NAME) and not schema_is_applied:
                print("Running schema.sql...")
                try:
                    for statement in schema_script.split(';'):
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)
                    print("✔️ schema.sql completed.")
                    _record_migration(cursor, SCHEMA_MIGRATION_NAME, schema_script)
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
                with open(mig_file, 'r') as f:
                    sql_script = f.read()
                if _require_matching_checksum(cursor, mig_file, sql_script):
                    print(f"Skipping applied migration: {mig_file}")
                    continue

                print(f"Running migration: {mig_file}...")

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
                    _record_migration(cursor, mig_file, sql_script)

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
    action_group.add_argument(
        '--backfill-checksums', action='store_true',
        help='Record current checksums for legacy applied journal entries without executing migrations.',
    )
    args = parser.parse_args()
    if args.status:
        for migration in get_migration_status():
            print(f"{migration['state']:10} {migration['migration_name']}")
    elif args.backfill_checksums:
        for migration_name in backfill_migration_checksums():
            print(f"BACKFILLED {migration_name}")
    else:
        migrate_db(continue_on_error=args.continue_on_error)
