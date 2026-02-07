-- Migration: Add school_id to studentinfo (Phase 4 - Students)
-- This migration assumes the schools table already exists with id=1.

-- Ensure there is at least a default school row
INSERT IGNORE INTO `schools` (`id`, `name`, `code`, `is_active`)
VALUES (1, 'Default School', 'DEFAULT', 1);

-- Add school_id column with default 1 so existing students are attached to the default school
ALTER TABLE `studentinfo`
  ADD COLUMN `school_id` INT UNSIGNED NOT NULL DEFAULT 1 AFTER `student_group_id`;

-- Index for tenant-scoped lookups
ALTER TABLE `studentinfo`
  ADD KEY `idx_studentinfo_school_id` (`school_id`);

-- Foreign key to schools
ALTER TABLE `studentinfo`
  ADD CONSTRAINT `fk_studentinfo_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);
