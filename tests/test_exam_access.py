import json

import pytest

from blueprints.exams.access import ExamAccessService
from blueprints.exams.audit import record_exam_event


class AccessCursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.lastrowid = 77

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if not self.responses:
            return None
        response_type, value = self.responses.pop(0)
        assert response_type == 'one'
        return value

    def fetchall(self):
        if not self.responses:
            return []
        response_type, value = self.responses.pop(0)
        assert response_type == 'all'
        return value


class AccessConnection:
    def __init__(self, responses):
        self.cursor_obj = AccessCursor(responses)
        self.commits = 0
        self.rollbacks = 0
        self.begins = 0

    def cursor(self, *_args, **_kwargs):
        return self.cursor_obj

    def begin(self):
        self.begins += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_examination_officer_gets_only_configured_exam_operations():
    connection = AccessConnection([
        ('all', [{'role_key': 'examination_officer'}]),
        ('all', [{'role_key': 'examination_officer'}]),
        ('all', [{'role_key': 'examination_officer'}]),
        ('all', [{'role_key': 'examination_officer'}]),
    ])
    service = ExamAccessService(connection, school_id=4, user_id=20)

    assert service.has_permission('exam.verify')
    assert service.has_permission('exam.publish')
    assert service.has_permission('exam.report')
    assert not service.has_permission('marks.edit')
    assert len(connection.cursor_obj.executed) == 4


def test_class_teacher_access_is_limited_to_assigned_exam_class():
    connection = AccessConnection([
        ('all', []),
        ('one', {'academic_year_id': 2026}),
        ('one', {'allowed': 1}),
    ])
    service = ExamAccessService(connection, school_id=4, user_id=20)

    assert service.has_permission(
        'marks.edit', exam_id=8, class_id=12, subject_id=33
    )
    class_query, class_params = connection.cursor_obj.executed[2]
    assert 'class_teachers' in class_query
    assert class_params == (20, 12, 2026, 4)


def test_class_teacher_cannot_access_class_outside_exam_or_tenant():
    connection = AccessConnection([
        ('all', []),
        ('one', None),
    ])
    service = ExamAccessService(connection, school_id=4, user_id=20)

    assert not service.has_permission(
        'marks.view', exam_id=8, class_id=99, subject_id=33
    )
    assert len(connection.cursor_obj.executed) == 2
    assert connection.cursor_obj.executed[1][1] == (8, 99, 4)


def test_subject_teacher_access_is_limited_to_allocated_subject():
    connection = AccessConnection([
        ('all', []),
        ('one', {'academic_year_id': 2026}),
        ('one', None),
        ('one', {'allowed': 1}),
    ])
    service = ExamAccessService(connection, school_id=4, user_id=20)

    assert service.has_permission(
        'marks.view', exam_id=8, class_id=12, subject_id=33
    )
    assert not service.has_permission(
        'report.student', exam_id=8, class_id=12, subject_id=33
    )
    subject_query, subject_params = connection.cursor_obj.executed[3]
    assert 'teacher_allocations' in subject_query
    assert subject_params == (20, 12, 33, 2026, 4, 4)


def test_specific_approved_grant_authorizes_only_matching_scope():
    connection = AccessConnection([
        ('all', []),
        ('one', {'academic_year_id': 2026}),
        ('one', None),
        ('one', None),
        ('one', {'allowed': 1}),
    ])
    service = ExamAccessService(connection, school_id=4, user_id=20)

    assert service.has_permission(
        'marks.view', exam_id=8, class_id=12, subject_id=33
    )
    grant_query, grant_params = connection.cursor_obj.executed[4]
    assert 'status = \'approved\'' in grant_query
    assert grant_params == (4, 20, 8, 12, 33, 'marks.view')


def test_exam_audit_event_serializes_before_and_after_values():
    connection = AccessConnection([])
    cursor = connection.cursor_obj

    record_exam_event(
        cursor,
        school_id=4,
        event_key='exam_mark_saved',
        entity_type='exam_mark',
        entity_id='8:101:33',
        actor_user_id=20,
        old_values={'mark': None, 'state': 'missing'},
        new_values={'mark': 0, 'state': 'scored'},
        reason='Corrected from source register',
    )

    query, params = cursor.executed[0]
    assert 'INSERT INTO exam_audit_events' in query
    assert params[:5] == (4, 20, 'exam_mark_saved', 'exam_mark', '8:101:33')
    assert json.loads(params[5]) == {'mark': None, 'state': 'missing'}
    assert json.loads(params[6]) == {'mark': 0, 'state': 'scored'}
    assert params[7] == 'Corrected from source register'


def test_scoped_access_request_is_validated_and_audited_transactionally():
    connection = AccessConnection([
        ('one', {'academic_year_id': 2026}),
        ('one', {'allowed': 1}),
        ('one', None),
    ])
    service = ExamAccessService(connection, school_id=4, user_id=20)

    grant_id = service.request_access(
        exam_id=8,
        class_id=12,
        subject_id=33,
        permission='marks.edit',
        reason='Cover the assigned teacher while they are away.',
    )

    assert grant_id == 77
    assert connection.begins == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0
    insert_query, insert_params = connection.cursor_obj.executed[3]
    assert 'INSERT INTO exam_access_grants' in insert_query
    assert insert_params == (
        4, 20, 8, 12, 33, 'marks.edit', 20,
        'Cover the assigned teacher while they are away.',
    )
    assert 'INSERT INTO exam_audit_events' in connection.cursor_obj.executed[4][0]


def test_scoped_access_review_only_allows_valid_state_transitions():
    connection = AccessConnection([
        ('one', {
            'id': 77,
            'user_id': 20,
            'exam_id': 8,
            'class_id': 12,
            'subject_id': 33,
            'permission_key': 'marks.view',
            'status': 'requested',
        }),
    ])
    service = ExamAccessService(connection, school_id=4, user_id=1)

    assert service.review_access_request(
        77, 'approved', 'Approved for temporary subject coverage.'
    )
    assert connection.commits == 1
    update_query, update_params = connection.cursor_obj.executed[1]
    assert 'UPDATE exam_access_grants' in update_query
    assert update_params == (
        'approved', 1, 'Approved for temporary subject coverage.', 77, 4,
    )
    assert 'INSERT INTO exam_audit_events' in connection.cursor_obj.executed[2][0]


def test_scoped_access_review_rejects_invalid_transition_and_rolls_back():
    connection = AccessConnection([
        ('one', {
            'id': 77,
            'user_id': 20,
            'exam_id': 8,
            'class_id': 12,
            'subject_id': 33,
            'permission_key': 'marks.view',
            'status': 'denied',
        }),
    ])
    service = ExamAccessService(connection, school_id=4, user_id=1)

    with pytest.raises(ValueError, match="Cannot change"):
        service.review_access_request(
            77, 'approved', 'Approved for temporary subject coverage.'
        )

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_exam_access_and_result_templates_compile(app):
    for template_name in (
        'exam_access_roles.html',
        'exam_access_request.html',
        'exam_access_requests.html',
        'marks_entry_select.html',
        'exam_tabulation.html',
        'report_card.html',
    ):
        app.jinja_env.get_template(template_name)


@pytest.mark.parametrize(
    'school_id,event_key,entity_type',
    [(None, 'event', 'exam'), (1, '', 'exam'), (1, 'event', '')],
)
def test_exam_audit_requires_tenant_event_and_entity(
    school_id, event_key, entity_type
):
    connection = AccessConnection([])

    with pytest.raises(ValueError, match='require a school'):
        record_exam_event(
            connection.cursor_obj,
            school_id,
            event_key,
            entity_type,
        )
