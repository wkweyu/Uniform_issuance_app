-- Migration: Add school_id to parentinfo (Phase 4 - Parents)
-- This migration assumes the schools table already exists with id=1.

-- Ensure there is at least a default school row
INSERT IGNORE INTO `schools` (`id`, `name`, `code`, `is_active`)
VALUES (1, 'Default School', 'DEFAULT', 1);

-- Add school_id column with default 1 so existing parents are attached to the default school
ALTER TABLE `parentinfo`
  ADD COLUMN `school_id` INT NOT NULL DEFAULT 1 AFTER `regDate`;

-- Index for tenant-scoped lookups
ALTER TABLE `parentinfo`
  ADD KEY `idx_parentinfo_school_id` (`school_id`);

-- Foreign key to schools
ALTER TABLE `parentinfo`
  ADD CONSTRAINT `fk_parentinfo_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);
