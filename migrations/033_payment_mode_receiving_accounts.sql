-- Migration 033: Tenant-scoped receiving accounts for fee payment modes.

CREATE TABLE IF NOT EXISTS `payment_mode_receiving_accounts` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `payment_mode` VARCHAR(30) NOT NULL,
  `account_id` INT NOT NULL,
  `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
  `configured_by` INT NULL,
  `configured_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY `uq_payment_mode_receiving_account` (`school_id`, `payment_mode`),
  KEY `idx_payment_mode_receiving_account_school_active` (`school_id`, `is_active`),
  KEY `idx_payment_mode_receiving_account_account` (`account_id`),
  CONSTRAINT `fk_payment_mode_receiving_account_finance_account`
    FOREIGN KEY (`account_id`) REFERENCES `finance_accounts` (`id`)
) ENGINE=InnoDB;

ALTER TABLE `fee_payments`
  ADD COLUMN IF NOT EXISTS `receiving_account_id` INT NULL AFTER `bank_name`,
  ADD KEY IF NOT EXISTS `idx_fee_payments_receiving_account` (`receiving_account_id`);