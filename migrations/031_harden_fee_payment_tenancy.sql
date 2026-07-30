-- Migration 031: Harden fee payment tables for tenant-scoped operation.
-- Safe to re-run on environments where columns may already exist.

-- 0) fee_ledger (required by record_payment before fee_payments insert)
ALTER TABLE `fee_ledger`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1;

UPDATE `fee_ledger` fl
JOIN `studentinfo` si ON fl.`admno` = si.`AdmNo`
SET fl.`school_id` = si.`school_id`
WHERE fl.`school_id` IS NULL OR fl.`school_id` = 1;

ALTER TABLE `fee_ledger`
  ADD KEY IF NOT EXISTS `idx_fee_ledger_school_id` (`school_id`);

-- 1) fee_payments
ALTER TABLE `fee_payments`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1;

UPDATE `fee_payments` fp
JOIN `fee_ledger` fl ON fp.`ledger_id` = fl.`id`
SET fp.`school_id` = fl.`school_id`
WHERE fp.`school_id` IS NULL OR fp.`school_id` = 1;

ALTER TABLE `fee_payments`
  ADD KEY IF NOT EXISTS `idx_fee_payments_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_fee_payments_school_admno` (`school_id`, `admno`);

-- 2) fee_receipts
ALTER TABLE `fee_receipts`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1;

UPDATE `fee_receipts` fr
JOIN `fee_payments` fp ON fr.`payment_id` = fp.`id`
SET fr.`school_id` = fp.`school_id`
WHERE fr.`school_id` IS NULL OR fr.`school_id` = 1;

ALTER TABLE `fee_receipts`
  ADD KEY IF NOT EXISTS `idx_fee_receipts_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_fee_receipts_school_payment` (`school_id`, `payment_id`);

-- 3) fee_payment_allocations
ALTER TABLE `fee_payment_allocations`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1;

UPDATE `fee_payment_allocations` fpa
JOIN `fee_payments` fp ON fpa.`payment_id` = fp.`id`
SET fpa.`school_id` = fp.`school_id`
WHERE fpa.`school_id` IS NULL OR fpa.`school_id` = 1;

ALTER TABLE `fee_payment_allocations`
  ADD KEY IF NOT EXISTS `idx_fee_payment_allocations_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_fee_payment_allocations_school_payment` (`school_id`, `payment_id`);

-- 4) fee_reallocation_log
ALTER TABLE `fee_reallocation_log`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1;

ALTER TABLE `fee_reallocation_log`
  ADD KEY IF NOT EXISTS `idx_fee_reallocation_log_school_id` (`school_id`);
