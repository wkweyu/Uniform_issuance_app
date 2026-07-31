from datetime import datetime
from flask import g, current_app
from core.audit import audit_log
from core.tenancy import require_current_school_id

class StudentService:
    def __init__(self, connection, school_id=None):
        self.connection = connection
        self.school_id = school_id or require_current_school_id()

    @staticmethod
    def _has_reference(value):
        return value not in (None, '', 0, '0')

    def get_classes(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE AND school_id = %s ORDER BY display_name", (self.school_id,))
        return cursor.fetchall()

    def get_transport_routes(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT id, name, amount FROM transport_routes WHERE is_active = TRUE AND school_id = %s ORDER BY name", (self.school_id,))
        return cursor.fetchall()

    def search_students(self, query, limit=15):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT si.AdmNo, si.FName, si.SName, c.display_name as class_name
            FROM studentinfo si
                        LEFT JOIN class_allocation ca ON si.AdmNo = ca.student_id AND ca.is_current = TRUE AND si.school_id = ca.school_id
                        LEFT JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            WHERE (si.AdmNo LIKE %s OR si.FName LIKE %s OR si.SName LIKE %s)
              AND si.school_id = %s
            LIMIT %s
        """, (f"%{query}%", f"%{query}%", f"%{query}%", self.school_id, limit))
        return cursor.fetchall()

    def get_student_by_admno(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT s.*,
                   p.pName as parent_name,
                   p.phone1 as parent_phone,
                   p.email as parent_email,
                   p.address as home_address,
                   p.hometown as residency,
                     p.nationalID as parent_id,
                     sg.name as student_group_name
            FROM studentinfo s
            LEFT JOIN parentinfo p ON s.AdmNo = p.admno AND s.school_id = p.school_id
                 LEFT JOIN student_groups sg ON s.student_group_id = sg.id AND s.school_id = sg.school_id
            WHERE s.AdmNo = %s AND s.school_id = %s
        """, (admno, self.school_id))
        return cursor.fetchone()

    def get_admission_form_profile(self, admno):
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                s.*,
                CONCAT(COALESCE(s.FName, ''), ' ', COALESCE(s.MName, ''), ' ', COALESCE(s.SName, '')) as Fullname,
                c.display_name as class_name,
                tr.name as route_name,
                tr.amount as route_amount
            FROM studentinfo s
            LEFT JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE AND s.school_id = ca.school_id
            LEFT JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            LEFT JOIN transport_routes tr ON s.route_id = tr.id AND s.school_id = tr.school_id
            WHERE s.AdmNo = %s AND s.school_id = %s
            """,
            (admno, self.school_id),
        )
        return cursor.fetchone()

    def get_parent_contact_for_student(self, admno, parent_id=None):
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT pName, phone1, phone2, email, address, hometown
            FROM parentinfo WHERE admno = %s AND school_id = %s
            """,
            (admno, self.school_id),
        )
        parent = cursor.fetchone()
        if parent or not parent_id:
            return parent

        cursor.execute(
            "SELECT pName, phone1, phone2, email, address, hometown FROM parentinfo WHERE parentid = %s AND school_id = %s LIMIT 1",
            (parent_id, self.school_id),
        )
        return cursor.fetchone()

    def get_sibling_profiles(self, parent_id, admno):
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
                s.AdmNo,
                CONCAT(COALESCE(s.FName, ''), ' ', COALESCE(s.SName, '')) as Fullname,
                c.display_name as class_name
            FROM studentinfo s
            LEFT JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE AND s.school_id = ca.school_id
            LEFT JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            WHERE s.parentID = %s AND s.AdmNo != %s AND s.school_id = %s
            """,
            (parent_id, admno, self.school_id),
        )
        return cursor.fetchall()

    def check_admno_exists(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("SELECT AdmNo FROM studentinfo WHERE AdmNo = %s AND school_id = %s", (admno, self.school_id))
        return cursor.fetchone() is not None

    def _assert_student_belongs_to_school(self, admno):
        if not self.check_admno_exists(admno):
            raise ValueError("Student not found for the active school.")

    def _assert_class_belongs_to_school(self, class_id):
        if not self._has_reference(class_id):
            raise ValueError("Class is required.")
        class_data = self.get_class_details(class_id)
        if not class_data:
            raise ValueError("Class not found for the active school.")
        return class_data

    def _assert_academic_year_belongs_to_school(self, academic_year_id):
        if not self._has_reference(academic_year_id):
            raise ValueError("Academic year is required.")
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id FROM academic_years WHERE id = %s AND school_id = %s",
            (academic_year_id, self.school_id),
        )
        if not cursor.fetchone():
            raise ValueError("Academic year not found for the active school.")

    def _assert_class_matches_academic_year(self, class_id, academic_year_id):
        class_data = self._assert_class_belongs_to_school(class_id)
        self._assert_academic_year_belongs_to_school(academic_year_id)
        if class_data.get('academic_year_id') != academic_year_id:
            raise ValueError("Academic year does not match the selected class.")
        return class_data

    def _assert_route_belongs_to_school(self, route_id):
        if not self._has_reference(route_id):
            return
        if not self.get_transport_route_by_id(route_id):
            raise ValueError("Transport route not found for the active school.")

    def _assert_student_group_belongs_to_school(self, student_group_id):
        if not self._has_reference(student_group_id):
            return
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id FROM student_groups WHERE id = %s AND school_id = %s",
            (student_group_id, self.school_id),
        )
        if not cursor.fetchone():
            raise ValueError("Student group not found for the active school.")

    def _assert_class_allocation_belongs_to_school(self, allocation_id):
        if not self._has_reference(allocation_id):
            raise ValueError("Class allocation is required.")
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id FROM class_allocation WHERE id = %s AND school_id = %s",
            (allocation_id, self.school_id),
        )
        if not cursor.fetchone():
            raise ValueError("Class allocation not found for the active school.")

    def _sync_legacy_classallocation(self, cursor, admno, class_id, academic_year_id):
        if not self._has_reference(academic_year_id):
            return
        cursor.execute(
            "SELECT allocationID FROM classallocation WHERE AdmNo = %s AND thisYear = %s AND school_id = %s",
            (admno, academic_year_id, self.school_id),
        )
        allocation = cursor.fetchone()

        if allocation:
            cursor.execute(
                "UPDATE classallocation SET classID = %s WHERE allocationID = %s AND school_id = %s",
                (class_id, allocation['allocationID'], self.school_id),
            )
        else:
            cursor.execute(
                "INSERT INTO classallocation (AdmNo, classID, thisYear, AllcDate, school_id) VALUES (%s, %s, %s, NOW(), %s)",
                (admno, class_id, academic_year_id, self.school_id),
            )

    def get_parent_by_phone(self, phone):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT parentid FROM parentinfo
            WHERE phone1 = %s AND school_id = %s
            ORDER BY _date DESC LIMIT 1
        """, (phone, self.school_id))
        return cursor.fetchone()

    def get_next_parent_id(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT COALESCE(MAX(parentid), 0) + 1 as next_id FROM parentinfo WHERE school_id = %s", (self.school_id,))
        return cursor.fetchone()['next_id']

    @audit_log('admit_student')
    def admit_student(self, student_data, parent_data, class_id, academic_year_id):
        self._assert_class_matches_academic_year(class_id, academic_year_id)
        self._assert_route_belongs_to_school(student_data.get('route_id'))
        self._assert_student_group_belongs_to_school(student_data.get('student_group_id'))

        cursor = self.connection.cursor()
        self.connection.begin()
        try:
            # Handle Parent
            final_parent_id = 0
            if parent_data.get('phone1'):
                existing_parent = self.get_parent_by_phone(parent_data['phone1'])
                if existing_parent:
                    final_parent_id = existing_parent['parentid']

            if final_parent_id == 0:
                final_parent_id = self.get_next_parent_id()

            # Insert student
            cursor.execute("""
                INSERT INTO studentinfo (
                    AdmNo, parentID, FName, MName, SName, Sex, DoB, birth, Religion,
                    boarding, category, route_id, alt_contact, stream, blocked, Date_Adm, student_group_id, school_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, NOW(), %s, %s)
            """, (
                student_data['admno'], final_parent_id, student_data['fname'], student_data['mname'],
                student_data['lname'], student_data['gender'], student_data['dob'], student_data['birth_cert'],
                student_data['religion'], student_data['boarding'], student_data['category'],
                student_data.get('route_id'), student_data['alt_contact'], student_data['stream'],
                student_data.get('student_group_id'), self.school_id
            ))

            # Parent Info
            if parent_data.get('pName'):
                cursor.execute(
                    "SELECT parentid FROM parentinfo WHERE admno = %s AND school_id = %s LIMIT 1",
                    (student_data['admno'], self.school_id)
                )
                existing_parent = cursor.fetchone()
                if existing_parent:
                    cursor.execute("""
                        UPDATE parentinfo
                        SET pName = %s, phone1 = %s, email = %s, nationalID = %s, address = %s, hometown = %s
                        WHERE admno = %s AND school_id = %s
                    """, (
                        parent_data['pName'], parent_data['phone1'], parent_data['email'],
                        parent_data['nationalID'], parent_data['address'], parent_data['hometown'],
                        student_data['admno'], self.school_id
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO parentinfo (parentid, admno, pName, phone1, email, nationalID, address, hometown, regDate, school_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                    """, (
                        final_parent_id, student_data['admno'], parent_data['pName'], parent_data['phone1'],
                        parent_data['email'], parent_data['nationalID'], parent_data['address'],
                        parent_data['hometown'], self.school_id
                    ))

            # Class Allocation
            self._sync_legacy_classallocation(cursor, student_data['admno'], class_id, academic_year_id)
            cursor.execute("""
                INSERT INTO class_allocation (student_id, class_id, academic_year_id, school_id, allocation_date, is_current)
                VALUES (%s, %s, %s, %s, NOW(), TRUE)
            """, (student_data['admno'], class_id, academic_year_id, self.school_id))

            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise e

    @audit_log('update_student')
    def update_student(self, admno, student_data, parent_data, class_id, academic_year_id):
        self._assert_student_belongs_to_school(admno)
        self._assert_class_matches_academic_year(class_id, academic_year_id)
        self._assert_route_belongs_to_school(student_data.get('route_id'))
        self._assert_student_group_belongs_to_school(student_data.get('student_group_id'))

        cursor = self.connection.cursor()
        self.connection.begin()
        try:
            # Update studentinfo
            cursor.execute("""
                UPDATE studentinfo SET
                    FName=%s, MName=%s, SName=%s, Sex=%s, DoB=%s, birth=%s,
                    Religion=%s, category=%s, alt_contact=%s, email=%s,
                    notes=%s, stream=%s, boarding=%s
                WHERE AdmNo = %s AND school_id = %s
            """, (
                student_data['fname'], student_data['mname'], student_data['lname'], student_data['gender'],
                student_data['dob'], student_data['birth_cert'], student_data['religion'],
                student_data['category'], student_data['alt_contact'], student_data['email'],
                student_data['notes'], student_data['stream'], student_data['boarding'],
                admno, self.school_id
            ))

            # Update parentinfo
            if parent_data.get('pName') or parent_data.get('phone1'):
                cursor.execute(
                    "SELECT parentid FROM parentinfo WHERE admno = %s AND school_id = %s LIMIT 1",
                    (admno, self.school_id)
                )
                existing_parent = cursor.fetchone()
                if existing_parent:
                    cursor.execute("""
                        UPDATE parentinfo
                        SET pName = %s, phone1 = %s, email = %s, nationalID = %s, address = %s, hometown = %s
                        WHERE admno = %s AND school_id = %s
                    """, (
                        parent_data['pName'], parent_data['phone1'], parent_data['email'],
                        parent_data['nationalID'], parent_data['address'], parent_data['hometown'],
                        admno, self.school_id
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO parentinfo (admno, pName, phone1, email, nationalID, address, hometown, regDate, parentid, school_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), 0, %s)
                    """, (
                        admno, parent_data['pName'], parent_data['phone1'], parent_data['email'],
                        parent_data['nationalID'], parent_data['address'], parent_data['hometown'], self.school_id
                    ))

            # Sync Class Allocations
            self._sync_legacy_classallocation(cursor, admno, class_id, academic_year_id)

            if academic_year_id:
                cursor.execute("""
                    SELECT id FROM class_allocation
                    WHERE student_id = %s AND academic_year_id = %s AND is_current = TRUE AND school_id = %s
                """, (admno, academic_year_id, self.school_id))
                modern_allocation = cursor.fetchone()

                if modern_allocation:
                    cursor.execute("""
                        UPDATE class_allocation SET class_id = %s WHERE id = %s AND school_id = %s
                    """, (class_id, modern_allocation['id'], self.school_id))
                else:
                    cursor.execute("""
                        INSERT INTO class_allocation (student_id, class_id, academic_year_id, school_id, allocation_date, is_current)
                        VALUES (%s, %s, %s, %s, NOW(), TRUE)
                    """, (admno, class_id, academic_year_id, self.school_id))

            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise e

    def get_students_list(self, query=None, year_cur=None):
        cursor = self.connection.cursor()
        if query:
            if year_cur:
                cursor.execute("""
                    SELECT
                        s.AdmNo, s.FName, s.MName, s.SName AS LName, s.Sex AS Gender, s.blocked AS Status,
                        COALESCE(
                            (SELECT display_name FROM classes WHERE classID = (
                                SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE AND school_id = %s LIMIT 1
                            ) AND school_id = %s LIMIT 1),
                            (SELECT class_name FROM classes WHERE classID = (
                                SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s AND school_id = %s LIMIT 1
                            ) AND school_id = %s LIMIT 1),
                            (SELECT class_name FROM classes WHERE classID = (
                                SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND school_id = %s ORDER BY thisYear DESC LIMIT 1
                            ) AND school_id = %s LIMIT 1)
                        ) AS class_name,
                        COALESCE(
                            (SELECT academic_year_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE AND school_id = %s LIMIT 1),
                            (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s AND school_id = %s LIMIT 1),
                            (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo AND school_id = %s ORDER BY thisYear DESC LIMIT 1)
                        ) AS thisYear
                    FROM studentinfo s
                    WHERE (s.AdmNo LIKE %s OR CONCAT(s.FName, ' ', COALESCE(s.MName, ''), ' ', s.SName) LIKE %s)
                      AND s.school_id = %s
                    ORDER BY s.FName, s.SName LIMIT 200
                """, (self.school_id, self.school_id, year_cur, self.school_id, self.school_id, self.school_id, self.school_id,
                      self.school_id, year_cur, self.school_id, self.school_id,
                      f"%{query}%", f"%{query}%", self.school_id))
            else:
                cursor.execute("""
                    SELECT
                        s.AdmNo, s.FName, s.MName, s.SName AS LName, s.Sex AS Gender, s.blocked AS Status,
                        COALESCE(
                            (SELECT display_name FROM classes WHERE classID = (
                                SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE AND school_id = %s LIMIT 1
                            ) AND school_id = %s LIMIT 1),
                            (SELECT class_name FROM classes WHERE classID = (
                                SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND school_id = %s ORDER BY thisYear DESC LIMIT 1
                            ) AND school_id = %s LIMIT 1)
                        ) AS class_name,
                        COALESCE(
                            (SELECT academic_year_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE AND school_id = %s LIMIT 1),
                            (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo AND school_id = %s ORDER BY thisYear DESC LIMIT 1)
                        ) AS thisYear
                    FROM studentinfo s
                    WHERE (s.AdmNo LIKE %s OR CONCAT(s.FName, ' ', COALESCE(s.MName, ''), ' ', s.SName) LIKE %s)
                      AND s.school_id = %s
                    ORDER BY s.FName, s.SName LIMIT 200
                """, (self.school_id, self.school_id, self.school_id, self.school_id,
                      self.school_id, self.school_id,
                      f"%{query}%", f"%{query}%", self.school_id))
        else:
            if year_cur:
                cursor.execute("""
                    SELECT
                        s.AdmNo, s.FName, s.MName, s.SName AS LName, s.Sex AS Gender, s.blocked AS Status,
                        COALESCE(
                            (SELECT display_name FROM classes WHERE classID = (
                                SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE AND school_id = %s LIMIT 1
                            ) AND school_id = %s LIMIT 1),
                            (SELECT class_name FROM classes WHERE classID = (
                                SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s AND school_id = %s LIMIT 1
                            ) AND school_id = %s LIMIT 1),
                            (SELECT class_name FROM classes WHERE classID = (
                                SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND school_id = %s ORDER BY thisYear DESC LIMIT 1
                            ) AND school_id = %s LIMIT 1)
                        ) AS class_name,
                        COALESCE(
                            (SELECT academic_year_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE AND school_id = %s LIMIT 1),
                            (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s AND school_id = %s LIMIT 1),
                            (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo AND school_id = %s ORDER BY thisYear DESC LIMIT 1)
                        ) AS thisYear
                    FROM studentinfo s
                    WHERE s.school_id = %s
                    ORDER BY s.FName, s.SName LIMIT 20
                """, (self.school_id, self.school_id, year_cur, self.school_id, self.school_id, self.school_id, self.school_id,
                      self.school_id, year_cur, self.school_id, self.school_id,
                      self.school_id))
            else:
                cursor.execute("""
                    SELECT s.AdmNo, s.FName, s.MName, s.SName AS LName, s.Sex AS Gender, s.blocked AS Status,
                           COALESCE(c_current.class_name, c_legacy.class_name) as class_name,
                           COALESCE(c_current.class_group, c_legacy.class_group) as class_group,
                           COALESCE(modern_ca.academic_year_id, legacy_ca.thisYear) as thisYear
                    FROM studentinfo s
                    LEFT JOIN class_allocation modern_ca ON s.AdmNo = modern_ca.student_id AND modern_ca.is_current = TRUE AND s.school_id = modern_ca.school_id
                    LEFT JOIN classes c_current ON modern_ca.class_id = c_current.classID AND modern_ca.school_id = c_current.school_id
                    LEFT JOIN classallocation legacy_ca ON s.AdmNo = legacy_ca.AdmNo AND s.school_id = legacy_ca.school_id
                    LEFT JOIN classes c_legacy ON legacy_ca.classID = c_legacy.classID AND legacy_ca.school_id = c_legacy.school_id
                    WHERE s.school_id = %s
                    ORDER BY modern_ca.allocation_date DESC, legacy_ca.AllcDate DESC, s.FName LIMIT 20
                """, (self.school_id,))
        return cursor.fetchall()

    def get_student_academic_history(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT history.thisYear, history.AllcDate, history.class_name, history.class_group
            FROM (
                SELECT ay.year AS thisYear, ca.allocation_date AS AllcDate, c.class_name, c.class_group
                FROM class_allocation ca
                JOIN academic_years ay ON ca.academic_year_id = ay.id AND ca.school_id = ay.school_id
                JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
                WHERE ca.student_id = %s AND ca.school_id = %s

                UNION ALL

                SELECT a.thisYear AS thisYear, a.AllcDate AS AllcDate, c.class_name, c.class_group
                FROM classallocation a
                JOIN classes c ON a.classID = c.classID AND a.school_id = c.school_id
                WHERE a.AdmNo = %s AND a.school_id = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM class_allocation ca2
                      JOIN academic_years ay2 ON ca2.academic_year_id = ay2.id AND ca2.school_id = ay2.school_id
                      WHERE ca2.student_id = a.AdmNo
                        AND ay2.year = a.thisYear
                        AND ca2.school_id = a.school_id
                  )
            ) history
            ORDER BY history.thisYear DESC, history.AllcDate DESC
        """, (admno, self.school_id, admno, self.school_id))
        return cursor.fetchall()

    def get_uniform_history(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT receipt_no, MAX(issued_on) as issued_on, SUM(total) as total, MAX(issued_by) as issued_by
            FROM uniform_receipts
            WHERE AdmNo = %s AND school_id = %s
            GROUP BY receipt_no
            ORDER BY issued_on DESC
        """, (str(admno), self.school_id))
        return cursor.fetchall()

    def get_enrolled_subjects(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT s.subjName as subject_name, s.code as subject_code, ss.enrollment_date
            FROM student_subjects ss
            JOIN subjects s ON ss.subject_id = s.subjectNo AND ss.school_id = s.school_id
            JOIN class_allocation ca ON ss.class_allocation_id = ca.id AND ss.school_id = ca.school_id
            WHERE ca.student_id = %s AND ca.is_current = TRUE AND s.school_id = %s
        """, (admno, self.school_id))
        return cursor.fetchall()

    def get_siblings(self, phone, current_admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT s.AdmNo, s.FName, s.MName, s.SName as LName,
                   COALESCE(c_current.display_name, c_legacy.class_name) as class_name
            FROM studentinfo s
            JOIN parentinfo p ON s.AdmNo = p.admno AND s.school_id = p.school_id
            LEFT JOIN class_allocation modern_ca ON s.AdmNo = modern_ca.student_id AND modern_ca.is_current = TRUE AND s.school_id = modern_ca.school_id
            LEFT JOIN classes c_current ON modern_ca.class_id = c_current.classID AND modern_ca.school_id = c_current.school_id
            LEFT JOIN classallocation legacy_ca ON s.AdmNo = legacy_ca.AdmNo AND s.school_id = legacy_ca.school_id
            LEFT JOIN classes c_legacy ON legacy_ca.classID = c_legacy.classID AND legacy_ca.school_id = c_legacy.school_id
            WHERE p.phone1 = %s AND s.AdmNo != %s AND s.school_id = %s
            GROUP BY s.AdmNo
        """, (phone, current_admno, self.school_id))
        return cursor.fetchall()

    @audit_log('toggle_student_status')
    def toggle_status(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("SELECT blocked FROM studentinfo WHERE AdmNo = %s AND school_id = %s", (admno, self.school_id))
        row = cursor.fetchone()
        if not row:
            return None
        new_status = 'YES' if row['blocked'] == 'NO' else 'NO'
        cursor.execute("UPDATE studentinfo SET blocked = %s WHERE AdmNo = %s AND school_id = %s", (new_status, admno, self.school_id))
        self.connection.commit()
        return new_status

    def search_parents(self, query):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT DISTINCT parentid, pName, phone1, email, address, hometown, nationalID
            FROM parentinfo
            WHERE (pName LIKE %s OR phone1 LIKE %s OR nationalID LIKE %s)
              AND school_id = %s
            LIMIT 10
        """, (f"%{query}%", f"%{query}%", f"%{query}%", self.school_id))
        return cursor.fetchall()

    def get_parent_info_and_siblings_by_phone(self, phone):
        cursor = self.connection.cursor()
        # 1. Get Siblings
        cursor.execute("""
            SELECT s.AdmNo, s.FName, s.MName, s.SName as LName,
                   COALESCE(c_current.display_name, c_legacy.class_name) as class_name
            FROM studentinfo s
            JOIN parentinfo p ON s.AdmNo = p.admno AND s.school_id = p.school_id
            LEFT JOIN class_allocation modern_ca ON s.AdmNo = modern_ca.student_id AND modern_ca.is_current = TRUE AND s.school_id = modern_ca.school_id
            LEFT JOIN classes c_current ON modern_ca.class_id = c_current.classID AND modern_ca.school_id = c_current.school_id
            LEFT JOIN classallocation legacy_ca ON s.AdmNo = legacy_ca.AdmNo AND s.school_id = legacy_ca.school_id
            LEFT JOIN classes c_legacy ON legacy_ca.classID = c_legacy.classID AND legacy_ca.school_id = c_legacy.school_id
            WHERE p.phone1 = %s AND s.school_id = %s
            GROUP BY s.AdmNo
        """, (phone, self.school_id))
        siblings = cursor.fetchall()

        # 2. Get Parent Info
        cursor.execute("""
            SELECT pName, email, phone1, address, hometown, nationalID
            FROM parentinfo
            WHERE phone1 = %s AND school_id = %s
            ORDER BY regDate DESC LIMIT 1
        """, (phone, self.school_id))
        parent = cursor.fetchone()
        return siblings, parent

    def get_student_class_info(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT
                COALESCE(c_current.class_name, c_legacy.class_name) as class_name,
                COALESCE(c_current.class_group, c_legacy.class_group) as class_group,
                COALESCE(c_current.classID, c_legacy.classID) as classID,
                COALESCE(c_current.stream_code, c_legacy.stream_code, s.stream) as stream,
                COALESCE(modern_ca.academic_year_id, legacy_ca.thisYear) as thisYear
            FROM studentinfo s
            LEFT JOIN class_allocation modern_ca ON s.AdmNo = modern_ca.student_id AND modern_ca.is_current = TRUE AND s.school_id = modern_ca.school_id
            LEFT JOIN classes c_current ON modern_ca.class_id = c_current.classID AND modern_ca.school_id = c_current.school_id
            LEFT JOIN classallocation legacy_ca ON s.AdmNo = legacy_ca.AdmNo AND s.school_id = legacy_ca.school_id
            LEFT JOIN classes c_legacy ON legacy_ca.classID = c_legacy.classID AND legacy_ca.school_id = c_legacy.school_id
            WHERE s.AdmNo = %s AND s.school_id = %s
            ORDER BY modern_ca.allocation_date DESC, legacy_ca.AllcDate DESC LIMIT 1
        """, (admno, self.school_id))
        return cursor.fetchone()

    def get_fee_summary(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT
                (SELECT SUM(amount) FROM fee_ledger WHERE admno = %s AND type = 'CHARGE' AND school_id = %s) as total_billed,
                (SELECT SUM(amount) FROM fee_payments WHERE admno = %s AND status = 'COMPLETED' AND school_id = %s) as total_paid,
                (SELECT balance_after FROM fee_ledger WHERE admno = %s AND school_id = %s ORDER BY id DESC LIMIT 1) as current_balance
        """, (admno, self.school_id, admno, self.school_id, admno, self.school_id))
        return cursor.fetchone()

    def get_payment_history(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT fr.receipt_no as rcptno, fp.id as payment_id, fp.payment_date as date_of_payment,
                   fp.amount as amount_paid, fp.payment_mode, fp.reference_number as chequeNo, fp.status, ay.year as fncYear
            FROM fee_payments fp
            JOIN fee_ledger fl ON fp.ledger_id = fl.id AND fp.school_id = fl.school_id
            JOIN fee_receipts fr ON fp.id = fr.payment_id AND fp.school_id = fr.school_id
            JOIN academic_years ay ON fl.academic_year_id = ay.id AND fl.school_id = ay.school_id
            WHERE fp.admno = %s AND fp.school_id = %s
            ORDER BY fp.payment_date DESC, fp.id DESC
        """, (admno, self.school_id))
        return cursor.fetchall()

    def get_exam_summaries(self, admno):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT e.id as exam_id, e.name as exam_name, e.term, ay.year as academic_year,
                   COUNT(m.id) as subjects_count, SUM(m.mark) as total_marks, AVG(m.mark) as mean_mark
            FROM exam_marks m
            JOIN exam_series e ON m.exam_id = e.id AND m.school_id = e.school_id
            JOIN academic_years ay ON e.academic_year_id = ay.id AND e.school_id = ay.school_id
            WHERE m.student_id = %s AND m.school_id = %s
            GROUP BY e.id, e.name, e.term, ay.year
            ORDER BY ay.year DESC, e.term DESC
        """, (str(admno), self.school_id))
        return cursor.fetchall()

    def get_class_details(self, class_id):
        cursor = self.connection.cursor()
        cursor.execute("SELECT stream_code, academic_year_id FROM classes WHERE classID = %s AND school_id = %s", (class_id, self.school_id))
        return cursor.fetchone()

    def get_transport_route_by_id(self, route_id):
        cursor = self.connection.cursor()
        cursor.execute("SELECT name, amount FROM transport_routes WHERE id = %s AND school_id = %s", (route_id, self.school_id))
        return cursor.fetchone()

    def get_or_create_votehead(self, name, description):
        cursor = self.connection.cursor()
        cursor.execute("SELECT id FROM fee_voteheads WHERE name = %s AND school_id = %s", (name, self.school_id))
        vh_res = cursor.fetchone()
        if vh_res:
            return vh_res['id']
        cursor.execute("INSERT INTO fee_voteheads (name, description, school_id) VALUES (%s, %s, %s)",
                     (name, description, self.school_id))
        return cursor.lastrowid

    def get_current_term_id(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT id FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date AND school_id = %s LIMIT 1", (self.school_id,))
        term_res = cursor.fetchone()
        return term_res['id'] if term_res else None

    @audit_log('bulk_import_students')
    def bulk_import_students(self, data):
        admnos = data.get('admno[]', [])
        fnames = data.get('fname[]', [])
        mnames = data.get('mname[]', [])
        lnames = data.get('lname[]', [])
        genders = data.get('gender[]', [])
        dobs = data.get('dob[]', [])
        religions = data.get('religion[]', [])
        categories = data.get('category[]', [])
        class_ids = data.get('class_id[]', [])
        p_names = data.get('parent_name[]', [])
        p_phones = data.get('parent_phone[]', [])
        p_emails = data.get('parent_email[]', [])
        p_ids = data.get('parent_id_no[]', [])
        p_addresses = data.get('home_address[]', [])
        p_residencies = data.get('residency[]', [])

        success_count = 0
        error_count = 0

        cursor = self.connection.cursor()

        for i in range(len(admnos)):
            admno = admnos[i].strip()
            if not admno:
                continue

            try:
                if self.check_admno_exists(admno):
                    error_count += 1
                    continue

                class_id = class_ids[i]
                if not class_id:
                    error_count += 1
                    continue

                class_info = self.get_class_details(class_id)
                if not class_info:
                    error_count += 1
                    continue

                p_phone = p_phones[i].strip()
                final_parent_id = 0
                if p_phone:
                    existing_p = self.get_parent_by_phone(p_phone)
                    if existing_p:
                        final_parent_id = existing_p['parentid']

                if final_parent_id == 0:
                    final_parent_id = self.get_next_parent_id()

                self.connection.begin()

                cat = categories[i]

                cursor.execute("""
                    INSERT INTO studentinfo (
                        AdmNo, parentID, FName, MName, SName, Sex, DoB, Religion,
                        boarding, category, stream, blocked, Date_Adm, school_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, NOW(), %s)
                """, (
                    admno, final_parent_id, fnames[i], mnames[i], lnames[i],
                    genders[i][:1].upper() if genders[i] else 'M',
                    dobs[i] if dobs[i] else None, religions[i],
                    'YES' if cat == 'Boarding' else 'NO', cat, class_info['stream_code'],
                    self.school_id
                ))

                pn = p_names[i].strip()
                if pn:
                    cursor.execute(
                        "SELECT parentid FROM parentinfo WHERE admno = %s AND school_id = %s LIMIT 1",
                        (admno, self.school_id)
                    )
                    existing_parent = cursor.fetchone()
                    if existing_parent:
                        cursor.execute("""
                            UPDATE parentinfo
                            SET pName = %s, phone1 = %s, email = %s, nationalID = %s, address = %s, hometown = %s
                            WHERE admno = %s AND school_id = %s
                        """, (
                            pn, p_phone, p_emails[i], p_ids[i], p_addresses[i], p_residencies[i], admno, self.school_id
                        ))
                    else:
                        cursor.execute("""
                            INSERT INTO parentinfo (parentid, admno, pName, phone1, email, nationalID, address, hometown, regDate, school_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                        """, (
                            final_parent_id, admno, pn, p_phone, p_emails[i],
                            p_ids[i], p_addresses[i], p_residencies[i], self.school_id
                        ))

                self._sync_legacy_classallocation(cursor, admno, class_id, class_info['academic_year_id'])

                cursor.execute("""
                    INSERT INTO class_allocation (student_id, class_id, academic_year_id, school_id, allocation_date, is_current)
                    VALUES (%s, %s, %s, %s, NOW(), TRUE)
                """, (admno, class_id, class_info['academic_year_id'], self.school_id))

                self.connection.commit()
                success_count += 1

            except Exception as e:
                self.connection.rollback()
                error_count += 1
                current_app.logger.error(f"Error importing {admno}: {str(e)}")

        return success_count, error_count

    def get_students_for_subject_enrollment(self):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT s.AdmNo as admno, CONCAT(s.FName, ' ', s.SName) as full_name, ca.class_id, c.display_name
            FROM studentinfo s
            JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE AND s.school_id = ca.school_id
            JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            WHERE s.blocked = 'NO' AND s.school_id = %s
            ORDER BY s.FName, s.SName
        """, (self.school_id,))
        return cursor.fetchall()

    def search_students_for_subjects(self, query):
        cursor = self.connection.cursor()
        cursor.execute("""
                        SELECT s.AdmNo, s.FName, s.MName, s.SName as LName,
                                     COALESCE(c_current.display_name, c_legacy.class_name) as class_name
                        FROM studentinfo s
                        LEFT JOIN class_allocation modern_ca ON s.AdmNo = modern_ca.student_id AND modern_ca.is_current = TRUE AND s.school_id = modern_ca.school_id
                        LEFT JOIN classes c_current ON modern_ca.class_id = c_current.classID AND modern_ca.school_id = c_current.school_id
                        LEFT JOIN classallocation legacy_ca ON s.AdmNo = legacy_ca.AdmNo AND s.school_id = legacy_ca.school_id
                        LEFT JOIN classes c_legacy ON legacy_ca.classID = c_legacy.classID AND legacy_ca.school_id = c_legacy.school_id
            WHERE (s.AdmNo LIKE %s OR s.FName LIKE %s OR s.SName LIKE %s)
              AND s.school_id = %s
            GROUP BY s.AdmNo
            LIMIT 20
        """, (f"%{query}%", f"%{query}%", f"%{query}%", self.school_id))
        return cursor.fetchall()

    def get_current_allocation(self, student_id):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT ca.*, c.display_name, c.classID, ay.year
            FROM class_allocation ca
            JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            JOIN academic_years ay ON ca.academic_year_id = ay.id AND ca.school_id = ay.school_id
            WHERE ca.student_id = %s AND ca.is_current = TRUE AND ca.school_id = %s
            LIMIT 1
        """, (student_id, self.school_id))
        return cursor.fetchone()

    def get_available_subjects_for_class(self, class_id):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT s.subjectNo as id, s.code, s.subjName as name, cs.is_compulsory
            FROM class_subjects cs
                        JOIN subjects s ON cs.subject_id = s.subjectNo AND cs.school_id = s.school_id
            WHERE cs.class_id = %s AND cs.is_active = TRUE
              AND cs.school_id = %s AND s.school_id = %s
            ORDER BY s.code
        """, (class_id, self.school_id, self.school_id))
        return cursor.fetchall()

    def get_enrolled_subject_ids(self, allocation_id):
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT subject_id FROM student_subjects
            WHERE class_allocation_id = %s AND is_active = TRUE AND school_id = %s
        """, (allocation_id, self.school_id))
        return [row['subject_id'] for row in cursor.fetchall()]

    def clear_student_subject_enrollments(self, allocation_id):
        self._assert_class_allocation_belongs_to_school(allocation_id)
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE student_subjects SET is_active = FALSE WHERE class_allocation_id = %s AND school_id = %s",
            (allocation_id, self.school_id),
        )
        self.connection.commit()
