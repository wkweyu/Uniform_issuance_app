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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ExamManagementError(Exception):
    """Base exception for exam management errors."""
    pass

class ExamManagementService:
    def __init__(self, connection: pymysql.Connection):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)

    # =========================================================================
    # 1. EXAM SERIES MANAGEMENT
    # =========================================================================

    def create_exam_series(self, name: str, academic_year_id: int, term: int, created_by: int, class_ids: List[int] = None) -> int:
        """Create a new exam series and assign classes."""
        try:
            sql = """
                INSERT INTO exam_series (name, academic_year_id, term, created_by)
                VALUES (%s, %s, %s, %s)
            """
            self.cursor.execute(sql, (name, academic_year_id, term, created_by))
            exam_id = self.cursor.lastrowid
            
            if class_ids:
                sql_class = "INSERT INTO exam_classes (exam_id, class_id) VALUES (%s, %s)"
                for cid in class_ids:
                    self.cursor.execute(sql_class, (exam_id, cid))
            
            self.connection.commit()
            return exam_id
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error creating exam series: {str(e)}")
            raise ExamManagementError(f"Failed to create exam series: {str(e)}")

    def get_exam_series(self, exam_id: int) -> Optional[Dict]:
        """Fetch a single exam series with year details."""
        sql = """
            SELECT e.*, ay.year as academic_year_name, ay.is_current
            FROM exam_series e
            JOIN academic_years ay ON e.academic_year_id = ay.id
            WHERE e.id = %s
        """
        self.cursor.execute(sql, (exam_id,))
        exam = self.cursor.fetchone()
        
        if exam:
            # Get assigned classes
            self.cursor.execute("""
                SELECT c.classID, c.display_name 
                FROM classes c
                JOIN exam_classes ec ON c.classID = ec.class_id
                WHERE ec.exam_id = %s
            """, (exam_id,))
            exam['classes'] = self.cursor.fetchall()
            
        return exam

    def update_exam_classes(self, exam_id: int, class_ids: List[int]) -> bool:
        """Update the classes assigned to an exam."""
        try:
            # Delete existing
            self.cursor.execute("DELETE FROM exam_classes WHERE exam_id = %s", (exam_id,))
            
            # Insert new
            if class_ids:
                sql = "INSERT INTO exam_classes (exam_id, class_id) VALUES (%s, %s)"
                for cid in class_ids:
                    self.cursor.execute(sql, (exam_id, cid))
            
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
            JOIN exam_classes ec ON c.classID = ec.class_id
            WHERE ec.exam_id = %s
            ORDER BY c.display_name
        """, (exam_id,))
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
            JOIN classes c ON ec.class_id = c.classID
            JOIN class_subjects cs ON c.classID = cs.class_id
            JOIN subjects s ON cs.subject_id = s.subjectNo
            JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE
            JOIN studentinfo si ON ca.student_id = si.AdmNo
            LEFT JOIN exam_marks em ON em.exam_id = ec.exam_id 
                                    AND em.student_id = si.AdmNo 
                                    AND em.subject_id = cs.subject_id
            WHERE ec.exam_id = %s
              AND (em.id IS NULL OR (em.mark IS NULL AND em.is_absent = FALSE))
            ORDER BY c.display_name, s.subjName, si.AdmNo
        """
        self.cursor.execute(sql, (exam_id,))
        return self.cursor.fetchall()

    def get_student_aggregate_report(self, exam_ids: List[int], student_id: int) -> Dict:
        """Get aggregate performance across multiple exams for a student."""
        if not exam_ids: return {}
        
        # 1. Get info
        self.cursor.execute("SELECT AdmNo, FName, SName as LName FROM studentinfo WHERE AdmNo = %s", (student_id,))
        student = self.cursor.fetchone()
        
        self.cursor.execute("""
            SELECT c.display_name, c.classID 
            FROM class_allocation ca 
            JOIN classes c ON ca.class_id = c.classID 
            WHERE ca.student_id = %s AND ca.is_current = TRUE
        """, (student_id,))
        class_info = self.cursor.fetchone()
        
        # 2. Get marks across selected exams
        format_strings = ','.join(['%s'] * len(exam_ids))
        sql_marks = f"""
            SELECT s.subjName as name, s.code, em.exam_id, em.mark, em.is_absent
            FROM exam_marks em
            JOIN subjects s ON em.subject_id = s.subjectNo
            WHERE em.student_id = %s AND em.exam_id IN ({format_strings})
        """
        self.cursor.execute(sql_marks, (student_id, *exam_ids))
        raw_marks = self.cursor.fetchall()
        
        # Group by subject
        subject_data = {}
        for m in raw_marks:
            subj_name = m['name']
            if subj_name not in subject_data:
                subject_data[subj_name] = {'name': subj_name, 'code': m['code'], 'marks': [], 'total': 0, 'count': 0}
            
            if not m['is_absent'] and m['mark'] is not None:
                subject_data[subj_name]['marks'].append({'exam_id': m['exam_id'], 'mark': m['mark']})
                subject_data[subj_name]['total'] += float(m['mark'])
                subject_data[subj_name]['count'] += 1
        
        # Calculate averages and grades
        results = []
        scale_id = self.get_class_grading_scale_id(class_info['classID']) if class_info else None
        
        total_avg = 0
        total_subjects = 0
        
        for subj in subject_data.values():
            if subj['count'] > 0:
                avg = subj['total'] / subj['count']
                grade_rec = self.get_grade_for_mark(avg, scale_id)
                
                results.append({
                    'name': subj['name'],
                    'code': subj['code'],
                    'average': avg,
                    'grade': grade_rec['grade'] if grade_rec else '-',
                    'remarks': grade_rec['remarks'] if grade_rec else '-'
                })
                total_avg += avg
                total_subjects += 1
                
        overall_avg = total_avg / total_subjects if total_subjects > 0 else 0
        overall_grade = self.get_grade_for_mark(overall_avg, scale_id)
        
        return {
            'student': student,
            'class': class_info,
            'results': results,
            'summary': {
                'average': overall_avg,
                'grade': overall_grade['grade'] if overall_grade else '-',
                'mean_points': overall_grade['points'] if overall_grade else 0
            }
        }

    def get_all_exams(self, academic_year_id: Optional[int] = None) -> List[Dict]:
        """Fetch all exam series, optionally filtered by year."""
        sql = """
            SELECT e.*, ay.year as academic_year_name, 
                   (SELECT COUNT(*) FROM exam_marks WHERE exam_id = e.id) as marks_count
            FROM exam_series e
            JOIN academic_years ay ON e.academic_year_id = ay.id
        """
        params = []
        if academic_year_id:
            sql += " WHERE e.academic_year_id = %s"
            params.append(academic_year_id)
        
        sql += " ORDER BY ay.year DESC, e.term DESC, e.id DESC"
        
        self.cursor.execute(sql, params)
        return self.cursor.fetchall()

    def toggle_exam_lock(self, exam_id: int, lock: bool) -> bool:
        """Lock or unlock an exam series."""
        try:
            sql = "UPDATE exam_series SET is_locked = %s WHERE id = %s"
            self.cursor.execute(sql, (lock, exam_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to toggle exam lock: {str(e)}")

    # =========================================================================
    # 2. MARKS & GRADING LOGIC
    # =========================================================================

    def get_grade_for_mark(self, mark: float, scale_id: Optional[int] = None) -> Optional[Dict]:
        """Determine grade for a given mark based on active scale."""
        if mark is None:
            return None
        
        if scale_id:
            sql = "SELECT * FROM grading_details WHERE scale_id = %s AND %s BETWEEN min_mark AND max_mark"
            self.cursor.execute(sql, (scale_id, mark))
        else:
            # Use default scale
            sql = """
                SELECT gd.* 
                FROM grading_details gd
                JOIN grading_scales gs ON gd.scale_id = gs.id
                WHERE gs.is_default = TRUE AND %s BETWEEN gd.min_mark AND gd.max_mark
            """
            self.cursor.execute(sql, (mark,))
        
        return self.cursor.fetchone()

    def save_mark(self, exam_id: int, student_id: str, subject_id: int, 
                 mark: Optional[float] = None, is_absent: bool = False, 
                 remarks: str = "", ct_remarks: str = "", p_remarks: str = "") -> bool:
        """Record or update a student's mark for a subject."""
        try:
            # Check if exam is locked
            exam = self.get_exam_series(exam_id)
            if not exam or exam['is_locked']:
                raise ExamManagementError("Cannot edit marks for a locked exam series.")

            grade_id = None
            if not is_absent and mark is not None:
                # Get student's class to determine scale
                sql_class = """
                    SELECT class_id FROM class_allocation 
                    WHERE student_id = %s AND is_current = TRUE 
                    LIMIT 1
                """
                self.cursor.execute(sql_class, (student_id,))
                alloc = self.cursor.fetchone()
                
                scale_id = None
                if alloc:
                    scale_id = self.get_class_grading_scale_id(alloc['class_id'])
                
                grade_rec = self.get_grade_for_mark(mark, scale_id)
                if grade_rec:
                    grade_id = grade_rec['id']

            sql = """
                INSERT INTO exam_marks (exam_id, student_id, subject_id, mark, grade_id, is_absent, remarks, ct_remarks, p_remarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    mark = VALUES(mark),
                    grade_id = VALUES(grade_id),
                    is_absent = VALUES(is_absent),
                    remarks = VALUES(remarks),
                    ct_remarks = VALUES(ct_remarks),
                    p_remarks = VALUES(p_remarks)
            """
            self.cursor.execute(sql, (exam_id, student_id, subject_id, mark, grade_id, is_absent, remarks, ct_remarks, p_remarks))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error saving mark: {str(e)}")
            raise ExamManagementError(f"Failed to save mark: {str(e)}")

    def get_marks_for_class_subject(self, exam_id: int, class_id: int, subject_id: int) -> List[Dict]:
        """Fetch all marks for a specific class and subject in an exam."""
        sql = """
            SELECT s.AdmNo, s.FName, s.SName as LName, 
                   m.mark, m.is_absent, gd.grade, m.remarks, m.ct_remarks, m.p_remarks
            FROM studentinfo s
            JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE
            LEFT JOIN exam_marks m ON s.AdmNo = m.student_id AND m.exam_id = %s AND m.subject_id = %s
            LEFT JOIN grading_details gd ON m.grade_id = gd.id
            WHERE ca.class_id = %s
            ORDER BY s.FName, s.SName
        """
        self.cursor.execute(sql, (exam_id, subject_id, class_id))
        return self.cursor.fetchall()

    def get_student_results(self, student_id: str, exam_id: int) -> Dict:
        """Fetch all scores for a student in a specific exam series."""
        # Get student's class to determine scale
        sql_class = """
            SELECT class_id FROM class_allocation 
            WHERE student_id = %s AND is_current = TRUE 
            LIMIT 1
        """
        self.cursor.execute(sql_class, (student_id,))
        alloc = self.cursor.fetchone()
        scale_id = self.get_class_grading_scale_id(alloc['class_id']) if alloc else None

        sql = """
            SELECT sub.subjName as subject_name, sub.code as subject_code,
                   m.mark, gd.grade, gd.points, m.remarks, m.ct_remarks, m.p_remarks,
                   gd.remarks as grade_remarks, m.is_absent
            FROM student_subjects ss
            JOIN class_allocation ca ON ss.class_allocation_id = ca.id
            JOIN subjects sub ON ss.subject_id = sub.subjectNo
            LEFT JOIN exam_marks m ON ca.student_id = m.student_id AND m.subject_id = sub.subjectNo AND m.exam_id = %s
            LEFT JOIN grading_details gd ON m.grade_id = gd.id
            WHERE ca.student_id = %s AND ca.is_current = TRUE
        """
        self.cursor.execute(sql, (exam_id, student_id))
        results = self.cursor.fetchall()
        
        total_marks = sum(r['mark'] for r in results if r['mark'] is not None)
        total_points = sum(r['points'] for r in results if r['points'] is not None)
        subjects_taken = len([r for r in results if r['mark'] is not None or r['is_absent']])
        
        mean_mark = total_marks / subjects_taken if subjects_taken > 0 else 0
        mean_grade_rec = self.get_grade_for_mark(mean_mark, scale_id)
        
        return {
            'subjects': results,
            'summary': {
                'total_marks': total_marks,
                'total_points': total_points,
                'mean_mark': mean_mark,
                'mean_grade': mean_grade_rec['grade'] if mean_grade_rec else 'N/A',
                'subjects_taken': subjects_taken
            }
        }

    def get_report_card_data(self, student_id: str, exam_id: int) -> Dict:
        """Gather all data required for a formal report card."""
        # 1. Student & Exam Info
        sql_info = """
            SELECT s.AdmNo, s.FName, s.SName as LName, c.display_name as class_name,
                   e.name as exam_name, e.term, ay.year as academic_year, c.classID
            FROM studentinfo s
            JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE
            JOIN classes c ON ca.class_id = c.classID
            JOIN exam_series e ON e.id = %s
            JOIN academic_years ay ON e.academic_year_id = ay.id
            WHERE s.AdmNo = %s
        """
        self.cursor.execute(sql_info, (exam_id, student_id))
        info = self.cursor.fetchone()
        
        if not info:
            raise ExamManagementError("Student or Exam record not found.")

        # 2. Get results using existing method
        results = self.get_student_results(student_id, exam_id)
        
        # 3. Calculate Rank and Class Size
        # We need the tabulation for the whole class to get rank
        tab_data = self.get_class_tabulation(exam_id, info['classID'])
        
        rank = "N/A"
        class_size = len(tab_data['tabulation'])
        
        for row in tab_data['tabulation']:
            if str(row['admno']) == str(student_id):
                rank = row['rank']
                break
        
        # 4. Final comments (often the ones from the marks entry of the last subject or aggregate)
        # For simplicity, we'll pick the remarks from the latest mark entered or define them as overall
        # Actually, in most schools, C/T and Headteacher remarks are specific "overall" remarks.
        # Let's see if we should have a separate table for overall remarks or just pull from the marks.
        # The user asked for "same remarks from subject teacher, class teacher and headteacher" 
        # which implies per-subject templates, but usually there's one overall comment.
        # We'll use the summary from the results.
        
        return {
            'info': info,
            'results': results['subjects'],
            'summary': results['summary'],
            'rank': rank,
            'class_size': class_size
        }

    def get_class_tabulation(self, exam_id: int, class_id: int) -> Dict:
        """Generate a tabulation sheet for a whole class in an exam series."""
        # 1. Get all subjects offered by this class
        sql_subs = """
            SELECT DISTINCT s.subjectNo as id, s.subjName as name, s.code
            FROM class_subjects cs
            JOIN subjects s ON cs.subject_id = s.subjectNo
            WHERE cs.class_id = %s AND cs.is_active = TRUE
            ORDER BY s.subjectNo
        """
        self.cursor.execute(sql_subs, (class_id,))
        subjects = self.cursor.fetchall()
        
        # 2. Get all students in this class
        sql_students = """
            SELECT s.AdmNo, s.FName, s.SName as LName
            FROM studentinfo s
            JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE
            WHERE ca.class_id = %s
            ORDER BY s.FName, s.SName
        """
        self.cursor.execute(sql_students, (class_id,))
        students = self.cursor.fetchall()
        
        # 3. Fetch all marks for this class and exam
        sql_marks = """
            SELECT m.student_id, m.subject_id, m.mark, gd.grade
            FROM exam_marks m
            JOIN grading_details gd ON m.grade_id = gd.id
            WHERE m.exam_id = %s AND m.student_id IN (
                SELECT student_id FROM class_allocation WHERE class_id = %s AND is_current = TRUE
            )
        """
        self.cursor.execute(sql_marks, (exam_id, class_id))
        marks_raw = self.cursor.fetchall()
        
        # Organize marks by student and subject
        marks_map = {}
        for m in marks_raw:
            student_id = str(m['student_id'])
            if student_id not in marks_map:
                marks_map[student_id] = {}
            marks_map[student_id][m['subject_id']] = m
            
        # 4. Compile tabulation rows
        tabulation = []
        for student in students:
            student_id_str = str(student['AdmNo'])
            row = {
                'admno': student['AdmNo'],
                'name': f"{student['FName']} {student['LName']}",
                'marks': [],
                'total': 0,
                'average': 0,
                'grade': 'E'
            }
            
            student_total = 0
            subjects_with_marks = 0
            
            for sub in subjects:
                m_data = marks_map.get(student_id_str, {}).get(sub['id'])
                if m_data:
                    row['marks'].append({
                        'subject_id': sub['id'],
                        'mark': m_data['mark'],
                        'grade': m_data['grade']
                    })
                    student_total += m_data['mark']
                    subjects_with_marks += 1
                else:
                    row['marks'].append({
                        'subject_id': sub['id'],
                        'mark': '-',
                        'grade': '-'
                    })
            
            row['total'] = student_total
            row['average'] = student_total / subjects_with_marks if subjects_with_marks > 0 else 0
            
            # Mean grade for student (using class-specific scale)
            scale_id = self.get_class_grading_scale_id(class_id)
            mean_grade_rec = self.get_grade_for_mark(row['average'], scale_id)
            row['grade'] = mean_grade_rec['grade'] if mean_grade_rec else '-'
            
            tabulation.append(row)
            
        # 5. Subject Analysis (Vertical statistics)
        subject_stats = []
        for i, sub in enumerate(subjects):
            marks = [r['marks'][i]['mark'] for r in tabulation if isinstance(r['marks'][i]['mark'], (int, float))]
            if marks:
                avg = sum(marks) / len(marks)
                grade_rec = self.get_grade_for_mark(avg, scale_id)
                subject_stats.append({
                    'subject_id': sub['id'],
                    'name': sub['name'],
                    'code': sub['code'],
                    'average': avg,
                    'grade': grade_rec['grade'] if grade_rec else '-',
                    'count': len(marks)
                })
            else:
                subject_stats.append({
                    'subject_id': sub['id'],
                    'name': sub['name'],
                    'code': sub['code'],
                    'average': 0,
                    'grade': '-',
                    'count': 0
                })

        # Sort by total descending (ranking)
        tabulation.sort(key=lambda x: x['total'], reverse=True)
        for i, row in enumerate(tabulation):
            row['rank'] = i + 1
            
        return {
            'subjects': subjects,
            'tabulation': tabulation,
            'subject_stats': subject_stats
        }

    # =========================================================================
    # 3. PERFORMANCE ANALYTICS & ADVANCED REPORTING
    # =========================================================================

    def get_exam_rankings(self, exam_id: int, class_id: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        """Get ranked list of students for an exam across one or all classes."""
        # 1. Get classes to include
        if class_id:
            target_class_ids = [class_id]
        else:
            self.cursor.execute("SELECT class_id FROM exam_classes WHERE exam_id = %s", (exam_id,))
            target_class_ids = [row['class_id'] for row in self.cursor.fetchall()]
        
        if not target_class_ids:
            return []

        # 2. Process each class and aggregate results
        all_results = []
        for cid in target_class_ids:
            tab = self.get_class_tabulation(exam_id, cid)
            # Add class info to each row
            self.cursor.execute("SELECT display_name FROM classes WHERE classID = %s", (cid,))
            cls_name = self.cursor.fetchone()['display_name']
            
            for row in tab['tabulation']:
                row['class_name'] = cls_name
                all_results.append(row)
        
        # 3. Re-rank across the entire set
        all_results.sort(key=lambda x: x['total'], reverse=True)
        for i, row in enumerate(all_results):
            row['overall_rank'] = i + 1
            
        if limit:
            return all_results[:limit]
        return all_results

    def get_subject_winners(self, exam_id: int, class_id: Optional[int] = None) -> List[Dict]:
        """Get the top student for each subject."""
        # Get all relevant subjects
        if class_id:
            sql_subs = """
                SELECT DISTINCT s.subjectNo, s.subjName, s.code
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.subjectNo
                WHERE cs.class_id = %s AND cs.is_active = TRUE
            """
            self.cursor.execute(sql_subs, (class_id,))
        else:
            sql_subs = """
                SELECT DISTINCT s.subjectNo, s.subjName, s.code
                FROM exam_classes ec
                JOIN class_subjects cs ON ec.class_id = cs.class_id
                JOIN subjects s ON cs.subject_id = s.subjectNo
                WHERE ec.exam_id = %s AND cs.is_active = TRUE
            """
            self.cursor.execute(sql_subs, (exam_id,))
            
        subjects = self.cursor.fetchall()
        winners = []
        
        for sub in subjects:
            sql_winner = """
                SELECT si.AdmNo, CONCAT(si.FName, ' ', si.SName) as student_name, 
                       em.mark, gd.grade, c.display_name as class_name
                FROM exam_marks em
                JOIN studentinfo si ON em.student_id = si.AdmNo
                LEFT JOIN grading_details gd ON em.grade_id = gd.id
                JOIN class_allocation ca ON si.AdmNo = ca.student_id AND ca.is_current = TRUE
                JOIN classes c ON ca.class_id = c.classID
                WHERE em.exam_id = %s AND em.subject_id = %s
            """
            params = [exam_id, sub['subjectNo']]
            if class_id:
                sql_winner += " AND ca.class_id = %s"
                params.append(class_id)
            
            sql_winner += " ORDER BY em.mark DESC LIMIT 1"
            
            self.cursor.execute(sql_winner, params)
            winner = self.cursor.fetchone()
            if winner:
                winner['subject_name'] = sub['subjName']
                winner['subject_code'] = sub['code']
                winners.append(winner)
                
        return winners

    def get_most_improved(self, exam_id: int, class_id: Optional[int] = None, limit: int = 5) -> List[Dict]:
        """Compare current exam with a previous one to find most improved students."""
        # 1. Identify previous exam
        self.cursor.execute("SELECT academic_year_id, term, id FROM exam_series WHERE id = %s", (exam_id,))
        current = self.cursor.fetchone()
        if not current: return []
        
        # Look for the immediate previous exam in the same year/term or previous term
        sql_prev = """
            SELECT id FROM exam_series 
            WHERE id < %s AND academic_year_id = %s
            ORDER BY id DESC LIMIT 1
        """
        self.cursor.execute(sql_prev, (exam_id, current['academic_year_id']))
        prev = self.cursor.fetchone()
        
        if not prev:
            # Try previous year if same year not found
            sql_prev_year = "SELECT id FROM exam_series WHERE academic_year_id < %s ORDER BY id DESC LIMIT 1"
            self.cursor.execute(sql_prev_year, (current['academic_year_id'],))
            prev = self.cursor.fetchone()
            
        if not prev:
            return [] # No baseline for improvement
            
        prev_id = prev['id']
        
        # 2. Get totals for both exams
        def get_all_totals(ex_id, c_id=None):
            sql = """
                SELECT em.student_id, SUM(em.mark) as total, COUNT(em.subject_id) as sub_count
                FROM exam_marks em
                JOIN class_allocation ca ON em.student_id = ca.student_id AND ca.is_current = TRUE
                WHERE em.exam_id = %s
            """
            params = [ex_id]
            if c_id:
                sql += " AND ca.class_id = %s"
                params.append(c_id)
            sql += " GROUP BY em.student_id"
            self.cursor.execute(sql, params)
            return {str(r['student_id']): r for r in self.cursor.fetchall()}
            
        current_totals = get_all_totals(exam_id, class_id)
        prev_totals = get_all_totals(prev_id, class_id)
        
        # 3. Calculate difference
        improvement = []
        for sid, cur in current_totals.items():
            if sid in prev_totals:
                pre = prev_totals[sid]
                # Compare averages to be fair about subject counts
                cur_avg = cur['total'] / cur['sub_count'] if cur['sub_count'] > 0 else 0
                pre_avg = pre['total'] / pre['sub_count'] if pre['sub_count'] > 0 else 0
                diff = cur_avg - pre_avg
                
                if diff > 0:
                    # Get student name
                    self.cursor.execute("SELECT AdmNo, CONCAT(FName, ' ', SName) as name FROM studentinfo WHERE AdmNo = %s", (sid,))
                    stu = self.cursor.fetchone()
                    improvement.append({
                        'admno': sid,
                        'name': stu['name'] if stu else sid,
                        'current_avg': cur_avg,
                        'prev_avg': pre_avg,
                        'improvement': diff
                    })
        
        improvement.sort(key=lambda x: x['improvement'], reverse=True)
        return improvement[:limit]

    def get_stream_performance_comparison(self, exam_id: int) -> List[Dict]:
        """Compare performance of different streams (e.g. Grade 4 A vs Grade 4 B)."""
        # 1. Get all assigned classes
        self.cursor.execute("""
            SELECT c.classID, c.display_name, c.class_group_code, c.stream_code
            FROM classes c
            JOIN exam_classes ec ON c.classID = ec.class_id
            WHERE ec.exam_id = %s
        """, (exam_id,))
        classes = self.cursor.fetchall()
        
        # Group by class_group_code
        groups = {}
        for c in classes:
            group = c['class_group_code']
            if group not in groups: groups[group] = []
            groups[group].append(c)
            
        stream_comparison = []
        for group, grp_classes in groups.items():
            if len(grp_classes) < 1: continue
            
            group_data = {'group': group, 'streams': []}
            for cls in grp_classes:
                tab = self.get_class_tabulation(exam_id, cls['classID'])
                # Calculate class average
                all_avgs = [r['average'] for r in tab['tabulation'] if r['average'] > 0]
                class_mean = sum(all_avgs) / len(all_avgs) if all_avgs else 0
                
                group_data['streams'].append({
                    'class_name': cls['display_name'],
                    'stream': cls['stream_code'],
                    'mean_score': class_mean,
                    'student_count': len(tab['tabulation'])
                })
            
            # Sort streams by mean score
            group_data['streams'].sort(key=lambda x: x['mean_score'], reverse=True)
            stream_comparison.append(group_data)
            
        return stream_comparison

    def get_class_performance_distribution(self, exam_id: int, class_id: int) -> Dict:
        """Get statistics on grade distribution for a class."""
        tab = self.get_class_tabulation(exam_id, class_id)
        
        distribution = {} # Grade -> Count
        for row in tab['tabulation']:
            grade = row['grade']
            distribution[grade] = distribution.get(grade, 0) + 1
            
        return {
            'distribution': distribution,
            'mean_score': sum(r['average'] for r in tab['tabulation']) / len(tab['tabulation']) if tab['tabulation'] else 0,
            'total_students': len(tab['tabulation']),
            'subject_stats': tab['subject_stats']
        }

    # =========================================================================
    # 4. GRADING SYSTEM MANAGEMENT
    # =========================================================================

    def create_grading_scale(self, name: str, description: str = "", is_default: bool = False) -> int:
        """Create a new grading scale."""
        try:
            if is_default:
                self.cursor.execute("UPDATE grading_scales SET is_default = FALSE")
            
            sql = "INSERT INTO grading_scales (name, description, is_default) VALUES (%s, %s, %s)"
            self.cursor.execute(sql, (name, description, is_default))
            self.connection.commit()
            return self.cursor.lastrowid
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to create scale: {str(e)}")

    def get_all_grading_scales(self) -> List[Dict]:
        """Fetch all grading scales."""
        self.cursor.execute("SELECT * FROM grading_scales ORDER BY is_default DESC, name ASC")
        return self.cursor.fetchall()

    def get_grading_scale(self, scale_id: int) -> Optional[Dict]:
        """Fetch details of a single scale."""
        self.cursor.execute("SELECT * FROM grading_scales WHERE id = %s", (scale_id,))
        return self.cursor.fetchone()

    def get_grading_details(self, scale_id: int) -> List[Dict]:
        """Fetch all grade entries within a scale."""
        self.cursor.execute("""
            SELECT * FROM grading_details 
            WHERE scale_id = %s 
            ORDER BY min_mark DESC
        """, (scale_id,))
        return self.cursor.fetchall()

    def save_grading_details(self, scale_id: int, grades: List[Dict]) -> bool:
        """Update grade entries for a scale."""
        try:
            # Simple approach: clear and re-insert
            self.cursor.execute("DELETE FROM grading_details WHERE scale_id = %s", (scale_id,))
            
            sql = """
                INSERT INTO grading_details (scale_id, grade, min_mark, max_mark, points, remarks, class_teacher_remarks, principal_remarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            for g in grades:
                self.cursor.execute(sql, (
                    scale_id, g['grade'], g['min_mark'], g['max_mark'], 
                    g.get('points', 0), g.get('remarks', ''),
                    g.get('class_teacher_remarks', ''),
                    g.get('principal_remarks', '')
                ))
            
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to save grades: {str(e)}")

    def assign_scale_to_class(self, class_id: int, scale_id: Optional[int]) -> bool:
        """Assign a specific scale to a class. Use None for default."""
        try:
            sql = "UPDATE classes SET grading_scale_id = %s WHERE classID = %s"
            self.cursor.execute(sql, (scale_id, class_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ExamManagementError(f"Failed to assign scale: {str(e)}")

    def get_class_grading_scale_id(self, class_id: int) -> Optional[int]:
        """Get the scale ID assigned to a class."""
        self.cursor.execute("SELECT grading_scale_id FROM classes WHERE classID = %s", (class_id,))
        res = self.cursor.fetchone()
        return res['grading_scale_id'] if res else None

