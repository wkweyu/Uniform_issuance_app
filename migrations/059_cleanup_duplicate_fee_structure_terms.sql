-- Migration 059: Clean up duplicate fee structure term records
-- Deletes orphaned/duplicate fee_structures records created by previous clone operations that share the same scope, version_number, and term_id.

DELETE fs1 FROM fee_structures fs1
INNER JOIN fee_structures fs2
  ON fs1.school_id = fs2.school_id
 AND fs1.academic_year_id = fs2.academic_year_id
 AND (fs1.class_id = fs2.class_id OR (fs1.class_id IS NULL AND fs2.class_id IS NULL))
 AND fs1.class_group_code = fs2.class_group_code
 AND fs1.student_category = fs2.student_category
 AND fs1.version_number = fs2.version_number
 AND fs1.term_id = fs2.term_id
 AND fs1.id > fs2.id;
