"""
=============================================================================
Module: Exam Management System Service
File: exam_management_service.py
Database: schoolmngt

Centralized business logic for:
- Exam Series Management
- Marks Recording
- Grading & Results Tabulation
- Performance Analytics
=============================================================================
"""

import pymysql
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Tuple, Optional
import logging
from flask import has_request_context, session
from core.audit import audit_log
from core.tenancy import require_current_school_id
from flask import g
from blueprints.exams.assessment import (
    AssessmentConfigurationError,
    calculate_bundle,
    calculate_assessment,
)
from blueprints.exams.audit import record_exam_event
from blueprints.exams.ranking import RankingStyle, TieBreaker, rank_rows
from blueprints.exams.statistics import describe_eligible_scores
from blueprints.exams.workflow import ExamWorkflowError, ExamWorkflowService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ExamManagementError(Exception):
    """Base exception for exam management errors."""
    pass

class ExamManagementService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id or require_current_school_id()
        self._grading_details_cache: Dict[Optional[int], List[Dict]] = {}
        self._effective_scale_cache: Dict[Tuple[int, int], Optional[int]] = {}
        self._class_scale_cache: Dict[int, Optional[int]] = {}
        self._exam_class_details_cache: Dict[Tuple[int, int], Dict] = {}
        self._exam_subjects_cache: Dict[Tuple[int, int], List[Dict]] = {}
        self._validated_exam_ids: set = set()

    def clear_caches(self) -> None:
        self._grading_details_cache.clear()
        self._effective_scale_cache.clear()
        self._class_scale_cache.clear()
        self._exam_class_details_cache.clear()
        self._exam_subjects_cache.clear()
        self._validated_exam_ids.clear()

    def _record_audit_event(
        self,
        event_key: str,
        entity_type: str,
        entity_id: Optional[str] = None,
        old_values=None,
        new_values=None,
        reason: Optional[str] = None,
    ) -> None:
        actor_user_id = session.get('userNo') if has_request_context() else None
        record_exam_event(
            self.cursor,
            self.school_id,
            event_key,
            entity_type,
            entity_id,
            actor_user_id=actor_user_id,
            old_values=old_values,
            new_values=new_values,
            reason=reason,
        )

    def _assert_academic_year_belongs_to_school(self, academic_year_id: int) -> None:
        self.cursor.execute("SELECT id FROM academic_years WHERE id = %s AND school_id = %s", (academic_year_id, self.school_id))
        if not self.cursor.fetchone():
            raise ExamManagementError("Academic year not found for the active school.")

    def _assert_exam_belongs_to_school(self, exam_id: int) -> None:
        if exam_id in self._validated_exam_ids:
            return
        self.cursor.execute("SELECT id FROM exam_series WHERE id = %s AND school_id = %s", (exam_id, self.school_id))
        if not self.cursor.fetchone():
            raise ExamManagementError("Exam series not found for the active school.")
        self._validated_exam_ids.add(exam_id)

    def _assert_classes_belong_to_school(
        self,
        class_ids: List[int],
        academic_year_id: Optional[int] = None,
        allow_inactive_exam_id: Optional[int] = None,
    ) -> None:
        if not class_ids:
            raise ExamManagementError("Select at least one participating class.")
        placeholders = ', '.join(['%s'] * len(class_ids))
        filters = ["school_id = %s"]
        params = tuple(class_ids) + (self.school_id,)
        if academic_year_id is not None:
            filters.append("academic_year_id = %s")
            params += (academic_year_id,)
            active_class_filter = "is_active = TRUE"
            if allow_inactive_exam_id is not None:
                active_class_filter = """
              (
                  is_active = TRUE
                  OR classID IN (
                      SELECT class_id
                      FROM exam_classes
                      WHERE exam_id = %s AND school_id = %s
                  )
              )
            """
                params += (allow_inactive_exam_id, self.school_id)
            filters.append(active_class_filter)
        self.cursor.execute(
            f"""
            SELECT classID
            FROM classes
            WHERE classID IN ({placeholders})
              AND {' AND '.join(filters)}
            """,
            params,
        )
        found = {row['classID'] for row in self.cursor.fetchall()}
        missing = [class_id for class_id in class_ids if class_id not in found]
        if missing:
            if academic_year_id is None:
                raise ExamManagementError("One or more classes do not belong to the active school.")
            raise ExamManagementError(
                "Select only active classes for the exam's academic year and active school."
            )

    def _assert_grading_scale_belongs_to_school(self, scale_id: Optional[int]) -> None:
        if scale_id is None:
            return
        self.cursor.execute("SELECT id FROM grading_scales WHERE id = %s AND school_id = %s", (scale_id, self.school_id))
        if not self.cursor.fetchone():
            raise ExamManagementError("Grading scale not found for the active school.")

    def _get_exam_class_details(self, exam_id: int, class_id: int) -> Dict:
        cache_key = (exam_id, class_id)
        if cache_key in self._exam_class_details_cache:
            return self._exam_class_details_cache[cache_key]
        self.cursor.execute(
            """
            SELECT c.classID, c.display_name, c.academic_year_id,
                   c.class_group_code, c.stream_code, e.academic_year_id as exam_academic_year_id
            FROM exam_series e
            JOIN exam_classes ec
              ON ec.exam_id = e.id AND ec.school_id = e.school_id
            JOIN classes c
              ON c.classID = ec.class_id AND c.school_id = ec.school_id
            WHERE e.id = %s AND ec.class_id = %s AND e.school_id = %s
            """,
            (exam_id, class_id, self.school_id),
        )
        class_info = self.cursor.fetchone()
        if not class_info:
            raise ExamManagementError("Class is not assigned to this exam series.")
        if class_info['academic_year_id'] != class_info['exam_academic_year_id']:
            raise ExamManagementError("Class does not belong to this exam's academic year.")
        self._exam_class_details_cache[cache_key] = class_info
        return class_info

    def _get_active_class_subjects(self, class_id: int) -> List[Dict]:
        try:
            self.cursor.execute(
                """
                SELECT s.subjectNo as id, s.code, s.subjName as name,
                       cs.is_compulsory
                FROM class_subjects cs
                JOIN subjects s ON s.subjectNo = cs.subject_id
                WHERE cs.class_id = %s AND cs.school_id = %s
                  AND cs.is_active = TRUE AND s.school_id = %s
                ORDER BY s.code, s.subjName
                """,
                (class_id, self.school_id, self.school_id),
            )
        except pymysql.Error:
            self.connection.rollback()
            self.cursor.execute(
                """
                SELECT s.id, s.code, s.name, cs.is_compulsory
                FROM class_subjects cs
                JOIN subjects s ON s.id = cs.subject_id
                WHERE cs.class_id = %s AND cs.school_id = %s
                  AND cs.is_active = TRUE AND s.school_id = %s
                ORDER BY s.code, s.name
                """,
                (class_id, self.school_id, self.school_id),
            )
        return self.cursor.fetchall()

    def _get_student_active_subject_ids(self, allocation_id: int) -> List[int]:
        self.cursor.execute(
            """
            SELECT subject_id
            FROM student_subjects
            WHERE class_allocation_id = %s AND school_id = %s AND is_active = TRUE
            """,
            (allocation_id, self.school_id),
        )
        return [row['subject_id'] for row in self.cursor.fetchall()]

    def _assert_mark_target_is_valid(self, exam_id: int, student_id: str, subject_id: int) -> int:
        self.cursor.execute(
            """
            SELECT ca.class_id, ca.id as allocation_id
            FROM class_allocation ca
            JOIN exam_series e
              ON e.id = %s AND e.school_id = ca.school_id
             AND e.academic_year_id = ca.academic_year_id
            JOIN exam_classes ec
              ON ec.exam_id = e.id AND ec.class_id = ca.class_id
             AND ec.school_id = ca.school_id
            JOIN class_subjects cs
              ON cs.class_id = ca.class_id AND cs.school_id = ca.school_id
             AND cs.subject_id = %s AND cs.is_active = TRUE
            WHERE ca.student_id = %s AND ca.is_current = TRUE
              AND ca.school_id = %s
            LIMIT 1
            """,
            (exam_id, subject_id, student_id, self.school_id),
        )
        row = self.cursor.fetchone()
        if not row:
            raise ExamManagementError("Student, subject, and exam assignment do not match for the active school.")

        enrolled_subject_ids = self._get_student_active_subject_ids(row['allocation_id'])
        if enrolled_subject_ids and subject_id not in enrolled_subject_ids:
            raise ExamManagementError("Subject is not enrolled for this student.")
        return row['class_id']

    def get_exam_subjects_for_class(self, exam_id: int, class_id: int) -> List[Dict]:
        """Return subjects eligible for this exam class under student enrollment rules."""
        cache_key = (exam_id, class_id)
        if cache_key in self._exam_subjects_cache:
            return self._exam_subjects_cache[cache_key]

        class_info = self._get_exam_class_details(exam_id, class_id)
        class_subjects = self._get_active_class_subjects(class_id)
        if not class_subjects:
            self._exam_subjects_cache[cache_key] = []
            return []

        self.cursor.execute(
            """
            SELECT DISTINCT ss.subject_id
            FROM class_allocation ca
            JOIN student_subjects ss
              ON ss.class_allocation_id = ca.id AND ss.school_id = ca.school_id
             AND ss.is_active = TRUE
            WHERE ca.class_id = %s AND ca.academic_year_id = %s
              AND ca.is_current = TRUE AND ca.school_id = %s
            """,
            (class_id, class_info['exam_academic_year_id'], self.school_id),
        )
        enrolled_subject_ids = {row['subject_id'] for row in self.cursor.fetchall()}
        self.cursor.execute(
            """
            SELECT COUNT(*) as count
            FROM class_allocation ca
            WHERE ca.class_id = %s AND ca.academic_year_id = %s
              AND ca.is_current = TRUE AND ca.school_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM student_subjects ss
                  WHERE ss.class_allocation_id = ca.id
                    AND ss.school_id = ca.school_id AND ss.is_active = TRUE
              )
            """,
            (class_id, class_info['exam_academic_year_id'], self.school_id),
        )
        fallback_student_count = self.cursor.fetchone()['count']

        if not enrolled_subject_ids and fallback_student_count == 0:
            res = class_subjects
        else:
            res = [
                subject for subject in class_subjects
                if subject['id'] in enrolled_subject_ids or fallback_student_count > 0
            ]
        self._exam_subjects_cache[cache_key] = res
        return res

    def get_exam_subjects_status(self, exam_id: int, class_id: int) -> List[Dict]:
        """Return eligible subjects and mark-entry completion counts for a class."""
        subjects = self.get_exam_subjects_for_class(exam_id, class_id)
        self.cursor.execute(
            """
            SELECT subject_id, COUNT(*) AS component_count
            FROM exam_assessment_components
            WHERE school_id = %s AND exam_id = %s AND class_id = %s
              AND is_active = TRUE
            GROUP BY subject_id
            """,
            (self.school_id, exam_id, class_id),
        )
        component_counts = {
            row['subject_id']: row['component_count']
            for row in self.cursor.fetchall()
        }
        status = []
        for subject in subjects:
            students = self.get_marks_for_class_subject(exam_id, class_id, subject['id'])
            total = len(students)
            component_count = component_counts.get(subject['id'], 0)
            if component_count:
                components = self.get_exam_assessment_components(
                    exam_id, class_id, subject['id']
                )
                component_marks = self.get_exam_component_marks_for_class(
                    exam_id,
                    class_id,
                    subject['id'],
                    [str(student['AdmNo']) for student in students],
                    components=components,
                )
                component_ids = {component['id'] for component in components}
                entered = sum(
                    all(
                        (str(student['AdmNo']), component_id) in component_marks
                        and (
                            component_marks[
                                (str(student['AdmNo']), component_id)
                            ]['mark'] is not None
                            or component_marks[
                                (str(student['AdmNo']), component_id)
                            ]['is_absent']
                        )
                        for component_id in component_ids
                    )
                    for student in students
                )
            else:
                entered = sum(
                    student['mark'] is not None or bool(student['is_absent'])
                    for student in students
                )
            complete = total > 0 and entered == total
            status.append({
                **subject,
                'is_complete': complete,
                'status_text': f"{entered}/{total} entered" if total else "No eligible students",
                'entered_count': entered,
                'student_count': total,
                'component_count': component_count,
                'uses_components': subject['id'] in component_counts,
            })
        return status

    def get_exam_assessment_components(
        self,
        exam_id: int,
        class_id: int,
        subject_id: int,
    ) -> List[Dict]:
        self.get_exam_subject(exam_id, class_id, subject_id)
        self.cursor.execute(
            """
            SELECT id, name, category, maximum_mark, weight_percent,
                   display_order, is_required
            FROM exam_assessment_components
            WHERE school_id = %s AND exam_id = %s AND class_id = %s
              AND subject_id = %s AND is_active = TRUE
            ORDER BY display_order, id
            """,
            (self.school_id, exam_id, class_id, subject_id),
        )
        return self.cursor.fetchall()

    def get_exam_component_marks_for_class(
        self,
        exam_id: int,
        class_id: int,
        subject_id: int,
        student_ids: List[str],
        components: Optional[List[Dict]] = None,
    ) -> Dict[Tuple[str, int], Dict]:
        if components is None:
            components = self.get_exam_assessment_components(
                exam_id, class_id, subject_id
            )
        if not components or not student_ids:
            return {}
        component_ids = [component['id'] for component in components]
        marks = {}
        for component_offset in range(0, len(component_ids), 500):
            component_chunk = component_ids[component_offset:component_offset + 500]
            component_placeholders = ', '.join(['%s'] * len(component_chunk))
            for student_offset in range(0, len(student_ids), 500):
                student_chunk = student_ids[student_offset:student_offset + 500]
                student_placeholders = ', '.join(['%s'] * len(student_chunk))
                self.cursor.execute(
                    f"""
                    SELECT component_id, student_id, mark, is_absent, remarks
                    FROM exam_component_marks
                    WHERE school_id = %s
                      AND component_id IN ({component_placeholders})
                      AND student_id IN ({student_placeholders})
                    """,
                    (
                        self.school_id, *component_chunk, *student_chunk,
                    ),
                )
                for mark in self.cursor.fetchall():
                    marks[(str(mark['student_id']), mark['component_id'])] = mark
        return marks

    def get_exam_bundle_options(self) -> List[Dict]:
        self.cursor.execute(
            """
            SELECT e.id, e.name, e.term, e.workflow_status, ay.year
            FROM exam_series e
            JOIN academic_years ay
              ON ay.id = e.academic_year_id AND ay.school_id = e.school_id
            WHERE e.school_id = %s
            ORDER BY ay.year DESC, e.term DESC, e.id DESC
            """,
            (self.school_id,),
        )
        return self.cursor.fetchall()

    def get_exam_bundles(self, bundle_id: Optional[int] = None) -> List[Dict]:
        filters = ["b.school_id = %s"]
        params = [self.school_id]
        if bundle_id is not None:
            filters.append("b.id = %s")
            params.append(bundle_id)
        self.cursor.execute(
            f"""
            SELECT b.id, b.name, b.calculation_method, b.ranking_metric,
                   b.ranking_scope, b.ranking_style, b.ranking_tie_breakers,
                   b.term_scope, b.effective_from, b.effective_to, b.is_active,
                   be.exam_id, be.display_order, be.weight_percent AS exam_weight,
                   e.name AS exam_name, e.term, ay.year AS academic_year
            FROM exam_result_bundles b
            LEFT JOIN exam_result_bundle_exams be
              ON be.bundle_id = b.id AND be.school_id = b.school_id
            LEFT JOIN exam_series e
              ON e.id = be.exam_id AND e.school_id = be.school_id
            LEFT JOIN academic_years ay
              ON ay.id = e.academic_year_id AND ay.school_id = e.school_id
            WHERE {' AND '.join(filters)}
            ORDER BY b.name, be.display_order, be.id
            """,
            tuple(params),
        )
        bundles_by_id = {}
        for row in self.cursor.fetchall():
            bundle = bundles_by_id.setdefault(row['id'], {
                key: row[key]
                for key in (
                    'id', 'name', 'calculation_method', 'ranking_metric',
                    'ranking_scope', 'ranking_style', 'ranking_tie_breakers',
                    'term_scope', 'effective_from', 'effective_to', 'is_active',
                )
            })
            if isinstance(bundle['ranking_tie_breakers'], str):
                bundle['ranking_tie_breakers'] = json.loads(
                    bundle['ranking_tie_breakers']
                )
            if row['exam_id'] is not None:
                bundle.setdefault('exams', []).append({
                    'id': row['exam_id'],
                    'name': row['exam_name'],
                    'term': row['term'],
                    'academic_year': row['academic_year'],
                    'display_order': row['display_order'],
                    'weight_percent': row['exam_weight'],
                })
            else:
                bundle['exams'] = []
        return list(bundles_by_id.values())

    def save_exam_bundle(
        self,
        bundle_id: Optional[int],
        name: str,
        calculation_method: str,
        ranking_metric: str,
        ranking_scope: str,
        ranking_style: str,
        exams: List[Dict],
        actor_user_id: int,
        *,
        ranking_tie_breakers: Optional[List[Dict]] = None,
        term_scope: Optional[str] = None,
        effective_from: Optional[str] = None,
        effective_to: Optional[str] = None,
    ) -> int:
        """Create or replace a school-owned exam bundle and its ordered exams."""
        name = (name or '').strip()
        if not name or len(name) > 100:
            raise ExamManagementError("Bundle name must contain 1 to 100 characters.")
        if calculation_method not in {'equal', 'weighted'}:
            raise ExamManagementError("Bundle calculation must be equal or weighted.")
        allowed_metrics = {
            'total_marks', 'total_points', 'average', 'percentage', 'mean_grade',
        }
        if ranking_metric not in allowed_metrics:
            raise ExamManagementError("The selected bundle ranking metric is invalid.")
        if ranking_scope not in {'stream', 'class', 'grade', 'school'}:
            raise ExamManagementError("The selected bundle ranking scope is invalid.")
        if ranking_style not in {'dense', 'competition'}:
            raise ExamManagementError("The selected bundle ranking style is invalid.")
        if not exams:
            raise ExamManagementError("Select at least one exam for the bundle.")
        if len(exams) > 100:
            raise ExamManagementError("A bundle cannot contain more than 100 exams.")

        tie_breakers = []
        allowed_tie_keys = {
            'total_marks', 'total_points', 'average', 'percentage',
            'mean_grade', 'gender', 'admno',
        }
        for item in ranking_tie_breakers or []:
            key = str(item.get('key') or '')
            direction = item.get('direction', 'desc')
            if key not in allowed_tie_keys or direction not in {'asc', 'desc'}:
                raise ExamManagementError("A bundle ranking tie-break rule is invalid.")
            tie_breakers.append({'key': key, 'direction': direction})
        if len({row['key'] for row in tie_breakers}) != len(tie_breakers):
            raise ExamManagementError("Bundle ranking tie-break fields must be unique.")
        if term_scope and len(term_scope) > 24:
            raise ExamManagementError("Term scope cannot exceed 24 characters.")

        normalized_exams = []
        seen_exam_ids = set()
        weight_total = Decimal(0)
        has_weight = False
        for position, item in enumerate(exams):
            try:
                exam_id = int(item.get('exam_id'))
            except (TypeError, ValueError) as exc:
                raise ExamManagementError("Each bundle exam must be selected.") from exc
            if exam_id in seen_exam_ids:
                raise ExamManagementError("An exam may appear only once in a bundle.")
            seen_exam_ids.add(exam_id)
            raw_weight = item.get('weight_percent')
            try:
                weight = Decimal(str(raw_weight)) if raw_weight not in (None, '') else None
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ExamManagementError("Bundle weights must be numeric.") from exc
            if weight is not None:
                if not weight.is_finite() or weight < 0 or weight > 100:
                    raise ExamManagementError("Bundle weights must be between 0 and 100.")
                has_weight = True
                weight_total += weight
            normalized_exams.append({
                'exam_id': exam_id,
                'display_order': position,
                'weight_percent': weight,
            })
        if calculation_method == 'weighted':
            if any(row['weight_percent'] is None for row in normalized_exams):
                raise ExamManagementError(
                    "Weighted bundles require a weight for every selected exam."
                )
            if weight_total != Decimal(100):
                raise ExamManagementError("Bundle weights must total 100%.")
        elif has_weight:
            raise ExamManagementError(
                "Leave exam weights blank when using equal weighting."
            )

        try:
            start_date = date.fromisoformat(effective_from) if effective_from else None
            end_date = date.fromisoformat(effective_to) if effective_to else None
        except ValueError as exc:
            raise ExamManagementError("Bundle effective dates must use YYYY-MM-DD.") from exc
        if start_date and end_date and start_date > end_date:
            raise ExamManagementError("Bundle start date must not be after its end date.")

        self.connection.begin()
        try:
            if bundle_id is not None:
                self.cursor.execute(
                    """
                    SELECT id, name, calculation_method, ranking_metric,
                           ranking_scope, ranking_style, ranking_tie_breakers,
                           term_scope, effective_from, effective_to
                    FROM exam_result_bundles
                    WHERE id = %s AND school_id = %s
                    FOR UPDATE
                    """,
                    (bundle_id, self.school_id),
                )
                previous = self.cursor.fetchone()
                if not previous:
                    raise ExamManagementError("Result bundle not found for the active school.")
                self.cursor.execute(
                    """
                    UPDATE exam_result_bundles
                    SET name = %s, calculation_method = %s, ranking_metric = %s,
                        ranking_scope = %s, ranking_style = %s,
                        ranking_tie_breakers = %s, term_scope = %s,
                        effective_from = %s, effective_to = %s
                    WHERE id = %s AND school_id = %s
                    """,
                    (
                        name, calculation_method, ranking_metric, ranking_scope,
                        ranking_style, json.dumps(tie_breakers), term_scope,
                        start_date, end_date, bundle_id, self.school_id,
                    ),
                )
            else:
                previous = None
                self.cursor.execute(
                    """
                    INSERT INTO exam_result_bundles (
                        school_id, name, calculation_method, ranking_metric,
                        ranking_scope, ranking_style, ranking_tie_breakers,
                        term_scope, effective_from, effective_to, created_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.school_id, name, calculation_method, ranking_metric,
                        ranking_scope, ranking_style, json.dumps(tie_breakers),
                        term_scope, start_date, end_date, actor_user_id,
                    ),
                )
                bundle_id = self.cursor.lastrowid

            exam_placeholders = ', '.join(['%s'] * len(normalized_exams))
            self.cursor.execute(
                f"""
                SELECT id FROM exam_series
                WHERE school_id = %s AND id IN ({exam_placeholders})
                """,
                (self.school_id, *(row['exam_id'] for row in normalized_exams)),
            )
            owned_exam_ids = {row['id'] for row in self.cursor.fetchall()}
            if owned_exam_ids != seen_exam_ids:
                raise ExamManagementError(
                    "Every selected exam must belong to the active school."
                )

            self.cursor.execute(
                """
                DELETE FROM exam_result_bundle_exams
                WHERE school_id = %s AND bundle_id = %s
                """,
                (self.school_id, bundle_id),
            )
            for row in normalized_exams:
                self.cursor.execute(
                    """
                    INSERT INTO exam_result_bundle_exams (
                        school_id, bundle_id, exam_id, display_order, weight_percent
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        self.school_id, bundle_id, row['exam_id'],
                        row['display_order'], row['weight_percent'],
                    ),
                )
            self._record_audit_event(
                'exam_result_bundle_saved',
                'exam_result_bundle',
                bundle_id,
                old_values=previous,
                new_values={
                    'name': name,
                    'calculation_method': calculation_method,
                    'ranking_metric': ranking_metric,
                    'ranking_scope': ranking_scope,
                    'ranking_style': ranking_style,
                    'ranking_tie_breakers': tie_breakers,
                    'term_scope': term_scope,
                    'effective_from': start_date,
                    'effective_to': end_date,
                    'exams': normalized_exams,
                },
            )
            self.connection.commit()
            return bundle_id
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, ExamManagementError):
                raise
            raise ExamManagementError(f"Failed to save result bundle: {exc}") from exc

    def calculate_bundle_for_learner(
        self,
        bundle: Dict,
        learner_results: Dict[int, Dict],
    ):
        """Calculate normalized bundle results using the shared bundle engine."""
        try:
            return calculate_bundle(
                bundle.get('exams', []),
                learner_results,
                calculation_method=bundle['calculation_method'],
            )
        except AssessmentConfigurationError as exc:
            raise ExamManagementError(str(exc)) from exc

    def rank_exam_bundle_results(
        self,
        bundle: Dict,
        rows: List[Dict],
        *,
        grade_order: Optional[List[str]] = None,
    ):
        """Rank already-calculated bundle rows using the saved school policy."""
        try:
            tie_breakers = [
                TieBreaker(
                    key=rule['key'],
                    descending=rule.get('direction', 'desc') == 'desc',
                )
                for rule in bundle.get('ranking_tie_breakers') or []
            ]
            return rank_rows(
                rows,
                bundle['ranking_metric'],
                tie_breakers=tie_breakers,
                style=bundle['ranking_style'],
                grade_order=grade_order,
                missing_policy='missing',
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExamManagementError(
                f"Bundle ranking configuration is invalid: {exc}"
            ) from exc

    def save_exam_assessment_components(
        self,
        exam_id: int,
        class_id: int,
        subject_id: int,
        components: List[Dict],
        actor_user_id: int,
    ) -> int:
        """Replace a draft subject's assessment definition atomically."""
        if not components:
            raise ExamManagementError("At least one assessment component is required.")
        self.connection.begin()
        try:
            self.cursor.execute(
                """
                SELECT workflow_status, is_locked
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            status = exam.get('workflow_status') or (
                'locked' if exam.get('is_locked') else 'marks_open'
            )
            if status != 'draft':
                raise ExamManagementError(
                    "Assessment components can only be configured while the exam is a draft."
                )
            self.get_exam_subject(exam_id, class_id, subject_id)

            normalized = []
            names = set()
            has_weight = any(
                row.get('weight_percent') not in (None, '')
                for row in components
            )
            weight_total = Decimal(0)
            for position, row in enumerate(components):
                name = str(row.get('name') or '').strip()
                category = str(row.get('category') or '').strip().lower()
                try:
                    maximum = Decimal(str(row.get('maximum_mark')))
                    weight = (
                        Decimal(str(row['weight_percent']))
                        if row.get('weight_percent') not in (None, '')
                        else None
                    )
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise ExamManagementError(
                        "Each component needs a valid maximum mark and optional weight."
                    ) from exc
                if not name or len(name) > 80:
                    raise ExamManagementError(
                        "Component names must contain 1 to 80 characters."
                    )
                if name.casefold() in names:
                    raise ExamManagementError("Component names must be unique per subject.")
                if category not in {'formative', 'summative'}:
                    raise ExamManagementError(
                        "Component category must be formative or summative."
                    )
                if not maximum.is_finite() or maximum <= 0:
                    raise ExamManagementError("Component maximum must be greater than zero.")
                if weight is not None and (
                    not weight.is_finite()
                    or weight < 0
                    or weight > 100
                ):
                    raise ExamManagementError(
                        "Component weights must be between 0 and 100."
                    )
                if has_weight and weight is None:
                    raise ExamManagementError(
                        "Provide a weight for every component or leave all weights empty."
                    )
                names.add(name.casefold())
                if weight is not None:
                    weight_total += weight
                normalized.append({
                    'name': name,
                    'category': category,
                    'maximum_mark': maximum,
                    'weight_percent': weight,
                    'display_order': int(row.get('display_order', position)),
                    'is_required': bool(row.get('is_required', True)),
                })
            if has_weight and weight_total != Decimal(100):
                raise ExamManagementError("Component weights must total 100%.")

            self.cursor.execute(
                """
                SELECT id, name, category, maximum_mark, weight_percent,
                       display_order, is_required
                FROM exam_assessment_components
                WHERE school_id = %s AND exam_id = %s AND class_id = %s
                  AND subject_id = %s
                FOR UPDATE
                """,
                (self.school_id, exam_id, class_id, subject_id),
            )
            previous = self.cursor.fetchall()
            previous_ids = [row['id'] for row in previous]
            if previous_ids:
                placeholders = ', '.join(['%s'] * len(previous_ids))
                self.cursor.execute(
                    f"""
                    SELECT 1
                    FROM exam_component_marks
                    WHERE school_id = %s AND component_id IN ({placeholders})
                    LIMIT 1
                    """,
                    (self.school_id, *previous_ids),
                )
                if self.cursor.fetchone():
                    raise ExamManagementError(
                        "Existing component marks prevent changing this assessment definition."
                    )
            self.cursor.execute(
                """
                DELETE FROM exam_assessment_components
                WHERE school_id = %s AND exam_id = %s AND class_id = %s
                  AND subject_id = %s
                """,
                (self.school_id, exam_id, class_id, subject_id),
            )
            for row in normalized:
                self.cursor.execute(
                    """
                    INSERT INTO exam_assessment_components (
                        school_id, exam_id, class_id, subject_id, name,
                        category, maximum_mark, weight_percent, display_order,
                        is_required, created_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.school_id, exam_id, class_id, subject_id,
                        row['name'], row['category'], row['maximum_mark'],
                        row['weight_percent'], row['display_order'],
                        row['is_required'], actor_user_id,
                    ),
                )
            self._record_audit_event(
                'exam_assessment_components_updated',
                'exam_series_class_subject',
                f'{exam_id}:{class_id}:{subject_id}',
                old_values={'components': previous},
                new_values={'components': normalized},
            )
            self.connection.commit()
            return len(normalized)
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, ExamManagementError):
                raise
            raise ExamManagementError(
                f"Failed to save assessment components: {exc}"
            ) from exc

    def _get_component_results_for_class(
        self,
        exam_id: int,
        class_id: int,
        subject_ids: List[int],
        student_ids: List[str],
    ) -> Dict[Tuple[str, int], Dict]:
        """Batch component configuration and marks for a class result view."""
        if not subject_ids or not student_ids:
            return {}
        subject_placeholders = ', '.join(['%s'] * len(subject_ids))
        self.cursor.execute(
            f"""
            SELECT id, subject_id, name, category, maximum_mark,
                   weight_percent, display_order, is_required
            FROM exam_assessment_components
            WHERE school_id = %s AND exam_id = %s AND class_id = %s
              AND subject_id IN ({subject_placeholders}) AND is_active = TRUE
            ORDER BY subject_id, display_order, id
            """,
            (
                self.school_id, exam_id, class_id, *subject_ids,
            ),
        )
        components_by_subject = {}
        for component in self.cursor.fetchall():
            components_by_subject.setdefault(
                component['subject_id'], []
            ).append(component)
        if not components_by_subject:
            return {}

        marks_by_component_student = {}
        component_ids = [
            component['id']
            for components in components_by_subject.values()
            for component in components
        ]
        for component_offset in range(0, len(component_ids), 500):
            component_chunk = component_ids[component_offset:component_offset + 500]
            component_placeholders = ', '.join(['%s'] * len(component_chunk))
            for student_offset in range(0, len(student_ids), 500):
                student_chunk = student_ids[student_offset:student_offset + 500]
                student_placeholders = ', '.join(['%s'] * len(student_chunk))
                self.cursor.execute(
                    f"""
                    SELECT component_id, student_id, mark, is_absent, remarks
                    FROM exam_component_marks
                    WHERE school_id = %s
                      AND component_id IN ({component_placeholders})
                      AND student_id IN ({student_placeholders})
                    """,
                    (
                        self.school_id, *component_chunk, *student_chunk,
                    ),
                )
                for mark in self.cursor.fetchall():
                    marks_by_component_student[
                        (str(mark['student_id']), mark['component_id'])
                    ] = mark

        results = {}
        for student_id in map(str, student_ids):
            for subject_id, components in components_by_subject.items():
                marks = {
                    component['id']: marks_by_component_student[
                        (student_id, component['id'])
                    ]
                    for component in components
                    if (student_id, component['id'])
                    in marks_by_component_student
                }
                try:
                    result = calculate_assessment(components, marks)
                except AssessmentConfigurationError as exc:
                    raise ExamManagementError(str(exc)) from exc
                component_states = [
                    (
                        'missing' if component['id'] not in marks
                        else 'absent' if marks[component['id']]['is_absent']
                        else 'missing' if marks[component['id']]['mark'] is None
                        else 'scored'
                    )
                    for component in components
                ]
                if all(state == 'absent' for state in component_states):
                    state = 'absent'
                elif any(state == 'scored' for state in component_states):
                    state = (
                        'scored'
                        if all(component_state == 'scored' for component_state in component_states)
                        else 'partial'
                    )
                elif all(state == 'missing' for state in component_states):
                    state = 'missing'
                else:
                    state = 'partial'
                results[(student_id, subject_id)] = {
                    'mark': float(result.percentage),
                    'is_absent': state == 'absent',
                    'grade': None,
                    'state': state,
                    'total_mark': float(result.total_mark),
                    'maximum_mark': float(result.maximum_mark),
                    'component_count': result.component_count,
                    'scored_components': result.scored_count,
                    'absent_components': result.absent_count,
                    'missing_components': result.missing_count,
                }
        return results

    def save_exam_component_marks_bulk(
        self,
        exam_id: int,
        class_id: int,
        subject_id: int,
        marks: List[Dict],
        actor_user_id: int,
    ) -> int:
        """Validate then atomically save a bounded component-mark batch."""
        if not marks:
            raise ExamManagementError("No component marks were provided.")
        if len(marks) > 1000:
            raise ExamManagementError(
                "A component-mark batch cannot contain more than 1,000 entries."
            )
        self.connection.begin()
        try:
            self.cursor.execute(
                """
                SELECT workflow_status, is_locked
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            status = exam.get('workflow_status') or (
                'locked' if exam.get('is_locked') else 'marks_open'
            )
            if status != 'marks_open' or exam.get('is_locked'):
                raise ExamManagementError(
                    f"Component marks can only be edited while marks entry is open "
                    f"(current state: {status})."
                )
            self.get_exam_subject(exam_id, class_id, subject_id)
            components = self.get_exam_assessment_components(
                exam_id, class_id, subject_id
            )
            if not components:
                raise ExamManagementError(
                    "This exam subject has no configured assessment components."
                )
            components_by_id = {
                component['id']: component for component in components
            }
            seen = set()
            prepared = []
            for row in marks:
                student_id = str(row.get('student_id', '')).strip()
                try:
                    component_id = int(row.get('component_id'))
                except (TypeError, ValueError) as exc:
                    raise ExamManagementError(
                        "Each mark needs a valid assessment component."
                    ) from exc
                if not student_id or component_id not in components_by_id:
                    raise ExamManagementError(
                        "Each mark needs an eligible student and a component assigned to this exam subject."
                    )
                key = (student_id, component_id)
                if key in seen:
                    raise ExamManagementError(
                        f"Duplicate component mark for student {student_id}."
                    )
                seen.add(key)
                class_for_student = self._assert_mark_target_is_valid(
                    exam_id, student_id, subject_id
                )
                if class_for_student != class_id:
                    raise ExamManagementError(
                        "Student is not enrolled in the selected exam class."
                    )
                is_absent = row.get('is_absent', False)
                if not isinstance(is_absent, bool):
                    raise ExamManagementError(
                        "Absent status must be true or false."
                    )
                raw_mark = row.get('mark')
                if is_absent and raw_mark not in (None, ''):
                    raise ExamManagementError(
                        "An absent component cannot also contain a numeric mark."
                    )
                if is_absent or raw_mark in (None, ''):
                    mark = None
                else:
                    try:
                        mark = Decimal(str(raw_mark))
                    except (InvalidOperation, TypeError, ValueError) as exc:
                        raise ExamManagementError(
                            "Component mark must be a valid number."
                        ) from exc
                    maximum = Decimal(
                        str(components_by_id[component_id]['maximum_mark'])
                    )
                    if not mark.is_finite() or mark < 0 or mark > maximum:
                        raise ExamManagementError(
                            f"Component mark must be between 0 and {maximum}."
                        )
                prepared.append((
                    student_id,
                    component_id,
                    mark,
                    is_absent,
                    str(row.get('remarks') or '')[:500],
                ))

            for student_id, component_id, mark, is_absent, remarks in prepared:
                self.cursor.execute(
                    """
                    SELECT mark, is_absent, remarks
                    FROM exam_component_marks
                    WHERE school_id = %s AND component_id = %s
                      AND student_id = %s
                    FOR UPDATE
                    """,
                    (self.school_id, component_id, student_id),
                )
                previous = self.cursor.fetchone()
                self.cursor.execute(
                    """
                    INSERT INTO exam_component_marks (
                        school_id, component_id, student_id, mark, is_absent,
                        remarks, created_by, updated_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        mark = VALUES(mark), is_absent = VALUES(is_absent),
                        remarks = VALUES(remarks), updated_by = VALUES(updated_by),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        self.school_id, component_id, student_id, mark,
                        is_absent, remarks, actor_user_id, actor_user_id,
                    ),
                )
                self._record_audit_event(
                    'exam_component_mark_saved',
                    'exam_component_mark',
                    f'{exam_id}:{student_id}:{component_id}',
                    old_values=(
                        {
                            'mark': previous.get('mark'),
                            'is_absent': bool(previous.get('is_absent')),
                            'remarks': previous.get('remarks'),
                        }
                        if previous else None
                    ),
                    new_values={
                        'mark': str(mark) if mark is not None else None,
                        'is_absent': is_absent,
                        'state': (
                            'absent' if is_absent
                            else 'missing' if mark is None
                            else 'scored'
                        ),
                        'remarks': remarks,
                    },
                )
            self.connection.commit()
            return len(prepared)
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, ExamManagementError):
                raise
            raise ExamManagementError(
                f"Failed to save component marks: {exc}"
            ) from exc

    def save_exam_workbook_component_marks(
        self,
        exam_id: int,
        class_id: int,
        marks: List[Dict],
        actor_user_id: int,
        source_sha256: str,
        row_count: int,
    ) -> Dict:
        """Atomically persist a fully validated multi-subject workbook."""
        if not marks:
            raise ExamManagementError("The workbook contains no component marks.")
        if len(marks) > 10000:
            raise ExamManagementError(
                "A workbook batch cannot contain more than 10,000 component marks."
            )
        if len(source_sha256) != 64 or any(
            character not in '0123456789abcdef' for character in source_sha256.lower()
        ):
            raise ExamManagementError("Workbook checksum is invalid.")
        self.connection.begin()
        try:
            self.cursor.execute(
                """
                SELECT workflow_status, is_locked
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            status = exam.get('workflow_status') or (
                'locked' if exam.get('is_locked') else 'marks_open'
            )
            if status != 'marks_open' or exam.get('is_locked'):
                raise ExamManagementError(
                    f"Workbook marks can only be imported while marks entry is open "
                    f"(current state: {status})."
                )
            self.get_exam_class_info(exam_id, class_id)
            self.cursor.execute(
                """
                SELECT id, subject_id, maximum_mark, is_required
                FROM exam_assessment_components
                WHERE school_id = %s AND exam_id = %s AND class_id = %s
                  AND is_active = TRUE
                """,
                (self.school_id, exam_id, class_id),
            )
            components = {
                row['id']: row for row in self.cursor.fetchall()
            }
            if not components:
                raise ExamManagementError(
                    "No assessment components are configured for this exam class."
                )

            prepared = []
            seen = set()
            checked_students = set()
            for row in marks:
                student_id = str(row.get('student_id') or '').strip()
                subject_id = row.get('subject_id')
                try:
                    component_id = int(row.get('component_id'))
                except (TypeError, ValueError) as exc:
                    raise ExamManagementError(
                        "Workbook contains an invalid component identifier."
                    ) from exc
                component = components.get(component_id)
                if not student_id or component is None:
                    raise ExamManagementError(
                        "Workbook contains a component outside this exam class."
                    )
                if component['subject_id'] != subject_id:
                    raise ExamManagementError(
                        "Workbook component does not belong to its listed subject."
                    )
                target = (student_id, component_id)
                if target in seen:
                    raise ExamManagementError(
                        f"Duplicate workbook mark for student {student_id}."
                    )
                seen.add(target)
                student_subject = (student_id, subject_id)
                if student_subject not in checked_students:
                    actual_class_id = self._assert_mark_target_is_valid(
                        exam_id, student_id, subject_id
                    )
                    if actual_class_id != class_id:
                        raise ExamManagementError(
                            f"Student {student_id} is not in the selected class."
                        )
                    checked_students.add(student_subject)
                is_absent = row.get('is_absent', False)
                if not isinstance(is_absent, bool):
                    raise ExamManagementError(
                        "Workbook absent state must be true or false."
                    )
                raw_mark = row.get('mark')
                if is_absent and raw_mark not in (None, ''):
                    raise ExamManagementError(
                        "An absent component cannot also contain a numeric mark."
                    )
                if is_absent or raw_mark in (None, ''):
                    mark = None
                else:
                    try:
                        mark = Decimal(str(raw_mark))
                    except (InvalidOperation, TypeError, ValueError) as exc:
                        raise ExamManagementError(
                            "Workbook component mark must be numeric."
                        ) from exc
                    maximum = Decimal(str(component['maximum_mark']))
                    if not mark.is_finite() or mark < 0 or mark > maximum:
                        raise ExamManagementError(
                            f"Component mark must be between 0 and {maximum}."
                        )
                prepared.append((
                    student_id,
                    component_id,
                    mark,
                    is_absent,
                    str(row.get('remarks') or '')[:500],
                ))

            self.cursor.execute(
                """
                INSERT INTO exam_import_batches (
                    school_id, exam_id, class_id, created_by, source_type,
                    source_sha256, row_count, mark_count, status
                )
                VALUES (%s, %s, %s, %s, 'xlsx_components', %s, %s, %s, 'applied')
                """,
                (
                    self.school_id, exam_id, class_id, actor_user_id,
                    source_sha256.lower(), row_count, len(prepared),
                ),
            )
            batch_id = self.cursor.lastrowid
            for student_id, component_id, mark, is_absent, remarks in prepared:
                self.cursor.execute(
                    """
                    SELECT mark, is_absent, remarks
                    FROM exam_component_marks
                    WHERE school_id = %s AND component_id = %s
                      AND student_id = %s
                    FOR UPDATE
                    """,
                    (self.school_id, component_id, student_id),
                )
                previous = self.cursor.fetchone()
                self.cursor.execute(
                    """
                    INSERT INTO exam_component_marks (
                        school_id, component_id, student_id, mark, is_absent,
                        remarks, created_by, updated_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        mark = VALUES(mark), is_absent = VALUES(is_absent),
                        remarks = VALUES(remarks), updated_by = VALUES(updated_by),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        self.school_id, component_id, student_id, mark,
                        is_absent, remarks, actor_user_id, actor_user_id,
                    ),
                )
                self._record_audit_event(
                    'exam_component_mark_imported',
                    'exam_component_mark',
                    f'{exam_id}:{student_id}:{component_id}',
                    old_values=(
                        {
                            'mark': previous.get('mark'),
                            'is_absent': bool(previous.get('is_absent')),
                            'remarks': previous.get('remarks'),
                        }
                        if previous else None
                    ),
                    new_values={
                        'mark': str(mark) if mark is not None else None,
                        'is_absent': is_absent,
                        'state': (
                            'absent' if is_absent
                            else 'missing' if mark is None
                            else 'scored'
                        ),
                        'remarks': remarks,
                        'batch_id': batch_id,
                    },
                )
            self._record_audit_event(
                'exam_component_workbook_imported',
                'exam_import_batch',
                batch_id,
                new_values={
                    'exam_id': exam_id,
                    'class_id': class_id,
                    'row_count': row_count,
                    'mark_count': len(prepared),
                    'source_sha256': source_sha256.lower(),
                },
            )
            self.connection.commit()
            return {'batch_id': batch_id, 'mark_count': len(prepared)}
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, ExamManagementError):
                raise
            raise ExamManagementError(
                f"Failed to import component workbook: {exc}"
            ) from exc

    # =========================================================================
    # 1. EXAM SERIES MANAGEMENT
    # =========================================================================

    @audit_log('create_exam_series')
    def create_exam_series(self, name: str, academic_year_id: int, term: int, created_by: int, class_ids: List[int] = None) -> int:
        """Create a new exam series and assign classes."""
        try:
            name = (name or "").strip()
            if not name:
                raise ExamManagementError("Exam series name is required.")
            class_ids = list(dict.fromkeys(class_ids or []))
            self._assert_academic_year_belongs_to_school(academic_year_id)
            self._assert_classes_belong_to_school(class_ids, academic_year_id)
            sql = """
                INSERT INTO exam_series (
                    name, academic_year_id, term, created_by, school_id,
                    workflow_status
                )
                VALUES (%s, %s, %s, %s, %s, 'draft')
            """
            self.cursor.execute(sql, (name, academic_year_id, term, created_by, self.school_id))
            exam_id = self.cursor.lastrowid

            sql_class = "INSERT INTO exam_classes (exam_id, class_id, school_id) VALUES (%s, %s, %s)"
            for cid in class_ids:
                self.cursor.execute(sql_class, (exam_id, cid, self.school_id))

            self._record_audit_event(
                'exam_created',
                'exam_series',
                exam_id,
                new_values={
                    'name': name,
                    'academic_year_id': academic_year_id,
                    'term': term,
                    'class_ids': class_ids,
                },
            )
            self.connection.commit()
            return exam_id
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error creating exam series: {str(e)}")
            raise ExamManagementError(f"Failed to create exam series: {str(e)}")

    def get_all_exams(self) -> List[Dict]:
        """Fetch all exam series for the active school."""
        sql = """
            SELECT e.*, ay.year as academic_year_name,
                   (
                       SELECT COUNT(DISTINCT ec.class_id)
                       FROM exam_classes ec
                       WHERE ec.exam_id = e.id AND ec.school_id = e.school_id
                   ) as class_count
            FROM exam_series e
            JOIN academic_years ay ON e.academic_year_id = ay.id AND e.school_id = ay.school_id
            WHERE e.school_id = %s
            ORDER BY e.created_at DESC, e.id DESC
        """
        self.cursor.execute(sql, (self.school_id,))
        return self.cursor.fetchall()

    def get_exam_series(self, exam_id: int) -> Optional[Dict]:
        """Fetch a single exam series with year details."""
        sql = """
            SELECT e.*, ay.year as academic_year_name, ay.is_current
            FROM exam_series e
            JOIN academic_years ay ON e.academic_year_id = ay.id AND e.school_id = ay.school_id
            WHERE e.id = %s AND e.school_id = %s
        """
        self.cursor.execute(sql, (exam_id, self.school_id))
        exam = self.cursor.fetchone()

        if exam:
            # Get assigned classes
            self.cursor.execute("""
                SELECT c.classID, c.display_name, c.academic_year_id, c.is_active
                FROM classes c
                JOIN exam_classes ec ON c.classID = ec.class_id AND c.school_id = ec.school_id
                WHERE ec.exam_id = %s AND ec.school_id = %s
            """, (exam_id, self.school_id))
            exam['classes'] = self.cursor.fetchall()

        return exam

    @audit_log('update_exam_series')
    def update_exam_series(self, exam_id: int, name: str, class_ids: List[int]) -> bool:
        """Update an unlocked exam's name and participating classes safely."""
        try:
            name = (name or "").strip()
            if not name:
                raise ExamManagementError("Exam series name is required.")
            class_ids = list(dict.fromkeys(class_ids or []))

            self.connection.begin()
            self.cursor.execute(
                """
                SELECT id, name, academic_year_id, is_locked, workflow_status
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            workflow_status = exam.get('workflow_status') or (
                'locked' if exam['is_locked'] else 'draft'
            )
            if workflow_status == 'locked':
                raise ExamManagementError("Unlock the exam series before editing it.")
            if workflow_status != 'draft':
                raise ExamManagementError(
                    "Only draft exam series can be edited."
                )

            self._assert_classes_belong_to_school(
                class_ids,
                exam['academic_year_id'],
                allow_inactive_exam_id=exam_id,
            )

            self.cursor.execute(
                "SELECT class_id FROM exam_classes WHERE exam_id = %s AND school_id = %s",
                (exam_id, self.school_id),
            )
            current_class_ids = {row['class_id'] for row in self.cursor.fetchall()}
            selected_class_ids = set(class_ids)
            removed_class_ids = current_class_ids - selected_class_ids

            if removed_class_ids:
                placeholders = ', '.join(['%s'] * len(removed_class_ids))
                self.cursor.execute(
                    f"""
                    SELECT DISTINCT ec.class_id, c.display_name
                    FROM exam_classes ec
                    JOIN classes c
                      ON c.classID = ec.class_id AND c.school_id = ec.school_id
                    JOIN class_allocation ca
                      ON ca.class_id = ec.class_id AND ca.school_id = ec.school_id
                    JOIN exam_marks em
                      ON em.student_id = ca.student_id
                     AND em.exam_id = ec.exam_id
                     AND em.school_id = ec.school_id
                    WHERE ec.exam_id = %s
                      AND ec.school_id = %s
                      AND ca.academic_year_id = %s
                      AND ec.class_id IN ({placeholders})
                    LIMIT 1
                    """,
                    (exam_id, self.school_id, exam['academic_year_id'], *sorted(removed_class_ids)),
                )
                marked_class = self.cursor.fetchone()
                if marked_class:
                    raise ExamManagementError(
                        f"Cannot remove {marked_class['display_name']} because marks have been recorded for that class."
                    )

            self.cursor.execute(
                "UPDATE exam_series SET name = %s WHERE id = %s AND school_id = %s",
                (name, exam_id, self.school_id),
            )

            for class_id in sorted(removed_class_ids):
                self.cursor.execute(
                    "DELETE FROM exam_classes WHERE exam_id = %s AND class_id = %s AND school_id = %s",
                    (exam_id, class_id, self.school_id),
                )
            for class_id in sorted(selected_class_ids - current_class_ids):
                self.cursor.execute(
                    "INSERT INTO exam_classes (exam_id, class_id, school_id) VALUES (%s, %s, %s)",
                    (exam_id, class_id, self.school_id),
                )

            self._record_audit_event(
                'exam_updated',
                'exam_series',
                exam_id,
                old_values={
                    'name': exam.get('name'),
                    'class_ids': sorted(current_class_ids),
                },
                new_values={
                    'name': name,
                    'class_ids': sorted(selected_class_ids),
                },
            )
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            if isinstance(e, ExamManagementError):
                raise
            raise ExamManagementError(f"Failed to update exam series: {str(e)}")

    @audit_log('update_exam_classes')
    def update_exam_classes(self, exam_id: int, class_ids: List[int]) -> bool:
        """Update participating classes while preserving exam edit safeguards."""
        exam = self.get_exam_series(exam_id)
        if not exam:
            raise ExamManagementError("Exam series not found for the active school.")
        return self.update_exam_series(exam_id, exam['name'], class_ids)

    def get_exam_classes(self, exam_id: int) -> List[Dict]:
        """Get all classes assigned to an exam."""
        self.cursor.execute("""
            SELECT c.classID, c.display_name, c.academic_year_id,
                   c.class_group_code, c.stream_code, c.is_active
            FROM classes c
            JOIN exam_classes ec ON c.classID = ec.class_id AND c.school_id = ec.school_id
            WHERE ec.exam_id = %s AND ec.school_id = %s
            ORDER BY c.display_name
        """, (exam_id, self.school_id))
        return self.cursor.fetchall()

    def get_exam_class_info(self, exam_id: int, class_id: int) -> Dict:
        return self._get_exam_class_details(exam_id, class_id)

    def get_exam_subject(self, exam_id: int, class_id: int, subject_id: int) -> Dict:
        subjects = self.get_exam_subjects_for_class(exam_id, class_id)
        subject = next((item for item in subjects if item['id'] == subject_id), None)
        if not subject:
            raise ExamManagementError("Subject is not allocated to an eligible student in this exam class.")
        return subject

    def get_exam_missing_marks_report(self, exam_id: int) -> List[Dict]:
        """Finds all students in classes assigned to an exam who are missing marks for their class subjects."""
        sql = """
            SELECT
                ec.class_id,
                c.display_name as class_name,
                s.subjName as subject_name,
                cs.subject_id,
                si.AdmNo,
                CONCAT(si.FName, ' ', si.SName) as student_name
            FROM exam_classes ec
            JOIN classes c ON ec.class_id = c.classID AND ec.school_id = c.school_id
            JOIN class_subjects cs ON c.classID = cs.class_id AND c.school_id = cs.school_id
            JOIN subjects s ON cs.subject_id = s.subjectNo AND cs.school_id = s.school_id
            JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE AND c.school_id = ca.school_id
            JOIN studentinfo si ON ca.student_id = si.AdmNo AND ca.school_id = si.school_id
            LEFT JOIN exam_marks em ON em.exam_id = ec.exam_id
                                    AND em.student_id = si.AdmNo
                                    AND em.subject_id = cs.subject_id
                                    AND em.school_id = ec.school_id
            WHERE ec.exam_id = %s AND ec.school_id = %s
              AND ca.academic_year_id = (
                  SELECT academic_year_id FROM exam_series
                  WHERE id = ec.exam_id AND school_id = ec.school_id
              )
              AND cs.is_active = TRUE
              AND (
                  EXISTS (
                      SELECT 1 FROM student_subjects ss
                      WHERE ss.class_allocation_id = ca.id
                        AND ss.subject_id = cs.subject_id
                        AND ss.school_id = ca.school_id
                        AND ss.is_active = TRUE
                  )
                  OR NOT EXISTS (
                      SELECT 1 FROM student_subjects ss
                      WHERE ss.class_allocation_id = ca.id
                        AND ss.school_id = ca.school_id
                        AND ss.is_active = TRUE
                  )
              )
              AND (em.id IS NULL OR (em.mark IS NULL AND em.is_absent = FALSE))
            ORDER BY c.display_name, s.subjName, si.AdmNo
        """
        self.cursor.execute(sql, (exam_id, self.school_id))
        return self.cursor.fetchall()

    # (Other methods kept for brevity, applying audit_log where needed)

    @audit_log('toggle_exam_lock')
    def transition_exam_workflow(
        self,
        exam_id: int,
        target_status: str,
        actor_user_id: int,
        reason: Optional[str] = None,
    ) -> str:
        """Apply a validated workflow transition to a school-owned exam."""
        try:
            return ExamWorkflowService(
                self.connection, self.school_id
            ).transition(
                exam_id,
                target_status,
                actor_user_id,
                reason=reason,
            )
        except ExamWorkflowError as exc:
            raise ExamManagementError(str(exc)) from exc

    def toggle_exam_lock(
        self,
        exam_id: int,
        lock: bool,
        reason: Optional[str] = None,
        actor_user_id: Optional[int] = None,
    ) -> bool:
        """Compatibility facade for the explicit publish/lock workflow transitions."""
        if actor_user_id is None and has_request_context():
            actor_user_id = session.get('userNo')
        if actor_user_id is None:
            raise ExamManagementError("An authenticated user is required.")
        self.transition_exam_workflow(
            exam_id,
            'locked' if lock else 'published',
            actor_user_id,
            reason,
        )
        return True

    @audit_log('save_exam_marks')
    def save_marks_bulk(self, exam_id: int, marks: List[Dict]) -> int:
        """Validate and save a set of marks atomically."""
        try:
            if not marks:
                raise ExamManagementError("No marks were provided.")

            self.connection.begin()
            self.cursor.execute(
                """
                SELECT id, is_locked, workflow_status
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            workflow_status = exam.get('workflow_status') or (
                'locked' if exam['is_locked'] else 'marks_open'
            )
            if workflow_status != 'marks_open' or exam['is_locked']:
                raise ExamManagementError(
                    f"Marks can only be edited while the exam is open for entry "
                    f"(current state: {workflow_status})."
                )

            prepared_marks = []
            seen_targets = set()
            checked_assessment_subjects = set()
            for row in marks:
                student_id = str(row.get('student_id', '')).strip()
                subject_id = row.get('subject_id')
                if not student_id or subject_id is None:
                    raise ExamManagementError("Each mark needs a student and subject.")
                target = (student_id, subject_id)
                if target in seen_targets:
                    raise ExamManagementError(
                        f"Duplicate mark for student {student_id} and subject {subject_id}."
                    )
                seen_targets.add(target)
                is_absent = row.get('is_absent', False)
                if not isinstance(is_absent, bool):
                    raise ExamManagementError("Absent status must be true or false.")
                mark = row.get('mark')
                if is_absent:
                    mark = None
                elif mark not in (None, ''):
                    try:
                        mark = float(mark)
                    except (TypeError, ValueError) as exc:
                        raise ExamManagementError("Mark must be a number between 0 and 100.") from exc
                    if not 0 <= mark <= 100:
                        raise ExamManagementError("Mark must be a number between 0 and 100.")
                else:
                    mark = None

                class_id = self._assert_mark_target_is_valid(
                    exam_id, student_id, subject_id
                )
                assessment_subject = (class_id, subject_id)
                if assessment_subject not in checked_assessment_subjects:
                    self.cursor.execute(
                        """
                        SELECT 1
                        FROM exam_assessment_components
                        WHERE school_id = %s AND exam_id = %s
                          AND class_id = %s AND subject_id = %s
                          AND is_active = TRUE
                        LIMIT 1
                        """,
                        (
                            self.school_id, exam_id, class_id, subject_id,
                        ),
                    )
                    if self.cursor.fetchone():
                        raise ExamManagementError(
                            "This subject uses assessment components. Enter marks on the component-mark page."
                        )
                    checked_assessment_subjects.add(assessment_subject)
                grade_id = None
                if not is_absent and mark is not None:
                    scale_id = self.get_effective_grading_scale_id(
                        exam_id, class_id
                    )
                    grade_rec = self.get_grade_for_mark(mark, scale_id)
                    if grade_rec:
                        grade_id = grade_rec['id']
                prepared_marks.append((
                    exam_id, student_id, subject_id, mark, grade_id, is_absent,
                    row.get('remarks', ''), row.get('ct_remarks', ''),
                    row.get('p_remarks', ''), self.school_id,
                ))

            sql = """
                INSERT INTO exam_marks (exam_id, student_id, subject_id, mark, grade_id, is_absent, remarks, ct_remarks, p_remarks, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    mark = VALUES(mark), grade_id = VALUES(grade_id), is_absent = VALUES(is_absent),
                    remarks = VALUES(remarks), ct_remarks = VALUES(ct_remarks), p_remarks = VALUES(p_remarks)
            """
            previous_marks = {}
            for offset in range(0, len(prepared_marks), 500):
                mark_chunk = prepared_marks[offset:offset + 500]
                pair_conditions = " OR ".join(
                    "(student_id = %s AND subject_id = %s)"
                    for _ in mark_chunk
                )
                pair_params = tuple(
                    value
                    for row in mark_chunk
                    for value in (row[1], row[2])
                )
                self.cursor.execute(
                    f"""
                    SELECT student_id, subject_id, mark, is_absent,
                           remarks, ct_remarks, p_remarks
                    FROM exam_marks
                    WHERE exam_id = %s AND school_id = %s
                      AND ({pair_conditions})
                    """,
                    (exam_id, self.school_id, *pair_params),
                )
                previous_marks.update({
                    (str(row['student_id']), row['subject_id']): row
                    for row in self.cursor.fetchall()
                })

            for values in prepared_marks:
                student_id = str(values[1])
                subject_id = values[2]
                previous = previous_marks.get((student_id, subject_id))
                old_values = None
                if previous is not None:
                    old_values = {
                        'mark': previous['mark'],
                        'is_absent': bool(previous['is_absent']),
                        'remarks': previous.get('remarks'),
                        'ct_remarks': previous.get('ct_remarks'),
                        'p_remarks': previous.get('p_remarks'),
                        'state': (
                            'absent' if previous['is_absent']
                            else 'missing' if previous['mark'] is None
                            else 'scored'
                        ),
                    }
                new_values = {
                    'mark': values[3],
                    'is_absent': bool(values[5]),
                    'remarks': values[6],
                    'ct_remarks': values[7],
                    'p_remarks': values[8],
                    'state': (
                        'absent' if values[5]
                        else 'missing' if values[3] is None
                        else 'scored'
                    ),
                }
                self._record_audit_event(
                    'exam_mark_saved',
                    'exam_mark',
                    f"{exam_id}:{student_id}:{subject_id}",
                    old_values=old_values,
                    new_values=new_values,
                )
                self.cursor.execute(sql, values)
            self.connection.commit()
            return len(prepared_marks)
        except Exception as e:
            self.connection.rollback()
            if isinstance(e, ExamManagementError):
                raise
            raise ExamManagementError(f"Failed to save marks: {str(e)}")

    def save_mark(self, exam_id: int, student_id: str, subject_id: int,
                  mark: Optional[float] = None, is_absent: bool = False,
                  remarks: str = "", ct_remarks: str = "", p_remarks: str = "") -> bool:
        """Record or update one student's mark using the atomic bulk-save path."""
        self.save_marks_bulk(exam_id, [{
            'student_id': student_id,
            'subject_id': subject_id,
            'mark': mark,
            'is_absent': is_absent,
            'remarks': remarks,
            'ct_remarks': ct_remarks,
            'p_remarks': p_remarks,
        }])
        return True

    def override_exam_subject_remark(
        self,
        exam_id: int,
        student_id: str,
        subject_id: int,
        remarks: str,
        reason: str,
        actor_user_id: int,
    ) -> bool:
        """Apply a reasoned, auditable subject-remark override before lock."""
        reason = (reason or '').strip()
        remarks = (remarks or '').strip()
        if len(reason) < 10 or len(reason) > 500:
            raise ExamManagementError(
                "A remark-override reason of 10 to 500 characters is required."
            )
        if len(remarks) > 500:
            raise ExamManagementError("Subject remarks cannot exceed 500 characters.")
        self.connection.begin()
        try:
            self.cursor.execute(
                """
                SELECT workflow_status, is_locked
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            status = exam.get('workflow_status') or (
                'locked' if exam.get('is_locked') else 'marks_open'
            )
            if status != 'marks_open' or exam.get('is_locked'):
                raise ExamManagementError(
                    "Subject remarks can only be overridden while marks entry is open."
                )
            self._assert_mark_target_is_valid(exam_id, student_id, subject_id)
            self.cursor.execute(
                """
                SELECT mark, grade_id, is_absent, remarks, ct_remarks, p_remarks
                FROM exam_marks
                WHERE exam_id = %s AND student_id = %s
                  AND subject_id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, student_id, subject_id, self.school_id),
            )
            previous = self.cursor.fetchone()
            old_remarks = previous.get('remarks') if previous else None
            if (old_remarks or '') == remarks:
                raise ExamManagementError("The new remark matches the current remark.")
            self.cursor.execute(
                """
                INSERT INTO exam_marks (
                    exam_id, student_id, subject_id, mark, grade_id, is_absent,
                    remarks, ct_remarks, p_remarks, school_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE remarks = VALUES(remarks)
                """,
                (
                    exam_id,
                    student_id,
                    subject_id,
                    previous.get('mark') if previous else None,
                    previous.get('grade_id') if previous else None,
                    previous.get('is_absent', False) if previous else False,
                    remarks,
                    previous.get('ct_remarks') if previous else None,
                    previous.get('p_remarks') if previous else None,
                    self.school_id,
                ),
            )
            self._record_audit_event(
                'exam_subject_remark_overridden',
                'exam_mark',
                f'{exam_id}:{student_id}:{subject_id}',
                old_values={'remarks': old_remarks},
                new_values={'remarks': remarks},
                reason=reason,
            )
            self.connection.commit()
            return True
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, ExamManagementError):
                raise
            raise ExamManagementError(
                f"Failed to override subject remark: {exc}"
            ) from exc

    def get_mark_feedback(
        self,
        exam_id: int,
        student_id: str,
        subject_id: int,
        mark: Optional[float],
        is_absent: bool = False,
    ) -> Dict:
        """Return the grade and standard remarks associated with a saved score."""
        if is_absent or mark in (None, ''):
            return {
                'grade': None,
                'remarks': None,
                'ct_remarks': None,
                'p_remarks': None,
            }
        class_id = self._assert_mark_target_is_valid(
            exam_id, student_id, subject_id
        )
        scale_id = self.get_effective_grading_scale_id(exam_id, class_id)
        grade = self.get_grade_for_mark(float(mark), scale_id)
        return {
            'grade': grade.get('grade') if grade else None,
            'remarks': grade.get('remarks') if grade else None,
            'ct_remarks': grade.get('class_teacher_remarks') if grade else None,
            'p_remarks': grade.get('principal_remarks') if grade else None,
        }

    @audit_log('create_grading_scale')
    def create_grading_scale(self, name: str, description: str = "", is_default: bool = False) -> int:
        try:
            self.clear_caches()
            self.connection.begin()
            previous_defaults = []
            if is_default:
                self.cursor.execute(
                    """
                    SELECT id, name
                    FROM grading_scales
                    WHERE is_default = TRUE AND school_id = %s
                    FOR UPDATE
                    """,
                    (self.school_id,),
                )
                previous_defaults = self.cursor.fetchall()
                self.cursor.execute("UPDATE grading_scales SET is_default = FALSE WHERE school_id = %s", (self.school_id,))
            sql = "INSERT INTO grading_scales (name, description, is_default, school_id) VALUES (%s, %s, %s, %s)"
            self.cursor.execute(sql, (name, description, is_default, self.school_id))
            scale_id = self.cursor.lastrowid
            self._record_audit_event(
                'grading_scale_created',
                'grading_scale',
                scale_id,
                old_values={
                    'default_scales': previous_defaults,
                },
                new_values={
                    'name': name,
                    'description': description,
                    'is_default': bool(is_default),
                },
            )
            self.connection.commit()
            return scale_id
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to create scale: {str(e)}")

    @audit_log('save_grading_details')
    def save_grading_details(self, scale_id: int, grades: List[Dict]) -> bool:
        try:
            self.clear_caches()
            self._assert_grading_scale_belongs_to_school(scale_id)
            if not grades:
                raise ExamManagementError("A grading scale must contain at least one grade.")
            normalized_grades = []
            seen_names = set()
            for row in grades:
                name = str(row.get('grade', '')).strip()
                try:
                    minimum = Decimal(str(row['min_mark']))
                    maximum = Decimal(str(row['max_mark']))
                    points = int(row.get('points') or 0)
                except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                    raise ExamManagementError("Each grade needs valid mark boundaries and points.") from exc
                if not name:
                    raise ExamManagementError("Grade names cannot be empty.")
                if name.casefold() in seen_names:
                    raise ExamManagementError(f"Grade '{name}' is duplicated.")
                if minimum < 0 or maximum > 100 or minimum > maximum:
                    raise ExamManagementError(
                        f"Grade '{name}' must have boundaries between 0 and 100 with minimum not exceeding maximum."
                    )
                seen_names.add(name.casefold())
                normalized_grades.append({
                    **row,
                    'grade': name,
                    'min_mark': minimum,
                    'max_mark': maximum,
                    'points': points,
                })

            normalized_grades.sort(key=lambda row: row['min_mark'])
            for previous, current in zip(normalized_grades, normalized_grades[1:]):
                if current['min_mark'] <= previous['max_mark']:
                    raise ExamManagementError(
                        f"Grade ranges for '{previous['grade']}' and '{current['grade']}' overlap."
                    )

            self.connection.begin()
            self.cursor.execute(
                """
                SELECT grade, min_mark, max_mark, points, remarks,
                       class_teacher_remarks, principal_remarks
                FROM grading_details
                WHERE scale_id = %s AND school_id = %s
                ORDER BY min_mark, id
                FOR UPDATE
                """,
                (scale_id, self.school_id),
            )
            previous_grades = self.cursor.fetchall()
            self.cursor.execute("DELETE FROM grading_details WHERE scale_id = %s AND school_id = %s", (scale_id, self.school_id))
            sql = "INSERT INTO grading_details (scale_id, grade, min_mark, max_mark, points, remarks, class_teacher_remarks, principal_remarks, school_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            for grade in normalized_grades:
                self.cursor.execute(sql, (
                    scale_id,
                    grade['grade'],
                    grade['min_mark'],
                    grade['max_mark'],
                    grade['points'],
                    grade.get('remarks', ''),
                    grade.get('class_teacher_remarks', ''),
                    grade.get('principal_remarks', ''),
                    self.school_id,
                ))
            self._record_audit_event(
                'grading_details_updated',
                'grading_scale',
                scale_id,
                old_values={'grades': previous_grades},
                new_values={'grades': normalized_grades},
            )
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            if isinstance(e, ExamManagementError):
                raise
            raise ExamManagementError(f"Failed to save grades: {str(e)}")

    @audit_log('assign_grading_scales')
    def assign_scales_to_classes(
        self,
        assignments: Dict[int, Optional[int]],
    ) -> bool:
        try:
            self.clear_caches()
            if not assignments:
                raise ExamManagementError("Select at least one class to update.")

            class_ids = list(assignments)
            self.connection.begin()
            self._assert_classes_belong_to_school(class_ids)
            for scale_id in set(assignments.values()):
                self._assert_grading_scale_belongs_to_school(scale_id)

            placeholders = ', '.join(['%s'] * len(class_ids))
            self.cursor.execute(
                f"""
                SELECT classID, grading_scale_id
                FROM classes
                WHERE school_id = %s AND classID IN ({placeholders})
                FOR UPDATE
                """,
                (self.school_id, *class_ids),
            )
            previous_assignments = {
                row['classID']: row['grading_scale_id']
                for row in self.cursor.fetchall()
            }
            for class_id, scale_id in assignments.items():
                self.cursor.execute(
                    """
                    UPDATE classes
                    SET grading_scale_id = %s
                    WHERE classID = %s AND school_id = %s
                    """,
                    (scale_id, class_id, self.school_id),
                )
                previous_scale_id = previous_assignments.get(class_id)
                if previous_scale_id != scale_id:
                    self._record_audit_event(
                        'class_grading_scale_assigned',
                        'class',
                        class_id,
                        old_values={'grading_scale_id': previous_scale_id},
                        new_values={'grading_scale_id': scale_id},
                    )
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            if isinstance(e, ExamManagementError):
                raise
            raise ExamManagementError(f"Failed to assign scale: {str(e)}")

    def assign_scale_to_class(self, class_id: int, scale_id: Optional[int]) -> bool:
        return self.assign_scales_to_classes({class_id: scale_id})

    def assign_exam_grading_scales(
        self,
        exam_id: int,
        assignments: Dict[int, Optional[int]],
        actor_user_id: int,
    ) -> bool:
        """Set or clear class-level scale overrides for one draft exam."""
        self.clear_caches()
        if not assignments:
            raise ExamManagementError("Select at least one participating class.")
        self.connection.begin()
        try:
            self.cursor.execute(
                """
                SELECT workflow_status, is_locked
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            status = exam.get('workflow_status') or (
                'locked' if exam.get('is_locked') else 'marks_open'
            )
            if status != 'draft':
                raise ExamManagementError(
                    "Exam-specific grading scales can only be changed while the exam is a draft."
                )

            for class_id, scale_id in assignments.items():
                self._get_exam_class_details(exam_id, class_id)
                self._assert_grading_scale_belongs_to_school(scale_id)
                self.cursor.execute(
                    """
                    SELECT grading_scale_id
                    FROM exam_grading_overrides
                    WHERE school_id = %s AND exam_id = %s AND class_id = %s
                    FOR UPDATE
                    """,
                    (self.school_id, exam_id, class_id),
                )
                current = self.cursor.fetchone()
                previous_scale_id = (
                    current['grading_scale_id'] if current else None
                )
                if previous_scale_id == scale_id:
                    continue
                if scale_id is None:
                    self.cursor.execute(
                        """
                        DELETE FROM exam_grading_overrides
                        WHERE school_id = %s AND exam_id = %s AND class_id = %s
                        """,
                        (self.school_id, exam_id, class_id),
                    )
                else:
                    self.cursor.execute(
                        """
                        INSERT INTO exam_grading_overrides (
                            school_id, exam_id, class_id, grading_scale_id,
                            created_by
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            grading_scale_id = VALUES(grading_scale_id),
                            created_by = VALUES(created_by)
                        """,
                        (
                            self.school_id,
                            exam_id,
                            class_id,
                            scale_id,
                            actor_user_id,
                        ),
                    )
                self._record_audit_event(
                    'exam_grading_scale_changed',
                    'exam_series_class',
                    f'{exam_id}:{class_id}',
                    old_values={'grading_scale_id': previous_scale_id},
                    new_values={'grading_scale_id': scale_id},
                )
            self.connection.commit()
            return True
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, ExamManagementError):
                raise
            raise ExamManagementError(
                f"Failed to assign exam grading scales: {exc}"
            ) from exc

    # Implementation of other helper methods from previous version...
    def get_class_grading_scale_id(self, class_id: int) -> Optional[int]:
        if class_id in self._class_scale_cache:
            return self._class_scale_cache[class_id]
        self.cursor.execute("SELECT grading_scale_id FROM classes WHERE classID = %s AND school_id = %s", (class_id, self.school_id))
        res = self.cursor.fetchone()
        scale_id = res['grading_scale_id'] if res else None
        self._class_scale_cache[class_id] = scale_id
        return scale_id

    def get_effective_grading_scale_id(
        self,
        exam_id: int,
        class_id: int,
    ) -> Optional[int]:
        """Resolve exam override, class assignment, then school default."""
        cache_key = (exam_id, class_id)
        if cache_key in self._effective_scale_cache:
            return self._effective_scale_cache[cache_key]

        self.cursor.execute(
            """
            SELECT grading_scale_id
            FROM exam_grading_overrides
            WHERE school_id = %s AND exam_id = %s AND class_id = %s
            """,
            (self.school_id, exam_id, class_id),
        )
        override = self.cursor.fetchone()
        if override:
            scale_id = override['grading_scale_id']
        else:
            class_scale_id = self.get_class_grading_scale_id(class_id)
            if class_scale_id is not None:
                scale_id = class_scale_id
            else:
                self.cursor.execute(
                    """
                    SELECT id
                    FROM grading_scales
                    WHERE school_id = %s AND is_default = TRUE
                    ORDER BY id
                    LIMIT 1
                    """,
                    (self.school_id,),
                )
                default_scale = self.cursor.fetchone()
                scale_id = default_scale['id'] if default_scale else None

        self._effective_scale_cache[cache_key] = scale_id
        return scale_id

    def _get_all_grading_details_for_scale(self, scale_id: Optional[int]) -> List[Dict]:
        if scale_id in self._grading_details_cache:
            return self._grading_details_cache[scale_id]

        if scale_id is not None:
            self.cursor.execute(
                "SELECT * FROM grading_details WHERE scale_id = %s AND school_id = %s ORDER BY min_mark ASC",
                (scale_id, self.school_id)
            )
            details = self.cursor.fetchall()
        else:
            self.cursor.execute(
                """
                SELECT gd.* FROM grading_details gd
                JOIN grading_scales gs ON gd.scale_id = gs.id AND gd.school_id = gs.school_id
                WHERE gs.is_default = TRUE AND gd.school_id = %s
                ORDER BY gd.min_mark ASC
                """,
                (self.school_id,)
            )
            details = self.cursor.fetchall()

        self._grading_details_cache[scale_id] = details
        return details

    def get_grade_for_mark(self, mark: Optional[float], scale_id: Optional[int] = None) -> Optional[Dict]:
        if mark is None:
            return None
        fmark = float(mark)
        details = self._get_all_grading_details_for_scale(scale_id)
        for gd in details:
            if float(gd['min_mark']) <= fmark <= float(gd['max_mark']):
                return gd
        return None

    def get_marks_for_class_subject(
        self,
        exam_id: int,
        class_id: int,
        subject_id: int,
        *,
        search_term: Optional[str] = None,
        page: int = 1,
        page_size: Optional[int] = None,
    ) -> List[Dict]:
        self._assert_exam_belongs_to_school(exam_id)
        class_info = self._get_exam_class_details(exam_id, class_id)
        self.get_exam_subject(exam_id, class_id, subject_id)
        if page < 1:
            raise ExamManagementError("Page number must be positive.")
        if page_size is not None and not 1 <= page_size <= 200:
            raise ExamManagementError("Page size must be between 1 and 200.")
        normalized_search = (search_term or '').strip()[:100]
        sql = """
            SELECT s.AdmNo, s.FName, s.SName as LName, m.mark, m.is_absent, gd.grade, m.remarks, m.ct_remarks, m.p_remarks
            FROM class_allocation ca
            JOIN studentinfo s ON s.AdmNo = ca.student_id AND s.school_id = ca.school_id
            LEFT JOIN exam_marks m ON s.AdmNo = m.student_id AND m.exam_id = %s AND m.subject_id = %s AND s.school_id = m.school_id
            LEFT JOIN grading_details gd ON m.grade_id = gd.id AND m.school_id = gd.school_id
            WHERE ca.class_id = %s AND ca.academic_year_id = %s
              AND ca.is_current = TRUE AND ca.school_id = %s
              AND (
                  EXISTS (
                      SELECT 1 FROM student_subjects ss
                      WHERE ss.class_allocation_id = ca.id
                        AND ss.subject_id = %s
                        AND ss.school_id = ca.school_id
                        AND ss.is_active = TRUE
                  )
                  OR NOT EXISTS (
                      SELECT 1 FROM student_subjects ss
                      WHERE ss.class_allocation_id = ca.id
                        AND ss.school_id = ca.school_id
                        AND ss.is_active = TRUE
                  )
            )
        """
        params = [
            exam_id, subject_id, class_id,
            class_info['exam_academic_year_id'], self.school_id, subject_id,
        ]
        if normalized_search:
            sql += """
             AND (
                 CAST(s.AdmNo AS CHAR) LIKE %s
                 OR s.FName LIKE %s
                 OR s.SName LIKE %s
             )
            """
            search_pattern = f'%{normalized_search}%'
            params.extend([search_pattern, search_pattern, search_pattern])
        sql += " ORDER BY s.FName, s.SName, s.AdmNo"
        if page_size is not None:
            sql += " LIMIT %s OFFSET %s"
            params.extend([page_size, (page - 1) * page_size])
        self.cursor.execute(
            sql,
            tuple(params),
        )
        rows = self.cursor.fetchall()
        scale_id = self.get_effective_grading_scale_id(exam_id, class_id)
        for row in rows:
            if row['mark'] is None or row['is_absent']:
                row['grade'] = None
                continue
            grade = self.get_grade_for_mark(float(row['mark']), scale_id)
            row['grade'] = grade['grade'] if grade else None
            if row['ct_remarks'] in (None, '') and grade:
                row['ct_remarks'] = grade.get('class_teacher_remarks')
            if row['p_remarks'] in (None, '') and grade:
                row['p_remarks'] = grade.get('principal_remarks')
            if row['remarks'] in (None, '') and grade:
                row['remarks'] = grade.get('remarks')
        return rows

    def count_exam_eligible_students(
        self,
        exam_id: int,
        class_id: int,
        subject_id: int,
        *,
        search_term: Optional[str] = None,
    ) -> int:
        self._assert_exam_belongs_to_school(exam_id)
        class_info = self._get_exam_class_details(exam_id, class_id)
        self.get_exam_subject(exam_id, class_id, subject_id)
        sql = """
            SELECT COUNT(*) AS total
            FROM class_allocation ca
            JOIN studentinfo s
              ON s.AdmNo = ca.student_id AND s.school_id = ca.school_id
            WHERE ca.class_id = %s AND ca.academic_year_id = %s
              AND ca.is_current = TRUE AND ca.school_id = %s
              AND (
                  EXISTS (
                      SELECT 1 FROM student_subjects ss
                      WHERE ss.class_allocation_id = ca.id
                        AND ss.subject_id = %s
                        AND ss.school_id = ca.school_id
                        AND ss.is_active = TRUE
                  )
                  OR NOT EXISTS (
                      SELECT 1 FROM student_subjects ss
                      WHERE ss.class_allocation_id = ca.id
                        AND ss.school_id = ca.school_id
                        AND ss.is_active = TRUE
                  )
              )
        """
        params = [
            class_id,
            class_info['exam_academic_year_id'],
            self.school_id,
            subject_id,
        ]
        normalized_search = (search_term or '').strip()[:100]
        if normalized_search:
            sql += """
              AND (
                  CAST(s.AdmNo AS CHAR) LIKE %s
                  OR s.FName LIKE %s
                  OR s.SName LIKE %s
              )
            """
            search_pattern = f'%{normalized_search}%'
            params.extend([search_pattern, search_pattern, search_pattern])
        self.cursor.execute(sql, tuple(params))
        return int((self.cursor.fetchone() or {}).get('total', 0))

    def _get_class_marks_bulk(
        self,
        exam_id: int,
        class_id: int,
        academic_year_id: int,
        scale_id: Optional[int],
    ) -> Dict[str, Dict[int, Dict]]:
        self.cursor.execute(
            """
            SELECT m.student_id AS AdmNo, m.subject_id, m.mark, m.is_absent,
                   m.remarks, m.ct_remarks, m.p_remarks
            FROM class_allocation ca
            JOIN exam_marks m
              ON m.student_id = ca.student_id AND m.exam_id = %s AND m.school_id = ca.school_id
            WHERE ca.class_id = %s AND ca.academic_year_id = %s
              AND ca.is_current = TRUE AND ca.school_id = %s
            """,
            (exam_id, class_id, academic_year_id, self.school_id),
        )
        raw_marks = self.cursor.fetchall()
        marks_map = {}
        for m in raw_marks:
            sid = str(m['AdmNo'])
            sub_id = m['subject_id']
            mark_val = m['mark']
            is_absent = bool(m['is_absent'])
            if mark_val is not None and not is_absent:
                grade_rec = self.get_grade_for_mark(float(mark_val), scale_id)
                grade = grade_rec['grade'] if grade_rec else None
                ct_remarks = m['ct_remarks'] or (grade_rec.get('class_teacher_remarks') if grade_rec else None)
                p_remarks = m['p_remarks'] or (grade_rec.get('principal_remarks') if grade_rec else None)
                remarks = m['remarks'] or (grade_rec.get('remarks') if grade_rec else None)
            else:
                grade = None
                ct_remarks = m['ct_remarks']
                p_remarks = m['p_remarks']
                remarks = m['remarks']

            marks_map.setdefault(sid, {})[sub_id] = {
                'AdmNo': m['AdmNo'],
                'mark': mark_val,
                'is_absent': is_absent,
                'grade': grade,
                'remarks': remarks,
                'ct_remarks': ct_remarks,
                'p_remarks': p_remarks,
            }
        return marks_map

    def get_class_tabulation(self, exam_id: int, class_id: int) -> Dict:
        class_info = self._get_exam_class_details(exam_id, class_id)
        subjects = self.get_exam_subjects_for_class(exam_id, class_id)
        self.cursor.execute(
            """
            SELECT s.AdmNo, s.FName, s.SName as LName, ca.id as allocation_id
            FROM studentinfo s
            JOIN class_allocation ca
              ON s.AdmNo = ca.student_id AND s.school_id = ca.school_id
            WHERE ca.class_id = %s AND ca.academic_year_id = %s
              AND ca.is_current = TRUE AND ca.school_id = %s
            ORDER BY s.FName, s.SName, s.AdmNo
            """,
            (class_id, class_info['exam_academic_year_id'], self.school_id),
        )
        students = self.cursor.fetchall()
        self.cursor.execute(
            """
            SELECT ss.class_allocation_id, ss.subject_id
            FROM student_subjects ss
            JOIN class_allocation ca
              ON ca.id = ss.class_allocation_id AND ca.school_id = ss.school_id
            WHERE ca.class_id = %s AND ca.academic_year_id = %s
              AND ca.is_current = TRUE AND ca.school_id = %s
              AND ss.is_active = TRUE
            """,
            (class_id, class_info['exam_academic_year_id'], self.school_id),
        )
        enrollment_rows = self.cursor.fetchall()
        enrolled_by_allocation = {}
        for enrollment in enrollment_rows:
            enrolled_by_allocation.setdefault(
                enrollment['class_allocation_id'], set()
            ).add(enrollment['subject_id'])

        scale_id = self.get_effective_grading_scale_id(exam_id, class_id)

        if 'get_marks_for_class_subject' in self.__dict__:
            marks_map = {}
            for subject in subjects:
                subject_marks = self.get_marks_for_class_subject(
                    exam_id, class_id, subject['id']
                )
                for mark in subject_marks:
                    marks_map.setdefault(str(mark['AdmNo']), {})[subject['id']] = mark
        else:
            marks_map = self._get_class_marks_bulk(
                exam_id, class_id, class_info['exam_academic_year_id'], scale_id
            )

        component_results = self._get_component_results_for_class(
            exam_id,
            class_id,
            [subject['id'] for subject in subjects],
            [str(student['AdmNo']) for student in students],
        )
        for (student_id, subject_id), component_result in component_results.items():
            mark_value = (
                None
                if component_result['scored_components'] == 0
                else component_result['mark']
            )
            grade_rec = (
                self.get_grade_for_mark(mark_value, scale_id)
                if mark_value is not None else None
            )
            marks_map.setdefault(student_id, {})[subject_id] = {
                **component_result,
                'mark': mark_value,
                'grade': grade_rec['grade'] if grade_rec else None,
            }
        tabulation = []
        for s in students:
            sid = str(s['AdmNo'])
            row = {
                'admno': s['AdmNo'],
                'name': f"{s['FName']} {s['LName']}",
                'class_name': class_info['display_name'],
                'marks': [],
                'total': 0.0,
            }
            enrolled_subject_ids = enrolled_by_allocation.get(
                s.get('allocation_id'), set()
            )
            eligible_subjects = [
                subject for subject in subjects
                if not enrolled_subject_ids or subject['id'] in enrolled_subject_ids
            ]
            eligible_subject_ids = {
                subject['id'] for subject in eligible_subjects
            }
            numeric_count = 0
            absent_count = 0
            missing_count = 0
            for sub in subjects:
                if sub['id'] not in eligible_subject_ids:
                    row['marks'].append({
                        'subject_id': sub['id'], 'mark': None,
                        'grade': '-', 'is_absent': False, 'state': 'ineligible',
                    })
                    continue
                m = marks_map.get(sid, {}).get(sub['id'])
                if m:
                    mark_value = m['mark']
                    state = m.get('state') or (
                        'absent' if m['is_absent']
                        else 'scored' if mark_value is not None
                        else 'missing'
                    )
                    if state == 'absent':
                        row['marks'].append({
                            'subject_id': sub['id'], 'mark': None,
                            'grade': '-', 'is_absent': True, 'state': state,
                        })
                        absent_count += 1
                    elif state == 'missing':
                        row['marks'].append({
                            'subject_id': sub['id'], 'mark': None,
                            'grade': '-', 'is_absent': False, 'state': state,
                        })
                        missing_count += 1
                    else:
                        row['marks'].append({
                            'subject_id': sub['id'], 'mark': mark_value,
                            'grade': m['grade'] or '-', 'is_absent': False,
                            'state': state,
                        })
                        if mark_value is not None:
                            row['total'] += float(mark_value)
                            numeric_count += 1
                        else:
                            missing_count += 1
                else:
                    row['marks'].append({
                        'subject_id': sub['id'], 'mark': None,
                        'grade': '-', 'is_absent': False, 'state': 'missing',
                    })
                    missing_count += 1
            row['eligible_subjects'] = len(eligible_subjects)
            row['numeric_subjects'] = numeric_count
            row['absent_subjects'] = absent_count
            row['missing_subjects'] = missing_count
            row['average'] = (
                row['total'] / len(eligible_subjects)
                if eligible_subjects else 0
            )
            grade_rec = (
                self.get_grade_for_mark(row['average'], scale_id)
                if eligible_subjects else None
            )
            row['grade'] = grade_rec['grade'] if grade_rec else '-'
            tabulation.append(row)
        tabulation.sort(key=lambda row: (
            row['eligible_subjects'] == 0,
            -row['average'],
            -row['total'],
            str(row['admno']),
        ))
        ranked_rows = rank_rows(
            [row for row in tabulation if row['eligible_subjects'] > 0],
            'average',
            style=RankingStyle.COMPETITION,
            missing_policy='missing',
        )
        for ranked_row in ranked_rows:
            ranked_row.row['rank'] = ranked_row.rank
        for row in tabulation:
            if row['eligible_subjects'] == 0:
                row['rank'] = '-'

        subject_stats = []
        eligible_mark_count = 0
        entered_mark_count = 0
        for subject in subjects:
            eligible_students = [
                student for student in students
                if not enrolled_by_allocation.get(student.get('allocation_id'))
                or subject['id'] in enrolled_by_allocation[
                    student.get('allocation_id')
                ]
            ]
            eligible_mark_count += len(eligible_students)
            entered_mark_count += sum(
                (mark := marks_map.get(str(student['AdmNo']), {}).get(subject['id']))
                is not None
                and (
                    mark['mark'] is not None
                    or bool(mark['is_absent'])
                    or (
                        mark.get('component_count', 0) > 0
                        and mark.get('scored_components', 0)
                            + mark.get('absent_components', 0)
                            == mark['component_count']
                    )
                )
                for student in eligible_students
            )
            eligible_count = len(eligible_students)
            subject_marks = [
                marks_map.get(str(student['AdmNo']), {}).get(subject['id'])
                for student in eligible_students
            ]
            scores = [
                mark['mark']
                for mark in subject_marks
                if mark is not None
                and not mark['is_absent']
                and mark['mark'] is not None
                and mark.get('state') != 'missing'
            ]
            average = (
                sum(float(score) for score in scores) / eligible_count
                if eligible_count else 0
            )
            grade = (
                self.get_grade_for_mark(average, scale_id)
                if eligible_count else None
            )
            statistics = describe_eligible_scores(
                (
                    0
                    if mark is None or mark['is_absent'] or mark['mark'] is None
                    else float(mark['mark'])
                    for mark in subject_marks
                ),
                grade_values=(
                    mark.get('grade')
                    for mark in subject_marks
                    if mark is not None
                    and not mark['is_absent']
                    and mark['mark'] is not None
                    and mark.get('state') != 'missing'
                ),
            )
            subject_stats.append({
                'subject_id': subject['id'],
                'name': subject['name'],
                'code': subject['code'],
                'count': len(scores),
                'eligible_count': eligible_count,
                'entered_count': sum(
                    mark is not None
                    and (
                        mark['mark'] is not None
                        or bool(mark['is_absent'])
                        or (
                            mark.get('component_count', 0) > 0
                            and mark.get('scored_components', 0)
                                + mark.get('absent_components', 0)
                                == mark['component_count']
                        )
                    )
                    for mark in subject_marks
                ),
                'absent_count': sum(
                    mark is not None and bool(mark['is_absent'])
                    for mark in subject_marks
                ),
                'absent_component_count': sum(
                    mark.get('absent_components', 0)
                    for mark in subject_marks if mark is not None
                ),
                'missing_component_count': sum(
                    mark.get('missing_components', 0)
                    for mark in subject_marks if mark is not None
                ),
                'missing_count': sum(
                    mark is None or (
                        mark.get('state') == 'missing'
                        or (
                            mark.get('component_count', 0) > 0
                            and mark.get('missing_components', 0) > 0
                        )
                        or (
                            mark['mark'] is None and not mark['is_absent']
                            and mark.get('scored_components', 0) == 0
                            and mark.get('absent_components', 0) == 0
                        )
                    )
                    for mark in subject_marks
                ),
                'average': average,
                'grade': grade['grade'] if grade else '-',
                'statistics': statistics,
            })
        return {
            'class_info': class_info,
            'subjects': subjects,
            'subject_stats': subject_stats,
            'tabulation': tabulation,
            'eligible_mark_count': eligible_mark_count,
            'entered_mark_count': entered_mark_count,
        }

    def get_report_card_data(self, student_id: str, exam_id: int) -> Dict:
        self.cursor.execute(
            """
            SELECT s.AdmNo, s.FName, s.SName as LName,
                   c.display_name as class_name, e.name as exam_name,
                   e.term, ay.year as academic_year, c.classID
            FROM studentinfo s
            JOIN class_allocation ca
              ON s.AdmNo = ca.student_id AND ca.is_current = TRUE
             AND s.school_id = ca.school_id
            JOIN classes c
              ON ca.class_id = c.classID AND ca.school_id = c.school_id
            JOIN exam_series e
              ON e.id = %s AND e.school_id = s.school_id
             AND e.academic_year_id = ca.academic_year_id
            JOIN exam_classes ec
              ON ec.exam_id = e.id AND ec.class_id = c.classID
             AND ec.school_id = e.school_id
            JOIN academic_years ay
              ON e.academic_year_id = ay.id AND e.school_id = ay.school_id
            WHERE s.AdmNo = %s AND s.school_id = %s
            """,
            (exam_id, student_id, self.school_id),
        )
        info = self.cursor.fetchone()
        if not info:
            raise ExamManagementError("Student is not assigned to a class participating in this exam.")
        results = self.get_student_results(student_id, exam_id)
        tab = self.get_class_tabulation(exam_id, info['classID'])
        rank = next(
            (r['rank'] for r in tab['tabulation'] if str(r['admno']) == str(student_id)),
            "N/A",
        )
        return {
            'info': info,
            'results': results['subjects'],
            'summary': results['summary'],
            'rank': rank,
            'class_size': sum(
                row.get('eligible_subjects', 1) > 0
                for row in tab['tabulation']
            ),
        }

    def get_student_results(self, student_id: str, exam_id: int) -> Dict:
        self.cursor.execute(
            """
            SELECT ca.id as allocation_id, ca.class_id, e.academic_year_id
            FROM class_allocation ca
            JOIN exam_series e ON e.id = %s AND e.school_id = ca.school_id
             AND e.academic_year_id = ca.academic_year_id
            JOIN exam_classes ec ON ec.exam_id = e.id AND ec.class_id = ca.class_id
             AND ec.school_id = ca.school_id
            WHERE ca.student_id = %s AND ca.is_current = TRUE
              AND ca.school_id = %s
            LIMIT 1
            """,
            (exam_id, student_id, self.school_id),
        )
        allocation = self.cursor.fetchone()
        if not allocation:
            raise ExamManagementError("Student is not assigned to a class participating in this exam.")

        class_subjects = self._get_active_class_subjects(allocation['class_id'])
        enrolled_subject_ids = set(self._get_student_active_subject_ids(allocation['allocation_id']))
        if enrolled_subject_ids:
            subjects = [
                subject for subject in class_subjects
                if subject['id'] in enrolled_subject_ids
            ]
        else:
            subjects = class_subjects

        if not subjects:
            return {
                'subjects': [],
                'summary': {
                    'total_marks': 0,
                    'mean_mark': 0,
                    'mean_grade': '-',
                    'subjects_taken': 0,
                },
            }

        subject_ids = [subject['id'] for subject in subjects]
        placeholders = ', '.join(['%s'] * len(subject_ids))
        self.cursor.execute(
            f"""
            SELECT subject_id, mark, is_absent, remarks, ct_remarks, p_remarks,
                   grade_id
            FROM exam_marks
            WHERE exam_id = %s AND student_id = %s AND school_id = %s
              AND subject_id IN ({placeholders})
            """,
            (exam_id, student_id, self.school_id, *subject_ids),
        )
        marks_by_subject = {
            row['subject_id']: row for row in self.cursor.fetchall()
        }
        component_results = self._get_component_results_for_class(
            exam_id,
            allocation['class_id'],
            subject_ids,
            [str(student_id)],
        )
        for (component_student_id, subject_id), component_result in component_results.items():
            if component_student_id != str(student_id):
                continue
            mark_value = (
                None
                if component_result['scored_components'] == 0
                else component_result['mark']
            )
            marks_by_subject[subject_id] = {
                **component_result,
                'mark': mark_value,
                'remarks': marks_by_subject.get(subject_id, {}).get('remarks'),
                'ct_remarks': marks_by_subject.get(subject_id, {}).get('ct_remarks'),
                'p_remarks': marks_by_subject.get(subject_id, {}).get('p_remarks'),
            }
        results = []
        scores = []
        scale_id = self.get_effective_grading_scale_id(
            exam_id, allocation['class_id']
        )
        for subject in subjects:
            mark = marks_by_subject.get(subject['id'], {})
            grade = None
            points = None
            numeric_mark = mark.get('mark')
            is_absent = bool(mark.get('is_absent', False))
            if numeric_mark is not None and not is_absent:
                grade = self.get_grade_for_mark(float(numeric_mark), scale_id)
            state = mark.get('state') or (
                'absent' if is_absent
                else 'scored' if numeric_mark is not None
                else 'missing'
            )
            if numeric_mark is not None and not is_absent:
                scores.append(float(numeric_mark))
            results.append({
                'subject_name': subject['name'],
                'subject_code': subject['code'],
                'mark': numeric_mark,
                'grade': grade['grade'] if grade else None,
                'points': grade['points'] if grade else None,
                'remarks': mark.get('remarks'),
                'grade_remarks': grade['remarks'] if grade else None,
                'ct_remarks': (
                    mark.get('ct_remarks')
                    or (grade.get('class_teacher_remarks') if grade else None)
                ),
                'p_remarks': (
                    mark.get('p_remarks')
                    or (grade.get('principal_remarks') if grade else None)
                ),
                'is_absent': is_absent,
                'state': state,
                'total_mark': mark.get('total_mark'),
                'maximum_mark': mark.get('maximum_mark'),
                'component_count': mark.get('component_count'),
                'scored_components': mark.get('scored_components'),
                'absent_components': mark.get('absent_components'),
                'missing_components': mark.get('missing_components'),
            })
        total = sum(scores)
        average = total / len(subjects) if subjects else 0
        mean_grade = (
            self.get_grade_for_mark(average, scale_id) if subjects else None
        )
        return {
            'subjects': results,
            'summary': {
                'total_marks': total,
                'mean_mark': average,
                'mean_grade': mean_grade['grade'] if mean_grade else '-',
                'subjects_taken': len(subjects),
                'scored_subjects': len(scores),
                'absent_subjects': sum(
                    result['state'] == 'absent' for result in results
                ),
                'missing_subjects': sum(
                    result['state'] == 'missing' for result in results
                ),
                'partial_subjects': sum(
                    result['state'] == 'partial' for result in results
                ),
                'absent_components': sum(
                    result.get('absent_components') or 0 for result in results
                ),
                'missing_components': sum(
                    result.get('missing_components') or 0 for result in results
                ),
            },
        }

    def get_exam_rankings(self, exam_id: int, class_id: Optional[int] = None, limit: int = None) -> List[Dict]:
        assigned_classes = self.get_exam_classes(exam_id)
        assigned_class_ids = {row['classID'] for row in assigned_classes}
        if class_id is not None and class_id not in assigned_class_ids:
            raise ExamManagementError("Class is not assigned to this exam series.")
        target_classes = [
            row for row in assigned_classes
            if class_id is None or row['classID'] == class_id
        ]
        results = []
        for class_row in target_classes:
            tab = self.get_class_tabulation(exam_id, class_row['classID'])
            results.extend(
                row for row in tab['tabulation']
                if row.get(
                    'eligible_subjects', row.get('numeric_subjects', 0)
                ) > 0
            )
        results.sort(
            key=lambda row: (
                -row['average'],
                -row['total'],
                str(row['admno']),
            )
        )
        ranked_rows = rank_rows(
            results,
            'average',
            style=RankingStyle.COMPETITION,
            missing_policy='missing',
        )
        for ranked_row in ranked_rows:
            ranked_row.row['rank'] = ranked_row.rank
        return results[:limit] if limit else results

    def get_subject_winners(self, exam_id: int, class_id: Optional[int] = None) -> List[Dict]:
        classes = self.get_exam_classes(exam_id)
        if class_id is not None:
            if class_id not in {row['classID'] for row in classes}:
                raise ExamManagementError("Class is not assigned to this exam series.")
            classes = [row for row in classes if row['classID'] == class_id]
        winners = {}
        for class_row in classes:
            tab = self.get_class_tabulation(exam_id, class_row['classID'])
            subject_names = {
                subject['id']: subject for subject in tab['subjects']
            }
            for student in tab['tabulation']:
                for mark in student['marks']:
                    if mark['mark'] is None or mark['is_absent']:
                        continue
                    existing = winners.get(mark['subject_id'])
                    if existing is None or float(mark['mark']) > float(existing['mark']):
                        subject = subject_names[mark['subject_id']]
                        winners[mark['subject_id']] = {
                            'subject_name': subject['name'],
                            'subject_code': subject['code'],
                            'student_name': student['name'],
                            'class_name': class_row['display_name'],
                            'mark': mark['mark'],
                            'grade': mark['grade'],
                        }
        return sorted(winners.values(), key=lambda winner: winner['subject_name'])

    def get_most_improved(self, exam_id: int, class_id: Optional[int] = None) -> List[Dict]:
        current_exam = self.get_exam_series(exam_id)
        if not current_exam:
            raise ExamManagementError("Exam series not found for the active school.")
        current_created_at = current_exam.get('created_at')
        if current_created_at is None:
            return []
        self.cursor.execute(
            """
            SELECT id
            FROM exam_series
            WHERE school_id = %s AND academic_year_id = %s AND term = %s
              AND id <> %s AND created_at < %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (
                self.school_id,
                current_exam['academic_year_id'],
                current_exam['term'],
                exam_id,
                current_created_at,
            ),
        )
        previous_exam = self.cursor.fetchone()
        if not previous_exam:
            return []

        current_results = self.get_exam_rankings(exam_id, class_id=class_id)
        previous_results = self.get_exam_rankings(previous_exam['id'])
        if class_id is not None:
            current_student_ids = {str(row['admno']) for row in current_results}
            previous_results = [
                row for row in previous_results
                if str(row['admno']) in current_student_ids
            ]
        previous_by_student = {
            str(row['admno']): row
            for row in previous_results
            if row.get(
                'eligible_subjects', row.get('numeric_subjects', 0)
            ) > 0
        }
        improvements = []
        for current in current_results:
            previous = previous_by_student.get(str(current['admno']))
            if previous and current.get(
                'eligible_subjects', current.get('numeric_subjects', 0)
            ) > 0:
                delta = current['average'] - previous['average']
                if delta > 0:
                    improvements.append({
                        'name': current['name'],
                        'admno': current['admno'],
                        'class_name': current['class_name'],
                        'improvement': delta,
                        'previous_average': previous['average'],
                        'current_average': current['average'],
                    })
        improvements.sort(key=lambda row: (-row['improvement'], str(row['admno'])))
        return improvements[:5]

    def get_class_performance_distribution(self, exam_id: int, class_id: int) -> Dict:
        tab = self.get_class_tabulation(exam_id, class_id)
        dist = {}
        ranked_students = [
            row for row in tab['tabulation']
            if row.get(
                'eligible_subjects', row.get('numeric_subjects', 0)
            ) > 0
        ]
        for row in ranked_students:
            if row['grade'] not in (None, '', '-'):
                dist[row['grade']] = dist.get(row['grade'], 0) + 1
        mean_score = (
            sum(row['average'] for row in ranked_students) / len(ranked_students)
            if ranked_students else 0
        )
        return {
            'distribution': dist,
            'mean_score': mean_score,
            'total_students': len(ranked_students),
            'subject_stats': tab['subject_stats'],
        }

    def get_exam_analytics_overview(self, exam_id: int) -> Dict:
        """Build school, class, and stream analytics for one exam series."""
        exam = self.get_exam_series(exam_id)
        if not exam:
            raise ExamManagementError("Exam series not found for the active school.")

        # Pre-warm grading scale overrides for all classes in this exam
        self.cursor.execute(
            """
            SELECT class_id, grading_scale_id
            FROM exam_grading_overrides
            WHERE school_id = %s AND exam_id = %s
            """,
            (self.school_id, exam_id),
        )
        for override in self.cursor.fetchall():
            self._effective_scale_cache[(exam_id, override['class_id'])] = override['grading_scale_id']

        classes = self.get_exam_classes(exam_id)
        class_summaries = []
        scored_students = []
        grade_distribution = {}
        subject_totals = {}
        school_subject_cohorts = {}
        stream_groups = {}
        expected_mark_count = 0
        entered_mark_count = 0
        student_count = 0

        for class_row in classes:
            tab = self.get_class_tabulation(exam_id, class_row['classID'])
            class_students = tab['tabulation']
            subject_keys_by_id = {}
            for subject in tab['subject_stats']:
                if subject.get('subject_id') is not None:
                    subject_keys_by_id[subject['subject_id']] = (
                        subject['code'], subject['name']
                    )
            class_scored = [
                student for student in class_students
                if student['numeric_subjects'] > 0
            ]
            class_rankable = [
                student for student in class_students
                if student.get(
                    'eligible_subjects', student.get('numeric_subjects', 0)
                ) > 0
            ]
            class_mean = (
                sum(student['average'] for student in class_rankable)
                / len(class_rankable)
                if class_rankable else 0
            )
            class_summary = {
                'class_id': class_row['classID'],
                'class_name': class_row['display_name'],
                'class_group': class_row.get('class_group_code') or 'Other Classes',
                'stream_code': class_row.get('stream_code'),
                'student_count': len(class_students),
                'eligible_student_count': len(class_rankable),
                'scored_student_count': len(class_scored),
                'mean_score': class_mean,
                'expected_mark_count': tab.get('eligible_mark_count', 0),
                'entered_mark_count': tab.get('entered_mark_count', 0),
                'subject_stats': tab['subject_stats'],
            }
            class_summaries.append(class_summary)
            student_count += len(class_students)
            expected_mark_count += class_summary['expected_mark_count']
            entered_mark_count += class_summary['entered_mark_count']

            for student in class_rankable:
                scored_students.append({
                    **student,
                    'class_id': class_row['classID'],
                    'class_name': class_row['display_name'],
                })
                grade = student['grade']
                if grade not in (None, '', '-'):
                    grade_distribution[grade] = grade_distribution.get(grade, 0) + 1
                for mark in student.get('marks', []):
                    if mark.get('state') == 'ineligible':
                        continue
                    subject_id = mark.get('subject_id')
                    subject_key = subject_keys_by_id.get(subject_id)
                    if subject_key is None:
                        continue
                    cohort = school_subject_cohorts.setdefault(
                        subject_key, {'scores': [], 'grades': []}
                    )
                    score = mark.get('mark')
                    cohort['scores'].append(
                        0 if score is None or mark.get('is_absent') else float(score)
                    )
                    grade_value = mark.get('grade')
                    if (
                        score is not None
                        and not mark.get('is_absent')
                        and grade_value not in (None, '', '-')
                    ):
                        cohort['grades'].append(grade_value)

            for subject in tab['subject_stats']:
                key = (subject['code'], subject['name'])
                (
                    total, eligible_count, scored_count, entered_count,
                    absent_count, absent_component_count, missing_count,
                    missing_component_count,
                ) = subject_totals.get(
                    key, (0.0, 0, 0, 0, 0, 0, 0, 0)
                )
                subject_count = subject.get('eligible_count', subject['count'])
                subject_totals[key] = (
                    total + float(subject['average']) * subject_count,
                    eligible_count + subject_count,
                    scored_count + subject['count'],
                    entered_count + subject.get('entered_count', 0),
                    absent_count + subject.get('absent_count', 0),
                    absent_component_count
                        + subject.get('absent_component_count', 0),
                    missing_count + subject.get('missing_count', 0),
                    missing_component_count
                        + subject.get('missing_component_count', 0),
                )

            stream_code = class_row.get('stream_code')
            if stream_code:
                group_code = class_row.get('class_group_code') or 'Other Classes'
                group_streams = stream_groups.setdefault(group_code, {})
                stream_summary = group_streams.setdefault(
                    stream_code,
                    {
                        'stream': stream_code,
                        'class_group': group_code,
                        'classes': [],
                        'student_averages': [],
                        'student_count': 0,
                    },
                )
                stream_summary['classes'].append(class_row['display_name'])
                stream_summary['student_averages'].extend(
                    student['average'] for student in class_rankable
                )
                stream_summary['student_count'] += len(class_rankable)

        class_summaries.sort(
            key=lambda item: (-item['mean_score'], item['class_name'])
        )
        scored_students.sort(
            key=lambda item: (
                -item['average'], -item['total'], str(item['admno'])
            )
        )
        ranked_students = rank_rows(
            scored_students,
            'average',
            style=RankingStyle.COMPETITION,
            missing_policy='missing',
        )
        for ranked_student in ranked_students:
            ranked_student.row['rank'] = ranked_student.rank
        subject_stats = []
        for (code, name), (
            total, eligible_count, scored_count, entered_count,
            absent_count, absent_component_count, missing_count,
            missing_component_count,
        ) in subject_totals.items():
            cohort = school_subject_cohorts.get(
                (code, name), {'scores': [], 'grades': []}
            )
            subject_stats.append({
                'code': code,
                'name': name,
                'count': scored_count,
                'eligible_count': eligible_count,
                'entered_count': entered_count,
                'absent_count': absent_count,
                'absent_component_count': absent_component_count,
                'missing_count': missing_count,
                'missing_component_count': missing_component_count,
                'average': total / eligible_count if eligible_count else 0,
                'statistics': describe_eligible_scores(
                    cohort['scores'],
                    grade_values=cohort['grades'],
                ),
            })
        subject_stats.sort(key=lambda item: item['name'])

        stream_comparisons = []
        for group_code, streams in sorted(stream_groups.items()):
            summaries = []
            for stream in streams.values():
                averages = stream.pop('student_averages')
                stream['classes'].sort()
                stream['mean_score'] = (
                    sum(averages) / len(averages) if averages else 0
                )
                summaries.append(stream)
            summaries.sort(
                key=lambda item: (-item['mean_score'], item['stream'])
            )
            stream_comparisons.append({
                'class_group': group_code,
                'streams': summaries,
            })

        mean_score = (
            sum(student['average'] for student in scored_students)
            / len(scored_students)
            if scored_students else 0
        )
        return {
            'exam': exam,
            'classes': class_summaries,
            'class_count': len(classes),
            'student_count': student_count,
            'scored_student_count': sum(
                student['numeric_subjects'] > 0
                for student in scored_students
            ),
            'mean_score': mean_score,
            'grade_distribution': grade_distribution,
            'expected_mark_count': expected_mark_count,
            'entered_mark_count': entered_mark_count,
            'mark_coverage_percent': (
                100 * entered_mark_count / expected_mark_count
                if expected_mark_count else 0
            ),
            'subject_stats': subject_stats,
            'stream_comparisons': stream_comparisons,
            'top_students': scored_students[:10],
        }

    def get_stream_performance_comparison(self, exam_id: int) -> List[Dict]:
        grouped = {}
        for class_row in self.get_exam_classes(exam_id):
            tab = self.get_class_tabulation(exam_id, class_row['classID'])
            students = [
                row for row in tab['tabulation']
                if row.get(
                    'eligible_subjects', row.get('numeric_subjects', 0)
                ) > 0
            ]
            group_name = class_row.get('class_group_code') or 'Other Classes'
            stream_name = class_row.get('stream_code') or class_row['display_name']
            grouped.setdefault(group_name, []).append({
                'stream': stream_name,
                'class_name': class_row['display_name'],
                'student_count': len(students),
                'mean_score': (
                    sum(row['average'] for row in students) / len(students)
                    if students else 0
                ),
            })
        return [
            {
                'group': group_name,
                'streams': sorted(
                    streams,
                    key=lambda row: (-row['mean_score'], row['class_name']),
                ),
            }
            for group_name, streams in sorted(grouped.items())
        ]

    def get_all_grading_scales(self) -> List[Dict]:
        self.cursor.execute("SELECT * FROM grading_scales WHERE school_id = %s", (self.school_id,))
        return self.cursor.fetchall()

    def get_grading_scale(self, scale_id: int) -> Optional[Dict]:
        self.cursor.execute("SELECT * FROM grading_scales WHERE id = %s AND school_id = %s", (scale_id, self.school_id))
        return self.cursor.fetchone()

    def get_grading_details(self, scale_id: int) -> List[Dict]:
        self.cursor.execute("SELECT * FROM grading_details WHERE scale_id = %s AND school_id = %s ORDER BY min_mark DESC", (scale_id, self.school_id))
        return self.cursor.fetchall()
