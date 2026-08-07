import sys

import run_remote_migrations as migration_runner

from run_remote_migrations import (
    _get_connection_settings,
    _preflight_cashier_session_open_uniqueness,
    _is_ignorable_migration_error,
    _normalize_column_type,
    _parse_create_table_statement,
    _preflight_fee_payment_reference_uniqueness,
    _preflight_foreign_keys,
    _split_sql_statements,
    parse_args,
)


class FakeCursor:
    def __init__(self, result):
        self.result = result
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result if isinstance(self.result, list) else []


def test_parse_create_table_statement_extracts_columns_and_foreign_keys():
    statement = """
    CREATE TABLE IF NOT EXISTS school_settings (
      `id` INT NOT NULL AUTO_INCREMENT,
      `school_id` INT NOT NULL,
      CONSTRAINT `fk_school_settings_school`
        FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci
    """

    table_name, column_types, foreign_keys = _parse_create_table_statement(statement)

    assert table_name == 'school_settings'
    assert column_types['school_id'] == 'INT'
    assert foreign_keys == [{'local': 'school_id', 'ref_table': 'schools', 'ref_column': 'id'}]


def test_preflight_foreign_keys_raises_on_type_mismatch():
    statement = """
    CREATE TABLE IF NOT EXISTS school_settings (
      `id` INT NOT NULL AUTO_INCREMENT,
      `school_id` INT UNSIGNED NOT NULL,
      CONSTRAINT `fk_school_settings_school`
        FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci
    """
    cursor = FakeCursor(
        {
            'COLUMN_TYPE': 'int(11)',
            'DATA_TYPE': 'int',
            'CHARACTER_SET_NAME': None,
            'COLLATION_NAME': None,
        }
    )

    try:
        _preflight_foreign_keys(cursor, 'migrations/test.sql', statement, 'schoolmngt')
    except RuntimeError as error:
        assert 'foreign key type mismatch' in str(error)
    else:
        raise AssertionError('Expected preflight to raise on type mismatch')


def test_preflight_foreign_keys_accepts_reference_created_earlier_in_migration_run():
    statement = """
    CREATE TABLE IF NOT EXISTS fee_allocation_template_items (
      `id` INT NOT NULL AUTO_INCREMENT,
      `template_id` INT NOT NULL,
      CONSTRAINT `fk_template`
        FOREIGN KEY (`template_id`) REFERENCES `fee_allocation_templates` (`id`)
    ) ENGINE=InnoDB
    """
    cursor = FakeCursor(None)

    _preflight_foreign_keys(
        cursor,
        'migrations/032_fee_allocation_templates.sql',
        statement,
        'schoolmngt',
        {'fee_allocation_templates': {'id': 'INT'}},
    )

    assert cursor.executed


def test_normalize_column_type_treats_integer_display_width_as_equivalent():
    assert _normalize_column_type('INT') == 'int'
    assert _normalize_column_type('int(11)') == 'int'
    assert _normalize_column_type('BIGINT(20) UNSIGNED') == 'bigint unsigned'


def test_split_sql_statements_ignores_comment_only_lines():
    sql = """
    -- comment only
    CREATE TABLE test_one (id INT);
    # another comment
    ALTER TABLE test_one ADD COLUMN school_id INT;
    """

    assert _split_sql_statements(sql) == [
        'CREATE TABLE test_one (id INT)',
        'ALTER TABLE test_one ADD COLUMN school_id INT',
    ]


def test_is_ignorable_migration_error_allows_duplicate_constraint_name():
    error = Exception(1005, 'Can\'t create table `db`.`classes` (errno: 121 "Duplicate key on write or update")')
    assert _is_ignorable_migration_error(error) is True


def test_fee_payment_reference_preflight_rejects_duplicate_tenant_references():
    cursor = FakeCursor([
        {
            'school_id': 7,
            'payment_mode': 'MPESA',
            'reference_number': 'QWE123',
            'duplicate_count': 2,
        },
    ])

    try:
        _preflight_fee_payment_reference_uniqueness(
            cursor,
            'migrations/041_tenant_scoped_fee_payment_references.sql',
        )
    except RuntimeError as error:
        assert 'duplicate fee payment references block migration 041' in str(error)
        assert 'school 7 / MPESA / QWE123 (2)' in str(error)
    else:
        raise AssertionError('Expected duplicate references to block migration 041')


def test_fee_payment_reference_preflight_ignores_other_migrations():
    cursor = FakeCursor([
        {
            'school_id': 7,
            'payment_mode': 'MPESA',
            'reference_number': 'QWE123',
            'duplicate_count': 2,
        },
    ])

    _preflight_fee_payment_reference_uniqueness(cursor, 'migrations/042_fee_receipt_repost_links.sql')

    assert cursor.executed == []


def test_cashier_session_preflight_rejects_duplicate_open_sessions():
    cursor = FakeCursor([
        {
            'school_id': 7,
            'cashier_user_id': 19,
            'duplicate_count': 2,
        },
    ])

    try:
        _preflight_cashier_session_open_uniqueness(
            cursor,
            'migrations/043_cashier_session_open_guard.sql',
            'schoolmngt',
        )
    except RuntimeError as error:
        assert 'duplicate open cashier sessions block migration 043' in str(error)
        assert 'school 7 / cashier 19 (2)' in str(error)
    else:
        raise AssertionError('Expected duplicate open sessions to block migration 043')


def test_cashier_session_preflight_skips_unapplied_table_created_by_earlier_migration():
    class MissingTableCursor(FakeCursor):
        def fetchone(self):
            return None

    cursor = MissingTableCursor([])

    _preflight_cashier_session_open_uniqueness(
        cursor,
        'migrations/043_cashier_session_open_guard.sql',
        'schoolmngt',
        {'cashier_sessions': {'id': 'INT'}},
    )

    assert len(cursor.executed) == 1


def test_parse_args_supports_preflight_only(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run_remote_migrations.py', '--preflight-only'])

    args = parse_args()

    assert args.preflight_only is True


def test_migration_runner_uses_central_config_when_db_environment_is_not_set(monkeypatch):
    for name in ('DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_PASS', 'DB_NAME'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        migration_runner.config,
        'Config',
        type('CloudConfig', (), {
            'DB_HOST': 'cloud-db.example.com',
            'DB_PORT': 3307,
            'DB_USER': 'cloud-user',
            'DB_PASSWORD': 'cloud-password',
            'DB_NAME': 'cloud-school',
            'DB_SSL_CA': 'C:/certificates/cloud-ca.pem',
        }),
    )

    assert _get_connection_settings() == {
        'host': 'cloud-db.example.com',
        'port': 3307,
        'user': 'cloud-user',
        'password': 'cloud-password',
        'database': 'cloud-school',
        'ssl_ca': 'C:/certificates/cloud-ca.pem',
    }
