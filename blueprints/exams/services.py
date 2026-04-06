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

    def _assert_classes_belong_to_school(self, class_ids: List[int]) -> None:
        if not class_ids:
            return
        placeholders = ', '.join(['%s'] * len(class_ids))
        self.cursor.execute(
            f"SELECT classID FROM classes WHERE classID IN ({placeholders}) AND school_id = %s",
            tuple(class_ids) + (self.school_id,),
        )
        found = {row['classID'] for row in self.cursor.fetchall()}
        missing = [class_id for class_id in class_ids if class_id not in found]
        if missing:
            raise ExamManagementError("One or more classes do not belong to the active school.")

    def _assert_grading_scale_belongs_to_school(self, scale_id: Optional[int]) -> None:
        if scale_id is None:
            return
        self.cursor.execute("SELECT id FROM grading_scales WHERE id = %s AND school_id = %s", (scale_id, self.school_id))
        if not self.cursor.fetchone():
            raise ExamManagementError("Grading scale not found for the active school.")

    def _assert_mark_target_is_valid(self, exam_id: int, student_id: str, subject_id: int) -> int:
        self.cursor.execute(
            """
            SELECT ca.class_id
            FROM class_allocation ca
            JOIN exam_classes ec ON ca.class_id = ec.class_id AND ca.school_id = ec.school_id
            JOIN class_subjects cs ON ca.class_id = cs.class_id AND ca.school_id = cs.school_id
            WHERE ec.exam_id = %s
              AND ca.student_id = %s
              AND cs.subject_id = %s
              AND ca.is_current = TRUE
              AND cs.is_active = TRUE
              AND ca.school_id = %s
            LIMIT 1
            """,
            (exam_id, student_id, subject_id, self.school_id),
        )
        row = self.cursor.fetchone()
        if not row:
            raise ExamManagementError("Student, subject, and exam assignment do not match for the active school.")
        return row['class_id']

    # =========================================================================
    # 1. EXAM SERIES MANAGEMENT
    # =========================================================================

    @audit_log('create_exam_series')
    def create_exam_series(self, name: str, academic_year_id: int, term: int, created_by: int, class_ids: List[int] = None) -> int:
        """Create a new exam series and assign classes."""
        try:
            self._assert_academic_year_belongs_to_school(academic_year_id)
            self._assert_classes_belong_to_school(class_ids or [])
            sql = """
                INSERT INTO exam_series (name, academic_year_id, term, created_by, school_id)
                VALUES (%s, %s, %s, %s, %s)
            """
            self.cursor.execute(sql, (name, academic_year_id, term, created_by, self.school_id))
            exam_id = self.cursor.lastrowid

            if class_ids:
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
                SELECT c.classID, c.display_name
                FROM classes c
                JOIN exam_classes ec ON c.classID = ec.class_id AND c.school_id = ec.school_id
                WHERE ec.exam_id = %s AND ec.school_id = %s
            """, (exam_id, self.school_id))
            exam['classes'] = self.cursor.fetchall()

        return exam

    @audit_log('update_exam_classes')
    def update_exam_classes(self, exam_id: int, class_ids: List[int]) -> bool:
        """Update the classes assigned to an exam."""
        try:
            self._assert_exam_belongs_to_school(exam_id)
            self._assert_classes_belong_to_school(class_ids or [])
            # Delete existing
            self.cursor.execute("DELETE FROM exam_classes WHERE exam_id = %s AND school_id = %s", (exam_id, self.school_id))

            # Insert new
            if class_ids:
                sql = "INSERT INTO exam_classes (exam_id, class_id, school_id) VALUES (%s, %s, %s)"
                for cid in class_ids:
                    self.cursor.execute(sql, (exam_id, cid, self.school_id))

            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to update exam classes: {str(e)}")

    def get_exam_classes(self, exam_id: int) -> List[Dict]:
        """Get all classes assigned to an exam."""
        self.cursor.execute("""
            SELECT c.classID, c.display_name
            FROM classes c
            JOIN exam_classes ec ON c.classID = ec.class_id AND c.school_id = ec.school_id
            WHERE ec.exam_id = %s AND ec.school_id = %s
            ORDER BY c.display_name
        """, (exam_id, self.school_id))
        return self.cursor.fetchall()

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

    @audit_log('save_exam_mark')
    def save_mark(self, exam_id: int, student_id: str, subject_id: int,
                 mark: Optional[float] = None, is_absent: bool = False,
                 remarks: str = "", ct_remarks: str = "", p_remarks: str = "") -> bool:
        """Record or update a student's mark for a subject."""
        try:
            # Check if exam is locked
            exam = self.get_exam_series(exam_id)
            if not exam or exam['is_locked']:
                raise ExamManagementError("Cannot edit marks for a locked exam series.")

            class_id = self._assert_mark_target_is_valid(exam_id, student_id, subject_id)

            grade_id = None
            if not is_absent and mark is not None:
                scale_id = self.get_class_grading_scale_id(class_id)
                grade_rec = self.get_grade_for_mark(mark, scale_id)
                if grade_rec: grade_id = grade_rec['id']

            sql = """
                INSERT INTO exam_marks (exam_id, student_id, subject_id, mark, grade_id, is_absent, remarks, ct_remarks, p_remarks, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    mark = VALUES(mark), grade_id = VALUES(grade_id), is_absent = VALUES(is_absent),
                    remarks = VALUES(remarks), ct_remarks = VALUES(ct_remarks), p_remarks = VALUES(p_remarks)
            """
            self.cursor.execute(sql, (exam_id, student_id, subject_id, mark, grade_id, is_absent, remarks, ct_remarks, p_remarks, self.school_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to save mark: {str(e)}")

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
            self.cursor.execute("DELETE FROM grading_details WHERE scale_id = %s AND school_id = %s", (scale_id, self.school_id))
            sql = "INSERT INTO grading_details (scale_id, grade, min_mark, max_mark, points, remarks, class_teacher_remarks, principal_remarks, school_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            for g in grades:
                self.cursor.execute(sql, (scale_id, g['grade'], g['min_mark'], g['max_mark'], g.get('points', 0), g.get('remarks', ''), g.get('class_teacher_remarks', ''), g.get('principal_remarks', ''), self.school_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
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
        self._assert_classes_belong_to_school([class_id])
        sql = """
            SELECT s.AdmNo, s.FName, s.SName as LName, m.mark, m.is_absent, gd.grade, m.remarks, m.ct_remarks, m.p_remarks
            FROM studentinfo s
            JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE AND s.school_id = ca.school_id
            LEFT JOIN exam_marks m ON s.AdmNo = m.student_id AND m.exam_id = %s AND m.subject_id = %s AND s.school_id = m.school_id
            LEFT JOIN grading_details gd ON m.grade_id = gd.id AND m.school_id = gd.school_id
            WHERE ca.class_id = %s AND s.school_id = %s ORDER BY s.FName, s.SName
        """
        self.cursor.execute(sql, (exam_id, subject_id, class_id, self.school_id))
        return self.cursor.fetchall()

    def get_class_tabulation(self, exam_id: int, class_id: int) -> Dict:
        # Implementation from previous version (abbreviated here for brevity but should be full in reality)
        self.cursor.execute("SELECT DISTINCT s.subjectNo as id, s.subjName as name, s.code FROM class_subjects cs JOIN subjects s ON cs.subject_id = s.subjectNo AND cs.school_id = s.school_id WHERE cs.class_id = %s AND cs.is_active = TRUE AND cs.school_id = %s ORDER BY s.subjectNo", (class_id, self.school_id))
        subjects = self.cursor.fetchall()
        self.cursor.execute("SELECT s.AdmNo, s.FName, s.SName as LName FROM studentinfo s JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE AND s.school_id = ca.school_id WHERE ca.class_id = %s AND s.school_id = %s ORDER BY s.FName, s.SName", (class_id, self.school_id))
        students = self.cursor.fetchall()
        self.cursor.execute("SELECT m.student_id, m.subject_id, m.mark, gd.grade FROM exam_marks m LEFT JOIN grading_details gd ON m.grade_id = gd.id AND m.school_id = gd.school_id WHERE m.exam_id = %s AND m.school_id = %s", (exam_id, self.school_id))
        marks_raw = self.cursor.fetchall()
        marks_map = {}
        for m in marks_raw:
            sid = str(m['student_id'])
            if sid not in marks_map: marks_map[sid] = {}
            marks_map[sid][m['subject_id']] = m
        tabulation = []
        scale_id = self.get_class_grading_scale_id(class_id)
        for s in students:
            sid = str(s['AdmNo'])
            row = {'admno': s['AdmNo'], 'name': f"{s['FName']} {s['LName']}", 'marks': [], 'total': 0}
            count = 0
            for sub in subjects:
                m = marks_map.get(sid, {}).get(sub['id'])
                if m:
                    row['marks'].append({'subject_id': sub['id'], 'mark': m['mark'], 'grade': m['grade']})
                    row['total'] += m['mark']; count += 1
                else: row['marks'].append({'subject_id': sub['id'], 'mark': '-', 'grade': '-'})
            row['average'] = row['total'] / count if count > 0 else 0
            grade_rec = self.get_grade_for_mark(row['average'], scale_id)
            row['grade'] = grade_rec['grade'] if grade_rec else '-'
            tabulation.append(row)
        tabulation.sort(key=lambda x: x['total'], reverse=True)
        for i, r in enumerate(tabulation): r['rank'] = i+1
        return {'subjects': subjects, 'tabulation': tabulation}

    def get_report_card_data(self, student_id: str, exam_id: int) -> Dict:
        self.cursor.execute("SELECT s.AdmNo, s.FName, s.SName as LName, c.display_name as class_name, e.name as exam_name, e.term, ay.year as academic_year, c.classID FROM studentinfo s JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE AND s.school_id = ca.school_id JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id JOIN exam_series e ON e.id = %s AND e.school_id = s.school_id JOIN academic_years ay ON e.academic_year_id = ay.id AND e.school_id = ay.school_id WHERE s.AdmNo = %s AND s.school_id = %s", (exam_id, student_id, self.school_id))
        info = self.cursor.fetchone()
        if not info: raise ExamManagementError("Not found")
        # Reuse student results and tabulation for rank
        results = self.get_student_results(student_id, exam_id)
        tab = self.get_class_tabulation(exam_id, info['classID'])
        rank = next((r['rank'] for r in tab['tabulation'] if str(r['admno']) == str(student_id)), "N/A")
        return {'info': info, 'results': results['subjects'], 'summary': results['summary'], 'rank': rank, 'class_size': len(tab['tabulation'])}

    def get_student_results(self, student_id: str, exam_id: int) -> Dict:
        self.cursor.execute("SELECT sub.subjName as subject_name, sub.code as subject_code, m.mark, gd.grade, gd.points, m.remarks, m.is_absent FROM student_subjects ss JOIN class_allocation ca ON ss.class_allocation_id = ca.id AND ss.school_id = ca.school_id JOIN subjects sub ON ss.subject_id = sub.subjectNo AND ss.school_id = sub.school_id LEFT JOIN exam_marks m ON ca.student_id = m.student_id AND m.subject_id = sub.subjectNo AND m.exam_id = %s AND ca.school_id = m.school_id LEFT JOIN grading_details gd ON m.grade_id = gd.id AND m.school_id = gd.school_id WHERE ca.student_id = %s AND ca.is_current = TRUE AND ca.school_id = %s", (exam_id, student_id, self.school_id))
        res = self.cursor.fetchall()
        total = sum(r['mark'] for r in res if r['mark']); taken = len([r for r in res if r['mark'] or r['is_absent']])
        avg = total / taken if taken > 0 else 0
        return {'subjects': res, 'summary': {'total_marks': total, 'mean_mark': avg, 'subjects_taken': taken}}

    def get_exam_rankings(self, exam_id: int, class_id: Optional[int] = None, limit: int = None) -> List[Dict]:
        cids = [class_id] if class_id else [r['class_id'] for r in self.get_exam_classes(exam_id)]
        results = []
        for cid in cids:
            tab = self.get_class_tabulation(exam_id, cid)
            for r in tab['tabulation']: results.append(r)
        results.sort(key=lambda x: x['total'], reverse=True)
        return results[:limit] if limit else results

    def get_subject_winners(self, exam_id: int, class_id: Optional[int] = None) -> List[Dict]:
        return [] # Placeholder

    def get_most_improved(self, exam_id: int, class_id: Optional[int] = None) -> List[Dict]:
        return [] # Placeholder

    def get_class_performance_distribution(self, exam_id: int, class_id: int) -> Dict:
        tab = self.get_class_tabulation(exam_id, class_id)
        dist = {}
        for r in tab['tabulation']: dist[r['grade']] = dist.get(r['grade'], 0) + 1
        return {'distribution': dist, 'mean_score': sum(r['average'] for r in tab['tabulation'])/len(tab['tabulation']) if tab['tabulation'] else 0, 'total_students': len(tab['tabulation']), 'subject_stats': []}

    def get_stream_performance_comparison(self, exam_id: int) -> List[Dict]:
        return [] # Placeholder

    def get_all_grading_scales(self) -> List[Dict]:
        self.cursor.execute("SELECT * FROM grading_scales WHERE school_id = %s", (self.school_id,))
        return self.cursor.fetchall()

    def get_grading_scale(self, scale_id: int) -> Optional[Dict]:
        self.cursor.execute("SELECT * FROM grading_scales WHERE id = %s AND school_id = %s", (scale_id, self.school_id))
        return self.cursor.fetchone()

    def get_grading_details(self, scale_id: int) -> List[Dict]:
        self.cursor.execute("SELECT * FROM grading_details WHERE scale_id = %s AND school_id = %s ORDER BY min_mark DESC", (scale_id, self.school_id))
        return self.cursor.fetchall()
