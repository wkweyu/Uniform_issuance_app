-- Migration 036: Link fee reallocation audit rows to payments and lifecycle correlations.

ALTER TABLE `fee_reallocation_log`
  ADD COLUMN IF NOT EXISTS `payment_id` INT NULL AFTER `amount`,
  ADD COLUMN IF NOT EXISTS `correlation_id` CHAR(36) NULL AFTER `school_id`,
  ADD KEY IF NOT EXISTS `idx_fee_reallocation_log_school_payment` (`school_id`, `payment_id`),
  ADD KEY IF NOT EXISTS `idx_fee_reallocation_log_school_correlation` (`school_id`, `correlation_id`);