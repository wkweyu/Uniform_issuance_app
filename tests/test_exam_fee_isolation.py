from datetime import datetime

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


def test_exam_service_rejects_exam_creation_without_participating_classes():
    connection = RecordingConnection(responses=[('one', {'id': 2026})])
    service = ExamManagementService(connection, school_id=13)

    with pytest.raises(ExamManagementError, match='Select at least one participating class'):
        service.create_exam_series('Midterm', 2026, 2, 9, [])

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    assert all('insert into exam_series' not in query.lower() for query, _ in connection.cursor_obj.executed)


def test_exam_service_rejects_classes_outside_exam_academic_year():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 2026}),
            ('all', []),
        ]
    )
    service = ExamManagementService(connection, school_id=13)

    with pytest.raises(ExamManagementError, match='active classes for the exam'):
        service.create_exam_series('Midterm', 2026, 2, 9, [4])

    query, params = connection.cursor_obj.executed[1]
    assert params == (4, 13, 2026)
    assert 'academic_year_id = %s' in query
    assert 'is_active = true' in query.lower()
    assert connection.rollback_calls == 1


def test_exam_service_disallows_editing_locked_exam():
    connection = RecordingConnection(
        responses=[('one', {'id': 4, 'academic_year_id': 2026, 'is_locked': 1})]
    )
    service = ExamManagementService(connection, school_id=13)

    with pytest.raises(ExamManagementError, match='Unlock the exam series'):
        service.update_exam_series(4, 'Updated Midterm', [8])

    assert connection.rollback_calls == 1
    assert len(connection.cursor_obj.executed) == 1


def test_exam_service_prevents_removing_a_class_with_recorded_marks():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 4, 'academic_year_id': 2026, 'is_locked': 0}),
            ('all', [{'classID': 9}]),
            ('all', [{'class_id': 8}]),
            ('one', {'class_id': 8, 'display_name': 'Grade 7 A'}),
        ]
    )
    service = ExamManagementService(connection, school_id=13)

    with pytest.raises(ExamManagementError, match='Cannot remove Grade 7 A'):
        service.update_exam_series(4, 'Updated Midterm', [9])

    assert connection.rollback_calls == 1
    assert all('update exam_series set name' not in query.lower() for query, _ in connection.cursor_obj.executed)


def test_exam_service_allows_adding_class_to_exam_with_existing_classes():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 4, 'academic_year_id': 2026, 'is_locked': 0}),
            ('all', [{'classID': 8}, {'classID': 9}]),
            ('all', [{'class_id': 8}]),
        ]
    )
    service = ExamManagementService(connection, school_id=13)

    assert service.update_exam_series(4, 'Updated Midterm', [8, 9]) is True
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0
    assert any('insert into exam_classes' in query.lower() for query, _ in connection.cursor_obj.executed)


def test_bulk_marks_roll_back_all_rows_when_any_student_is_not_eligible():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 4, 'is_locked': 0}),
            ('one', {'class_id': 8, 'allocation_id': 80}),
            ('all', []),
            ('one', None),
        ]
    )
    service = ExamManagementService(connection, school_id=13)

    with pytest.raises(ExamManagementError, match='Student, subject, and exam assignment'):
        service.save_marks_bulk(4, [
            {'student_id': '1001', 'subject_id': 12, 'mark': '71', 'is_absent': False},
            {'student_id': '1002', 'subject_id': 12, 'mark': '88', 'is_absent': False},
        ])

    assert connection.begin_calls == 1
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    assert not any(
        'insert into exam_marks' in query.lower()
        for query, _ in connection.cursor_obj.executed
    )


def test_save_mark_persists_all_remarks_and_commits_once():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 4, 'is_locked': 0}),
            ('one', {'class_id': 8, 'allocation_id': 80}),
            ('all', []),
            ('one', None),
            ('one', None),
        ]
    )
    service = ExamManagementService(connection, school_id=13)

    assert service.save_mark(
        4, '1001', 12, 71, False, 'Subject remark', 'Class remark', 'Head remark'
    ) is True

    assert connection.commit_calls == 1
    insert_query, insert_params = next(
        (query, params)
        for query, params in connection.cursor_obj.executed
        if 'insert into exam_marks' in query.lower()
    )
    assert insert_params[6:9] == ('Subject remark', 'Class remark', 'Head remark')


def test_exam_subjects_include_class_subjects_for_students_without_enrollments():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'classID': 5, 'display_name': 'Grade 1 A',
                'academic_year_id': 2026, 'exam_academic_year_id': 2026,
            }),
            ('all', [
                {'id': 1, 'code': 'ENG', 'name': 'English'},
                {'id': 2, 'code': 'MTH', 'name': 'Mathematics'},
            ]),
            ('all', [{'subject_id': 1}]),
            ('one', {'count': 1}),
        ]
    )
    service = ExamManagementService(connection, school_id=13)

    subjects = service.get_exam_subjects_for_class(4, 5)

    assert [subject['id'] for subject in subjects] == [1, 2]


def test_exam_subjects_use_individual_enrollments_when_all_students_have_them():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'classID': 5, 'display_name': 'Grade 1 A',
                'academic_year_id': 2026, 'exam_academic_year_id': 2026,
            }),
            ('all', [
                {'id': 1, 'code': 'ENG', 'name': 'English'},
                {'id': 2, 'code': 'MTH', 'name': 'Mathematics'},
            ]),
            ('all', [{'subject_id': 2}]),
            ('one', {'count': 0}),
        ]
    )
    service = ExamManagementService(connection, school_id=13)

    subjects = service.get_exam_subjects_for_class(4, 5)

    assert [subject['id'] for subject in subjects] == [2]


def test_exam_rankings_assign_tied_places_and_exclude_unmarked_students(monkeypatch):
    connection = RecordingConnection()
    service = ExamManagementService(connection, school_id=13)
    classes = [
        {'classID': 5, 'display_name': 'Grade 1 A'},
        {'classID': 6, 'display_name': 'Grade 1 B'},
    ]
    tabulations = {
        5: {'tabulation': [
            {'admno': '1001', 'average': 90, 'total': 180, 'numeric_subjects': 2},
            {'admno': '1002', 'average': 0, 'total': 0, 'numeric_subjects': 0},
        ]},
        6: {'tabulation': [
            {'admno': '1003', 'average': 90, 'total': 90, 'numeric_subjects': 1},
            {'admno': '1004', 'average': 70, 'total': 70, 'numeric_subjects': 1},
        ]},
    }
    monkeypatch.setattr(service, 'get_exam_classes', lambda _exam_id: classes)
    monkeypatch.setattr(
        service,
        'get_class_tabulation',
        lambda _exam_id, class_id: tabulations[class_id],
    )

    rankings = service.get_exam_rankings(4)

    assert [(row['admno'], row['rank']) for row in rankings] == [
        ('1001', 1), ('1003', 1), ('1004', 3),
    ]


def test_class_tabulation_ranks_zero_mark_ahead_of_unmarked_student(monkeypatch):
    connection = RecordingConnection(
        responses=[
            ('all', [
                {'AdmNo': '1001', 'FName': 'No', 'LName': 'Mark'},
                {'AdmNo': '1002', 'FName': 'Zero', 'LName': 'Score'},
            ]),
        ]
    )
    service = ExamManagementService(connection, school_id=13)
    class_info = {
        'classID': 5,
        'display_name': 'Grade 1 A',
        'exam_academic_year_id': 2026,
    }
    subject = {'id': 12, 'name': 'Mathematics', 'code': 'MTH'}
    monkeypatch.setattr(service, '_get_exam_class_details', lambda *_args: class_info)
    monkeypatch.setattr(service, 'get_exam_subjects_for_class', lambda *_args: [subject])
    monkeypatch.setattr(
        service,
        'get_marks_for_class_subject',
        lambda *_args: [{
            'AdmNo': '1002', 'mark': 0, 'is_absent': False, 'grade': None,
        }],
    )
    monkeypatch.setattr(service, 'get_class_grading_scale_id', lambda _class_id: None)
    monkeypatch.setattr(service, 'get_grade_for_mark', lambda *_args: None)

    tabulation = service.get_class_tabulation(4, 5)['tabulation']

    assert [(row['admno'], row['rank']) for row in tabulation] == [
        ('1002', 1), ('1001', '-'),
    ]


def test_most_improved_handles_previous_exam_without_requested_class(monkeypatch):
    connection = RecordingConnection(responses=[('one', {'id': 3})])
    service = ExamManagementService(connection, school_id=13)
    monkeypatch.setattr(
        service,
        'get_exam_series',
        lambda _exam_id: {
            'created_at': datetime(2026, 3, 1),
            'academic_year_id': 2026,
            'term': 1,
        },
    )
    ranking_calls = []

    def rankings(exam_id, class_id=None, limit=None):
        ranking_calls.append((exam_id, class_id, limit))
        if exam_id == 4:
            return [{
                'admno': '1001', 'name': 'Ada', 'class_name': 'Grade 1 B',
                'average': 80, 'numeric_subjects': 2,
            }]
        return [{
            'admno': '1001', 'name': 'Ada', 'class_name': 'Grade 1 A',
            'average': 70, 'numeric_subjects': 2,
        }]

    monkeypatch.setattr(service, 'get_exam_rankings', rankings)

    improved = service.get_most_improved(4, class_id=6)

    assert improved[0]['improvement'] == 10
    assert ranking_calls == [(4, 6, None), (3, None, None)]


def test_stream_analysis_orders_classes_by_mean_score(monkeypatch):
    connection = RecordingConnection()
    service = ExamManagementService(connection, school_id=13)
    classes = [
        {
            'classID': 5, 'display_name': 'Grade 1 A',
            'class_group_code': 'Grade 1-3', 'stream_code': 'A',
        },
        {
            'classID': 6, 'display_name': 'Grade 1 B',
            'class_group_code': 'Grade 1-3', 'stream_code': 'B',
        },
    ]
    tabulations = {
        5: {'tabulation': [
            {'average': 60, 'numeric_subjects': 1},
            {'average': 40, 'numeric_subjects': 1},
        ]},
        6: {'tabulation': [
            {'average': 90, 'numeric_subjects': 1},
        ]},
    }
    monkeypatch.setattr(service, 'get_exam_classes', lambda _exam_id: classes)
    monkeypatch.setattr(
        service,
        'get_class_tabulation',
        lambda _exam_id, class_id: tabulations[class_id],
    )

    analysis = service.get_stream_performance_comparison(4)

    assert [row['stream'] for row in analysis[0]['streams']] == ['B', 'A']
    assert [row['mean_score'] for row in analysis[0]['streams']] == [90, 50]


def test_grading_save_rejects_overlapping_ranges_before_deleting_existing_rows():
    connection = RecordingConnection(
        responses=[('one', {'id': 2})]
    )
    service = ExamManagementService(connection, school_id=13)

    with pytest.raises(ExamManagementError, match='overlap'):
        service.save_grading_details(2, [
            {'grade': 'A', 'min_mark': '0', 'max_mark': '60', 'points': '4'},
            {'grade': 'B', 'min_mark': '50', 'max_mark': '100', 'points': '3'},
        ])

    assert connection.commit_calls == 0
    assert not any(
        'delete from grading_details' in query.lower()
        for query, _ in connection.cursor_obj.executed
    )


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