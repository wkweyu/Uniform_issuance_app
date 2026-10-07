-- Migration 057: Add fee structure versioning and status columns
-- Ensures fee_structures table contains versioning and approval columns required by the Fee Structure Engine.

ALTER TABLE `fee_structures`
  ADD COLUMN IF NOT EXISTS `status` VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' AFTER `student_category`,
  ADD COLUMN IF NOT EXISTS `version_number` INT NOT NULL DEFAULT 1 AFTER `status`,
  ADD COLUMN IF NOT EXISTS `approval_status` VARCHAR(20) NOT NULL DEFAULT 'APPROVED' AFTER `version_number`,
  ADD COLUMN IF NOT EXISTS `scope_key` VARCHAR(100) NULL AFTER `approval_status`,
  ADD COLUMN IF NOT EXISTS `parent_version_id` INT NULL AFTER `scope_key`,
  ADD COLUMN IF NOT EXISTS `effective_from` DATETIME NULL AFTER `parent_version_id`,
  ADD COLUMN IF NOT EXISTS `approved_by` INT NULL AFTER `effective_from`,
  ADD COLUMN IF NOT EXISTS `approved_at` DATETIME NULL AFTER `approved_by`,
  ADD KEY IF NOT EXISTS `idx_fs_school_scope_status` (`school_id`, `scope_key`, `status`),
  ADD KEY IF NOT EXISTS `idx_fs_academic_year_status` (`school_id`, `academic_year_id`, `status`);
