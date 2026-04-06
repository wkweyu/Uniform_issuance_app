-- Migration: expand SaaS core metadata without replacing existing control-plane tables.
-- Safe and additive. Reuses existing `schools`, `subscriptions`, and `platform_users` tables.

ALTER TABLE `schools`
  ADD COLUMN IF NOT EXISTS `email` VARCHAR(255) NULL AFTER `code`,
  ADD COLUMN IF NOT EXISTS `phone` VARCHAR(64) NULL AFTER `email`,
  ADD COLUMN IF NOT EXISTS `address` VARCHAR(255) NULL AFTER `phone`,
  ADD COLUMN IF NOT EXISTS `city` VARCHAR(128) NULL AFTER `address`,
  ADD COLUMN IF NOT EXISTS `country` VARCHAR(128) NULL AFTER `city`,
  ADD COLUMN IF NOT EXISTS `logo` VARCHAR(255) NULL AFTER `country`,
  ADD COLUMN IF NOT EXISTS `subscription_plan` VARCHAR(64) NULL AFTER `logo`,
  ADD COLUMN IF NOT EXISTS `subscription_status` VARCHAR(32) NOT NULL DEFAULT 'trial' AFTER `subscription_plan`,
  ADD COLUMN IF NOT EXISTS `subscription_start` DATE NULL AFTER `subscription_status`;

CREATE TABLE IF NOT EXISTS `school_settings` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `school_name` VARCHAR(255) NULL,
  `logo` VARCHAR(255) NULL,
  `address` VARCHAR(255) NULL,
  `email` VARCHAR(255) NULL,
  `phone` VARCHAR(64) NULL,
  `website` VARCHAR(255) NULL,
  `timezone` VARCHAR(64) NOT NULL DEFAULT 'UTC',
  `currency` VARCHAR(16) NOT NULL DEFAULT 'USD',
  `grading_system` VARCHAR(64) NULL,
  `report_template` VARCHAR(128) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_school_settings_school_id` (`school_id`),
  CONSTRAINT `fk_school_settings_school`
    FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_general_ci;

ALTER TABLE `subscriptions`
  ADD COLUMN IF NOT EXISTS `billing_cycle` VARCHAR(32) NOT NULL DEFAULT 'monthly' AFTER `status`,
  ADD COLUMN IF NOT EXISTS `amount_cents` INT NOT NULL DEFAULT 0 AFTER `billing_cycle`,
  ADD COLUMN IF NOT EXISTS `payment_reference` VARCHAR(128) NULL AFTER `amount_cents`,
  ADD COLUMN IF NOT EXISTS `trial_ends_at` DATETIME NULL AFTER `payment_reference`,
  ADD COLUMN IF NOT EXISTS `grace_period_ends_at` DATETIME NULL AFTER `trial_ends_at`,
  ADD COLUMN IF NOT EXISTS `ended_at` DATETIME NULL AFTER `grace_period_ends_at`,
  ADD COLUMN IF NOT EXISTS `archived_at` DATETIME NULL AFTER `ended_at`;

ALTER TABLE `platform_users`
  ADD COLUMN IF NOT EXISTS `name` VARCHAR(255) NULL AFTER `id`,
  ADD COLUMN IF NOT EXISTS `is_active` TINYINT(1) NOT NULL DEFAULT 1 AFTER `role`,
  ADD COLUMN IF NOT EXISTS `portfolio_scope` JSON NULL AFTER `assigned_school_id`,
  ADD COLUMN IF NOT EXISTS `mfa_enabled` TINYINT(1) NOT NULL DEFAULT 0 AFTER `portfolio_scope`;