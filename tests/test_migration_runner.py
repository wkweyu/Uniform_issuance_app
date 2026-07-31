import io

import pymysql
import pytest

import migrate_db


class FailingCursor:
    def __init__(self):
        self.executed = []

    def execute(self, statement):
        self.executed.append(statement)
        raise pymysql.err.OperationalError(1064, 'synthetic migration syntax error')


class FailingConnection:
    def __init__(self):
        self.cursor_obj = FailingCursor()
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self.cursor_obj

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def close(self):
        self.closed = True


def _configure_failing_migration(monkeypatch):
    connection = FailingConnection()
    monkeypatch.setattr(migrate_db.pymysql, 'connect', lambda **_kwargs: connection)
    monkeypatch.setattr(migrate_db.os.path, 'exists', lambda _path: False)
    monkeypatch.setattr(migrate_db.glob, 'glob', lambda _pattern: ['migrations/999_broken.sql'])
    monkeypatch.setattr('builtins.open', lambda *_args, **_kwargs: io.StringIO('BROKEN SQL;'))
    return connection


def test_migration_runner_fails_closed_on_unexpected_statement_error(monkeypatch):
    connection = _configure_failing_migration(monkeypatch)

    with pytest.raises(migrate_db.MigrationError, match='Migration failed'):
        migrate_db.migrate_db()

    assert connection.cursor_obj.executed == ['BROKEN SQL']
    assert connection.closed is True


def test_migration_runner_diagnostic_mode_still_exits_failed(monkeypatch):
    connection = _configure_failing_migration(monkeypatch)

    with pytest.raises(migrate_db.MigrationError, match='1 migration statement'):
        migrate_db.migrate_db(continue_on_error=True)

    assert connection.cursor_obj.executed == ['BROKEN SQL']
    assert connection.closed is True
