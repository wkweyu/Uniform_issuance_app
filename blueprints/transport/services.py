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
        self.cursor.execute("""
            SELECT r.*, b.reg_no as bus_reg_no, b.driver_name
            FROM transport_routes r
            LEFT JOIN buses b ON r.bus_id = b.id AND r.school_id = b.school_id
            WHERE r.school_id = %s
            ORDER BY r.name
        """, (self.school_id,))
        return self.cursor.fetchall()

    def get_route_by_id(self, route_id: int) -> Optional[Dict]:
        self.cursor.execute("""
            SELECT r.*, b.reg_no as bus_reg_no, b.driver_name
            FROM transport_routes r
            LEFT JOIN buses b ON r.bus_id = b.id AND r.school_id = b.school_id
            WHERE r.id = %s AND r.school_id = %s
        """, (route_id, self.school_id))
        return self.cursor.fetchone()

    def get_transport_assignments(self, route_id: Optional[int] = None, search_query: Optional[str] = None) -> List[Dict]:
        query = """
            SELECT s.AdmNo, CONCAT_WS(' ', COALESCE(s.FName, ''), COALESCE(s.MName, ''), COALESCE(s.SName, '')) as student_name,
                   s.Sex as gender, s.category, r.id as route_id, r.name as route_name, r.amount as route_amount,
                   COALESCE(c_current.display_name, c_legacy.class_name, 'Unassigned') as class_name,
                   p.pName as parent_name, p.phone1 as parent_phone
            FROM studentinfo s
            JOIN transport_routes r ON s.route_id = r.id AND s.school_id = r.school_id
            LEFT JOIN class_allocation modern_ca ON s.AdmNo = modern_ca.student_id AND modern_ca.is_current = TRUE AND s.school_id = modern_ca.school_id
            LEFT JOIN classes c_current ON modern_ca.class_id = c_current.classID AND modern_ca.school_id = c_current.school_id
            LEFT JOIN classallocation legacy_ca ON s.AdmNo = legacy_ca.AdmNo AND s.school_id = legacy_ca.school_id
            LEFT JOIN classes c_legacy ON legacy_ca.classID = c_legacy.classID AND legacy_ca.school_id = c_legacy.school_id
            LEFT JOIN parentinfo p ON s.AdmNo = p.admno AND s.school_id = p.school_id
            WHERE s.school_id = %s
        """
        params = [self.school_id]
        if route_id:
            query += " AND s.route_id = %s"
            params.append(route_id)
        if search_query:
            query += " AND (s.AdmNo LIKE %s OR CONCAT_WS(' ', COALESCE(s.FName, ''), COALESCE(s.MName, ''), COALESCE(s.SName, '')) LIKE %s OR r.name LIKE %s)"
            params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])
        query += " GROUP BY s.AdmNo ORDER BY r.name, s.FName, s.SName"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_transport_revenue_summary(self) -> List[Dict]:
        query = """
            SELECT r.id as route_id, r.name as route_name, r.amount as route_charge,
                   COALESCE(b.reg_no, 'Unassigned') as bus_reg_no, COALESCE(b.driver_name, 'N/A') as driver_name,
                   COUNT(s.AdmNo) as student_count,
                   (COUNT(s.AdmNo) * r.amount) as expected_revenue,
                   COALESCE(SUM(paid_tbl.paid_amount), 0) as collected_revenue
            FROM transport_routes r
            LEFT JOIN buses b ON r.bus_id = b.id AND r.school_id = b.school_id
            LEFT JOIN studentinfo s ON r.id = s.route_id AND r.school_id = s.school_id
            LEFT JOIN (
                SELECT fl.admno, fl.school_id, SUM(fl.amount) as paid_amount
                FROM fee_ledger fl
                JOIN fee_voteheads fv ON fl.votehead_id = fv.id AND fl.school_id = fv.school_id
                WHERE fv.name = 'Transport' AND fl.type = 'PAYMENT'
                GROUP BY fl.admno, fl.school_id
            ) paid_tbl ON s.AdmNo = paid_tbl.admno AND s.school_id = paid_tbl.school_id
            WHERE r.school_id = %s
            GROUP BY r.id
            ORDER BY r.name
        """
        self.cursor.execute(query, (self.school_id,))
        return self.cursor.fetchall()

    def get_unassigned_active_students(self) -> List[Dict]:
        query = """
            SELECT s.AdmNo, CONCAT_WS(' ', COALESCE(s.FName, ''), COALESCE(s.MName, ''), COALESCE(s.SName, '')) as student_name,
                   COALESCE(c_current.display_name, c_legacy.class_name, 'Unassigned') as class_name
            FROM studentinfo s
            LEFT JOIN class_allocation modern_ca ON s.AdmNo = modern_ca.student_id AND modern_ca.is_current = TRUE AND s.school_id = modern_ca.school_id
            LEFT JOIN classes c_current ON modern_ca.class_id = c_current.classID AND modern_ca.school_id = c_current.school_id
            LEFT JOIN classallocation legacy_ca ON s.AdmNo = legacy_ca.AdmNo AND s.school_id = legacy_ca.school_id
            LEFT JOIN classes c_legacy ON legacy_ca.classID = c_legacy.classID AND legacy_ca.school_id = c_legacy.school_id
            WHERE s.school_id = %s AND (s.route_id IS NULL OR s.route_id = 0) AND (s.blocked = 'NO' OR s.blocked IS NULL)
            GROUP BY s.AdmNo ORDER BY s.FName, s.SName
        """
        self.cursor.execute(query, (self.school_id,))
        return self.cursor.fetchall()

    @audit_log('assign_student_transport')
    def assign_student_transport(self, admno: int, route_id: int, user_id: int):
        self._assert_route_belongs_to_school(route_id)
        self.cursor.execute("SELECT AdmNo FROM studentinfo WHERE AdmNo = %s AND school_id = %s", (admno, self.school_id))
        if not self.cursor.fetchone():
            raise ValueError("Student not found for active school.")

        # Update student route and category to Transport
        self.cursor.execute("UPDATE studentinfo SET route_id = %s, category = 'Transport' WHERE AdmNo = %s AND school_id = %s", (route_id, admno, self.school_id))

        # Get route details
        self.cursor.execute("SELECT name, amount FROM transport_routes WHERE id = %s AND school_id = %s", (route_id, self.school_id))
        route_data = self.cursor.fetchone()
        if route_data and route_data.get('amount', 0) > 0:
            # Check/Create Transport votehead
            self.cursor.execute("SELECT id FROM fee_voteheads WHERE name = 'Transport' AND school_id = %s", (self.school_id,))
            vh = self.cursor.fetchone()
            if vh:
                votehead_id = vh['id']
            else:
                self.cursor.execute("INSERT INTO fee_voteheads (name, description, school_id) VALUES ('Transport', 'Standard Transport Charges', %s)", (self.school_id,))
                votehead_id = self.cursor.lastrowid

            # Get active academic year & term
            self.cursor.execute("SELECT id FROM academic_years WHERE is_current = TRUE AND school_id = %s LIMIT 1", (self.school_id,))
            ay = self.cursor.fetchone()
            self.cursor.execute("SELECT id FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date AND school_id = %s LIMIT 1", (self.school_id,))
            ut = self.cursor.fetchone()

            if ay and ut:
                from blueprints.fees.services import FeesService
                fees_service = FeesService(self.connection, school_id=self.school_id)
                fees_service.invoice_student(
                    admno=admno,
                    year_id=ay['id'],
                    term_id=ut['id'],
                    structure_id=None,
                    user_id=user_id,
                    custom_items=[{
                        'votehead_id': votehead_id,
                        'votehead_name': 'Transport',
                        'amount': route_data['amount']
                    }]
                )
        self.connection.commit()

    @audit_log('add_route')
    def add_route(self, data: Dict):
        bus_id = data.get('bus_id')
        if bus_id:
            self._assert_bus_belongs_to_school(bus_id)
        self.cursor.execute("""
            INSERT INTO transport_routes (name, amount, description, bus_id, school_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (data['name'], data['amount'], data['description'], bus_id, self.school_id))
        self.connection.commit()

    @audit_log('update_route')
    def update_route(self, route_id: int, data: Dict):
        self._assert_route_belongs_to_school(route_id)
        bus_id = data.get('bus_id')
        if bus_id:
            self._assert_bus_belongs_to_school(bus_id)
        self.cursor.execute("""
            UPDATE transport_routes
            SET name=%s, amount=%s, description=%s, bus_id=%s
            WHERE id=%s AND school_id=%s
        """, (data['name'], data['amount'], data['description'], bus_id, route_id, self.school_id))
        self.connection.commit()

    @audit_log('delete_route')
    def delete_route(self, route_id: int):
        self._assert_route_belongs_to_school(route_id)
        self.cursor.execute("DELETE FROM transport_routes WHERE id = %s AND school_id = %s", (route_id, self.school_id))
        self.connection.commit()
