import pymysql
from datetime import datetime
from typing import Dict, List, Optional
import logging
import uuid
from core.audit import audit_log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ClassManagementException(Exception):
    pass

class ValidationError(ClassManagementException):
    pass

class PromotionError(ClassManagementException):
    pass

class ClassManagementService:
    def __init__(self, connection: pymysql.Connection, school_id: int = 1):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id

    def get_dashboard_stats(self) -> Dict:
        self.cursor.execute("SELECT COUNT(*) as count FROM academic_years WHERE school_id = %s", (self.school_id,))
        ay_count = self.cursor.fetchone()['count']

        self.cursor.execute("SELECT COUNT(*) as count FROM classes WHERE school_id = %s", (self.school_id,))
        total_classes = self.cursor.fetchone()['count']

        self.cursor.execute("SELECT COUNT(*) as count FROM class_allocation WHERE is_current = TRUE AND school_id = %s", (self.school_id,))
        total_students = self.cursor.fetchone()['count']

        self.cursor.execute("SELECT COUNT(*) as count FROM subjects WHERE school_id = %s", (self.school_id,))
        total_subjects = self.cursor.fetchone()['count']

        self.cursor.execute("SELECT year FROM academic_years WHERE is_current = TRUE AND school_id = %s LIMIT 1", (self.school_id,))
        result = self.cursor.fetchone()
        current_year = result['year'] if result else None

        return {
            'academic_years_count': ay_count,
            'total_classes': total_classes,
            'total_students': total_students,
            'total_subjects': total_subjects,
            'current_year': current_year
        }

    def get_classes_with_details(self) -> List[Dict]:
        self.cursor.execute("""
            SELECT c.classID, c.class_name, c.class_group, c.stream_code,
                   c.display_name, a.year, COUNT(ca.id) as student_count
            FROM classes c
            LEFT JOIN academic_years a ON c.academic_year_id = a.id
            LEFT JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE
            WHERE a.is_current = TRUE AND c.school_id = %s
            GROUP BY c.classID
            ORDER BY c.class_name ASC
        """, (self.school_id,))
        return self.cursor.fetchall()

    def get_classes_missing_subjects(self) -> List[str]:
        self.cursor.execute("""
            SELECT c.display_name
            FROM classes c
            LEFT JOIN class_subjects cs ON c.classID = cs.class_id AND cs.is_active = TRUE AND cs.school_id = %s
            LEFT JOIN academic_years ay ON c.academic_year_id = ay.id
            WHERE ay.is_current = TRUE AND c.is_active = TRUE AND c.school_id = %s
            GROUP BY c.classID
            HAVING COUNT(cs.subject_id) = 0
        """, (self.school_id, self.school_id))
        return [row['display_name'] for row in self.cursor.fetchall()]

    def get_classes_missing_teachers(self) -> List[str]:
        self.cursor.execute("""
            SELECT c.display_name
            FROM classes c
            LEFT JOIN academic_years ay ON c.academic_year_id = ay.id
            LEFT JOIN class_teachers ct ON c.classID = ct.class_id AND ct.academic_year_id = ay.id AND ct.is_active = TRUE AND ct.school_id = %s
            WHERE ay.is_current = TRUE AND c.is_active = TRUE AND c.school_id = %s
            GROUP BY c.classID
            HAVING COUNT(ct.teacher_id) = 0
        """, (self.school_id, self.school_id))
        return [row['display_name'] for row in self.cursor.fetchall()]

    def get_class_subjects_missing_teachers(self) -> List[str]:
        # Fallback to multiple schemas as seen in app.py
        try:
            self.cursor.execute("""
                SELECT c.display_name, s.subjName as subject_name
                FROM classes c
                JOIN class_subjects cs ON c.classID = cs.class_id AND cs.is_active = TRUE AND cs.school_id = %s
                JOIN subjects s ON cs.subject_id = s.subjectNo AND s.school_id = %s
                LEFT JOIN teacher_allocations ta ON c.classID = ta.class_id AND cs.subject_id = ta.subject_id AND ta.is_active = TRUE AND ta.school_id = %s
                LEFT JOIN academic_years ay ON c.academic_year_id = ay.id
                WHERE ay.is_current = TRUE AND c.is_active = TRUE AND c.school_id = %s
                GROUP BY c.classID, cs.subject_id
                HAVING COUNT(ta.teacher_id) = 0
            """, (self.school_id, self.school_id, self.school_id, self.school_id))
            return [f"{row['display_name']} - {row['subject_name']}" for row in self.cursor.fetchall()]
        except:
            return []

    def update_class(self, class_id: int, class_name: str, class_group: str, stream_code: str):
        self.cursor.execute("""
            UPDATE classes SET class_name = %s, class_group = %s, stream_code = %s WHERE classID = %s AND school_id = %s
        """, (class_name, class_group, stream_code, class_id, self.school_id))
        self.connection.commit()

    def delete_class(self, class_id: int):
        self.cursor.execute("SELECT COUNT(*) as count FROM class_allocation WHERE class_id = %s AND school_id = %s", (class_id, self.school_id))
        if self.cursor.fetchone()['count'] > 0:
            raise ValidationError("Cannot delete class with students.")
        self.cursor.execute("DELETE FROM classes WHERE classID = %s AND school_id = %s", (class_id, self.school_id))
        self.connection.commit()

    def get_active_classes(self) -> List[Dict]:
        self.cursor.execute("SELECT classID, display_name, academic_year_id, class_group_code, stream_code FROM classes WHERE is_active = TRUE AND school_id = %s ORDER BY display_name", (self.school_id,))
        return self.cursor.fetchall()

    def get_class_summary_report(self) -> List[Dict]:
        self.cursor.execute("""
            SELECT c.display_name, ay.year, COUNT(ca.id) as students
            FROM classes c
            LEFT JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE AND ca.school_id = c.school_id
            JOIN academic_years ay ON c.academic_year_id = ay.id AND ay.school_id = c.school_id
            WHERE c.school_id = %s
            GROUP BY c.classID, ay.year
            ORDER BY ay.year DESC, c.display_name
        """, (self.school_id,))
        return self.cursor.fetchall()

    def get_recent_promotions_log(self, limit: int = 20) -> List[Dict]:
        self.cursor.execute("""
            SELECT old_class_id, new_class_id, student_count, promotion_date
            FROM class_promotion_log
            WHERE school_id = %s
            ORDER BY promotion_date DESC LIMIT %s
        """, (self.school_id, limit))
        return self.cursor.fetchall()

    def get_all_academic_years(self) -> List[Dict]:
        self.cursor.execute("SELECT id, year, name, start_date, end_date, is_current FROM academic_years WHERE school_id = %s ORDER BY year DESC", (self.school_id,))
        return self.cursor.fetchall()

    def get_class_groups(self) -> Dict[str, Dict]:
        self.cursor.execute("SELECT code, name FROM class_group_settings WHERE school_id = %s ORDER BY code", (self.school_id,))
        results = self.cursor.fetchall()
        if not results: # Fallback to hardcoded if settings table empty
             return {
                'Playgroup-PP2': {'name': 'Playgroup-PP2'},
                'Grade 1-3': {'name': 'Grade 1-3'},
                'Grade 4-6': {'name': 'Grade 4-6'},
                'Grade 7-9': {'name': 'Grade 7-9'},
            }
        return {row['code']: {'name': row['name']} for row in results}

    def get_allowed_streams(self, school_id: int) -> List[Dict]:
        self.cursor.execute("SELECT code, name FROM stream_settings WHERE school_id = %s AND is_active = TRUE ORDER BY code", (school_id,))
        return self.cursor.fetchall()

    def validate_stream(self, stream_code: str) -> bool:
        self.cursor.execute("SELECT id FROM stream_settings WHERE code = %s AND school_id = %s AND is_active = TRUE", (stream_code, self.school_id))
        return self.cursor.fetchone() is not None

    @audit_log('create_class')
    def create_class(self, academic_year_id: int, class_group_code: str, stream_code: str, created_by: int, class_name: str) -> Dict:
        display_name = f"{class_name} – Stream {stream_code}"
        self.connection.begin()
        try:
            self.cursor.execute("""
                INSERT INTO classes (academic_year_id, class_group_code, stream_code, display_name, is_active, created_by, created_at, updated_at, class_name, class_group, school_id)
                VALUES (%s, %s, %s, %s, TRUE, %s, NOW(), NOW(), %s, %s, %s)
            """, (academic_year_id, class_group_code, stream_code, display_name, created_by, class_name, class_group_code, self.school_id))
            class_id = self.cursor.lastrowid
            self.connection.commit()
            self.cursor.execute("SELECT * FROM classes WHERE classID = %s", (class_id,))
            return self.cursor.fetchone()
        except Exception as e:
            self.connection.rollback()
            raise e

    @audit_log('promote_students')
    def promote_students(self, old_class_id: int, new_class_id: int, promoted_by: int, notes: str) -> Dict:
        batch_id = str(uuid.uuid4())[:8]
        # (Simplified logic from previous version for brevity but keep important parts)
        self.cursor.execute("SELECT c.*, ay.year FROM classes c JOIN academic_years ay ON c.academic_year_id = ay.id WHERE c.classID = %s AND c.school_id = %s", (old_class_id, self.school_id))
        old_class = self.cursor.fetchone()
        self.cursor.execute("SELECT c.*, ay.year, ay.id as ay_id FROM classes c JOIN academic_years ay ON c.academic_year_id = ay.id WHERE c.classID = %s AND c.school_id = %s", (new_class_id, self.school_id))
        new_class = self.cursor.fetchone()

        if not old_class or not new_class: raise PromotionError("Classes not found.")

        self.cursor.execute("SELECT id, student_id FROM class_allocation WHERE class_id = %s AND is_current = TRUE AND school_id = %s", (old_class_id, self.school_id))
        students = self.cursor.fetchall()

        self.connection.begin()
        try:
            for student in students:
                self.cursor.execute("INSERT INTO class_allocation (student_id, class_id, academic_year_id, allocation_date, promoted_from_id, is_current, school_id) VALUES (%s, %s, %s, NOW(), %s, TRUE, %s)",
                                 (student['student_id'], new_class_id, new_class['ay_id'], student['id'], self.school_id))
            self.cursor.execute("UPDATE class_allocation SET is_current = FALSE WHERE class_id = %s AND is_current = TRUE AND school_id = %s", (old_class_id, self.school_id))
            self.cursor.execute("INSERT INTO class_promotion_log (batch_id, old_class_id, new_class_id, student_count, promotion_date, promoted_by, notes, school_id) VALUES (%s, %s, %s, %s, CURDATE(), %s, %s, %s)",
                             (batch_id, old_class_id, new_class_id, len(students), promoted_by, notes, self.school_id))
            self.connection.commit()
            return {'success': True, 'students_promoted': len(students), 'message': f"Promoted {len(students)} students."}
        except Exception as e:
            self.connection.rollback()
            raise e

    def get_all_streams(self) -> List[Dict]:
        self.cursor.execute("SELECT id, code, name, is_active FROM stream_settings WHERE school_id = %s ORDER BY code", (self.school_id,))
        return self.cursor.fetchall()

    def add_stream(self, code: str, name: str):
        self.cursor.execute("INSERT INTO stream_settings (school_id, code, name, is_active) VALUES (%s, %s, %s, TRUE)", (self.school_id, code, name))
        self.connection.commit()

    def toggle_stream(self, stream_id: int):
        self.cursor.execute("UPDATE stream_settings SET is_active = NOT is_active WHERE id = %s AND school_id = %s", (stream_id, self.school_id))
        self.connection.commit()

    def delete_stream(self, stream_id: int):
        self.cursor.execute("DELETE FROM stream_settings WHERE id = %s AND school_id = %s", (stream_id, self.school_id))
        self.connection.commit()

    def get_active_subjects(self) -> List[Dict]:
        try:
            self.cursor.execute("SELECT subjectNo as id, code, subjName as name FROM subjects WHERE school_id = %s ORDER BY code", (self.school_id,))
        except:
             self.cursor.execute("SELECT id, code, name FROM subjects WHERE school_id = %s ORDER BY code", (self.school_id,))
        return self.cursor.fetchall()

    def get_allocated_subject_ids(self, class_id: int) -> List[int]:
        self.cursor.execute("SELECT subject_id FROM class_subjects WHERE class_id = %s AND is_active = TRUE AND school_id = %s", (class_id, self.school_id))
        return [row['subject_id'] for row in self.cursor.fetchall()]

    @audit_log('allocate_subjects_to_class')
    def allocate_subjects_to_class(self, class_id: int, subject_ids: List[int], compulsory: bool = True):
        self.connection.begin()
        try:
            self.cursor.execute("DELETE FROM class_subjects WHERE class_id = %s AND school_id = %s", (class_id, self.school_id))
            for sid in subject_ids:
                self.cursor.execute("INSERT INTO class_subjects (class_id, subject_id, is_compulsory, is_active, school_id) VALUES (%s, %s, %s, TRUE, %s)", (class_id, sid, compulsory, self.school_id))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise e

    def get_active_teachers(self) -> List[Dict]:
        self.cursor.execute("SELECT userNo, username, StaffID FROM users WHERE access_flag = 1 AND school_id = %s ORDER BY username", (self.school_id,))
        return self.cursor.fetchall()

    @audit_log('set_class_teacher')
    def set_class_teacher(self, class_id: int, teacher_id: int, ay_id: int):
        self.connection.begin()
        try:
            self.cursor.execute("UPDATE class_teachers SET is_active = FALSE WHERE class_id = %s AND academic_year_id = %s AND school_id = %s", (class_id, ay_id, self.school_id))
            self.cursor.execute("INSERT INTO class_teachers (teacher_id, class_id, academic_year_id, is_active, school_id) VALUES (%s, %s, %s, TRUE, %s)", (teacher_id, class_id, ay_id, self.school_id))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise e

    @audit_log('allocate_teacher_to_subject')
    def allocate_teacher_to_class_subject(self, teacher_id: int, class_id: int, subject_id: int, ay_id: int):
        self.connection.begin()
        try:
            self.cursor.execute("UPDATE teacher_allocations SET is_active = FALSE WHERE class_id = %s AND subject_id = %s AND academic_year_id = %s AND school_id = %s", (class_id, subject_id, ay_id, self.school_id))
            self.cursor.execute("INSERT INTO teacher_allocations (teacher_id, class_id, subject_id, academic_year_id, allocation_date, is_active, school_id) VALUES (%s, %s, %s, %s, CURDATE(), TRUE, %s)",
                             (teacher_id, class_id, subject_id, ay_id, self.school_id))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise e

    def get_class_hub_data(self, class_id: int) -> Dict:
        self.cursor.execute("SELECT c.*, ay.year as academic_year_name FROM classes c JOIN academic_years ay ON c.academic_year_id = ay.id WHERE c.classID = %s AND c.school_id = %s", (class_id, self.school_id))
        class_details = self.cursor.fetchone()
        if not class_details: raise ValidationError("Class not found")

        ay_id = class_details['academic_year_id']
        self.cursor.execute("SELECT u.username, u.userNo, u.StaffID FROM class_teachers ct JOIN users u ON ct.teacher_id = u.userNo WHERE ct.class_id = %s AND ct.academic_year_id = %s AND ct.is_active = TRUE AND ct.school_id = %s", (class_id, ay_id, self.school_id))
        class_teacher = self.cursor.fetchone()

        try:
             self.cursor.execute("""
                SELECT s.subjectNo as subject_id, s.code, s.subjName as name, cs.is_compulsory, u.username as teacher_name, u.userNo as teacher_id
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.subjectNo
                LEFT JOIN teacher_allocations ta ON ta.class_id = cs.class_id AND ta.subject_id = s.subjectNo AND ta.is_active = TRUE AND ta.school_id = %s
                LEFT JOIN users u ON ta.teacher_id = u.userNo
                WHERE cs.class_id = %s AND cs.is_active = TRUE AND cs.school_id = %s
            """, (self.school_id, class_id, self.school_id))
        except:
             self.cursor.execute("""
                SELECT s.id as subject_id, s.code, s.name, cs.is_compulsory, u.username as teacher_name, u.userNo as teacher_id
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN teacher_allocations ta ON ta.class_id = cs.class_id AND ta.subject_id = s.id AND ta.is_active = TRUE AND ta.school_id = %s
                LEFT JOIN users u ON ta.teacher_id = u.userNo
                WHERE cs.class_id = %s AND cs.is_active = TRUE AND cs.school_id = %s
            """, (self.school_id, class_id, self.school_id))
        subjects = self.cursor.fetchall()

        self.cursor.execute("SELECT si.AdmNo, si.FName, si.SName, si.Sex as Gender, ca.id as allocation_id FROM class_allocation ca JOIN studentinfo si ON ca.student_id = si.AdmNo WHERE ca.class_id = %s AND ca.is_current = TRUE AND si.school_id = %s ORDER BY si.FName, si.SName", (class_id, self.school_id))
        students = self.cursor.fetchall()

        return {
            'class_details': class_details,
            'class_teacher': class_teacher,
            'subjects': subjects,
            'students': students,
            'all_teachers': self.get_active_teachers(),
            'all_subjects': self.get_active_subjects(),
            'available_students': self.get_available_students(ay_id)
        }

    def get_available_students(self, ay_id: int) -> List[Dict]:
        self.cursor.execute("SELECT AdmNo, FName, SName, Sex as Gender FROM studentinfo WHERE AdmNo NOT IN (SELECT student_id FROM class_allocation WHERE academic_year_id = %s AND is_current = TRUE AND school_id = %s) AND school_id = %s ORDER BY FName, SName", (ay_id, self.school_id, self.school_id))
        return self.cursor.fetchall()

    def get_class_academic_year_id(self, class_id: int) -> int:
        self.cursor.execute("SELECT academic_year_id FROM classes WHERE classID = %s AND school_id = %s", (class_id, self.school_id))
        res = self.cursor.fetchone()
        return res['academic_year_id'] if res else None

    def enroll_all_students_in_class_subjects(self, class_id: int, subject_ids: Optional[List[int]]) -> int:
        self.cursor.execute("SELECT id FROM class_allocation WHERE class_id = %s AND is_current = TRUE AND school_id = %s", (class_id, self.school_id))
        allocs = self.cursor.fetchall()
        if not subject_ids:
            self.cursor.execute("SELECT subject_id FROM class_subjects WHERE class_id = %s AND is_active = TRUE AND school_id = %s", (class_id, self.school_id))
            subject_ids = [s['subject_id'] for s in self.cursor.fetchall()]

        self.connection.begin()
        count = 0
        try:
            for a in allocs:
                for sid in subject_ids:
                    self.cursor.execute("INSERT INTO student_subjects (class_allocation_id, subject_id, enrollment_date, is_active, school_id) VALUES (%s, %s, NOW(), TRUE, %s) ON DUPLICATE KEY UPDATE is_active = TRUE", (a['id'], sid, self.school_id))
                    count += 1
            self.connection.commit()
            return count
        except Exception as e:
            self.connection.rollback()
            raise e

    def enroll_student_in_subjects(self, allocation_id: int, subject_ids: List[int]):
        self.connection.begin()
        try:
            for sid in subject_ids:
                self.cursor.execute("INSERT INTO student_subjects (class_allocation_id, subject_id, enrollment_date, is_active, school_id) VALUES (%s, %s, NOW(), TRUE, %s) ON DUPLICATE KEY UPDATE is_active = TRUE", (allocation_id, sid, self.school_id))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise e

    def get_subjects_for_class_form(self, class_id: int) -> List[Dict]:
        try:
            self.cursor.execute("""
                SELECT s.subjectNo as id, s.code, s.subjName as name
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.subjectNo
                WHERE cs.class_id = %s AND cs.is_active = TRUE AND cs.school_id = %s AND s.school_id = %s
                ORDER BY s.code
            """, (class_id, self.school_id, self.school_id))
        except:
             self.cursor.execute("""
                SELECT s.id as id, s.code, s.name
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.id
                WHERE cs.class_id = %s AND cs.is_active = TRUE AND cs.school_id = %s AND s.school_id = %s
                ORDER BY s.code
            """, (class_id, self.school_id, self.school_id))
        return self.cursor.fetchall()

    def get_classes_by_year(self, year_id: int) -> List[Dict]:
        self.cursor.execute("SELECT classID, display_name, class_group_code, stream_code FROM classes WHERE academic_year_id = %s AND is_active = TRUE AND school_id = %s ORDER BY display_name", (year_id, self.school_id))
        return self.cursor.fetchall()

    def remove_student_from_class(self, allocation_id: int):
        self.cursor.execute("UPDATE class_allocation SET is_current = FALSE WHERE id = %s AND school_id = %s", (allocation_id, self.school_id))
        self.connection.commit()
