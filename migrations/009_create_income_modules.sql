-- SQL Migration for Additional Income & Farm Management Module
-- Includes Dairy, Poultry, Horticulture, etc.

CREATE TABLE IF NOT EXISTS `income_activities` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(20) NOT NULL, -- e.g., 'DAIRY', 'POULTRY'
  `name` VARCHAR(100) NOT NULL,
  `description` TEXT,
  `income_account_id` INT, -- Link to COA/Ledger
  `expense_account_id` INT, -- Link to COA/Ledger
  `school_id` INT NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY `unique_activity` (`code`, `school_id`)
);

CREATE TABLE IF NOT EXISTS `income_production_log` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `activity_id` INT NOT NULL,
  `unit_type` VARCHAR(20) NOT NULL, -- 'LITERS', 'CRATES', 'KGS'
  `quantity_produced` DECIMAL(10,2) NOT NULL,
  `quantity_spoiled` DECIMAL(10,2) DEFAULT 0,
  `quantity_consumed_internal` DECIMAL(10,2) DEFAULT 0, -- School Kitchen
  `log_date` DATE NOT NULL,
  `recorded_by` INT NOT NULL,
  `school_id` INT NOT NULL,
  `notes` TEXT,
  FOREIGN KEY (`activity_id`) REFERENCES `income_activities`(`id`)
);

CREATE TABLE IF NOT EXISTS `income_sales` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `activity_id` INT NOT NULL,
  `customer_name` VARCHAR(100),
  `quantity` DECIMAL(10,2) NOT NULL,
  `unit_price` DECIMAL(10,2) NOT NULL,
  `total_amount` DECIMAL(10,2) NOT NULL,
  `payment_status` ENUM('PAID', 'PENDING') DEFAULT 'PAID',
  `sale_date` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `recorded_by` INT NOT NULL,
  `school_id` INT NOT NULL,
  FOREIGN KEY (`activity_id`) REFERENCES `income_activities`(`id`)
);

CREATE TABLE IF NOT EXISTS `income_expenses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `activity_id` INT NOT NULL,
  `description` VARCHAR(255) NOT NULL,
  `amount` DECIMAL(10,2) NOT NULL,
  `expense_date` DATE NOT NULL,
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING',
  `approved_by` INT,
  `procurement_id` INT, -- Link to existing procurement if applicable
  `school_id` INT NOT NULL,
  FOREIGN KEY (`activity_id`) REFERENCES `income_activities`(`id`)
);
