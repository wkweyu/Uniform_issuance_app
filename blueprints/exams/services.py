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
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Tuple, Optional
import logging
from core.audit import audit_log
from core.tenancy import require_current_school_id
from flask import g

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

    def _assert_academic_year_belongs_to_school(self, academic_year_id: int) -> None:
        self.cursor.execute("SELECT id FROM academic_years WHERE id = %s AND school_id = %s", (academic_year_id, self.school_id))
        if not self.cursor.fetchone():
            raise ExamManagementError("Academic year not found for the active school.")

    def _assert_exam_belongs_to_school(self, exam_id: int) -> None:
        self.cursor.execute("SELECT id FROM exam_series WHERE id = %s AND school_id = %s", (exam_id, self.school_id))
        if not self.cursor.fetchone():
            raise ExamManagementError("Exam series not found for the active school.")

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
        class_info = self._get_exam_class_details(exam_id, class_id)
        class_subjects = self._get_active_class_subjects(class_id)
        if not class_subjects:
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
            return class_subjects
        return [
            subject for subject in class_subjects
            if subject['id'] in enrolled_subject_ids or fallback_student_count > 0
        ]

    def get_exam_subjects_status(self, exam_id: int, class_id: int) -> List[Dict]:
        """Return eligible subjects and mark-entry completion counts for a class."""
        subjects = self.get_exam_subjects_for_class(exam_id, class_id)
        status = []
        for subject in subjects:
            students = self.get_marks_for_class_subject(exam_id, class_id, subject['id'])
            entered = sum(
                student['mark'] is not None or bool(student['is_absent'])
                for student in students
            )
            total = len(students)
            complete = total > 0 and entered == total
            status.append({
                **subject,
                'is_complete': complete,
                'status_text': f"{entered}/{total} entered" if total else "No eligible students",
                'entered_count': entered,
                'student_count': total,
            })
        return status

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
                INSERT INTO exam_series (name, academic_year_id, term, created_by, school_id)
                VALUES (%s, %s, %s, %s, %s)
            """
            self.cursor.execute(sql, (name, academic_year_id, term, created_by, self.school_id))
            exam_id = self.cursor.lastrowid

            sql_class = "INSERT INTO exam_classes (exam_id, class_id, school_id) VALUES (%s, %s, %s)"
            for cid in class_ids:
                self.cursor.execute(sql_class, (exam_id, cid, self.school_id))

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
                SELECT id, academic_year_id, is_locked
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            if exam['is_locked']:
                raise ExamManagementError("Unlock the exam series before editing it.")

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
    def toggle_exam_lock(self, exam_id: int, lock: bool) -> bool:
        """Lock or unlock an exam series."""
        try:
            sql = "UPDATE exam_series SET is_locked = %s WHERE id = %s AND school_id = %s"
            self.cursor.execute(sql, (lock, exam_id, self.school_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to toggle exam lock: {str(e)}")

    @audit_log('save_exam_marks')
    def save_marks_bulk(self, exam_id: int, marks: List[Dict]) -> int:
        """Validate and save a set of marks atomically."""
        try:
            if not marks:
                raise ExamManagementError("No marks were provided.")

            self.connection.begin()
            self.cursor.execute(
                """
                SELECT id, is_locked
                FROM exam_series
                WHERE id = %s AND school_id = %s
                FOR UPDATE
                """,
                (exam_id, self.school_id),
            )
            exam = self.cursor.fetchone()
            if not exam:
                raise ExamManagementError("Exam series not found for the active school.")
            if exam['is_locked']:
                raise ExamManagementError("Cannot edit marks for a locked exam series.")

            prepared_marks = []
            seen_targets = set()
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
                grade_id = None
                if not is_absent and mark is not None:
                    scale_id = self.get_class_grading_scale_id(class_id)
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
            for values in prepared_marks:
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
        scale_id = self.get_class_grading_scale_id(class_id)
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
            if is_default:
                self.cursor.execute("UPDATE grading_scales SET is_default = FALSE WHERE school_id = %s", (self.school_id,))
            sql = "INSERT INTO grading_scales (name, description, is_default, school_id) VALUES (%s, %s, %s, %s)"
            self.cursor.execute(sql, (name, description, is_default, self.school_id))
            self.connection.commit()
            return self.cursor.lastrowid
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to create scale: {str(e)}")

    @audit_log('save_grading_details')
    def save_grading_details(self, scale_id: int, grades: List[Dict]) -> bool:
        try:
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
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            if isinstance(e, ExamManagementError):
                raise
            raise ExamManagementError(f"Failed to save grades: {str(e)}")

    @audit_log('assign_grading_scale')
    def assign_scale_to_class(self, class_id: int, scale_id: Optional[int]) -> bool:
        try:
            self._assert_classes_belong_to_school([class_id])
            self._assert_grading_scale_belongs_to_school(scale_id)
            self.cursor.execute("UPDATE classes SET grading_scale_id = %s WHERE classID = %s AND school_id = %s", (scale_id, class_id, self.school_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to assign scale: {str(e)}")

    # Implementation of other helper methods from previous version...
    def get_class_grading_scale_id(self, class_id: int) -> Optional[int]:
        self.cursor.execute("SELECT grading_scale_id FROM classes WHERE classID = %s AND school_id = %s", (class_id, self.school_id))
        res = self.cursor.fetchone()
        return res['grading_scale_id'] if res else None

    def get_grade_for_mark(self, mark: float, scale_id: Optional[int] = None) -> Optional[Dict]:
        if mark is None: return None
        if scale_id:
            self.cursor.execute("SELECT * FROM grading_details WHERE scale_id = %s AND %s BETWEEN min_mark AND max_mark AND school_id = %s", (scale_id, mark, self.school_id))
        else:
            self.cursor.execute("SELECT gd.* FROM grading_details gd JOIN grading_scales gs ON gd.scale_id = gs.id AND gd.school_id = gs.school_id WHERE gs.is_default = TRUE AND %s BETWEEN gd.min_mark AND gd.max_mark AND gd.school_id = %s", (mark, self.school_id))
        return self.cursor.fetchone()

    def get_marks_for_class_subject(self, exam_id: int, class_id: int, subject_id: int) -> List[Dict]:
        self._assert_exam_belongs_to_school(exam_id)
        class_info = self._get_exam_class_details(exam_id, class_id)
        self.get_exam_subject(exam_id, class_id, subject_id)
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
            ORDER BY s.FName, s.SName
        """
        self.cursor.execute(
            sql,
            (
                exam_id, subject_id, class_id,
                class_info['exam_academic_year_id'], self.school_id, subject_id,
            ),
        )
        return self.cursor.fetchall()

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
        marks_map = {}
        for subject in subjects:
            subject_marks = self.get_marks_for_class_subject(
                exam_id, class_id, subject['id']
            )
            for mark in subject_marks:
                marks_map.setdefault(str(mark['AdmNo']), {})[subject['id']] = mark

        scale_id = self.get_class_grading_scale_id(class_id)
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
            count = 0
            for sub in subjects:
                m = marks_map.get(sid, {}).get(sub['id'])
                if m:
                    mark_value = m['mark']
                    if m['is_absent']:
                        row['marks'].append({
                            'subject_id': sub['id'], 'mark': None,
                            'grade': '-', 'is_absent': True,
                        })
                    else:
                        row['marks'].append({
                            'subject_id': sub['id'], 'mark': mark_value,
                            'grade': m['grade'] or '-', 'is_absent': False,
                        })
                        if mark_value is not None:
                            row['total'] += float(mark_value)
                            count += 1
                else:
                    row['marks'].append({
                        'subject_id': sub['id'], 'mark': None,
                        'grade': '-', 'is_absent': False,
                    })
            row['numeric_subjects'] = count
            row['average'] = row['total'] / count if count else 0
            grade_rec = self.get_grade_for_mark(row['average'], scale_id) if count else None
            row['grade'] = grade_rec['grade'] if grade_rec else '-'
            tabulation.append(row)
        tabulation.sort(key=lambda row: (
            row['numeric_subjects'] == 0,
            -row['average'],
            -row['total'],
            str(row['admno']),
        ))
        rank = 0
        previous_average = None
        ranked_position = 0
        for row in tabulation:
            if row['numeric_subjects'] == 0:
                row['rank'] = '-'
            else:
                ranked_position += 1
                if previous_average is None or row['average'] != previous_average:
                    rank = ranked_position
                    previous_average = row['average']
                row['rank'] = rank

        subject_stats = []
        for subject in subjects:
            scores = [
                mark['mark']
                for row in tabulation
                for mark in row['marks']
                if mark['subject_id'] == subject['id']
                and not mark['is_absent']
                and mark['mark'] is not None
            ]
            average = sum(float(score) for score in scores) / len(scores) if scores else 0
            grade = self.get_grade_for_mark(average, scale_id) if scores else None
            subject_stats.append({
                'subject_id': subject['id'],
                'name': subject['name'],
                'code': subject['code'],
                'count': len(scores),
                'average': average,
                'grade': grade['grade'] if grade else '-',
            })
        return {
            'class_info': class_info,
            'subjects': subjects,
            'subject_stats': subject_stats,
            'tabulation': tabulation,
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
            'class_size': len(tab['tabulation']),
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
        results = []
        scores = []
        for subject in subjects:
            mark = marks_by_subject.get(subject['id'], {})
            grade = None
            points = None
            if mark.get('grade_id'):
                self.cursor.execute(
                    """
                    SELECT grade, points, remarks, class_teacher_remarks,
                           principal_remarks
                    FROM grading_details
                    WHERE id = %s AND school_id = %s
                    """,
                    (mark['grade_id'], self.school_id),
                )
                grade = self.cursor.fetchone()
            numeric_mark = mark.get('mark')
            is_absent = bool(mark.get('is_absent', False))
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
                'ct_remarks': mark.get('ct_remarks'),
                'p_remarks': mark.get('p_remarks'),
                'is_absent': is_absent,
            })
        total = sum(scores)
        average = total / len(scores) if scores else 0
        scale_id = self.get_class_grading_scale_id(allocation['class_id'])
        mean_grade = self.get_grade_for_mark(average, scale_id) if scores else None
        return {
            'subjects': results,
            'summary': {
                'total_marks': total,
                'mean_mark': average,
                'mean_grade': mean_grade['grade'] if mean_grade else '-',
                'subjects_taken': len(scores),
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
                if row['numeric_subjects'] > 0
            )
        results.sort(
            key=lambda row: (
                row['numeric_subjects'] == 0,
                -row['average'],
                -row['total'],
                str(row['admno']),
            )
        )
        rank = 0
        previous_average = None
        for index, row in enumerate(results, start=1):
            if row['numeric_subjects'] == 0:
                row['rank'] = '-'
                continue
            if previous_average is None or row['average'] != previous_average:
                rank = index
                previous_average = row['average']
            row['rank'] = rank
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
            if row['numeric_subjects'] > 0
        }
        improvements = []
        for current in current_results:
            previous = previous_by_student.get(str(current['admno']))
            if previous and current['numeric_subjects'] > 0:
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
            if row['numeric_subjects'] > 0
        ]
        for row in ranked_students:
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

    def get_stream_performance_comparison(self, exam_id: int) -> List[Dict]:
        grouped = {}
        for class_row in self.get_exam_classes(exam_id):
            tab = self.get_class_tabulation(exam_id, class_row['classID'])
            students = [
                row for row in tab['tabulation']
                if row['numeric_subjects'] > 0
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
