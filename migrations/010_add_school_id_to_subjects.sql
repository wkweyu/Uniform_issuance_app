-- Migration: Add school_id to subjects (Phase 4 - subjects)
-- Assumes schools table exists with id=1.

-- Ensure default school row exists
INSERT IGNORE INTO `schools` (`id`, `name`, `code`, `is_active`)
VALUES (1, 'Default School', 'DEFAULT', 1);

-- Add school_id with default 1 for existing subjects
ALTER TABLE `subjects`
  ADD COLUMN `school_id` INT UNSIGNED NOT NULL DEFAULT 1 AFTER `subjectNo`;

-- Index for tenant lookups
ALTER TABLE `subjects`
  ADD KEY `idx_subjects_school_id` (`school_id`);

-- Foreign key to schools
ALTER TABLE `subjects`
  ADD CONSTRAINT `fk_subjects_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`);
