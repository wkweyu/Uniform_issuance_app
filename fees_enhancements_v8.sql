-- =============================================================================
-- Migration: fees_enhancements_v8.sql
-- Module: Fees / Optional Services Engine (Phase 5)
-- Description: Adds Optional Services Catalog with effective dates, billing frequencies,
--              and billing cycle charge tracking to prevent duplicate postings.
-- =============================================================================

CREATE TABLE IF NOT EXISTS `fee_optional_services` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `school_id` INT NOT NULL DEFAULT 1,
    `name` VARCHAR(100) NOT NULL,
    `code` VARCHAR(30) NULL,
    `votehead_id` INT NOT NULL,
    `default_amount` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `billing_frequency` VARCHAR(20) NOT NULL DEFAULT 'TERMLY', -- ONE_TIME, MONTHLY, TERMLY, ANNUAL, CUSTOM
    `description` TEXT NULL,
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `created_by` INT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_fos_school_name` (`school_id`, `name`),
    INDEX `idx_fos_school_active` (`school_id`, `is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `student_optional_service_subscriptions` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `school_id` INT NOT NULL DEFAULT 1,
    `student_id` INT NOT NULL,
    `optional_service_id` INT NOT NULL,
    `effective_from` DATE NOT NULL,
    `effective_to` DATE NULL,
    `custom_amount` DECIMAL(10,2) NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, PAUSED, CANCELLED
    `created_by` INT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_soss_student` (`school_id`, `student_id`),
    INDEX `idx_soss_effective` (`school_id`, `status`, `effective_from`, `effective_to`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `student_optional_service_charges` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `school_id` INT NOT NULL DEFAULT 1,
    `student_id` INT NOT NULL,
    `optional_service_id` INT NOT NULL,
    `academic_year_id` INT NOT NULL,
    `term_id` INT NOT NULL,
    `subscription_id` INT NOT NULL,
    `ledger_id` INT NOT NULL,
    `billing_cycle_key` VARCHAR(100) NOT NULL,
    `amount` DECIMAL(10,2) NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_sosc_cycle` (`school_id`, `subscription_id`, `billing_cycle_key`),
    INDEX `idx_sosc_student` (`school_id`, `student_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
