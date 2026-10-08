"""
=============================================================================
PRODUCTION-GRADE BUSINESS OPERATIONS & FARM MANAGEMENT SERVICE
Module: blueprints/farm/services.py
Database: schoolmngt

Features:
- Enterprise Business Unit Management (`business_units`)
- Multi-Location Central Inventory & Department Issues (`inventory_locations`, `inventory_issues`)
- Batch Production & Approved Loss Accounting (`production_batches`, `production_losses`)
- POS & Multi-Item Sales Invoicing (`business_sales`, `business_sales_items`)
- Multi-Stage Expense Authorizations (`business_expenses`)
- Idempotent Accounting Event Queue (`business_transaction_events`)
- Backward Compatible Wrappers for Farm/IGA (`income_activities`, `income_sales`, `income_expenses`)
=============================================================================
"""

import pymysql
import uuid
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from core.tenancy import require_current_school_id
from blueprints.inventory.services import InventoryTransactionService

logger = logging.getLogger(__name__)


class BusinessOperationsService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id or require_current_school_id()
        self.inventory_tx_service = InventoryTransactionService(connection, self.school_id)

    # --- BUSINESS UNITS ---
    def get_business_units(self, active_only: bool = True) -> List[Dict]:
        query = """
            SELECT bu.*,
                   bu.revenue_gl_account AS gl_income_account,
                   bu.expense_gl_account AS gl_expense_account,
                   ut.name as type_name,
                   ut.code as type_code
            FROM business_units bu
            JOIN business_unit_types ut ON bu.type_id = ut.id
            WHERE bu.school_id = %s
        """
        if active_only:
            query += " AND bu.is_active = TRUE"
        query += " ORDER BY bu.name"
        self.cursor.execute(query, (self.school_id,))
        return self.cursor.fetchall()

    def create_business_unit(self, name: str, type_code: str, cost_center_code: str = "", revenue_gl: str = "", expense_gl: str = "", inventory_gl: str = "", cogs_gl: str = "") -> int:
        self.cursor.execute("SELECT id FROM business_unit_types WHERE code = %s", (type_code,))
        row = self.cursor.fetchone()
        type_id = row['id'] if row else 1

        query = """
            INSERT INTO business_units (school_id, name, type_id, cost_center_code, revenue_gl_account, expense_gl_account, inventory_gl_account, cogs_gl_account)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        self.cursor.execute(query, (self.school_id, name, type_id, cost_center_code, revenue_gl, expense_gl, inventory_gl, cogs_gl))
        self.connection.commit()
        return self.cursor.lastrowid

    # --- INVENTORY LOCATIONS ---
    def get_locations(self, business_unit_id: Optional[int] = None) -> List[Dict]:
        query = """
            SELECT loc.*, bu.name as business_unit_name, lt.name as location_type_name
            FROM inventory_locations loc
            JOIN business_units bu ON loc.business_unit_id = bu.id
            JOIN location_types lt ON loc.location_type_id = lt.id
            WHERE loc.school_id = %s
        """
        params = [self.school_id]
        if business_unit_id:
            query += " AND loc.business_unit_id = %s"
            params.append(business_unit_id)
        query += " ORDER BY loc.name"
        self.cursor.execute(query, tuple(params))
        return self.cursor.fetchall()

    def create_location(self, business_unit_id: int, name: str, location_type_code: str = "STORE") -> int:
        self.cursor.execute("SELECT id FROM location_types WHERE code = %s", (location_type_code,))
        lt_row = self.cursor.fetchone()
        lt_id = lt_row['id'] if lt_row else 1

        self.cursor.execute(
            "INSERT INTO inventory_locations (school_id, business_unit_id, name, location_type_id) VALUES (%s, %s, %s, %s)",
            (self.school_id, business_unit_id, name, lt_id)
        )
        self.connection.commit()
        return self.cursor.lastrowid

    # --- ACCOUNTING EVENT QUEUE ---
    def enqueue_accounting_event(self, business_unit_id: int, event_type: str, source_table: str, source_id: int, payload: Dict) -> str:
        """Publishes an idempotent accounting event to the business_transaction_events queue."""
        event_uuid = str(uuid.uuid4())
        payload_json = json.dumps(payload, default=str)

        query = """
            INSERT INTO business_transaction_events (school_id, event_uuid, business_unit_id, event_type, source_table, source_id, event_payload, posting_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
            ON DUPLICATE KEY UPDATE posting_status = posting_status
        """
        self.cursor.execute(query, (self.school_id, event_uuid, business_unit_id, event_type, source_table, source_id, payload_json))
        return event_uuid

    # --- POS & SALES INVOICING ---
    def record_pos_sale(self, business_unit_id: int, items: List[Dict], customer_type: str, customer_name: str, user_id: int, student_adm_no: Optional[str] = None, payment_method: str = "CASH", location_id: Optional[int] = None) -> Dict:
        try:
            total_amount = Decimal('0.00')
            for item in items:
                total_amount += Decimal(str(item['quantity'])) * Decimal(str(item['unit_price']))

            receipt_no = f"POS-{datetime.now().strftime('%y%m%d%H%M%S')}"

            self.cursor.execute(
                """INSERT INTO business_sales (school_id, business_unit_id, sale_date, customer_type, customer_name, student_adm_no, total_amount, payment_status, payment_method, receipt_no, recorded_by)
                   VALUES (%s, %s, CURDATE(), %s, %s, %s, %s, 'PAID', %s, %s, %s)""",
                (self.school_id, business_unit_id, customer_type, customer_name, student_adm_no, total_amount, payment_method, receipt_no, user_id)
            )
            sale_id = self.cursor.lastrowid

            for item in items:
                qty = Decimal(str(item['quantity']))
                price = Decimal(str(item['unit_price']))
                item_total = qty * price
                item_name = item['item_name']

                self.inventory_tx_service.issue_stock(
                    item_name=item_name,
                    quantity=float(qty),
                    user_id=user_id,
                    location_id=location_id,
                    business_unit_id=business_unit_id,
                    ref_no=receipt_no,
                    notes=f"POS Sale to {customer_name}",
                    autocommit=False
                )

                item_master_id = self.inventory_tx_service._get_or_create_item_master(item_name)

                self.cursor.execute(
                    """INSERT INTO business_sales_items (school_id, sale_id, item_master_id, item_name, quantity, unit_price, total_price)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (self.school_id, sale_id, item_master_id, item_name, qty, price, item_total)
                )

            # Enqueue accounting event
            self.enqueue_accounting_event(
                business_unit_id=business_unit_id,
                event_type='POS_SALE' if customer_type != 'STUDENT' else 'STUDENT_AR_SALE',
                source_table='business_sales',
                source_id=sale_id,
                payload={'receipt_no': receipt_no, 'total_amount': float(total_amount), 'customer_name': customer_name, 'student_adm_no': student_adm_no}
            )

            self.connection.commit()
            return {'sale_id': sale_id, 'receipt_no': receipt_no, 'total_amount': float(total_amount)}
        except Exception as e:
            self.connection.rollback()
            raise e

    # --- BATCH PRODUCTION & LOSSES ---
    def record_production_batch(self, business_unit_id: int, batch_no: str, item_name: str, location_id: int, total_produced: Decimal, loss_quantity: Decimal, input_cost: Decimal, user_id: int, loss_type_code: str = "SPOILAGE", loss_reason: str = "") -> Dict:
        try:
            item_master_id = self.inventory_tx_service._get_or_create_item_master(item_name)
            saleable_qty = Decimal(str(total_produced)) - Decimal(str(loss_quantity))
            if saleable_qty < Decimal('0.00'):
                saleable_qty = Decimal('0.00')

            unit_cost = (Decimal(str(input_cost)) / saleable_qty) if saleable_qty > Decimal('0.00') else Decimal('0.00')

            self.cursor.execute(
                """INSERT INTO production_batches (school_id, business_unit_id, batch_no, item_master_id, location_id, total_produced_qty, saleable_qty, total_input_cost, unit_production_cost, production_date, status, recorded_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE(), 'COMPLETED', %s)""",
                (self.school_id, business_unit_id, batch_no, item_master_id, location_id, total_produced, saleable_qty, input_cost, unit_cost, user_id)
            )
            batch_id = self.cursor.lastrowid

            # Add saleable output stock
            if saleable_qty > Decimal('0.00'):
                self.inventory_tx_service.produce_stock(
                    batch_id=batch_id,
                    item_name=item_name,
                    quantity=float(saleable_qty),
                    unit_cost=float(unit_cost),
                    user_id=user_id,
                    location_id=location_id,
                    business_unit_id=business_unit_id,
                    ref_no=batch_no,
                    notes=f"Batch production {batch_no}",
                    autocommit=False
                )

            # Record production loss if any
            if loss_quantity > Decimal('0.00'):
                self.cursor.execute("SELECT id FROM production_loss_types WHERE code = %s", (loss_type_code,))
                lt_row = self.cursor.fetchone()
                lt_id = lt_row['id'] if lt_row else 1
                loss_val = Decimal(str(loss_quantity)) * unit_cost

                self.cursor.execute(
                    """INSERT INTO production_losses (school_id, production_batch_id, item_master_id, quantity, loss_type_id, reason, financial_value, approval_status, recorded_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s)""",
                    (self.school_id, batch_id, item_master_id, loss_quantity, lt_id, loss_reason, loss_val, user_id)
                )

            self.connection.commit()
            return {'batch_id': batch_id, 'batch_no': batch_no, 'saleable_qty': float(saleable_qty), 'unit_cost': float(unit_cost)}
        except Exception as e:
            self.connection.rollback()
            raise e

    # --- EXPENSES ---
    def request_expense(self, business_unit_id: int, category_code: str, amount: Decimal, description: str, user_id: int) -> int:
        self.cursor.execute("SELECT id FROM expense_categories WHERE code = %s", (category_code,))
        cat_row = self.cursor.fetchone()
        cat_id = cat_row['id'] if cat_row else 1

        self.cursor.execute(
            """INSERT INTO business_expenses (school_id, business_unit_id, expense_date, description, amount, category_id, status, requested_by)
               VALUES (%s, %s, CURDATE(), %s, %s, %s, 'REQUESTED', %s)""",
            (self.school_id, business_unit_id, description, amount, cat_id, user_id)
        )
        self.connection.commit()
        return self.cursor.lastrowid

    def approve_expense(self, expense_id: int, approver_id: int) -> bool:
        try:
            self.cursor.execute("SELECT * FROM business_expenses WHERE id = %s AND school_id = %s", (expense_id, self.school_id))
            expense = self.cursor.fetchone()
            if not expense:
                raise ValueError("Expense request not found.")

            self.cursor.execute(
                "UPDATE business_expenses SET status = 'APPROVED', approved_by = %s WHERE id = %s AND school_id = %s",
                (approver_id, expense_id, self.school_id)
            )

            self.enqueue_accounting_event(
                business_unit_id=expense['business_unit_id'],
                event_type='EXPENSE_APPROVED',
                source_table='business_expenses',
                source_id=expense_id,
                payload={'amount': float(expense['amount']), 'description': expense['description']}
            )

            self.connection.commit()
            return True
        except Exception:
            self.connection.rollback()
            return False


class FarmManagementService(BusinessOperationsService):
    """
    Backward-compatible FarmManagementService wrapping BusinessOperationsService.
    Preserves exact legacy method signatures for existing farm endpoints.
    """
    def __init__(self, connection, school_id=None):
        super().__init__(connection, school_id)
        self.logger = logger

    def get_activities(self, active_only: bool = True) -> List[Dict]:
        return self.get_business_units(active_only=active_only)

    def _assert_activity_belongs_to_school(self, activity_id: int) -> None:
        self.cursor.execute("SELECT id FROM business_units WHERE id = %s AND school_id = %s", (activity_id, self.school_id))
        if not self.cursor.fetchone():
            raise ValueError("Business unit / activity not found for the active school.")

    def _assert_expense_belongs_to_school(self, expense_id: int) -> None:
        self.cursor.execute("SELECT id FROM business_expenses WHERE id = %s AND school_id = %s", (expense_id, self.school_id))
        if not self.cursor.fetchone():
            raise ValueError("Expense not found for the active school.")

    def create_activity(self, name: str, unit_of_measure: str, income_gl: str, expense_gl: str, description: str = "") -> int:
        return self.create_business_unit(
            name=name,
            type_code='AGRICULTURE',
            revenue_gl=income_gl,
            expense_gl=expense_gl
        )

    def record_production(self, activity_id: int, quantity: Decimal, spoilage: Decimal, internal: Decimal, recorded_by: int, notes: str = "") -> int:
        self._assert_activity_belongs_to_school(activity_id)
        batch_no = f"MILK-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        # Dynamically get or create a store location for this business unit
        locs = self.get_locations(activity_id)
        if locs:
            location_id = locs[0]['id']
        else:
            location_id = self.create_location(activity_id, "Main Store")

        res = self.record_production_batch(
            business_unit_id=activity_id,
            batch_no=batch_no,
            item_name="Farm Produce",
            location_id=location_id,
            total_produced=quantity,
            loss_quantity=spoilage,
            input_cost=Decimal('0.00'),
            user_id=recorded_by,
            loss_reason=notes
        )
        return res['batch_id']

    def record_sale(self, activity_id: int, customer: str, quantity: Decimal, unit_price: Decimal, recorded_by: int, is_paid: bool = True) -> int:
        self._assert_activity_belongs_to_school(activity_id)
        res = self.record_pos_sale(
            business_unit_id=activity_id,
            items=[{'item_name': 'Farm Produce', 'quantity': quantity, 'unit_price': unit_price}],
            customer_type='EXTERNAL',
            customer_name=customer,
            user_id=recorded_by,
            payment_method='CASH' if is_paid else 'STUDENT_ACCOUNT'
        )
        return res['sale_id']

    def request_expense(self, activity_id: int, category: str, amount: Decimal, description: str, recorded_by: int) -> int:
        self._assert_activity_belongs_to_school(activity_id)
        return super().request_expense(
            business_unit_id=activity_id,
            category_code=category.upper(),
            amount=amount,
            description=description,
            user_id=recorded_by
        )

    def get_financial_summary(self, activity_id: int = None, start_date: str = None, end_date: str = None) -> Dict:
        """Calculates Yield, Sales vs Expenses, and Spoilage Summary."""
        base_params = [self.school_id]
        filters = ""
        if activity_id:
            filters += " AND business_unit_id = %s"
            base_params.append(activity_id)

        sales_query = f"SELECT SUM(total_amount) as total_sales FROM business_sales WHERE school_id = %s {filters}"
        self.cursor.execute(sales_query, tuple(base_params))
        sales_res = self.cursor.fetchone()
        sales_total = (sales_res['total_sales'] if sales_res else 0) or 0

        exp_query = f"SELECT SUM(amount) as total_expenses FROM business_expenses WHERE school_id = %s AND status IN ('APPROVED', 'PAID', 'POSTED_TO_GL') {filters}"
        self.cursor.execute(exp_query, tuple(base_params))
        exp_res = self.cursor.fetchone()
        exp_total = (exp_res['total_expenses'] if exp_res else 0) or 0

        prod_query = f"SELECT SUM(total_produced_qty) as total_produced, SUM(total_produced_qty - saleable_qty) as total_spoilage FROM production_batches WHERE school_id = %s {filters}"
        self.cursor.execute(prod_query, tuple(base_params))
        prod_res = self.cursor.fetchone() or {'total_produced': 0, 'total_spoilage': 0}

        return {
            'revenue': float(sales_total),
            'expenses': float(exp_total),
            'profit': float(sales_total - exp_total),
            'production': {
                'total_produced': float((prod_res and prod_res['total_produced']) or 0),
                'total_spoilage': float((prod_res and prod_res['total_spoilage']) or 0),
                'total_internal': 0.0
            }
        }
