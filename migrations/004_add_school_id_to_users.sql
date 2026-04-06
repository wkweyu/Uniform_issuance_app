-- Migration: Add school_id to users table and backfill existing rows (STEP 2)
-- This migration assumes the schools table already exists.

-- Ensure there is a default school with id = 1 to attach existing users to.
INSERT IGNORE INTO `schools` (`id`, `name`, `code`, `is_active`)
VALUES (1, 'Default School', 'DEFAULT', 1);

-- Add school_id column to users with default 1 so existing rows are set.
ALTER TABLE `users`
  ADD COLUMN `school_id` INT NOT NULL DEFAULT 1 AFTER `_date`;

-- Add index for efficient lookups by school.
ALTER TABLE `users`
  ADD KEY `idx_users_school_id` (`school_id`);

-- Add foreign key constraint linking users to schools.
ALTER TABLE `users`
  ADD CONSTRAINT `fk_users_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);
