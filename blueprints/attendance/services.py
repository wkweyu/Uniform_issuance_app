from datetime import date

from core.tenancy import require_current_school_id


ALLOWED_ATTENDANCE_STATUSES = ('present', 'absent', 'late', 'excused')


class AttendanceService:
    def __init__(self, connection, school_id=None):
        self.connection = connection
        self.school_id = school_id or require_current_school_id()

    def get_classes(self):
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT classID, display_name
            FROM classes
            WHERE is_active = TRUE AND school_id = %s
            ORDER BY display_name
            """,
            (self.school_id,),
        )
        return cursor.fetchall()

    def _assert_class_belongs_to_school(self, class_id):
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT classID, display_name FROM classes WHERE classID = %s AND school_id = %s LIMIT 1",
            (class_id, self.school_id),
        )
        class_row = cursor.fetchone()
        if not class_row:
            raise ValueError('Class not found for the active school.')
        return class_row

    def get_class_attendance_register(self, class_id, attendance_date):
        self._assert_class_belongs_to_school(class_id)
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                s.AdmNo AS student_id,
                CONCAT(COALESCE(s.FName, ''), ' ', COALESCE(s.MName, ''), ' ', COALESCE(s.SName, '')) AS full_name,
                COALESCE(a.status, 'present') AS status,
                COALESCE(a.remarks, '') AS remarks
            FROM class_allocation ca
            JOIN studentinfo s
              ON ca.student_id = s.AdmNo
             AND ca.school_id = s.school_id
            JOIN classes c
              ON ca.class_id = c.classID
             AND ca.school_id = c.school_id
                        LEFT JOIN student_attendance a
              ON a.student_id = s.AdmNo
             AND a.class_id = ca.class_id
             AND a.attendance_date = %s
             AND a.school_id = s.school_id
            WHERE ca.class_id = %s
              AND ca.is_current = TRUE
              AND ca.school_id = %s
            ORDER BY s.FName, s.MName, s.SName, s.AdmNo
            """,
            (attendance_date, class_id, self.school_id),
        )
        return cursor.fetchall()

    def record_attendance(self, class_id, attendance_date, records, user_id):
        if not records:
            raise ValueError('Attendance records are required.')

        self._assert_class_belongs_to_school(class_id)

        normalized_records = []
        for record in records:
            status = (record.get('status') or '').strip().lower()
            if status not in ALLOWED_ATTENDANCE_STATUSES:
                raise ValueError(f"Invalid attendance status: {status or 'blank'}")
            try:
                student_id = int(record.get('student_id'))
            except (TypeError, ValueError):
                raise ValueError('student_id must be a valid integer.')
            normalized_records.append(
                {
                    'student_id': student_id,
                    'status': status,
                    'remarks': (record.get('remarks') or '').strip(),
                }
            )

        student_ids = [record['student_id'] for record in normalized_records]
        placeholders = ', '.join(['%s'] * len(student_ids))
        cursor = self.connection.cursor()
        cursor.execute(
            f"""
            SELECT student_id
            FROM class_allocation
            WHERE class_id = %s
              AND is_current = TRUE
              AND school_id = %s
              AND student_id IN ({placeholders})
            """,
            [class_id, self.school_id, *student_ids],
        )
        allowed_student_ids = {row['student_id'] for row in cursor.fetchall()}
        if allowed_student_ids != set(student_ids):
            raise ValueError('One or more students do not belong to the selected class for the active school.')

        self.connection.begin()
        try:
            for record in normalized_records:
                cursor.execute(
                    """
                    SELECT id, status
                                        FROM student_attendance
                    WHERE class_id = %s
                      AND student_id = %s
                      AND attendance_date = %s
                      AND school_id = %s
                    LIMIT 1
                    """,
                    (class_id, record['student_id'], attendance_date, self.school_id),
                )
                existing = cursor.fetchone()

                if existing:
                    cursor.execute(
                        """
                        UPDATE student_attendance
                        SET status = %s,
                            remarks = %s,
                            recorded_by = %s,
                            updated_at = NOW()
                        WHERE id = %s AND school_id = %s
                        """,
                        (record['status'], record['remarks'], user_id, existing['id'], self.school_id),
                    )
                    attendance_id = existing['id']
                    action = 'updated'
                    old_status = existing['status']
                else:
                    cursor.execute(
                        """
                        INSERT INTO student_attendance (school_id, class_id, student_id, attendance_date, status, remarks, recorded_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            self.school_id,
                            class_id,
                            record['student_id'],
                            attendance_date,
                            record['status'],
                            record['remarks'],
                            user_id,
                        ),
                    )
                    attendance_id = cursor.lastrowid
                    action = 'created'
                    old_status = None

                cursor.execute(
                    """
                    INSERT INTO student_attendance_logs (
                        school_id,
                        attendance_id,
                        class_id,
                        student_id,
                        attendance_date,
                        action,
                        old_status,
                        new_status,
                        remarks,
                        changed_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.school_id,
                        attendance_id,
                        class_id,
                        record['student_id'],
                        attendance_date,
                        action,
                        old_status,
                        record['status'],
                        record['remarks'],
                        user_id,
                    ),
                )

            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def get_attendance_summary(self, start_date, end_date, class_id=None):
        cursor = self.connection.cursor()
        params = [self.school_id, start_date, end_date]
        filters = ''
        if class_id is not None:
            self._assert_class_belongs_to_school(class_id)
            filters = ' AND a.class_id = %s'
            params.append(class_id)

        cursor.execute(
            f"""
            SELECT
                a.attendance_date,
                c.display_name AS class_name,
                a.status,
                COUNT(*) AS total_students
                        FROM student_attendance a
            JOIN classes c
              ON a.class_id = c.classID
             AND a.school_id = c.school_id
            WHERE a.school_id = %s
              AND a.attendance_date BETWEEN %s AND %s
              {filters}
            GROUP BY a.attendance_date, c.display_name, a.status
            ORDER BY a.attendance_date DESC, c.display_name ASC, a.status ASC
            """,
            params,
        )
        return cursor.fetchall()

    def get_recent_attendance_summary(self, limit_days=7):
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                a.attendance_date,
                COUNT(*) AS total_records,
                SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) AS absent_count,
                SUM(CASE WHEN a.status = 'late' THEN 1 ELSE 0 END) AS late_count
                        FROM student_attendance a
            WHERE a.school_id = %s
              AND a.attendance_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            GROUP BY a.attendance_date
            ORDER BY a.attendance_date DESC
            """,
            (self.school_id, limit_days),
        )
        return cursor.fetchall()


def default_attendance_date():
    return date.today().isoformat()