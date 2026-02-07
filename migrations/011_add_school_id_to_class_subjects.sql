-- Migration: Add school_id to class_subjects (Phase 4 - class_subjects)
-- Assumes schools table exists with id=1.

-- Ensure default school row exists
INSERT IGNORE INTO `schools` (`id`, `name`, `code`, `is_active`)
VALUES (1, 'Default School', 'DEFAULT', 1);

-- Add school_id with default 1 for existing rows
ALTER TABLE `class_subjects`
  ADD COLUMN `school_id` INT(11) NOT NULL DEFAULT 1 AFTER `id`;

-- Index for tenant lookups
ALTER TABLE `class_subjects`
  ADD KEY `idx_class_subjects_school_id` (`school_id`);

-- Strengthen uniqueness per tenant
ALTER TABLE `class_subjects`
  DROP INDEX `unique_class_subject`,
  ADD UNIQUE KEY `unique_class_subject_per_school` (`school_id`, `class_id`, `subject_id`);

-- Foreign key to schools
ALTER TABLE `class_subjects`
  ADD CONSTRAINT `fk_class_subjects_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`);
