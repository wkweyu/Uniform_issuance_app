-- =============================================================================
-- FEES MANAGEMENT MODULE MIGRATION v1.0
-- Database: schoolmngt
-- =============================================================================

-- 1. Fee Voteheads (Tuition, Transport, Boarding, etc.)
CREATE TABLE IF NOT EXISTS `fee_voteheads` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(100) NOT NULL UNIQUE,
    `description` TEXT,
    `is_active` BOOLEAN DEFAULT TRUE,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 2. Fee Structure (Global per Year/Term/ClassGroup/Category)
CREATE TABLE IF NOT EXISTS `fee_structures` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `academic_year_id` INT NOT NULL,
    `term_id` INT NOT NULL COMMENT 'FK to uniform_term_dates.id',
    `class_group_code` VARCHAR(50) NOT NULL COMMENT 'FK to class_group_settings.code',
    `student_category` VARCHAR(50) NOT NULL DEFAULT 'Day' COMMENT 'Day, Boarding, etc.',
    `total_amount` DECIMAL(15, 2) DEFAULT 0.00,
    `created_by` INT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `unique_structure` (`academic_year_id`, `term_id`, `class_group_code`, `student_category`),
    FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years`(`id`),
    FOREIGN KEY (`term_id`) REFERENCES `uniform_term_dates`(`id`)
) ENGINE=InnoDB;

-- 3. Fee Structure Items (Breakdown into Voteheads)
CREATE TABLE IF NOT EXISTS `fee_structure_items` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `fee_structure_id` INT NOT NULL,
    `votehead_id` INT NOT NULL,
    `amount` DECIMAL(15, 2) NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`fee_structure_id`) REFERENCES `fee_structures`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`votehead_id`) REFERENCES `fee_voteheads`(`id`)
) ENGINE=InnoDB;

-- 4. Fee Ledger (Single source of truth for all student transactions)
CREATE TABLE IF NOT EXISTS `fee_ledger` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `admno` INT NOT NULL,
    `academic_year_id` INT NOT NULL,
    `term_id` INT NOT NULL,
    `type` ENUM('CHARGE', 'PAYMENT', 'ADJUSTMENT', 'REFUND') NOT NULL,
    `votehead_id` INT COMMENT 'Optional: specific votehead for charges/adjustments',
    `amount` DECIMAL(15, 2) NOT NULL COMMENT 'Amount involved (always positive)',
    `balance_after` DECIMAL(15, 2) DEFAULT 0.00 COMMENT 'Running balance for student',
    `description` TEXT,
    `reference_no` VARCHAR(100) COMMENT 'Invoice ID, Receipt ID, or Adjustment ID',
    `transaction_date` DATE NOT NULL,
    `created_by` INT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_admno` (`admno`),
    INDEX `idx_year_term` (`academic_year_id`, `term_id`),
    INDEX `idx_ref` (`reference_no`),
    FOREIGN KEY (`admno`) REFERENCES `studentinfo`(`AdmNo`),
    FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years`(`id`),
    FOREIGN KEY (`term_id`) REFERENCES `uniform_term_dates`(`id`),
    FOREIGN KEY (`votehead_id`) REFERENCES `fee_voteheads`(`id`)
) ENGINE=InnoDB;

-- 5. Fee Payments (Detailed record for credits)
CREATE TABLE IF NOT EXISTS `fee_payments` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `ledger_id` INT NOT NULL,
    `admno` INT NOT NULL,
    `payment_mode` ENUM('CASH', 'CHEQUE', 'MPESA', 'BANK_TRANSFER', 'OTHER') NOT NULL,
    `reference_number` VARCHAR(100) NOT NULL COMMENT 'M-PESA Code, Cheque No, Bank Slip No',
    `bank_name` VARCHAR(100),
    `payment_date` DATE NOT NULL,
    `amount` DECIMAL(15, 2) NOT NULL,
    `status` ENUM('COMPLETED', 'PENDING', 'CANCELLED', 'REVERSED') DEFAULT 'COMPLETED',
    `received_by` INT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `unique_payment_ref` (`payment_mode`, `reference_number`),
    FOREIGN KEY (`ledger_id`) REFERENCES `fee_ledger`(`id`),
    FOREIGN KEY (`admno`) REFERENCES `studentinfo`(`AdmNo`)
) ENGINE=InnoDB;

-- 6. Fee Receipts (Sequential receipt tracking)
CREATE TABLE IF NOT EXISTS `fee_receipts` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `payment_id` INT NOT NULL,
    `receipt_no` VARCHAR(50) UNIQUE NOT NULL COMMENT 'e.g. RCP-2026-0001',
    `issued_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `issued_by` INT,
    FOREIGN KEY (`payment_id`) REFERENCES `fee_payments`(`id`)
) ENGINE=InnoDB;

-- 7. Student Discounts / Scholarships / Waivers (Adjustments cache)
CREATE TABLE IF NOT EXISTS `fee_adjustments` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `admno` INT NOT NULL,
    `academic_year_id` INT NOT NULL,
    `term_id` INT NOT NULL,
    `amount` DECIMAL(15, 2) NOT NULL,
    `reason` TEXT,
    `approved_by` INT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`admno`) REFERENCES `studentinfo`(`AdmNo`)
) ENGINE=InnoDB;

-- Initial Data
INSERT IGNORE INTO `fee_voteheads` (name, description) VALUES 
('Tuition', 'Standard academic tuition fees'),
('Boarding', 'Hostel and meals for boarding students'),
('Transport', 'School bus transportation services'),
('Exam Fees', 'Assessments and internal examination materials'),
('Activity Fees', 'Sports, drama, and school activities'),
('Medical Fees', 'Basic school clinic services'),
('P.T.A', 'Parents Teachers Association contribution'),
('Library', 'Library maintenance and book access'),
('Lab Fees', 'Science laboratory consumables'),
('Caution Money', 'One-time refundable security deposit'),
('Admin Fees', 'Registration and administrative costs');
