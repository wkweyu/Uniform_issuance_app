-- Migration: 060_business_operations_core.sql
-- Description: Business Operations Platform Core Schema Expansion
-- Author: SkoolTrack Pro ERP
-- Date: 2026-10-08

-- =============================================================================
-- 1. CONFIGURATION LOOKUP TABLES (No Hardcoded ENUMs)
-- =============================================================================

CREATE TABLE IF NOT EXISTS `business_unit_types` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE,
  `name` VARCHAR(100) NOT NULL,
  `description` TEXT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `departments` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `code` VARCHAR(50) NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `expense_gl_account` VARCHAR(50) NULL,
  `is_active` BOOLEAN DEFAULT TRUE,
  INDEX `idx_dept_school` (`school_id`),
  UNIQUE KEY `uq_dept_school_code` (`school_id`, `code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `location_types` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE,
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `inventory_transaction_types` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE,
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `item_categories` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `parent_id` INT NULL,
  `code` VARCHAR(50) NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE,
  INDEX `idx_cat_school` (`school_id`),
  FOREIGN KEY (`parent_id`) REFERENCES `item_categories`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `item_classifications` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE,
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `production_loss_types` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE,
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `expense_categories` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE,
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed Default Lookup Configurations
INSERT IGNORE INTO `business_unit_types` (`code`, `name`) VALUES
('AGRICULTURE', 'Agriculture & Farming'),
('RETAIL', 'Retail & Uniform Shop'),
('FOOD_BEVERAGE', 'Food & Canteen Services'),
('TRANSPORT', 'Transport & Fleet Services'),
('RENTAL', 'Facility & Equipment Rentals'),
('SERVICES', 'General Services'),
('PRODUCTION', 'Manufacturing & Bakery');

INSERT IGNORE INTO `location_types` (`code`, `name`) VALUES
('WAREHOUSE', 'Central Warehouse'),
('STORE', 'Retail / Unit Store'),
('COLD_STORAGE', 'Cold Storage / Processing'),
('FUEL_TANK', 'Fuel Tank / Storage'),
('TRANSIT', 'In-Transit Storage');

INSERT IGNORE INTO `inventory_transaction_types` (`code`, `name`) VALUES
('PURCHASE', 'Supplier Purchase GRN'),
('PRODUCTION', 'Batch Production Yield'),
('SALE', 'POS Customer Sale'),
('TRANSFER', 'Inter-Departmental Transfer'),
('SPOILAGE', 'Stock Spoilage / Write-off'),
('ADJUSTMENT', 'Stock Adjustment'),
('ISSUANCE', 'Student / Department Issuance'),
('UNIFORM_RETURN', 'Uniform Student Return'),
('UNIFORM_EXCHANGE', 'Uniform Size Exchange');

INSERT IGNORE INTO `item_classifications` (`code`, `name`) VALUES
('CONSUMABLE', 'Consumable Item (Non-Returnable)'),
('RETURNABLE', 'Returnable Custody Asset'),
('FIXED_ASSET', 'Fixed Asset'),
('SALE_ITEM', 'Commercial Retail Item'),
('UNIFORM', 'School Uniform Item'),
('FOOD_ITEM', 'Food & Kitchen Supplies'),
('MEDICINE', 'Medical & Livestock Drugs'),
('FARM_INPUT', 'Agricultural Feed & Seeds'),
('FUEL', 'Petroleum & Diesel Fuel'),
('STATIONERY', 'Books & Stationery');

INSERT IGNORE INTO `production_loss_types` (`code`, `name`) VALUES
('SPILLAGE', 'Accidental Spillage'),
('SPOILAGE', 'Spoilage / Degradation'),
('CONTAMINATION', 'Batch Contamination'),
('EVAPORATION', 'Evaporation / Shrinkage'),
('EXPIRY', 'Product Expiry');

INSERT IGNORE INTO `expense_categories` (`code`, `name`) VALUES
('FEED', 'Animal Feed'),
('DRUGS', 'Veterinary & Drugs'),
('FUEL', 'Vehicle & Machinery Fuel'),
('MAINTENANCE', 'Repair & Maintenance'),
('SUPPLIES', 'Operational Supplies'),
('LABOR', 'Direct Labor / Wages'),
('UTILITIES', 'Electricity & Water');

-- =============================================================================
-- 2. ITEM MASTER & BUSINESS UNITS CORE
-- =============================================================================

CREATE TABLE IF NOT EXISTS `item_master` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `category_id` INT NULL,
  `classification_id` INT NOT NULL,
  `name` VARCHAR(150) NOT NULL,
  `code_sku` VARCHAR(50) NULL,
  `barcode` VARCHAR(100) NULL,
  `unit_of_measure` VARCHAR(30) DEFAULT 'Pcs',
  `default_purchase_cost` DECIMAL(12,2) DEFAULT 0.00,
  `default_selling_price` DECIMAL(12,2) DEFAULT 0.00,
  `reorder_level` DECIMAL(12,2) DEFAULT 10.00,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`),
  FOREIGN KEY (`category_id`) REFERENCES `item_categories`(`id`) ON DELETE SET NULL,
  FOREIGN KEY (`classification_id`) REFERENCES `item_classifications`(`id`),
  INDEX `idx_im_school` (`school_id`),
  INDEX `idx_im_sku` (`code_sku`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `business_units` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `name` VARCHAR(150) NOT NULL,
  `type_id` INT NOT NULL,
  `manager_id` INT NULL,
  `cost_center_code` VARCHAR(50) NULL,
  `revenue_gl_account` VARCHAR(50) NULL,
  `expense_gl_account` VARCHAR(50) NULL,
  `inventory_gl_account` VARCHAR(50) NULL,
  `cogs_gl_account` VARCHAR(50) NULL,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`type_id`) REFERENCES `business_unit_types`(`id`),
  FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`),
  INDEX `idx_bu_school` (`school_id`),
  INDEX `idx_bu_type` (`type_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Backward-Compatibility Database View for Legacy Code
CREATE OR REPLACE VIEW `income_activities` AS
SELECT id, school_id, name, '' AS description, revenue_gl_account AS gl_income_account, expense_gl_account AS gl_expense_account, is_active, created_at
FROM `business_units`;

CREATE TABLE IF NOT EXISTS `inventory_locations` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `location_type_id` INT NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`location_type_id`) REFERENCES `location_types`(`id`),
  INDEX `idx_loc_school` (`school_id`),
  INDEX `idx_loc_bu` (`business_unit_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Evolved Central Stock Balances
ALTER TABLE `item_stock`
  ADD COLUMN IF NOT EXISTS `item_master_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `location_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `selling_price` DECIMAL(12,2) DEFAULT 0.00,
  ADD KEY IF NOT EXISTS `idx_stock_im` (`item_master_id`),
  ADD KEY IF NOT EXISTS `idx_stock_loc` (`location_id`),
  ADD KEY IF NOT EXISTS `idx_stock_bu` (`business_unit_id`),
  ADD CONSTRAINT `fk_stock_im` FOREIGN KEY (`item_master_id`) REFERENCES `item_master`(`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_stock_loc` FOREIGN KEY (`location_id`) REFERENCES `inventory_locations`(`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_stock_bu` FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE SET NULL;

ALTER TABLE `stock_movements`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS `item_master_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `location_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `transaction_type_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `reference_no` VARCHAR(100) NULL,
  ADD KEY IF NOT EXISTS `idx_sm_school` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_sm_im` (`item_master_id`),
  ADD KEY IF NOT EXISTS `idx_sm_bu` (`business_unit_id`),
  ADD KEY IF NOT EXISTS `idx_sm_loc` (`location_id`),
  ADD CONSTRAINT `fk_sm_im` FOREIGN KEY (`item_master_id`) REFERENCES `item_master`(`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_sm_type` FOREIGN KEY (`transaction_type_id`) REFERENCES `inventory_transaction_types`(`id`) ON DELETE SET NULL;

-- =============================================================================
-- 3. DEPARTMENT ISSUES & RETURNABLE ASSET CUSTODY TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS `inventory_issues` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `department_id` INT NOT NULL,
  `item_master_id` INT NOT NULL,
  `from_location_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_cost` DECIMAL(12,2) NOT NULL,
  `total_value` DECIMAL(12,2) NOT NULL,
  `is_returnable` BOOLEAN DEFAULT FALSE,
  `status` ENUM('ISSUED', 'RETURNED', 'WRITTEN_OFF') DEFAULT 'ISSUED',
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'APPROVED',
  `approved_by` INT NULL,
  `gl_event_id` INT NULL,
  `issue_date` DATE NOT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  FOREIGN KEY (`department_id`) REFERENCES `departments`(`id`),
  FOREIGN KEY (`item_master_id`) REFERENCES `item_master`(`id`),
  FOREIGN KEY (`from_location_id`) REFERENCES `inventory_locations`(`id`),
  INDEX `idx_ii_school` (`school_id`),
  INDEX `idx_ii_date` (`issue_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `inventory_custody` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `inventory_issue_id` INT NOT NULL,
  `item_master_id` INT NOT NULL,
  `custodian_type` ENUM('STAFF', 'DEPARTMENT', 'STUDENT') DEFAULT 'STAFF',
  `custodian_id` INT NOT NULL,
  `custodian_name` VARCHAR(150) NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `serial_number` VARCHAR(100) NULL,
  `issue_condition` TEXT NULL,
  `expected_return_date` DATE NULL,
  `status` ENUM('ACTIVE_CUSTODY', 'RETURNED', 'DAMAGED', 'LOST') DEFAULT 'ACTIVE_CUSTODY',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`inventory_issue_id`) REFERENCES `inventory_issues`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_master_id`) REFERENCES `item_master`(`id`),
  INDEX `idx_ic_school` (`school_id`),
  INDEX `idx_ic_custodian` (`custodian_type`, `custodian_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `inventory_returns` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `inventory_issue_id` INT NOT NULL,
  `inventory_custody_id` INT NULL,
  `to_location_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `return_condition` TEXT NULL,
  `return_date` DATE NOT NULL,
  `received_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`inventory_issue_id`) REFERENCES `inventory_issues`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`inventory_custody_id`) REFERENCES `inventory_custody`(`id`) ON DELETE SET NULL,
  FOREIGN KEY (`to_location_id`) REFERENCES `inventory_locations`(`id`),
  INDEX `idx_ir_school` (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 4. BATCH PRODUCTION & APPROVED LOSS MANAGEMENT
-- =============================================================================

CREATE TABLE IF NOT EXISTS `production_batches` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `batch_no` VARCHAR(50) NOT NULL,
  `item_master_id` INT NOT NULL,
  `location_id` INT NOT NULL,
  `total_produced_qty` DECIMAL(12,2) NOT NULL,
  `saleable_qty` DECIMAL(12,2) NOT NULL,
  `total_input_cost` DECIMAL(12,2) DEFAULT 0.00,
  `unit_production_cost` DECIMAL(12,2) DEFAULT 0.00,
  `production_date` DATE NOT NULL,
  `status` ENUM('IN_PROGRESS', 'COMPLETED', 'CLOSED') DEFAULT 'COMPLETED',
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  FOREIGN KEY (`item_master_id`) REFERENCES `item_master`(`id`),
  FOREIGN KEY (`location_id`) REFERENCES `inventory_locations`(`id`),
  INDEX `idx_pb_school` (`school_id`),
  INDEX `idx_pb_batch` (`batch_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `production_losses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `production_batch_id` INT NOT NULL,
  `item_master_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `loss_type_id` INT NOT NULL,
  `reason` TEXT NULL,
  `financial_value` DECIMAL(12,2) DEFAULT 0.00,
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING',
  `approved_by` INT NULL,
  `financial_posting_status` ENUM('PENDING', 'POSTED', 'FAILED') DEFAULT 'PENDING',
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`production_batch_id`) REFERENCES `production_batches`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_master_id`) REFERENCES `item_master`(`id`),
  FOREIGN KEY (`loss_type_id`) REFERENCES `production_loss_types`(`id`),
  INDEX `idx_pl_school` (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 5. POS, EXPENSES & IDEMPOTENT ACCOUNTING QUEUE
-- =============================================================================

CREATE TABLE IF NOT EXISTS `business_sales` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `sale_date` DATE NOT NULL,
  `customer_type` ENUM('EXTERNAL', 'STUDENT', 'STAFF', 'ORGANIZATION') DEFAULT 'EXTERNAL',
  `customer_name` VARCHAR(150) NULL,
  `student_adm_no` VARCHAR(30) NULL,
  `total_amount` DECIMAL(12,2) NOT NULL,
  `payment_status` ENUM('PAID', 'PENDING', 'CANCELLED') DEFAULT 'PAID',
  `payment_method` ENUM('CASH', 'MOBILE_MONEY', 'BANK', 'STUDENT_ACCOUNT') DEFAULT 'CASH',
  `receipt_no` VARCHAR(50) NOT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  INDEX `idx_sales_school` (`school_id`),
  INDEX `idx_sales_bu` (`business_unit_id`),
  INDEX `idx_sales_receipt` (`receipt_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `business_sales_items` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `sale_id` INT NOT NULL,
  `item_master_id` INT NULL,
  `item_name` VARCHAR(150) NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_price` DECIMAL(12,2) NOT NULL,
  `total_price` DECIMAL(12,2) NOT NULL,
  FOREIGN KEY (`sale_id`) REFERENCES `business_sales`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_master_id`) REFERENCES `item_master`(`id`) ON DELETE SET NULL,
  INDEX `idx_bsi_school` (`school_id`),
  INDEX `idx_bsi_sale` (`sale_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `business_expenses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `expense_date` DATE NOT NULL,
  `description` VARCHAR(255) NOT NULL,
  `amount` DECIMAL(12,2) NOT NULL,
  `category_id` INT NOT NULL,
  `status` ENUM('REQUESTED', 'APPROVED', 'PURCHASED', 'PAID', 'POSTED_TO_GL', 'REJECTED') DEFAULT 'REQUESTED',
  `requested_by` INT NOT NULL,
  `approved_by` INT NULL,
  `paid_by` INT NULL,
  `gl_event_id` INT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  FOREIGN KEY (`category_id`) REFERENCES `expense_categories`(`id`),
  INDEX `idx_be_school` (`school_id`),
  INDEX `idx_be_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `business_transaction_events` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `event_uuid` CHAR(36) NOT NULL UNIQUE,
  `business_unit_id` INT NOT NULL,
  `event_type` VARCHAR(50) NOT NULL,
  `source_table` VARCHAR(50) NOT NULL,
  `source_id` INT NOT NULL,
  `event_payload` JSON NOT NULL,
  `posting_status` ENUM('PENDING', 'POSTED', 'FAILED', 'REVERSED') DEFAULT 'PENDING',
  `gl_transaction_id` INT NULL,
  `retry_count` INT DEFAULT 0,
  `processed_by` INT NULL,
  `error_message` TEXT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `posted_at` TIMESTAMP NULL,
  INDEX `idx_bte_status` (`school_id`, `posting_status`),
  UNIQUE KEY `uq_event_source` (`school_id`, `source_table`, `source_id`, `event_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
