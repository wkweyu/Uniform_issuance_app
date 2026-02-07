-- Migration: Add school_id to uniform_term_dates (Phase 4 - Term Dates)
-- This migration assumes the schools table already exists with id=1.

-- Ensure there is at least a default school row
INSERT IGNORE INTO `schools` (`id`, `name`, `code`, `is_active`)
VALUES (1, 'Default School', 'DEFAULT', 1);

-- Add school_id column with default 1 so existing term records are attached to the default school
ALTER TABLE `uniform_term_dates`
  ADD COLUMN `school_id` INT(11) NOT NULL DEFAULT 1;

-- Index for tenant-scoped lookups
ALTER TABLE `uniform_term_dates`
  ADD KEY `idx_uniform_term_dates_school_id` (`school_id`);

-- Foreign key to schools
ALTER TABLE `uniform_term_dates`
  ADD CONSTRAINT `fk_uniform_term_dates_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);
