-- Migration: Add school_id to classes, class_allocation, and classallocation (Phase 4 - Class domain)
-- Assumes the schools table already exists with id=1.

-- Ensure there is at least a default school row
INSERT IGNORE INTO `schools` (`id`, `name`, `code`, `is_active`)
VALUES (1, 'Default School', 'DEFAULT', 1);

-- -------------------------------------------------------------------------
-- 1) classes: attach classes to a school
-- -------------------------------------------------------------------------
ALTER TABLE `classes`
  ADD COLUMN `school_id` INT NOT NULL DEFAULT 1 AFTER `classID`;

ALTER TABLE `classes`
  ADD KEY `idx_classes_school_id` (`school_id`);

ALTER TABLE `classes`
  ADD CONSTRAINT `fk_classes_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- -------------------------------------------------------------------------
-- 2) class_allocation: attach allocations to a school
-- -------------------------------------------------------------------------
ALTER TABLE `class_allocation`
  ADD COLUMN `school_id` INT NOT NULL DEFAULT 1 AFTER `academic_year_id`;

ALTER TABLE `class_allocation`
  ADD KEY `idx_class_allocation_school_id` (`school_id`);

ALTER TABLE `class_allocation`
  ADD CONSTRAINT `fk_class_allocation_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- -------------------------------------------------------------------------
-- 3) classallocation (legacy): attach legacy allocations to a school
-- -------------------------------------------------------------------------
ALTER TABLE `classallocation`
  ADD COLUMN `school_id` INT NOT NULL DEFAULT 1 AFTER `feegrp`;

ALTER TABLE `classallocation`
  ADD KEY `idx_classallocation_school_id` (`school_id`);

ALTER TABLE `classallocation`
  ADD CONSTRAINT `fk_classallocation_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);
