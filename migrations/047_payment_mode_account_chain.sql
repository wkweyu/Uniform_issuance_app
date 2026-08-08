-- Migration 047: Extend tenant payment-mode receiving accounts into an auditable account chain.

ALTER TABLE `payment_mode_receiving_accounts`
  ADD COLUMN IF NOT EXISTS `settlement_account_id` INT NULL AFTER `account_id`,
  ADD COLUMN IF NOT EXISTS `clearing_account_id` INT NULL AFTER `settlement_account_id`,
  ADD COLUMN IF NOT EXISTS `default_gl_account_id` INT NULL AFTER `clearing_account_id`,
  ADD KEY IF NOT EXISTS `idx_payment_mode_account_settlement` (`settlement_account_id`),
  ADD KEY IF NOT EXISTS `idx_payment_mode_account_clearing` (`clearing_account_id`),
  ADD KEY IF NOT EXISTS `idx_payment_mode_account_default_gl` (`default_gl_account_id`);

CREATE TABLE IF NOT EXISTS `payment_mode_account_events` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `payment_mode` VARCHAR(30) NOT NULL,
  `event_type` ENUM('CONFIGURED', 'DEACTIVATED') NOT NULL,
  `receiving_account_id` INT NOT NULL,
  `settlement_account_id` INT NULL,
  `clearing_account_id` INT NULL,
  `default_gl_account_id` INT NULL,
  `is_active` BOOLEAN NOT NULL,
  `actor_user_id` INT NOT NULL,
  `occurred_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY `idx_payment_mode_account_events_school_mode` (`school_id`, `payment_mode`, `id`)
) ENGINE=InnoDB;