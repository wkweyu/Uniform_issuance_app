"""Deterministic population statistics for eligible examination cohorts."""

from collections import Counter
from math import isfinite, sqrt
from statistics import median
from typing import Dict, Iterable, List, Optional


def _percentile(values: List[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def describe_eligible_scores(
    eligible_scores: Iterable[float],
    *,
    grade_values: Iterable[Optional[str]] = (),
) -> Dict:
    """Describe scores, where callers supply zero for eligible ABS/MISSING rows.

    Dispersion uses population variance. Quartiles use linear interpolation.
    Grade distribution covers recorded grades only; it does not infer a grade
    for an absent or unmarked row.
    """
    values = [float(value) for value in eligible_scores]
    if any(not isfinite(value) for value in values):
        raise ValueError("Eligible scores must be finite real numbers.")
    if any(value < 0 or value > 100 for value in values):
        raise ValueError("Eligible percentage scores must be between 0 and 100.")
    counts = Counter(values)
    highest_frequency = max(counts.values(), default=0)
    modes = sorted(
        value for value, frequency in counts.items()
        if frequency == highest_frequency and frequency > 1
    )
    grade_distribution = Counter(
        grade for grade in grade_values if grade not in (None, '')
    )
    if not values:
        return {
            'eligible_count': 0,
            'highest': None,
            'lowest': None,
            'mean': None,
            'median': None,
            'mode': [],
            'variance': None,
            'standard_deviation': None,
            'quartiles': {'q1': None, 'q2': None, 'q3': None},
            'distribution': {},
            'grade_distribution': dict(grade_distribution),
            'pass_percentage': None,
            'pass_threshold': None,
            'denominator_policy': 'eligible learners; ABS and MISSING are zero',
        }
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    distribution = {}
    for lower in range(0, 100, 10):
        upper = lower + 10
        label = f'{lower}-<{upper}' if upper < 100 else '90-100'
        if lower == 90:
            distribution[label] = sum(lower <= value <= 100 for value in values)
        else:
            distribution[label] = sum(lower <= value < upper for value in values)
    return {
        'eligible_count': len(values),
        'highest': max(values),
        'lowest': min(values),
        'mean': mean,
        'median': median(values),
        'mode': modes,
        'variance': variance,
        'standard_deviation': sqrt(variance),
        'quartiles': {
            'q1': _percentile(values, 0.25),
            'q2': _percentile(values, 0.5),
            'q3': _percentile(values, 0.75),
        },
        'distribution': distribution,
        'grade_distribution': dict(grade_distribution),
        'pass_percentage': None,
        'pass_threshold': None,
        'denominator_policy': 'eligible learners; ABS and MISSING are zero',
    }
