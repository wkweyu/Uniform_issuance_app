import pymysql
from datetime import datetime
from typing import Dict, List, Optional
from core.audit import audit_log
from core.tenancy import require_current_school_id
from flask import g

class TransportService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id or require_current_school_id()

    def get_buses(self) -> List[Dict]:
        self.cursor.execute("SELECT * FROM buses WHERE school_id = %s ORDER BY reg_no", (self.school_id,))
        return self.cursor.fetchall()

    def get_bus_by_id(self, bus_id: int) -> Optional[Dict]:
        self.cursor.execute("SELECT * FROM buses WHERE id = %s AND school_id = %s", (bus_id, self.school_id))
        return self.cursor.fetchone()

    def _assert_bus_belongs_to_school(self, bus_id: int) -> None:
        self.cursor.execute("SELECT id FROM buses WHERE id = %s AND school_id = %s", (bus_id, self.school_id))
        if not self.cursor.fetchone():
            raise ValueError("Bus not found for the active school.")

    def _assert_route_belongs_to_school(self, route_id: int) -> None:
        self.cursor.execute("SELECT id FROM transport_routes WHERE id = %s AND school_id = %s", (route_id, self.school_id))
        if not self.cursor.fetchone():
            raise ValueError("Route not found for the active school.")

    @audit_log('add_bus')
    def add_bus(self, data: Dict):
        model = data['model']
        self.cursor.execute("""
            INSERT INTO buses (reg_no, model, capacity, current_mileage, driver_name, school_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (data['reg_no'], model, data['capacity'], data['current_mileage'], data['driver_name'], self.school_id))
        self.connection.commit()

    @audit_log('update_bus')
    def update_bus(self, bus_id: int, data: Dict):
        self._assert_bus_belongs_to_school(bus_id)
        model = data['model']
        self.cursor.execute("""
            UPDATE buses SET reg_no=%s, model=%s, capacity=%s, current_mileage=%s, driver_name=%s
            WHERE id=%s AND school_id=%s
        """, (data['reg_no'], model, data['capacity'], data['current_mileage'], data['driver_name'], bus_id, self.school_id))
        self.connection.commit()

    @audit_log('delete_bus')
    def delete_bus(self, bus_id: int):
        self._assert_bus_belongs_to_school(bus_id)
        self.cursor.execute("DELETE FROM buses WHERE id=%s AND school_id=%s", (bus_id, self.school_id))
        self.connection.commit()

    @audit_log('record_service')
    def record_service(self, data: Dict):
        self._assert_bus_belongs_to_school(data['bus_id'])
        self.cursor.execute("""
            INSERT INTO bus_services (bus_id, service_date, service_type, description, cost, garage_name, mileage_at_service, school_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (data['bus_id'], data['service_date'], data['service_type'], data['description'], data['cost'], data['garage_name'], data['mileage_at_service'], self.school_id))

        # Update bus mileage if newer
        self.cursor.execute("UPDATE buses SET current_mileage = GREATEST(current_mileage, %s) WHERE id = %s AND school_id = %s", (data['mileage_at_service'], data['bus_id'], self.school_id))
        self.connection.commit()

    def get_service_history(self, bus_id: Optional[int] = None) -> List[Dict]:
        query = "SELECT s.*, b.reg_no FROM bus_services s JOIN buses b ON s.bus_id = b.id AND s.school_id = b.school_id WHERE s.school_id = %s"
        params = [self.school_id]
        if bus_id:
            query += " AND s.bus_id = %s"
            params.append(bus_id)
        query += " ORDER BY s.service_date DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    @audit_log('issue_fuel')
    def issue_fuel(self, data: Dict):
        self._assert_bus_belongs_to_school(data['bus_id'])
        # Generate voucher number
        self.cursor.execute("SELECT COUNT(*) as count FROM fuel_vouchers WHERE school_id = %s", (self.school_id,))
        count = self.cursor.fetchone()['count'] + 1
        voucher_no = f"FV-{datetime.now().year}-{count:04d}"

        self.cursor.execute("""
            INSERT INTO fuel_vouchers (voucher_no, bus_id, date_issued, fuel_type, quantity, unit_price, total_cost, current_mileage, issued_by, school_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (voucher_no, data['bus_id'], data['date_issued'], data['fuel_type'], data['quantity'], data['unit_price'], data['total_cost'], data['current_mileage'], data['issued_by'], self.school_id))

        self.cursor.execute("UPDATE buses SET current_mileage = GREATEST(current_mileage, %s) WHERE id = %s AND school_id = %s", (data['current_mileage'], data['bus_id'], self.school_id))
        self.connection.commit()
        return voucher_no

    def get_fuel_vouchers(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        query = "SELECT v.*, b.reg_no FROM fuel_vouchers v JOIN buses b ON v.bus_id = b.id AND v.school_id = b.school_id WHERE v.school_id = %s"
        params = [self.school_id]
        if start_date: query += " AND v.date_issued >= %s"; params.append(start_date)
        if end_date: query += " AND v.date_issued <= %s"; params.append(end_date)
        query += " ORDER BY v.date_issued DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_fuel_voucher_for_print(self, voucher_no: str) -> Optional[Dict]:
        self.cursor.execute(
            """
            SELECT v.*, b.reg_no, b.driver_name, COALESCE(u.username, CAST(v.issued_by AS CHAR)) as issued_by
            FROM fuel_vouchers v
            JOIN buses b ON v.bus_id = b.id AND v.school_id = b.school_id
            LEFT JOIN users u ON v.issued_by = u.userNo AND v.school_id = u.school_id
            WHERE v.voucher_no = %s AND v.school_id = %s
            """,
            (voucher_no, self.school_id),
        )
        return self.cursor.fetchone()

    def get_fleet_dashboard_summary(self) -> Dict:
        self.cursor.execute("SELECT COUNT(*) as count FROM buses WHERE school_id = %s", (self.school_id,))
        bus_count = self.cursor.fetchone()['count']

        self.cursor.execute("SELECT COALESCE(SUM(total_cost), 0) as total FROM fuel_vouchers WHERE school_id = %s", (self.school_id,))
        fuel_cost = self.cursor.fetchone()['total']

        self.cursor.execute("SELECT COALESCE(SUM(cost), 0) as total FROM bus_services WHERE school_id = %s", (self.school_id,))
        service_cost = self.cursor.fetchone()['total']

        return {
            'bus_count': bus_count,
            'fuel_cost_total': fuel_cost,
            'service_cost_total': service_cost,
        }

    def get_routes(self) -> List[Dict]:
        self.cursor.execute("SELECT * FROM transport_routes WHERE school_id = %s ORDER BY name", (self.school_id,))
        return self.cursor.fetchall()

    @audit_log('add_route')
    def add_route(self, data: Dict):
        self.cursor.execute("""
            INSERT INTO transport_routes (name, amount, description, school_id)
            VALUES (%s, %s, %s, %s)
        """, (data['name'], data['amount'], data['description'], self.school_id))
        self.connection.commit()

    @audit_log('delete_route')
    def delete_route(self, route_id: int):
        self._assert_route_belongs_to_school(route_id)
        self.cursor.execute("DELETE FROM transport_routes WHERE id = %s AND school_id = %s", (route_id, self.school_id))
        self.connection.commit()
