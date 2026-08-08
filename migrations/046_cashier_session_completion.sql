-- Migration 046: Complete tenant-scoped cashier session accountability controls.

CREATE TABLE IF NOT EXISTS `cashier_session_settings` (
  `school_id` INT NOT NULL PRIMARY KEY,
  `variance_approval_threshold` DECIMAL(15, 2) NOT NULL DEFAULT 0.00,
  `updated_by` INT NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY `idx_cashier_session_settings_updated_by` (`updated_by`)
) ENGINE=InnoDB;

ALTER TABLE `cashier_sessions`
  ADD COLUMN IF NOT EXISTS `opening_float` DECIMAL(15, 2) NOT NULL DEFAULT 0.00 AFTER `opened_by`,
  ADD COLUMN IF NOT EXISTS `variance_approval_threshold` DECIMAL(15, 2) NOT NULL DEFAULT 0.00 AFTER `opening_float`,
  ADD COLUMN IF NOT EXISTS `variance_reason` VARCHAR(500) NULL AFTER `closure_notes`,
  ADD COLUMN IF NOT EXISTS `reopened_at` DATETIME NULL AFTER `approved_at`,
  ADD COLUMN IF NOT EXISTS `reopened_by` INT NULL AFTER `reopened_at`,
  ADD COLUMN IF NOT EXISTS `reopen_reason` VARCHAR(500) NULL AFTER `reopened_by`;

CREATE TABLE IF NOT EXISTS `cashier_session_events` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `cashier_session_id` INT NOT NULL,
  `event_type` ENUM('OPENED', 'CLOSED', 'VARIANCE_APPROVED', 'REOPENED') NOT NULL,
  `actor_user_id` INT NOT NULL,
  `reason` VARCHAR(500) NULL,
  `snapshot_json` JSON NULL,
  `occurred_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY `idx_cashier_session_events_school_session` (`school_id`, `cashier_session_id`, `id`),
  KEY `idx_cashier_session_events_school_type` (`school_id`, `event_type`, `occurred_at`)
) ENGINE=InnoDB;