"""
=============================================================================
Production-Grade Business Logic Module: Class Management System
File: class_management_service.py
Database: schoolmngt

This module provides centralized business logic for:
- Automatic class group assignment
- Stream validation
- Academic year management
- Class promotion engine
- Subject allocation
- Teacher assignment

Usage:
    from class_management_service import ClassManagementService
    service = ClassManagementService(connection)
    service.create_class(academic_year_id, class_group_code, stream_code)
    service.promote_students(old_class_id, new_class_id)
=============================================================================
"""

import pymysql
from datetime import datetime
from enum import Enum
from typing import Dict, List, Tuple, Optional
import logging
import hashlib
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ClassManagementException(Exception):
    """Base exception for class management errors."""
    pass


class ValidationError(ClassManagementException):
    """Raised when validation fails."""
    pass


class PromotionError(ClassManagementException):
    """Raised when promotion fails."""
    pass


class StreamEnum(str, Enum):
    """Allowed streams (settings-driven; update in DB)."""
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ClassGroupEnum(str, Enum):
    """Class group codes (settings-driven; update in DB)."""
    PLAYGROUP_PP2 = "Playgroup-PP2"
    GRADE_1_3 = "Grade 1-3"
    GRADE_4_6 = "Grade 4-6"
    GRADE_7_9 = "Grade 7-9"


class ClassManagementService:
    """
    Centralized service for class, subject, and teacher management.
    
    Architecture:
    - Validate input before DB writes
    - Use transactions for multi-step operations
    - Log all mutations for audit trail
    - Support rollback on error
    """

    def __init__(self, connection: pymysql.Connection):
        """Initialize service with database connection."""
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)

    # =========================================================================
    # 1. CLASS GROUP & STREAM MANAGEMENT
    # =========================================================================

    def get_class_group_by_name(self, class_name: str) -> Optional[str]:
        """
        Automatically determine class group from class name.
        
        Examples:
            "Playgroup" → "Playgroup-PP2"
            "Grade 1" → "Grade 1-3"
            "Grade 5" → "Grade 4-6"
            "Grade 9" → "Grade 7-9"
        
        Returns:
            Class group code (e.g., "Grade 1-3") or None if not found.
        
        Raises:
            ValidationError if class_name is invalid.
        """
        if not class_name or not isinstance(class_name, str):
            raise ValidationError("Class name must be a non-empty string.")

        # Query the mapping table (more flexible than hardcoding)
        self.cursor.execute("""
            SELECT code 
            FROM class_group_settings 
            WHERE (
                FIND_IN_SET(%s, CONCAT_WS(',', min_grade, max_grade))
                OR min_grade = %s
            )
            LIMIT 1
        """, (class_name, class_name))
        
        result = self.cursor.fetchone()
        if result:
            return result['code']
        
        # Fallback: hardcoded mapping (for legacy classes)
        CLASS_GROUPS = {
            'Playgroup': 'Playgroup-PP2',
            'Pre-Primary 1': 'Playgroup-PP2',
            'Pre-Primary 2': 'Playgroup-PP2',
            'Grade 1': 'Grade 1-3',
            'Grade 2': 'Grade 1-3',
            'Grade 3': 'Grade 1-3',
            'Grade 4': 'Grade 4-6',
            'Grade 5': 'Grade 4-6',
            'Grade 6': 'Grade 4-6',
            'Grade 7': 'Grade 7-9',
            'Grade 8': 'Grade 7-9',
            'Grade 9': 'Grade 7-9',
        }
        
        return CLASS_GROUPS.get(class_name)

    def validate_stream(self, stream_code: str, school_id: int = 1) -> bool:
        """
        Validate that stream is in allowed list (settings-driven).
        
        Args:
            stream_code: e.g., "A", "B"
            school_id: For multi-school support
        
        Returns:
            True if valid, False otherwise.
        """
        self.cursor.execute("""
            SELECT id FROM stream_settings 
            WHERE code = %s AND school_id = %s AND is_active = TRUE
        """, (stream_code, school_id))
        
        return self.cursor.fetchone() is not None

    def get_allowed_streams(self, school_id: int = 1) -> List[Dict]:
        """Get list of allowed streams for a school."""
        self.cursor.execute("""
            SELECT code, name 
            FROM stream_settings 
            WHERE school_id = %s AND is_active = TRUE
            ORDER BY code
        """, (school_id,))
        
        return self.cursor.fetchall()

    # =========================================================================
    # 2. ACADEMIC YEAR MANAGEMENT
    # =========================================================================

    def get_current_academic_year(self) -> Optional[Dict]:
        """Get the current academic year record."""
        self.cursor.execute("""
            SELECT id, year, name, start_date, end_date, is_current
            FROM academic_years 
            WHERE is_current = TRUE
            LIMIT 1
        """)
        
        return self.cursor.fetchone()

    def set_current_academic_year(self, year: int) -> bool:
        """Set a specific year as current (one-per-school)."""
        try:
            self.connection.begin()
            
            # Unset previous current year
            self.cursor.execute("""
                UPDATE academic_years SET is_current = FALSE 
                WHERE is_current = TRUE
            """)
            
            # Set new current year
            self.cursor.execute("""
                UPDATE academic_years SET is_current = TRUE 
                WHERE year = %s
            """, (year,))
            
            self.connection.commit()
            logger.info(f"Set academic year {year} as current.")
            return True
        except pymysql.Error as e:
            self.connection.rollback()
            logger.error(f"Failed to set academic year: {str(e)}")
            raise ClassManagementException(f"Failed to set academic year: {str(e)}")

    def create_academic_year(self, year: int, start_date: str, end_date: str) -> int:
        """
        Create a new academic year.
        
        Args:
            year: e.g., 2026
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
        
        Returns:
            ID of created year
        
        Raises:
            ValidationError if year already exists
        """
        if year < 1900 or year > 2100:
            raise ValidationError("Invalid year range.")
        
        try:
            self.cursor.execute("""
                INSERT INTO academic_years (year, name, start_date, end_date, is_current)
                VALUES (%s, %s, %s, %s, FALSE)
            """, (year, f"{year}-{year + 1}", start_date, end_date))
            
            self.connection.commit()
            logger.info(f"Created academic year {year}.")
            return self.cursor.lastrowid
        except pymysql.IntegrityError:
            raise ValidationError(f"Academic year {year} already exists.")

    def get_all_academic_years(self) -> List[Dict]:
        """Get all academic years ordered by year descending."""
        self.cursor.execute("""
            SELECT id, year, name, start_date, end_date, is_current
            FROM academic_years 
            ORDER BY year DESC
        """)
        
        return self.cursor.fetchall()

    def get_class_groups(self) -> Dict[str, Dict]:
        """Get all class groups from settings table."""
        self.cursor.execute("""
            SELECT code, name 
            FROM class_group_settings 
            ORDER BY code
        """)
        
        results = self.cursor.fetchall()
        return {row['code']: {'name': row['name']} for row in results}

    # =========================================================================
    # 3. CLASS CREATION & MANAGEMENT
    # =========================================================================

    def create_class(
        self,
        academic_year_id: int,
        class_group_code: str,
        stream_code: str,
        created_by: int = None,
        class_name: str = None
    ) -> Dict:
        """
        Create a new class with automatic validation.
        
        Args:
            academic_year_id: FK to academic_years
            class_group_code: e.g., "Grade 1-3"
            stream_code: e.g., "A"
            created_by: User ID of creator
            class_name: Custom class name (e.g., "Grade 1A")
        
        Returns:
            Created class record
        
        Raises:
            ValidationError if validation fails
            ClassManagementException if creation fails
        """
        # Validation Phase
        if not self._validate_academic_year(academic_year_id):
            raise ValidationError(f"Academic year ID {academic_year_id} not found.")
        
        if not self._validate_class_group(class_group_code):
            raise ValidationError(f"Invalid class group: {class_group_code}")
        
        if not self.validate_stream(stream_code):
            raise ValidationError(f"Invalid stream: {stream_code}")
        
        # Get class group name for display
        self.cursor.execute("""
            SELECT name FROM class_group_settings WHERE code = %s
        """, (class_group_code,))
        cg_result = self.cursor.fetchone()
        class_group_name = cg_result['name'] if cg_result else class_group_code
        
        # Generate display name - use class_name if provided, otherwise auto-generate
        if class_name:
            display_name = f"{class_name} – Stream {stream_code}"
        else:
            display_name = f"{class_group_name} – Stream {stream_code}"
        
        # Creation Phase (with transaction)
        try:
            self.connection.begin()
            
            self.cursor.execute("""
                INSERT INTO classes (
                    academic_year_id, class_group_code, stream_code,
                    display_name, is_active, created_by, created_at, updated_at,
                    class_name, class_group
                )
                VALUES (%s, %s, %s, %s, TRUE, %s, NOW(), NOW(), %s, %s)
            """, (
                academic_year_id,
                class_group_code,
                stream_code,
                display_name,
                created_by,
                class_name or display_name,  # class_name (legacy)
                class_group_code  # class_group (legacy)
            ))
            
            class_id = self.cursor.lastrowid
            self.connection.commit()
            
            logger.info(f"Created class {display_name} (ID: {class_id})")
            
            # Return created record
            self.cursor.execute("SELECT * FROM classes WHERE classID = %s", (class_id,))
            return self.cursor.fetchone()
            
        except pymysql.IntegrityError as e:
            self.connection.rollback()
            raise ValidationError(f"Class already exists for this year/stream combination: {str(e)}")
        except pymysql.Error as e:
            self.connection.rollback()
            raise ClassManagementException(f"Failed to create class: {str(e)}")

    def _validate_academic_year(self, academic_year_id: int) -> bool:
        """Check if academic year exists."""
        self.cursor.execute(
            "SELECT id FROM academic_years WHERE id = %s",
            (academic_year_id,)
        )
        return self.cursor.fetchone() is not None

    def _validate_class_group(self, class_group_code: str) -> bool:
        """Check if class group exists in settings."""
        self.cursor.execute(
            "SELECT id FROM class_group_settings WHERE code = %s",
            (class_group_code,)
        )
        return self.cursor.fetchone() is not None

    # =========================================================================
    # 4. CLASS PROMOTION ENGINE
    # =========================================================================

    def promote_students(
        self,
        old_class_id: int,
        new_class_id: int,
        promoted_by: int = None,
        notes: str = ""
    ) -> Dict:
        """
        Promote all students from one class to another.
        
        Workflow:
        1. Validate both classes exist and belong to consecutive years
        2. Check that all students can be promoted
        3. Begin transaction
        4. Create new allocations with promoted_from reference
        5. Update old allocations to is_current = FALSE
        6. Log promotion in audit table
        7. Commit transaction
        
        Args:
            old_class_id: Source class ID
            new_class_id: Destination class ID
            promoted_by: User ID of promoter
            notes: Promotion notes
        
        Returns:
            {
                'success': bool,
                'students_promoted': int,
                'batch_id': str,
                'message': str
            }
        
        Raises:
            PromotionError if validation fails
        """
        batch_id = str(uuid.uuid4())[:8]  # Short batch identifier
        
        try:
            # Phase 1: Validation
            self.cursor.execute("""
                SELECT c.classID, c.academic_year_id, c.display_name, ay.year
                FROM classes c
                JOIN academic_years ay ON c.academic_year_id = ay.id
                WHERE c.classID = %s
            """, (old_class_id,))
            old_class = self.cursor.fetchone()
            
            if not old_class:
                raise PromotionError(f"Old class (ID: {old_class_id}) not found.")
            
            self.cursor.execute("""
                SELECT c.classID, c.academic_year_id, c.display_name, ay.year
                FROM classes c
                JOIN academic_years ay ON c.academic_year_id = ay.id
                WHERE c.classID = %s
            """, (new_class_id,))
            new_class = self.cursor.fetchone()
            
            if not new_class:
                raise PromotionError(f"New class (ID: {new_class_id}) not found.")
            
            # Validate academic year progression
            old_year = old_class['year']
            new_year = new_class['year']
            if new_year != old_year + 1:
                raise PromotionError(
                    f"Cannot promote from year {old_year} to {new_year}. "
                    "Must be consecutive years."
                )
            
            # Get students to promote
            self.cursor.execute("""
                SELECT id, student_id, academic_year_id
                FROM class_allocation
                WHERE class_id = %s AND is_current = TRUE
            """, (old_class_id,))
            students = self.cursor.fetchall()
            student_count = len(students)
            
            if student_count == 0:
                raise PromotionError("No students to promote in this class.")
            
            # Phase 2: Transaction (Create new allocations + update old)
            self.connection.begin()
            
            for student in students:
                # Create new allocation in new class
                self.cursor.execute("""
                    INSERT INTO class_allocation (
                        student_id, class_id, academic_year_id,
                        allocation_date, promoted_from_id, is_current
                    )
                    VALUES (%s, %s, %s, NOW(), %s, TRUE)
                """, (
                    student['student_id'],
                    new_class_id,
                    new_class['academic_year_id'],
                    student['id']  # Reference to old allocation
                ))
                
                # Copy subjects from old class to new allocation
                # (if student had specific subject selections)
                self.cursor.execute("""
                    SELECT subject_id FROM student_subjects
                    WHERE class_allocation_id = %s AND is_active = TRUE
                """, (student['id'],))
                subjects = self.cursor.fetchall()
                
                new_allocation_id = self.cursor.lastrowid
                
                # Enroll student in new subjects (if any were selected)
                if subjects:
                    for subj in subjects:
                        self.cursor.execute("""
                            INSERT INTO student_subjects (
                                class_allocation_id, subject_id,
                                enrollment_date, is_active
                            )
                            VALUES (%s, %s, NOW(), TRUE)
                            ON DUPLICATE KEY UPDATE is_active = TRUE
                        """, (new_allocation_id, subj['subject_id']))
            
            # Update old allocations to not current
            self.cursor.execute("""
                UPDATE class_allocation
                SET is_current = FALSE
                WHERE class_id = %s AND is_current = TRUE
            """, (old_class_id,))
            
            # Phase 3: Audit Log
            self.cursor.execute("""
                INSERT INTO class_promotion_log (
                    batch_id, old_class_id, new_class_id,
                    student_count, promotion_date, promoted_by, notes
                )
                VALUES (%s, %s, %s, %s, CURDATE(), %s, %s)
            """, (
                batch_id,
                old_class_id,
                new_class_id,
                student_count,
                promoted_by,
                notes
            ))
            
            self.connection.commit()
            
            logger.info(
                f"Promoted {student_count} students from class {old_class['display_name']} "
                f"to {new_class['display_name']} (batch: {batch_id})"
            )
            
            return {
                'success': True,
                'students_promoted': student_count,
                'batch_id': batch_id,
                'message': f"✓ Successfully promoted {student_count} students from "
                           f"{old_class['display_name']} to {new_class['display_name']}"
            }
            
        except PromotionError as e:
            self.connection.rollback()
            logger.error(f"Promotion validation error: {str(e)}")
            raise
        except pymysql.Error as e:
            self.connection.rollback()
            logger.error(f"Promotion database error: {str(e)}")
            raise PromotionError(f"Promotion failed: {str(e)}")

    # =========================================================================
    # 5. SUBJECT MANAGEMENT
    # =========================================================================

    def allocate_subjects_to_class(
        self,
        class_id: int,
        subject_ids: List[int],
        compulsory: bool = True
    ) -> bool:
        """
        Allocate a set of subjects to a class.
        
        Args:
            class_id: Target class
            subject_ids: List of subject IDs
            compulsory: Mark as compulsory for all students
        
        Returns:
            True if successful
        """
        try:
            self.connection.begin()
            
            # Clear existing allocations
            self.cursor.execute("""
                DELETE FROM class_subjects WHERE class_id = %s
            """, (class_id,))
            
            # Add new allocations
            for subject_id in subject_ids:
                self.cursor.execute("""
                    INSERT INTO class_subjects (
                        class_id, subject_id, is_compulsory, is_active
                    )
                    VALUES (%s, %s, %s, TRUE)
                """, (class_id, subject_id, compulsory))
            
            self.connection.commit()
            logger.info(f"Allocated {len(subject_ids)} subjects to class {class_id}")
            return True
            
        except pymysql.Error as e:
            self.connection.rollback()
            logger.error(f"Failed to allocate subjects: {str(e)}")
            raise ClassManagementException(f"Failed to allocate subjects: {str(e)}")

    def enroll_student_in_subjects(
        self,
        class_allocation_id: int,
        subject_ids: List[int]
    ) -> bool:
        """
        Enroll a student in specific subjects within their class.
        Enforces: subject_ids ⊆ class_subjects
        
        Args:
            class_allocation_id: Student's allocation ID
            subject_ids: List of subject IDs to enroll in
        
        Returns:
            True if successful
        
        Raises:
            ValidationError if subject not in class
        """
        try:
            # Get class ID from allocation
            self.cursor.execute("""
                SELECT class_id FROM class_allocation WHERE id = %s
            """, (class_allocation_id,))
            alloc = self.cursor.fetchone()
            
            if not alloc:
                raise ValidationError("Class allocation not found.")
            
            class_id = alloc['class_id']
            
            # Validate all subjects are in class
            self.cursor.execute("""
                SELECT GROUP_CONCAT(subject_id) AS subject_ids
                FROM class_subjects
                WHERE class_id = %s AND is_active = TRUE
            """, (class_id,))
            
            result = self.cursor.fetchone()
            allowed_subjects = set(map(int, result['subject_ids'].split(','))) if result['subject_ids'] else set()
            
            provided_subjects = set(subject_ids)
            invalid_subjects = provided_subjects - allowed_subjects
            
            if invalid_subjects:
                raise ValidationError(
                    f"Subjects {invalid_subjects} not allocated to this class."
                )
            
            # Enroll student
            self.connection.begin()
            
            for subject_id in subject_ids:
                self.cursor.execute("""
                    INSERT INTO student_subjects (
                        class_allocation_id, subject_id, enrollment_date, is_active
                    )
                    VALUES (%s, %s, NOW(), TRUE)
                    ON DUPLICATE KEY UPDATE is_active = TRUE
                """, (class_allocation_id, subject_id))
            
            self.connection.commit()
            logger.info(f"Enrolled student in {len(subject_ids)} subjects")
            return True
            
        except ValidationError:
            raise
        except pymysql.Error as e:
            self.connection.rollback()
            logger.error(f"Failed to enroll student in subjects: {str(e)}")
            raise ClassManagementException(f"Failed to enroll: {str(e)}")

    # =========================================================================
    # 6. TEACHER ALLOCATION
    # =========================================================================

    def allocate_teacher_to_class_subject(
        self,
        teacher_id: int,
        class_id: int,
        subject_id: int,
        academic_year_id: int
    ) -> bool:
        """
        Allocate a teacher to teach a specific subject in a class.
        Enforces: one teacher per class-subject combination per year
        
        Args:
            teacher_id: FK to users.userNo
            class_id: FK to classes.classID
            subject_id: FK to subjects.id
            academic_year_id: FK to academic_years.id
        
        Returns:
            True if successful
        
        Raises:
            ValidationError if subject not in class
        """
        try:
            # Validate subject is in class
            self.cursor.execute("""
                SELECT id FROM class_subjects
                WHERE class_id = %s AND subject_id = %s AND is_active = TRUE
            """, (class_id, subject_id))
            
            if not self.cursor.fetchone():
                raise ValidationError("Subject not allocated to this class.")
            
            # Remove existing teacher for this class-subject
            self.cursor.execute("""
                UPDATE teacher_allocations
                SET is_active = FALSE
                WHERE class_id = %s AND subject_id = %s AND academic_year_id = %s
            """, (class_id, subject_id, academic_year_id))
            
            # Allocate new teacher
            self.cursor.execute("""
                INSERT INTO teacher_allocations (
                    teacher_id, class_id, subject_id, academic_year_id, is_active
                )
                VALUES (%s, %s, %s, %s, TRUE)
            """, (teacher_id, class_id, subject_id, academic_year_id))
            
            self.connection.commit()
            logger.info(f"Allocated teacher {teacher_id} to class {class_id} subject {subject_id}")
            return True
            
        except pymysql.Error as e:
            self.connection.rollback()
            logger.error(f"Failed to allocate teacher: {str(e)}")
            raise ClassManagementException(f"Failed to allocate teacher: {str(e)}")

    # =========================================================================
    # 7. REPORTING QUERIES
    # =========================================================================

    def get_class_list_by_year(self, academic_year_id: int) -> List[Dict]:
        """Get all active classes for a year."""
        self.cursor.execute("""
            SELECT c.classID, c.display_name, c.class_group_code, c.stream_code, ay.name as year
            FROM classes c
            JOIN academic_years ay ON c.academic_year_id = ay.id
            WHERE c.academic_year_id = %s AND c.is_active = TRUE
            ORDER BY c.class_group_code, c.stream_code
        """, (academic_year_id,))
        
        return self.cursor.fetchall()

    def get_students_in_class(self, class_id: int) -> List[Dict]:
        """Get all students currently in a class."""
        self.cursor.execute("""
            SELECT
                ca.id,
                si.AdmNo,
                si.FName,
                si.SName,
                c.display_name,
                ay.name as year
            FROM class_allocation ca
            JOIN studentinfo si ON ca.student_id = si.AdmNo
            JOIN classes c ON ca.class_id = c.classID
            JOIN academic_years ay ON ca.academic_year_id = ay.id
            WHERE ca.class_id = %s AND ca.is_current = TRUE
            ORDER BY si.FName, si.SName
        """, (class_id,))
        
        return self.cursor.fetchall()

    def get_student_subjects(self, class_allocation_id: int) -> List[Dict]:
        """Get all subjects a student is enrolled in."""
        self.cursor.execute("""
            SELECT s.id, s.code, s.name
            FROM student_subjects ss
            JOIN subjects s ON ss.subject_id = s.id
            WHERE ss.class_allocation_id = %s AND ss.is_active = TRUE
            ORDER BY s.name
        """, (class_allocation_id,))
        
        return self.cursor.fetchall()

    def get_teacher_assignments(self, academic_year_id: int) -> List[Dict]:
        """Get all teacher-class-subject assignments for a year."""
        self.cursor.execute("""
            SELECT
                ta.id,
                u.username as teacher_name,
                c.display_name as class_name,
                s.code as subject_code,
                s.name as subject_name
            FROM teacher_allocations ta
            JOIN users u ON ta.teacher_id = u.userNo
            JOIN classes c ON ta.class_id = c.classID
            JOIN subjects s ON ta.subject_id = s.id
            WHERE ta.academic_year_id = %s AND ta.is_active = TRUE
            ORDER BY c.display_name, s.name
        """, (academic_year_id,))
        
        return self.cursor.fetchall()

    def get_promotion_history(self, student_id: int) -> List[Dict]:
        """Get promotion history for a student."""
        self.cursor.execute("""
            SELECT
                ca.id,
                c.display_name as class_name,
                ay.name as year,
                ca.allocation_date,
                ca.promoted_from_id
            FROM class_allocation ca
            JOIN classes c ON ca.class_id = c.classID
            JOIN academic_years ay ON ca.academic_year_id = ay.id
            WHERE ca.student_id = %s
            ORDER BY ay.year DESC
        """, (student_id,))
        
        return self.cursor.fetchall()


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

def example_create_class():
    """Example: Create a new class."""
    import pymysql
    
    connection = pymysql.connect(
        host='localhost',
        user='schooluser',
        password='jbs',
        database='schoolmngt'
    )
    
    service = ClassManagementService(connection)
    
    try:
        # Create class for current year
        ay = service.get_current_academic_year()
        class_rec = service.create_class(
            academic_year_id=ay['id'],
            class_group_code='Grade 1-3',
            stream_code='A',
            created_by=1
        )
        print(f"✓ Created class: {class_rec['display_name']}")
    finally:
        connection.close()


def example_promote_students():
    """Example: Promote students to next class."""
    import pymysql
    
    connection = pymysql.connect(
        host='localhost',
        user='schooluser',
        password='jbs',
        database='schoolmngt'
    )
    
    service = ClassManagementService(connection)
    
    try:
        result = service.promote_students(
            old_class_id=1,  # Grade 1 – Stream A (2025)
            new_class_id=5,  # Grade 2 – Stream A (2026)
            promoted_by=1,
            notes="Annual promotion end of year 2025"
        )
        print(result['message'])
    finally:
        connection.close()


if __name__ == "__main__":
    # Uncomment to test:
    # example_create_class()
    # example_promote_students()
    pass
