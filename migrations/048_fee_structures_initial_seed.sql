-- Migration 048: Seed fee structures for the current academic year.
-- The migration runner records this file in schema_migrations; no manual
-- journal insert is required here.

INSERT INTO fee_structures
    (academic_year_id, term_id, class_group_code, student_category, total_amount, created_by, school_id, class_id)
SELECT DISTINCT
    years.id,
    terms.id,
    groups.code,
    categories.student_category,
    0.00,
    NULL,
    groups.school_id,
    NULL
FROM academic_years years
JOIN class_group_settings groups
    ON groups.school_id = years.school_id
JOIN uniform_term_dates terms
    ON terms.school_id = years.school_id
JOIN (
    SELECT 'Regular' AS student_category
    UNION ALL SELECT 'Day'
    UNION ALL SELECT 'Boarding'
) categories
WHERE years.is_current = TRUE
  AND NOT EXISTS (
      SELECT 1
      FROM fee_structures existing
      WHERE existing.school_id = groups.school_id
        AND existing.academic_year_id = years.id
        AND existing.term_id = terms.id
        AND existing.class_group_code = groups.code
        AND existing.student_category = categories.student_category
        AND (existing.class_id IS NULL OR existing.class_id = 0)
  );

INSERT INTO fee_structure_items
    (fee_structure_id, votehead_id, amount, school_id)
SELECT
    structures.id,
    voteheads.id,
    0.00,
    structures.school_id
FROM fee_structures structures
JOIN fee_voteheads voteheads
    ON voteheads.school_id = structures.school_id
   AND voteheads.is_active = TRUE
WHERE (structures.class_id IS NULL OR structures.class_id = 0)
  AND NOT EXISTS (
      SELECT 1
      FROM fee_structure_items existing
      WHERE existing.fee_structure_id = structures.id
        AND existing.votehead_id = voteheads.id
        AND existing.school_id = structures.school_id
  );
