import pymysql
from datetime import datetime
from typing import Dict, List, Optional
from core.audit import audit_log
from core.tenancy import require_current_school_id
from flask import g

class InventoryService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id or require_current_school_id()

    def get_class_groups(self) -> List[Dict]:
        self.cursor.execute(
            "SELECT code, name FROM class_group_settings WHERE school_id = %s ORDER BY code",
            (self.school_id,),
        )
        return self.cursor.fetchall()

    def get_item_name_options(self) -> List[Dict]:
        self.cursor.execute(
            "SELECT DISTINCT item_name FROM uniform_prices WHERE school_id = %s ORDER BY item_name",
            (self.school_id,),
        )
        return self.cursor.fetchall()

    def get_uniform_items_for_group(self, class_group: str) -> List[Dict]:
        self.cursor.execute("SELECT item_name, price FROM uniform_prices WHERE class_group = %s AND school_id = %s", (class_group, self.school_id))
        return self.cursor.fetchall()

    @audit_log('add_uniform_item')
    def add_uniform_item(self, item_name: str, class_groups: List[str]):
        # Logic from app.py
        for group in class_groups:
            self.cursor.execute("INSERT INTO uniform_prices (item_name, class_group, price, school_id) VALUES (%s, %s, 0, %s)", (item_name, group, self.school_id))

        # Initialize stock
        self.cursor.execute("SELECT item_id FROM item_stock WHERE item_name = %s AND school_id = %s", (item_name, self.school_id))
        if not self.cursor.fetchone():
            self.cursor.execute("INSERT INTO item_stock (item_name, current_stock, reorder_level, school_id) VALUES (%s, 0, 10, %s)", (item_name, self.school_id))

        self.connection.commit()

    @audit_log('delete_uniform_item')
    def delete_uniform_item(self, item_name: str):
        normalized_item_name = (item_name or '').strip()
        if not normalized_item_name:
            raise ValueError("Item name is required.")
        self.cursor.execute(
            "SELECT item_name FROM uniform_prices WHERE item_name = %s AND school_id = %s LIMIT 1",
            (normalized_item_name, self.school_id),
        )
        if not self.cursor.fetchone():
            raise ValueError("Item not found for the active school.")
        self.cursor.execute("DELETE FROM uniform_prices WHERE item_name = %s AND school_id = %s", (normalized_item_name, self.school_id))
        self.cursor.execute("DELETE FROM item_stock WHERE item_name = %s AND school_id = %s", (normalized_item_name, self.school_id))
        self.connection.commit()

    def get_all_prices(self):
        self.cursor.execute("""
            SELECT item_name, class_group, price 
            FROM uniform_prices 
            WHERE school_id = %s 
            ORDER BY item_name, class_group
        """, (self.school_id,))
        return self.cursor.fetchall()

    @audit_log('update_uniform_price')
    def update_price(self, item_name, class_group, price):
        self.cursor.execute("""
            UPDATE uniform_prices 
            SET price = %s 
            WHERE item_name = %s AND class_group = %s AND school_id = %s
        """, (price, item_name, class_group, self.school_id))
        self.connection.commit()

    def get_stock_levels(self) -> List[Dict]:
        self.cursor.execute("""
            SELECT up.item_name,
                GROUP_CONCAT(DISTINCT up.class_group ORDER BY up.class_group) as class_groups,
                COALESCE(ist.current_stock, 0) as current_stock,
                COALESCE(ist.reorder_level, 10) as reorder_level,
                ist.last_restock_date
            FROM uniform_prices up
            LEFT JOIN item_stock ist ON up.item_name = ist.item_name AND up.school_id = ist.school_id
            WHERE up.school_id = %s
            GROUP BY up.item_name, ist.current_stock, ist.reorder_level, ist.last_restock_date
            ORDER BY up.item_name
        """, (self.school_id,))
        return self.cursor.fetchall()

    @audit_log('adjust_stock')
    def adjust_stock(self, item_name: str, quantity: int, type: str, user_id: int, notes: str = "", reference: str = ""):
        # Get current stock
        self.cursor.execute("SELECT current_stock, item_id FROM item_stock WHERE item_name = %s AND school_id = %s", (item_name, self.school_id))
        current = self.cursor.fetchone()

        if not current:
            self.cursor.execute("INSERT INTO item_stock (item_name, current_stock, reorder_level, updated_at, school_id) VALUES (%s, 0, 10, NOW(), %s)", (item_name, self.school_id))
            self.connection.commit()
            self.cursor.execute("SELECT current_stock, item_id FROM item_stock WHERE item_name = %s AND school_id = %s", (item_name, self.school_id))
            current = self.cursor.fetchone()

        prev_stock = current['current_stock']
        item_id = current['item_id']

        if type == 'PURCHASE':
            new_stock = prev_stock + quantity
        elif type == 'ADJUSTMENT':
            new_stock = quantity
        else: # ISSUANCE
            new_stock = prev_stock - quantity

        self.cursor.execute("UPDATE item_stock SET current_stock = %s, updated_at = NOW() WHERE item_id = %s AND school_id = %s", (new_stock, item_id, self.school_id))

        self.cursor.execute("""
            INSERT INTO stock_movements (item_id, movement_type, quantity, previous_stock, new_stock, reference_no, notes, user_id, school_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (item_id, type, quantity, prev_stock, new_stock, reference, notes, user_id, self.school_id))

        self.connection.commit()

    def get_stock_movements(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        query = """
            SELECT sm.movement_date, is.item_name, sm.movement_type, sm.quantity, sm.previous_stock, sm.new_stock, sm.reference_no, sm.student_admno, sm.notes, u.username
            FROM stock_movements sm
            JOIN item_stock is ON sm.item_id = is.item_id AND sm.school_id = is.school_id
            LEFT JOIN users u ON sm.user_id = u.userNo AND u.school_id = sm.school_id
            WHERE sm.school_id = %s
        """
        params = [self.school_id]
        if start_date: query += " AND sm.movement_date >= %s"; params.append(start_date)
        if end_date: query += " AND sm.movement_date <= %s"; params.append(end_date)
        query += " ORDER BY sm.movement_date DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_stock_ledger(self, item_name: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        query = """
            SELECT sm.*, u.username
            FROM stock_movements sm
            JOIN item_stock ist ON sm.item_id = ist.item_id AND sm.school_id = ist.school_id
            LEFT JOIN users u ON sm.user_id = u.userNo AND u.school_id = sm.school_id
            WHERE ist.item_name = %s AND sm.school_id = %s
        """
        params = [item_name, self.school_id]
        if start_date: query += " AND sm.movement_date >= %s"; params.append(start_date)
        if end_date: query += " AND sm.movement_date <= %s"; params.append(end_date)
        query += " ORDER BY sm.movement_date ASC, sm.movement_id ASC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_current_term(self):
        self.cursor.execute("SELECT id, term_number, year FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date AND school_id = %s LIMIT 1", (self.school_id,))
        return self.cursor.fetchone()

    def get_all_term_dates(self):
        self.cursor.execute("SELECT id, term_number, year, start_date, end_date FROM uniform_term_dates WHERE school_id = %s ORDER BY start_date DESC", (self.school_id,))
        return self.cursor.fetchall()

    def add_term_date(self, term_number, year, start_date, end_date):
        self.cursor.execute("""
            INSERT INTO uniform_term_dates (term_number, year, start_date, end_date, school_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (term_number, year, start_date, end_date, self.school_id))
        self.connection.commit()

    def delete_term_date(self, term_id):
        self.cursor.execute("DELETE FROM uniform_term_dates WHERE id = %s AND school_id = %s", (term_id, self.school_id))
        self.connection.commit()

    def get_student_by_admno(self, admno: str):
        self.cursor.execute("""
            SELECT si.AdmNo, si.FName, si.MName, si.SName, c.display_name, cgs.name as class_group
            FROM studentinfo si
            JOIN class_allocation ca ON si.AdmNo = ca.student_id AND ca.is_current = TRUE AND ca.school_id = si.school_id
            JOIN classes c ON ca.class_id = c.classID AND c.school_id = si.school_id
            JOIN class_group_settings cgs ON c.class_group_code = cgs.code AND cgs.school_id = si.school_id
            WHERE si.AdmNo = %s AND si.school_id = %s
        """, (admno, self.school_id))
        return self.cursor.fetchone()

    def _assert_student_belongs_to_school(self, admno: str) -> None:
        if not admno:
            raise ValueError("Student admission number is required.")
        if not self.get_student_by_admno(admno):
            raise ValueError("Student not found for the active school.")

    def _assert_item_belongs_to_school(self, item_name: str) -> None:
        self.cursor.execute(
            "SELECT item_id FROM item_stock WHERE item_name = %s AND school_id = %s",
            (item_name, self.school_id),
        )
        if not self.cursor.fetchone():
            raise ValueError("Item not found for the active school.")

    def _validate_issuance_items(self, items) -> List[Dict]:
        if not isinstance(items, list) or not items:
            raise ValueError("At least one issuance item is required.")

        normalized_items = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each issuance item must be an object.")

            item_name = (item.get('item_name') or '').strip()
            if not item_name:
                raise ValueError("Each issuance item must include an item name.")

            try:
                quantity = int(item.get('quantity', 0))
            except (TypeError, ValueError):
                raise ValueError("Each issuance item must include a valid quantity.")

            if quantity <= 0:
                raise ValueError("Each issuance item must have a quantity greater than zero.")

            try:
                price = float(item.get('price', 0))
                total = float(item.get('total', 0))
            except (TypeError, ValueError):
                raise ValueError("Each issuance item must include valid price and total values.")

            if price < 0 or total < 0:
                raise ValueError("Each issuance item must include non-negative price and total values.")

            self._assert_item_belongs_to_school(item_name)
            normalized_items.append(
                {
                    'item_name': item_name,
                    'quantity': quantity,
                    'price': price,
                    'total': total,
                }
            )

        return normalized_items

    @audit_log('process_uniform_issuance')
    def process_issuance(self, admno, items, user_id, receipt_no, total_amount):
        try:
            self._assert_student_belongs_to_school(admno)
            normalized_items = self._validate_issuance_items(items)

            # 1. Deduct stock and record movements
            for item in normalized_items:
                self.adjust_stock(
                    item['item_name'], 
                    item['quantity'], 
                    'ISSUANCE', 
                    user_id, 
                    f"Issued to {admno}", 
                    receipt_no
                )

                # 2. Save to uniform_receipts
                self.cursor.execute("""
                    INSERT INTO uniform_receipts (receipt_no, AdmNo, item_name, quantity, price, total, issued_by, school_id, issued_on)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (receipt_no, admno, item['item_name'], item['quantity'], item['price'], item['total'], user_id, self.school_id))
            
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise e

    def get_receipt_details(self, receipt_no: str):
        self.cursor.execute("""
            SELECT ur.*, si.FName, si.SName, u.username as issuer_name
            FROM uniform_receipts ur
            JOIN studentinfo si ON ur.AdmNo = si.AdmNo AND ur.school_id = si.school_id
            LEFT JOIN users u ON ur.issued_by = u.userNo AND ur.school_id = u.school_id
            WHERE ur.receipt_no = %s AND ur.school_id = %s
        """, (receipt_no, self.school_id))
        return self.cursor.fetchall()

    def get_issued_summary(self, start_date=None, end_date=None):
        query = """
            SELECT item_name, SUM(quantity) as total_quantity, SUM(total) as total_amount, COUNT(DISTINCT receipt_no) as receipts
            FROM uniform_receipts
            WHERE school_id = %s
        """
        params = [self.school_id]
        if start_date:
            query += " AND DATE(issued_on) >= %s"
            params.append(start_date)
        if end_date:
            query += " AND DATE(issued_on) <= %s"
            params.append(end_date)
        query += " GROUP BY item_name ORDER BY total_amount DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_items_totals(self, start_date=None, end_date=None):
        query = """
            SELECT item_name, SUM(quantity) as total_quantity
            FROM uniform_receipts
            WHERE school_id = %s
        """
        params = [self.school_id]
        if start_date:
            query += " AND DATE(issued_on) >= %s"
            params.append(start_date)
        if end_date:
            query += " AND DATE(issued_on) <= %s"
            params.append(end_date)
        query += " GROUP BY item_name"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_receipts_register(self, start_date=None, end_date=None):
        query = """
            SELECT ur.receipt_no, ur.AdmNo, si.FName, si.SName, ur.total, ur.issued_on, u.username as issued_by
            FROM uniform_receipts ur
            JOIN studentinfo si ON ur.AdmNo = si.AdmNo AND ur.school_id = si.school_id
            LEFT JOIN users u ON ur.issued_by = u.userNo AND ur.school_id = u.school_id
            WHERE ur.school_id = %s
        """
        params = [self.school_id]
        if start_date:
            query += " AND DATE(ur.issued_on) >= %s"
            params.append(start_date)
        if end_date:
            query += " AND DATE(ur.issued_on) <= %s"
            params.append(end_date)
        query += " ORDER BY ur.issued_on DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()
