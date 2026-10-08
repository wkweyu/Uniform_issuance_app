# Business Operations Architecture Refinement & Implementation Report

## Executive Summary

This report delivers the finalized, ERP-grade architectural blueprint for evolving the school's **Income Generating Activities (IGA) / Farm Module** into a comprehensive **Business Operations Platform**.

Incorporating final enterprise architecture refinements, this design adopts a **Business Operations Core + Specialized Domain Extensions** topology. It unifies physical inventory under a **Multi-Location Inventory Engine**, establishes batch-level **Production & Cost Accounting**, introduces an asynchronous **Accounting Event Queue** for decoupled GL postings, enforces multi-stage **Approval & Audit Controls**, and provides operational KPI dashboards while preserving existing Uniform Issuance, Transport Management, and Fleet Management modules with **zero downtime and 100% backward compatibility**.

---

## 1. Domain Naming & Architecture Re-Evaluation

### 1.1 Critique of Legacy `income_*` Naming
The legacy prefix `income_*` (`income_activities`, `income_sales`, `income_expenses`) originated when the module was conceived strictly as a farm/IGA logging utility. In an enterprise-grade school Business Operations platform, `income_*` naming is architecturally limiting:
1. **Misleading Scope**: Operational business units encompass cost centers, inventory stock, procurement expenses, maintenance, and inter-departmental transfers—not merely income.
2. **Multi-Enterprise Ambiguity**: School enterprises include commercial tuckshops, tailoring workshops, transport services, rental halls, and bakeries. Representing a workshop inventory movement or tuckshop expense under `income_*` creates confusion.

### 1.2 Recommended `business_*` Domain Naming

We standardize all core entities under the `business_*` domain convention while evolving the existing `item_stock` table into the central multi-location inventory engine:

| Legacy Table Name | Proposed Standardized Table Name | Domain & Purpose |
| :--- | :--- | :--- |
| `income_activities` | `business_units` | Enterprise units / Cost centers |
| `income_inventory` *(Obsolete)* | `item_stock` *(Evolved)* | Single Central Multi-Location Inventory Core |
| *N/A (New)* | `inventory_locations` | Physical warehouses, stores, and holding points |
| `income_stock_movements` *(Obsolete)* | `stock_movements` *(Evolved)* | Universal stock movement ledger & audit log |
| `income_sales` | `business_sales` | Enterprise POS, invoicing & sales ledger |
| `income_sales_items` *(New)* | `business_sales_items` | Multi-item sales detail rows |
| `income_expenses` | `business_expenses` | Multi-stage expense requests & approval workflow |
| `income_transfers` *(New)* | `business_transfers` | Non-cash inter-departmental GL transfer ledger |
| `income_production_log` | `production_batches` | Batch production lifecycle & batch costing |
| *N/A (New)* | `production_losses` | Spoilage, spillage, and wastage event log |
| *N/A (New)* | `business_transaction_events` | Asynchronous Accounting Event Queue for GL postings |

### 1.3 Backward Compatibility & SaaS Scalability Strategy
To ensure existing queries and reports running against `income_activities`, `income_sales`, or `income_expenses` continue operating without interruption:
1. **Database Views for Backward Compatibility**:
   ```sql
   CREATE OR REPLACE VIEW `income_activities` AS
   SELECT id, school_id, name, description, revenue_gl_account AS gl_income_account, expense_gl_account AS gl_expense_account, is_active, created_at
   FROM `business_units`;
   ```
2. **Service Layer Wrapper**:
   `FarmManagementService` will wrap `BusinessOperationsService`, retaining legacy method signatures (`get_activities()`, `record_sale()`, `request_expense()`).
3. **Multi-Tenant Isolation**:
   Every entity mandates `school_id` with composite indexes (`idx_bu_school_id`, `idx_stock_school_location`).

---

## 2. Business Unit & Inventory Location Architecture

### 2.1 `business_units` Entity Specification

The `business_units` entity replaces narrow IGA cost centers with a generic enterprise structure.

```sql
CREATE TABLE IF NOT EXISTS `business_units` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `name` VARCHAR(150) NOT NULL,
  `unit_type` ENUM('AGRICULTURE', 'RETAIL', 'FOOD_BEVERAGE', 'TRANSPORT', 'RENTAL', 'SERVICES', 'PRODUCTION', 'OTHER') NOT NULL DEFAULT 'AGRICULTURE',
  `manager_id` INT NULL, -- Link to users.userNo
  `cost_center_code` VARCHAR(50) NULL,
  `revenue_gl_account` VARCHAR(50) NULL, -- Link to Chart of Accounts (Income)
  `expense_gl_account` VARCHAR(50) NULL, -- Link to Chart of Accounts (Expense)
  `inventory_gl_account` VARCHAR(50) NULL, -- Link to Chart of Accounts (Asset/Inventory)
  `cogs_gl_account` VARCHAR(50) NULL, -- Link to Chart of Accounts (Cost of Goods Sold)
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_bu_school` (`school_id`),
  INDEX `idx_bu_type` (`unit_type`),
  CONSTRAINT `fk_bu_school` FOREIGN KEY (`school_id`) REFERENCES `schools`(`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2.2 Enterprise Inventory Location Engine (`inventory_locations`)

To avoid restricting a business unit to a single inventory pool, enterprise inventory separates:
- **Item**: What is it? (Milk, Blue Shirt, Diesel, Feed)
- **Location**: Where is it? (Main Store, Boarding Store, Cold Room, Fuel Tank)
- **Ownership / Cost Center**: Who owns it? (Dairy Farm, Uniform Shop, Transport)

```sql
CREATE TABLE IF NOT EXISTS `inventory_locations` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `name` VARCHAR(100) NOT NULL, -- e.g. 'Cold Room', 'Main Uniform Store', 'Diesel Tank 1'
  `location_type` ENUM('WAREHOUSE', 'STORE', 'COLD_STORAGE', 'FUEL_TANK', 'TRANSIT', 'OTHER') DEFAULT 'STORE',
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE CASCADE,
  INDEX `idx_loc_school` (`school_id`),
  INDEX `idx_loc_bu` (`business_unit_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Evolved item_stock with Location mapping
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
```

---

## 3. Production Lifecycle, Wastage, & Cost Accounting

For agricultural and manufacturing enterprises (Dairy, Poultry, Bakery, Tailoring), production is modeled as a managed batch lifecycle with cost accumulation and wastage tracking.

```
+---------------------------------------------------------------------------------------------------+
|                                PRODUCTION BATCH (`production_batches`)                            |
|  * Batch ID: MILK-20261008-001 | Business Unit: Dairy Farm | Production Date: 2026-10-08         |
+---------------------------------------------------------------------------------------------------+
                                                  |
       +------------------------------------------+------------------------------------------+
       |                                          |                                          |
       v                                          v                                          v
+-------------------------------+      +-------------------------------+      +-------------------------------+
|    INPUT COSTS ACCUMULATION   |      |    PRODUCTION LOSSES / WASTED |      |    NET SALEABLE OUTPUT        |
|  - Animal Feed: KES 20,000    |      |  - Spillage: 3 litres         |      |  - Available: 95 litres       |
|  - Vet & Meds: KES  3,000     |      |  - Spoilage: 2 litres         |      |  - Efficiency Rate: 95.0%     |
|  - Direct Labor: KES 8,000    |      |  - Losses Total: 5 litres     |      |  - Cost/Unit: KES 347.37/L    |
|  - Total Cost: KES 33,000     |      |  (`production_losses`)        |      |  (`item_stock` +95L)          |
+-------------------------------+      +-------------------------------+      +-------------------------------+
```

### 3.1 Production Batches & Loss Tracking Schemas

```sql
-- 1. Production Batch Lifecycle Table
CREATE TABLE IF NOT EXISTS `production_batches` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `batch_no` VARCHAR(50) NOT NULL, -- e.g. 'MILK-20261008-001'
  `item_id` INT NOT NULL, -- Target item produced in item_stock
  `location_id` INT NOT NULL, -- Destination storage location
  `total_produced_qty` DECIMAL(12,2) NOT NULL,
  `saleable_qty` DECIMAL(12,2) NOT NULL,
  `total_input_cost` DECIMAL(12,2) DEFAULT 0.00, -- Sum of feed, labor, overheads
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

-- 2. Production Loss / Wastage Ledger
CREATE TABLE IF NOT EXISTS `production_losses` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `production_batch_id` INT NOT NULL,
  `item_id` INT NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `loss_type` ENUM('SPILLAGE', 'SPOILAGE', 'CONTAMINATION', 'EVAPORATION', 'OTHER') NOT NULL,
  `reason` TEXT NULL,
  `financial_value` DECIMAL(12,2) DEFAULT 0.00, -- quantity * unit_production_cost
  `approval_status` ENUM('PENDING', 'APPROVED', 'REJECTED') DEFAULT 'APPROVED',
  `approved_by` INT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`production_batch_id`) REFERENCES `production_batches`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  INDEX `idx_pl_school` (`school_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3.2 Unit Cost Accumulation Engine Formula

$$\text{Production Efficiency \%} = \left( \frac{\text{Saleable Output Qty}}{\text{Total Production Qty}} \right) \times 100$$

$$\text{Unit Production Cost} = \frac{\sum (\text{Direct Inputs} + \text{Direct Labor} + \text{Allocated Overheads})}{\text{Saleable Output Qty}}$$

Automatically updates `item_stock.unit_cost` for the batch destination location and logs an immutable `stock_movements` record (`movement_type = 'PRODUCTION'`).

---

## 4. Decoupled Accounting Integration Architecture

To insulate business transactions from General Ledger posting logic and support reversals, eTIMS compliance, and audit trails, business events do not call `FinanceService.post_journal_entry()` directly. Instead, they publish to an **Accounting Event Queue** (`business_transaction_events`):

```
+-----------------------------------+
|     BUSINESS TRANSACTION EVENT    |
| (POS Sale, Expense, Transfer)     |
+-----------------------------------+
                  |
                  v
+-----------------------------------+
|    ACCOUNTING EVENT QUEUE         |
|  (`business_transaction_events`)  |
|  Status: PENDING                  |
+-----------------------------------+
                  |
                  v
+-----------------------------------+
|    FINANCE POSTING SERVICE        |
| - Validation & Rules Check        |
| - Double-Entry Ledger Generation  |
+-----------------------------------+
                  |
                  v
+-----------------------------------+
|      GENERAL LEDGER (GL)          |
|  (`finance_transactions` &        |
|   `ledger_entries`)               |
+-----------------------------------+
```

### 4.1 Accounting Event Queue Schema

```sql
CREATE TABLE IF NOT EXISTS `business_transaction_events` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `event_type` ENUM('POS_SALE', 'STUDENT_AR_SALE', 'EXPENSE_APPROVED', 'INTER_DEPT_TRANSFER', 'PRODUCTION_COST_ALLOCATION', 'SPOILAGE_WRITE_OFF') NOT NULL,
  `source_table` VARCHAR(50) NOT NULL, -- e.g. 'business_sales', 'business_expenses'
  `source_id` INT NOT NULL, -- Primary key ID in source table
  `event_payload` JSON NOT NULL, -- Contains GL account codes, amounts, descriptions
  `posting_status` ENUM('PENDING', 'POSTED', 'FAILED', 'REVERSED') DEFAULT 'PENDING',
  `gl_transaction_id` INT NULL, -- Link to finance_transactions upon posting
  `error_message` TEXT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `posted_at` TIMESTAMP NULL,
  INDEX `idx_bte_status` (`school_id`, `posting_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 5. Expense Approval Lifecycle & Controls

To guarantee strict administrative financial controls, business expenses follow an auditable multi-stage lifecycle:

$$\text{REQUESTED} \longrightarrow \text{APPROVED} \longrightarrow \text{PURCHASED} \longrightarrow \text{PAID} \longrightarrow \text{POSTED\_TO\_GL}$$

```sql
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
  `gl_transaction_id` INT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  INDEX `idx_be_school` (`school_id`),
  INDEX `idx_be_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 6. Operational & Financial KPI Dashboards

The Business Operations platform provides targeted operational and financial KPIs tailored for each enterprise unit:

```
+----------------------------------------------------------------------------------------------------+
|                                OPERATIONAL & FINANCIAL KPI DASHBOARDS                              |
+-------------------+-------------------+-------------------+-------------------+--------------------+
|   DAIRY FARM      |   UNIFORM SHOP    |  FLEET & TRANSPORT|  SCHOOL CANTEEN   |  RENTAL ENTERPRISE |
+-------------------+-------------------+-------------------+-------------------+--------------------+
| Total Produced    | Total Sales Value | Fleet Utilization | Daily POS Sales   | Facility Bookings  |
| Spoilage Rate (%) | Inventory Value   | Fuel Cost / KM    | Top Sold Snacks   | Revenue Realized   |
| Production Cost/L | Low Stock Items   | Repair Costs      | AR Student Debits | Outstanding Bills  |
| Selling Price/L   | Gross Margin (%)  | Net Route Profit  | COGS Margin (%)   | Maintenance Cost   |
| Net Unit Profit   | Fast Moving Items | Driver Efficiency | Meal Card Balance | Net Operating Margin|
+-------------------+-------------------+-------------------+-------------------+--------------------+
```

---

## 7. Migration-Safe Implementation Roadmap

```
+-----------------------------------------------------------------------------------+
|                     MIGRATION-SAFE IMPLEMENTATION ROADMAP                         |
+-----------------------------------------------------------------------------------+
| PHASE 1: Database Schema Expansion & Backward-Compatibility Foundation             |
| - Apply migration script 060_business_operations_core.sql                         |
| - Create `business_units`, `inventory_locations`, `production_batches`,          |
|   `production_losses`, and `business_transaction_events`                          |
| - Add backward-compatible database views (`income_activities`)                    |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 2: Single-Source Multi-Location Inventory Engine                            |
| - Evolve `item_stock` and `stock_movements` with location & business unit links   |
| - Implement `business_transfers` for non-cash kitchen transfers                   |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 3: Batch Production Costing, POS & Accounting Event Queue                   |
| - Implement `production_batches` lifecycle & `production_losses` tracking         |
| - Implement multi-item POS sales (`business_sales_items`) with AR student debits  |
| - Connect business transaction events to Asynchronous Accounting Event Queue      |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 4: Specialized Module Adapters (Uniform & Fleet Integration)                |
| - Uniform Issuance: Deduct `item_stock` at specified location upon issuance       |
| - Transport/Fleet: Route fuel & vehicle maintenance expenses through approval     |
|   pipeline while preserving student route billing and fuel voucher tracking        |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 5: Operational KPI Dashboards & System Verification                         |
| - Build operational KPI cards for Dairy, Fleet, Uniforms, and Tuckshop            |
| - Execute automated test suites for tenancy isolation, GL debits/credits, and     |
|   zero regression across legacy endpoints                                         |
+-----------------------------------------------------------------------------------+
```

---

## 8. Verification & Test Plan

1. **Schema & Multi-Tenant Verification**:
   - Verify every new table enforces `school_id` and foreign key constraints.
   - Confirm legacy view `income_activities` returns exact query results for existing farm methods.
2. **Double-Entry Balance Verification**:
   - Verify that all posted events in `business_transaction_events` generate equal debits and credits (`sum(debit) == sum(credit)`).
3. **Inventory Isolation & Consistency Verification**:
   - Verify uniform issuance stock deductions correctly decrement `item_stock.current_stock` at the specified `location_id` and insert `stock_movements` record.
4. **Regression Verification**:
   - Execute existing test suite (`tests/test_procurement_inventory_isolation.py`) to confirm zero regressions.

---

## 9. Conclusion

This report delivers a complete, ERP-grade architectural blueprint for the Business Operations Platform. By introducing `inventory_locations`, `production_batches`, `production_losses`, unit cost accumulation, an asynchronous `business_transaction_events` queue, multi-stage expense controls, and operational dashboards, SkoolTrack Pro establishes an enterprise-ready foundation with zero operational risk.
