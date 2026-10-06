-- =============================================================================
-- Migration: fees_enhancements_v7.sql
-- Module: Fees / Discount Profiles Engine (Phase 3 & 4)
-- Description: Creates fee_discount_profiles and student_discount_profiles tables.
-- =============================================================================

CREATE TABLE IF NOT EXISTS `fee_discount_profiles` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `school_id` INT NOT NULL DEFAULT 1,
    `name` VARCHAR(100) NOT NULL,
    `code` VARCHAR(30) NULL,
    `discount_type` VARCHAR(30) NOT NULL DEFAULT 'PERCENTAGE', -- PERCENTAGE, FIXED_AMOUNT, VOTEHEAD_SPECIFIC
    `value` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `votehead_id` INT NULL,
    `effective_from` DATE NULL,
    `effective_to` DATE NULL,
    `description` TEXT NULL,
    `is_active` BOOLEAN NOT NULL DEFAULT TRUE,
    `created_by` INT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_fdp_school_name` (`school_id`, `name`),
    INDEX `idx_fdp_school_active` (`school_id`, `is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `student_discount_profiles` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `school_id` INT NOT NULL DEFAULT 1,
    `student_id` INT NOT NULL,
    `discount_profile_id` INT NOT NULL,
    `effective_from` DATE NOT NULL,
    `effective_to` DATE NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    `assigned_by` INT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_sdp_student` (`school_id`, `student_id`),
    INDEX `idx_sdp_profile` (`school_id`, `discount_profile_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
