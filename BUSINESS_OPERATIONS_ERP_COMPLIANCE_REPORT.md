# SkoolTrack Pro Business Operations Platform - ERP Compliance Matrix & UI Architectural Redesign Report

## Executive Summary

This report delivers a thorough, feature-by-feature **Compliance Review**, **Gap Explanation**, and **ERP Architectural Redesign Proposal** for the **Business Operations Platform** in SkoolTrack Pro.

While migration `060_business_operations_core.sql` established the database schema foundation and `InventoryTransactionService` / `BusinessOperationsService` implemented underlying transaction primitives, the user-facing application currently behaves like a prototype rather than a full-scale ERP Business Operations module.

This directive establishes the exact architectural blueprint required to elevate Business Operations into an **ERP-grade commercial engine** while strictly adhering to the **Existing Code First Policy** and preserving specialized domain master modules (**Uniform Issuance**, **Transport Management**, **Fleet Management**, **Student Fees Ledger**, **Procurement**, and **Finance GL**).

---

## 1. Feature-by-Feature Compliance Matrix Against `IGA_GAP_ANALYSIS.md`

| Feature Domain | Feature Requirement | Status | Gap Explanation & Current Implementation Assessment |
| :--- | :--- | :--- | :--- |
| **Enterprise Scope** | Multi-Unit Cost Centers (`business_units`) | **Partially Implemented** | Database schema, CRUD service, and basic form exist. **Gap**: Cashier workflow still forces per-transaction unit selection instead of inferring unit from store/cashier shift context. |
| **Locations** | Physical Stores & Warehouses (`inventory_locations`) | **Partially Implemented** | Schema & service layer support locations. **Gap**: POS checkout does not enforce location-based stock filtering or store selection. |
| **Central Inventory** | `item_master` & `item_stock` Consolidation | **Partially Implemented** | `item_master` and `InventoryTransactionService` exist. **Gap**: POS frontend accepts free-text strings instead of dynamically searching `item_master` by SKU/barcode/typeahead. |
| **POS Engine** | Commercial Sales Grid & Invoicing | **Partially Implemented** | Backend supports `business_sales` & `business_sales_items`. **Gap**: UI uses a single-item demonstration form instead of a multi-line ERP sales grid with line totals, discounts, taxes, and grand totals. |
| **Customer Lookup** | Dynamic Student/Staff/Customer Search | **Partially Implemented** | Backend handles `STUDENT`, `STAFF`, `EXTERNAL`. **Gap**: UI requires manually typing Admission Number/Name instead of live search with photos, class, balance, and credit status. |
| **Services & Retail** | Service Billing & Farm Produce Sales | **Partially Implemented** | Schema supports all item classifications. **Gap**: POS does not distinguish non-inventory service items (tuition, trips, hire) from inventory items during stock validation. |
| **Department Issues** | Department Inventory Consumption | **Partially Implemented** | `inventory_issues` and `inventory_custody` schemas exist. **Gap**: No user-facing UI screen for issuing materials to departments or managing returnable asset custody. |
| **Production Batches** | Agricultural Batch & Yield Accounting | **Partially Implemented** | `production_batches` and `production_losses` services exist. **Gap**: Farm yield form uses single-item inputs instead of multi-item production cost accumulation and loss approvals. |
| **Expense Controls** | Multi-Stage Expense Approval | **Partially Implemented** | `business_expenses` service and basic approval queue exist. **Gap**: Approval flow lacks purchase order GRN linking and multi-level budget check displays. |
| **Accounting Queue** | Asynchronous GL Event Queuing | **Partially Implemented** | `business_transaction_events` table enqueues events with UUIDs and composite unique constraints. **Gap**: No background worker or UI queue monitor to process/post queued events to GL. |
| **Procurement** | 3-Way Matching (PO = GRN = Invoice) | **Partially Implemented** | Procurement module exists. **Gap**: POS & inventory adjustments do not enforce GRN validation or supervisor approval for manual stock additions. |
| **Uniform Issuance** | Preserved Academic Service Adapter | **Implemented** | Uniform Issuance remains a specialized student service module in `blueprints/inventory` with student sizing and class requirements intact. |
| **Transport & Fleet** | Preserved Domain Master | **Implemented** | Fleet management (`buses`, `service_register`, `fuel_vouchers`) and Transport routes operate independently in `blueprints/transport`. |
| **ERP Reporting** | Stock Card & Weighted Average Costing | **Partially Implemented** | Basic aggregate summary queries exist. **Gap**: Lacks Stock Card audit reports (Opening + In - Out = Closing), Valuation, Stock Aging, and CSV/PDF export. |
| **ERP Navigation** | Menu Structure & Operational Dashboard | **Partially Implemented** | Added `Business Ops` nav link in `templates/base.html`. **Gap**: Dashboard is minimal and lacks daily sales breakdown, payment method charts, inventory alerts, and KPI cards. |

---

## 2. Explanation: Backend Foundation vs. Complete Feature Delivery

### Why UI Screens Were Minimal in Initial Iterations
The initial phase focused strictly on building a **rock-solid backend foundation** (DB schema, multi-tenant scoping, `InventoryTransactionService` abstraction, idempotent accounting queue, and legacy API adapters). This was done to guarantee that existing database models and working blueprints would not break or experience HTTP 500 runtime exceptions.

However, as correctly identified by the ERP Completion Directive:
* Exposing backend services without rich, interactive UI screens leaves the application feeling like a prototype.
* **To deliver a true ERP Business Operations module**, we must replace demonstration forms with **production-grade ERP interfaces**: multi-line sales grids, typeahead item search, live student/staff customer cards, cashier shift contexts, and interactive drill-down dashboards.

---

## 3. Redesign Proposals & Architectural Refinements

### 3.1 Commercial POS Interface Redesign

#### Removal of Repeated Business Unit Selection
Cashiers will **NOT** select a Business Unit for every single transaction. Instead:
- **Cashier Shift Context**: Upon logging into POS or opening a cashier shift, the cashier selects or inherits their **Store / Terminal / Business Unit**.
- **Automated Context**: Every sale automatically inherits the `business_unit_id` and `location_id` from the active cashier session.

#### Multi-Line ERP Sales Grid
The POS interface will feature a dynamic Javascript/Alpine/Vue sales grid:

```
+---------------------------------------------------------------------------------------------------------------+
| COMMERCIAL POS CHECKOUT                                                      Shift: Tuckshop Main Store      |
+---------------------------------------------------------------------------------------------------------------+
| Customer: [ Student: ADM-1024 - John Doe (Form 3 West) ] [ Outstanding Balance: KES 4,500 ] [ Credit: OK ]   |
+---------------------------------------------------------------------------------------------------------------+
| BARCODE / ITEM SEARCH: [ Scan Barcode or Type Item Name...                              ] (+ Add Line)       |
+---------------------------------------------------------------------------------------------------------------+
| #  | Item SKU    | Item Name / Service        | Location   | Available | Qty | Unit Price | Disc % | Line Total|
|----+-------------+----------------------------+------------+-----------+-----+------------+--------+-----------|
| 1  | MILK-500ML  | Fresh Dairy Milk 500ml     | Main Store | 120 L     | 2   | KES  60.00 |   0%   | KES 120.00|
| 2  | BREAD-700G  | White Bread 700g           | Main Store |  45 Pcs   | 3   | KES  80.00 |   0%   | KES 240.00|
| 3  | EGGS-CRATE  | Fresh Farm Eggs (Tray)     | Main Store |  18 Trays | 1   | KES 450.00 |   0%   | KES 450.00|
| 4  | TRIP-SWIM   | Weekend Swimming Fee       | Service N/A| N/A       | 1   | KES 200.00 |   0%   | KES 200.00|
+---------------------------------------------------------------------------------------------------------------+
|                                                             Subtotal:                        KES 1,010.00     |
|                                                             VAT (0%):                        KES     0.00     |
|                                                             Discount:                        KES     0.00     |
|                                                             GRAND TOTAL:                     KES 1,010.00     |
+---------------------------------------------------------------------------------------------------------------+
| PAYMENT METHOD: [ Student Fee Account Debit v ] [ Amount Tendered: KES 1,010.00 ] [ Complete Sale & Print ]   |
+---------------------------------------------------------------------------------------------------------------+
```

#### Dynamic Inventory Search & Auto-Pricing
- **Search Mechanism**: Searching queries `item_master` and `item_stock` by item name, SKU, or barcode scan.
- **Auto-Populated Details**: Selecting an item automatically populates unit description, SKU, available location stock, unit of measure, and default selling price.
- **Pricing Tiers**: Supports default retail price, student price, staff price, and wholesale price. Manual price overrides are locked behind supervisor permissions.
- **Stock Validation**: Stocked items validate `quantity_on_hand` at the active location before allowing checkout. Service items (trips, hire, swimming, tuition) bypass physical stock deductions.

#### Dynamic Customer Search
- **External Customer**: Walk-in cash sales (optional name/phone).
- **Student Search**: Typing Admission Number or Name queries `StudentService` via AJAX, rendering a Student Card with **Photo, Admission No, Full Name, Class, Stream, Outstanding Fees, Credit Status, and Dorm**.
- **Staff Search**: Typing Payroll No or Name queries Staff Directory, showing **Photo, Department, Position, Payroll No, and Balance**.
- **Organization**: Corporate clients, NGOs, Parents Association credit accounts.

---

### 3.2 Enterprise Operational Dashboard Redesign

The Business Operations Dashboard (`/farm/dashboard` or `/business/dashboard`) will render a comprehensive ERP overview:

```
+---------------------------------------------------------------------------------------------------------------+
| BUSINESS OPERATIONS DASHBOARD                                                                                 |
+---------------------------------------------------------------------------------------------------------------+
| [ Today's Sales: KES 142,500 ] [ Cash: KES 45k ] [ Mpesa: KES 62k ] [ AR Student Debits: KES 35.5k ]          |
+---------------------------------------------------------------------------------------------------------------+
| KEY OPERATIONAL KPIS & ALERTS                                                                                |
| - Low Stock Items: 8 Items below reorder level (e.g. Blue Shirts Size 32, Dairy Feed)                          |
| - Farm Yield Efficiency: Dairy Farm 96.2% (350L produced, 5L spoilage)                                        |
| - Pending Expense Approvals: 3 Requisitions awaiting authorization (Total KES 28,000)                        |
| - Unposted Accounting Events: 12 Transactions queued for GL Posting                                           |
+---------------------------------------------------------------------------------------------------------------+
| REVENUE BY BUSINESS UNIT (Chart)                    | TOP SELLING ITEMS THIS MONTH                            |
| [ Dairy Farm: 45% ] [ Tuckshop: 30% ] [ Rentals: 25%] | 1. Fresh Milk 500ml (1,200 L)                         |
|                                                     | 2. Exercise Books 200pg (850 Pcs)                       |
|                                                     | 3. Swimming Trip Pass (320 Issued)                      |
+---------------------------------------------------------------------------------------------------------------+
```

---

## 4. Restructured Navigation Hierarchy

To maintain domain expertise while providing unified operational access, SkoolTrack Pro's menu structure is organized into:

### Master Domain Menus (Preserved Domain Controllers)
- **Students**: Student Register, Admissions, Class Allocations
- **Fees**: Fee Structures, Invoicing, Waivers, Student Accounts, Statements
- **Uniform Issuance**: Student Uniform Search, Sizing, Class Requirements, Issuance & Returns
- **Transport**: Bus Routes, Route Allocations, Transport Billing
- **Fleet**: Vehicle Register, Maintenance Logs, Fuel Vouchers & Efficiency Reports
- **Procurement**: Suppliers, Requisitions, Purchase Orders (POs), Goods Received Notes (GRN)
- **Finance / GL**: Chart of Accounts, Journal Entries, Trial Balance, Income Statement

### Business Operations ERP Menu (`/business/*` or `/farm/*`)
```
Business Operations
 ├── Dashboard (KPI Cards, Charts, Sales Summary, Alerts)
 ├── Commercial POS (Multi-Line Checkout, Customer Card, Student AR)
 ├── Business Units (Enterprise Cost Centers Setup)
 ├── Inventory Stores (Multi-Location Warehouses & Stores)
 ├── Department Issues (Internal Consumption & Returnable Custody)
 ├── Production Batches (Agricultural & Manufacturing Yield & Spoilage)
 ├── Sales Ledger & Invoices (Historical POS Receipts & Customer Billing)
 ├── Expense Approvals (Requisition Authorization Pipeline)
 ├── Accounting Queue (GL Event Monitor)
 └── Enterprise Reports (Stock Card, Valuation, Yield Efficiency, P&L)
```

---

## 5. Existing Code-First Reuse Strategy & Database Impact

### Services & Models to Reuse
- **`StudentService` (`blueprints/students/services.py`)**: Reuse `get_student_by_admno` and student search for POS customer cards.
- **`FeesService` (`blueprints/fees/services.py`)**: Reuse fee debit note creation for POS student account credit sales.
- **`ProcurementService` (`blueprints/procurement/services.py`)**: Reuse PO and GRN receiving methods for 3-way matching stock additions.
- **`FinanceService` (`blueprints/finance/services.py`)**: Process `business_transaction_events` into `finance_transactions` and `ledger_entries`.
- **`InventoryTransactionService` (`blueprints/inventory/services.py`)**: Execute all stock movements (`receive`, `issue`, `consume`, `produce`, `transfer`, `return`).

### Database Impact Assessment
All tables defined in `migrations/060_business_operations_core.sql` exist and are fully compatible with existing schemas. Non-destructive columns on `item_stock` and `stock_movements` allow seamless stock tracking across multi-location stores.

---

## 6. Phased Implementation Roadmap

To transition from backend foundation to full user-facing ERP delivery safely:

```
+-----------------------------------------------------------------------------------+
|               PHASED USER-FACING ERP IMPLEMENTATION ROADMAP                      |
+-----------------------------------------------------------------------------------+
| PHASE 1: Architectural Assessment & Compliance Specification (COMPLETE)           |
| - Feature-by-feature compliance review & ERP UI specification (`IGA_GAP_ANALYSIS`)|
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 2: Commercial POS Redesign & Multi-Line Sales Grid                          |
| - Build interactive multi-line POS sales grid with automatic calculations         |
| - Add dynamic `item_master` typeahead search (SKU, barcode, description)          |
| - Add dynamic Customer Card lookup (Student photo/balance, Staff, External)       |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 3: Department Issues, Returnable Custody & Asset Returns                    |
| - Build UI for department material consumption                                    |
| - Build custody register for returnable assets (laptops, equipment, furniture)    |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 4: Farm Batch Production & Approved Wastage Workflows                       |
| - Build agricultural batch yield input screen with input cost accumulation        |
| - Build supervisor loss/spoilage approval interface                               |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 5: Accounting Event Queue Worker & GL Posting Monitor                        |
| - Build background event queue processor (`business_transaction_events`)          |
| - Connect sales, expenses, and transfers to double-entry GL journal generation    |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
| PHASE 6: ERP Operational Dashboards, Stock Card Reports & Analytics               |
| - Build interactive dashboard with KPI cards, sales breakdown, and low stock alerts|
| - Build Stock Card audit report (Opening + In - Out = Closing) & Excel/PDF exports|
+-----------------------------------------------------------------------------------+
```

---

## 7. Conclusion

This report provides a clear compliance assessment and an ERP architectural blueprint for the Business Operations Platform. By implementing the multi-line POS grid, dynamic item/customer typeahead search, department issue workflows, production batch costing, and operational dashboards, SkoolTrack Pro will deliver a complete, production-ready ERP platform.
