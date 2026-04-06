from datetime import date

import pytest

from blueprints.attendance.services import AttendanceService


class RecordingCursor:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.executed = []
        self.lastrowid = 0

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if not self.responses:
            return None
        response_type, value = self.responses.pop(0)
        if response_type != 'one':
            raise AssertionError(f'Expected fetchone response, got {response_type}')
        return value

    def fetchall(self):
        if not self.responses:
            return []
        response_type, value = self.responses.pop(0)
        if response_type != 'all':
            raise AssertionError(f'Expected fetchall response, got {response_type}')
        return value


class RecordingConnection:
    def __init__(self, responses=None):
        self.cursor_obj = RecordingCursor(responses=responses)
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def cursor(self, *_args, **_kwargs):
        return self.cursor_obj

    def begin(self):
        self.begin_calls += 1

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


def test_attendance_register_query_is_school_scoped():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 5, 'display_name': 'Grade 4 A'}),
            ('all', [{'student_id': 1001, 'full_name': 'Jane Doe', 'status': 'present', 'remarks': ''}]),
        ]
    )
    service = AttendanceService(connection, school_id=44)

    rows = service.get_class_attendance_register(5, '2026-04-03')

    assert rows == [{'student_id': 1001, 'full_name': 'Jane Doe', 'status': 'present', 'remarks': ''}]
    class_query, class_params = connection.cursor_obj.executed[0]
    register_query, register_params = connection.cursor_obj.executed[1]

    assert class_params == (5, 44)
    assert 'where classid = %s and school_id = %s' in class_query.lower()
    assert register_params == ('2026-04-03', 5, 44)
    assert 'ca.school_id = s.school_id' in register_query
    assert 'ca.class_id = c.classid' in register_query.lower()
    assert 'a.school_id = s.school_id' in register_query
    assert 'left join student_attendance a' in register_query.lower()
    assert 'where ca.class_id = %s' in register_query.lower()
    assert 'and ca.school_id = %s' in register_query.lower()


def test_attendance_record_rejects_foreign_student_membership_before_transaction():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 5, 'display_name': 'Grade 4 A'}),
            ('all', [{'student_id': 1001}]),
        ]
    )
    service = AttendanceService(connection, school_id=44)

    with pytest.raises(ValueError, match='One or more students do not belong to the selected class for the active school'):
        service.record_attendance(
            5,
            '2026-04-03',
            [
                {'student_id': 1001, 'status': 'present', 'remarks': ''},
                {'student_id': 1002, 'status': 'absent', 'remarks': 'Sick'},
            ],
            9,
        )

    assert connection.begin_calls == 0
    membership_query, membership_params = connection.cursor_obj.executed[1]
    assert membership_params == [5, 44, 1001, 1002]
    assert 'from class_allocation' in membership_query.lower()
    assert 'school_id = %s' in membership_query.lower()


def test_attendance_summary_query_is_school_scoped():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 5, 'display_name': 'Grade 4 A'}),
            ('all', [{'attendance_date': date(2026, 4, 3), 'class_name': 'Grade 4 A', 'status': 'absent', 'total_students': 3}]),
        ]
    )
    service = AttendanceService(connection, school_id=44)

    rows = service.get_attendance_summary('2026-04-01', '2026-04-03', class_id=5)

    assert rows == [{'attendance_date': date(2026, 4, 3), 'class_name': 'Grade 4 A', 'status': 'absent', 'total_students': 3}]
    summary_query, summary_params = connection.cursor_obj.executed[1]
    assert summary_params == [44, '2026-04-01', '2026-04-03', 5]
    assert 'a.school_id = c.school_id' in summary_query
    assert 'from student_attendance a' in summary_query.lower()
    assert 'where a.school_id = %s' in summary_query.lower()
    assert 'and a.class_id = %s' in summary_query.lower()