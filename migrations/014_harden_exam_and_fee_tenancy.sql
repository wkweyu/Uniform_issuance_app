-- Migration: finish tenant hardening for exam and fee tables that are already school-aware in the service layer.

-- -------------------------------------------------------------------------
-- 1) grading_scales: add tenant ownership and convert global unique name to
--    school-scoped uniqueness.
-- -------------------------------------------------------------------------
ALTER TABLE `grading_scales`
  ADD COLUMN `school_id` INT NULL AFTER `is_default`;

UPDATE `grading_scales`
SET `school_id` = 1
WHERE `school_id` IS NULL;

ALTER TABLE `grading_scales`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1;

ALTER TABLE `grading_scales`
  ADD KEY `idx_grading_scales_school_id` (`school_id`);

ALTER TABLE `grading_scales`
  ADD CONSTRAINT `fk_grading_scales_school_id`
  FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

ALTER TABLE `grading_scales`
  DROP INDEX `name`;

ALTER TABLE `grading_scales`
  ADD UNIQUE KEY `uq_grading_scales_school_name` (`school_id`, `name`);

-- -------------------------------------------------------------------------
-- 2) grading_details: add tenant ownership and a scoped uniqueness/index.
-- -------------------------------------------------------------------------
ALTER TABLE `grading_details`
  ADD COLUMN `school_id` INT NULL AFTER `principal_remarks`;

UPDATE `grading_details` gd
JOIN `grading_scales` gs ON gd.`scale_id` = gs.`id`
SET gd.`school_id` = gs.`school_id`
WHERE gd.`school_id` IS NULL;

UPDATE `grading_details`
SET `school_id` = 1
WHERE `school_id` IS NULL;

ALTER TABLE `grading_details`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1;

ALTER TABLE `grading_details`
  ADD KEY `idx_grading_details_school_id` (`school_id`),
  ADD KEY `idx_grading_details_school_scale` (`school_id`, `scale_id`);

ALTER TABLE `grading_details`
  ADD CONSTRAINT `fk_grading_details_school_id`
  FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

ALTER TABLE `grading_details`
  ADD UNIQUE KEY `uq_grading_details_school_scale_grade` (`school_id`, `scale_id`, `grade`);

-- -------------------------------------------------------------------------
-- 3) exam_series: add tenant ownership with a best-effort backfill from
--    academic_years.
-- -------------------------------------------------------------------------
ALTER TABLE `exam_series`
  ADD COLUMN `school_id` INT NULL AFTER `created_by`;

UPDATE `exam_series` es
JOIN `academic_years` ay ON es.`academic_year_id` = ay.`id`
SET es.`school_id` = ay.`school_id`
WHERE es.`school_id` IS NULL;

UPDATE `exam_series`
SET `school_id` = 1
WHERE `school_id` IS NULL;

ALTER TABLE `exam_series`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1;

ALTER TABLE `exam_series`
  ADD KEY `idx_exam_series_school_id` (`school_id`);

ALTER TABLE `exam_series`
  ADD CONSTRAINT `fk_exam_series_school_id`
  FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- -------------------------------------------------------------------------
-- 4) exam_marks: add tenant ownership with backfill from exam_series and
--    studentinfo.
-- -------------------------------------------------------------------------
ALTER TABLE `exam_marks`
  ADD COLUMN `school_id` INT NULL AFTER `p_remarks`;

UPDATE `exam_marks` em
JOIN `exam_series` es ON em.`exam_id` = es.`id`
SET em.`school_id` = es.`school_id`
WHERE em.`school_id` IS NULL;

UPDATE `exam_marks` em
JOIN `studentinfo` si ON em.`student_id` = si.`AdmNo`
SET em.`school_id` = si.`school_id`
WHERE em.`school_id` IS NULL;

UPDATE `exam_marks`
SET `school_id` = 1
WHERE `school_id` IS NULL;

ALTER TABLE `exam_marks`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1;

ALTER TABLE `exam_marks`
  ADD KEY `idx_exam_marks_school_id` (`school_id`),
  ADD KEY `idx_exam_marks_school_exam` (`school_id`, `exam_id`);

ALTER TABLE `exam_marks`
  ADD CONSTRAINT `fk_exam_marks_school_id`
  FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- -------------------------------------------------------------------------
-- 5) exam_classes: ensure the table exists and carries tenant ownership.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `exam_classes` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `exam_id` INT NOT NULL,
  `class_id` INT NOT NULL,
  `school_id` INT NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exam_classes_school_exam_class` (`school_id`, `exam_id`, `class_id`),
  KEY `idx_exam_classes_exam_id` (`exam_id`),
  KEY `idx_exam_classes_class_id` (`class_id`),
  KEY `idx_exam_classes_school_id` (`school_id`),
  CONSTRAINT `fk_exam_classes_exam_id` FOREIGN KEY (`exam_id`) REFERENCES `exam_series` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_classes_class_id` FOREIGN KEY (`class_id`) REFERENCES `classes` (`classID`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

ALTER TABLE `exam_classes`
  ADD COLUMN `school_id` INT NULL AFTER `class_id`;

UPDATE `exam_classes` ec
JOIN `exam_series` es ON ec.`exam_id` = es.`id`
SET ec.`school_id` = es.`school_id`
WHERE ec.`school_id` IS NULL;

UPDATE `exam_classes`
SET `school_id` = 1
WHERE `school_id` IS NULL;

ALTER TABLE `exam_classes`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1;

ALTER TABLE `exam_classes`
  ADD KEY `idx_exam_classes_school_id` (`school_id`);

ALTER TABLE `exam_classes`
  ADD KEY `idx_exam_classes_exam_id` (`exam_id`);

ALTER TABLE `exam_classes`
  ADD CONSTRAINT `fk_exam_classes_school_scope`
  FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

ALTER TABLE `exam_classes`
  DROP INDEX `unique_exam_class`;

ALTER TABLE `exam_classes`
  ADD UNIQUE KEY `uq_exam_classes_school_exam_class` (`school_id`, `exam_id`, `class_id`);

-- -------------------------------------------------------------------------
-- 6) fee_structures: extend uniqueness to include school_id so different
--    schools can define the same term/class/category combinations safely.
-- -------------------------------------------------------------------------
ALTER TABLE `fee_structures`
  ADD KEY `idx_fee_structures_academic_year_id` (`academic_year_id`);

ALTER TABLE `fee_structures`
  DROP INDEX `unique_structure_scope`;

ALTER TABLE `fee_structures`
  ADD UNIQUE KEY `unique_structure_scope` (`school_id`, `academic_year_id`, `term_id`, `class_group_code`, `student_category`, `class_id`);

-- -------------------------------------------------------------------------
-- 7) fee_adjustments: add tenant ownership to match the scoped fee services.
-- -------------------------------------------------------------------------
ALTER TABLE `fee_adjustments`
  ADD COLUMN `school_id` INT NULL AFTER `approved_by`;

UPDATE `fee_adjustments` fa
JOIN `studentinfo` si ON fa.`admno` = si.`AdmNo`
SET fa.`school_id` = si.`school_id`
WHERE fa.`school_id` IS NULL;

UPDATE `fee_adjustments`
SET `school_id` = 1
WHERE `school_id` IS NULL;

ALTER TABLE `fee_adjustments`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1;

ALTER TABLE `fee_adjustments`
  ADD KEY `idx_fee_adjustments_school_id` (`school_id`),
  ADD KEY `idx_fee_adjustments_school_admno` (`school_id`, `admno`);

ALTER TABLE `fee_adjustments`
  ADD CONSTRAINT `fk_fee_adjustments_school_id`
  FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);