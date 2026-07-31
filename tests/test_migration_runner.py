import io

import pymysql
import pytest

import migrate_db


class MigrationCursor:
    def __init__(self, failing_statements=None, applied_migrations=None, checksums=None):
        self.executed = []
        self.failing_statements = set(failing_statements or [])
        self.applied_migrations = set(applied_migrations or [])
        self.checksums = dict(checksums or {})
        self._last_result = None

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if statement in self.failing_statements:
            raise pymysql.err.OperationalError(1064, 'synthetic migration syntax error')
        if 'SELECT migrations.migration_name' in statement:
            migration_name = params[0]
            self._last_result = (
                {
                    'migration_name': migration_name,
                    'checksum': self.checksums.get(migration_name),
                }
                if migration_name in self.applied_migrations
                else None
            )
        elif statement.startswith('INSERT INTO schema_migrations'):
            self.applied_migrations.add(params[0])
        elif statement.startswith('INSERT INTO schema_migration_checksums'):
            self.checksums[params[0]] = params[1]

    def fetchone(self):
        return self._last_result


class MigrationConnection:
    def __init__(self, failing_statements=None, applied_migrations=None, checksums=None):
        self.cursor_obj = MigrationCursor(failing_statements, applied_migrations, checksums)
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self.cursor_obj

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def close(self):
        self.closed = True


def _configure_migration(
    monkeypatch,
    failing_statements=None,
    applied_migrations=None,
    checksums=None,
    schema_exists=False,
):
    connection = MigrationConnection(failing_statements, applied_migrations, checksums)
    monkeypatch.setattr(migrate_db.pymysql, 'connect', lambda **_kwargs: connection)
    monkeypatch.setattr(migrate_db.os.path, 'exists', lambda _path: schema_exists)
    monkeypatch.setattr(migrate_db.glob, 'glob', lambda _pattern: ['migrations/999_broken.sql'])
    monkeypatch.setattr('builtins.open', lambda *_args, **_kwargs: io.StringIO('BROKEN SQL;'))
    return connection


def test_migration_runner_fails_closed_on_unexpected_statement_error(monkeypatch):
    connection = _configure_migration(monkeypatch, failing_statements={'BROKEN SQL'})

    with pytest.raises(migrate_db.MigrationError, match='Migration failed'):
        migrate_db.migrate_db()

    assert ('BROKEN SQL', None) in connection.cursor_obj.executed
    assert 'migrations/999_broken.sql' not in connection.cursor_obj.applied_migrations
    assert connection.closed is True


def test_migration_runner_diagnostic_mode_still_exits_failed(monkeypatch):
    connection = _configure_migration(monkeypatch, failing_statements={'BROKEN SQL'})

    with pytest.raises(migrate_db.MigrationError, match='1 migration statement'):
        migrate_db.migrate_db(continue_on_error=True)

    assert ('BROKEN SQL', None) in connection.cursor_obj.executed
    assert 'migrations/999_broken.sql' not in connection.cursor_obj.applied_migrations
    assert connection.closed is True


def test_migration_runner_records_successful_migration(monkeypatch):
    connection = _configure_migration(monkeypatch)

    migrate_db.migrate_db()

    assert ('BROKEN SQL', None) in connection.cursor_obj.executed
    assert connection.cursor_obj.applied_migrations == {'migrations/999_broken.sql'}


def test_migration_runner_skips_previously_applied_migration(monkeypatch):
    connection = _configure_migration(
        monkeypatch,
        applied_migrations={'migrations/999_broken.sql'},
        checksums={
            'migrations/999_broken.sql': migrate_db._calculate_checksum('BROKEN SQL;'),
        },
    )

    migrate_db.migrate_db()

    assert ('BROKEN SQL', None) not in connection.cursor_obj.executed
    assert connection.cursor_obj.applied_migrations == {'migrations/999_broken.sql'}


def test_migration_runner_records_and_skips_successful_schema(monkeypatch):
    connection = _configure_migration(monkeypatch, schema_exists=True)

    migrate_db.migrate_db()

    assert connection.cursor_obj.applied_migrations == {
        'schema.sql',
        'migrations/999_broken.sql',
    }

    executed_count = len(connection.cursor_obj.executed)
    migrate_db.migrate_db()

    assert len(connection.cursor_obj.executed) == executed_count + 4


def test_migration_status_lists_applied_and_pending_files(monkeypatch):
    connection = _configure_migration(
        monkeypatch,
        applied_migrations={'schema.sql'},
        checksums={'schema.sql': migrate_db._calculate_checksum('BROKEN SQL;')},
        schema_exists=True,
    )

    status = migrate_db.get_migration_status()

    assert status == [
        {'migration_name': 'schema.sql', 'state': 'APPLIED'},
        {'migration_name': 'migrations/999_broken.sql', 'state': 'PENDING'},
    ]
    assert ('BROKEN SQL', None) not in connection.cursor_obj.executed
    assert connection.closed is True


def test_migration_runner_rejects_changed_applied_migration(monkeypatch):
    connection = _configure_migration(
        monkeypatch,
        applied_migrations={'migrations/999_broken.sql'},
        checksums={'migrations/999_broken.sql': '0' * 64},
    )

    with pytest.raises(migrate_db.MigrationError, match='checksum differs'):
        migrate_db.migrate_db()

    assert ('BROKEN SQL', None) not in connection.cursor_obj.executed


def test_migration_status_marks_legacy_entry_as_unverified(monkeypatch):
    _configure_migration(
        monkeypatch,
        applied_migrations={'migrations/999_broken.sql'},
    )

    status = migrate_db.get_migration_status()

    assert status == [
        {'migration_name': 'migrations/999_broken.sql', 'state': 'UNVERIFIED'},
    ]


def test_migration_checksum_backfill_updates_only_legacy_applied_entries(monkeypatch):
    connection = _configure_migration(
        monkeypatch,
        applied_migrations={'migrations/999_broken.sql'},
    )

    backfilled_migrations = migrate_db.backfill_migration_checksums()

    assert backfilled_migrations == ['migrations/999_broken.sql']
    assert connection.cursor_obj.checksums == {
        'migrations/999_broken.sql': migrate_db._calculate_checksum('BROKEN SQL;'),
    }
    assert migrate_db.get_migration_status() == [
        {'migration_name': 'migrations/999_broken.sql', 'state': 'APPLIED'},
    ]
