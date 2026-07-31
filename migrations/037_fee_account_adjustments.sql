-- Migration 037: Audited debit and credit notes linked to the fee ledger.

ALTER TABLE `fee_adjustments`
  ADD COLUMN IF NOT EXISTS `adjustment_type` ENUM('DEBIT', 'CREDIT') NULL AFTER `amount`,
  ADD COLUMN IF NOT EXISTS `votehead_id` INT NULL AFTER `term_id`,
  ADD COLUMN IF NOT EXISTS `effective_date` DATE NULL AFTER `reason`,
  ADD COLUMN IF NOT EXISTS `supporting_reference` VARCHAR(100) NULL AFTER `effective_date`,
  ADD COLUMN IF NOT EXISTS `ledger_id` INT NULL AFTER `approved_by`,
  ADD COLUMN IF NOT EXISTS `created_by` INT NULL AFTER `ledger_id`,
  ADD KEY IF NOT EXISTS `idx_fee_adjustments_school_type` (`school_id`, `adjustment_type`),
  ADD KEY IF NOT EXISTS `idx_fee_adjustments_school_ledger` (`school_id`, `ledger_id`);