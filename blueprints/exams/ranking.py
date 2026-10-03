"""Pure ranking utilities for exam results.

Rows are mappings whose selected metric is already calculated and stored under
the metric's field name. Mean grades use ``grade_order`` from best to worst.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from functools import cmp_to_key
import math
from numbers import Real
from typing import Any, Mapping, Sequence


class RankingMetric(str, Enum):
    TOTAL_MARKS = "total_marks"
    TOTAL_POINTS = "total_points"
    AVERAGE = "average"
    PERCENTAGE = "percentage"
    MEAN_GRADE = "mean_grade"


class RankingStyle(str, Enum):
    DENSE = "dense"
    COMPETITION = "competition"


class MissingValuePolicy(str, Enum):
    ZERO = "zero"
    MISSING = "missing"


@dataclass(frozen=True)
class TieBreaker:
    """A secondary sort criterion; ``order`` optionally defines category order."""

    key: str
    descending: bool = False
    order: Sequence[Any] | None = None


@dataclass(frozen=True)
class RankedRow:
    """One ranked input row, returned without modifying that row."""

    row: Mapping[str, Any]
    rank: int
    value: Any
    original_index: int


def rank_rows(
    rows: Sequence[Mapping[str, Any]],
    metric: RankingMetric | str,
    *,
    tie_breakers: Sequence[TieBreaker] = (),
    style: RankingStyle | str = RankingStyle.COMPETITION,
    grade_order: Sequence[str] | None = None,
    missing_policy: MissingValuePolicy | str | None = None,
) -> list[RankedRow]:
    """Rank result rows by a precomputed metric and optional ordered tie-breakers.

    Metric fields are ``total_marks``, ``total_points``, ``average``,
    ``percentage``, and ``mean_grade``. Grade order must be provided best to
    worst for ``mean_grade``. Missing fields and explicit ``None`` values raise
    unless ``missing_policy`` is explicitly ``"zero"`` or ``"missing"``.
    Under ``"zero"``, missing values behave as score zero; under ``"missing"``,
    they rank below present values. Missing values in tie-break fields follow
    the same policy. Absent fields, explicit ``None``, and present values
    retain distinct states for ordering and rank equality.

    Tie-breakers participate in rank equality after the primary metric. Rows
    equal on the primary metric and every tie-breaker share a rank and retain
    input order. Missing/absent values remain distinct from present values,
    including a present numeric zero.
    """
    selected_metric = RankingMetric(metric)
    selected_style = RankingStyle(style)
    selected_missing_policy = (
        MissingValuePolicy(missing_policy) if missing_policy is not None else None
    )

    if selected_metric is RankingMetric.MEAN_GRADE:
        if not grade_order:
            raise ValueError("grade_order is required for mean_grade ranking")
        if len(set(grade_order)) != len(grade_order):
            raise ValueError("grade_order must not contain duplicates")
        grade_scores = {grade: len(grade_order) - index for index, grade in enumerate(grade_order)}
    else:
        grade_scores = {}

    def read_value(row: Mapping[str, Any], key: str) -> tuple[str, Any]:
        if key not in row or row[key] is None:
            if selected_missing_policy is None:
                state = "absent" if key not in row else "None"
                raise ValueError(
                    f"Missing value for {key!r} ({state}); pass missing_policy explicitly"
                )
            state = "absent" if key not in row else "none"
            if selected_missing_policy is MissingValuePolicy.ZERO:
                return state, 0
            return state, None
        return "present", row[key]

    def numeric_score(value: Any, key: str) -> Real | Decimal:
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            raise TypeError(f"{key!r} must contain a real number, got {value!r}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{key!r} must contain a finite number, got {value!r}")
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError(f"{key!r} must contain a finite number, got {value!r}")
        return value

    normalized: list[
        tuple[Mapping[str, Any], Any, Real | Decimal, bool, list[tuple[bool, Any]], int]
    ] = []
    for index, row in enumerate(rows):
        primary_state, value = read_value(row, selected_metric.value)
        if selected_metric is RankingMetric.MEAN_GRADE and primary_state == "present":
            if value not in grade_scores:
                raise ValueError(f"Unknown mean grade {value!r}; include it in grade_order")
            score = grade_scores[value]
        elif primary_state != "present":
            score = value if value is not None else 0
        else:
            score = numeric_score(value, selected_metric.value)

        tie_values = [read_value(row, tie_breaker.key) for tie_breaker in tie_breakers]
        normalized.append((row, value, score, primary_state, tie_values, index))

    def compare(left: tuple, right: tuple) -> int:
        def compare_value(
            left_state: str,
            left_value: Any,
            right_state: str,
            right_value: Any,
            *,
            descending: bool,
        ) -> int:
            if (
                selected_missing_policy is MissingValuePolicy.MISSING
                and (left_state == "present") != (right_state == "present")
            ):
                return -1 if left_state == "present" else 1
            if left_value != right_value:
                result = -1 if left_value < right_value else 1
                return -result if descending else result
            if left_state != right_state:
                state_order = {"present": 0, "absent": 1, "none": 2}
                return (
                    -1
                    if state_order[left_state] < state_order[right_state]
                    else 1
                )
            return 0

        result = compare_value(left[3], left[2], right[3], right[2], descending=True)
        if result:
            return result
        for position, criterion in enumerate(tie_breakers):
            left_state, left_value = left[4][position]
            right_state, right_value = right[4][position]
            if left_value is None and right_value is None:
                left_order_value = right_order_value = None
            else:
                left_order_value, right_order_value = left_value, right_value
            if criterion.order is not None:
                order = {value: rank for rank, value in enumerate(criterion.order)}
                if (
                    (left_state == "present" and left_order_value not in order)
                    or (right_state == "present" and right_order_value not in order)
                ):
                    raise ValueError(
                        f"Values for tie-breaker {criterion.key!r} must occur in its order"
                    )
                if left_state == "present":
                    left_order_value = order[left_order_value]
                if right_state == "present":
                    right_order_value = order[right_order_value]
            try:
                result = compare_value(
                    left_state,
                    left_order_value,
                    right_state,
                    right_order_value,
                    descending=criterion.descending,
                )
                if result:
                    return result
            except TypeError as error:
                raise TypeError(
                    f"Values for tie-breaker {criterion.key!r} are not comparable"
                ) from error
        return 0

    normalized.sort(key=cmp_to_key(compare))

    ranked: list[RankedRow] = []
    previous: tuple | None = None
    current_rank = 0
    for position, entry in enumerate(normalized, start=1):
        row, value, _score, _state, _tie_values, index = entry
        if previous is None or compare(previous, entry) != 0:
            current_rank = (
                position
                if selected_style is RankingStyle.COMPETITION
                else current_rank + 1
            )
        ranked.append(RankedRow(row=row, rank=current_rank, value=value, original_index=index))
        previous = entry

    return ranked
