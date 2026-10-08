# SkoolTrack Pro Business Operations Platform - Enterprise Architecture Implementation Directive

## Executive Summary & Implementation Principles

This document defines the authoritative, ERP-grade architectural blueprint and implementation specification for evolving the school's **Income Generating Activities (IGA) / Farm Module** into a complete **Business Operations Platform**.

Adhering strictly to the **Existing Code First Policy**, this implementation creates an operational integration backbone connecting:
- Farm / IGA Management
- Uniform Issuance
- Transport Management
- Fleet Management
- Student Fees Ledger
- Procurement
- Inventory Core
- Finance / General Ledger

---

## 1. Non-Negotiable Implementation Safety Rules & Restrictions

### 1.1 Implementation Restrictions
Before modifying any code, the engineer MUST follow these rules:
1. **Application Health Verification**: Run application startup tests and inspect existing routes and services before touching code.
2. **Do Not Rewrite Working Modules**: Do not replace or rewrite existing working modules or workflows with duplicate implementations.
3. **Use Adapters Around Master Modules**: Create service adapters around master modules instead of modifying their internal logic:
   - **Uniform Issuance**: Authoritative for student uniform selection, student search, admission number lookup, uniform issue workflow, student fee debit creation, and receipts.
   - **Transport Module**: Authoritative for route management, student transport assignments, and transport billing.
   - **Procurement**: Authoritative for supplier purchases, purchase orders (POs), Goods Received Notes (GRN), and stock receiving.
   - **Fees Module**: Authoritative for student accounts, fee ledger, and Accounts Receivable (AR) balances.
   - **Finance Module**: Authoritative for GL posting, double-entry accounting, and financial statements.
4. **Configuration-Driven Design**: Do not hardcode ENUMs for business unit types, departments, expense categories, inventory transaction types, loss types, item classifications, or location types. Use administrative CRUD configuration tables.
5. **Centralized Inventory Service Layer**: All stock changes **MUST** pass through `InventoryTransactionService`. No module may directly update `item_stock.current_stock`.
6. **Accounting Queue Idempotency**: All accounting events mandate composite unique constraints `UNIQUE(source_table, source_id, event_type)` to guarantee zero duplicate GL postings.
7. **Phase Verification**: After each phase, run database migrations, start the application, test existing URLs, and check logs to verify zero HTTP 500 errors.

---

## 2. Core Architecture & Domain Boundaries

### 2.1 Architectural Topology
```
                          SALES & BILLING LAYER
                                    |
        ----------------------------------------------------------
        |                                                        |
 Student Services POS Adapter                             Commercial POS
        |                                                        |
 Uniform Issuance                                        Tuckshop/Farm/Retail
        |
 Student Fees AR (`FeesService`)


                          INVENTORY SERVICE LAYER
                                    |
                    `InventoryTransactionService`
                                    |
                    Central Inventory (`item_stock`)
                                    |
                 Stock Movement Audit (`stock_movements`)
                                    |
                 Physical Store (`inventory_locations`)


                    ACCOUNTING EVENT QUEUE LAYER
                                    |
              Accounting Event Queue (`business_transaction_events`)
                   `UNIQUE(source_table, source_id, event_type)`
                                    |
                      Finance Posting Service
                                    |
                           General Ledger (GL)
```

### 2.2 Uniform Issuance vs. Commercial POS Clarification
**Uniform Issuance acts as a specialized sales adapter consuming the Business Operations Inventory Engine and Student Fees AR services.** It is NOT converted into generic POS because its transaction lifecycle is governed by academic rules (checking class requirements, allowed items, sizes, term restrictions, student fee billing, parent statements). Generic POS handles commercial transactions (Tuckshop, Farm produce, Bakery, Merchandise, Rentals).

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
  `code` VARCHAR(50) NOT NULL UNIQUE,
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `item_classifications` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE, -- e.g. 'CONSUMABLE', 'RETURNABLE', 'ASSET', 'SALE_ITEM', 'PRODUCTION_INPUT'
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
('ISSUANCE', 'Student / Department Issuance');

INSERT IGNORE INTO `item_classifications` (`code`, `name`) VALUES
('CONSUMABLE', 'Consumable Item (Non-Returnable)'),
('RETURNABLE', 'Returnable Asset (Custody Tracked)'),
('ASSET', 'Fixed Asset'),
('SALE_ITEM', 'Commercial Retail Item'),
('PRODUCTION_INPUT', 'Production Raw Material / Input');

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
-- 2. BUSINESS UNITS & LOCATIONS
-- =============================================================================

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

-- Backward-Compatibility View for Legacy Code
CREATE OR REPLACE VIEW `income_activities` AS
SELECT id, school_id, name, description, revenue_gl_account AS gl_income_account, expense_gl_account AS gl_expense_account, is_active, created_at
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

-- =============================================================================
-- 3. EVOLVED CENTRAL INVENTORY CORE (`item_stock` & `stock_movements`)
-- =============================================================================

ALTER TABLE `item_stock`
  ADD COLUMN IF NOT EXISTS `location_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `classification_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `selling_price` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `category` VARCHAR(50) DEFAULT 'General',
  ADD COLUMN IF NOT EXISTS `unit_of_measure` VARCHAR(30) DEFAULT 'units',
  ADD COLUMN IF NOT EXISTS `sku` VARCHAR(50) NULL,
  ADD KEY IF NOT EXISTS `idx_stock_loc` (`location_id`),
  ADD KEY IF NOT EXISTS `idx_stock_bu` (`business_unit_id`),
  ADD KEY IF NOT EXISTS `idx_stock_class` (`classification_id`),
  ADD CONSTRAINT `fk_stock_loc` FOREIGN KEY (`location_id`) REFERENCES `inventory_locations`(`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_stock_bu` FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_stock_class` FOREIGN KEY (`classification_id`) REFERENCES `item_classifications`(`id`) ON DELETE SET NULL;

ALTER TABLE `stock_movements`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `location_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `transaction_type_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `reference_no` VARCHAR(100) NULL,
  ADD KEY IF NOT EXISTS `idx_sm_school` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_sm_bu` (`business_unit_id`),
  ADD KEY IF NOT EXISTS `idx_sm_loc` (`location_id`),
  ADD CONSTRAINT `fk_sm_type` FOREIGN KEY (`transaction_type_id`) REFERENCES `inventory_transaction_types`(`id`) ON DELETE SET NULL;

-- =============================================================================
-- 4. DEPARTMENT ISSUES & RETURNABLE STOCK LEDGERS
-- =============================================================================

CREATE TABLE IF NOT EXISTS `inventory_issues` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `department_id` INT NOT NULL, -- Configurable department link
  `item_id` INT NOT NULL,
  `from_location_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_cost` DECIMAL(12,2) NOT NULL,
  `total_value` DECIMAL(12,2) NOT NULL,
  `recipient_user_no` INT NULL, -- Staff/Teacher receiving custody
  `is_returnable` BOOLEAN DEFAULT FALSE,
  `status` ENUM('ISSUED', 'RETURNED', 'WRITTEN_OFF') DEFAULT 'ISSUED',
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'APPROVED',
  `approved_by` INT NULL,
  `issue_date` DATE NOT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  FOREIGN KEY (`department_id`) REFERENCES `departments`(`id`),
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  FOREIGN KEY (`from_location_id`) REFERENCES `inventory_locations`(`id`),
  INDEX `idx_ii_school` (`school_id`),
  INDEX `idx_ii_date` (`issue_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `inventory_returns` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `inventory_issue_id` INT NOT NULL,
  `to_location_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `condition_notes` TEXT NULL,
  `return_date` DATE NOT NULL,
  `received_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`inventory_issue_id`) REFERENCES `inventory_issues`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`to_location_id`) REFERENCES `inventory_locations`(`id`),
  INDEX `idx_ir_school` (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 5. BATCH PRODUCTION & APPROVED LOSS MANAGEMENT
-- =============================================================================

CREATE TABLE IF NOT EXISTS `production_batches` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `batch_no` VARCHAR(50) NOT NULL,
  `item_id` INT NOT NULL,
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
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  FOREIGN KEY (`location_id`) REFERENCES `inventory_locations`(`id`),
  INDEX `idx_pb_school` (`school_id`),
  INDEX `idx_pb_batch` (`batch_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `production_losses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `production_batch_id` INT NOT NULL,
  `item_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `loss_type_id` INT NOT NULL,
  `reason` TEXT NULL,
  `financial_value` DECIMAL(12,2) DEFAULT 0.00,
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'PENDING', -- Mandates approval
  `approved_by` INT NULL,
  `financial_posting_status` ENUM('PENDING', 'POSTED', 'FAILED') DEFAULT 'PENDING',
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`production_batch_id`) REFERENCES `production_batches`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  FOREIGN KEY (`loss_type_id`) REFERENCES `production_loss_types`(`id`),
  INDEX `idx_pl_school` (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 6. POS, EXPENSES & IDEMPOTENT ACCOUNTING QUEUE
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
  `item_id` INT NULL,
  `item_name` VARCHAR(150) NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_price` DECIMAL(12,2) NOT NULL,
  `total_price` DECIMAL(12,2) NOT NULL,
  FOREIGN KEY (`sale_id`) REFERENCES `business_sales`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`) ON DELETE SET NULL,
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
  `business_unit_id` INT NOT NULL,
  `event_type` VARCHAR(50) NOT NULL, -- e.g. 'POS_SALE', 'STUDENT_AR_SALE', 'EXPENSE_APPROVED', 'INTER_DEPT_TRANSFER'
  `source_table` VARCHAR(50) NOT NULL,
  `source_id` INT NOT NULL,
  `event_payload` JSON NOT NULL,
  `posting_status` ENUM('PENDING', 'POSTED', 'FAILED', 'REVERSED') DEFAULT 'PENDING',
  `gl_transaction_id` INT NULL,
  `error_message` TEXT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `posted_at` TIMESTAMP NULL,
  INDEX `idx_bte_status` (`school_id`, `posting_status`),
  -- Strict Idempotency Constraint to Prevent Duplicate GL Postings
  UNIQUE KEY `uq_event_source` (`school_id`, `source_table`, `source_id`, `event_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 4. Service Layer Abstraction & Procurement 3-Way Matching

### 4.1 Centralized `InventoryTransactionService`
**No module may directly modify `item_stock.current_stock`.** All inventory changes pass through `InventoryTransactionService`:
- `receive_stock(item_id, location_id, qty, unit_cost, ref_no)`
- `issue_stock(item_id, location_id, qty, recipient_id, ref_no)`
- `transfer_stock(item_id, from_location_id, to_location_id, qty, ref_no)`
- `consume_stock(item_id, location_id, dept_id, qty, ref_no)`
- `produce_stock(batch_id, item_id, location_id, qty, unit_cost)`
- `adjust_stock(item_id, location_id, new_qty, reason)`
- `writeoff_stock(item_id, location_id, qty, loss_type_id, reason)`

### 4.2 Procurement Three-Way Matching
Before supplier invoices are approved and posted to Accounts Payable, Procurement enforces 3-way matching:
$$\text{Purchase Order (PO) Quantity} = \text{Goods Received Note (GRN) Quantity} = \text{Supplier Invoice Quantity}$$
If quantity mismatches exist, the system flags the invoice for administrative review prior to payment.

---

## 5. Enterprise Reporting Specifications

Reports support filtering (date range, business unit, location, department), drill-down, CSV/Excel export, and PDF generation:

1. **Inventory Reports**:
   - Stock Valuation Report (`item_stock.current_stock` $\times$ `unit_cost`)
   - Stock Aging & Slow Moving / Dead Stock Analysis
   - Stock Movement Ledger Audit Log
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
5. **Transport Reports**:
   - Route Profitability Report (Revenue vs Fuel/Maintenance Expenses)
   - Vehicle Utilization & Maintenance Cost per KM
6. **Business Unit Financial Reports**:
   - Profit & Loss Statement per Business Unit

---

## 6. Revised Risk-Mitigated 6-Phase Migration Plan

```
+-----------------------------------------------------------------------------------+
|                   REVISED 6-PHASE RISK-MITIGATED ROADMAP                         |
+-----------------------------------------------------------------------------------+
| PHASE 1: Configuration Tables & Inventory Schema Extensions                      |
| - Execute migration script 060_business_operations_core.sql                       |
| - Create lookup tables (`business_unit_types`, `departments`, `location_types`)   |
| - Evolve `item_stock` and `stock_movements` with location/business unit links     |
| - Create `income_activities` SQL view for 100% backward compatibility             |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 2: Centralized Inventory Transaction Service Layer                         |
| - Implement `InventoryTransactionService` (`receive`, `issue`, `transfer`)        |
| - Enforce zero direct writes to `item_stock.current_stock`                        |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 3: Specialized Module Adapters (Uniform, Procurement, Transport)             |
| - Uniform Adapter: Route uniform issuance stock deductions through `InventoryService` |
| - Procurement Adapter: Connect GRN receipts & enforce 3-Way Matching               |
| - Transport Adapter: Handle route change billing reversals & fee debits            |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 4: Department Issues, Production Batches & Loss Approvals                    |
| - Implement `inventory_issues` & `inventory_returns` for returnable assets        |
| - Implement `production_batches` & `production_losses` with approval workflows    |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 5: Generic Commercial POS & Multi-Stage Expenses                            |
| - Implement generic commercial POS (`business_sales` & `business_sales_items`)     |
| - Implement multi-stage expense workflow (`REQUESTED` -> `APPROVED` -> `PAID`)    |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 6: Idempotent Accounting Event Queue, GL Posting & Enterprise Reports        |
| - Implement `business_transaction_events` with composite unique constraint        |
| - Implement Finance Posting Service for GL journal generation                     |
| - Implement enterprise reports with Excel/CSV/PDF export and operational dashboards|
+-----------------------------------------------------------------------------------+
```

---

## 7. Pre-Implementation Regression Protection Checklist

After each phase, the following regression checklist MUST be verified:

- [ ] **Application Health**:
  - [ ] Flask application starts cleanly with zero import errors
  - [ ] All blueprint routes respond with 200 OK (zero HTTP 500 errors)
- [ ] **Uniform Module**:
  - [ ] Student search and lookup work (`/issue_uniform`)
  - [ ] Uniform item creation & pricing work (`/manage_uniform_items`)
  - [ ] Uniform issuance deducts `item_stock` via `InventoryTransactionService`
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

This Implementation Directive establishes the authoritative ERP specification for the Business Operations Platform. By centralizing inventory under `InventoryTransactionService`, implementing configurable departments and item classifications, enforcing 3-way matching, guaranteeing accounting event queue idempotency, and structuring a 6-phase rollout, SkoolTrack Pro achieves enterprise-grade operational scalability with zero disruption to working modules.
