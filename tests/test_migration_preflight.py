import sys

from run_remote_migrations import (
    _is_ignorable_migration_error,
    _normalize_column_type,
    _parse_create_table_statement,
    _preflight_foreign_keys,
    _split_sql_statements,
    parse_args,
)


class FakeCursor:
    def __init__(self, result):
        self.result = result
        self.executed = []

    def execute(self, query, params):
        self.executed.append((query, params))

    def fetchone(self):
        return self.result


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


def test_parse_args_supports_preflight_only(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run_remote_migrations.py', '--preflight-only'])

    args = parse_args()

    assert args.preflight_only is True
