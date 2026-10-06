-- =============================================================================
-- Migration: fees_enhancements_v9.sql
-- Module: Fees / Billing Profile Engine (Phase 8 & 9)
-- Description: Auditable Student Billing Profile combining Academic Year, Class,
--              Stream, Billing Group, Discount Profile, Optional Services,
--              Fee Structure Version, Effective Date, Expiry Date, and Approval.
-- =============================================================================

CREATE TABLE IF NOT EXISTS `student_billing_profiles` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `school_id` INT NOT NULL DEFAULT 1,
    `student_id` INT NOT NULL,
    `academic_year_id` INT NOT NULL,
    `class_id` INT NULL,
    `stream_code` VARCHAR(50) NULL,
    `billing_group_id` INT NULL,
    `discount_profile_id` INT NULL,
    `fee_structure_version_id` INT NULL,
    `effective_date` DATE NOT NULL,
    `expiry_date` DATE NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    `approval_status` VARCHAR(20) NOT NULL DEFAULT 'APPROVED',
    `approved_by` INT NULL,
    `approved_at` DATETIME NULL,
    `created_by` INT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_sbp_school_student` (`school_id`, `student_id`),
    INDEX `idx_sbp_status_dates` (`school_id`, `status`, `effective_date`, `expiry_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `student_billing_profile_optional_services` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `billing_profile_id` INT NOT NULL,
    `optional_service_id` INT NOT NULL,
    `custom_amount` DECIMAL(10,2) NULL,
    `school_id` INT NOT NULL DEFAULT 1,
    INDEX `idx_sbpos_profile` (`billing_profile_id`),
    INDEX `idx_sbpos_school` (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
