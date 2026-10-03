import pytest

from blueprints.exams.services import ExamManagementError, ExamManagementService


class ComponentCursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.lastrowid = 71

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        if not self.responses:
            return []
        return self.responses.pop(0)

    def fetchone(self):
        if not self.responses:
            return None
        return self.responses.pop(0)


class ComponentConnection:
    def __init__(self, responses):
        self.cursor_obj = ComponentCursor(responses)
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


def test_component_results_feed_weighted_marks_and_keep_absence_and_missing_distinct():
    service = ExamManagementService(
        ComponentConnection([
            [
                {
                    'id': 11, 'subject_id': 4, 'name': 'CAT',
                    'category': 'formative', 'maximum_mark': 20,
                    'weight_percent': 50, 'display_order': 0,
                    'is_required': True,
                },
                {
                    'id': 12, 'subject_id': 4, 'name': 'Final',
                    'category': 'summative', 'maximum_mark': 80,
                    'weight_percent': 50, 'display_order': 1,
                    'is_required': True,
                },
            ],
            [
                {
                    'component_id': 11, 'student_id': '1001', 'mark': 10,
                    'is_absent': False, 'remarks': None,
                },
                {
                    'component_id': 12, 'student_id': '1001', 'mark': None,
                    'is_absent': True, 'remarks': None,
                },
                {
                    'component_id': 11, 'student_id': '1002', 'mark': None,
                    'is_absent': True, 'remarks': None,
                },
                {
                    'component_id': 12, 'student_id': '1002', 'mark': None,
                    'is_absent': True, 'remarks': None,
                },
            ],
        ]),
        school_id=7,
    )

    results = service._get_component_results_for_class(
        3, 9, [4], ['1001', '1002', '1003']
    )

    partial = results[('1001', 4)]
    assert partial['mark'] == 25
    assert partial['state'] == 'partial'
    assert (partial['scored_components'], partial['absent_components']) == (1, 1)

    absent = results[('1002', 4)]
    assert absent['mark'] == 0
    assert absent['state'] == 'absent'

    missing = results[('1003', 4)]
    assert missing['mark'] == 0
    assert missing['state'] == 'missing'
    assert missing['missing_components'] == 2


def test_component_mark_batch_rejects_more_than_configured_maximum():
    service = ExamManagementService(ComponentConnection([]), school_id=7)

    with pytest.raises(ExamManagementError, match='1,000'):
        service.save_exam_component_marks_bulk(
            3, 9, 4, [{'student_id': '1001'}] * 1001, actor_user_id=2
        )


def test_weighted_bundle_persists_only_school_owned_exams_atomically():
    connection = ComponentConnection([[{'id': 8}, {'id': 9}]])
    service = ExamManagementService(connection, school_id=7)

    bundle_id = service.save_exam_bundle(
        None,
        'Term Results',
        'weighted',
        'percentage',
        'class',
        'competition',
        [
            {'exam_id': 8, 'weight_percent': '60'},
            {'exam_id': 9, 'weight_percent': '40'},
        ],
        actor_user_id=3,
        ranking_tie_breakers=[{'key': 'total_points', 'direction': 'desc'}],
    )

    assert bundle_id == 71
    assert connection.begin_calls == connection.commit_calls == 1
    assert connection.rollback_calls == 0
    queries = [query.lower() for query, _ in connection.cursor_obj.executed]
    assert any('insert into exam_result_bundles' in query for query in queries)
    assert sum('insert into exam_result_bundle_exams' in query for query in queries) == 2
    assert any('insert into exam_audit_events' in query for query in queries)


def test_weighted_bundle_rejects_invalid_weights_before_starting_transaction():
    connection = ComponentConnection([])
    service = ExamManagementService(connection, school_id=7)

    with pytest.raises(ExamManagementError, match='total 100%'):
        service.save_exam_bundle(
            None,
            'Term Results',
            'weighted',
            'percentage',
            'class',
            'competition',
            [
                {'exam_id': 8, 'weight_percent': '60'},
                {'exam_id': 9, 'weight_percent': '30'},
            ],
            actor_user_id=3,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == connection.rollback_calls == 0


def test_bundle_ranking_uses_saved_metric_style_and_tie_breakers():
    service = ExamManagementService(ComponentConnection([]), school_id=7)
    ranked = service.rank_exam_bundle_results(
        {
            'ranking_metric': 'percentage',
            'ranking_style': 'competition',
            'ranking_tie_breakers': [
                {'key': 'total_points', 'direction': 'desc'},
            ],
        },
        [
            {'admno': '1001', 'percentage': 80, 'total_points': 12},
            {'admno': '1002', 'percentage': 80, 'total_points': 15},
            {'admno': '1003', 'percentage': 70, 'total_points': 18},
        ],
    )

    assert [(row.row['admno'], row.rank) for row in ranked] == [
        ('1002', 1), ('1001', 2), ('1003', 3),
    ]


def test_workbook_component_import_writes_batch_marks_and_audit_atomically(monkeypatch):
    connection = ComponentConnection([
        {'workflow_status': 'marks_open', 'is_locked': False},
        [{'id': 21, 'subject_id': 4, 'maximum_mark': 20, 'is_required': True}],
        None,
    ])
    service = ExamManagementService(connection, school_id=7)
    monkeypatch.setattr(service, 'get_exam_class_info', lambda *_args: {'classID': 9})
    monkeypatch.setattr(
        service, '_assert_mark_target_is_valid',
        lambda *_args: 9,
    )

    result = service.save_exam_workbook_component_marks(
        3,
        9,
        [{
            'student_id': '1001', 'subject_id': 4, 'component_id': 21,
            'mark': '10', 'is_absent': False, 'remarks': 'Good',
        }],
        actor_user_id=2,
        source_sha256='a' * 64,
        row_count=1,
    )

    assert result == {'batch_id': 71, 'mark_count': 1}
    assert connection.begin_calls == connection.commit_calls == 1
    assert connection.rollback_calls == 0
    queries = [query.lower() for query, _ in connection.cursor_obj.executed]
    assert any('insert into exam_import_batches' in query for query in queries)
    assert any('insert into exam_component_marks' in query for query in queries)
    assert sum('insert into exam_audit_events' in query for query in queries) == 2


def test_workbook_component_import_rolls_back_unassigned_component(monkeypatch):
    connection = ComponentConnection([
        {'workflow_status': 'marks_open', 'is_locked': False},
        [{'id': 21, 'subject_id': 4, 'maximum_mark': 20, 'is_required': True}],
    ])
    service = ExamManagementService(connection, school_id=7)
    monkeypatch.setattr(service, 'get_exam_class_info', lambda *_args: {'classID': 9})

    with pytest.raises(ExamManagementError, match='outside this exam class'):
        service.save_exam_workbook_component_marks(
            3,
            9,
            [{
                'student_id': '1001', 'subject_id': 4, 'component_id': 99,
                'mark': '10', 'is_absent': False,
            }],
            actor_user_id=2,
            source_sha256='b' * 64,
            row_count=1,
        )

    assert connection.begin_calls == 1
    assert connection.rollback_calls == 1
    assert connection.commit_calls == 0


def test_subject_remark_override_requires_reason_and_writes_audited_change(monkeypatch):
    connection = ComponentConnection([
        {'workflow_status': 'marks_open', 'is_locked': False},
        {
            'mark': 14, 'grade_id': 3, 'is_absent': False,
            'remarks': 'Good', 'ct_remarks': 'Keep it up',
            'p_remarks': 'Good progress',
        },
    ])
    service = ExamManagementService(connection, school_id=7)
    monkeypatch.setattr(
        service, '_assert_mark_target_is_valid',
        lambda *_args: 9,
    )

    assert service.override_exam_subject_remark(
        3, '1001', 4, 'Excellent progress',
        'Approved after moderation', 2,
    ) is True

    assert connection.begin_calls == connection.commit_calls == 1
    insert = next(
        (query, params)
        for query, params in connection.cursor_obj.executed
        if 'insert into exam_marks' in query.lower()
    )
    assert insert[1][3:9] == (
        14, 3, False, 'Excellent progress', 'Keep it up', 'Good progress',
    )
    audit = next(
        params for query, params in connection.cursor_obj.executed
        if 'insert into exam_audit_events' in query.lower()
    )
    assert audit[-1] == 'Approved after moderation'


def test_subject_remark_override_is_rejected_after_exam_closes():
    connection = ComponentConnection([
        {'workflow_status': 'locked', 'is_locked': True},
    ])
    service = ExamManagementService(connection, school_id=7)

    with pytest.raises(ExamManagementError, match='only be overridden'):
        service.override_exam_subject_remark(
            3, '1001', 4, 'A new remark',
            'Approved after moderation', 2,
        )

    assert connection.rollback_calls == 1
    assert connection.commit_calls == 0
