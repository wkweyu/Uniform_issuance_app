-- =============================================================================
-- FEES & FINANCE ENHANCEMENTS MIGRATION v2.0
-- Includes Student Groups, Votehead Priorities, and Finance COA
-- =============================================================================

-- 1. Student Groups (Day, Boarding, Special, etc.)
CREATE TABLE IF NOT EXISTS `student_groups` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(50) NOT NULL UNIQUE,
    `description` TEXT,
    `is_active` BOOLEAN DEFAULT TRUE,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 2. Enhance Student Info (Add Group Link)
-- Note: Assuming studentinfo already exists
ALTER TABLE `studentinfo` ADD COLUMN IF NOT EXISTS `student_group_id` INT;
ALTER TABLE `studentinfo` ADD COLUMN IF NOT EXISTS `category` VARCHAR(50) DEFAULT 'Day'; -- Backward compatibility

-- 3. Enhance Voteheads (Add Priority and Group Filter)
ALTER TABLE `fee_voteheads` ADD COLUMN IF NOT EXISTS `priority` INT DEFAULT 99;
ALTER TABLE `fee_voteheads` ADD COLUMN IF NOT EXISTS `applicable_student_group_id` INT NULL;
ALTER TABLE `fee_voteheads` ADD CONSTRAINT `fk_votehead_group` FOREIGN KEY (`applicable_student_group_id`) REFERENCES `student_groups`(`id`);

-- 4. Finance Chart of Accounts (COA)
CREATE TABLE IF NOT EXISTS `finance_accounts` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `code` VARCHAR(20) UNIQUE NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `type` ENUM('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE') NOT NULL,
    `parent_id` INT NULL,
    `is_active` BOOLEAN DEFAULT TRUE,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`parent_id`) REFERENCES `finance_accounts`(`id`)
) ENGINE=InnoDB;

-- 5. General Ledger (Double Entry)
CREATE TABLE IF NOT EXISTS `finance_transactions` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `transaction_date` DATE NOT NULL,
    `reference_no` VARCHAR(100) NOT NULL,
    `description` TEXT,
    `created_by` INT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `finance_ledger_entries` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `transaction_id` INT NOT NULL,
    `account_id` INT NOT NULL,
    `debit` DECIMAL(15, 2) DEFAULT 0.00,
    `credit` DECIMAL(15, 2) DEFAULT 0.00,
    `note` TEXT,
    FOREIGN KEY (`transaction_id`) REFERENCES `finance_transactions`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`account_id`) REFERENCES `finance_accounts`(`id`)
) ENGINE=InnoDB;

-- 6. Payment Vouchers & Cheque Register
CREATE TABLE IF NOT EXISTS `finance_payment_vouchers` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `voucher_no` VARCHAR(50) UNIQUE NOT NULL,
    `payee_name` VARCHAR(255) NOT NULL,
    `amount` DECIMAL(15, 2) NOT NULL,
    `payment_mode` ENUM('CASH', 'CHEQUE', 'MPESA', 'BANK_TRANSFER') NOT NULL,
    `cheque_no` VARCHAR(50),
    `description` TEXT,
    `status` ENUM('DRAFT', 'APPROVED', 'PAID', 'CANCELLED') DEFAULT 'DRAFT',
    `transaction_id` INT NULL,
    `created_by` INT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`transaction_id`) REFERENCES `finance_transactions`(`id`)
) ENGINE=InnoDB;

-- 7. Audit Trail for Fees Reallocation
CREATE TABLE IF NOT EXISTS `fee_reallocation_log` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `original_admno` INT,
    `new_admno` INT,
    `reference_no` VARCHAR(100),
    `amount` DECIMAL(15, 2),
    `reason` TEXT,
    `reallocated_by` INT,
    `reallocated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Initial Data for Student Groups
INSERT IGNORE INTO `student_groups` (name, description) VALUES 
('Day Scholar', 'Students who commute daily'),
('Boarding', 'Students residing in school hostels'),
('Special Program', 'Students in specialized academic programs');

-- Initial Chart of Accounts
INSERT IGNORE INTO `finance_accounts` (code, name, type) VALUES 
('1000', 'Current Assets', 'ASSET'),
('1100', 'Cash at Bank', 'ASSET'),
('1200', 'Petty Cash', 'ASSET'),
('1300', 'Accounts Receivable (Fees)', 'ASSET'),
('2000', 'Current Liabilities', 'LIABILITY'),
('2100', 'Accounts Payable', 'LIABILITY'),
('3000', 'Equity', 'EQUITY'),
('4000', 'Income', 'INCOME'),
('4100', 'Tuition Fees', 'INCOME'),
('4200', 'Transport Income', 'INCOME'),
('4300', 'Other Income', 'INCOME'),
('5000', 'Expenses', 'EXPENSE'),
('5100', 'Salaries & Wages', 'EXPENSE'),
('5200', 'Fuel & Maintenance', 'EXPENSE'),
('5300', 'Academic Supplies', 'EXPENSE'),
('5400', 'Utility Bills', 'EXPENSE');
