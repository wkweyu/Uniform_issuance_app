# SkoolTrack Pro Business Operations Platform - Enterprise Architecture Implementation Directive

## Executive Summary & Implementation Principles

This document defines the authoritative, ERP-grade architectural blueprint and implementation specification for evolving the school's **Income Generating Activities (IGA) / Farm Module** into a complete **Business Operations Platform**.

Adhering strictly to the **Existing Code First Policy**, this implementation creates an operational integration backbone connecting:
- Farm / IGA Management
- Uniform Issuance & Return Lifecycle
- Transport Management
- Fleet Management
- Student Fees Ledger
- Procurement (with 3-Way Matching)
- Central Multi-Location Inventory Engine
- Finance / General Ledger

---

## 1. AI Implementation Safety Directive & Code First Rules

### 1.1 Non-Negotiable AI Safety Rules
Before modifying any code or committing changes, the engineer MUST follow these rules:
1. **Startup Verification**: Run the application startup command (`python app.py`) before and after every phase to verify zero runtime errors.
2. **Diff Verification**: Run `git diff` before committing to verify that:
   - No existing route is removed or altered.
   - No existing service signature is renamed.
   - No database migration modifies existing production data destructively.
3. **Regression Testing**: Run existing test suites (`pytest`) after every phase to confirm zero regressions.
4. **No Feature Disabling**: Never fix errors by disabling or removing existing functionality. Create adapters around existing modules instead.
5. **Specialized Master Modules**:
   - **Uniform Issuance**: Authoritative for student uniform selection, student search, admission number lookup, uniform issue workflow, fee debiting, returns/exchanges, and receipts.
   - **Transport Module**: Authoritative for route management, student transport assignments, and transport billing.
   - **Procurement**: Authoritative for supplier purchases, purchase orders (POs), Goods Received Notes (GRN), and stock receiving.
   - **Fees Module**: Authoritative for student accounts, fee ledger, and Accounts Receivable (AR) balances.
   - **Finance Module**: Authoritative for GL posting, double-entry accounting, and financial statements.

---

## 2. Core Architecture & Domain Boundaries

### 2.1 Architectural Topology
```
                          SALES & BILLING LAYER
                                    |
        ----------------------------------------------------------
        |                                                        |
 Student Services Adapter                                 Commercial POS
        |                                                        |
 Uniform Issuance & Return Adapter                       Tuckshop/Farm/Retail
        |
 Student Fees AR (`FeesService`)


                          INVENTORY SERVICE LAYER
                                    |
                    `InventoryTransactionService`
                                    |
                        Item Master (`item_master`)
                                    |
                    Central Stock (`item_stock`)
                                    |
                 Stock Movement Audit (`stock_movements`)
                                    |
                 Physical Store (`inventory_locations`)


                    ACCOUNTING EVENT QUEUE LAYER
                                    |
              Accounting Event Queue (`business_transaction_events`)
                   `UNIQUE(school_id, source_table, source_id, event_type)`
                   `event_uuid CHAR(36)`, `retry_count`, `processed_by`
                                    |
                      Finance Posting Service
                                    |
                           General Ledger (GL)
```

### 2.2 Uniform Issuance & Return Adapter Clarification
**Uniform Issuance acts as a specialized sales adapter consuming the Business Operations Inventory Engine and Student Fees AR services.** It is NOT converted into generic POS because its transaction lifecycle is governed by academic rules (class requirements, sizing, allowed items, term restrictions, parent billing).

#### Uniform Return & Exchange Lifecycle
When a student returns or exchanges a uniform item (wrong size, damaged item, or exchange):
```
Uniform Return / Exchange Request
               |
    `InventoryTransactionService` (receive_stock / return_stock)
               |
  `item_stock.current_stock` Restored at Location
               |
    `stock_movements` Audit Log (`UNIFORM_RETURN` / `UNIFORM_EXCHANGE`)
               |
   `FeesService` Credit Note / Account Balance Adjustment
               |
    `business_transaction_events` Enqueued for GL Posting
```

---

## 3. Dynamic Configuration-Driven Database Schemas

All lookup categories use configurable database tables to prevent hardcoded ENUMs.

```sql
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
  `code` VARCHAR(50) NOT NULL, -- e.g. 'KITCHEN', 'BOARDING', 'MAINTENANCE', 'ADMINISTRATION', 'ICT', 'TRANSPORT'
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
  `code` VARCHAR(50) NOT NULL UNIQUE, -- e.g. 'PURCHASE', 'PRODUCTION', 'SALE', 'TRANSFER', 'SPOILAGE', 'ADJUSTMENT', 'ISSUANCE', 'UNIFORM_RETURN', 'UNIFORM_EXCHANGE'
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `item_categories` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `parent_id` INT NULL, -- Hierarchical categories (e.g. Uniform -> Shirts)
  `code` VARCHAR(50) NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE,
  INDEX `idx_cat_school` (`school_id`),
  FOREIGN KEY (`parent_id`) REFERENCES `item_categories`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `item_classifications` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE, -- e.g. 'CONSUMABLE', 'RETURNABLE', 'FIXED_ASSET', 'SALE_ITEM', 'UNIFORM', 'FOOD_ITEM', 'MEDICINE', 'FARM_INPUT', 'FUEL', 'STATIONERY'
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `production_loss_types` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE, -- e.g. 'SPILLAGE', 'SPOILAGE', 'CONTAMINATION', 'EVAPORATION', 'EXPIRY'
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `expense_categories` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE, -- e.g. 'FEED', 'DRUGS', 'FUEL', 'MAINTENANCE', 'SUPPLIES', 'LABOR', 'UTILITIES'
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed Default Configurations
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
-- 2. ITEM MASTER & MULTI-LOCATION STOCK CORE
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
SELECT id, school_id, name, description, revenue_gl_account AS gl_income_account, expense_gl_account AS gl_expense_account, is_active, created_at
FROM `business_units`;

CREATE TABLE IF NOT EXISTS `inventory_locations` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `name` VARCHAR(100) NOT NULL, -- e.g. 'Main Uniform Store', 'Cold Room', 'Main Diesel Tank'
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
  `custodian_id` INT NOT NULL, -- userNo, department_id, or AdmNo
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
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING', -- Mandates Supervisor Approval
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
  `event_uuid` CHAR(36) NOT NULL UNIQUE, -- Distributed Globally Unique ID
  `business_unit_id` INT NOT NULL,
  `event_type` VARCHAR(50) NOT NULL,
  `source_table` VARCHAR(50) NOT NULL,
  `source_id` INT NOT NULL,
  `event_payload` JSON NOT NULL,
  `posting_status` ENUM('PENDING', 'POSTED', 'FAILED', 'REVERSED') DEFAULT 'PENDING',
  `gl_transaction_id` INT NULL,
  `retry_count` INT DEFAULT 0,
  `processed_by` INT NULL, -- userNo or system worker
  `error_message` TEXT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `posted_at` TIMESTAMP NULL,
  INDEX `idx_bte_status` (`school_id`, `posting_status`),
  -- Strict Idempotency Constraint to Guarantee Zero Duplicate GL Postings
  UNIQUE KEY `uq_event_source` (`school_id`, `source_table`, `source_id`, `event_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 4. Service Abstractions, Procurement 3-Way Matching & Stock Adjustments

### 4.1 Centralized `InventoryTransactionService`
**No module may directly modify `item_stock.current_stock`.** All inventory changes pass through `InventoryTransactionService`:
- `receive_stock(item_master_id, location_id, qty, unit_cost, ref_no)`
- `issue_stock(item_master_id, location_id, qty, recipient_id, ref_no)`
- `transfer_stock(item_master_id, from_location_id, to_location_id, qty, ref_no)`
- `consume_stock(item_master_id, location_id, dept_id, qty, ref_no)`
- `produce_stock(batch_id, item_master_id, location_id, qty, unit_cost)`
- `adjust_stock(item_master_id, location_id, new_qty, reason, approved_by)`
- `writeoff_stock(item_master_id, location_id, qty, loss_type_id, reason, approved_by)`
- `return_stock(issue_id, to_location_id, qty, condition_notes, received_by)`

### 4.2 Procurement Three-Way Matching & Approval Policy
Stock purchases **MUST NEVER** be created manually. All supplier stock additions consume Procurement POs and Goods Received Notes (GRN). Before supplier invoices are approved for AP payment, Procurement enforces **3-Way Matching**:
$$\text{Purchase Order (PO) Quantity} = \text{Goods Received Note (GRN) Quantity} = \text{Supplier Invoice Quantity}$$

#### Manual Stock Adjustment Approval Rules
Manual stock level adjustments (e.g. adding 500 shirts) via arbitrary input are **strictly blocked**. Direct stock adjustments are permitted ONLY for:
1. Opening Balance Initialization
2. Stock Count Variance Correction
3. Damaged/Lost Stock Write-off

All manual adjustments mandate **supervisor approval** before stock levels update.

---

## 5. Enterprise Reporting & Weighted Average Costing Specifications

Reports support filtering (date range, business unit, location, department), drill-down, CSV/Excel export, and PDF generation:

1. **Inventory Audit Reports**:
   - **Stock Card Report**: Per-item audit statement tracking Opening Balance $+$ Purchases $-$ Issues $-$ Returns $-$ Adjustments $=$ Closing Balance.
   - **Weighted Average Inventory Valuation Report**:
     $$\text{Weighted Average Unit Cost} = \frac{\sum (\text{Qty Received} \times \text{Unit Cost})}{\sum \text{Qty Received}}$$
   - Stock Aging & Slow Moving / Dead Stock Analysis
   - Reorder Level Alert Report
2. **Uniform Reports**:
   - Purchase vs Issuance Analysis
   - Current Stock by Size & Location
   - Student Outstanding Uniform Charges Report
   - Item Gross Margin Report
3. **Farm / Production Reports**:
   - Production Yield Efficiency Report ($[\text{Saleable Output} / \text{Total Production}] \times 100$)
   - Spoilage & Loss % Report by Loss Type
   - Cost per Unit vs Market Selling Price Analysis
   - Batch Profitability Summary
4. **Department Consumption Reports**:
   - Kitchen Food Consumption Report
   - Boarding / Maintenance Expense Allocation Report
   - Department Usage vs Budget Variance Analysis

---

## 6. Revised Risk-Mitigated 6-Phase Rollout Plan

```
+-----------------------------------------------------------------------------------+
|                   REVISED 6-PHASE RISK-MITIGATED ROADMAP                         |
+-----------------------------------------------------------------------------------+
| PHASE 1: Discovery & Existing Schema Mapping (No Code Modifications)               |
| - Audit existing schema, routes, models, and services                              |
| - Map existing database constraints and dependencies                               |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 2: Database Foundation & Item Master                                        |
| - Execute migration script 060_business_operations_core.sql                       |
| - Create `item_master`, `business_units`, `inventory_locations`, lookup tables   |
| - Create `income_activities` SQL view for 100% backward compatibility             |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 3: Inventory Transaction Service Layer                                      |
| - Implement `InventoryTransactionService` (`receive`, `issue`, `transfer`, `return`)|
| - Enforce zero direct writes to `item_stock.current_stock`                        |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 4: Specialized Module Integration Adapters (Uniform, Procurement, Transport) |
| - Uniform Adapter: Issue/Return stock deductions via `InventoryService`           |
| - Procurement Adapter: Connect GRN stock receipts & enforce 3-Way Matching         |
| - Transport Adapter: Handle route change billing reversals & fee debits            |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 5: Business Operations: POS, Production Batches & Custody Issues            |
| - Implement `inventory_issues` & `inventory_custody` for returnable assets        |
| - Implement `production_batches` & `production_losses` with approval workflows    |
| - Implement commercial POS (`business_sales` & `business_sales_items`)             |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 6: Idempotent Accounting Event Queue, GL Posting & Enterprise Reports        |
| - Implement `business_transaction_events` with `event_uuid` & composite unique key |
| - Implement Finance Posting Service for GL journal generation                     |
| - Implement Stock Card reports & operational KPI dashboards                       |
+-----------------------------------------------------------------------------------+
```

---

## 7. Pre-Implementation Regression Protection Checklist

After each phase, the following regression checklist MUST be verified:

- [ ] **Application Health**:
  - [ ] Flask application starts cleanly (`python app.py`) with zero import errors
  - [ ] All blueprint routes respond with 200 OK (zero HTTP 500 errors)
- [ ] **Uniform Module**:
  - [ ] Student search and lookup work (`/issue_uniform`)
  - [ ] Uniform item creation & pricing work (`/manage_uniform_items`)
  - [ ] Uniform issuance & returns deduct/restore `item_stock` via `InventoryTransactionService`
  - [ ] Student fee account debits via `FeesService`
  - [ ] Receipt generation and PDF print preview operate without error
- [ ] **Transport Module**:
  - [ ] Vehicle management operates (`/fleet/buses`)
  - [ ] Route creation and route fee setting function (`/fleet/routes`)
  - [ ] Student transport route allocation and billing work (`/fleet/transport_assignments`)
  - [ ] Route change fee reversals and new debits calculate accurately
  - [ ] Fuel voucher generation and print work (`/fleet/issue_fuel`)
- [ ] **Student Fees & Ledger**:
  - [ ] Student statements remain 100% accurate (`/admin/fees/student/<admno>/statement`)
  - [ ] Fee waivers, discounts, and optional service charges operate cleanly
- [ ] **Procurement Module**:
  - [ ] Requisition creation and purchase order approval operate
  - [ ] Goods Received Note (GRN) updates `item_stock` cleanly and enforces 3-way matching
- [ ] **Inventory Core**:
  - [ ] All stock movements record immutable audit entries in `stock_movements`

---

## 8. Conclusion

This Implementation Directive establishes the authoritative ERP specification for the Business Operations Platform. By introducing `item_master`, centralizing inventory under `InventoryTransactionService`, implementing returnable asset custody tracking (`inventory_custody`), enforcing 3-way matching and adjustment approvals, guaranteeing accounting event queue idempotency (`event_uuid` $+$ unique constraint), and structuring a 6-phase rollout, SkoolTrack Pro achieves enterprise-grade operational scalability with zero disruption to working modules.
