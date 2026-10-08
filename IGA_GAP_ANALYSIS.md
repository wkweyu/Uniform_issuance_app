# IGA (Income Generating Activities) Gap Analysis Report

## Executive Summary

This report evaluates the current **Income Generating Activities (IGA) / Farm Management Module** in the School Management ERP (`blueprints/farm`) and provides a strategic blueprint for transforming it into an enterprise-grade **Business Operations Module**.

The goal is to expand the system from a farm-centric logging utility into a unified, multi-enterprise operational engine capable of driving diverse school enterprises (e.g., Dairy, Poultry, Tuckshop/Canteen, Bakery, Tailoring, Bus/Facility Hire, Printing & Bookshop) while maintaining **100% backward compatibility** with existing `/farm` routes, databases, and business logic.

---

## 1. Current State Assessment

### 1.1 Existing Architecture
Currently, the IGA module is implemented under `blueprints/farm` with the following key files:
- **Routes**: `blueprints/farm/routes.py` (Dashboard, Production form, Sales form, Expense form)
- **Service Layer**: `blueprints/farm/services.py` (`FarmManagementService`)
- **Templates**: `templates/farm/*.html`
- **Database Schema**:
  - `income_activities` (Cost centers/activity definition)
  - `income_production_log` (Daily yield, spoilage, and internal consumption quantities)
  - `income_sales` (Sales entries with receipt numbers)
  - `income_expenses` (Expense requests with `PENDING`, `APPROVED`, `REJECTED`, `PAID` workflow)

### 1.2 Strengths & Reusable Foundations
- **Multi-Tenant Isolation**: Fully enforced via `school_id` filtering and `require_current_school_id()`.
- **Cost Center Architecture**: Each activity links to `gl_income_account` and `gl_expense_account`.
- **Approval Lifecycle**: Expense requests feature an approval workflow (`status`, `approved_by`).
- **Base Reporting**: Real-time aggregate queries for Total Sales, Expenses, Net Profit, and Spoilage rates.

---

## 2. Target ERP Architecture

The expanded **Business Operations Engine** will serve as a multi-unit enterprise management system:

```
+-----------------------------------------------------------------------------------+
|                           BUSINESS OPERATIONS MODULE                              |
+-----------------------------------------------------------------------------------+
|  Enterprise Cost Centers: Farm, Tuckshop, Bakery, Transport Hire, Printing, etc.  |
+-------------------+--------------------+--------------------+---------------------+
|   Production &    |    Inventory &     |   Point of Sale    | Inter-Departmental  |
| Yield Management  | Stock Management   |   & Invoicing      |    Transfers        |
+-------------------+--------------------+--------------------+---------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                          CORE ERP INTEGRATION LAYER                               |
+-------------------+--------------------+--------------------+---------------------+
|   Finance GL      |    Procurement     |  Student Billing   |   Audit & RBAC      |
| Auto Journaling   | Requisitions & POs |  Student Accounts  | Role Permissions    |
+-------------------+--------------------+--------------------+---------------------+
```

---

## 3. Comprehensive Gap Analysis

| Functional Domain | Current State Capability | Target ERP Architecture | Gap Category | Required Action / Extension |
| :--- | :--- | :--- | :--- | :--- |
| **Enterprise Scope** | Farm-oriented (Dairy, Poultry) | Generic Multi-Enterprise (Farm, Tuckshop, Rentals, Bakery, Tailoring, Bookshop) | **Extend** | Expand `income_activities` with `activity_type`, unit metrics, and default GL configs. |
| **Stock & Inventory** | Quantity totals logged per production entry | Unit-level inventory tracking, stock movements, reorder alerts | **New** | Introduce `income_inventory` & `income_stock_movements` tables. |
| **Sales & POS** | Single line customer sales entries | Multi-item POS sales, itemized receipts, customer invoicing | **Extend** | Add itemized sales support (`income_sales_items`) and customer credit balances. |
| **Student Billing** | External sales only | Charge sales or rental fees directly to student billing ledger | **New / Integration** | Integrate with Student Fee Ledger / Accounts Receivable via `FinanceService`. |
| **Finance GL Posting** | GL account code placeholders stored | Real-time double-entry journal postings on sales, expenses & transfers | **New / Integration** | Connect `record_sale` & `approve_expense` to `FinanceService.post_journal_entry()`. |
| **Internal Consumption** | Quantity counter in production log | Non-Cash Journal entries transferring value to School Kitchen / Maintenance GL | **New / Integration** | Implement non-cash inter-departmental GL transfer logic. |
| **Procurement** | Standalone expense request form | Requisition linkage to central Procurement module (`procurement_requisitions`) | **Integration** | Option to route approved expenses to Procurement PO workflow. |
| **Reporting & P&L** | High-level summary (Revenue, Expense, Profit) | Enterprise P&L statement, Yield trend analysis, Margin analysis | **Extend** | Detailed activity-level P&L breakdown and CSV export. |
| **Backward Compatibility** | Existing `/farm/*` endpoints | `/farm/*` preserved seamlessly, aliased to `/operations/*` or `/farm/*` | **Reuse / Preserve** | Ensure all legacy routes continue functioning without breaking changes. |

---

## 4. Technical Specifications & Architectural Extensions

### 4.1 Database Schema Extensions

1. **`income_activities`**: Add columns:
   - `activity_type`: ENUM(`FARM`, `TUCKSHOP`, `RENTAL`, `PRODUCTION`, `SERVICES`, `OTHER`) DEFAULT `FARM`.
   - `inventory_gl_account`: VARCHAR(50) for asset GL mapping.
   - `cogs_gl_account`: VARCHAR(50) for cost of goods sold.

2. **`income_inventory`** (New Table):
   - `id`, `school_id`, `activity_id`, `item_name`, `unit_of_measure`, `unit_cost`, `selling_price`, `quantity_on_hand`, `reorder_level`, `created_at`.

3. **`income_stock_movements`** (New Table):
   - `id`, `school_id`, `inventory_id`, `movement_type` (`PRODUCTION`, `SALE`, `TRANSFER`, `SPOILAGE`, `ADJUSTMENT`), `quantity`, `reference_no`, `notes`, `recorded_by`, `created_at`.

4. **`income_sales_items`** (New Table):
   - `id`, `school_id`, `sale_id`, `inventory_id`, `item_name`, `quantity`, `unit_price`, `total_price`.

5. **`income_transfers`** (New Table for Internal Consumption):
   - `id`, `school_id`, `activity_id`, `target_department` (`KITCHEN`, `BOARDING`, `MAINTENANCE`), `inventory_id`, `quantity`, `unit_cost`, `total_value`, `gl_journal_id`, `recorded_by`, `transfer_date`.

### 4.2 Integration Specifications

1. **Finance GL Integration**:
   - Cash Sales: Debit Cash/Bank GL, Credit `gl_income_account`.
   - Credit / Student Sales: Debit Student AR / Customer Ledger, Credit `gl_income_account`.
   - Approved Expenses: Debit `gl_expense_account`, Credit Accounts Payable / Cash.
   - Internal Consumption: Debit Kitchen Expense GL (e.g., Food & Boarding), Credit Enterprise Income/Asset GL.

2. **Student Billing Integration**:
   - Provide an option on sales recording to select a student by Admission Number, generating an automated ledger fee charge/debit note.

3. **Backward Compatibility Guarantee**:
   - Existing methods `get_activities()`, `record_production()`, `record_sale()`, `request_expense()`, `get_financial_summary()` will retain identical parameter signatures and return types.
   - Route handlers in `blueprints/farm/routes.py` will remain fully intact while exposing enhanced UI options.

---

## 5. Verification & Testing Strategy

1. **Unit & Isolation Testing**:
   - Test multi-tenant isolation for all new tables (`income_inventory`, `income_transfers`, `income_sales_items`).
   - Validate strict schema handling and non-zero quantity bounds.
2. **Integration Testing**:
   - Verify double-entry GL postings generated by IGA transactions.
   - Test student fee account posting for student-billed sales.
   - Test inter-departmental kitchen transfer journal creation.
3. **Regression Testing**:
   - Execute existing test suite (`tests/test_procurement_inventory_isolation.py`) to confirm zero regressions in existing farm tests.

---

## 6. Conclusion

This gap analysis establishes a clear roadmap for upgrading the IGA module into a fully integrated Business Operations engine. All enhancements build cleanly upon the existing database tables and service structures without interrupting running school operations or breaking backward compatibility.
