# Business Operations Platform Architectural Specification & Implementation Blueprint

## Executive Summary

This document defines the final, ERP-grade architectural blueprint and implementation specification for evolving the school's **Income Generating Activities (IGA) / Farm Module** into a unified, enterprise **Business Operations Platform**.

Adhering strictly to the **Existing Code First Policy**, this design extends and connects existing production modules (**Uniform Issuance**, **Transport Management**, **Fleet Management**, **Student Fees Ledger**, **Procurement**, and **Finance GL**) without replacing, rewriting, or breaking them.

The Business Operations Platform serves as an operational integration backbone providing:
1. Dynamic Business Unit Management
2. Central Multi-Location Inventory Engine (`item_stock` & `inventory_locations`)
3. Unified POS & Student Fee Billing Adapters
4. Multi-Stage Expense Approval Lifecycle
5. Procurement Purchase Order & GRN Integration
6. Batch Production & Cost Accounting
7. Asynchronous Accounting Event Queue (`business_transaction_events`)
8. Enterprise Reporting & Drill-Down Analytics
9. Regression Protection Checklist & Implementation Safety Controls

---

## 1. Existing Code First Policy & Regression Protection Rules

### 1.1 Core Principles
1. **Extend Existing Functionality**: Reuse existing models, services, APIs, UI templates, and reports.
2. **Preserve Specialized Modules**: Do not modify existing working workflows unless required through a controlled service adapter.
3. **No Duplicate Truths**: Evolve `item_stock` into the single central inventory engine; avoid creating parallel stock tables.
4. **No Rewriting Billing Logic**: Reuse `StudentService` and `FeesService` for student fee debits; do not create parallel student billing engines.
5. **Multi-Tenant SaaS Integrity**: Enforce strict `school_id` isolation across all schema extensions, composite indexes, and queries.
6. **Backward Compatibility**: Maintain 100% route, service signature, and database template compatibility (`income_activities` SQL view).

### 1.2 Implementation Safety Rules
- **Rule 1**: Identify existing routes, service dependencies, and database tables before modifying code.
- **Rule 2**: Avoid breaking imports, renaming existing functions, or altering templates unless strictly necessary.
- **Rule 3**: Implement incrementally and execute startup tests, migration dry-runs, and regression test suites after each phase.
- **Rule 4**: Verify zero Internal Server Errors (500), broken blueprints, or missing imports.

---

## 2. Integration Architecture & Domain Boundaries

```
                    BUSINESS OPERATIONS CORE LAYER

                         Business Units (`business_units`)
                                      |
 ---------------------------------------------------------------------------------------
 |                    |                       |                        |
Farm / IGA           Uniform Shop            Transport Services       Future Business Units
(AGRICULTURE)        (RETAIL)                (TRANSPORT)              (Bakery, Rentals, Canteen)
 ---------------------------------------------------------------------------------------
                                      |
                           Central Inventory Engine
                                      |
                             `item_stock` Catalog
                                      |
                           `stock_movements` Audit Log
                                      |
                         `inventory_locations` Store
                                      |
 ---------------------------------------------------------------------------------------
 |                                    |                                                |
Procurement Integration              Student Fee Ledger Integration                  Finance GL Integration
- Purchase Orders (POs)               - Student Fee Debits / AR                       - Accounting Event Queue
- Goods Received Notes (GRN)          - Receipt Lifecycle Events                      - Double-Entry Journaling
```

---

## 3. Domain Naming & Database Schema Specifications

### 3.1 Standardized `business_*` Schema Extensions

| Legacy Table / Proposal | Evolved / Target Table Name | Domain Purpose & Code-First Mapping |
| :--- | :--- | :--- |
| `income_activities` | `business_units` | Core enterprise cost centers (View alias maintained for backward compatibility) |
| `income_inventory` *(Obsolete)* | `item_stock` *(Evolved)* | Single Central Multi-Location Inventory Engine |
| *N/A (New)* | `inventory_locations` | Physical warehouses, stores, cold rooms, fuel tanks |
| `income_stock_movements` *(Obsolete)* | `stock_movements` *(Evolved)* | Universal stock movement audit log |
| `income_sales` | `business_sales` | POS transactions, credit customer billing & invoices |
| `income_sales_items` *(New)* | `business_sales_items` | Multi-item sales detail rows |
| `income_expenses` | `business_expenses` | Multi-stage expense approval lifecycle |
| `income_transfers` *(New)* | `business_transfers` | Non-cash inter-departmental GL transfer ledger |
| `income_production_log` | `production_batches` | Agricultural & manufacturing batch production log |
| *N/A (New)* | `production_losses` | Spoilage, spillage, and wastage event log |
| *N/A (New)* | `business_transaction_events` | Asynchronous Accounting Event Queue for GL postings |

### 3.2 Migration-Safe DDL Schema

```sql
-- 1. Dynamic Business Units Entity
CREATE TABLE IF NOT EXISTS `business_units` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `name` VARCHAR(150) NOT NULL,
  `unit_type` ENUM('AGRICULTURE', 'RETAIL', 'FOOD_BEVERAGE', 'TRANSPORT', 'RENTAL', 'SERVICES', 'PRODUCTION', 'OTHER') NOT NULL DEFAULT 'AGRICULTURE',
  `manager_id` INT NULL, -- Link to users.userNo
  `cost_center_code` VARCHAR(50) NULL,
  `revenue_gl_account` VARCHAR(50) NULL,
  `expense_gl_account` VARCHAR(50) NULL,
  `inventory_gl_account` VARCHAR(50) NULL,
  `cogs_gl_account` VARCHAR(50) NULL,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_bu_school` (`school_id`),
  INDEX `idx_bu_type` (`unit_type`),
  CONSTRAINT `fk_bu_school` FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Backward-Compatibility Database View for Legacy Code
CREATE OR REPLACE VIEW `income_activities` AS
SELECT id, school_id, name, description, revenue_gl_account AS gl_income_account, expense_gl_account AS gl_expense_account, is_active, created_at
FROM `business_units`;

-- 2. Physical Inventory Locations Table
CREATE TABLE IF NOT EXISTS `inventory_locations` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `name` VARCHAR(100) NOT NULL, -- e.g. 'Main Uniform Store', 'Cold Room', 'Main Diesel Tank'
  `location_type` ENUM('WAREHOUSE', 'STORE', 'COLD_STORAGE', 'FUEL_TANK', 'TRANSIT', 'OTHER') DEFAULT 'STORE',
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE CASCADE,
  INDEX `idx_loc_school` (`school_id`),
  INDEX `idx_loc_bu` (`business_unit_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Evolving item_stock as Central Inventory Core
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

-- 4. Evolving stock_movements Audit Log
ALTER TABLE `stock_movements`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `location_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `movement_type` ENUM('PURCHASE', 'PRODUCTION', 'SALE', 'TRANSFER', 'SPOILAGE', 'ADJUSTMENT', 'ISSUANCE') NOT NULL DEFAULT 'ADJUSTMENT',
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `reference_no` VARCHAR(100) NULL,
  ADD KEY IF NOT EXISTS `idx_sm_school` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_sm_bu` (`business_unit_id`),
  ADD KEY IF NOT EXISTS `idx_sm_loc` (`location_id`);

-- 5. POS & Multi-Item Sales Tables
CREATE TABLE IF NOT EXISTS `business_sales` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `sale_date` DATE NOT NULL,
  `customer_type` ENUM('EXTERNAL', 'STUDENT', 'STAFF', 'ORGANIZATION') DEFAULT 'EXTERNAL',
  `customer_name` VARCHAR(150) NULL,
  `student_adm_no` VARCHAR(30) NULL, -- Direct link to student fee account
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

-- 6. Non-Cash Inter-Departmental Transfers
CREATE TABLE IF NOT EXISTS `business_transfers` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `target_department` ENUM('KITCHEN', 'BOARDING', 'MAINTENANCE', 'ADMINISTRATION', 'OTHER') NOT NULL,
  `item_id` INT NOT NULL,
  `from_location_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_cost` DECIMAL(12,2) NOT NULL,
  `total_value` DECIMAL(12,2) NOT NULL,
  `gl_event_id` INT NULL,
  `transfer_date` DATE NOT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  FOREIGN KEY (`from_location_id`) REFERENCES `inventory_locations`(`id`),
  INDEX `idx_bt_school` (`school_id`),
  INDEX `idx_bt_date` (`transfer_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. Batch Production & Costing Tables
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
  `loss_type` ENUM('SPILLAGE', 'SPOILAGE', 'CONTAMINATION', 'EVAPORATION', 'OTHER') NOT NULL,
  `reason` TEXT NULL,
  `financial_value` DECIMAL(12,2) DEFAULT 0.00,
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'APPROVED',
  `approved_by` INT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`production_batch_id`) REFERENCES `production_batches`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  INDEX `idx_pl_school` (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. Multi-Stage Expense Approval Lifecycle Table
CREATE TABLE IF NOT EXISTS `business_expenses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `expense_date` DATE NOT NULL,
  `description` VARCHAR(255) NOT NULL,
  `amount` DECIMAL(12,2) NOT NULL,
  `category` ENUM('FEED', 'DRUGS', 'FUEL', 'MAINTENANCE', 'SUPPLIES', 'LABOR', 'UTILITIES', 'OTHER') NOT NULL,
  `status` ENUM('REQUESTED', 'APPROVED', 'PURCHASED', 'PAID', 'POSTED_TO_GL', 'REJECTED') DEFAULT 'REQUESTED',
  `requested_by` INT NOT NULL,
  `approved_by` INT NULL,
  `paid_by` INT NULL,
  `gl_event_id` INT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  INDEX `idx_be_school` (`school_id`),
  INDEX `idx_be_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. Asynchronous Accounting Event Queue Table
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

## 4. Specialized Module Integration & Adapter Strategy

### 4.1 Uniform Module Integration
- **Preserved**: `uniform_prices` matrix by class group, student issuance search (`issue_uniform`), issuance receipts (`uniform_receipts`), and student fee debiting.
- **Enhanced**: Uniform items connect directly to `item_stock` and `inventory_locations` ("Main Uniform Store"). When uniforms are issued via `issue_uniform`:
  1. `item_stock.current_stock` decreases for the specified `location_id`.
  2. `stock_movements` record is logged (`movement_type = 'ISSUANCE'`).
  3. `business_transaction_events` record is enqueued for accounting posting.
- **Dynamic CRUD**: Uniform items, sizes, categories, purchase costs, selling prices, and price history are managed dynamically via administrative UI without hardcoding.

### 4.2 Transport & Fleet Module Integration
- **Preserved**: Bus records (`buses`), driver/co-driver assignments, fuel vouchers (`fuel_vouchers`), fuel efficiency reports, maintenance registers (`service_register`), route allocations (`transport_routes`), and automatic termly student fee billing.
- **Enhanced**:
  - Route modification / student transport assignment changes automatically calculate adjustments, reverse prior billings where applicable, post new fee debits, and maintain audit logs via `StudentService`.
  - Vehicle maintenance and fuel invoice entries auto-submit into `business_expenses` (`REQUESTED` $\rightarrow$ `APPROVED` $\rightarrow$ `PURCHASED` $\rightarrow$ `PAID` $\rightarrow$ `POSTED_TO_GL`).

### 4.3 Procurement Module Integration
- **Preserved**: Purchase Order creation, Goods Received Notes (GRN), Supplier aging, and Approval workflows in `blueprints/procurement`.
- **Integration**: All business unit stock purchases (e.g. Uniforms, Feed, Drugs, Fuel, Tuckshop items) consume Procurement POs and GRNs:
  $$\text{Supplier PO} \longrightarrow \text{Goods Received Note (GRN)} \longrightarrow \text{item\_stock Increase} \longrightarrow \text{Supplier Invoice} \longrightarrow \text{AP Posting}$$

---

## 5. Asynchronous Accounting Event Queue & GL Posting Matrix

Business transactions publish events to `business_transaction_events`. The Finance Posting Service processes queued events into balanced double-entry transactions in `finance_transactions` and `ledger_entries`:

| Event Type | Debit Account | Credit Account | Cash / Non-Cash |
| :--- | :--- | :--- | :--- |
| **POS Cash Sale** | Cash / Bank GL | Business Unit `revenue_gl_account` | Cash |
| **Student AR Sale** | Student Accounts Receivable (AR) | Business Unit `revenue_gl_account` | Credit |
| **COGS (Sale)** | Business Unit `cogs_gl_account` | Business Unit `inventory_gl_account` | Non-Cash |
| **Approved Expense** | Business Unit `expense_gl_account` | Accounts Payable / Cash GL | Cash / Credit |
| **Kitchen Transfer** | School Kitchen Expense GL (Food/Boarding) | Business Unit `inventory_gl_account` / Revenue | Non-Cash Journal |
| **Spoilage / Loss** | Spoilage Expense GL | Business Unit `inventory_gl_account` | Non-Cash Journal |

---

## 6. Enterprise Reporting Specifications

Reports provide filtering (date range, business unit, location), drill-down, CSV export, and PDF generation:

1. **Inventory Reports**:
   - Stock Valuation Report (`item_stock` quantity $\times$ `unit_cost`)
   - Stock Movement History Ledger
   - Low Stock / Reorder Alert Report
   - Item Purchase vs Usage Analysis
2. **Uniform Reports**:
   - Uniform Stock Balance by Item & Size
   - Issued Quantity vs Available Balance Report
   - Revenue & Margin Report per Item
   - Outstanding Student Uniform Fee Charges
3. **Farm / Agriculture Reports**:
   - Production Yield & Spoilage/Loss % Report
   - Cost per Unit vs Selling Price Analysis
   - Batch Production Efficiency Report ($[\text{Saleable Output} / \text{Total Production}] \times 100$)
4. **Transport & Fleet Reports**:
   - Route Revenue vs Operating Expense P&L
   - Vehicle Utilization & Maintenance Cost per KM
   - Fuel Efficiency & Voucher Summary
5. **Business Unit P&L Reports**:
   - Enterprise Income Statement per `business_unit_id`

---

## 7. Migration-Safe Phased Rollout Plan

```
+-----------------------------------------------------------------------------------+
|                     PHASE-BY-PHASE IMPLEMENTATION ROADMAP                         |
+-----------------------------------------------------------------------------------+
| PHASE 1: Database Migration & Backward-Compatibility Layer                        |
| - Execute migration 060_business_operations_core.sql                              |
| - Create `business_units`, `inventory_locations`, `production_batches`,          |
|   `production_losses`, and `business_transaction_events`                          |
| - Create `income_activities` backward-compatibility SQL view                       |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 2: Single-Source Multi-Location Inventory & Transfer Engine                 |
| - Evolve `item_stock` & `stock_movements` with location & business unit links     |
| - Implement `business_transfers` for non-cash kitchen transfers                   |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 3: Batch Production Costing, POS, & Accounting Event Queue                  |
| - Implement `production_batches` lifecycle & `production_losses` tracking         |
| - Implement POS multi-item sales (`business_sales_items`) with AR student debits  |
| - Connect transaction events to Asynchronous Accounting Event Queue               |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 4: Specialized Module Adapters (Uniform, Fleet & Procurement)               |
| - Uniform Issuance: Deduct `item_stock` at specified location upon issuance       |
| - Transport/Fleet: Route fuel & maintenance expenses through approval pipeline    |
| - Procurement: Connect GRN stock receipts directly to `item_stock`                |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 5: Operational Dashboards & Regression Verification                         |
| - Build KPI cards for Dairy, Fleet, Uniforms, Tuckshop, and Rentals                |
| - Execute regression tests to verify zero disruption across existing endpoints    |
+-----------------------------------------------------------------------------------+
```

---

## 8. Pre-Implementation Regression Checklist

Prior to starting code implementation, the following regression checklist must be verified:

- [ ] **Uniform Module**:
  - [ ] Item creation & price editing works (`/manage_uniform_items`)
  - [ ] Term date constraints validate correctly (`manage_term_dates`)
  - [ ] Uniform issuance search and submission works (`/issue_uniform`)
  - [ ] Student fee account debits correctly
  - [ ] Receipt generation and PDF print preview operate without error
- [ ] **Transport Module**:
  - [ ] Vehicle management operates (`/fleet/buses`)
  - [ ] Route creation and route fee setting functions (`/fleet/routes`)
  - [ ] Student transport route allocation and billing works (`/fleet/transport_assignments`)
  - [ ] Service register logs maintenance correctly (`/fleet/record_service`)
  - [ ] Fuel voucher generation and print works (`/fleet/issue_fuel`)
- [ ] **Student Fees & Ledger**:
  - [ ] Account balance calculations remain accurate (`/admin/fees/student/<admno>/statement`)
  - [ ] Fee waivers, discounts, and optional service charges operate cleanly
- [ ] **Procurement Module**:
  - [ ] Requisition creation and purchase order approval operate (`manage_requisitions`, `create_purchase_order`)
  - [ ] Goods Received Note (GRN) updates stock levels cleanly

---

## 9. Conclusion

This blueprint provides an ERP-grade architectural specification for the Business Operations Platform. Adhering strictly to the **Existing Code First Policy**, it unifies inventory under `item_stock`, connects sales, procurement, and GL journaling, and establishes enterprise production costing while ensuring 100% operational continuity for all existing school modules.
