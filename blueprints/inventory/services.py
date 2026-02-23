import pymysql
from datetime import datetime
from typing import Dict, List, Optional
from core.audit import audit_log
from flask import g

class InventoryService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id or g.school_id or 1

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
        self.cursor.execute("DELETE FROM uniform_prices WHERE item_name = %s AND school_id = %s", (item_name, self.school_id))
        self.cursor.execute("DELETE FROM item_stock WHERE item_name = %s AND school_id = %s", (item_name, self.school_id))
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
