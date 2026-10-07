-- Migration 058: Drop unique index on fee_structures to support versioning (multiple versions per scope)
-- Fee structure versioning allows multiple DRAFT, APPROVED, ACTIVE, and ARCHIVED versions for the same (school_id, academic_year_id, term_id, class_group_code, student_category, class_id).

ALTER TABLE `fee_structures`
  DROP INDEX `unique_structure_scope`;
