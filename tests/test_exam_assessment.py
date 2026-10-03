from decimal import Decimal

import pytest

from blueprints.exams.assessment import (
    AssessmentConfigurationError,
    calculate_assessment,
    calculate_bundle,
)
from blueprints.exams.workflow import ExamWorkflowError, ExamWorkflowService


def test_assessment_engine_calculates_unweighted_score_and_preserves_states():
    components = [
        {'id': 1, 'maximum_mark': 20},
        {'id': 2, 'maximum_mark': 80},
        {'id': 3, 'maximum_mark': 20},
    ]

    result = calculate_assessment(
        components,
        {
            1: {'mark': 10, 'is_absent': False},
            2: {'mark': None, 'is_absent': True},
        },
    )

    assert result.total_mark == Decimal(10)
    assert result.maximum_mark == Decimal(120)
    assert result.percentage == Decimal(10) / Decimal(120) * Decimal(100)
    assert (result.scored_count, result.absent_count, result.missing_count) == (1, 1, 1)


def test_assessment_engine_applies_configured_component_weights():
    components = [
        {'id': 1, 'maximum_mark': 20, 'weight_percent': 40},
        {'id': 2, 'maximum_mark': 80, 'weight_percent': 60},
    ]

    result = calculate_assessment(
        components,
        {
            1: {'mark': 10, 'is_absent': False},
            2: {'mark': 60, 'is_absent': False},
        },
    )

    assert result.percentage == Decimal(65)
    assert result.total_mark == Decimal(70)


@pytest.mark.parametrize(
    'components,marks,error',
    [
        (
            [
                {'id': 1, 'maximum_mark': 10, 'weight_percent': 40},
                {'id': 2, 'maximum_mark': 10},
            ],
            {},
            'every component',
        ),
        (
            [
                {'id': 1, 'maximum_mark': 10, 'weight_percent': 40},
                {'id': 2, 'maximum_mark': 10, 'weight_percent': 50},
            ],
            {},
            'total 100%',
        ),
        (
            [{'id': 1, 'maximum_mark': 10}],
            {1: {'mark': 11, 'is_absent': False}},
            'between 0 and 10',
        ),
        (
            [{'id': 1, 'maximum_mark': 10}],
            {1: {'mark': 1, 'is_absent': True}},
            'cannot also contain',
        ),
    ],
)
def test_assessment_engine_rejects_invalid_component_configuration_or_marks(
    components, marks, error
):
    with pytest.raises(AssessmentConfigurationError, match=error):
        calculate_assessment(components, marks)


def test_bundle_engine_excludes_ineligible_exams_and_renormalizes_weights():
    result = calculate_bundle(
        [
            {'id': 1, 'weight_percent': 20},
            {'id': 2, 'weight_percent': 30},
            {'id': 3, 'weight_percent': 50},
        ],
        {
            1: {'eligible': True, 'percentage': 80},
            2: {'eligible': False, 'percentage': 100},
            3: {'eligible': True, 'percentage': 60},
        },
        calculation_method='weighted',
    )

    assert result.percentage == Decimal(4600) / Decimal(70)
    assert result.included_exam_count == 2
    assert result.included_exam_ids == (1, 3)


def test_equal_bundle_has_an_empty_result_for_an_ineligible_learner():
    result = calculate_bundle(
        [{'id': 1}, {'id': 2}],
        {
            1: {'eligible': False, 'percentage': 99},
            2: {'eligible': True, 'percentage': 0},
        },
    )

    assert result.percentage == 0
    assert result.included_exam_count == 1
    assert result.included_exam_ids == (2,)


class WorkflowCursor:
    def __init__(self, exam):
        self.exam = exam
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.exam


class WorkflowConnection:
    def __init__(self, exam):
        self.cursor_obj = WorkflowCursor(exam)
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


def test_workflow_transition_audits_and_records_actor_and_timestamp():
    connection = WorkflowConnection({
        'id': 10, 'workflow_status': 'draft', 'is_locked': False,
    })
    service = ExamWorkflowService(connection, school_id=4)

    assert service.transition(10, 'marks_open', 20) == 'marks_open'

    update_query, update_params = connection.cursor_obj.executed[1]
    assert 'workflow_status = %s' in update_query
    assert update_params == ('marks_open', 10, 4)
    assert 'INSERT INTO exam_audit_events' in connection.cursor_obj.executed[2][0]
    assert connection.begin_calls == connection.commit_calls == 1
    assert connection.rollback_calls == 0


def test_workflow_rejects_skipped_transition_without_committing():
    connection = WorkflowConnection({
        'id': 10, 'workflow_status': 'draft', 'is_locked': False,
    })
    service = ExamWorkflowService(connection, school_id=4)

    with pytest.raises(ExamWorkflowError, match='Cannot transition'):
        service.transition(10, 'published', 20, reason='Ready for release')

    assert connection.rollback_calls == 1
    assert connection.commit_calls == 0


def test_workflow_requires_reason_for_publication_and_unlock_permission_is_distinct():
    connection = WorkflowConnection({
        'id': 10, 'workflow_status': 'approved', 'is_locked': False,
    })
    service = ExamWorkflowService(connection, school_id=4)

    with pytest.raises(ExamWorkflowError, match='reason'):
        service.transition(10, 'published', 20)
    assert ExamWorkflowService.permission_for_transition(
        'published', 'locked'
    ) == 'exam.unlock'
