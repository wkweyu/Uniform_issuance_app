-- Migration: create platform control-plane tables (safe, idempotent)

CREATE TABLE IF NOT EXISTS `plans` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(255) NOT NULL UNIQUE,
  `price_cents` INT NOT NULL DEFAULT 0,
  `billing_period` VARCHAR(32) NOT NULL DEFAULT 'monthly',
  `features` JSON,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `subscriptions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `plan_id` INT NOT NULL,
  `status` VARCHAR(32) DEFAULT 'active',
  `started_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `renewal_date` DATETIME,
  `billing_meta` JSON,
  INDEX (`school_id`),
  INDEX (`plan_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `platform_users` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `email` VARCHAR(255) NOT NULL UNIQUE,
  `password_hash` VARCHAR(255) NOT NULL,
  `role` VARCHAR(64) NOT NULL,
  `assigned_school_id` INT NULL,
  `created_by` INT NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `last_login_at` DATETIME NULL,
  INDEX (`assigned_school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `support_tickets` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `raised_by_email` VARCHAR(255),
  `subject` VARCHAR(255),
  `description` TEXT,
  `status` VARCHAR(32) DEFAULT 'open',
  `assigned_to_user_id` INT NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX (`school_id`),
  INDEX (`assigned_to_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `actor_user_id` INT NULL,
  `actor_platform` TINYINT(1) DEFAULT 1,
  `action` VARCHAR(255),
  `target_table` VARCHAR(255),
  `target_id` VARCHAR(255),
  `school_id` INT NULL,
  `changes` JSON,
  `ip` VARCHAR(64),
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Note: `schools` table already exists in the main application schema; do not recreate it here.
