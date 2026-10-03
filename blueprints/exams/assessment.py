"""Pure assessment and multi-exam bundle calculations."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence


class AssessmentConfigurationError(ValueError):
    """Raised when component or bundle configuration cannot be calculated."""


@dataclass(frozen=True)
class AssessmentResult:
    total_mark: Decimal
    maximum_mark: Decimal
    percentage: Decimal
    component_count: int
    scored_count: int
    absent_count: int
    missing_count: int


@dataclass(frozen=True)
class BundleResult:
    percentage: Decimal
    included_exam_count: int
    included_exam_ids: tuple[int, ...]


def _decimal(value, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AssessmentConfigurationError(f"{label} must be numeric.") from exc
    if not result.is_finite():
        raise AssessmentConfigurationError(f"{label} must be finite.")
    return result


def calculate_assessment(
    components: Sequence[Mapping],
    marks_by_component: Mapping[int, Mapping],
) -> AssessmentResult:
    """Calculate one subject result; eligible absent/missing components count zero."""
    if not components:
        raise AssessmentConfigurationError("At least one active component is required.")
    component_ids = [component.get("id") for component in components]
    if any(component_id is None for component_id in component_ids):
        raise AssessmentConfigurationError("Each component requires an identifier.")
    if len(component_ids) != len(set(component_ids)):
        raise AssessmentConfigurationError("Component identifiers must be unique.")

    maximums = []
    weights = []
    has_weight = any(
        component.get("weight_percent") is not None
        for component in components
    )
    for component in components:
        maximum = _decimal(component.get("maximum_mark"), "Component maximum")
        if maximum <= 0:
            raise AssessmentConfigurationError("Component maximum must be positive.")
        maximums.append(maximum)
        raw_weight = component.get("weight_percent")
        weight = _decimal(raw_weight, "Component weight") if raw_weight is not None else None
        if weight is not None and not Decimal(0) <= weight <= Decimal(100):
            raise AssessmentConfigurationError("Component weights must be from 0 to 100.")
        weights.append(weight)

    if has_weight:
        if any(weight is None for weight in weights):
            raise AssessmentConfigurationError(
                "Either provide weights for every component or leave all weights empty."
            )
        if sum(weights, Decimal(0)) != Decimal(100):
            raise AssessmentConfigurationError("Component weights must total 100%.")

    total = Decimal(0)
    weighted_percentage = Decimal(0)
    scored = absent = missing = 0
    for component, maximum, weight in zip(components, maximums, weights):
        component_id = component["id"]
        record = marks_by_component.get(component_id)
        if record is None:
            mark = Decimal(0)
            missing += 1
        elif bool(record.get("is_absent", False)):
            if record.get("mark") not in (None, ""):
                raise AssessmentConfigurationError(
                    "An absent component cannot also contain a numeric mark."
                )
            mark = Decimal(0)
            absent += 1
        elif record.get("mark") in (None, ""):
            mark = Decimal(0)
            missing += 1
        else:
            mark = _decimal(record["mark"], "Component mark")
            if mark < 0 or mark > maximum:
                raise AssessmentConfigurationError(
                    f"Mark for component {component_id} must be between 0 and {maximum}."
                )
            scored += 1
        total += mark
        component_percentage = mark / maximum * Decimal(100)
        weighted_percentage += (
            component_percentage * weight / Decimal(100)
            if has_weight
            else mark
        )

    maximum_total = sum(maximums, Decimal(0))
    percentage = (
        weighted_percentage
        if has_weight
        else weighted_percentage / maximum_total * Decimal(100)
    )
    return AssessmentResult(
        total_mark=total,
        maximum_mark=maximum_total,
        percentage=percentage,
        component_count=len(components),
        scored_count=scored,
        absent_count=absent,
        missing_count=missing,
    )


def calculate_bundle(
    exams: Sequence[Mapping],
    learner_results: Mapping[int, Mapping],
    *,
    calculation_method: str = "equal",
) -> BundleResult:
    """Combine eligible exam percentages without penalizing ineligible exams."""
    if calculation_method not in {"equal", "weighted"}:
        raise AssessmentConfigurationError(
            "Bundle calculation method must be equal or weighted."
        )
    exam_ids = [exam.get("id") for exam in exams]
    if any(exam_id is None for exam_id in exam_ids):
        raise AssessmentConfigurationError("Each bundle exam requires an identifier.")
    if len(exam_ids) != len(set(exam_ids)):
        raise AssessmentConfigurationError("An exam may appear only once in a bundle.")
    if not exams:
        raise AssessmentConfigurationError("A bundle must contain at least one exam.")

    configured_weights = []
    for exam in exams:
        raw_weight = exam.get("weight_percent")
        weight = _decimal(raw_weight, "Exam weight") if raw_weight is not None else None
        if weight is not None and not Decimal(0) <= weight <= Decimal(100):
            raise AssessmentConfigurationError("Exam weights must be from 0 to 100.")
        configured_weights.append(weight)
    if calculation_method == "weighted":
        if any(weight is None for weight in configured_weights):
            raise AssessmentConfigurationError(
                "Weighted bundles require a weight for every exam."
            )
        if sum(configured_weights, Decimal(0)) != Decimal(100):
            raise AssessmentConfigurationError("Exam weights must total 100%.")

    included = []
    for exam, weight in zip(exams, configured_weights):
        result = learner_results.get(exam["id"])
        if result is None or not result.get("eligible", False):
            continue
        percentage = _decimal(result.get("percentage"), "Exam percentage")
        if percentage < 0 or percentage > 100:
            raise AssessmentConfigurationError("Exam percentages must be from 0 to 100.")
        included.append((exam["id"], percentage, weight))

    if not included:
        return BundleResult(Decimal(0), 0, ())
    if calculation_method == "equal":
        average = sum((row[1] for row in included), Decimal(0)) / len(included)
    else:
        included_weight = sum((row[2] for row in included), Decimal(0))
        if included_weight <= 0:
            raise AssessmentConfigurationError(
                "Eligible exams must have a combined weight greater than zero."
            )
        average = sum(
            (row[1] * row[2] for row in included),
            Decimal(0),
        ) / included_weight
    return BundleResult(
        percentage=average,
        included_exam_count=len(included),
        included_exam_ids=tuple(row[0] for row in included),
    )
