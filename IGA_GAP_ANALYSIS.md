# Business Operations Architecture Refinement & Implementation Report

## Executive Summary

This report establishes the refined architectural framework for evolving the school's **Income Generating Activities (IGA) / Farm Module** into a unified, enterprise-grade **Business Operations Platform**.

Based on architectural review, this design adopts a **Business Operations Core + Specialized Domain Extensions** topology. It addresses naming conventions, introduces a formal **Business Unit Architecture**, resolves inventory overlap by evolving `item_stock` into a **Single Central Inventory Engine**, and provides a migration-safe implementation strategy that preserves existing Uniform Issuance, Transport Management, and Fleet Management modules with **zero downtime and full backward compatibility**.

---

## 1. Domain Naming & Architecture Re-Evaluation

### 1.1 Critique of Legacy `income_*` Naming
The legacy prefix `income_*` (`income_activities`, `income_sales`, `income_expenses`) originated when the module was conceived strictly as a farm/IGA logging utility. In a comprehensive school Business Operations platform, the `income_*` naming convention is architecturally flawed:
1. **Misleading Domain Scope**: Operational activities encompass cost centers, inventory stock, procurement expenses, and inter-departmental transfers—none of which are purely "income".
2. **SaaS Multi-Enterprise Ambiguity**: School enterprises include commercial tuckshops, tailoring workshops, transport services, rental halls, and bakeries. Representing a tuckshop expense or workshop inventory movement under `income_*` causes confusion.

### 1.2 Recommended `business_*` Domain Naming

We recommend standardizing all core entities under the `business_*` domain convention while evolving the existing `item_stock` table into the central inventory engine:

| Legacy Table Name | Proposed Standardized Table Name | Domain & Purpose |
| :--- | :--- | :--- |
| `income_activities` | `business_units` | Core enterprise units / Cost centers |
| `income_inventory` *(Proposed)* | `item_stock` *(Evolved)* | Single Central Inventory Core across all modules |
| `income_stock_movements` *(Proposed)* | `stock_movements` *(Evolved)* | Universal stock movement ledger & audit log |
| `income_sales` | `business_sales` | Enterprise POS, invoicing & sales ledger |
| `income_sales_items` *(New)* | `business_sales_items` | Multi-item sales detail rows |
| `income_expenses` | `business_expenses` | Enterprise expense requests & approval workflow |
| `income_transfers` *(New)* | `business_transfers` | Non-cash inter-departmental GL transfer ledger |
| `income_production_log` | `business_production_log` | Agriculture & manufacturing yield/spoilage logs |

### 1.3 Backward Compatibility & SaaS Scalability Strategy
To ensure existing code, queries, and reports running against `income_activities`, `income_sales`, or `income_expenses` do not break:
1. **Database Views for Backward Compatibility**:
   Create SQL views mapping legacy table names to the new schema:
   ```sql
   CREATE OR REPLACE VIEW `income_activities` AS
   SELECT id, school_id, name, description, revenue_gl_account AS gl_income_account, expense_gl_account AS gl_expense_account, is_active, created_at
   FROM `business_units`;
   ```
2. **Service Layer Alias**:
   `FarmManagementService` will inherit from or wrap `BusinessOperationsService`, retaining exact method signatures (`get_activities()`, `record_sale()`, `request_expense()`).
3. **Multi-Tenant Isolation**:
   Every new and evolved table mandates `school_id` with composite indexes (`idx_bu_school_id`, `idx_stock_school_id`).

---

## 2. Business Unit Architecture

### 2.1 `business_units` Entity Specification

The `business_units` entity replaces the narrow concept of "income activities" with a general cost-center and business enterprise structure.

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

### 2.2 Cross-Module Association Mapping

Existing and future modules associate cleanly with `business_units` without losing their domain-specific functionality:

```
+----------------------------------------------------------------------------------------------------+
|                                    BUSINESS UNITS (`business_units`)                               |
+-------------------+-------------------+-------------------+-------------------+--------------------+
| Dairy Farm        | Uniform Shop      | School Transport  | Canteen / Tuck    | Bakery & Printing  |
| (AGRICULTURE)     | (RETAIL)          | (TRANSPORT)       | (FOOD_BEVERAGE)   | (PRODUCTION)       |
+---------+---------+---------+---------+---------+---------+---------+---------+---------+----------+
          |                   |                   |                   |                   |
          v                   v                   v                   v                   v
+-------------------+ +-------------------+ +-------------------+ +-------------------+ +-------------------+
| Farm / Production | | Uniform Issuance  | | Transport & Fleet | | Canteen POS &     | | Commercial        |
| Log & Spoilage    | | & Class Group     | | Vehicles & Fuel   | | Student Account   | | Manufacturing   |
| Tracking          | | Pricing Matrix    | | Voucher Tracking  | | Fee Debits        | | & Custom Billing  |
+-------------------+ +-------------------+ +-------------------+ +-------------------+ +-------------------+
```

| Business Unit Name | Unit Type | Associated Domain Module | Specialized Logic Preserved | Central Core Features Consumed |
| :--- | :--- | :--- | :--- | :--- |
| **Dairy / Poultry Farm** | `AGRICULTURE` | Farm / IGA (`blueprints/farm`) | Daily yield logging, milk/egg spoilage rates | `item_stock`, `business_sales`, `business_expenses`, GL Journaling |
| **Uniform Shop** | `RETAIL` | Uniform Issuance (`blueprints/inventory`) | Class-group pricing matrix (`uniform_prices`), student sizing, issuance receipts | `item_stock` (uniform inventory), POS billing, AR debiting |
| **School Transport** | `TRANSPORT` | Transport/Fleet (`blueprints/transport`) | Bus records (`buses`), fuel vouchers (`fuel_vouchers`), maintenance register, student route allocation | Fleet expense approval pipeline, route revenue tracking |
| **School Canteen** | `FOOD_BEVERAGE` | Business Operations POS | Student meal cards, tuckshop cash sales | `item_stock`, POS sales invoicing, student account debiting |
| **Rental Hall / Bus Hire**| `RENTAL` | Business Operations Rentals | Calendar booking, facility rental agreements | `business_sales` (credit customer billing), revenue GL posting |

---

## 3. Inventory Architecture Review & Core Consolidation

### 3.1 Analysis of Inventory Overlap
A critical evaluation reveals that creating a separate `income_inventory` table would create **fragmented inventory data**:
- `item_stock` already exists in the database and is consumed by `blueprints/inventory` (Uniform Issuance) and `blueprints/procurement` (Purchase Orders & Stock Ledger).
- Creating `income_inventory` alongside `item_stock` would force developers to sync two stock tables, risk stock level discrepancies, and duplicate stock movement auditing.

### 3.2 Evaluation Answers
1. **Should `item_stock` evolve into a central Inventory Core?**
   **YES.** `item_stock` must serve as the Single Source of Truth for ALL physical inventory across all school modules (Uniforms, Procurement, Tuckshop, Farm Produce, Maintenance Spare Parts).
2. **Should `income_inventory` be removed/avoided?**
   **YES.** We explicitly drop the proposal for `income_inventory` and standardize entirely on `item_stock`.
3. **Should all modules consume one inventory engine?**
   **YES.** All modules (Uniforms, Procurement, Farm, Tuckshop, Fleet) will read from and write to `item_stock` and log movements in `stock_movements`.

### 3.3 Target Central Inventory Architecture

`item_stock` and `stock_movements` will be enhanced with multi-tenant and business unit linkage:

```sql
-- 1. Evolving Central Inventory Catalog (`item_stock`)
ALTER TABLE `item_stock`
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `selling_price` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `category` VARCHAR(50) DEFAULT 'General',
  ADD COLUMN IF NOT EXISTS `unit_of_measure` VARCHAR(30) DEFAULT 'units',
  ADD COLUMN IF NOT EXISTS `sku` VARCHAR(50) NULL,
  ADD KEY IF NOT EXISTS `idx_stock_bu` (`business_unit_id`),
  ADD CONSTRAINT `fk_stock_bu` FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE SET NULL;

-- 2. Evolving Central Stock Movement Audit Log (`stock_movements`)
ALTER TABLE `stock_movements`
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `movement_type` ENUM('PURCHASE', 'PRODUCTION', 'SALE', 'TRANSFER', 'SPOILAGE', 'ADJUSTMENT', 'ISSUANCE') NOT NULL DEFAULT 'ADJUSTMENT',
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `reference_no` VARCHAR(100) NULL,
  ADD KEY IF NOT EXISTS `idx_sm_school` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_sm_bu` (`business_unit_id`);
```

---

## 4. Sales, Expenses, & Inter-Departmental Transfer Architecture

### 4.1 POS & Multi-Item Sales (`business_sales` & `business_sales_items`)
Supports both cash/credit customer sales and direct student fee ledger debits:

```sql
CREATE TABLE IF NOT EXISTS `business_sales` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `sale_date` DATE NOT NULL,
  `customer_type` ENUM('EXTERNAL', 'STUDENT', 'STAFF') DEFAULT 'EXTERNAL',
  `customer_name` VARCHAR(150) NULL,
  `student_adm_no` VARCHAR(30) NULL, -- Optional link for direct fee ledger debit
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
  `item_id` INT NULL, -- Link to item_stock
  `item_name` VARCHAR(150) NOT NULL,
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_price` DECIMAL(12,2) NOT NULL,
  `total_price` DECIMAL(12,2) NOT NULL,
  FOREIGN KEY (`sale_id`) REFERENCES `business_sales`(`id`) ON DELETE CASCADE,
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`) ON DELETE SET NULL,
  INDEX `idx_bsi_school` (`school_id`),
  INDEX `idx_bsi_sale` (`sale_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.2 Non-Cash Inter-Departmental Transfers (`business_transfers`)
Solves the requirement for non-cash transfers (e.g., Farm milk transferred to School Kitchen, Tuckshop stock transferred to Staff Common Room) with automated GL debit/credit entries:

```sql
CREATE TABLE IF NOT EXISTS `business_transfers` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `business_unit_id` INT NOT NULL,
  `target_department` ENUM('KITCHEN', 'BOARDING', 'MAINTENANCE', 'ADMINISTRATION', 'OTHER') NOT NULL,
  `item_id` INT NOT NULL, -- Link to item_stock
  `quantity` DECIMAL(12,2) NOT NULL,
  `unit_cost` DECIMAL(12,2) NOT NULL,
  `total_value` DECIMAL(12,2) NOT NULL,
  `gl_journal_id` INT NULL, -- Created via FinanceService.post_journal_entry()
  `transfer_date` DATE NOT NULL,
  `recorded_by` INT NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`),
  FOREIGN KEY (`item_id`) REFERENCES `item_stock`(`item_id`),
  INDEX `idx_bt_school` (`school_id`),
  INDEX `idx_bt_date` (`transfer_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 5. Automated Double-Entry Finance GL Integration Matrix

Every operational event in the Business Operations Core generates balanced double-entry accounting transactions via `FinanceService.post_journal_entry()`:

| Transaction Event | Debit GL Account | Credit GL Account | Non-Cash / Cash |
| :--- | :--- | :--- | :--- |
| **Cash POS Sale** | Cash / Bank Account | Business Unit `revenue_gl_account` | Cash |
| **Student Billed Sale** | Student Accounts Receivable (AR) | Business Unit `revenue_gl_account` | Credit |
| **Cost of Goods Sold (Sale)** | Business Unit `cogs_gl_account` | Business Unit `inventory_gl_account` | Non-Cash |
| **Approved Expense** | Business Unit `expense_gl_account` | Accounts Payable / Cash GL | Cash / Credit |
| **Kitchen Transfer** | School Kitchen Expense GL (Food/Boarding) | Business Unit `inventory_gl_account` / Revenue | Non-Cash Journal |
| **Stock Spoilage / Write-off**| Spoilage Expense GL | Business Unit `inventory_gl_account` | Non-Cash Journal |

---

## 6. Migration-Safe Phased Implementation Roadmap

To ensure zero downtime, data integrity, and complete backward compatibility, implementation follows five strict phases:

```
+-----------------------------------------------------------------------------------+
|                     MIGRATION-SAFE IMPLEMENTATION ROADMAP                         |
+-----------------------------------------------------------------------------------+
| PHASE 1: Core Schema Evolution & Service Layer Foundation                         |
| - Execute migration 060_business_operations_core.sql                              |
| - Create `business_units`, evolve `item_stock` and `stock_movements`               |
| - Add backward-compatibility database views (`income_activities`)                 |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 2: Single Source of Truth Inventory & Transfer Engine                       |
| - Implement `item_stock` management API in `BusinessOperationsService`             |
| - Implement non-cash inter-departmental transfers (`business_transfers`)          |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 3: Universal POS, Student Billing, & Double-Entry GL Journaling             |
| - Implement multi-item sales (`business_sales_items`) with stock deduction        |
| - Connect sales & expenses to `FinanceService.post_journal_entry()`               |
| - Enable direct student fee ledger debits for student account sales               |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 4: Specialized Module Adapters (Uniform & Fleet Integration)                |
| - Connect Uniform Issuance stock deductions to central `item_stock`               |
| - Route Fleet fuel & maintenance expenses into central `business_expenses`        |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 5: UI Enhancement, Multi-Enterprise Dashboard, & Verification              |
| - Update UI templates (`templates/farm/*` or `templates/operations/*`)             |
| - Enterprise P&L reporting & CSV export                                           |
| - Run test suites to verify multi-tenant isolation and zero regressions          |
+-----------------------------------------------------------------------------------+
```

---

## 7. Verification & Testing Strategy

1. **Schema & Multi-Tenant Verification**:
   - Verify every new table enforces `school_id` and foreign key constraints.
   - Confirm legacy view `income_activities` returns exact query results for existing farm methods.
2. **Double-Entry Balance Verification**:
   - Verify that all automated journal entries maintain equal debits and credits (`sum(debit) == sum(credit)`).
3. **Inventory Isolation & Consistency Verification**:
   - Verify uniform issuance stock deductions correctly decrement `item_stock.current_stock` and insert `stock_movements` record.
4. **Regression Verification**:
   - Execute existing test suite (`tests/test_procurement_inventory_isolation.py`) to confirm zero regressions.

---

## 8. Conclusion

This refined architecture solves naming limitations, establishes a formal `business_units` entity structure, and unifies inventory under `item_stock`. By implementing a single inventory engine and automated double-entry GL journaling while preserving Uniform and Transport domain modules, the system achieves enterprise scalability with zero operational risk.
