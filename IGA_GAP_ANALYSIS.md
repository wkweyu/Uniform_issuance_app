# IGA (Income Generating Activities) Architectural Discovery & Gap Analysis Report

## Executive Summary

This report delivers a comprehensive **Architectural Discovery** and **Strategic Gap Analysis** for evolving the existing **Income Generating Activities (IGA) / Farm Management Module** into an enterprise-grade **Business Operations Module**.

Crucially, this evolution is architected to **preserve existing Uniform Issuance, Transport Management, and Fleet Management modules** in full. Rather than rewriting or duplicating specialized domain features (such as vehicle fuel voucher tracking or student uniform sizing matrices), the system establishes a **Centralized Business Operations Core** (Shared Inventory, POS/Invoicing, Sales & Receivables, Inter-Departmental Transfers, Expense Approvals, and Double-Entry GL Integration) while preserving specialized modules as domain extensions that consume the Business Operations Core.

---

## 1. Architectural Discovery: Existing Codebase State

### 1.1 Income Generating Activities (IGA / Farm)
- **Module Blueprint**: `blueprints/farm` (registered as `farm_bp` at `/farm`)
- **Routes & Views**: `dashboard`, `record_production`, `record_sale`, `farm_expenses` (`templates/farm/*.html`)
- **Service Layer**: `FarmManagementService` in `blueprints/farm/services.py`
- **Database Tables**:
  - `income_activities` (Cost centers with `gl_income_account`, `gl_expense_account`)
  - `income_production_log` (Yield, spoilage, internal consumption quantities)
  - `income_sales` (Sales entries with receipt numbers)
  - `income_expenses` (Expense requests with `PENDING`, `APPROVED`, `REJECTED`, `PAID` approval workflow)
- **Permissions**: `login_required`, `admin_required`, `user_module_access` checks.

### 1.2 Uniform Issuance Module
- **Module Blueprint**: `blueprints/inventory` (registered as `inventory_bp`)
- **Routes & Views**: `/manage_uniform_items`, `/issue_uniform`, `/submit_issuance`, `/reports/*` (`templates/manage_uniform_items.html`, `templates/student.html`)
- **Service Layer**: `InventoryService` in `blueprints/inventory/services.py`, integrated with `ProcurementService` for purchase orders.
- **Database Tables**:
  - `uniform_prices` (Item names, class groups, prices, linked `item_id`)
  - `uniform_receipts` (Student issuance receipts linked by `AdmNo`)
  - `uniform_term_dates` (Term constraints for uniform issuance)
  - `item_stock` (Central stock levels)
- **Specialized Capabilities**: Class group pricing matrices, student admission linkage, student receipt issuance, term date validation.

### 1.3 Transport & Fleet Management Module
- **Module Blueprint**: `blueprints/transport` (registered as `transport_bp`)
- **Routes & Views**: `/fleet/fleet_dashboard`, `/fleet/buses`, `/fleet/record_service`, `/fleet/issue_fuel`, `/fleet/routes`, `/fleet/transport_assignments`, `/fleet/transport_reports`
- **Service Layer**: `TransportService` in `blueprints/transport/services.py`
- **Database Tables**:
  - `buses` (Vehicle details, driver assignments, registration numbers)
  - `transport_routes` (Route names, fee amounts, assigned `bus_id`)
  - `transport_allocations` (Student transport allocations by `AdmNo` & `route_id`)
  - `service_register` (Vehicle maintenance logs, costs, service dates)
  - `fuel_vouchers` & `fuel_invoices` (Fuel vouchers, tank capacities, meter readings, fuel efficiency calculations)
- **Specialized Capabilities**: Vehicle maintenance scheduling, odometer tracking, fuel efficiency analysis, bus-to-driver binding, route-based student transport billing.

---

## 2. Boundary Recommendations: Centralized Core vs. Specialized Modules

To maintain architectural purity, zero redundancy, and full backward compatibility, domain boundaries are defined as follows:

```
+---------------------------------------------------------------------------------------------------+
|                               BUSINESS OPERATIONS CENTRAL CORE                                    |
|                                                                                                   |
|  * Shared Multi-Enterprise Catalog & Inventory Management (`income_inventory`, `income_stock_movements`)|
|  * Universal Enterprise Cost Centers (`income_activities`: Farm, Tuckshop, Bakery, Rentals, etc.) |
|  * Centralized POS, Multi-Item Invoicing & Customer Billing (`income_sales`, `income_sales_items`)|
|  * Inter-Departmental Transfer & Internal Consumption Engine (`income_transfers`)                |
|  * Expense Request & Approval Workflow (`income_expenses`)                                       |
|  * Double-Entry Finance GL Auto-Journaling (`FinanceService.post_journal_entry()`)                |
+---------------------------------------------------------------------------------------------------+
                                   ^                               ^
                                   | (Consumes Stock & AR)         | (Consumes Expenses & GL)
                                   |                               |
+----------------------------------+---+   +-----------------------+--------------------------------+
|    UNIFORM ISSUANCE MODULE           |   |      TRANSPORT & FLEET MANAGEMENT MODULE               |
|    (Specialized Domain Extension)    |   |      (Specialized Domain Extension)                    |
|                                      |   |                                                        |
|  * Student Sizing & Pricing Matrix   |   |  * Fleet / Bus Master (`buses`)                        |
|  * Student Class Allocation Links    |   |  * Odometer & Fuel Voucher Register (`fuel_vouchers`)  |
|  * Uniform Issuance Receipts (`AdmNo`)|  * Vehicle Maintenance & Service Register              |
|  * Term Date Issuance Rules          |   |  * Student Bus Route Allocations (`transport_routes`)  |
+--------------------------------------+   +--------------------------------------------------------+
```

### 2.1 What is Centralized in Business Operations Core
1. **Multi-Enterprise Cost Center Engine**: Ability to define enterprises (`FARM`, `TUCKSHOP`, `BAKERY`, `RENTAL`, `PRINTING`, `SERVICES`, `OTHER`).
2. **Unified Inventory & Stock Movements**: Stock tracking (`income_inventory`), reorder levels, cost/selling prices, and immutable stock audit movement logs (`income_stock_movements`).
3. **Universal Point of Sale (POS) & Invoicing**: Multi-item sales, receipts, external customer billing, and direct student ledger fee debiting.
4. **Inter-Departmental Non-Cash Transfers**: Transfers of enterprise output (e.g. farm milk to school kitchen, tuckshop items to staff, uniform inventory stock transfers) with automated non-cash GL journal postings.
5. **Expense Approval Lifecycle**: Standardized requisition, manager approval, and Accounts Payable / Finance transaction linking.
6. **Automated Double-Entry Finance GL Postings**: Automated posting of revenue, expenses, COGS, and inter-departmental transfer journals to Chart of Accounts (`finance_transactions` & `ledger_entries`).

### 2.2 What Remains in Specialized Modules
1. **Uniform Issuance Module**:
   - Retains `uniform_prices` matrix by class group.
   - Retains student-facing uniform issuance forms (`issue_uniform`) and student receipts (`uniform_receipts`).
   - *Adapter*: Uniform stock levels sync automatically with central `income_inventory` / `item_stock` without altering the issuance UI or receipt format.
2. **Transport & Fleet Management Module**:
   - Retains vehicle master (`buses`), driver assignments, fuel vouchers (`fuel_vouchers`), fuel efficiency reports, and vehicle maintenance registers (`service_register`).
   - Retains route management (`transport_routes`) and student route allocations (`transport_allocations`).
   - *Adapter*: Fuel invoices and vehicle service expenses auto-submit expense requests into the Business Operations expense pipeline while maintaining transport-specific dashboard views.

---

## 3. Comprehensive Gap Analysis

| Domain | Current State Capability | Target ERP Architecture | Gap Category | Required Action / Extension |
| :--- | :--- | :--- | :--- | :--- |
| **Enterprise Scope** | Farm-oriented (Dairy, Poultry) | Generic Multi-Enterprise (Farm, Tuckshop, Rentals, Bakery, Tailoring, Bookshop) | **Extend** | Expand `income_activities` with `activity_type`, unit metrics, and default GL configs. |
| **Stock & Inventory** | Quantity totals logged per production entry | Unit-level inventory tracking, stock movements, reorder alerts | **New** | Introduce `income_inventory` & `income_stock_movements` tables. |
| **Sales & POS** | Single line customer sales entries | Multi-item POS sales, itemized receipts, customer invoicing | **Extend** | Add itemized sales support (`income_sales_items`) and customer credit balances. |
| **Student Billing** | External sales only | Charge sales or rental fees directly to student billing ledger | **New / Integration** | Integrate with Student Fee Ledger / Accounts Receivable via `FinanceService`. |
| **Finance GL Posting** | GL account code placeholders stored | Real-time double-entry journal postings on sales, expenses & transfers | **New / Integration** | Connect `record_sale` & `approve_expense` to `FinanceService.post_journal_entry()`. |
| **Internal Consumption** | Quantity counter in production log | Non-Cash Journal entries transferring value to School Kitchen / Maintenance GL | **New / Integration** | Implement non-cash inter-departmental GL transfer logic. |
| **Procurement** | Standalone expense request form | Requisition linkage to central Procurement module (`procurement_requisitions`) | **Integration** | Option to route approved expenses to Procurement PO workflow. |
| **Reporting & P&L** | High-level summary (Revenue, Expense, Profit) | Enterprise P&L statement, Yield trend analysis, Margin analysis | **Extend** | Detailed activity-level P&L breakdown and CSV export. |
| **Uniform & Fleet Linkage** | Independent standalone queries | Unified stock & expense adapter layer | **Integration** | Sync uniform stock and fleet expenses via BizOps Core APIs. |
| **Backward Compatibility** | Existing `/farm/*` endpoints | `/farm/*` preserved seamlessly, aliased to `/operations/*` or `/farm/*` | **Reuse / Preserve** | Ensure all legacy routes continue functioning without breaking changes. |

---

## 4. Technical Specifications & Database Schema Extensions

### 4.1 Schema Extensions (Migration-Safe SQL)

1. **`income_activities`** (Extension):
   ```sql
   ALTER TABLE `income_activities`
     ADD COLUMN IF NOT EXISTS `activity_type` ENUM('FARM', 'TUCKSHOP', 'RENTAL', 'PRODUCTION', 'SERVICES', 'OTHER') DEFAULT 'FARM',
     ADD COLUMN IF NOT EXISTS `inventory_gl_account` VARCHAR(50) NULL,
     ADD COLUMN IF NOT EXISTS `cogs_gl_account` VARCHAR(50) NULL;
   ```

2. **`income_inventory`** (New Table):
   ```sql
   CREATE TABLE IF NOT EXISTS `income_inventory` (
     `id` INT AUTO_INCREMENT PRIMARY KEY,
     `school_id` INT NOT NULL,
     `activity_id` INT NOT NULL,
     `item_name` VARCHAR(150) NOT NULL,
     `unit_of_measure` VARCHAR(30) DEFAULT 'units',
     `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
     `selling_price` DECIMAL(12,2) DEFAULT 0.00,
     `quantity_on_hand` DECIMAL(12,2) DEFAULT 0.00,
     `reorder_level` DECIMAL(12,2) DEFAULT 0.00,
     `is_active` BOOLEAN DEFAULT TRUE,
     `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
     FOREIGN KEY (`activity_id`) REFERENCES `income_activities`(`id`) ON DELETE CASCADE,
     INDEX (`school_id`),
     INDEX (`activity_id`)
   ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
   ```

3. **`income_stock_movements`** (New Table):
   ```sql
   CREATE TABLE IF NOT EXISTS `income_stock_movements` (
     `id` INT AUTO_INCREMENT PRIMARY KEY,
     `school_id` INT NOT NULL,
     `inventory_id` INT NOT NULL,
     `movement_type` ENUM('PRODUCTION', 'SALE', 'TRANSFER', 'SPOILAGE', 'ADJUSTMENT') NOT NULL,
     `quantity` DECIMAL(12,2) NOT NULL,
     `unit_cost` DECIMAL(12,2) DEFAULT 0.00,
     `reference_no` VARCHAR(100) NULL,
     `notes` TEXT NULL,
     `recorded_by` INT NOT NULL,
     `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
     FOREIGN KEY (`inventory_id`) REFERENCES `income_inventory`(`id`) ON DELETE CASCADE,
     INDEX (`school_id`),
     INDEX (`movement_type`)
   ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
   ```

4. **`income_sales_items`** (New Table):
   ```sql
   CREATE TABLE IF NOT EXISTS `income_sales_items` (
     `id` INT AUTO_INCREMENT PRIMARY KEY,
     `school_id` INT NOT NULL,
     `sale_id` INT NOT NULL,
     `inventory_id` INT NULL,
     `item_name` VARCHAR(150) NOT NULL,
     `quantity` DECIMAL(12,2) NOT NULL,
     `unit_price` DECIMAL(12,2) NOT NULL,
     `total_price` DECIMAL(12,2) NOT NULL,
     FOREIGN KEY (`sale_id`) REFERENCES `income_sales`(`id`) ON DELETE CASCADE,
     INDEX (`school_id`),
     INDEX (`sale_id`)
   ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
   ```

5. **`income_transfers`** (New Table for Internal Consumption):
   ```sql
   CREATE TABLE IF NOT EXISTS `income_transfers` (
     `id` INT AUTO_INCREMENT PRIMARY KEY,
     `school_id` INT NOT NULL,
     `activity_id` INT NOT NULL,
     `target_department` ENUM('KITCHEN', 'BOARDING', 'MAINTENANCE', 'ADMINISTRATION', 'OTHER') NOT NULL,
     `inventory_id` INT NULL,
     `quantity` DECIMAL(12,2) NOT NULL,
     `unit_cost` DECIMAL(12,2) NOT NULL,
     `total_value` DECIMAL(12,2) NOT NULL,
     `gl_journal_id` INT NULL,
     `transfer_date` DATE NOT NULL,
     `recorded_by` INT NOT NULL,
     `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
     FOREIGN KEY (`activity_id`) REFERENCES `income_activities`(`id`) ON DELETE CASCADE,
     INDEX (`school_id`),
     INDEX (`transfer_date`)
   ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
   ```

---

## 5. Migration-Safe Implementation Roadmap

To guarantee zero system downtime, data integrity, and complete backward compatibility, the rollout is structured into five distinct phases:

```
+-----------------------------------------------------------------------------------+
|                     PHASE-BY-PHASE IMPLEMENTATION ROADMAP                        |
+-----------------------------------------------------------------------------------+
| PHASE 1: Database Schema Expansion & Backward-Compatible Service Foundation        |
| - Apply non-breaking migrations (060_business_operations_core.sql)                |
| - Extend `FarmManagementService` / `BusinessOperationsService` with legacy aliases|
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 2: Centralized Inventory & Inter-Departmental Transfer Engine               |
| - Implement stock management, movement logging, and reorder alerts                |
| - Implement Non-Cash Kitchen / Internal Consumption Transfer Engine               |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 3: Double-Entry Finance GL & Student Billing Integration                    |
| - Implement automated journal postings via `FinanceService.post_journal_entry()`  |
| - Enable direct student fee account debiting for POS credit sales                 |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 4: Specialized Module Integration Adapters (Uniform & Fleet)                 |
| - Connect Uniform Issuance stock adjustments to central `income_inventory`        |
| - Connect Fleet fuel/service expense requests into Business Operations pipeline   |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 5: UI/UX Expansion, Enterprise Analytics, & Verification                   |
| - Enhance UI templates with enterprise selection, POS billing, & P&L reports     |
| - Execute unit, integration, and regression test suites                           |
+-----------------------------------------------------------------------------------+
```

### Phase 1: Database Schema Expansion & Service Foundation
- **Goal**: Apply schema extensions and prepare core service layer while preserving existing methods.
- **Actions**:
  - Run migration script `060_business_operations_core.sql` adding `income_inventory`, `income_stock_movements`, `income_sales_items`, and `income_transfers`.
  - Maintain all legacy signatures in `FarmManagementService` (`get_activities`, `record_production`, `record_sale`, `request_expense`, `get_financial_summary`).

### Phase 2: Centralized Inventory & Inter-Departmental Transfers
- **Goal**: Enable stock movements and inter-departmental transfers.
- **Actions**:
  - Add methods `add_inventory_item()`, `get_inventory()`, `record_stock_movement()`, and `record_transfer()`.
  - Automatically update `income_inventory.quantity_on_hand` upon production, sales, or transfers.

### Phase 3: Double-Entry Finance GL & Student Billing Integration
- **Goal**: Connect sales, expenses, and non-cash transfers to core finance ledgers.
- **Actions**:
  - Cash Sales: Debit Cash/Bank GL, Credit Activity Income GL.
  - Student Billed Sales: Debit Student AR Ledger, Credit Activity Income GL.
  - Non-Cash Transfers: Debit Target Department GL (e.g. Kitchen Food Expense), Credit Enterprise Asset/Income GL.
  - Approved Expenses: Debit Activity Expense GL, Credit Accounts Payable / Cash GL.

### Phase 4: Specialized Module Integration Adapters
- **Goal**: Seamlessly connect Uniform and Transport modules to BizOps Core without altering their domain workflows.
- **Actions**:
  - Uniform Issuance: Trigger stock deduction in `income_inventory` whenever uniforms are issued.
  - Fleet Management: Route fuel invoice and vehicle maintenance entries to `income_expenses` for centralized authorization.

### Phase 5: UI/UX Expansion, Reporting, & Verification
- **Goal**: Expose new capabilities in UI, offer multi-enterprise filtering, and verify stability.
- **Actions**:
  - Update `templates/farm/dashboard.html`, `sales_form.html`, and `expense_form.html`.
  - Provide enterprise profit & loss reports and inventory valuation export.
  - Run regression test suites (`tests/test_procurement_inventory_isolation.py`) to confirm zero regressions.

---

## 6. Verification & Test Plan

1. **Schema & Multi-Tenant Verification**:
   - Verify every new table enforces `school_id` and foreign key constraints.
   - Confirm unmigrated or missing optional values do not break legacy queries.
2. **Double-Entry Balance Verification**:
   - Verify that all automated journal entries maintain equal debits and credits (`sum(debit) == sum(credit)`).
3. **Domain Isolation Verification**:
   - Confirm Uniform Issuance forms (`/issue_uniform`) and Fleet management dashboards (`/fleet/fleet_dashboard`) operate without breaking changes.
4. **Regression Verification**:
   - Ensure all existing unit tests in `tests/` pass cleanly.

---

## 7. Conclusion

This report provides a clear architectural vision and migration-safe roadmap for transforming the IGA module into an enterprise Business Operations Core. By centralizing inventory, POS invoicing, inter-departmental transfers, and GL journaling while preserving Uniform and Transport domain modules, the ERP achieves full enterprise scalability with zero operational risk.
