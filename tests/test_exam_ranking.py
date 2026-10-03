from copy import deepcopy
from decimal import Decimal

import pytest

from blueprints.exams.ranking import (
    MissingValuePolicy,
    RankingMetric,
    RankingStyle,
    TieBreaker,
    rank_rows,
)


@pytest.mark.parametrize(
    ('metric', 'values'),
    [
        (RankingMetric.TOTAL_MARKS, [80, 60]),
        (RankingMetric.TOTAL_POINTS, [8, 6]),
        (RankingMetric.AVERAGE, [80, 60]),
        (RankingMetric.PERCENTAGE, [80, 60]),
        (RankingMetric.MEAN_GRADE, ['A', 'B']),
    ],
)
def test_rank_rows_supports_each_metric(metric, values):
    rows = [
        {metric.value: values[0], 'student': 'Ada'},
        {metric.value: values[1], 'student': 'Ben'},
    ]

    ranked = rank_rows(rows, metric, grade_order=['A', 'B'] if metric is RankingMetric.MEAN_GRADE else None)

    assert [(entry.row['student'], entry.rank) for entry in ranked] == [('Ada', 1), ('Ben', 2)]


def test_mean_grade_uses_caller_order_and_rejects_unknown_grade():
    rows = [{'mean_grade': 'B'}, {'mean_grade': 'A'}, {'mean_grade': 'C'}]

    ranked = rank_rows(rows, 'mean_grade', grade_order=['A', 'B', 'C'])

    assert [entry.row['mean_grade'] for entry in ranked] == ['A', 'B', 'C']
    with pytest.raises(ValueError, match='Unknown mean grade'):
        rank_rows([{'mean_grade': 'D'}], 'mean_grade', grade_order=['A', 'B', 'C'])


def test_dense_and_competition_styles_assign_complete_ranks():
    rows = [{'average': mark} for mark in [90, 90, 80, 70]]

    dense = rank_rows(rows, 'average', style=RankingStyle.DENSE)
    competition = rank_rows(rows, 'average', style=RankingStyle.COMPETITION)

    assert [entry.rank for entry in dense] == [1, 1, 2, 3]
    assert [entry.rank for entry in competition] == [1, 1, 3, 4]


def test_ordered_tie_breakers_resolve_ranks_and_preserve_input_rows():
    rows = [
        {'total_marks': 90, 'student': 'first', 'grade': 'B', 'name': 'Zoe'},
        {'total_marks': 90, 'student': 'second', 'grade': 'A', 'name': 'Mia'},
        {'total_marks': 90, 'student': 'third', 'grade': 'A', 'name': 'Amy'},
        {'total_marks': 80, 'student': 'fourth', 'grade': 'A', 'name': 'Ann'},
    ]
    original = deepcopy(rows)

    ranked = rank_rows(
        rows,
        'total_marks',
        tie_breakers=[
            TieBreaker('grade', order=['A', 'B']),
            TieBreaker('name'),
        ],
    )

    assert [entry.row['student'] for entry in ranked] == ['third', 'second', 'first', 'fourth']
    assert [entry.rank for entry in ranked] == [1, 2, 3, 4]
    assert [entry.original_index for entry in ranked] == [2, 1, 0, 3]
    assert rows == original


@pytest.mark.parametrize(
    ('style', 'expected_ranks'),
    [
        (RankingStyle.DENSE, [1, 1, 2]),
        (RankingStyle.COMPETITION, [1, 1, 3]),
    ],
)
def test_rows_still_tie_when_tie_breakers_do_not_distinguish_them(style, expected_ranks):
    rows = [
        {'average': 90, 'grade': 'A'},
        {'average': 90, 'grade': 'A'},
        {'average': 80, 'grade': 'B'},
    ]

    ranked = rank_rows(
        rows,
        'average',
        tie_breakers=[TieBreaker('grade', order=['A', 'B'])],
        style=style,
    )

    assert [entry.rank for entry in ranked] == expected_ranks


def test_zero_is_numeric_and_decimal_values_are_supported():
    ranked = rank_rows(
        [{'average': 0, 'student': 'zero'}, {'average': Decimal('0.5'), 'student': 'positive'}],
        'average',
    )

    assert [(entry.row['student'], entry.rank) for entry in ranked] == [('positive', 1), ('zero', 2)]


@pytest.mark.parametrize('row', [{'average': None}, {}])
def test_missing_value_requires_an_explicit_policy(row):
    with pytest.raises(ValueError, match='pass missing_policy explicitly'):
        rank_rows([row], 'average')


def test_missing_policy_can_convert_to_zero_or_rank_as_missing():
    rows = [{'average': 0, 'student': 'actual zero'}, {'average': None, 'student': 'unknown'}]

    as_zero = rank_rows(rows, 'average', missing_policy=MissingValuePolicy.ZERO)
    as_missing = rank_rows(rows, 'average', missing_policy=MissingValuePolicy.MISSING)

    assert [entry.row['student'] for entry in as_zero] == ['actual zero', 'unknown']
    assert [entry.rank for entry in as_zero] == [1, 2]
    assert [entry.rank for entry in as_missing] == [1, 2]


def test_missing_grade_policy_and_missing_tie_break_values_are_explicit():
    rows = [{'mean_grade': 'A', 'name': None}, {'mean_grade': None, 'name': 'A'}]

    ranked = rank_rows(
        rows,
        'mean_grade',
        grade_order=['A', 'B'],
        tie_breakers=[TieBreaker('name')],
        missing_policy='missing',
    )

    assert [entry.row for entry in ranked] == [rows[0], rows[1]]
    assert [entry.rank for entry in ranked] == [1, 2]


def test_absent_and_none_remain_distinct_states_under_missing_policy():
    rows = [{'average': 0}, {'average': None}, {}]

    ranked = rank_rows(rows, 'average', missing_policy='missing')

    assert [entry.row for entry in ranked] == [rows[0], rows[2], rows[1]]
    assert [entry.rank for entry in ranked] == [1, 2, 3]
