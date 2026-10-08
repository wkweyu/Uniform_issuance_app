# Business Operations Platform Enterprise Architecture Implementation Directive

## Executive Summary & Non-Negotiable Core Directives

This document establishes the authoritative **Enterprise Architecture Implementation Directive** for evolving the school's **Income Generating Activities (IGA) / Farm Module** into a complete, ERP-grade **Business Operations Platform**.

Adhering strictly to the **Existing Code First Policy**, this implementation creates an operational integration backbone connecting:
- Farm / IGA Management
- Uniform Issuance
- Transport Management
- Fleet Management
- Student Fees Ledger
- Procurement
- Inventory Core
- Finance / General Ledger

### Non-Negotiable Implementation Safety Rules
Before modifying any code, the following rules are strictly enforced:
1. **Inspect Before Changing**: Inspect existing database schema, models, services, routes, templates, APIs, and migration history.
2. **Do Not Rewrite Working Modules**: Do not replace or rewrite existing working modules or workflows with duplicate implementations.
3. **Specialized Modules Remain Authoritative**:
   - **Uniform Issuance**: Authoritative for student uniform selection, student search, admission number lookup, uniform issue workflow, student fee debit creation, and receipts.
   - **Transport Module**: Authoritative for route management, student transport assignments, and transport billing.
   - **Procurement**: Authoritative for supplier purchases, purchase orders (POs), Goods Received Notes (GRN), and stock receiving.
   - **Fees Module**: Authoritative for student accounts, fee ledger, and Accounts Receivable (AR) balances.
   - **Finance Module**: Authoritative for GL posting, double-entry accounting, and financial statements.
4. **Configuration-Driven Design**: Do not hardcode values using ENUMs for business unit types, expense categories, inventory transaction types, loss types, or location types. Use administrative CRUD configuration tables.
5. **No Duplicate Truths**: Evolve `item_stock` into the single central inventory engine; avoid creating parallel stock tables.
6. **Multi-Tenant SaaS Integrity**: Enforce strict `school_id` isolation across all schema extensions, composite indexes, and queries.

---

## 1. Core Integration Architecture & Domain Boundaries

### 1.1 Architectural Topology
```
                          BUSINESS OPERATIONS CORE LAYER
                                       |
                     Business Units (`business_units`)
                                       |
 ---------------------------------------------------------------------------------------------
 |                     |                         |                         |
Farm / IGA            Uniform Shop              Transport Services        Future Business Units
(AGRICULTURE)         (RETAIL)                  (TRANSPORT)               (Bakery, Rentals, Canteen)
 ---------------------------------------------------------------------------------------------
                                       |
                        Inventory Transaction Engine
                                       |
                      Central Inventory (`item_stock`)
                                       |
                    Stock Movement Audit (`stock_movements`)
                                       |
                    Physical Store (`inventory_locations`)
                                       |
 ---------------------------------------------------------------------------------------------
 |                                     |                                                     |
Procurement Integration               Student Fees Ledger Integration                       Finance GL Integration
- Purchase Orders (POs)                - Student Fee Debits / AR                             - Accounting Event Queue
- Goods Received Notes (GRN)           - Receipt Lifecycle Events                            - Double-Entry Journaling
```

### 1.2 Architectural Decision: Uniform Issuance vs. Generic POS
Uniform Issuance **must NOT** be migrated into POS. Uniform Issuance remains a specialized student service module with specific domain rules (class-based requirements, student eligibility, sizing matrices, term restrictions, student fee billing, parent statements).

The POS engine is implemented separately for commercial transactions (Tuckshop, Farm produce, Bakery, External sales, Merchandise, Rentals). Uniform Issuance connects directly to the **Inventory Transaction Engine** to deduct `item_stock` and enqueue accounting events without altering its student issuance workflow or fee debiting.

---

## 2. Dynamic Configuration-Driven Schema Specifications

To prevent hardcoding and support future administrative scalability, all lookup categories use configuration tables.

```sql
-- =============================================================================
-- 1. CONFIGURATION LOOKUP TABLES (No Hardcoded ENUMs)
-- =============================================================================

CREATE TABLE IF NOT EXISTS `business_unit_types` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE, -- e.g. 'AGRICULTURE', 'RETAIL', 'FOOD_BEVERAGE', 'TRANSPORT', 'RENTAL', 'SERVICES', 'PRODUCTION'
  `name` VARCHAR(100) NOT NULL,
  `description` TEXT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `location_types` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE, -- e.g. 'WAREHOUSE', 'STORE', 'COLD_STORAGE', 'FUEL_TANK', 'TRANSIT'
  `name` VARCHAR(100) NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `inventory_transaction_types` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `code` VARCHAR(50) NOT NULL UNIQUE, -- e.g. 'PURCHASE', 'PRODUCTION', 'SALE', 'TRANSFER', 'SPOILAGE', 'ADJUSTMENT', 'ISSUANCE'
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

-- Seed Default Configuration Lookups
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
-- 2. BUSINESS UNITS & LOCATION CORE
-- =============================================================================

CREATE TABLE IF NOT EXISTS `business_units` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `name` VARCHAR(150) NOT NULL,
  `type_id` INT NOT NULL, -- Link to business_unit_types
  `manager_id` INT NULL, -- Link to users.userNo
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
  `location_type_id` INT NOT NULL, -- Link to location_types
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
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `selling_price` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `category` VARCHAR(50) DEFAULT 'General',
  ADD COLUMN IF NOT EXISTS `unit_of_measure` VARCHAR(30) DEFAULT 'units',
  ADD COLUMN IF NOT EXISTS `sku` VARCHAR(50) NULL,
  ADD KEY IF NOT EXISTS `idx_stock_loc` (`location_id`),
  ADD KEY IF NOT EXISTS `idx_stock_bu` (`business_unit_id`),
  ADD CONSTRAINT `fk_stock_loc` FOREIGN KEY (`location_id`) REFERENCES `inventory_locations`(`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_stock_bu` FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE SET NULL;

ALTER TABLE `stock_movements`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `location_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `transaction_type_id` INT NULL, -- Link to inventory_transaction_types
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `reference_no` VARCHAR(100) NULL,
  ADD KEY IF NOT EXISTS `idx_sm_school` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_sm_bu` (`business_unit_id`),
  ADD KEY IF NOT EXISTS `idx_sm_loc` (`location_id`),
  ADD CONSTRAINT `fk_sm_type` FOREIGN KEY (`transaction_type_id`) REFERENCES `inventory_transaction_types`(`id`) ON DELETE SET NULL;

-- =============================================================================
-- 4. DEPARTMENT INVENTORY ISSUE TRANSACTIONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS `inventory_issue_transactions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `target_department` ENUM('KITCHEN', 'BOARDING', 'MAINTENANCE', 'ADMINISTRATION', 'TRANSPORT', 'OTHER') NOT NULL,
  `item_id` INT NOT NULL,
  `from_location_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_cost` DECIMAL(12,2) NOT NULL,
  `total_value` DECIMAL(12,2) NOT NULL,
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'APPROVED',
  `approved_by` INT NULL,
  `gl_event_id` INT NULL,
  `issue_date` DATE NOT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  FOREIGN KEY (`from_location_id`) REFERENCES `inventory_locations`(`id`),
  INDEX `idx_iit_school` (`school_id`),
  INDEX `idx_iit_date` (`issue_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 5. BATCH PRODUCTION & LOSS MANAGEMENT
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
  `unit_production_cost` DECIMAL(12,2) DEFAULT 0.00, -- total_input_cost / saleable_qty
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
  `loss_type_id` INT NOT NULL, -- Link to production_loss_types
  `reason` TEXT NULL,
  `financial_value` DECIMAL(12,2) DEFAULT 0.00,
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'APPROVED',
  `approved_by` INT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`production_batch_id`) REFERENCES `production_batches`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  FOREIGN KEY (`loss_type_id`) REFERENCES `production_loss_types`(`id`),
  INDEX `idx_pl_school` (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 6. POS & MULTI-ITEM SALES
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

-- =============================================================================
-- 7. EXPENSE APPROVAL LIFECYCLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS `business_expenses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `expense_date` DATE NOT NULL,
  `description` VARCHAR(255) NOT NULL,
  `amount` DECIMAL(12,2) NOT NULL,
  `category_id` INT NOT NULL, -- Link to expense_categories
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

-- =============================================================================
-- 8. ASYNCHRONOUS ACCOUNTING EVENT QUEUE
-- =============================================================================

CREATE TABLE IF NOT EXISTS `business_transaction_events` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `event_type` ENUM('POS_SALE', 'STUDENT_AR_SALE', 'EXPENSE_APPROVED', 'INTER_DEPT_TRANSFER', 'PRODUCTION_COST_ALLOCATION', 'SPOILAGE_WRITE_OFF') NOT NULL,
  `source_table` VARCHAR(50) NOT NULL,
  `source_id` INT NOT NULL,
  `event_payload` JSON NOT NULL,
  `posting_status` ENUM('PENDING', 'POSTED', 'FAILED', 'REVERSED') DEFAULT 'PENDING',
  `gl_transaction_id` INT NULL,
  `error_message` TEXT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `posted_at` TIMESTAMP NULL,
  INDEX `idx_bte_status` (`school_id`, `posting_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 3. Procurement, Transport, & Uniform Module Integrations

### 3.1 Procurement Integration (Goods Received Notes)
Stock purchases **must never be created manually** for purchased items.
```
Purchase Requisition ---> Purchase Order (PO) ---> Supplier Delivery ---> Goods Received Note (GRN) ---> item_stock Increase ---> Stock Movement Audit
```
1. Uniform Purchase: PO for 500 shirts $\rightarrow$ GRN received $\rightarrow$ `item_stock.current_stock` $+500$ at specified location.
2. Farm Purchase: Animal Feed PO $\rightarrow$ GRN received $\rightarrow$ `item_stock` increases $\rightarrow$ Production batch consumes feed.

### 3.2 Uniform Module Integration
The existing Uniform Issuance workflow remains intact:
$$\text{Search Student} \longrightarrow \text{Select Items} \longrightarrow \text{Validate Available Stock} \longrightarrow \text{Issue} \longrightarrow \text{Debit Student Fees} \longrightarrow \text{Receipt}$$
Upon issuance:
1. Validate `item_stock.current_stock` availability at specified `location_id`.
2. Deduct `item_stock.current_stock`.
3. Create `stock_movements` record (`transaction_type_id = ISSUANCE`).
4. Enqueue `business_transaction_events` record for GL posting.

### 3.3 Transport & Fleet Integration
Existing transport workflows (route creation, student transport assignment, automatic fee billing, bus records, fuel vouchers) remain unchanged.
- **Route / Assignment Modifications**: When a student changes transport routes, `StudentService` / `TransportService`:
  1. Calculates the billing difference.
  2. Reverses prior billing where applicable.
  3. Posts new student fee debit via `FeesService`.
  4. Maintains audit history.
- **Vehicle Maintenance & Fuel Expenses**: Routed through `business_expenses` pipeline (`REQUESTED` $\rightarrow$ `APPROVED` $\rightarrow$ `PURCHASED` $\rightarrow$ `PAID` $\rightarrow$ `POSTED_TO_GL`).

---

## 4. Asynchronous Accounting Event Queue & Double-Entry GL Matrix

Business transactions do not post to Finance directly. Instead, they publish to `business_transaction_events`. The Finance Posting Service processes queued events into balanced double-entry transactions in `finance_transactions` and `ledger_entries`:

| Event Type | Debit Account | Credit Account | Cash / Non-Cash |
| :--- | :--- | :--- | :--- |
| **POS Cash Sale** | Cash / Bank GL | Business Unit `revenue_gl_account` | Cash |
| **Student AR Sale** | Student Accounts Receivable (AR) | Business Unit `revenue_gl_account` | Credit |
| **COGS (Sale)** | Business Unit `cogs_gl_account` | Business Unit `inventory_gl_account` | Non-Cash |
| **Approved Expense** | Business Unit `expense_gl_account` | Accounts Payable / Cash GL | Cash / Credit |
| **Department Issue** | Department Expense GL (Food/Boarding/Admin) | Business Unit `inventory_gl_account` / Revenue | Non-Cash Journal |
| **Spoilage / Loss** | Spoilage Expense GL | Business Unit `inventory_gl_account` | Non-Cash Journal |

---

## 5. Migration-Safe 6-Phase Rollout Plan

```
+-----------------------------------------------------------------------------------+
|                     6-PHASE MIGRATION-SAFE ROLLOUT ROADMAP                        |
+-----------------------------------------------------------------------------------+
| PHASE 1: Configuration Tables, Business Units & Locations Foundation              |
| - Execute migration script 060_business_operations_core.sql                       |
| - Create CRUD configuration tables (`business_unit_types`, `location_types`, etc.)|
| - Create `business_units`, `inventory_locations`, and `income_activities` view   |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 2: Single-Source Multi-Location Inventory & Department Issue Engine         |
| - Evolve `item_stock` and `stock_movements` with location & business unit links   |
| - Implement `inventory_issue_transactions` for internal consumption               |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 3: Specialized Module Integration Adapters (Uniform, Fleet & Procurement)   |
| - Uniform Adapter: Validate stock & deduct `item_stock` at location upon issuance |
| - Transport Adapter: Handle route changes with billing reversals & fee debits     |
| - Procurement Adapter: Connect GRN stock receipts directly to `item_stock`        |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 4: Generic POS, Production Batches, & Loss Management                       |
| - Implement generic POS (`business_sales` & `business_sales_items`)               |
| - Implement `production_batches` & `production_losses` tracking                   |
| - Implement multi-stage expense approval workflow (`business_expenses`)           |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 5: Asynchronous Accounting Event Queue & GL Posting                         |
| - Connect business transaction events to `business_transaction_events`            |
| - Implement Finance Posting Service for double-entry GL generation                |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 6: Enterprise Reporting, Dashboards, & Regression Verification              |
| - Build KPI cards for Dairy, Fleet, Uniforms, Tuckshop, and Rentals                |
| - Implement Excel/CSV/PDF drill-down reports                                      |
| - Execute regression testing suite across all existing modules                    |
+-----------------------------------------------------------------------------------+
```

---

## 6. Pre-Implementation Regression Protection Checklist

After each implementation phase, the following regression checklist must be verified:

- [ ] **Application Health**:
  - [ ] Server starts cleanly with zero import errors or missing dependencies
  - [ ] All blueprint endpoints respond with 200 OK (zero HTTP 500 errors)
- [ ] **Uniform Module**:
  - [ ] Student search and lookup work (`/issue_uniform`)
  - [ ] Uniform item creation & pricing work (`/manage_uniform_items`)
  - [ ] Uniform issuance deducts `item_stock` correctly
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
  - [ ] Goods Received Note (GRN) updates `item_stock` cleanly
- [ ] **Inventory Core**:
  - [ ] All stock movements record immutable audit entries in `stock_movements`

---

## 7. Conclusion

This Implementation Directive establishes the complete enterprise framework for the Business Operations Platform. Adhering strictly to the **Existing Code First Policy**, it unifies inventory under `item_stock`, connects sales, procurement, and GL journaling, and enforces multi-level approvals while preserving 100% operational continuity for all existing school modules.
