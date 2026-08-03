import pymysql
from typing import Dict, List, Optional
from decimal import Decimal

from core.tenancy import require_current_school_id


class DashboardService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.school_id = school_id or require_current_school_id()
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)

    def get_summary(self) -> Dict:
        """Return the tenant-scoped totals used by the legacy dashboard cards."""
        self.cursor.execute(
            "SELECT COUNT(*) AS count FROM studentinfo WHERE school_id = %s",
            (self.school_id,),
        )
        total_students = self.cursor.fetchone()['count']

        self.cursor.execute(
            "SELECT COUNT(*) AS count FROM users WHERE school_id = %s",
            (self.school_id,),
        )
        total_staff = self.cursor.fetchone()['count']

        self.cursor.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM fee_collections
            WHERE school_id = %s AND DATE(collection_date) = CURDATE()
            """,
            (self.school_id,),
        )
        today_collections = self.cursor.fetchone()['total']

        return {
            'total_students': total_students,
            'total_staff': total_staff,
            'today_collections': today_collections,
        }

    # ------------------------------------------------------------------
    # 1. Student Statistics
    # ------------------------------------------------------------------
    def get_student_stats(self) -> Dict:
        self.cursor.execute(
            "SELECT COUNT(*) AS total FROM studentinfo WHERE school_id = %s",
            (self.school_id,),
        )
        total = self.cursor.fetchone()['total']

        self.cursor.execute(
            "SELECT COUNT(*) AS total FROM users WHERE school_id = %s",
            (self.school_id,),
        )
        total_staff = self.cursor.fetchone()['total']

        # Student distribution by class (for bar chart)
        self.cursor.execute(
            """
            SELECT c.class_name AS label, COUNT(ca.id) AS value
            FROM classes c
            LEFT JOIN class_allocation ca ON c.classID = ca.class_id
                AND ca.school_id = c.school_id AND ca.is_current = 1
            WHERE c.school_id = %s
            GROUP BY c.classID, c.class_name
            ORDER BY c.class_name
            """,
            (self.school_id,),
        )
        by_class = self.cursor.fetchall()

        return {
            'total_students': total,
            'total_staff': total_staff,
            'by_class': by_class,
        }

    # ------------------------------------------------------------------
    # 2. Financial Summary
    # ------------------------------------------------------------------
    def get_financial_summary(self, term_start: str = None, term_end: str = None) -> Dict:
        # Today's fee collections
        self.cursor.execute(
            """SELECT COALESCE(SUM(amount), 0) AS total
               FROM fee_payments
               WHERE school_id = %s AND payment_date = CURDATE() AND status = 'COMPLETED'""",
            (self.school_id,),
        )
        today_collected = float(self.cursor.fetchone()['total'] or 0)

        # Term collections
        term_collected = 0.0
        if term_start and term_end:
            self.cursor.execute(
                """SELECT COALESCE(SUM(amount), 0) AS total
                   FROM fee_payments
                   WHERE school_id = %s AND payment_date BETWEEN %s AND %s
                     AND status = 'COMPLETED'""",
                (self.school_id, term_start, term_end),
            )
            term_collected = float(self.cursor.fetchone()['total'] or 0)

        # Total outstanding (latest balance per student)
        self.cursor.execute(
            """SELECT COALESCE(SUM(fl.balance_after), 0) AS total
               FROM fee_ledger fl
               WHERE fl.school_id = %s
                 AND fl.id IN (SELECT MAX(id) FROM fee_ledger WHERE school_id = %s GROUP BY admno)""",
            (self.school_id, self.school_id),
        )
        total_outstanding = float(self.cursor.fetchone()['total'] or 0)

        # Collection rate
        total_billed = total_outstanding + term_collected
        collection_rate = round((term_collected / total_billed * 100), 1) if total_billed > 0 else 0.0

        # Recent payments (last 5)
        self.cursor.execute(
            """SELECT fp.amount, fp.payment_mode, fp.payment_date, fp.reference_number,
                      si.name AS student_name, si.AdmNo
               FROM fee_payments fp
               JOIN studentinfo si ON fp.admno = si.AdmNo AND fp.school_id = si.school_id
               WHERE fp.school_id = %s AND fp.status = 'COMPLETED'
               ORDER BY fp.created_at DESC LIMIT 5""",
            (self.school_id,),
        )
        recent_payments = self.cursor.fetchall()

        return {
            'today_collected': today_collected,
            'term_collected': term_collected,
            'total_outstanding': total_outstanding,
            'collection_rate': collection_rate,
            'recent_payments': recent_payments,
        }

    # ------------------------------------------------------------------
    # 3. Fee Collection Trend (30 days)
    # ------------------------------------------------------------------
    def get_fee_trend(self, days: int = 30) -> List[Dict]:
        self.cursor.execute(
            """SELECT DATE(payment_date) AS date, COALESCE(SUM(amount), 0) AS amount
               FROM fee_payments
               WHERE school_id = %s AND payment_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                 AND status = 'COMPLETED'
               GROUP BY DATE(payment_date)
               ORDER BY date""",
            (self.school_id, days),
        )
        rows = self.cursor.fetchall()
        return [{'date': str(r['date']), 'amount': float(r['amount'])} for r in rows]

    # ------------------------------------------------------------------
    # 4. Attendance Today
    # ------------------------------------------------------------------
    def get_attendance_today(self) -> Dict:
        self.cursor.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_count,
                 SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_count,
                 SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) AS late_count
               FROM student_attendance
               WHERE school_id = %s AND attendance_date = CURDATE()""",
            (self.school_id,),
        )
        row = self.cursor.fetchone()
        total = row['total'] or 0
        present = row['present_count'] or 0
        absent = row['absent_count'] or 0
        late = row['late_count'] or 0
        pct = round((present + late) / total * 100, 1) if total > 0 else 0.0

        # Lowest attending class today
        self.cursor.execute(
            """SELECT c.class_name,
                      COUNT(*) AS total,
                      SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) AS absent_cnt
               FROM student_attendance a
               JOIN classes c ON a.class_id = c.classID AND a.school_id = c.school_id
               WHERE a.school_id = %s AND a.attendance_date = CURDATE()
               GROUP BY a.class_id
               HAVING absent_cnt > 0
               ORDER BY (absent_cnt / total) DESC
               LIMIT 1""",
            (self.school_id,),
        )
        worst = self.cursor.fetchone()
        lowest_class = worst['class_name'] if worst else None

        return {
            'total': total,
            'present': present,
            'absent': absent,
            'late': late,
            'attendance_pct': pct,
            'lowest_class': lowest_class,
        }

    # ------------------------------------------------------------------
    # 5. Alerts
    # ------------------------------------------------------------------
    def get_alerts(self) -> Dict:
        # Students with fee arrears (balance > 0)
        self.cursor.execute(
            """SELECT si.AdmNo, si.name AS student_name, fl.balance_after AS balance
               FROM fee_ledger fl
               JOIN studentinfo si ON fl.admno = si.AdmNo AND fl.school_id = si.school_id
               WHERE fl.school_id = %s
                 AND fl.id IN (SELECT MAX(id) FROM fee_ledger WHERE school_id = %s GROUP BY admno)
                 AND fl.balance_after > 0
               ORDER BY fl.balance_after DESC LIMIT 10""",
            (self.school_id, self.school_id),
        )
        arrears_students = self.cursor.fetchall()

        # Missing exam marks count — exams with classes assigned but no marks
        self.cursor.execute(
            """SELECT COUNT(DISTINCT ec.id) AS cnt
               FROM exam_classes ec
               JOIN exam_series es ON ec.exam_id = es.id AND ec.school_id = es.school_id
               LEFT JOIN exam_marks em ON em.exam_id = ec.exam_id AND em.school_id = ec.school_id
               WHERE ec.school_id = %s AND es.is_active = 1 AND em.id IS NULL""",
            (self.school_id,),
        )
        missing_row = self.cursor.fetchone()
        missing_marks = missing_row['cnt'] if missing_row else 0

        warnings = []
        if len(arrears_students) >= 10:
            warnings.append('10+ students have outstanding fee balances')
        if missing_marks > 0:
            warnings.append(f'{missing_marks} exam class(es) have no marks entered')

        return {
            'arrears_students': arrears_students,
            'missing_marks_count': missing_marks,
            'warnings': warnings,
        }

    # ------------------------------------------------------------------
    # 6. Activity Feed
    # ------------------------------------------------------------------
    def get_activity_feed(self, limit: int = 15) -> List[Dict]:
        self.cursor.execute(
            """(
                SELECT fp.created_at AS ts, 'fee_payment' AS type,
                       CONCAT(si.name, ' paid ', fp.payment_mode) AS description,
                       fp.amount
                FROM fee_payments fp
                JOIN studentinfo si ON fp.admno = si.AdmNo AND fp.school_id = si.school_id
                WHERE fp.school_id = %s AND fp.status = 'COMPLETED'
                ORDER BY fp.created_at DESC LIMIT %s
              )
              UNION ALL
              (
                SELECT ur.created_at AS ts, 'uniform' AS type,
                       CONCAT(si.name, ' — uniform receipt') AS description,
                       ur.total_amount AS amount
                FROM uniform_receipts ur
                JOIN studentinfo si ON ur.student_admno = si.AdmNo AND ur.school_id = si.school_id
                WHERE ur.school_id = %s
                ORDER BY ur.created_at DESC LIMIT %s
              )
              UNION ALL
              (
                SELECT fv.created_at AS ts, 'fuel_voucher' AS type,
                       CONCAT(b.reg_no, ' — fuel voucher') AS description,
                       fv.total_cost AS amount
                FROM fuel_vouchers fv
                JOIN buses b ON fv.bus_id = b.id AND fv.school_id = b.school_id
                WHERE fv.school_id = %s
                ORDER BY fv.created_at DESC LIMIT %s
              )
              ORDER BY ts DESC LIMIT %s""",
            (self.school_id, limit,
             self.school_id, limit,
             self.school_id, limit,
             limit),
        )
        rows = self.cursor.fetchall()
        return [
            {
                'timestamp': str(r['ts']),
                'type': r['type'],
                'description': r['description'],
                'amount': float(r['amount'] or 0),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 7. Academic Summary
    # ------------------------------------------------------------------
    def get_academic_summary(self) -> Dict:
        # Latest active exam
        self.cursor.execute(
            """SELECT es.id, es.name, es.term
               FROM exam_series es
               WHERE es.school_id = %s AND es.is_active = 1
               ORDER BY es.created_at DESC LIMIT 1""",
            (self.school_id,),
        )
        latest_exam = self.cursor.fetchone()
        if not latest_exam:
            return {'latest_exam': None, 'top_classes': [], 'lowest_classes': [], 'mean_score': 0}

        exam_id = latest_exam['id']

        # Class performance averages for this exam
        self.cursor.execute(
            """SELECT c.class_name, AVG(em.mark) AS avg_mark
               FROM exam_marks em
               JOIN exam_classes ec ON em.exam_id = ec.exam_id AND em.school_id = ec.school_id
               JOIN classes c ON ec.class_id = c.classID AND ec.school_id = c.school_id
               WHERE em.exam_id = %s AND em.school_id = %s AND em.mark IS NOT NULL
               GROUP BY ec.class_id
               ORDER BY avg_mark DESC""",
            (exam_id, self.school_id),
        )
        by_class = self.cursor.fetchall()
        top_classes = by_class[:3]
        lowest_classes = by_class[-3:] if len(by_class) > 3 else by_class[::-1][:3]

        # Overall mean
        self.cursor.execute(
            """SELECT AVG(mark) AS mean_score
               FROM exam_marks
               WHERE exam_id = %s AND school_id = %s AND mark IS NOT NULL""",
            (exam_id, self.school_id),
        )
        mean_row = self.cursor.fetchone()
        mean_score = round(float(mean_row['mean_score'] or 0), 1)

        return {
            'latest_exam': latest_exam,
            'top_classes': [{'class_name': r['class_name'], 'avg_mark': round(float(r['avg_mark']), 1)} for r in top_classes],
            'lowest_classes': [{'class_name': r['class_name'], 'avg_mark': round(float(r['avg_mark']), 1)} for r in lowest_classes],
            'mean_score': mean_score,
        }

    # ------------------------------------------------------------------
    # 8. Fleet Summary
    # ------------------------------------------------------------------
    def get_fleet_summary(self) -> Dict:
        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM buses WHERE school_id = %s",
            (self.school_id,),
        )
        active_buses = self.cursor.fetchone()['cnt']

        # Fuel cost today
        self.cursor.execute(
            """SELECT COALESCE(SUM(total_cost), 0) AS total
               FROM fuel_vouchers
               WHERE school_id = %s AND DATE(date_issued) = CURDATE()""",
            (self.school_id,),
        )
        fuel_today = float(self.cursor.fetchone()['total'] or 0)

        # Vehicles due for service (last service > 90 days ago or never serviced)
        self.cursor.execute(
            """SELECT COUNT(DISTINCT b.id) AS cnt
               FROM buses b
               LEFT JOIN (
                   SELECT bus_id, MAX(service_date) AS last_service
                   FROM bus_services WHERE school_id = %s
                   GROUP BY bus_id
               ) ls ON b.id = ls.bus_id
               WHERE b.school_id = %s
                 AND (ls.last_service IS NULL OR ls.last_service < DATE_SUB(CURDATE(), INTERVAL 90 DAY))""",
            (self.school_id, self.school_id),
        )
        due_for_service = self.cursor.fetchone()['cnt']

        return {
            'active_buses': active_buses,
            'fuel_today': fuel_today,
            'due_for_service': due_for_service,
        }

    # ------------------------------------------------------------------
    # 9. Finance Overview (GL-based)
    # ------------------------------------------------------------------
    def get_finance_overview(self) -> Dict:
        # Monthly income
        self.cursor.execute(
            """SELECT COALESCE(SUM(le.credit - le.debit), 0) AS total
               FROM finance_ledger_entries le
               JOIN finance_accounts a ON le.account_id = a.id AND le.school_id = a.school_id
               JOIN finance_transactions t ON le.transaction_id = t.id AND le.school_id = t.school_id
               WHERE le.school_id = %s AND a.type = 'INCOME'
                 AND t.transaction_date >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')""",
            (self.school_id,),
        )
        monthly_income = float(self.cursor.fetchone()['total'] or 0)

        # Monthly expenses
        self.cursor.execute(
            """SELECT COALESCE(SUM(le.debit - le.credit), 0) AS total
               FROM finance_ledger_entries le
               JOIN finance_accounts a ON le.account_id = a.id AND le.school_id = a.school_id
               JOIN finance_transactions t ON le.transaction_id = t.id AND le.school_id = t.school_id
               WHERE le.school_id = %s AND a.type = 'EXPENSE'
                 AND t.transaction_date >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')""",
            (self.school_id,),
        )
        monthly_expenses = float(self.cursor.fetchone()['total'] or 0)

        # Cash on hand
        self.cursor.execute(
            """SELECT COALESCE(SUM(le.debit - le.credit), 0) AS balance
               FROM finance_ledger_entries le
               JOIN finance_accounts a ON le.account_id = a.id AND le.school_id = a.school_id
               WHERE le.school_id = %s AND (a.name LIKE '%%Bank%%' OR a.name LIKE '%%Cash%%')""",
            (self.school_id,),
        )
        cash_on_hand = float(self.cursor.fetchone()['balance'] or 0)

        # Pending vouchers
        self.cursor.execute(
            """SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total
               FROM finance_payment_vouchers
               WHERE school_id = %s AND status != 'PAID'""",
            (self.school_id,),
        )
        pv = self.cursor.fetchone()

        return {
            'monthly_income': monthly_income,
            'monthly_expenses': monthly_expenses,
            'cash_on_hand': cash_on_hand,
            'pending_vouchers_count': pv['cnt'],
            'pending_vouchers_amount': float(pv['total'] or 0),
        }

    # ------------------------------------------------------------------
    # 10. Operations (vouchers / uniforms / classes counts)
    # ------------------------------------------------------------------
    def get_operations_stats(self, term_start: str = None, term_end: str = None) -> Dict:
        # Fuel vouchers issued today
        self.cursor.execute(
            """SELECT COUNT(*) AS cnt FROM fuel_vouchers
               WHERE school_id = %s AND DATE(date_issued) = CURDATE()""",
            (self.school_id,),
        )
        vouchers_today = self.cursor.fetchone()['cnt']

        # Uniform receipts this term
        uniform_term = 0
        if term_start and term_end:
            self.cursor.execute(
                """SELECT COUNT(*) AS cnt FROM uniform_receipts
                   WHERE school_id = %s AND DATE(created_at) BETWEEN %s AND %s""",
                (self.school_id, term_start, term_end),
            )
            uniform_term = self.cursor.fetchone()['cnt']

        # Active classes
        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM classes WHERE school_id = %s",
            (self.school_id,),
        )
        total_classes = self.cursor.fetchone()['cnt']

        return {
            'vouchers_today': vouchers_today,
            'uniform_term': uniform_term,
            'total_classes': total_classes,
        }

    # ------------------------------------------------------------------
    # 11. Upcoming Events
    # ------------------------------------------------------------------
    def get_upcoming_events(self, limit: int = 10) -> List[Dict]:
        self.cursor.execute(
            """SELECT id, title, description, event_date, end_date, event_type
               FROM school_events
               WHERE school_id = %s AND event_date >= CURDATE()
               ORDER BY event_date ASC LIMIT %s""",
            (self.school_id, limit),
        )
        rows = self.cursor.fetchall()
        return [
            {**r, 'event_date': str(r['event_date']), 'end_date': str(r['end_date']) if r['end_date'] else None}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 12. Events CRUD
    # ------------------------------------------------------------------
    def add_event(self, title: str, event_date: str, event_type: str = 'other',
                  description: str = None, end_date: str = None, created_by: int = None) -> int:
        self.cursor.execute(
            """INSERT INTO school_events (school_id, title, description, event_date, end_date, event_type, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (self.school_id, title, description, event_date, end_date or None, event_type, created_by),
        )
        self.connection.commit()
        return self.cursor.lastrowid

    def delete_event(self, event_id: int):
        self.cursor.execute(
            "DELETE FROM school_events WHERE id = %s AND school_id = %s",
            (event_id, self.school_id),
        )
        self.connection.commit()

    # ------------------------------------------------------------------
    # Master: Collect all dashboard data in one call
    # ------------------------------------------------------------------
    def get_full_dashboard(self, term_start: str = None, term_end: str = None) -> Dict:
        """Collect all dashboard sections. Each section is isolated so a
        single query failure doesn't break the entire dashboard."""
        data = {}

        sections = [
            ('students', lambda: self.get_student_stats()),
            ('financial', lambda: self.get_financial_summary(term_start, term_end)),
            ('fee_trend', lambda: self.get_fee_trend(30)),
            ('attendance', lambda: self.get_attendance_today()),
            ('alerts', lambda: self.get_alerts()),
            ('activity', lambda: self.get_activity_feed(15)),
            ('academic', lambda: self.get_academic_summary()),
            ('fleet', lambda: self.get_fleet_summary()),
            ('finance', lambda: self.get_finance_overview()),
            ('operations', lambda: self.get_operations_stats(term_start, term_end)),
            ('events', lambda: self.get_upcoming_events(10)),
        ]

        for key, fn in sections:
            try:
                data[key] = fn()
            except Exception:
                data[key] = {}

        return data