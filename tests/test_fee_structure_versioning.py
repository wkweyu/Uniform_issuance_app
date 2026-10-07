import pytest
import pymysql
from blueprints.fees.services import FeesService, FeesError
from tests.test_exam_fee_isolation import RecordingConnection

def test_table_has_column_handles_missing_table_exception():
    class ExceptionRaisingCursor:
        def __init__(self):
            self.executed = []

        def execute(self, query, params=None):
            self.executed.append((query, params))
            raise pymysql.err.ProgrammingError(1146, "Table 'test_db.missing_table' doesn't exist")

        def fetchall(self):
            return []

    class CustomConnection:
        def cursor(self, *_args, **_kwargs):
            return ExceptionRaisingCursor()

    service = FeesService(CustomConnection(), school_id=10)
    assert service._table_has_column('missing_table', 'some_column') is False


def test_clone_fee_structure_version_creates_draft_v2():
    parent_struct = {
        'id': 10,
        'academic_year_id': 2026,
        'term_id': 1,
        'class_id': 5,
        'class_group_code': 'Grade 1-3',
        'student_category': 'Day',
        'version_number': 1,
        'total_amount': 15000,
        'scope_key': '2026-5-Day'
    }
    connection = RecordingConnection(
        responses=[
            ('one', parent_struct), # original structure check
            ('all', [parent_struct]), # sibling terms check
            ('one', {'max_v': 1}), # max version number check
            ('all', [
                {'votehead_id': 1, 'amount': 10000},
                {'votehead_id': 2, 'amount': 5000}
            ]), # items check
            ('one', None), # insert cloned structure
            ('one', None), # insert item 1
            ('one', None)  # insert item 2
        ]
    )
    service = FeesService(connection, school_id=10)

    cloned_id = service.clone_fee_structure_version(10, user_id=1)

    assert cloned_id is not None
    executed = connection.cursor_obj.executed
    # executed[3] is the insert query into fee_structures
    assert "insert into fee_structures" in executed[4][0].lower()
    # Ensure status is DRAFT and version_number is 2
    params = executed[4][1]
    assert params[5] == 2 # version_number = 2
    assert params[6] == 10 # parent_version_id = 10


def test_approve_fee_structure_version():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 10,
                'status': 'DRAFT',
                'approval_status': 'PENDING',
                'school_id': 10
            }), # struct check
            ('one', None) # update query
        ]
    )
    service = FeesService(connection, school_id=10)

    res = service.approve_fee_structure_version(10, user_id=1)

    assert res is True
    executed = connection.cursor_obj.executed
    assert "approval_status = 'approved'" in executed[1][0].lower()


def test_approve_fee_structure_version_rejects_non_draft():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 10,
                'status': 'ACTIVE',
                'approval_status': 'APPROVED',
                'school_id': 10
            })
        ]
    )
    service = FeesService(connection, school_id=10)

    with pytest.raises(FeesError, match="Only DRAFT fee structure versions can be approved"):
        service.approve_fee_structure_version(10, user_id=1)


def test_activate_fee_structure_version_archives_previous_active_version():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 11,
                'academic_year_id': 2026,
                'term_id': 1,
                'class_id': 5,
                'class_group_code': 'Grade 1-3',
                'student_category': 'Day',
                'version_number': 2,
                'status': 'DRAFT',
                'approval_status': 'APPROVED',
                'scope_key': '2026-5-Day'
            }), # target structure check
            ('one', None), # archive previous active
            ('one', None)  # activate new version
        ]
    )
    service = FeesService(connection, school_id=10)

    res = service.activate_fee_structure_version(11, user_id=1)

    assert res is True
    executed = connection.cursor_obj.executed
    assert "status = 'archived'" in executed[1][0].lower()
    assert "status = 'active'" in executed[2][0].lower()


def test_activate_fee_structure_version_rejects_unapproved():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 11,
                'academic_year_id': 2026,
                'term_id': 1,
                'class_id': 5,
                'class_group_code': 'Grade 1-3',
                'student_category': 'Day',
                'version_number': 2,
                'status': 'DRAFT',
                'approval_status': 'PENDING',
                'scope_key': '2026-5-Day'
            })
        ]
    )
    service = FeesService(connection, school_id=10)

    with pytest.raises(FeesError, match="must be APPROVED before activation"):
        service.activate_fee_structure_version(11, user_id=1)


def test_archive_fee_structure():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 10}), # check belongs to school
            ('all', [{'Field': 'id'}, {'Field': 'status'}, {'Field': 'school_id'}]), # SHOW COLUMNS FROM fee_structures
            ('one', None) # update query
        ]
    )
    service = FeesService(connection, school_id=10)

    res = service.archive_fee_structure(10)

    assert res is True
    executed = connection.cursor_obj.executed
    assert "status = 'archived'" in executed[2][0].lower()


def test_get_fee_structure_dashboard_metrics_with_status_column():
    connection = RecordingConnection(
        responses=[
            ('one', {'total': 5}), # total_classes query
            ('all', [{'Field': 'id'}, {'Field': 'status'}, {'Field': 'school_id'}]), # SHOW COLUMNS FROM fee_structures
            ('one', {'active_count': 3, 'draft_count': 1, 'archived_count': 1}), # status_row
            ('one', {'configured': 3}) # configured_classes
        ]
    )
    service = FeesService(connection, school_id=10)

    metrics = service.get_fee_structure_dashboard_metrics(year_id=2026)

    assert metrics['total_classes'] == 5
    assert metrics['configured_classes'] == 3
    assert metrics['missing_classes_count'] == 2
    assert metrics['active_structures'] == 3
    assert metrics['draft_structures'] == 1
    assert metrics['archived_structures'] == 1


def test_get_fee_structure_dashboard_metrics_fallback_without_status_column():
    connection = RecordingConnection(
        responses=[
            ('one', {'total': 5}), # total_classes query
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]), # SHOW COLUMNS FROM fee_structures (NO status column)
            ('one', {'total_count': 4, 'configured': 3}) # fallback query
        ]
    )
    service = FeesService(connection, school_id=10)

    metrics = service.get_fee_structure_dashboard_metrics(year_id=2026)

    assert metrics['total_classes'] == 5
    assert metrics['configured_classes'] == 3
    assert metrics['missing_classes_count'] == 2
    assert metrics['active_structures'] == 4
    assert metrics['draft_structures'] == 0
    assert metrics['archived_structures'] == 0


def test_get_missing_fee_structures_fallback_without_status_column():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]), # SHOW COLUMNS FROM fee_structures
            ('all', [{'classID': 2, 'display_name': 'Class 2', 'class_group_code': 'G1', 'stream_code': 'A'}]) # missing classes query
        ]
    )
    service = FeesService(connection, school_id=10)

    missing = service.get_missing_fee_structures(year_id=2026)

    assert len(missing) == 1
    assert missing[0]['classID'] == 2
    executed = connection.cursor_obj.executed
    # Verify fallback query doesn't filter on status = 'ACTIVE'
    assert "status = 'active'" not in executed[1][0].lower()
