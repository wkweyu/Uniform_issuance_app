-- Migration: Enforce school_id on stream_settings (Phase 4 - stream_settings)
-- Ensures all stream settings are tenant-bound and default to school_id=1 for legacy rows.

-- Ensure default school exists
INSERT IGNORE INTO `schools` (`id`, `name`, `code`, `is_active`)
VALUES (1, 'Default School', 'DEFAULT', 1);

-- Backfill null school_id values
UPDATE `stream_settings` SET `school_id` = 1 WHERE `school_id` IS NULL;

-- Make school_id NOT NULL with default 1
ALTER TABLE `stream_settings`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1;

-- Reinforce unique-per-school constraint (drop and recreate to be safe)
ALTER TABLE `stream_settings`
  DROP INDEX `unique_stream_per_school`,
  ADD UNIQUE KEY `unique_stream_per_school` (`school_id`, `code`);

-- Index for active lookups (already exists, keep)
-- No change needed for idx_is_active
