import io

import pymysql
import pytest

import migrate_db


class MigrationCursor:
    def __init__(
        self,
        failing_statements=None,
        applied_migrations=None,
        checksums=None,
        database_has_tables=False,
    ):
        self.executed = []
        self.failing_statements = set(failing_statements or [])
        self.applied_migrations = set(applied_migrations or [])
        self.checksums = dict(checksums or {})
        self.database_has_tables = database_has_tables
        self._last_result = None

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if statement in self.failing_statements:
            raise pymysql.err.OperationalError(1064, 'synthetic migration syntax error')
        if 'FROM information_schema.tables' in statement:
            self._last_result = (1,) if self.database_has_tables else None
        elif 'SELECT migrations.migration_name' in statement:
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
    def __init__(
        self,
        failing_statements=None,
        applied_migrations=None,
        checksums=None,
        database_has_tables=False,
    ):
        self.cursor_obj = MigrationCursor(
            failing_statements,
            applied_migrations,
            checksums,
            database_has_tables,
        )
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self.cursor_obj

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def close(self):
        self.closed = True


class UniformPriceSchemaCursor:
    def __init__(self, *, price_item_type='int', foreign_key=None):
        self.price_item_type = price_item_type
        self.foreign_key = foreign_key
        self.executed = []
        self._result = None
        self._results = []

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        normalized = ' '.join(statement.lower().split())
        if 'from information_schema.columns' in normalized:
            if "table_name = 'uniform_prices'" in normalized:
                self._result = (
                    (self.price_item_type,)
                    if self.price_item_type is not None else None
                )
            else:
                self._result = ('int',)
        elif 'from information_schema.key_column_usage' in normalized:
            self._results = [self.foreign_key] if self.foreign_key else []
        elif normalized == 'alter table uniform_prices add column item_id int':
            self.price_item_type = 'int'
        elif 'add constraint fk_uniform_prices_item_stock' in normalized:
            self.foreign_key = ('item_stock', 'item_id')

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._results


def _configure_migration(
    monkeypatch,
    failing_statements=None,
    applied_migrations=None,
    checksums=None,
    schema_exists=False,
    database_has_tables=False,
):
    connection = MigrationConnection(
        failing_statements,
        applied_migrations,
        checksums,
        database_has_tables,
    )
    monkeypatch.setattr(migrate_db.pymysql, 'connect', lambda **_kwargs: connection)
    monkeypatch.setattr(migrate_db.os.path, 'exists', lambda _path: schema_exists)
    monkeypatch.setattr(migrate_db.glob, 'glob', lambda _pattern: ['migrations/999_broken.sql'])
    monkeypatch.setattr('builtins.open', lambda *_args, **_kwargs: io.StringIO('BROKEN SQL;'))
    return connection


def test_schema_item_reference_statement_matches_with_comment_prefix():
    statement = """
    -- Update uniform_prices to reference item_stock
    ALTER TABLE uniform_prices
    ADD COLUMN item_id INT,
    ADD FOREIGN KEY (item_id)
    REFERENCES item_stock(item_id) ON DELETE CASCADE
    """

    assert migrate_db._is_uniform_prices_item_reference_statement(statement)


def test_schema_item_reference_adds_missing_foreign_key_when_column_exists():
    cursor = UniformPriceSchemaCursor(price_item_type='int')

    migrate_db._ensure_uniform_prices_item_reference(cursor)

    statements = [statement.lower() for statement, _ in cursor.executed]
    assert not any('add column item_id' in statement for statement in statements)
    assert any(
        'add constraint fk_uniform_prices_item_stock' in statement
        for statement in statements
    )


def test_schema_item_reference_skips_existing_matching_foreign_key():
    cursor = UniformPriceSchemaCursor(
        price_item_type='int',
        foreign_key=('item_stock', 'item_id'),
    )

    migrate_db._ensure_uniform_prices_item_reference(cursor)

    assert not any(
        'alter table uniform_prices' in statement.lower()
        for statement, _ in cursor.executed
    )


def test_schema_item_reference_adds_column_and_foreign_key_when_missing():
    cursor = UniformPriceSchemaCursor(price_item_type=None)

    migrate_db._ensure_uniform_prices_item_reference(cursor)

    statements = [statement.lower() for statement, _ in cursor.executed]
    assert 'alter table uniform_prices add column item_id int' in statements
    assert any(
        'add constraint fk_uniform_prices_item_stock' in statement
        for statement in statements
    )


def test_schema_item_reference_rejects_unexpected_existing_foreign_key():
    cursor = UniformPriceSchemaCursor(
        price_item_type='int',
        foreign_key=('other_table', 'id'),
    )

    with pytest.raises(migrate_db.MigrationError, match='unexpected foreign key'):
        migrate_db._ensure_uniform_prices_item_reference(cursor)


def test_migration_connection_does_not_force_tls_without_configured_ca(monkeypatch):
    captured = {}
    monkeypatch.setenv('DB_HOST', 'mysql.internal.render')
    monkeypatch.delenv('DB_SSL_CA', raising=False)
    monkeypatch.setattr(migrate_db.config, 'DB_SSL_CA', None, raising=False)
    monkeypatch.setattr(
        migrate_db.pymysql,
        'connect',
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    migrate_db._get_database_connection()

    assert captured['ssl'] is None


def test_migration_connection_uses_configured_ca(monkeypatch):
    captured = {}
    monkeypatch.setenv('DB_HOST', 'mysql.internal.render')
    monkeypatch.setenv('DB_SSL_CA', 'C:/certificates/render-ca.pem')
    monkeypatch.setattr(
        migrate_db.os.path,
        'isfile',
        lambda path: path == 'C:/certificates/render-ca.pem',
    )
    monkeypatch.setattr(
        migrate_db.pymysql,
        'connect',
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    migrate_db._get_database_connection()

    assert captured['ssl'] == {
        'ca': 'C:/certificates/render-ca.pem',
        'check_hostname': False,
    }


def test_migration_connection_rejects_missing_configured_ca(monkeypatch):
    monkeypatch.setenv('DB_SSL_CA', 'C:/certificates/missing-ca.pem')
    monkeypatch.setattr(migrate_db.os.path, 'isfile', lambda _path: False)

    with pytest.raises(migrate_db.MigrationError, match='DB_SSL_CA'):
        migrate_db._get_database_connection()


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


def test_migration_runner_skips_schema_baseline_for_existing_database(
    monkeypatch, capsys
):
    connection = _configure_migration(
        monkeypatch,
        schema_exists=True,
        database_has_tables=True,
    )

    migrate_db.migrate_db()

    assert [
        statement for statement, _ in connection.cursor_obj.executed
        if statement == 'BROKEN SQL'
    ] == ['BROKEN SQL']
    assert connection.cursor_obj.applied_migrations == {
        'schema.sql',
        'migrations/999_broken.sql',
    }
    assert connection.cursor_obj.checksums['schema.sql'] == (
        migrate_db._calculate_checksum('BROKEN SQL;')
    )
    assert 'Existing database detected. Skipping schema.sql baseline.' in (
        capsys.readouterr().out
    )


def test_migration_runner_executes_schema_for_empty_database(monkeypatch):
    connection = _configure_migration(monkeypatch, schema_exists=True)

    migrate_db.migrate_db()

    assert [
        statement for statement, _ in connection.cursor_obj.executed
        if statement == 'BROKEN SQL'
    ] == ['BROKEN SQL', 'BROKEN SQL']
    assert connection.cursor_obj.checksums['schema.sql'] == (
        migrate_db._calculate_checksum('BROKEN SQL;')
    )


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
