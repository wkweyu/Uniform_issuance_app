# SkoolTrack Pro Business Operations - Commercial POS Technical Design Document

**Document Identifier**: `BUSINESS_OPERATIONS_POS_TECHNICAL_DESIGN.md`
**Phase Target**: Phase 2 Commercial Operational Workflows
**Author**: SkoolTrack Pro ERP Core Team
**Date**: 2026-10-08
**Status**: Pending Client Review & Approval

---

## Executive Summary & System Boundaries

This Technical Design Document defines the complete backend, frontend, security, and financial integration specifications for the **Commercial Point of Sale (POS) Module** in SkoolTrack Pro.

As established in the architectural review, **Business Operations is the Operational Orchestration Layer** and does not replace specialized master domain controllers.

### Domain System of Record Matrix

| Domain | System of Record / Authoritative Master | Integration Protocol |
| :--- | :--- | :--- |
| **Student Profiles & Search** | `StudentService` (`blueprints/students/services.py`) | Read-only API lookup |
| **Student Receivables / AR** | `FeesService` (`blueprints/fees/services.py`) | Fee Debit Note posting for student credit sales |
| **Uniform Issuance & Sizing** | `InventoryService` (`blueprints/inventory/services.py`) | Specialized academic service adapter |
| **Transport Routes & Billing** | `TransportService` (`blueprints/transport/services.py`) | Termly fee billing & route allocations |
| **Fleet & Fuel Vouchers** | `TransportService` (`blueprints/transport/services.py`) | Standalone maintenance & fuel registers |
| **Procurement & GRN Receiving** | `ProcurementService` (`blueprints/procurement/services.py`) | PO creation, 3-way matching & GRN stock receiving |
| **General Ledger & Accounting** | `FinanceService` (`blueprints/finance/services.py`) | Double-entry journal processing from event queue |
| **Inventory Stock Movements** | `InventoryTransactionService` (`blueprints/inventory/services.py`) | **Mandatory Gateway** for ALL stock balance mutations |
| **Commercial Sales Operations** | `BusinessOperationsService` (`blueprints/farm/services.py`) | Commercial POS, multi-item carts, cashier shifts |

---

## 1. Cashier Session & Shift Architecture

Cashiers will **NOT** select a Business Unit or Store Location for every sale. Instead, cashiers open an auditable **Cashier Shift Session**, inheriting the terminal, location, and business unit for all subsequent transactions.

### 1.1 `cashier_sessions` Schema Extension

Reusing and extending existing cashier session infrastructure (`migrations/034_cashier_sessions.sql` & `046_cashier_session_completion.sql`):

```sql
ALTER TABLE `cashier_sessions`
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `location_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `terminal_code` VARCHAR(50) DEFAULT 'POS-01',
  ADD KEY IF NOT EXISTS `idx_cs_bu` (`business_unit_id`),
  ADD KEY IF NOT EXISTS `idx_cs_loc` (`location_id`),
  ADD CONSTRAINT `fk_cs_bu` FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_cs_loc` FOREIGN KEY (`location_id`) REFERENCES `inventory_locations`(`id`) ON DELETE SET NULL;
```

### 1.2 Sales Table Shift Linking

```sql
ALTER TABLE `business_sales`
  ADD COLUMN IF NOT EXISTS `cashier_session_id` INT NULL,
  ADD KEY IF NOT EXISTS `idx_bs_cs` (`cashier_session_id`),
  ADD CONSTRAINT `fk_bs_cs` FOREIGN KEY (`cashier_session_id`) REFERENCES `cashier_sessions`(`id`) ON DELETE SET NULL;
```

---

## 2. Pricing Service Architecture (`PricingService`)

Price resolution is handled by a standalone `PricingService` rather than being hardcoded inside POS routes.

### 2.1 Price Tier Resolution Algorithm

$$\text{Unit Price} = \text{ResolvePrice}(\text{item\_master\_id}, \text{customer\_type}, \text{school\_id})$$

```python
class PricingService:
    def __init__(self, connection, school_id: int):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id

    def resolve_item_price(self, item_master_id: int, customer_type: str = "EXTERNAL", quantity: float = 1.0) -> Dict:
        """
        Resolves selling price based on customer tier (RETAIL, STUDENT, STAFF, WHOLESALE, CONTRACT).
        Returns unit_price, cost_price, discount_pct, and currency.
        """
        self.cursor.execute(
            """SELECT im.id, im.name, im.default_selling_price, im.default_purchase_cost, im.unit_of_measure, ic.code as classification
               FROM item_master im
               JOIN item_classifications ic ON im.classification_id = ic.id
               WHERE im.id = %s AND im.school_id = %s""",
            (item_master_id, self.school_id)
        )
        item = self.cursor.fetchone()
        if not item:
            raise ValueError("Item not found.")

        base_price = Decimal(str(item['default_selling_price'] or 0.00))
        cost_price = Decimal(str(item['default_purchase_cost'] or 0.00))

        # Price tier adjustments
        if customer_type == 'STUDENT':
            # Example: 5% student discount or specific student tier
            selling_price = base_price
        elif customer_type == 'STAFF':
            # Example: Staff discount tier
            selling_price = base_price * Decimal('0.95')
        elif customer_type == 'ORGANIZATION':
            selling_price = base_price * Decimal('0.90')
        else:
            selling_price = base_price

        return {
            'item_master_id': item['id'],
            'item_name': item['name'],
            'classification': item['classification'],
            'unit_of_measure': item['unit_of_measure'],
            'unit_price': float(selling_price),
            'unit_cost': float(cost_price)
        }
```

---

## 3. Asynchronous Accounting Event Queue Lifecycle

To insulate business transactions from General Ledger posting logic and support audit logs, retries, and reversals, `business_transaction_events` mandates an auditable status workflow:

$$\text{CREATED} \longrightarrow \text{QUEUED} \longrightarrow \text{PROCESSING} \longrightarrow \text{POSTED} \quad \text{or} \quad \text{FAILED} \longrightarrow \text{REVERSED}$$

```sql
-- Accounting Event Status Transition Specification
-- CREATED: Published by BusinessOperationsService
-- QUEUED: Scheduled for Finance Processing Worker
-- PROCESSING: Active double-entry posting in progress
-- POSTED: Successfully posted to finance_transactions & ledger_entries
-- FAILED: Posting failed (error logged in error_message, retry_count incremented)
-- REVERSED: Reversal journal created for cancelled sale/refund
```

---

## 4. Sensitive Operation Audit Requirements

All sensitive operational overrides mandate explicit auditing (`created_by`, `approved_by`, `approved_at`, `reason`, `timestamp`):

1. **Price Override**: When cashier modifies unit selling price manually.
2. **Discount Override**: Line item or total cart discount exceeding standard limit.
3. **Manual Stock Adjustment**: Variance adjustments outside purchase POs.
4. **Expense Request Authorization**: Approving business unit expense requisitions.
5. **Production Batch Loss Write-off**: Approving milk/egg spoilage or contamination write-offs.

---

## 5. Security & Permission Policy

Role-Based Access Control (RBAC) permissions enforced across POS endpoints:

| Permission Code | Permission Name | Scope / User Roles |
| :--- | :--- | :--- |
| `business.pos.open_shift` | Open Cashier Shift | Cashier, Accountant, Admin |
| `business.pos.sell` | Execute Commercial POS Sale | Cashier, Storekeeper, Admin |
| `business.pos.discount_override` | Override Discount % | Supervisor, Accountant, Admin |
| `business.pos.price_override` | Override Selling Price | Supervisor, Admin |
| `business.pos.cancel_sale` | Cancel / Void Active Sale | Supervisor, Admin |
| `business.pos.refund` | Process Sales Refund | Accountant, Admin |
| `business.inventory.adjust` | Approve Stock Adjustment | Store Manager, Admin |

---

## 6. Frontend Component Architecture

The Commercial POS interface (`templates/farm/pos.html` / `templates/business/pos.html`) is structured into 7 modular UI components:

```
+---------------------------------------------------------------------------------------------------------+
| [1] BusinessPOSDashboard Header & Cashier Shift Banner                                                  |
+---------------------------------------------------------------------------------------------------------+
| [2] CashierShiftSelector (Shift Status: OPEN | Terminal: POS-01 | Store: Tuckshop Main Store)              |
+---------------------------------------------------------------------------------------------------------+
| [3] CustomerSearchCard                                                                                  |
|     Customer Type: [ Student v ] Search: [ ADM-1024 / John Doe                                    ]     |
|     --> Live Student Card: Photo, ADM-1024, John Doe (Form 3 W), Fees Balance: KES 4,500, Status: OK    |
+---------------------------------------------------------------------------------------------------------+
| [4] ItemSearchGrid                                                                                      |
|     Search: [ Scan Barcode or Type SKU/Name...                                                ]         |
|     --> Typeahead Dropdown: SKU | Item Name | Available Stock | Unit Price | (+ Add Line)                |
+---------------------------------------------------------------------------------------------------------+
| [5] SalesCart (Multi-Line Grid)                                                                         |
|     # | SKU        | Item / Service Description | Available | Qty | Unit Price | Disc % | Line Total   |
|     1 | MILK-500ML | Fresh Milk 500ml           | 120 L     | 2   | KES  60.00 |   0%   | KES 120.00   |
|     2 | BREAD-700G | White Bread 700g         | 45 Pcs    | 3   | KES  80.00 |   0%   | KES 240.00   |
+---------------------------------------------------------------------------------------------------------+
| [6] PaymentPanel                                                                                        |
|     Subtotal: KES 360.00 | VAT: KES 0.00 | Discount: KES 0.00 | GRAND TOTAL: KES 360.00                   |
|     Payment Method: [ Student Fee Account Debit v ] [ Tendered: KES 360.00 ] [ Complete Sale & Print ]   |
+---------------------------------------------------------------------------------------------------------+
| [7] ReceiptPreview (Print Preview Modal with Thermal Receipt Layout & Barcode)                          |
+---------------------------------------------------------------------------------------------------------+
```

---

## 7. Backend API Specification

| Endpoint Route | Method | Required Permission | Description |
| :--- | :--- | :--- | :--- |
| `/farm/api/shift/open` | `POST` | `business.pos.open_shift` | Opens cashier shift for specified store & business unit. |
| `/farm/api/shift/current` | `GET` | `business.pos.sell` | Retrieves active shift context for logged-in user. |
| `/farm/api/items/search` | `GET` | `business.pos.sell` | Typeahead search on `item_master` and `item_stock`. |
| `/farm/api/customers/student` | `GET` | `business.pos.sell` | Live student lookup (returns photo, balance, credit status). |
| `/farm/api/customers/staff` | `GET` | `business.pos.sell` | Live staff directory lookup. |
| `/farm/api/pos/checkout` | `POST` | `business.pos.sell` | Validates stock, executes multi-line sale, deducts inventory via `InventoryTransactionService`, posts student fee debit via `FeesService` if applicable, and enqueues GL event. |

---

## 8. Phase 2 Verification & Success Criteria

Phase 2 implementation will be validated against the following criteria:

- [ ] **Sales Execution**:
  - [ ] Multi-line sales cart supports adding, editing quantity, removing lines.
  - [ ] Typeahead barcode/item search queries `item_master` and populates prices automatically.
  - [ ] Quantities validate against `item_stock` at active store location.
  - [ ] Subtotal, VAT, discount, grand total, and balance calculate automatically.
  - [ ] Thermal receipt preview renders clean printable layout.
- [ ] **Customer Integration**:
  - [ ] Student lookup displays photo, admission number, name, class, and fee balance.
  - [ ] Staff lookup queries staff directory.
  - [ ] External walk-in cash sales operate cleanly.
- [ ] **Inventory Core Integration**:
  - [ ] Stock deducts automatically through `InventoryTransactionService.issue_stock`.
  - [ ] Non-inventory service items (trips, tuition, hire) bypass stock deduction.
  - [ ] All inventory changes log audit entries to `stock_movements`.
- [ ] **Finance & Accounting**:
  - [ ] Transaction enqueues idempotent record in `business_transaction_events`.
  - [ ] Student account credit sales create debit entries via `FeesService`.
  - [ ] Payment methods (Cash, Mpesa, Bank, Student Account) capture accurately.
- [ ] **Shift & Shift Reports**:
  - [ ] Cashier shift open/close tracks opening balance, total sales, and closing balance.
  - [ ] Daily cashier shift sales summary report generates correctly.

---

## 9. Conclusion

This Technical Design Specification establishes the architecture for Phase 2 Commercial POS execution. By separating specialized domain master modules, enforcing cashier shift contexts, centralizing stock mutations through `InventoryTransactionService`, implementing multi-line sales grids with live typeahead search, and guaranteeing idempotent GL event queuing, SkoolTrack Pro achieves enterprise commercial reliability with zero disruption to existing school operations.
