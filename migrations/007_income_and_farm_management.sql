-- SQL Migration for School Income & Farm Management Module
-- Treats each activity as a separate Cost Center for accounting integration

-- 1. Activity Master (Cost Centers)
CREATE TABLE IF NOT EXISTS `income_activities` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `name` VARCHAR(100) NOT NULL, -- e.g., 'Dairy', 'Poultry', 'Horticulture'
  `description` TEXT,
  `gl_income_account` VARCHAR(50), -- Link to Chart of Accounts (Income)
  `gl_expense_account` VARCHAR(50), -- Link to Chart of Accounts (Expenses)
  `unit_of_measure` VARCHAR(20) DEFAULT 'units', -- e.g., 'liters', 'crates', 'kg'
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX (`school_id`),
  INDEX (`name`)
) ENGINE=InnoDB;

-- 2. Daily Production Ledger
CREATE TABLE IF NOT EXISTS `income_production_log` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `activity_id` INT NOT NULL,
  `production_date` DATE NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `spoilage_quantity` DECIMAL(12,2) DEFAULT 0.00, -- e.g., spoiled milk
  `internal_consumption` DECIMAL(12,2) DEFAULT 0.00, -- e.g., milk used in kitchen
  `notes` TEXT,
  `recorded_by` INT NOT NULL, -- userNo
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`activity_id`) REFERENCES `income_activities`(`id`) ON DELETE CASCADE,
  INDEX (`school_id`),
  INDEX (`production_date`)
) ENGINE=InnoDB;

-- 3. Farm Sales Ledger
CREATE TABLE IF NOT EXISTS `income_sales` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `activity_id` INT NOT NULL,
  `sale_date` DATE NOT NULL,
  `customer_name` VARCHAR(150),
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_price` DECIMAL(12,2) NOT NULL,
  `total_amount` DECIMAL(12,2) NOT NULL,
  `is_paid` BOOLEAN DEFAULT FALSE,
  `receipt_no` VARCHAR(50), -- For tracking
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`activity_id`) REFERENCES `income_activities`(`id`) ON DELETE CASCADE,
  INDEX (`school_id`),
  INDEX (`sale_date`),
  INDEX (`receipt_no`)
) ENGINE=InnoDB;

-- 4. Farm Expense Requests (Sub-Accounting for Procurement)
CREATE TABLE IF NOT EXISTS `income_expenses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `activity_id` INT NOT NULL,
  `expense_date` DATE NOT NULL,
  `description` VARCHAR(255) NOT NULL,
  `amount` DECIMAL(12,2) NOT NULL,
  `category` ENUM('FEED', 'DRUGS', 'LABOR', 'MAINTENANCE', 'OTHER') NOT NULL,
  `status` ENUM('PENDING', 'APPROVED', 'REJECTED', 'PAID') DEFAULT 'PENDING',
  `approved_by` INT, -- userNo
  `recorded_by` INT NOT NULL,
  `gl_transaction_id` INT, -- Once paid, link to finance_transactions
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`activity_id`) REFERENCES `income_activities`(`id`) ON DELETE CASCADE,
  INDEX (`school_id`),
  INDEX (`status`)
) ENGINE=InnoDB;

-- 5. Seeding initial Activities (Optional)
-- INSERT INTO income_activities (school_id, name, unit_of_measure) VALUES (1, 'Dairy', 'liters'), (1, 'Poultry', 'crates');
