import pytest

from blueprints.exams.services import ExamManagementError
from blueprints.exams.services import ExamManagementService
from blueprints.fees.services import FeesService


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
        self.commit_calls = 0
        self.rollback_calls = 0
        self.begin_calls = 0

    def cursor(self, *_args, **_kwargs):
        return self.cursor_obj

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def begin(self):
        self.begin_calls += 1


def test_exam_service_scopes_grading_scale_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'id': 10, 'name': 'Tenant A Scale'}]),
            ('all', [{'id': 20, 'grade': 'A'}]),
        ]
    )
    service = ExamManagementService(connection, school_id=7)

    scales = service.get_all_grading_scales()
    details = service.get_grading_details(10)

    assert scales == [{'id': 10, 'name': 'Tenant A Scale'}]
    assert details == [{'id': 20, 'grade': 'A'}]
    assert connection.cursor_obj.executed[0][1] == (7,)
    assert 'where school_id = %s' in connection.cursor_obj.executed[0][0].lower()
    assert connection.cursor_obj.executed[1][1] == (10, 7)
    assert 'where scale_id = %s and school_id = %s' in connection.cursor_obj.executed[1][0].lower()


def test_exam_service_scopes_exam_series_and_class_queries_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 4, 'name': 'Midterm', 'academic_year_name': '2026', 'is_current': 1}),
            ('all', [{'classID': 3, 'display_name': 'Grade 4 A'}]),
        ]
    )
    service = ExamManagementService(connection, school_id=11)

    exam = service.get_exam_series(4)

    assert exam['id'] == 4
    assert exam['classes'] == [{'classID': 3, 'display_name': 'Grade 4 A'}]

    first_query, first_params = connection.cursor_obj.executed[0]
    second_query, second_params = connection.cursor_obj.executed[1]

    assert first_params == (4, 11)
    assert 'e.school_id = ay.school_id' in first_query
    assert 'where e.id = %s and e.school_id = %s' in first_query.lower()

    assert second_params == (4, 11)
    assert 'c.school_id = ec.school_id' in second_query
    assert 'where ec.exam_id = %s and ec.school_id = %s' in second_query.lower()


def test_exam_service_scopes_all_exams_list_to_school():
    connection = RecordingConnection(
        responses=[('all', [{'id': 4, 'name': 'Midterm', 'academic_year_name': 2026, 'class_count': 2}])]
    )
    service = ExamManagementService(connection, school_id=11)

    exams = service.get_all_exams()

    assert exams == [{'id': 4, 'name': 'Midterm', 'academic_year_name': 2026, 'class_count': 2}]
    query, params = connection.cursor_obj.executed[0]
    assert params == (11,)
    assert 'e.school_id = ay.school_id' in query
    assert 'where ec.exam_id = e.id and ec.school_id = e.school_id' in query.lower()
    assert 'where e.school_id = %s' in query.lower()


def test_exam_service_scopes_exam_class_list_to_school():
    connection = RecordingConnection(
        responses=[('all', [{'classID': 5, 'display_name': 'Grade 6 Blue'}])]
    )
    service = ExamManagementService(connection, school_id=13)

    classes = service.get_exam_classes(9)

    assert classes == [{'classID': 5, 'display_name': 'Grade 6 Blue'}]
    query, params = connection.cursor_obj.executed[0]
    assert params == (9, 13)
    assert 'c.school_id = ec.school_id' in query
    assert 'where ec.exam_id = %s and ec.school_id = %s' in query.lower()


def test_exam_service_rejects_marks_lookup_for_foreign_exam_before_mark_query():
    connection = RecordingConnection(
        responses=[('one', None)]
    )
    service = ExamManagementService(connection, school_id=13)

    with pytest.raises(ExamManagementError, match='Exam series not found for the active school'):
        service.get_marks_for_class_subject(exam_id=9, class_id=5, subject_id=2)

    assert len(connection.cursor_obj.executed) == 1
    query, params = connection.cursor_obj.executed[0]
    assert params == (9, 13)
    assert 'select id from exam_series where id = %s and school_id = %s' in query.lower()


def test_fees_service_scopes_voteheads_query_and_group_join_to_school():
    connection = RecordingConnection(
        responses=[('all', [{'id': 1, 'name': 'Tuition', 'group_name': 'Boarders'}])]
    )
    service = FeesService(connection, school_id=21)

    voteheads = service.get_voteheads(group_id=8)

    assert voteheads == [{'id': 1, 'name': 'Tuition', 'group_name': 'Boarders'}]
    query, params = connection.cursor_obj.executed[0]
    assert params == (21, 8)
    assert 'v.applicable_student_group_id = g.id and v.school_id = g.school_id' in query.lower()
    assert 'v.school_id = %s' in query


def test_fees_service_scopes_recent_payments_and_receipts_register_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'id': 1, 'receipt_no': 'RCP-2026-00001'}]),
            ('all', [{'id': 2, 'receipt_no': 'RCP-2026-00002'}]),
        ]
    )
    service = FeesService(connection, school_id=31)
    service._table_columns_cache = {
        'fee_payments': {'school_id'},
        'fee_receipts': {'school_id'},
    }

    recent = service.get_recent_payments(1001, limit=3)
    register = service.get_receipts_register(start_date='2026-01-01', end_date='2026-12-31', admno=1001, mode='MPESA')

    assert recent == [{'id': 1, 'receipt_no': 'RCP-2026-00001'}]
    assert register == [{'id': 2, 'receipt_no': 'RCP-2026-00002'}]

    recent_query, recent_params = connection.cursor_obj.executed[0]
    register_query, register_params = connection.cursor_obj.executed[1]

    assert recent_params == (1001, 31, 3)
    assert 'fp.school_id = %s' in recent_query
    assert 'fp.id = fr.payment_id and fp.school_id = fr.school_id' in recent_query.lower()

    assert register_params == [31, '2026-01-01', '2026-12-31', 1001, 'MPESA']
    assert 'where fp.school_id = %s' in register_query.lower()
    assert 'fp.id = fr.payment_id and fp.school_id = fr.school_id' in register_query.lower()
    assert 'fp.admno = si.admno and fp.school_id = si.school_id' in register_query.lower()


def test_fees_service_scopes_student_balance_to_school():
    connection = RecordingConnection(
        responses=[('one', {'balance_after': '1250.50'})]
    )
    service = FeesService(connection, school_id=44)

    balance = service.get_student_balance(2002)

    assert str(balance) == '1250.50'
    query, params = connection.cursor_obj.executed[0]
    assert params == (2002, 44)
    assert 'where admno = %s and school_id = %s' in query.lower()