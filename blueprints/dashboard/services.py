import pymysql
from typing import Dict, Optional

from core.tenancy import require_current_school_id


class DashboardService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.school_id = school_id or require_current_school_id()
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)

    def get_summary(self) -> Dict:
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