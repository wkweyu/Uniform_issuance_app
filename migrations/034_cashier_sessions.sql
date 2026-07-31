-- Migration 034: Tenant-scoped cashier sessions for cash receipt accountability.

CREATE TABLE IF NOT EXISTS `cashier_sessions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `cashier_user_id` INT NOT NULL,
  `status` ENUM('OPEN', 'PENDING_APPROVAL', 'CLOSED') NOT NULL DEFAULT 'OPEN',
  `opened_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `opened_by` INT NOT NULL,
  `closed_at` DATETIME NULL,
  `closed_by` INT NULL,
  `expected_cash` DECIMAL(15, 2) NULL,
  `actual_cash` DECIMAL(15, 2) NULL,
  `variance` DECIMAL(15, 2) NULL,
  `closure_notes` VARCHAR(500) NULL,
  `approved_by` INT NULL,
  `approved_at` DATETIME NULL,
  KEY `idx_cashier_sessions_school_cashier_status` (`school_id`, `cashier_user_id`, `status`),
  KEY `idx_cashier_sessions_school_status` (`school_id`, `status`)
) ENGINE=InnoDB;

ALTER TABLE `fee_payments`
  ADD COLUMN IF NOT EXISTS `cashier_session_id` INT NULL AFTER `receiving_account_id`,
  ADD KEY IF NOT EXISTS `idx_fee_payments_cashier_session` (`cashier_session_id`);