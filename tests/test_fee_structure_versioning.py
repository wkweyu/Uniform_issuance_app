import pytest
from blueprints.fees.services import FeesService, FeesError
from tests.test_exam_fee_isolation import RecordingConnection

def test_clone_fee_structure_version_creates_draft_v2():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 10,
                'academic_year_id': 2026,
                'term_id': 1,
                'class_id': 5,
                'class_group_code': 'Grade 1-3',
                'student_category': 'Day',
                'version_number': 1,
                'total_amount': 15000,
                'scope_key': '2026-5-Day'
            }), # original structure check
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
    assert "insert into fee_structures" in executed[2][0].lower()
    # Ensure status is DRAFT and version_number is 2
    params = executed[2][1]
    assert params[5] == 2 # version_number = 2
    assert params[6] == 10 # parent_version_id = 10


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
