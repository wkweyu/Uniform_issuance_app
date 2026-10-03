import pytest

from blueprints.exams.statistics import describe_eligible_scores


def test_statistics_use_eligible_denominator_and_include_absent_zero():
    result = describe_eligible_scores(
        [90, 0, 80, 0],
        grade_values=['A', 'B'],
    )

    assert result['eligible_count'] == 4
    assert result['mean'] == 42.5
    assert result['median'] == 40
    assert result['highest'] == 90
    assert result['lowest'] == 0
    assert result['mode'] == [0.0]
    assert result['distribution']['0-<10'] == 2
    assert result['grade_distribution'] == {'A': 1, 'B': 1}
    assert result['pass_percentage'] is None


def test_statistics_are_empty_for_empty_cohort():
    result = describe_eligible_scores([])

    assert result['eligible_count'] == 0
    assert result['mean'] is None
    assert result['quartiles'] == {'q1': None, 'q2': None, 'q3': None}
    assert result['distribution'] == {}


@pytest.mark.parametrize('score', [float('nan'), float('inf'), float('-inf')])
def test_statistics_reject_non_finite_scores(score):
    with pytest.raises(ValueError, match='finite'):
        describe_eligible_scores([score])


@pytest.mark.parametrize('score', [-0.01, 100.01])
def test_statistics_reject_scores_outside_percentage_range(score):
    with pytest.raises(ValueError, match='between 0 and 100'):
        describe_eligible_scores([score])
