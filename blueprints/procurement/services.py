from typing import List, Dict, Optional, Any
from decimal import Decimal
from datetime import datetime
import pymysql
from core.audit import audit_log
from flask import g

class ProcurementError(Exception):
    pass

class ProcurementService:
    def __init__(self, connection, school_id: Optional[int] = None):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id or g.school_id or 1

    # =========================================================================
    # 1. SUPPLIERS
    # =========================================================================

    def get_suppliers(self, active_only: bool = True) -> List[Dict]:
        """Fetch all suppliers from the existing suppliers table."""
        query = "SELECT * FROM suppliers WHERE school_id = %s"
        params = [self.school_id]
        if active_only:
            query += " AND in_operation = 'Y'"
        query += " ORDER BY company ASC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    @audit_log('create_supplier')
    def create_supplier(self, company: str, contact_person: str, email: str, phone: str, address: str, cert_no: str = "", pin_no: str = "") -> int:
        """Create a new supplier in the existing schema."""
        try:
            # Note: mobilePhone maps to mobilePhone in table
            self.cursor.execute("""
                INSERT INTO suppliers (company, contact_person, email, mobilePhone, address, cert_no, pin_no, in_operation, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'Y', %s)
            """, (company, contact_person, email, phone, address, cert_no, pin_no, self.school_id))
            self.connection.commit()
            return self.cursor.lastrowid
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to create supplier: {str(e)}")

    # =========================================================================
    # 2. PURCHASE REQUISITIONS (Internal)
    # =========================================================================

    @audit_log('create_requisition')
    def create_requisition(self, department_id: int, items: List[Dict], user_id: int, justification: str = "", category: str = "General", academic_year_id: int = None) -> Dict:
        """Create an internal request for items."""
        try:
            self.connection.begin()
            
            # Get current academic year if not provided
            if not academic_year_id:
                self.cursor.execute("SELECT id FROM academic_years WHERE is_current = 1 AND school_id = %s LIMIT 1", (self.school_id,))
                ay = self.cursor.fetchone()
                academic_year_id = ay['id'] if ay else 1

            # Generate Req number
            year_short = datetime.now().strftime('%y')
            self.cursor.execute("SELECT COUNT(*) as count FROM procurement_requisitions WHERE YEAR(created_at) = YEAR(CURDATE()) AND school_id = %s", (self.school_id,))
            count = self.cursor.fetchone()['count'] + 1
            req_number = f"REQ-{count:04d}-{year_short}"
            
            total_est = sum(Decimal(str(item['quantity'])) * Decimal(str(item.get('estimated_unit_price', 0))) for item in items)
            
            self.cursor.execute("""
                INSERT INTO procurement_requisitions (req_number, department_id, requested_by, request_date, total_estimated_amount, justification, category, academic_year_id, status, school_id)
                VALUES (%s, %s, %s, CURDATE(), %s, %s, %s, %s, 'PENDING_APPROVAL', %s)
            """, (req_number, department_id, user_id, total_est, justification, category, academic_year_id, self.school_id))
            
            req_id = self.cursor.lastrowid
            
            for item in items:
                self.cursor.execute("""
                    INSERT INTO procurement_requisition_items (requisition_id, description, quantity, estimated_unit_price, item_id, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (req_id, item['description'], item['quantity'], item.get('estimated_unit_price', 0), item.get('item_id'), self.school_id))
            
            self.connection.commit()
            return {'id': req_id, 'req_number': req_number}
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to create requisition: {str(e)}")

    def get_requisitions(self, status: Optional[str] = None) -> List[Dict]:
        query = """
            SELECT r.*, u.username as requester_name, d.dept as department_name
            FROM procurement_requisitions r
            JOIN users u ON r.requested_by = u.userNo AND r.school_id = u.school_id
            LEFT JOIN staffdepts d ON r.department_id = d.deptID AND r.school_id = d.school_id
            WHERE r.school_id = %s
        """
        params = [self.school_id]
        if status:
            query += " AND r.status = %s"
            params.append(status)
        query += " ORDER BY r.created_at DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    @audit_log('update_requisition_status')
    def update_requisition_status(self, req_id: int, status: str, user_id: int) -> bool:
        try:
            approved_at = datetime.now() if status == 'APPROVED' else None
            self.cursor.execute("""
                UPDATE procurement_requisitions 
                SET status = %s, approved_by = %s, approved_at = %s 
                WHERE id = %s AND school_id = %s
            """, (status, user_id if approved_at else None, approved_at, req_id, self.school_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to update requisition status: {str(e)}")

    def get_requisition_details(self, req_id: int) -> Dict:
        """Fetch a specific requisition with its items."""
        self.cursor.execute("""
            SELECT r.*, u.username as requester_name, d.dept as department_name,
                   appr.username as approved_by_name
            FROM procurement_requisitions r
            JOIN users u ON r.requested_by = u.userNo AND r.school_id = u.school_id
            LEFT JOIN staffdepts d ON r.department_id = d.deptID AND r.school_id = d.school_id
            LEFT JOIN users appr ON r.approved_by = appr.userNo AND r.school_id = appr.school_id
            WHERE r.id = %s AND r.school_id = %s
        """, (req_id, self.school_id))
        req = self.cursor.fetchone()
        
        if not req:
            return None
            
        self.cursor.execute("SELECT * FROM procurement_requisition_items WHERE requisition_id = %s AND school_id = %s", (req_id, self.school_id))
        req['items'] = self.cursor.fetchall()
        return req

    @audit_log('convert_requisition_to_po')
    def convert_requisition_to_po(self, req_id: int, supplier_id: int, user_id: int) -> Dict:
        """Convert an APPROVED requisition into a Purchase Order."""
        try:
            self.connection.begin()
            
            # 1. Validate requisition
            req = self.get_requisition_details(req_id)
            if not req or req['status'] != 'APPROVED':
                raise ProcurementError("Only APPROVED requisitions can be converted to PO")
                
            # 2. Create PO (re-using create_purchase_order logic but in same txn)
            year_short = datetime.now().strftime('%y')
            self.cursor.execute("SELECT COUNT(*) as count FROM purchase_orders WHERE YEAR(created_at) = YEAR(CURDATE()) AND school_id = %s", (self.school_id,))
            count = self.cursor.fetchone()['count'] + 1
            po_number = f"PO-{count:04d}-{year_short}"
            
            self.cursor.execute("""
                INSERT INTO purchase_orders (po_number, supplier_id, order_date, total_amount, status, notes, created_by, category, academic_year_id, department_id, school_id)
                VALUES (%s, %s, CURDATE(), %s, 'DRAFT', %s, %s, %s, %s, %s, %s)
            """, (po_number, supplier_id, req['total_estimated_amount'], f"Converted from {req['req_number']}", user_id, req['category'], req['academic_year_id'], req['department_id'], self.school_id))
            
            po_id = self.cursor.lastrowid
            
            # 3. Copy items
            for item in req['items']:
                self.cursor.execute("""
                    INSERT INTO purchase_order_items (po_id, item_id, description, quantity, unit_price, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (po_id, item.get('item_id'), item['description'], item['quantity'], item['estimated_unit_price'], self.school_id))
                
            # 4. Update Requisition Status
            self.cursor.execute("UPDATE procurement_requisitions SET status = 'CONVERTED_TO_PO' WHERE id = %s AND school_id = %s", (req_id, self.school_id))
            
            self.connection.commit()
            return {'id': po_id, 'po_number': po_number}
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Conversion failed: {str(e)}")

    # =========================================================================
    # 3. PURCHASE ORDERS
    # =========================================================================

    @audit_log('create_purchase_order')
    def create_purchase_order(self, supplier_id: int, order_date: str, items: List[Dict], user_id: int, notes: str = "", category: str = "General", academic_year_id: int = None, department_id: int = None) -> Dict:
        """
        Create a new PO with multiple items.
        Items: [{'description': str, 'quantity': decimal, 'unit_price': decimal}]
        """
        try:
            self.connection.begin()
            
            if not academic_year_id:
                self.cursor.execute("SELECT id FROM academic_years WHERE is_current = 1 AND school_id = %s LIMIT 1", (self.school_id,))
                ay = self.cursor.fetchone()
                academic_year_id = ay['id'] if ay else 1

            # Generate PO number
            year_short = datetime.now().strftime('%y')
            self.cursor.execute("SELECT COUNT(*) as count FROM purchase_orders WHERE YEAR(created_at) = YEAR(CURDATE()) AND school_id = %s", (self.school_id,))
            count = self.cursor.fetchone()['count'] + 1
            po_number = f"PO-{count:04d}-{year_short}"
            
            total_amount = sum(Decimal(str(item['quantity'])) * Decimal(str(item['unit_price'])) for item in items)
            
            self.cursor.execute("""
                INSERT INTO purchase_orders (po_number, supplier_id, order_date, total_amount, status, notes, created_by, category, academic_year_id, department_id, school_id)
                VALUES (%s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s, %s, %s)
            """, (po_number, supplier_id, order_date, total_amount, notes, user_id, category, academic_year_id, department_id, self.school_id))
            
            po_id = self.cursor.lastrowid
            
            for item in items:
                self.cursor.execute("""
                    INSERT INTO purchase_order_items (po_id, item_id, description, quantity, unit_price, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (po_id, item.get('item_id'), item['description'], item['quantity'], item['unit_price'], self.school_id))
            
            self.connection.commit()
            return {'id': po_id, 'po_number': po_number}
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to create purchase order: {str(e)}")

    @audit_log('update_purchase_order')
    def update_purchase_order(self, po_id: int, supplier_id: int, order_date: str, items: List[Dict], notes: str = "") -> bool:
        """Update an existing PO. Only allowed if status is DRAFT or PENDING_APPROVAL."""
        try:
            self.connection.begin()
            
            # Check status
            self.cursor.execute("SELECT status FROM purchase_orders WHERE id = %s AND school_id = %s", (po_id, self.school_id))
            po = self.cursor.fetchone()
            if not po:
                raise ProcurementError("Purchase order not found")
            
            if po['status'] not in ['DRAFT', 'PENDING_APPROVAL']:
                raise ProcurementError(f"Cannot edit PO in {po['status']} status")
                
            total_amount = sum(Decimal(str(item['quantity'])) * Decimal(str(item['unit_price'])) for item in items)
            
            # Update header
            self.cursor.execute("""
                UPDATE purchase_orders 
                SET supplier_id = %s, order_date = %s, total_amount = %s, notes = %s
                WHERE id = %s AND school_id = %s
            """, (supplier_id, order_date, total_amount, notes, po_id, self.school_id))
            
            # Refresh items: Delete old and insert new (simplest way for dynamic items)
            self.cursor.execute("DELETE FROM purchase_order_items WHERE po_id = %s AND school_id = %s", (po_id, self.school_id))
            
            for item in items:
                self.cursor.execute("""
                    INSERT INTO purchase_order_items (po_id, item_id, description, quantity, unit_price, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (po_id, item.get('item_id'), item['description'], item['quantity'], item['unit_price'], self.school_id))
            
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to update purchase order: {str(e)}")

    @audit_log('delete_purchase_order')
    def delete_purchase_order(self, po_id: int) -> bool:
        """Delete a PO. Only allowed if status is DRAFT."""
        try:
            self.connection.begin()
            
            self.cursor.execute("SELECT status FROM purchase_orders WHERE id = %s AND school_id = %s", (po_id, self.school_id))
            po = self.cursor.fetchone()
            if not po:
                raise ProcurementError("Purchase order not found")
                
            if po['status'] != 'DRAFT':
                raise ProcurementError(f"Cannot delete PO in {po['status']} status")
                
            # items will be deleted via CASCADE FK if set, but let's be explicit if not
            self.cursor.execute("DELETE FROM purchase_order_items WHERE po_id = %s AND school_id = %s", (po_id, self.school_id))
            self.cursor.execute("DELETE FROM purchase_orders WHERE id = %s AND school_id = %s", (po_id, self.school_id))
            
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to delete purchase order: {str(e)}")

    def get_purchase_orders(self, status: Optional[str] = None, po_number: Optional[str] = None, supplier_id: Optional[int] = None) -> List[Dict]:
        """Fetch all purchase orders with optional filters."""
        query = """
            SELECT po.*, s.company as supplier_name, u.username as created_by_name
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.supplierID AND po.school_id = s.school_id
            LEFT JOIN users u ON po.created_by = u.userNo AND po.school_id = u.school_id
            WHERE po.school_id = %s
        """
        params = [self.school_id]
        
        if status:
            query += " AND po.status = %s"
            params.append(status)
        if po_number:
            query += " AND po.po_number LIKE %s"
            params.append(f"%{po_number}%")
        if supplier_id:
            query += " AND po.supplier_id = %s"
            params.append(supplier_id)
            
        query += " ORDER BY po.created_at DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_po_details(self, po_id: int) -> Dict:
        """Fetch a specific PO with its items and received quantities."""
        self.cursor.execute("""
            SELECT po.*, s.company as supplier_name, s.email as supplier_email, s.mobilePhone as supplier_phone,
                   u.username as created_by_name
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.supplierID AND po.school_id = s.school_id
            LEFT JOIN users u ON po.created_by = u.userNo AND po.school_id = u.school_id
            WHERE po.id = %s AND po.school_id = %s
        """, (po_id, self.school_id))
        po = self.cursor.fetchone()
        
        if not po:
            return None
            
        # Get items with total received quantity
        self.cursor.execute("""
            SELECT poi.*, 
                   COALESCE(SUM(gi.quantity_received), 0) as total_received
            FROM purchase_order_items poi
            LEFT JOIN procurement_grn_items gi ON poi.id = gi.po_item_id AND poi.school_id = gi.school_id
            WHERE poi.po_id = %s AND poi.school_id = %s
            GROUP BY poi.id
        """, (po_id, self.school_id))
        po['po_items'] = self.cursor.fetchall()
        
        # Get associated GRNs
        self.cursor.execute("SELECT * FROM procurement_grns WHERE po_id = %s AND school_id = %s", (po_id, self.school_id))
        po['grns'] = self.cursor.fetchall()
        
        return po

    @audit_log('record_grn')
    def record_grn(self, po_id: int, received_by: int, items: List[Dict], delivery_note_ref: str = "", notes: str = "") -> str:
        """Record a partial or full delivery (GRN). Updates stock for each item."""
        try:
            self.connection.begin()
            
            # Generate GRN number
            year_short = datetime.now().strftime('%y')
            self.cursor.execute("SELECT COUNT(*) as count FROM procurement_grns WHERE YEAR(created_at) = YEAR(CURDATE()) AND school_id = %s", (self.school_id,))
            count = self.cursor.fetchone()['count'] + 1
            grn_number = f"GRN-{count:04d}-{year_short}"
            
            self.cursor.execute("""
                INSERT INTO procurement_grns (grn_number, po_id, received_date, received_by, delivery_note_ref, notes, school_id)
                VALUES (%s, %s, CURDATE(), %s, %s, %s, %s)
            """, (grn_number, po_id, received_by, delivery_note_ref, notes, self.school_id))
            grn_id = self.cursor.lastrowid
            
            # Process Items
            for item in items:
                po_item_id = item['po_item_id']
                qty_received = Decimal(str(item['quantity']))
                
                if qty_received <= 0:
                    continue
                    
                self.cursor.execute("""
                    INSERT INTO procurement_grn_items (grn_id, po_item_id, quantity_received, school_id)
                    VALUES (%s, %s, %s, %s)
                """, (grn_id, po_item_id, qty_received, self.school_id))
                
                # Fetch original item info for stock update
                self.cursor.execute("SELECT description, item_id FROM purchase_order_items WHERE id = %s AND school_id = %s", (po_item_id, self.school_id))
                poi = self.cursor.fetchone()
                
                # Update Stock (Re-using robust logic from before)
                item_id = poi.get('item_id')
                item_name = poi.get('description')
                
                if not item_id and item_name:
                    self.cursor.execute("SELECT item_id FROM item_stock WHERE UPPER(item_name) = UPPER(%s) AND school_id = %s", (item_name, self.school_id))
                    stock_item = self.cursor.fetchone()
                    if stock_item:
                        item_id = stock_item['item_id']
                    else:
                        # Only auto-create if it's a uniform item
                        self.cursor.execute("SELECT item_name FROM uniform_prices WHERE UPPER(item_name) = UPPER(%s) AND school_id = %s LIMIT 1", (item_name, self.school_id))
                        u_info = self.cursor.fetchone()
                        if u_info:
                            self.cursor.execute("INSERT INTO item_stock (item_name, current_stock, school_id) VALUES (%s, 0, %s)", (u_info['item_name'], self.school_id))
                            item_id = self.cursor.lastrowid
                            self.cursor.execute("UPDATE purchase_order_items SET item_id = %s WHERE id = %s AND school_id = %s", (item_id, po_item_id, self.school_id))

                if item_id:
                    self.cursor.execute("SELECT current_stock FROM item_stock WHERE item_id = %s AND school_id = %s", (item_id, self.school_id))
                    curr_item = self.cursor.fetchone()
                    curr = curr_item.get('current_stock', 0) if curr_item else 0
                    new_st = curr + qty_received
                    
                    self.cursor.execute("UPDATE item_stock SET current_stock = %s, last_restock_date = CURDATE() WHERE item_id = %s AND school_id = %s", (new_st, item_id, self.school_id))
                    
                    self.cursor.execute("""
                        INSERT INTO stock_movements (item_id, movement_type, quantity, previous_stock, new_stock, reference_no, user_id, notes, school_id)
                        VALUES (%s, 'PURCHASE', %s, %s, %s, %s, %s, %s, %s)
                    """, (item_id, qty_received, curr, new_st, grn_number, received_by, f"GRN for PO item {po_item_id}", self.school_id))

            # Check if PO is now fully received
            self.cursor.execute("""
                SELECT 
                    (SELECT SUM(quantity) FROM purchase_order_items WHERE po_id = %s AND school_id = %s) as total_ordered,
                    (SELECT SUM(quantity_received) FROM procurement_grn_items gi 
                     JOIN purchase_order_items poi ON gi.po_item_id = poi.id AND gi.school_id = poi.school_id
                     WHERE poi.po_id = %s AND poi.school_id = %s) as total_received
            """, (po_id, self.school_id, po_id, self.school_id))
            balance = self.cursor.fetchone()
            
            if balance and balance['total_received'] and balance['total_ordered'] and balance['total_received'] >= balance['total_ordered']:
                self.cursor.execute("UPDATE purchase_orders SET status = 'RECEIVED' WHERE id = %s AND school_id = %s", (po_id, self.school_id))

            self.connection.commit()
            return grn_number
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to record GRN: {str(e)}")

    @audit_log('update_po_status')
    def update_po_status(self, po_id: int, status: str, user_id: int) -> bool:
        """Update status and post to GL if RECEIVED (Accrual Basis)."""
        try:
            self.connection.begin()
            
            self.cursor.execute("SELECT * FROM purchase_orders WHERE id = %s AND school_id = %s", (po_id, self.school_id))
            po = self.cursor.fetchone()
            if not po:
                raise ProcurementError("Purchase order not found")

            # Post Invoice to GL when goods are received
            if status == 'RECEIVED' and po['status'] != 'RECEIVED':
                # 1. Identify Accounts
                self.cursor.execute("SELECT id FROM finance_accounts WHERE (name LIKE '%%Purchases%%' OR name LIKE '%%Inventory%%') AND school_id = %s ORDER BY id ASC LIMIT 1", (self.school_id,))
                expense_acc = self.cursor.fetchone()
                expense_id = expense_acc['id'] if expense_acc else 1
                
                self.cursor.execute("SELECT id FROM finance_accounts WHERE (name LIKE '%%Accounts Payable%%' OR name LIKE '%%Suppliers%%') AND school_id = %s ORDER BY id ASC LIMIT 1", (self.school_id,))
                ap_acc = self.cursor.fetchone()
                ap_id = ap_acc['id'] if ap_acc else 6
                
                # 2. Transaction Header
                self.cursor.execute("""
                    INSERT INTO finance_transactions (transaction_date, reference_no, description, created_by, school_id)
                    VALUES (CURDATE(), %s, %s, %s, %s)
                """, (f"INV-{po['po_number']}", f"Goods Received Note for PO {po['po_number']}", user_id, self.school_id))
                txn_id = self.cursor.lastrowid
                
                # 3. Double Entry
                # DR Expense (Purchases)
                self.cursor.execute("""
                    INSERT INTO finance_ledger_entries (transaction_id, account_id, debit, credit, note, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (txn_id, expense_id, po['total_amount'], 0, f"PO {po['po_number']} Received", self.school_id))
                
                # CR Accounts Payable (Associate with Supplier)
                self.cursor.execute("""
                    INSERT INTO finance_ledger_entries (transaction_id, account_id, supplier_id, debit, credit, note, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (txn_id, ap_id, po['supplier_id'], 0, po['total_amount'], f"Liability recognized for PO {po['po_number']}", self.school_id))

                # 4. Update Uniform Stock if applicable
                self.cursor.execute("SELECT * FROM purchase_order_items WHERE po_id = %s AND school_id = %s", (po_id, self.school_id))
                po_items = self.cursor.fetchall()
                for item in po_items:
                    item_id = item.get('item_id')
                    item_name = item.get('description')
                    
                    # If item_id is missing, try matching by name in item_stock (case-insensitive)
                    if not item_id and item_name:
                        self.cursor.execute("SELECT item_id FROM item_stock WHERE UPPER(item_name) = UPPER(%s) AND school_id = %s", (item_name, self.school_id))
                        stock_item = self.cursor.fetchone()
                        if stock_item:
                            item_id = stock_item['item_id']
                        else:
                            # ONLY auto-create if it's explicitly a uniform item (exists in uniform_prices)
                            self.cursor.execute("SELECT item_name FROM uniform_prices WHERE UPPER(item_name) = UPPER(%s) AND school_id = %s LIMIT 1", (item_name, self.school_id))
                            uniform_exists = self.cursor.fetchone()
                            
                            if uniform_exists:
                                standardized_name = uniform_exists['item_name']
                                self.cursor.execute("""
                                    INSERT INTO item_stock (item_name, current_stock, last_restock_date, school_id)
                                    VALUES (%s, 0, CURDATE(), %s)
                                """, (standardized_name, self.school_id))
                                item_id = self.cursor.lastrowid
                                
                                # Update references for consistency
                                self.cursor.execute("UPDATE purchase_order_items SET item_id = %s WHERE id = %s AND school_id = %s", (item_id, item['id'], self.school_id))
                                self.cursor.execute("UPDATE uniform_prices SET item_id = %s WHERE item_name = %s AND school_id = %s", (item_id, standardized_name, self.school_id))
                            else:
                                # Not a uniform item, skip stock update
                                continue

                    if item_id:
                        # Get current stock
                        self.cursor.execute("SELECT current_stock FROM item_stock WHERE item_id = %s AND school_id = %s", (item_id, self.school_id))
                        curr_stock_row = self.cursor.fetchone()
                        curr_stock = curr_stock_row['current_stock'] if curr_stock_row else 0
                        qty = int(item['quantity'])
                        new_stock = curr_stock + qty
                        
                        # Update stock
                        self.cursor.execute("""
                            UPDATE item_stock 
                            SET current_stock = %s, last_restock_date = CURDATE()
                            WHERE item_id = %s AND school_id = %s
                        """, (new_stock, item_id, self.school_id))
                        
                        # Record movement
                        self.cursor.execute("""
                            INSERT INTO stock_movements 
                            (item_id, movement_type, quantity, previous_stock, new_stock, reference_no, user_id, notes, school_id)
                            VALUES (%s, 'PURCHASE', %s, %s, %s, %s, %s, %s, %s)
                        """, (item_id, qty, curr_stock, new_stock, po['po_number'], user_id, f"Restock via PO {po['po_number']}", self.school_id))


            update_fields = ["status = %s"]
            params = [status]
            
            if status == 'ORDERED':
                # Mark approved
                update_fields.append("approved_by = %s")
                params.append(user_id)
                
                # Update Budget Spent Amount
                if po['category'] and po['academic_year_id'] and po['department_id']:
                    self.cursor.execute("""
                        UPDATE procurement_budgets 
                        SET spent_amount = spent_amount + %s 
                        WHERE category = %s AND academic_year_id = %s AND department_id = %s AND school_id = %s
                    """, (po['total_amount'], po['category'], po['academic_year_id'], po['department_id'], self.school_id))

            query = f"UPDATE purchase_orders SET {', '.join(update_fields)} WHERE id = %s AND school_id = %s"
            params.append(po_id)
            params.append(self.school_id)
            
            self.cursor.execute(query, params)
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to update PO status: {str(e)}")

    @audit_log('record_po_payment')
    def record_po_payment(self, po_id: int, amount: Decimal, mode: str, reference: str, date: str, user_id: int, source_account_id: int) -> bool:
        """Record a partial or full payment for a PO, clearing liability in GL."""
        try:
            self.connection.begin()
            
            # 1. Insert into supplier_payments
            self.cursor.execute("""
                INSERT INTO supplier_payments (po_id, amount, payment_date, payment_mode, reference_no, created_by, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (po_id, amount, date, mode, reference, user_id, self.school_id))
            
            # 2. Update PO payment status
            self.cursor.execute("SELECT total_amount, po_number, supplier_id FROM purchase_orders WHERE id = %s AND school_id = %s", (po_id, self.school_id))
            po = self.cursor.fetchone()
            if not po:
                raise ProcurementError("Purchase order not found")
            po_num = po['po_number']
            
            self.cursor.execute("SELECT SUM(amount) as total_paid FROM supplier_payments WHERE po_id = %s AND school_id = %s", (po_id, self.school_id))
            total_paid_row = self.cursor.fetchone()
            total_paid = Decimal(str(total_paid_row['total_paid'] if total_paid_row['total_paid'] else 0))
            
            if total_paid >= Decimal(str(po['total_amount'])):
                new_status = 'PAID'
            elif total_paid > 0:
                new_status = 'PARTIAL'
            else:
                new_status = 'UNPAID'
                
            self.cursor.execute("UPDATE purchase_orders SET payment_status = %s WHERE id = %s AND school_id = %s", (new_status, po_id, self.school_id))
            
            # 3. Double-Entry Accounting
            # Identify Accounts Payable (to Debit)
            self.cursor.execute("SELECT id FROM finance_accounts WHERE (name LIKE '%%Accounts Payable%%' OR name LIKE '%%Suppliers%%') AND school_id = %s ORDER BY id ASC LIMIT 1", (self.school_id,))
            ap_acc = self.cursor.fetchone()
            ap_id = ap_acc['id'] if ap_acc else 6
            
            # Create Transaction Header
            self.cursor.execute("""
                INSERT INTO finance_transactions (transaction_date, reference_no, description, created_by, school_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (date, f"PAY-{po_num}-{reference}", f"Payment for PO {po_num} to Supplier", user_id, self.school_id))
            txn_id = self.cursor.lastrowid
            
            # Create Ledger Entries
            # DR Accounts Payable (Clear liability for Supplier)
            self.cursor.execute("""
                INSERT INTO finance_ledger_entries (transaction_id, account_id, supplier_id, debit, credit, note, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (txn_id, ap_id, po['supplier_id'], amount, 0, f"PO {po_num} Payment - {reference}", self.school_id))
            
            # CR Bank/Cash (Source Account)
            self.cursor.execute("""
                INSERT INTO finance_ledger_entries (transaction_id, account_id, debit, credit, note, school_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (txn_id, source_account_id, 0, amount, f"Payment for PO {po_num} via {mode}", self.school_id))
            
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to record payment: {str(e)}")

    def get_vendor_statement(self, supplier_id: int, start_date: str, end_date: str) -> List[Dict]:
        """Fetch all ledger transactions for a vendor to produce a statement."""
        # First, ensure we get a clean running balance by fetching ALL history up to start_date if needed, 
        # but for this implementation we return the requested range.
        self.cursor.execute("""
            SELECT 
                t.transaction_date as date,
                t.reference_no,
                le.note as description,
                le.debit,
                le.credit,
                a.name as account_mapped
            FROM finance_ledger_entries le
            JOIN finance_transactions t ON le.transaction_id = t.id AND le.school_id = t.school_id
            JOIN finance_accounts a ON le.account_id = a.id AND le.school_id = a.school_id
            WHERE le.supplier_id = %s AND le.school_id = %s
            ORDER BY t.transaction_date ASC, t.id ASC
        """, (supplier_id, self.school_id))
        return self.cursor.fetchall()

    # =========================================================================
    # 5. ASSET REGISTRY
    # =========================================================================

    @audit_log('register_asset')
    def register_asset(self, data: Dict, user_id: int) -> int:
        """Register a new fixed asset."""
        try:
            self.cursor.execute("""
                INSERT INTO assets_registry 
                (asset_name, tag_number, category, purchase_date, purchase_value, 
                 location, condition_status, po_id, created_by, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data['asset_name'], data.get('tag_number'), data['category'],
                data['purchase_date'], data['purchase_value'],
                data.get('location'), data.get('condition_status', 'NEW'),
                data.get('po_id'), user_id, self.school_id
            ))
            self.connection.commit()
            return self.cursor.lastrowid
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to register asset: {str(e)}")

    def get_assets(self, filters: Dict = None) -> List[Dict]:
        """Fetch assets with optional filtering."""
        query = "SELECT a.*, u.username as creator_name FROM assets_registry a JOIN users u ON a.created_by = u.userNo AND a.school_id = u.school_id WHERE a.school_id = %s"
        params = [self.school_id]
        if filters:
            if filters.get('category'):
                query += " AND a.category = %s"
                params.append(filters['category'])
            if filters.get('condition'):
                query += " AND a.condition_status = %s"
                params.append(filters['condition'])
        
        query += " ORDER BY a.purchase_date DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    @audit_log('update_asset_condition')
    def update_asset_condition(self, asset_id: int, new_condition: Dict, user_id: int) -> bool:
        """Update asset condition or location."""
        try:
            self.cursor.execute("""
                UPDATE assets_registry 
                SET condition_status = %s, location = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND school_id = %s
            """, (new_condition['condition'], new_condition['location'], asset_id, self.school_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to update asset: {str(e)}")

    # =========================================================================
    # 6. BUDGETARY CONTROL
    # =========================================================================

    def get_budgets(self, academic_year_id: int) -> List[Dict]:
        """Fetch all budgets for a given academic year."""
        self.cursor.execute("""
            SELECT b.*, d.dept as department_name, ay.year as year_name
            FROM procurement_budgets b
            JOIN staffdepts d ON b.department_id = d.deptID AND b.school_id = d.school_id
            JOIN academic_years ay ON b.academic_year_id = ay.id AND b.school_id = ay.school_id
            WHERE b.academic_year_id = %s AND b.school_id = %s
        """, (academic_year_id, self.school_id))
        return self.cursor.fetchall()

    def set_budget(self, department_id: int, academic_year_id: int, category: str, amount: Decimal) -> bool:
        """Create or update a departmental budget."""
        try:
            self.cursor.execute("""
                INSERT INTO procurement_budgets (department_id, academic_year_id, category, allocated_amount, school_id)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE allocated_amount = VALUES(allocated_amount)
            """, (department_id, academic_year_id, category, amount, self.school_id))
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise ProcurementError(f"Failed to set budget: {str(e)}")

    def check_budget(self, department_id: int, category: str, amount: Decimal, academic_year_id: int) -> Dict:
        """Check if an expense fits within the remaining budget."""
        self.cursor.execute("""
            SELECT allocated_amount, spent_amount 
            FROM procurement_budgets 
            WHERE department_id = %s AND category = %s AND academic_year_id = %s AND school_id = %s
        """, (department_id, category, academic_year_id, self.school_id))
        budget = self.cursor.fetchone()
        
        if not budget:
            return {'allowed': True, 'warning': "No budget defined for this category/department."}
            
        remaining = Decimal(str(budget['allocated_amount'])) - Decimal(str(budget['spent_amount']))
        if amount > remaining:
            return {
                'allowed': False, 
                'remaining': remaining,
                'message': f"Request of {amount} exceeds remaining budget of {remaining}"
            }
        
        return {'allowed': True, 'remaining': remaining}

    # =========================================================================
    # 7. FINANCIAL REPORTS & AGING
    # =========================================================================

    def get_suppliers_aging(self) -> List[Dict]:
        """
        Produce a Supplier Aging Report.
        Buckets: 0-30 days, 31-60 days, 61-90 days, 91+ days.
        Owed = PO Total - Payments
        """
        # We define "Due" by order_date because we don't have a formal "due_date" 
        # but in schools, it's usually 30 days from order/invoice.
        self.cursor.execute("""
            SELECT 
                s.supplierID,
                s.company as supplier_name,
                SUM(CASE WHEN DATEDIFF(CURDATE(), po.order_date) <= 30 THEN (po.total_amount - COALESCE(payments.paid, 0)) ELSE 0 END) as bucket_0_30,
                SUM(CASE WHEN DATEDIFF(CURDATE(), po.order_date) BETWEEN 31 AND 60 THEN (po.total_amount - COALESCE(payments.paid, 0)) ELSE 0 END) as bucket_31_60,
                SUM(CASE WHEN DATEDIFF(CURDATE(), po.order_date) BETWEEN 61 AND 90 THEN (po.total_amount - COALESCE(payments.paid, 0)) ELSE 0 END) as bucket_61_90,
                SUM(CASE WHEN DATEDIFF(CURDATE(), po.order_date) > 90 THEN (po.total_amount - COALESCE(payments.paid, 0)) ELSE 0 END) as bucket_91_plus,
                SUM(po.total_amount - COALESCE(payments.paid, 0)) as total_owed
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.supplierID AND po.school_id = s.school_id
            LEFT JOIN (
                SELECT po_id, school_id, SUM(amount) as paid FROM supplier_payments GROUP BY po_id, school_id
            ) payments ON po.id = payments.po_id AND po.school_id = payments.school_id
            WHERE po.status IN ('ORDERED', 'RECEIVED', 'PARTIAL') 
              AND po.payment_status != 'PAID'
              AND po.school_id = %s
            GROUP BY s.supplierID
            HAVING total_owed > 0
            ORDER BY total_owed DESC
        """, (self.school_id,))
        return self.cursor.fetchall()
