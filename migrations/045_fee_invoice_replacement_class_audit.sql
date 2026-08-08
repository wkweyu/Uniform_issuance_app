-- Migration 045: Preserve class and stream changes in audited invoice replacements.
ALTER TABLE `fee_invoice_replacements`
  ADD COLUMN IF NOT EXISTS `previous_class_id` INT NULL AFTER `new_student_group_id`,
  ADD COLUMN IF NOT EXISTS `new_class_id` INT NULL AFTER `previous_class_id`,
  ADD COLUMN IF NOT EXISTS `previous_stream_code` VARCHAR(30) NULL AFTER `new_class_id`,
  ADD COLUMN IF NOT EXISTS `new_stream_code` VARCHAR(30) NULL AFTER `previous_stream_code`,
  ADD KEY IF NOT EXISTS `idx_fee_invoice_replacements_class_change` (`school_id`, `previous_class_id`, `new_class_id`);
