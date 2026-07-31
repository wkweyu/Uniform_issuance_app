"""
=============================================================================
PRODUCTION-GRADE FEES MANAGEMENT SERVICE
Module: fees_service.py
Database: schoolmngt

This module provides business logic for:
- Votehead Management
- Fee Structure Creation
- Student Invoicing (Individually & Bulk)
- Payment Collection
- Ledger Reconciliation
- Financial Reporting
=============================================================================
"""

import pymysql
from datetime import datetime
import logging
import json
import uuid
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from core.audit import audit_log
from core.tenancy import require_current_school_id
from blueprints.finance.services import FinanceService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FeesError(Exception):
    """Base exception for fees management errors."""
    pass

class FeesService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)
        self.school_id = school_id or require_current_school_id()
        self._table_columns_cache: Dict[str, set] = {}

    def _table_has_column(self, table_name: str, column_name: str) -> bool:
        """Return True when a table contains a given column (cached per instance)."""
        if table_name not in self._table_columns_cache:
            self.cursor.execute(f"SHOW COLUMNS FROM {table_name}")
            self._table_columns_cache[table_name] = {row['Field'] for row in self.cursor.fetchall()}
        return column_name in self._table_columns_cache[table_name]

    def get_current_term_id(self):
        self.cursor.execute(
            "SELECT id FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date AND school_id = %s LIMIT 1",
            (self.school_id,)
        )
        term_res = self.cursor.fetchone()
        return term_res['id'] if term_res else None

    def _required_int(self, value, field_name: str) -> int:
        try:
            return int(str(value).strip())
        except (AttributeError, TypeError, ValueError):
            raise FeesError(f"{field_name} must be a valid integer.")

    def _extract_votehead_ids(self, items: List[Dict], field_name: str = 'votehead_id') -> List[int]:
        votehead_ids = []
        for index, item in enumerate(items or [], start=1):
            if not isinstance(item, dict):
                raise FeesError(f"item[{index}] must be an object.")
            votehead_ids.append(self._required_int(item.get(field_name), field_name))
        return votehead_ids

    def _assert_student_belongs_to_school(self, admno: int) -> None:
        self.cursor.execute("SELECT AdmNo FROM studentinfo WHERE AdmNo = %s AND school_id = %s", (admno, self.school_id))
        if not self.cursor.fetchone():
            raise FeesError("Student not found for the active school.")

    def _assert_academic_year_belongs_to_school(self, year_id: int) -> None:
        self.cursor.execute("SELECT id FROM academic_years WHERE id = %s AND school_id = %s", (year_id, self.school_id))
        if not self.cursor.fetchone():
            raise FeesError("Academic year not found for the active school.")

    def _assert_term_belongs_to_school(self, term_id: int, year_id: Optional[int] = None) -> None:
        if year_id is None:
            self.cursor.execute("SELECT id FROM uniform_term_dates WHERE id = %s AND school_id = %s", (term_id, self.school_id))
        else:
            self.cursor.execute("SELECT id FROM uniform_term_dates WHERE id = %s AND academic_year_id = %s AND school_id = %s", (term_id, year_id, self.school_id))
        if not self.cursor.fetchone():
            raise FeesError("Term not found for the active school.")

    def _assert_class_belongs_to_school(self, class_id: Optional[int]) -> None:
        if not class_id:
            return
        self.cursor.execute("SELECT classID FROM classes WHERE classID = %s AND school_id = %s", (class_id, self.school_id))
        if not self.cursor.fetchone():
            raise FeesError("Class not found for the active school.")

    def _assert_classes_belong_to_school(self, class_ids: List[int]) -> None:
        filtered_ids = [class_id for class_id in class_ids if class_id]
        if not filtered_ids:
            return
        placeholders = ', '.join(['%s'] * len(filtered_ids))
        self.cursor.execute(
            f"SELECT classID FROM classes WHERE classID IN ({placeholders}) AND school_id = %s",
            tuple(filtered_ids) + (self.school_id,),
        )
        found = {row['classID'] for row in self.cursor.fetchall()}
        missing = [class_id for class_id in filtered_ids if class_id not in found]
        if missing:
            raise FeesError("One or more classes do not belong to the active school.")

    def _assert_structure_belongs_to_school(self, structure_id: int) -> None:
        self.cursor.execute("SELECT id FROM fee_structures WHERE id = %s AND school_id = %s", (structure_id, self.school_id))
        if not self.cursor.fetchone():
            raise FeesError("Fee structure not found for the active school.")

    def _assert_student_group_belongs_to_school(self, group_id: Optional[int]) -> None:
        if not group_id:
            return
        self.cursor.execute("SELECT id FROM student_groups WHERE id = %s AND school_id = %s", (group_id, self.school_id))
        if not self.cursor.fetchone():
            raise FeesError("Student group not found for the active school.")

    def _assert_voteheads_belong_to_school(self, votehead_ids: List[int]) -> None:
        if not votehead_ids:
            return
        placeholders = ', '.join(['%s'] * len(votehead_ids))
        self.cursor.execute(
            f"SELECT id FROM fee_voteheads WHERE id IN ({placeholders}) AND school_id = %s",
            tuple(votehead_ids) + (self.school_id,),
        )
        found = {row['id'] for row in self.cursor.fetchall()}
        missing = [votehead_id for votehead_id in votehead_ids if votehead_id not in found]
        if missing:
            raise FeesError("One or more voteheads do not belong to the active school.")

    def _assert_waiver_category_belongs_to_school(self, category_id: int) -> None:
        self.cursor.execute("SELECT id FROM fee_waiver_categories WHERE id = %s AND school_id = %s", (category_id, self.school_id))
        if not self.cursor.fetchone():
            raise FeesError("Invalid waiver category.")

    # =========================================================================
    # 1. SETUP & CONFIGURATION (Voteheads & Structures)
    # =========================================================================

    def get_student_groups(self, active_only: bool = True) -> List[Dict]:
        """Fetch all student groups."""
        query = "SELECT * FROM student_groups WHERE school_id = %s"
        if active_only:
            query += " AND is_active = TRUE"
        query += " ORDER BY name"
        self.cursor.execute(query, (self.school_id,))
        return self.cursor.fetchall()

    def get_dashboard_totals(self, today) -> Dict:
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')

        if fee_payments_has_school_id:
            self.cursor.execute(
                "SELECT SUM(amount) as total FROM fee_payments WHERE payment_date = %s AND status = 'COMPLETED' AND school_id = %s",
                (today, self.school_id),
            )
        else:
            self.cursor.execute(
                """
                SELECT SUM(fp.amount) as total
                FROM fee_payments fp
                JOIN fee_ledger fl ON fp.ledger_id = fl.id
                WHERE fp.payment_date = %s AND fp.status = 'COMPLETED' AND fl.school_id = %s
                """,
                (today, self.school_id),
            )
        today_total = self.cursor.fetchone()['total'] or 0

        if fee_payments_has_school_id:
            self.cursor.execute(
                "SELECT SUM(amount) as total FROM fee_payments WHERE MONTH(payment_date) = MONTH(%s) AND YEAR(payment_date) = YEAR(%s) AND status = 'COMPLETED' AND school_id = %s",
                (today, today, self.school_id),
            )
        else:
            self.cursor.execute(
                """
                SELECT SUM(fp.amount) as total
                FROM fee_payments fp
                JOIN fee_ledger fl ON fp.ledger_id = fl.id
                WHERE MONTH(fp.payment_date) = MONTH(%s)
                  AND YEAR(fp.payment_date) = YEAR(%s)
                  AND fp.status = 'COMPLETED'
                  AND fl.school_id = %s
                """,
                (today, today, self.school_id),
            )
        monthly_total = self.cursor.fetchone()['total'] or 0

        self.cursor.execute(
            """
            SELECT SUM(fl.balance_after) as total
            FROM fee_ledger fl
            WHERE fl.school_id = %s
              AND fl.id IN (SELECT MAX(id) FROM fee_ledger WHERE school_id = %s GROUP BY admno)
            """,
            (self.school_id, self.school_id),
        )
        total_arrears = self.cursor.fetchone()['total'] or 0

        return {
            'today_total': today_total,
            'monthly_total': monthly_total,
            'total_arrears': total_arrears,
        }

    def get_distinct_stream_codes(self) -> List[str]:
        self.cursor.execute(
            "SELECT DISTINCT stream_code FROM classes WHERE stream_code IS NOT NULL AND stream_code != '' AND school_id = %s",
            (self.school_id,),
        )
        return [row['stream_code'] for row in self.cursor.fetchall()]

    def get_recent_terms(self, limit: Optional[int] = None) -> List[Dict]:
        query = "SELECT * FROM uniform_term_dates WHERE school_id = %s ORDER BY year DESC, term_number DESC"
        params: List = [self.school_id]
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        self.cursor.execute(query, tuple(params))
        return self.cursor.fetchall()

    def get_terms_for_academic_year(self, year_id: int) -> List[Dict]:
        self.cursor.execute(
            "SELECT id, term_number FROM uniform_term_dates WHERE academic_year_id = %s AND school_id = %s ORDER BY term_number",
            (year_id, self.school_id),
        )
        return self.cursor.fetchall()

    def get_recent_waivers(self, limit: int = 50) -> List[Dict]:
        self.cursor.execute(
            """
            SELECT sw.*, si.FName, si.SName, fwc.name as category_name, ay.year as year_name, utd.term_number
            FROM student_waivers sw
            JOIN studentinfo si ON sw.admno = si.AdmNo AND sw.school_id = si.school_id
            JOIN fee_waiver_categories fwc ON sw.category_id = fwc.id AND sw.school_id = fwc.school_id
            JOIN academic_years ay ON sw.academic_year_id = ay.id AND sw.school_id = ay.school_id
            JOIN uniform_term_dates utd ON sw.term_id = utd.id AND sw.school_id = utd.school_id
            WHERE sw.school_id = %s
            ORDER BY sw.created_at DESC LIMIT %s
            """,
            (self.school_id, limit),
        )
        return self.cursor.fetchall()

    def get_structure_card_items(self, year_id: int, category: str, class_id: Optional[int] = None, group_code: Optional[str] = None) -> List[Dict]:
        query = """
            SELECT fsi.votehead_id, fsi.amount, fs.term_id, fs.is_locked
            FROM fee_structure_items fsi
            JOIN fee_structures fs ON fsi.fee_structure_id = fs.id AND fsi.school_id = fs.school_id
            WHERE fs.academic_year_id = %s AND fs.student_category = %s AND fs.school_id = %s
        """
        params: List = [year_id, category, self.school_id]
        if class_id:
            query += " AND fs.class_id = %s"
            params.append(class_id)
        else:
            query += " AND fs.class_group_code = %s AND (fs.class_id IS NULL OR fs.class_id = 0)"
            params.append(group_code or 'all')
        self.cursor.execute(query, tuple(params))
        return self.cursor.fetchall()

    def get_structure_overview_rows(self, year_id: int) -> List[Dict]:
        self.cursor.execute(
            """
            SELECT fs.class_group_code, fs.class_id, fs.student_category, fs.term_id, fs.total_amount,
                   c.display_name as specific_class_name
            FROM fee_structures fs
            LEFT JOIN classes c ON fs.class_id = c.classID AND fs.school_id = c.school_id
            WHERE fs.academic_year_id = %s AND fs.school_id = %s
            """,
            (year_id, self.school_id),
        )
        return self.cursor.fetchall()

    def create_student_group(self, name: str, description: str = "") -> int:
        """Create a tenant-scoped student group."""
        self.cursor.execute(
            "INSERT INTO student_groups (name, description, school_id) VALUES (%s, %s, %s)",
            (name, description, self.school_id),
        )
        self.connection.commit()
        return self.cursor.lastrowid

    def get_voteheads(self, active_only: bool = True, group_id: Optional[int] = None) -> List[Dict]:
        """Fetch all fee voteheads with optional group filter."""
        query = "SELECT v.*, g.name as group_name FROM fee_voteheads v LEFT JOIN student_groups g ON v.applicable_student_group_id = g.id AND v.school_id = g.school_id"
        conditions = ["v.school_id = %s"]
        params = [self.school_id]
        if active_only:
            conditions.append("v.is_active = TRUE")
        if group_id:
            conditions.append("(v.applicable_student_group_id IS NULL OR v.applicable_student_group_id = %s)")
            params.append(group_id)
            
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY v.priority ASC, v.name ASC"
        
        self.cursor.execute(query, tuple(params))
        return self.cursor.fetchall()

    def get_allocation_templates(self) -> List[Dict]:
        """Return reusable manual allocation templates for the active school."""
        self.cursor.execute("""
            SELECT t.id, t.name, t.created_at, i.votehead_id, i.amount, v.name AS votehead_name
            FROM fee_allocation_templates t
            LEFT JOIN fee_allocation_template_items i
              ON i.template_id = t.id AND i.school_id = t.school_id
            LEFT JOIN fee_voteheads v
              ON v.id = i.votehead_id AND v.school_id = i.school_id
            WHERE t.school_id = %s
            ORDER BY t.name ASC, v.priority ASC, v.name ASC
        """, (self.school_id,))

        templates = {}
        for row in self.cursor.fetchall():
            template = templates.setdefault(row['id'], {
                'id': row['id'],
                'name': row['name'],
                'created_at': row['created_at'],
                'items': [],
            })
            if row.get('votehead_id') is not None:
                template['items'].append({
                    'votehead_id': row['votehead_id'],
                    'votehead_name': row['votehead_name'],
                    'amount': Decimal(str(row['amount'])),
                })
        return list(templates.values())

    def create_allocation_template(self, name: str, allocations: List[Dict], user_id: int) -> Dict:
        """Persist a reusable manual allocation template after tenant validation."""
        template_name = (name or '').strip()
        if not template_name:
            raise FeesError('Template name is required.')
        if not allocations:
            raise FeesError('At least one allocation is required.')

        normalized_items = []
        seen_voteheads = set()
        for allocation in allocations:
            try:
                votehead_id = self._required_int(allocation.get('votehead_id'), 'votehead_id')
                amount = Decimal(str(allocation.get('amount')))
            except (AttributeError, InvalidOperation, TypeError, ValueError):
                raise FeesError('Each template allocation requires a valid votehead_id and amount.')
            if votehead_id in seen_voteheads:
                raise FeesError('A votehead can only appear once in an allocation template.')
            if amount <= 0:
                raise FeesError('Template allocation amounts must be greater than zero.')
            seen_voteheads.add(votehead_id)
            normalized_items.append({'votehead_id': votehead_id, 'amount': amount})

        self._assert_voteheads_belong_to_school([item['votehead_id'] for item in normalized_items])
        try:
            self.connection.begin()
            self.cursor.execute("""
                INSERT INTO fee_allocation_templates (school_id, name, created_by)
                VALUES (%s, %s, %s)
            """, (self.school_id, template_name, user_id))
            template_id = self.cursor.lastrowid
            for item in normalized_items:
                self.cursor.execute("""
                    INSERT INTO fee_allocation_template_items (template_id, votehead_id, amount, school_id)
                    VALUES (%s, %s, %s, %s)
                """, (template_id, item['votehead_id'], item['amount'], self.school_id))
            self.connection.commit()
        except pymysql.IntegrityError:
            self.connection.rollback()
            raise FeesError(f"An allocation template named '{template_name}' already exists.")
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f'Failed to save allocation template: {str(e)}')

        return {'id': template_id, 'name': template_name, 'items': normalized_items}

    def create_votehead(self, name: str, priority: int = 99, group_id: Optional[int] = None, description: str = "") -> int:
        """Create a new fee votehead."""
        try:
            self._assert_student_group_belongs_to_school(group_id)
            self.cursor.execute(
                "INSERT INTO fee_voteheads (name, priority, applicable_student_group_id, description, school_id) VALUES (%s, %s, %s, %s, %s)",
                (name, priority, group_id, description, self.school_id)
            )
            self.connection.commit()
            return self.cursor.lastrowid
        except pymysql.IntegrityError:
            raise FeesError(f"Votehead '{name}' already exists.")

    def copy_fee_structure(self, from_structure_id: int, target_year_id: int, target_term_id: int, user_id: int) -> int:
        """Copy an existing fee structure to a new year/term."""
        try:
            # 1. Get original structure
            self.cursor.execute("SELECT * FROM fee_structures WHERE id = %s AND school_id = %s", (from_structure_id, self.school_id))
            old = self.cursor.fetchone()
            if not old:
                raise FeesError("Source structure not found.")
            
            # 2. Get items
            self.cursor.execute("SELECT * FROM fee_structure_items WHERE fee_structure_id = %s AND school_id = %s", (from_structure_id, self.school_id))
            items = self.cursor.fetchall()
            
            # 3. Create new structure
            return self.create_fee_structure(
                target_year_id, 
                target_term_id, 
                old['class_group_code'], 
                old['student_category'], 
                items, 
                user_id
            )
        except Exception as e:
            raise FeesError(f"Failed to copy structure: {str(e)}")

    def create_fee_structure(self, year_id: int, term_id: int, class_group: str, category: str, items: List[Dict], user_id: int, class_id: Optional[int] = None) -> int:
        """
        Create a fee structure and its associated items.
        Items should be a list of {'votehead_id': X, 'amount': Y}
        """
        try:
            self._assert_academic_year_belongs_to_school(year_id)
            self._assert_term_belongs_to_school(term_id, year_id)
            self._assert_class_belongs_to_school(class_id)
            self._assert_voteheads_belong_to_school(self._extract_votehead_ids(items))
            self.connection.begin()
            
            total_amount = sum(Decimal(str(item['amount'])) for item in items)
            
            self.cursor.execute("""
                INSERT INTO fee_structures (academic_year_id, term_id, class_id, class_group_code, student_category, total_amount, created_by, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (year_id, term_id, class_id, class_group, category, total_amount, user_id, self.school_id))
            
            structure_id = self.cursor.lastrowid
            
            for item in items:
                self.cursor.execute("""
                    INSERT INTO fee_structure_items (fee_structure_id, votehead_id, amount, school_id)
                    VALUES (%s, %s, %s, %s)
                """, (structure_id, item['votehead_id'], item['amount'], self.school_id))
            
            self.connection.commit()
            return structure_id
        except pymysql.IntegrityError as e:
            self.connection.rollback()
            raise FeesError(f"Fee structure already exists for this combination.")
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Failed to create fee structure: {str(e)}")

    def create_bulk_fee_structures(self, year_id: int, term_id: int, class_groups: List[str], categories: List[str], items: List[Dict], user_id: int, class_ids: List[int] = None) -> Dict:
        """Create multiple structures for a combination of groups, categories, and optionally specific classes."""
        results = {'success': 0, 'skipped': 0, 'errors': []}
        self._assert_academic_year_belongs_to_school(year_id)
        self._assert_term_belongs_to_school(term_id, year_id)
        self._assert_voteheads_belong_to_school(self._extract_votehead_ids(items))
        
        # If specific classes are provided, use them. Otherwise use class groups.
        if class_ids:
            self._assert_classes_belong_to_school(class_ids)
            for c_id in class_ids:
                # Fetch class group for this class to maintain category mapping
                self.cursor.execute("SELECT class_group_code FROM classes WHERE classID = %s AND school_id = %s", (c_id, self.school_id))
                c_row = self.cursor.fetchone()
                group = c_row['class_group_code'] if c_row else "Unknown"
                
                for cat in categories:
                    try:
                        self.create_fee_structure(year_id, term_id, group, cat, items, user_id, class_id=c_id)
                        results['success'] += 1
                    except FeesError:
                        results['skipped'] += 1
                    except Exception as e:
                        results['errors'].append(f"Class {c_id}/{cat}: {str(e)}")
        else:
            for group in class_groups:
                for cat in categories:
                    try:
                        self.create_fee_structure(year_id, term_id, group, cat, items, user_id)
                        results['success'] += 1
                    except FeesError:
                        results['skipped'] += 1
                    except Exception as e:
                        results['errors'].append(f"{group}/{cat}: {str(e)}")
        return results

    def delete_fee_structure(self, structure_id: int) -> bool:
        """Delete a fee structure. Only allowed if not yet invoiced (optional safety)."""
        try:
            self._assert_structure_belongs_to_school(structure_id)
            # Check if invoiced (optional but recommended for ERP standards)
            # self.cursor.execute("SELECT id FROM fee_ledger WHERE reference_no LIKE %s AND school_id = %s", (f"INV-%-{structure_id}", self.school_id))
            
            self.cursor.execute("DELETE FROM fee_structures WHERE id = %s AND school_id = %s", (structure_id, self.school_id))
            self.connection.commit()
            return True
        except Exception as e:
            raise FeesError(f"Deletion failed: {str(e)}")

    def get_fee_structures(self, year_id: Optional[int] = None) -> List[Dict]:
        """Fetch structures with breakdown."""
        query = """
            SELECT fs.*, ay.year as year_name, utd.term_number, utd.start_date, utd.end_date,
                   c.display_name as specific_class_name
            FROM fee_structures fs
            JOIN academic_years ay ON fs.academic_year_id = ay.id AND fs.school_id = ay.school_id
            JOIN uniform_term_dates utd ON fs.term_id = utd.id AND fs.school_id = utd.school_id
            LEFT JOIN classes c ON fs.class_id = c.classID AND fs.school_id = c.school_id
            WHERE fs.school_id = %s
        """
        params = [self.school_id]
        if year_id:
            query += " AND fs.academic_year_id = %s"
            params.append(year_id)
        
        query += " ORDER BY ay.year DESC, utd.term_number DESC, c.display_name"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_fee_structure_details(self, structure_id: int) -> Dict:
        """Fetch a single structure with its items."""
        self.cursor.execute("""
            SELECT fs.*, ay.year as year_name, utd.term_number,
                   c.display_name as specific_class_name
            FROM fee_structures fs
            JOIN academic_years ay ON fs.academic_year_id = ay.id AND fs.school_id = ay.school_id
            JOIN uniform_term_dates utd ON fs.term_id = utd.id AND fs.school_id = utd.school_id
            LEFT JOIN classes c ON fs.class_id = c.classID AND fs.school_id = c.school_id
            WHERE fs.id = %s AND fs.school_id = %s
        """, (structure_id, self.school_id))
        struct = self.cursor.fetchone()
        
        if struct:
            self.cursor.execute("""
                SELECT fsi.*, fv.name as votehead_name
                FROM fee_structure_items fsi
                JOIN fee_voteheads fv ON fsi.votehead_id = fv.id AND fsi.school_id = fv.school_id
                WHERE fsi.fee_structure_id = %s AND fsi.school_id = %s
                ORDER BY fv.priority ASC
            """, (structure_id, self.school_id))
            struct['items'] = self.cursor.fetchall()
            
        return struct

    def update_fee_structure(self, structure_id: int, items: List[Dict], user_id: int) -> bool:
        """Update items in an existing fee structure."""
        try:
            self._assert_structure_belongs_to_school(structure_id)
            self._assert_voteheads_belong_to_school(self._extract_votehead_ids(items))
            self.connection.begin()
            
            # 1. Check if locked
            self.cursor.execute("SELECT is_locked FROM fee_structures WHERE id = %s AND school_id = %s", (structure_id, self.school_id))
            res = self.cursor.fetchone()
            if res and res['is_locked']:
                raise FeesError("This structure is locked and cannot be modified.")

            # 2. Clear existing items
            self.cursor.execute("DELETE FROM fee_structure_items WHERE fee_structure_id = %s AND school_id = %s", (structure_id, self.school_id))
            
            # 3. Insert new items
            total_amount = Decimal("0.00")
            for item in items:
                amt = Decimal(str(item['amount']))
                if amt > 0:
                    self.cursor.execute("""
                        INSERT INTO fee_structure_items (fee_structure_id, votehead_id, amount, school_id)
                        VALUES (%s, %s, %s, %s)
                    """, (structure_id, item['votehead_id'], amt, self.school_id))
                    total_amount += amt
            
            # 4. Update total
            self.cursor.execute("UPDATE fee_structures SET total_amount = %s WHERE id = %s AND school_id = %s", (total_amount, structure_id, self.school_id))
            
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Update failed: {str(e)}")

    # =========================================================================
    # 2. STUDENT ACCOUNTS & INVOICING
    # =========================================================================

    def get_student_balance(self, admno: int) -> Decimal:
        """Calculate current running balance for a student."""
        self.cursor.execute("""
            SELECT balance_after FROM fee_ledger 
            WHERE admno = %s AND school_id = %s
            ORDER BY id DESC LIMIT 1
        """, (admno, self.school_id))
        result = self.cursor.fetchone()
        return Decimal(str(result['balance_after'])) if result else Decimal("0.00")

    def create_account_adjustment(
        self, admno: int, adjustment_type: str, votehead_id: int, amount: Decimal,
        year_id: int, term_id: int, effective_date: str, reason: str,
        supporting_reference: str, user_id: int,
    ) -> int:
        """Post an audited debit or credit note distinct from payments and waivers."""
        adjustment_type = (adjustment_type or '').strip().upper()
        if adjustment_type not in ('DEBIT', 'CREDIT'):
            raise FeesError('Adjustment type must be DEBIT or CREDIT.')
        amount = Decimal(str(amount))
        if amount <= 0:
            raise FeesError('Adjustment amount must be greater than zero.')
        reason = (reason or '').strip()
        supporting_reference = (supporting_reference or '').strip()
        if not reason:
            raise FeesError('An adjustment reason is required.')
        if not supporting_reference:
            raise FeesError('A supporting reference is required.')
        try:
            self._assert_student_belongs_to_school(admno)
            self._assert_academic_year_belongs_to_school(year_id)
            self._assert_term_belongs_to_school(term_id, year_id)
            self._assert_voteheads_belong_to_school([votehead_id])
            self.connection.begin()
            self.cursor.execute("""
                INSERT INTO fee_adjustments
                    (admno, academic_year_id, term_id, votehead_id, amount, adjustment_type, reason,
                     effective_date, supporting_reference, approved_by, created_by, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                admno, year_id, term_id, votehead_id, amount, adjustment_type, reason,
                effective_date, supporting_reference, user_id, user_id, self.school_id,
            ))
            adjustment_id = self.cursor.lastrowid
            current_balance = self.get_student_balance(admno)
            new_balance = current_balance + amount if adjustment_type == 'DEBIT' else current_balance - amount
            reference = f"{adjustment_type[:3]}-{adjustment_id}"
            self.cursor.execute("""
                INSERT INTO fee_ledger
                    (admno, academic_year_id, term_id, type, votehead_id, amount, balance_after,
                     description, reference_no, transaction_date, created_by, school_id)
                VALUES (%s, %s, %s, 'ADJUSTMENT', %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                admno, year_id, term_id, votehead_id, amount, new_balance,
                f"{adjustment_type} NOTE: {reason}", reference, effective_date, user_id, self.school_id,
            ))
            ledger_id = self.cursor.lastrowid
            self.cursor.execute(
                "UPDATE fee_adjustments SET ledger_id = %s WHERE id = %s AND school_id = %s",
                (ledger_id, adjustment_id, self.school_id),
            )
            self.connection.commit()
            return adjustment_id
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, FeesError):
                raise
            raise FeesError(f'Adjustment posting failed: {str(exc)}')

    def get_student_term_summary(self, admno: int, term_id: int) -> Dict:
        """Summarize current-term ledger movements for a student."""
        self.cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN type = 'CHARGE' THEN amount ELSE 0 END), 0) AS charges,
                                COALESCE(SUM(CASE
                                        WHEN type = 'DEBIT'
                                            OR (type = 'ADJUSTMENT' AND (description LIKE 'DEBIT NOTE:%%' OR description LIKE 'VOID RECEIPT:%%'))
                                        THEN amount ELSE 0 END), 0) AS debits,
                COALESCE(SUM(CASE WHEN type = 'PAYMENT' THEN amount ELSE 0 END), 0) AS payments,
                                COALESCE(SUM(CASE
                                        WHEN type = 'CREDIT' OR (type = 'ADJUSTMENT' AND description LIKE 'CREDIT NOTE:%%')
                                        THEN amount ELSE 0 END), 0) AS credits
            FROM fee_ledger
            WHERE admno = %s AND term_id = %s AND school_id = %s
        """, (admno, term_id, self.school_id))
        summary = self.cursor.fetchone() or {}
        charges = Decimal(str(summary.get('charges') or 0))
        debits = Decimal(str(summary.get('debits') or 0))
        payments = Decimal(str(summary.get('payments') or 0))
        credits = Decimal(str(summary.get('credits') or 0))
        return {
            'charges': charges,
            'debits': debits,
            'payments': payments,
            'credits': credits,
            'net_due': charges + debits - payments - credits,
        }

    def get_student_term_invoices(self, admno: int, term_id: int) -> List[Dict]:
        """Return invoice references and totals posted for a student in a term."""
        self.cursor.execute("""
            SELECT
                reference_no,
                MIN(transaction_date) AS issued_on,
                SUM(amount) AS amount,
                COUNT(*) AS item_count
            FROM fee_ledger
            WHERE admno = %s
              AND term_id = %s
              AND type = 'CHARGE'
              AND reference_no LIKE 'INV-%%'
              AND school_id = %s
            GROUP BY reference_no
            ORDER BY issued_on DESC, reference_no DESC
        """, (admno, term_id, self.school_id))
        return self.cursor.fetchall()

    def get_category_change_preflight(self, admno: int, year_id: int, term_id: int) -> Dict:
        """Identify whether a category-driven current-term invoice replacement is safe to automate."""
        self._assert_student_belongs_to_school(admno)
        self._assert_academic_year_belongs_to_school(year_id)
        self._assert_term_belongs_to_school(term_id, year_id)
        self.cursor.execute("""
            SELECT reference_no
            FROM fee_ledger
            WHERE admno = %s AND academic_year_id = %s AND term_id = %s
              AND type = 'CHARGE' AND reference_no LIKE 'INV-%%'
              AND reference_no NOT LIKE 'INV-SPEC-%%' AND school_id = %s
            GROUP BY reference_no
        """, (admno, year_id, term_id, self.school_id))
        invoice_references = [row['reference_no'] for row in self.cursor.fetchall()]

        self.cursor.execute("""
            SELECT COUNT(*) AS allocation_count
            FROM fee_payment_allocations allocations
            JOIN fee_payments payments ON allocations.payment_id = payments.id AND allocations.school_id = payments.school_id
            JOIN fee_ledger payment_ledger ON payments.ledger_id = payment_ledger.id AND payments.school_id = payment_ledger.school_id
            WHERE payments.admno = %s AND payments.status = 'COMPLETED'
              AND payment_ledger.academic_year_id = %s AND payment_ledger.term_id = %s
              AND allocations.school_id = %s
        """, (admno, year_id, term_id, self.school_id))
        allocation_count = self.cursor.fetchone()['allocation_count'] or 0

        self.cursor.execute("""
            SELECT COUNT(*) AS locked_count
            FROM fee_structures
            WHERE academic_year_id = %s AND term_id = %s AND is_locked = TRUE AND school_id = %s
        """, (year_id, term_id, self.school_id))
        locked_count = self.cursor.fetchone()['locked_count'] or 0

        blockers = []
        if allocation_count:
            blockers.append('Completed payment allocations exist for this term and require manual review.')
        if locked_count:
            blockers.append('The term fee structure is locked and cannot be replaced automatically.')
        return {
            'eligible': not blockers,
            'invoice_references': invoice_references,
            'has_current_term_invoice': bool(invoice_references),
            'blockers': blockers,
        }

    def replace_category_invoice(self, admno: int, year_id: int, term_id: int,
                                 new_category: str, new_student_group_id: Optional[int],
                                 reason: str, user_id: int) -> Dict:
        """Replace an unpaid current-term invoice after a tenant-scoped category correction."""
        category = (new_category or '').strip()
        reason = (reason or '').strip()
        if not category or not reason:
            raise FeesError('New category and replacement reason are required.')
        if new_student_group_id is not None:
            self._assert_student_group_belongs_to_school(new_student_group_id)

        preflight = self.get_category_change_preflight(admno, year_id, term_id)
        if preflight['blockers']:
            raise FeesError(' '.join(preflight['blockers']))
        if len(preflight['invoice_references']) != 1:
            raise FeesError('Exactly one unpaid standard invoice is required for automatic replacement.')

        original_reference = preflight['invoice_references'][0]
        self.cursor.execute("""
            SELECT category, student_group_id
            FROM studentinfo WHERE AdmNo = %s AND school_id = %s FOR UPDATE
        """, (admno, self.school_id))
        student = self.cursor.fetchone()
        if not student:
            raise FeesError('Student not found for the active school.')
        previous_group_id = student.get('student_group_id')
        target_group_id = new_student_group_id if new_student_group_id is not None else previous_group_id

        self.cursor.execute("""
            SELECT c.classID, c.class_group_code
            FROM class_allocation allocation
            JOIN classes c ON allocation.class_id = c.classID AND allocation.school_id = c.school_id
            WHERE allocation.student_id = %s AND allocation.is_current = TRUE AND allocation.school_id = %s
            ORDER BY allocation.id DESC LIMIT 1
        """, (admno, self.school_id))
        class_info = self.cursor.fetchone()
        if not class_info:
            raise FeesError('Student has no current class assignment for fee structure resolution.')

        self.cursor.execute("""
            SELECT id, is_locked FROM fee_structures
            WHERE academic_year_id = %s AND term_id = %s AND class_id = %s
              AND student_category = %s AND school_id = %s
            LIMIT 1
        """, (year_id, term_id, class_info['classID'], category, self.school_id))
        structure = self.cursor.fetchone()
        if not structure:
            self.cursor.execute("""
                SELECT id, is_locked FROM fee_structures
                WHERE academic_year_id = %s AND term_id = %s AND class_group_code = %s
                  AND student_category = %s AND (class_id IS NULL OR class_id = 0) AND school_id = %s
                LIMIT 1
            """, (year_id, term_id, class_info['class_group_code'], category, self.school_id))
            structure = self.cursor.fetchone()
        if not structure or structure['is_locked']:
            raise FeesError('No unlocked fee structure exists for the corrected category.')

        self.cursor.execute("""
            SELECT id, votehead_id, amount FROM fee_ledger
            WHERE admno = %s AND academic_year_id = %s AND term_id = %s
              AND type = 'CHARGE' AND reference_no = %s AND school_id = %s
            ORDER BY id ASC FOR UPDATE
        """, (admno, year_id, term_id, original_reference, self.school_id))
        original_rows = self.cursor.fetchall()
        self.cursor.execute("""
            SELECT votehead_id, amount FROM fee_structure_items
            WHERE fee_structure_id = %s AND school_id = %s ORDER BY id ASC
        """, (structure['id'], self.school_id))
        replacement_items = self.cursor.fetchall()
        if not original_rows or not replacement_items:
            raise FeesError('Invoice replacement data is incomplete.')

        correlation = uuid.uuid4().hex[:24]
        reversal_reference = f'INV-REV-{correlation}'
        replacement_reference = f'INV-REP-{correlation}'
        try:
            self.connection.begin()
            for row in original_rows:
                self.cursor.execute("""
                    INSERT INTO fee_ledger
                        (admno, academic_year_id, term_id, type, votehead_id, amount, balance_after,
                         description, reference_no, transaction_date, created_by, school_id)
                    VALUES (%s, %s, %s, 'CREDIT', %s, %s, 0, %s, %s, CURDATE(), %s, %s)
                """, (admno, year_id, term_id, row['votehead_id'], row['amount'],
                      f'INVOICE REVERSAL: {original_reference} - {reason}', reversal_reference, user_id, self.school_id))
            for item in replacement_items:
                self.cursor.execute("""
                    INSERT INTO fee_ledger
                        (admno, academic_year_id, term_id, type, votehead_id, amount, balance_after,
                         description, reference_no, transaction_date, created_by, school_id)
                    VALUES (%s, %s, %s, 'CHARGE', %s, %s, 0, %s, %s, CURDATE(), %s, %s)
                """, (admno, year_id, term_id, item['votehead_id'], item['amount'],
                      f'CATEGORY REPLACEMENT INVOICE: {category}', replacement_reference, user_id, self.school_id))
            self.cursor.execute("""
                UPDATE studentinfo SET category = %s, student_group_id = %s
                WHERE AdmNo = %s AND school_id = %s
            """, (category, target_group_id, admno, self.school_id))
            self.cursor.execute("""
                INSERT INTO fee_invoice_replacements
                    (school_id, admno, academic_year_id, term_id, original_invoice_reference,
                     reversal_reference, replacement_invoice_reference, previous_category, new_category,
                     previous_student_group_id, new_student_group_id, reason, changed_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (self.school_id, admno, year_id, term_id, original_reference, reversal_reference,
                  replacement_reference, student.get('category') or '', category, previous_group_id,
                  target_group_id, reason, user_id))
            self._recalculate_student_ledger_balances(admno)
            self.connection.commit()
            return {'original_reference': original_reference, 'reversal_reference': reversal_reference,
                    'replacement_reference': replacement_reference}
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, FeesError):
                raise
            raise FeesError(f'Category invoice replacement failed: {str(exc)}')

    def get_outstanding_voteheads(self, admno: int) -> List[Dict]:
        """Return the student's outstanding voteheads in payment priority order."""
        self.cursor.execute("""
            SELECT
                fl.votehead_id,
                MAX(fv.name) AS votehead_name,
                MAX(fv.priority) AS priority,
                SUM(CASE WHEN fl.type = 'CHARGE' THEN fl.amount ELSE -fl.amount END) AS outstanding
            FROM fee_ledger fl
            JOIN fee_voteheads fv ON fl.votehead_id = fv.id AND fl.school_id = fv.school_id
            WHERE fl.admno = %s AND fl.school_id = %s AND fl.votehead_id IS NOT NULL
            GROUP BY fl.votehead_id
            HAVING outstanding > 0
            ORDER BY priority ASC, votehead_name ASC
        """, (admno, self.school_id))
        return self.cursor.fetchall()

    @audit_log('invoice_student')
    def invoice_student(self, admno: int, year_id: int, term_id: int, structure_id: int, user_id: int, custom_items: List[Dict] = None) -> List[int]:
        """Apply a fee structure or custom items to a student's ledger."""
        try:
            self._assert_student_belongs_to_school(admno)
            self._assert_academic_year_belongs_to_school(year_id)
            self._assert_term_belongs_to_school(term_id, year_id)
            # Get period details for description
            self.cursor.execute("SELECT year FROM academic_years WHERE id = %s AND school_id = %s", (year_id, self.school_id))
            y_name = self.cursor.fetchone()['year']
            self.cursor.execute("SELECT term_number FROM uniform_term_dates WHERE id = %s AND school_id = %s", (term_id, self.school_id))
            t_num = self.cursor.fetchone()['term_number']

            # Check if using structure or custom items
            if custom_items:
                self._assert_voteheads_belong_to_school(self._extract_votehead_ids(custom_items))
                items = custom_items
                # Reference for custom items identifies the specific votehead if possible
                v_id = items[0]['votehead_id'] if len(items) == 1 else 'MULTI'
                invoice_ref = f"INV-SPEC-{admno}-{v_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            else:
                self._assert_structure_belongs_to_school(structure_id)
                # Check if already invoiced for this term via standard structure
                self.cursor.execute("""
                    SELECT id FROM fee_ledger 
                    WHERE admno = %s AND academic_year_id = %s AND term_id = %s AND type = 'CHARGE'
                    AND reference_no LIKE 'INV-%%' AND reference_no NOT LIKE 'INV-SPEC-%%' AND school_id = %s
                """, (admno, year_id, term_id, self.school_id))
                if self.cursor.fetchone():
                    raise FeesError(f"Student {admno} already invoiced for this term.")

                # Get structure items
                self.cursor.execute("""
                    SELECT fsi.*, fv.name as votehead_name
                    FROM fee_structure_items fsi
                    JOIN fee_voteheads fv ON fsi.votehead_id = fv.id AND fsi.school_id = fv.school_id
                    WHERE fsi.fee_structure_id = %s AND fsi.school_id = %s
                """, (structure_id, self.school_id))
                items = self.cursor.fetchall()
                invoice_ref = f"INV-{admno}-{year_id}-{term_id}"
            
            if not items:
                raise FeesError("No items found to invoice.")

            self.connection.begin()
            
            transaction_ids = []
            current_balance = self.get_student_balance(admno)
            
            # Post each item individually to maintain votehead-level accounting for distribution
            for item in items:
                amount = Decimal(str(item['amount']))
                current_balance += amount
                
                # Fetch votehead name if not provided
                v_name = item.get('votehead_name')
                if not v_name:
                    self.cursor.execute("SELECT name FROM fee_voteheads WHERE id = %s AND school_id = %s", (item['votehead_id'], self.school_id))
                    v_res = self.cursor.fetchone()
                    v_name = v_res['name'] if v_res else "System Charge"

                # Use the calculated description for standard items to aid grouping in view
                # Standard items are grouped by Reference in the statement view
                desc = f"Charge: {v_name}"
                if not custom_items:
                    desc = f"Term {t_num} Fees - {y_name}"

                self.cursor.execute("""
                    INSERT INTO fee_ledger (admno, academic_year_id, term_id, type, votehead_id, amount, balance_after, description, reference_no, transaction_date, created_by, school_id)
                    VALUES (%s, %s, %s, 'CHARGE', %s, %s, %s, %s, %s, CURDATE(), %s, %s)
                """, (admno, year_id, term_id, item['votehead_id'], amount, current_balance, desc, invoice_ref, user_id, self.school_id))
                transaction_ids.append(self.cursor.lastrowid)

            self.connection.commit()
            return transaction_ids
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Invoicing failed: {str(e)}")

    def bulk_invoice_classes(self, class_ids: List[int], year_id: int, term_id: int, user_id: int, specific_votehead_id: int = None, specific_amount: Decimal = None) -> int:
        """Invoice all students in selected classes based on their category."""
        invoiced_count = 0
        
        # Get all students in these classes (check both new and legacy allocation tables)
        placeholders = ', '.join(['%s'] * len(class_ids))
        query = f"""
            SELECT ca.student_id, si.category, c.class_group_code, ca.class_id
            FROM class_allocation ca
            JOIN studentinfo si ON ca.student_id = si.AdmNo AND ca.school_id = si.school_id
            JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            WHERE ca.class_id IN ({placeholders}) AND ca.is_current = TRUE AND ca.school_id = %s
            
            UNION
            
            SELECT lca.AdmNo as student_id, si.category, c.class_group_code, lca.classID as class_id
            FROM classallocation lca
            JOIN studentinfo si ON lca.AdmNo = si.AdmNo AND lca.school_id = si.school_id
            JOIN classes c ON lca.classID = c.classID AND lca.school_id = c.school_id
            JOIN academic_years ay ON ay.year = lca.thisYear AND lca.school_id = ay.school_id
            WHERE lca.classID IN ({placeholders}) AND ay.id = %s AND lca.school_id = %s
            AND lca.AdmNo NOT IN (SELECT student_id FROM class_allocation WHERE is_current = TRUE AND school_id = %s)
        """
        params = list(class_ids) + [self.school_id] + list(class_ids) + [year_id, self.school_id, self.school_id]
        self.cursor.execute(query, params)
        students = self.cursor.fetchall()
        
        # Cache structures to avoid repeat lookups
        structures_cache = {}
        
        for student in students:
            if specific_votehead_id and specific_amount:
                # Individual votehead invoicing
                try:
                    custom_items = [{'votehead_id': specific_votehead_id, 'amount': specific_amount}]
                    self.invoice_student(student['student_id'], year_id, term_id, 0, user_id, custom_items=custom_items)
                    invoiced_count += 1
                except FeesError:
                    continue
            else:
                # Standard structure invoicing
                category = student['category'] or 'Regular'
                class_id = student['class_id']
                group = student['class_group_code']
                
                cache_key = (class_id, category, group)
                if cache_key not in structures_cache:
                    # 1. Try class-specific structure
                    self.cursor.execute("""
                        SELECT id FROM fee_structures 
                        WHERE academic_year_id = %s AND term_id = %s AND class_id = %s AND student_category = %s AND school_id = %s
                    """, (year_id, term_id, class_id, category, self.school_id))
                    res = self.cursor.fetchone()

                    # 2. Try class-group specific category
                    if not res:
                        self.cursor.execute("""
                            SELECT id FROM fee_structures 
                            WHERE academic_year_id = %s AND term_id = %s AND class_group_code = %s AND student_category = %s AND school_id = %s
                            AND (class_id IS NULL OR class_id = 0)
                        """, (year_id, term_id, group, category, self.school_id))
                        res = self.cursor.fetchone()
                    
                    # 3. Try 'all' as fallback if not found
                    if not res:
                        self.cursor.execute("""
                            SELECT id FROM fee_structures 
                            WHERE academic_year_id = %s AND term_id = %s AND class_group_code = 'all' AND student_category = %s AND school_id = %s
                            AND (class_id IS NULL OR class_id = 0)
                        """, (year_id, term_id, category, self.school_id))
                        res = self.cursor.fetchone()
                    
                    structures_cache[cache_key] = res['id'] if res else None
                
                structure_id = structures_cache[cache_key]
                if structure_id:
                    try:
                        self.invoice_student(student['student_id'], year_id, term_id, structure_id, user_id)
                        invoiced_count += 1
                    except FeesError:
                        continue # Skip already invoiced
                    
        return invoiced_count

    # =========================================================================
    # 3. PAYMENTS & RECEIPTS
    # =========================================================================

    def find_duplicate_payment(self, mode: str, reference: str) -> Optional[Dict]:
        """Find an existing payment with the same mode and reference in this school."""
        if not reference:
            return None

        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        receipts_has_school_id = self._table_has_column('fee_receipts', 'school_id')
        if fee_payments_has_school_id:
            receipt_join = "fr.payment_id = fp.id AND fr.school_id = fp.school_id" if receipts_has_school_id else "fr.payment_id = fp.id"
            self.cursor.execute("""
                SELECT fp.id, fp.admno, fp.amount, fp.payment_date, fp.status, fr.receipt_no
                FROM fee_payments fp
                LEFT JOIN fee_receipts fr ON """ + receipt_join + """
                WHERE fp.payment_mode = %s AND fp.reference_number = %s AND fp.school_id = %s
                ORDER BY fp.id DESC
                LIMIT 1
            """, (mode, reference, self.school_id))
        else:
            self.cursor.execute("""
                SELECT fp.id, fp.admno, fp.amount, fp.payment_date, fp.status, fr.receipt_no
                FROM fee_payments fp
                JOIN fee_ledger fl ON fp.ledger_id = fl.id
                LEFT JOIN fee_receipts fr ON fr.payment_id = fp.id
                WHERE fp.payment_mode = %s AND fp.reference_number = %s AND fl.school_id = %s
                ORDER BY fp.id DESC
                LIMIT 1
            """, (mode, reference, self.school_id))
        return self.cursor.fetchone()

    def get_payment_mode_receiving_account(self, mode: str) -> int:
        """Return the active Finance receiving account for a fee payment mode."""
        payment_mode = (mode or '').strip().upper()
        if not payment_mode:
            raise FeesError('Payment mode is required.')
        self.cursor.execute("""
            SELECT config.account_id
            FROM payment_mode_receiving_accounts config
            JOIN finance_accounts account
              ON account.id = config.account_id AND account.school_id = config.school_id
            WHERE config.school_id = %s
              AND config.payment_mode = %s
              AND config.is_active = TRUE
              AND account.is_active = TRUE
            LIMIT 1
        """, (self.school_id, payment_mode))
        account = self.cursor.fetchone()
        if not account:
            raise FeesError(
                f"No active receiving account is configured for payment mode '{payment_mode}'."
            )
        return account['account_id']

    def get_payment_mode_receiving_account_labels(self) -> Dict[str, str]:
        """Return active configured account labels for the bursar payment form."""
        try:
            self.cursor.execute("""
                SELECT config.payment_mode, account.code, account.name
                FROM payment_mode_receiving_accounts config
                JOIN finance_accounts account
                  ON account.id = config.account_id AND account.school_id = config.school_id
                WHERE config.school_id = %s AND config.is_active = TRUE AND account.is_active = TRUE
            """, (self.school_id,))
            return {
                row['payment_mode']: f"{row['code']} - {row['name']}"
                for row in self.cursor.fetchall()
            }
        except pymysql.Error:
            return {}

    @audit_log('record_fee_payment')
    def record_payment(self, admno: int, amount: Decimal, mode: str, reference: str, bank: str, date: str, year_id: int, term_id: int, user_id: int,
                       allocation_mode: str = 'AUTOMATIC', manual_allocations: Optional[List[Dict]] = None,
                       lifecycle_source_payment_id: Optional[int] = None, lifecycle_correlation_id: Optional[str] = None) -> Dict:
        """Record a student payment with manual or priority-based votehead allocation."""
        try:
            mode = (mode or '').strip().upper()
            self._assert_student_belongs_to_school(admno)
            self._assert_academic_year_belongs_to_school(year_id)
            self._assert_term_belongs_to_school(term_id, year_id)
            fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
            fee_payments_has_receiving_account_id = self._table_has_column('fee_payments', 'receiving_account_id')
            fee_payments_has_cashier_session_id = self._table_has_column('fee_payments', 'cashier_session_id')
            allocations_has_school_id = self._table_has_column('fee_payment_allocations', 'school_id')
            receipts_has_school_id = self._table_has_column('fee_receipts', 'school_id')

            duplicate = self.find_duplicate_payment(mode, reference)
            if duplicate:
                receipt_no = duplicate.get('receipt_no') or 'unissued receipt'
                raise FeesError(
                    f"Payment reference '{reference}' already exists for {mode} "
                    f"(receipt {receipt_no}, admission {duplicate['admno']})."
                )

            receiving_account_id = self.get_payment_mode_receiving_account(mode)
            cashier_session_id = None
            if mode == 'CASH':
                if not fee_payments_has_cashier_session_id:
                    raise FeesError('Cashier-session support is unavailable. Apply migration 034 before posting cash receipts.')
                cashier_session = FinanceService(self.connection, school_id=self.school_id).get_open_cashier_session(user_id)
                if not cashier_session:
                    raise FeesError('Open a cashier session before posting a cash receipt.')
                cashier_session_id = cashier_session['id']
            self.connection.begin()
            
            amount = Decimal(str(amount))
            remaining_payment = amount
            current_balance = self.get_student_balance(admno)
            new_balance = current_balance - amount
            
            # 1. Ledger Entry (Main Payment Record)
            self.cursor.execute("""
                INSERT INTO fee_ledger (admno, academic_year_id, term_id, type, amount, balance_after, description, reference_no, transaction_date, created_by, school_id)
                VALUES (%s, %s, %s, 'PAYMENT', %s, %s, %s, %s, %s, %s, %s)
            """, (admno, year_id, term_id, amount, new_balance, f"Payment via {mode}", reference, date, user_id, self.school_id))
            ledger_id = self.cursor.lastrowid
            
            # 2. Payment Detail
            if fee_payments_has_school_id and fee_payments_has_receiving_account_id and fee_payments_has_cashier_session_id:
                self.cursor.execute("""
                    INSERT INTO fee_payments (ledger_id, admno, payment_mode, reference_number, bank_name, receiving_account_id, cashier_session_id, payment_date, amount, received_by, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (ledger_id, admno, mode, reference, bank, receiving_account_id, cashier_session_id, date, amount, user_id, self.school_id))
            elif fee_payments_has_school_id and fee_payments_has_receiving_account_id:
                self.cursor.execute("""
                    INSERT INTO fee_payments (ledger_id, admno, payment_mode, reference_number, bank_name, receiving_account_id, payment_date, amount, received_by, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (ledger_id, admno, mode, reference, bank, receiving_account_id, date, amount, user_id, self.school_id))
            elif fee_payments_has_school_id:
                self.cursor.execute("""
                    INSERT INTO fee_payments (ledger_id, admno, payment_mode, reference_number, bank_name, payment_date, amount, received_by, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (ledger_id, admno, mode, reference, bank, date, amount, user_id, self.school_id))
            else:
                self.cursor.execute("""
                    INSERT INTO fee_payments (ledger_id, admno, payment_mode, reference_number, bank_name, payment_date, amount, received_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (ledger_id, admno, mode, reference, bank, date, amount, user_id))
            payment_id = self.cursor.lastrowid
            
            # 3. Votehead Distribution (Double-Entry Allocation)
            # Fetch outstanding liabilities by votehead priority.
            self.cursor.execute("""
                SELECT votehead_id, SUM(CASE WHEN type='CHARGE' THEN amount ELSE -amount END) as outstanding
                FROM fee_ledger 
                WHERE admno = %s AND school_id = %s 
                GROUP BY votehead_id
                HAVING outstanding > 0
                ORDER BY (SELECT priority FROM fee_voteheads WHERE id = votehead_id AND school_id = %s) ASC
            """, (admno, self.school_id, self.school_id))
            liabilities = self.cursor.fetchall()

            outstanding_by_votehead = {
                liability['votehead_id']: Decimal(str(liability['outstanding']))
                for liability in liabilities
            }
            allocation_mode = (allocation_mode or 'AUTOMATIC').upper()
            if allocation_mode not in ('AUTOMATIC', 'MANUAL'):
                raise FeesError('allocation_mode must be AUTOMATIC or MANUAL.')

            allocations = []

            def add_allocation(votehead_id: int, allocation_amount: Decimal) -> None:
                if allocation_amount <= 0:
                    return
                if allocations_has_school_id:
                    self.cursor.execute("""
                        INSERT INTO fee_payment_allocations (payment_id, votehead_id, amount, school_id)
                        VALUES (%s, %s, %s, %s)
                    """, (payment_id, votehead_id, allocation_amount, self.school_id))
                else:
                    self.cursor.execute("""
                        INSERT INTO fee_payment_allocations (payment_id, votehead_id, amount)
                        VALUES (%s, %s, %s)
                    """, (payment_id, votehead_id, allocation_amount))
                allocations.append({'votehead_id': votehead_id, 'amount': allocation_amount})

            if allocation_mode == 'MANUAL':
                manual_allocations = manual_allocations or []
                seen_voteheads = set()
                for allocation in manual_allocations:
                    try:
                        votehead_id = int(allocation.get('votehead_id'))
                        allocation_amount = Decimal(str(allocation.get('amount')))
                    except (AttributeError, TypeError, ValueError, InvalidOperation):
                        raise FeesError('Each manual allocation requires a valid votehead_id and amount.')

                    if votehead_id in seen_voteheads:
                        raise FeesError('A votehead can only be selected once for manual allocation.')
                    if allocation_amount <= 0:
                        raise FeesError('Manual allocation amounts must be greater than zero.')
                    if allocation_amount > remaining_payment:
                        raise FeesError('Manual allocation total cannot exceed the receipt amount.')
                    if votehead_id not in outstanding_by_votehead:
                        raise FeesError('Manual allocation must target an outstanding votehead for this student.')
                    if allocation_amount > outstanding_by_votehead[votehead_id]:
                        raise FeesError('Manual allocation cannot exceed the votehead outstanding balance.')

                    add_allocation(votehead_id, allocation_amount)
                    outstanding_by_votehead[votehead_id] -= allocation_amount
                    remaining_payment -= allocation_amount
                    seen_voteheads.add(votehead_id)
            
            for liab in liabilities:
                if remaining_payment <= 0:
                    break
                
                pay_amount = min(remaining_payment, outstanding_by_votehead[liab['votehead_id']])
                if pay_amount > 0:
                    add_allocation(liab['votehead_id'], pay_amount)
                    remaining_payment -= pay_amount

            # If still remaining (Advance Payment / Arrears clearing without specific votehead)
            if remaining_payment > 0:
                # Assign to tuition by default or general if tuition not in list
                self.cursor.execute("SELECT id FROM fee_voteheads WHERE name = 'Tuition' AND school_id = %s LIMIT 1", (self.school_id,))
                tuition = self.cursor.fetchone()
                vid = tuition['id'] if tuition else 1 # Fallback to first votehead
                add_allocation(vid, remaining_payment)

            # 4. Generate Receipt Number
            receipt_no = f"RCP-{datetime.now().year}-{str(payment_id).zfill(5)}"
            if receipts_has_school_id:
                self.cursor.execute("""
                    INSERT INTO fee_receipts (payment_id, receipt_no, issued_by, school_id)
                    VALUES (%s, %s, %s, %s)
                """, (payment_id, receipt_no, user_id, self.school_id))
            else:
                self.cursor.execute("""
                    INSERT INTO fee_receipts (payment_id, receipt_no, issued_by)
                    VALUES (%s, %s, %s)
                """, (payment_id, receipt_no, user_id))

            lifecycle_snapshot = {
                'payment': {
                    'admno': admno,
                    'amount': amount,
                    'payment_mode': mode,
                    'reference_number': reference,
                    'payment_date': date,
                    'receiving_account_id': receiving_account_id,
                },
                'receipt_no': receipt_no,
                'allocations': allocations,
            }
            correlation_id = lifecycle_correlation_id or str(uuid.uuid4())
            self.cursor.execute("""
                INSERT INTO fee_receipt_lifecycle_events
                    (school_id, payment_id, event_type, status_after, actor_user_id, correlation_id, snapshot_json)
                VALUES (%s, %s, 'POSTED', 'COMPLETED', %s, %s, %s)
            """, (
                self.school_id, payment_id, user_id, correlation_id,
                json.dumps(lifecycle_snapshot, default=str, sort_keys=True),
            ))
            if lifecycle_source_payment_id:
                self.cursor.execute("""
                    INSERT INTO fee_receipt_lifecycle_events
                        (school_id, payment_id, event_type, status_after, reason, actor_user_id, correlation_id, replacement_payment_id, snapshot_json)
                    VALUES (%s, %s, 'REPOSTED', 'CANCELLED', %s, %s, %s, %s, %s)
                """, (
                    self.school_id, lifecycle_source_payment_id,
                    f'Reposted as {receipt_no}', user_id, correlation_id, payment_id,
                    json.dumps({'replacement_receipt_no': receipt_no}, sort_keys=True),
                ))
            
            self.connection.commit()
            return {
                'payment_id': payment_id,
                'receipt_no': receipt_no,
                'balance': new_balance,
                'allocations': [
                    {'votehead_id': allocation['votehead_id'], 'amount': float(allocation['amount'])}
                    for allocation in allocations
                ]
            }
        except pymysql.IntegrityError:
            self.connection.rollback()
            raise FeesError(f"Payment reference '{reference}' already exists for this mode.")
        except FeesError:
            self.connection.rollback()
            raise
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Payment failed: {str(e)}")

    @audit_log('repost_fee_receipt')
    def repost_cancelled_receipt(self, payment_id: int, new_reference: str, posting_date: str, user_id: int) -> Dict:
        """Create a replacement receipt for a cancelled payment without reactivating it."""
        reference = (new_reference or '').strip()
        if not reference:
            raise FeesError('A new payment reference is required when reposting a receipt.')
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        if fee_payments_has_school_id:
            self.cursor.execute("""
                SELECT fp.*, fl.academic_year_id, fl.term_id
                FROM fee_payments fp
                JOIN fee_ledger fl ON fp.ledger_id = fl.id AND fp.school_id = fl.school_id
                WHERE fp.id = %s AND fp.school_id = %s
            """, (payment_id, self.school_id))
        else:
            self.cursor.execute("""
                SELECT fp.*, fl.academic_year_id, fl.term_id
                FROM fee_payments fp
                JOIN fee_ledger fl ON fp.ledger_id = fl.id
                WHERE fp.id = %s AND fl.school_id = %s
            """, (payment_id, self.school_id))
        original = self.cursor.fetchone()
        if not original:
            raise FeesError('Original receipt not found.')
        if original['status'] != 'CANCELLED':
            raise FeesError('Only cancelled receipts can be reposted.')

        return self.record_payment(
            admno=original['admno'],
            amount=Decimal(str(original['amount'])),
            mode=original['payment_mode'],
            reference=reference,
            bank=original.get('bank_name') or '',
            date=posting_date,
            year_id=original['academic_year_id'],
            term_id=original['term_id'],
            user_id=user_id,
            lifecycle_source_payment_id=payment_id,
            lifecycle_correlation_id=str(uuid.uuid4()),
        )

    def _recalculate_student_ledger_balances(self, admno: int) -> None:
        """Rebuild stored running balances after a financial correction."""
        self.cursor.execute("""
            SELECT id, type, amount, description
            FROM fee_ledger
            WHERE admno = %s AND school_id = %s
            ORDER BY transaction_date ASC, id ASC
        """, (admno, self.school_id))
        running_balance = Decimal('0.00')
        for row in self.cursor.fetchall():
            amount = Decimal(str(row['amount']))
            entry_type = row['type']
            description = row.get('description') or ''
            if entry_type in ('CHARGE', 'DEBIT', 'REFUND') or (
                entry_type == 'ADJUSTMENT' and description.startswith('VOID RECEIPT:')
            ):
                running_balance += amount
            else:
                running_balance -= amount
            self.cursor.execute(
                "UPDATE fee_ledger SET balance_after = %s WHERE id = %s AND school_id = %s",
                (running_balance, row['id'], self.school_id),
            )

    def reallocate_payment(self, reference_no: str, from_admno: int, to_admno: int, user_id: int, reason: str):
        """Transfer a completed payment and rebuild both affected running balances."""
        try:
            reason = (reason or '').strip()
            if from_admno == to_admno:
                raise FeesError('The source and target students must be different.')
            if not reason:
                raise FeesError('A reallocation reason is required.')
            self._assert_student_belongs_to_school(from_admno)
            self._assert_student_belongs_to_school(to_admno)
            fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
            self.connection.begin()
            
            # 1. Fetch payment
            if fee_payments_has_school_id:
                self.cursor.execute("SELECT * FROM fee_payments WHERE reference_number = %s AND admno = %s AND school_id = %s", (reference_no, from_admno, self.school_id))
            else:
                self.cursor.execute("""
                    SELECT fp.*
                    FROM fee_payments fp
                    JOIN fee_ledger fl ON fp.ledger_id = fl.id
                    WHERE fp.reference_number = %s AND fp.admno = %s AND fl.school_id = %s
                """, (reference_no, from_admno, self.school_id))
            payment = self.cursor.fetchone()
            if not payment:
                raise FeesError("Payment record not found.")
            if payment['status'] != 'COMPLETED':
                raise FeesError('Only completed receipts can be reallocated.')

            correlation_id = str(uuid.uuid4())
            
            # 2. Record in audit trail
            self.cursor.execute("""
                INSERT INTO fee_reallocation_log (original_admno, new_admno, reference_no, amount, payment_id, reason, reallocated_by, school_id, correlation_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (from_admno, to_admno, reference_no, payment['amount'], payment['id'], reason, user_id, self.school_id, correlation_id))
            
            # 3. Update main records
            if fee_payments_has_school_id:
                self.cursor.execute("UPDATE fee_payments SET admno = %s WHERE id = %s AND school_id = %s", (to_admno, payment['id'], self.school_id))
            else:
                self.cursor.execute("UPDATE fee_payments SET admno = %s WHERE id = %s", (to_admno, payment['id']))
            self.cursor.execute("UPDATE fee_ledger SET admno = %s WHERE id = %s AND school_id = %s", (to_admno, payment['ledger_id'], self.school_id))

            self._recalculate_student_ledger_balances(from_admno)
            self._recalculate_student_ledger_balances(to_admno)
            self.cursor.execute("""
                INSERT INTO fee_receipt_lifecycle_events
                    (school_id, payment_id, event_type, status_after, reason, actor_user_id, correlation_id, snapshot_json)
                VALUES (%s, %s, 'TRANSFERRED', 'COMPLETED', %s, %s, %s, %s)
            """, (
                self.school_id, payment['id'], reason, user_id, correlation_id,
                json.dumps({'from_admno': from_admno, 'to_admno': to_admno, 'reference_no': reference_no}, sort_keys=True),
            ))
            
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Reallocation failed: {str(e)}")


    def get_student_statement(self, admno: int, year_id: Optional[int] = None) -> List[Dict]:
        """Fetch full transaction history for a student, consolidated by reference."""
        query = """
            SELECT 
                MAX(fl.id) as id, 
                fl.admno, 
                fl.type, 
                SUM(fl.amount) as amount, 
                MAX(fl.balance_after) as balance_after,
                COALESCE(
                    NULLIF(MAX(fl.description), ''),
                    CASE 
                        WHEN fl.reference_no LIKE 'INV-%%' AND fl.reference_no NOT LIKE 'INV-SPEC-%%' 
                        THEN 'Term Fees' 
                        ELSE MAX(fv.name) 
                    END,
                    fl.type
                ) as description,
                fl.reference_no, 
                fl.transaction_date,
                MAX(fv.name) as votehead_name, 
                MAX(u.username) as created_by_name
            FROM fee_ledger fl
            LEFT JOIN fee_voteheads fv ON fl.votehead_id = fv.id AND fl.school_id = fv.school_id
            LEFT JOIN users u ON fl.created_by = u.userNo AND fl.school_id = u.school_id
            WHERE fl.admno = %s AND fl.school_id = %s
        """
        params = [admno, self.school_id]
        if year_id:
            query += " AND fl.academic_year_id = %s"
            params.append(year_id)
        
        query += " GROUP BY fl.reference_no, fl.type, fl.transaction_date"
        query += " ORDER BY id ASC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_student_statement_summary(self, admno: int, year_id: Optional[int] = None) -> List[Dict]:
        """Return an auditable year-and-term roll-up for a student's fee ledger."""
        signed_amount = """
            CASE
                WHEN fl.type IN ('CHARGE', 'DEBIT', 'REFUND')
                  OR (fl.type = 'ADJUSTMENT' AND (fl.description LIKE 'DEBIT NOTE:%%' OR fl.description LIKE 'VOID RECEIPT:%%'))
                    THEN fl.amount
                WHEN fl.type IN ('PAYMENT', 'CREDIT')
                  OR (fl.type = 'ADJUSTMENT' AND fl.description LIKE 'CREDIT NOTE:%%')
                    THEN -fl.amount
                ELSE 0
            END
        """
        query = f"""
            SELECT
                fl.academic_year_id,
                ay.year AS academic_year,
                fl.term_id,
                utd.term_number,
                CAST(SUBSTRING_INDEX(GROUP_CONCAT(fl.balance_after ORDER BY fl.transaction_date, fl.id), ',', 1) AS DECIMAL(15, 2))
                    - CAST(SUBSTRING_INDEX(GROUP_CONCAT(({signed_amount}) ORDER BY fl.transaction_date, fl.id), ',', 1) AS DECIMAL(15, 2))
                    AS opening_balance,
                COALESCE(SUM(CASE WHEN fl.type = 'CHARGE' THEN fl.amount ELSE 0 END), 0) AS charges,
                COALESCE(SUM(CASE
                    WHEN fl.type = 'DEBIT'
                      OR (fl.type = 'ADJUSTMENT' AND (fl.description LIKE 'DEBIT NOTE:%%' OR fl.description LIKE 'VOID RECEIPT:%%'))
                    THEN fl.amount ELSE 0 END), 0) AS debits,
                COALESCE(SUM(CASE WHEN fl.type = 'PAYMENT' THEN fl.amount ELSE 0 END), 0) AS payments,
                COALESCE(SUM(CASE
                    WHEN fl.type = 'CREDIT' AND fl.reference_no LIKE 'WVR-%%' THEN fl.amount ELSE 0 END), 0) AS waivers,
                COALESCE(SUM(CASE
                    WHEN (fl.type = 'CREDIT' AND (fl.reference_no IS NULL OR fl.reference_no NOT LIKE 'WVR-%%'))
                      OR (fl.type = 'ADJUSTMENT' AND fl.description LIKE 'CREDIT NOTE:%%')
                    THEN fl.amount ELSE 0 END), 0) AS credits,
                COALESCE(SUM(CASE WHEN fl.type = 'REFUND' THEN fl.amount ELSE 0 END), 0) AS refunds,
                CAST(SUBSTRING_INDEX(GROUP_CONCAT(fl.balance_after ORDER BY fl.transaction_date DESC, fl.id DESC), ',', 1) AS DECIMAL(15, 2))
                    AS closing_balance,
                COUNT(*) AS transaction_count
            FROM fee_ledger fl
            JOIN academic_years ay ON fl.academic_year_id = ay.id AND fl.school_id = ay.school_id
            JOIN uniform_term_dates utd ON fl.term_id = utd.id AND fl.school_id = utd.school_id
            WHERE fl.admno = %s AND fl.school_id = %s
        """
        params = [admno, self.school_id]
        if year_id:
            query += " AND fl.academic_year_id = %s"
            params.append(year_id)
        query += " GROUP BY fl.academic_year_id, ay.year, fl.term_id, utd.term_number"
        query += " ORDER BY ay.year DESC, utd.term_number DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_recent_payments(self, admno: int, limit: int = 5) -> List[Dict]:
        """Fetch most recent payments for a student."""
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        receipts_has_school_id = self._table_has_column('fee_receipts', 'school_id')

        if fee_payments_has_school_id and receipts_has_school_id:
            self.cursor.execute(
                """
                SELECT fp.*, fr.receipt_no
                FROM fee_payments fp
                LEFT JOIN fee_receipts fr ON fp.id = fr.payment_id AND fp.school_id = fr.school_id
                WHERE fp.admno = %s AND fp.school_id = %s
                ORDER BY fp.payment_date DESC, fp.id DESC
                LIMIT %s
                """,
                (admno, self.school_id, limit)
            )
        else:
            self.cursor.execute(
                """
                SELECT fp.*, fr.receipt_no
                FROM fee_payments fp
                LEFT JOIN fee_receipts fr ON fp.id = fr.payment_id
                JOIN fee_ledger fl ON fp.ledger_id = fl.id
                WHERE fp.admno = %s AND fl.school_id = %s
                ORDER BY fp.payment_date DESC, fp.id DESC
                LIMIT %s
                """,
                (admno, self.school_id, limit)
            )
        return self.cursor.fetchall()

    def get_receipts_register(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                              admno: Optional[int] = None, mode: Optional[str] = None,
                              query_text: Optional[str] = None, status: Optional[str] = None) -> List[Dict]:
        """Fetch list of receipts with filtering."""
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        receipts_has_school_id = self._table_has_column('fee_receipts', 'school_id')

        if fee_payments_has_school_id and receipts_has_school_id:
            query = """
                SELECT fp.*, fr.receipt_no, si.FName, si.SName, ay.year as year_name, utd.term_number,
                       u.username as received_by_name
                FROM fee_payments fp
                JOIN fee_receipts fr ON fp.id = fr.payment_id AND fp.school_id = fr.school_id
                JOIN studentinfo si ON fp.admno = si.AdmNo AND fp.school_id = si.school_id
                JOIN fee_ledger fl ON fp.ledger_id = fl.id AND fp.school_id = fl.school_id
                JOIN academic_years ay ON fl.academic_year_id = ay.id AND fl.school_id = ay.school_id
                JOIN uniform_term_dates utd ON fl.term_id = utd.id AND fl.school_id = utd.school_id
                LEFT JOIN users u ON fp.received_by = u.userNo AND fp.school_id = u.school_id
                WHERE fp.school_id = %s
            """
            params = [self.school_id]
        else:
            query = """
                SELECT fp.*, fr.receipt_no, si.FName, si.SName, ay.year as year_name, utd.term_number,
                       u.username as received_by_name
                FROM fee_payments fp
                JOIN fee_receipts fr ON fp.id = fr.payment_id
                JOIN fee_ledger fl ON fp.ledger_id = fl.id AND fl.school_id = %s
                JOIN studentinfo si ON fp.admno = si.AdmNo AND si.school_id = fl.school_id
                JOIN academic_years ay ON fl.academic_year_id = ay.id AND ay.school_id = fl.school_id
                JOIN uniform_term_dates utd ON fl.term_id = utd.id AND utd.school_id = fl.school_id
                LEFT JOIN users u ON fp.received_by = u.userNo AND u.school_id = si.school_id
                WHERE fl.school_id = %s
            """
            params = [self.school_id, self.school_id]
        if start_date:
            query += " AND fp.payment_date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND fp.payment_date <= %s"
            params.append(end_date)
        if admno:
            query += " AND fp.admno = %s"
            params.append(admno)
        if mode:
            query += " AND fp.payment_mode = %s"
            params.append(mode)
        if status:
            query += " AND fp.status = %s"
            params.append(status)
        if query_text:
            search_term = f"%{query_text.strip()}%"
            query += " AND (fr.receipt_no LIKE %s OR fp.reference_number LIKE %s OR CONCAT_WS(' ', si.FName, si.MName, si.SName) LIKE %s)"
            params.extend([search_term, search_term, search_term])
            
        query += " ORDER BY fp.id DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_receipt_lifecycle(self, payment_id: int) -> List[Dict]:
        """Return immutable lifecycle events for a receipt in the active school."""
        self.cursor.execute("""
            SELECT events.*, users.username AS actor_name
            FROM fee_receipt_lifecycle_events events
            LEFT JOIN users ON users.userNo = events.actor_user_id AND users.school_id = events.school_id
            WHERE events.payment_id = %s AND events.school_id = %s
            ORDER BY events.id ASC
        """, (payment_id, self.school_id))
        return self.cursor.fetchall()

    def get_receipt_lifecycle_register(self, start_date: Optional[str] = None,
                                       end_date: Optional[str] = None,
                                       event_type: Optional[str] = None) -> List[Dict]:
        """Return immutable receipt lifecycle events for audit and reconciliation."""
        query = """
            SELECT events.*, receipts.receipt_no, payments.reference_number, payments.amount,
                   payments.payment_mode, payments.status AS payment_status,
                   students.AdmNo AS admno, students.FName, students.SName,
                   users.username AS actor_name
            FROM fee_receipt_lifecycle_events events
            JOIN fee_payments payments ON events.payment_id = payments.id AND events.school_id = payments.school_id
            LEFT JOIN fee_receipts receipts ON payments.id = receipts.payment_id AND payments.school_id = receipts.school_id
            LEFT JOIN studentinfo students ON payments.admno = students.AdmNo AND payments.school_id = students.school_id
            LEFT JOIN users ON events.actor_user_id = users.userNo AND events.school_id = users.school_id
            WHERE events.school_id = %s
        """
        params = [self.school_id]
        if start_date:
            query += " AND DATE(events.occurred_at) >= %s"
            params.append(start_date)
        if end_date:
            query += " AND DATE(events.occurred_at) <= %s"
            params.append(end_date)
        if event_type:
            query += " AND events.event_type = %s"
            params.append(event_type)
        query += " ORDER BY events.id DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_reallocation_register(self, start_date: Optional[str] = None,
                                  end_date: Optional[str] = None) -> List[Dict]:
        """Return immutable payment-reallocation audit records for the active school."""
        query = """
            SELECT reallocations.*, source.FName AS source_first_name, source.SName AS source_last_name,
                   destination.FName AS destination_first_name, destination.SName AS destination_last_name,
                   users.username AS reallocated_by_name, receipts.receipt_no
            FROM fee_reallocation_log reallocations
            LEFT JOIN studentinfo source
              ON reallocations.original_admno = source.AdmNo AND reallocations.school_id = source.school_id
            LEFT JOIN studentinfo destination
              ON reallocations.new_admno = destination.AdmNo AND reallocations.school_id = destination.school_id
            LEFT JOIN users ON reallocations.reallocated_by = users.userNo AND reallocations.school_id = users.school_id
            LEFT JOIN fee_receipts receipts
              ON reallocations.payment_id = receipts.payment_id AND reallocations.school_id = receipts.school_id
            WHERE reallocations.school_id = %s
        """
        params = [self.school_id]
        if start_date:
            query += " AND DATE(reallocations.reallocated_at) >= %s"
            params.append(start_date)
        if end_date:
            query += " AND DATE(reallocations.reallocated_at) <= %s"
            params.append(end_date)
        query += " ORDER BY reallocations.id DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def record_receipt_print(self, payment_id: int, user_id: int) -> str:
        """Append a print or reprint event after confirming receipt ownership."""
        self.cursor.execute(
            "SELECT id FROM fee_payments WHERE id = %s AND school_id = %s",
            (payment_id, self.school_id),
        )
        if not self.cursor.fetchone():
            raise FeesError('Receipt not found.')
        self.cursor.execute("""
            SELECT COUNT(*) AS print_count
            FROM fee_receipt_lifecycle_events
            WHERE payment_id = %s AND school_id = %s AND event_type IN ('PRINTED', 'REPRINTED')
        """, (payment_id, self.school_id))
        event_type = 'REPRINTED' if self.cursor.fetchone()['print_count'] else 'PRINTED'
        self.cursor.execute("""
            INSERT INTO fee_receipt_lifecycle_events
                (school_id, payment_id, event_type, status_after, actor_user_id, correlation_id, snapshot_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            self.school_id, payment_id, event_type, 'COMPLETED', user_id, str(uuid.uuid4()),
            json.dumps({'rendered_for_print': True}, sort_keys=True),
        ))
        self.connection.commit()
        return event_type

    def archive_receipt(self, payment_id: int, reason: str, user_id: int) -> None:
        """Append an archive event without deleting or changing the underlying payment."""
        reason = (reason or '').strip()
        if not reason:
            raise FeesError('An archive reason is required.')
        self.cursor.execute(
            "SELECT id FROM fee_payments WHERE id = %s AND school_id = %s",
            (payment_id, self.school_id),
        )
        if not self.cursor.fetchone():
            raise FeesError('Receipt not found.')
        self.cursor.execute("""
            SELECT id FROM fee_receipt_lifecycle_events
            WHERE payment_id = %s AND school_id = %s AND event_type = 'ARCHIVED'
            LIMIT 1
        """, (payment_id, self.school_id))
        if self.cursor.fetchone():
            raise FeesError('Receipt is already archived.')
        self.cursor.execute("""
            INSERT INTO fee_receipt_lifecycle_events
                (school_id, payment_id, event_type, status_after, reason, actor_user_id, correlation_id, snapshot_json)
            VALUES (%s, %s, 'ARCHIVED', 'ARCHIVED', %s, %s, %s, %s)
        """, (
            self.school_id, payment_id, reason, user_id, str(uuid.uuid4()),
            json.dumps({'archived': True}, sort_keys=True),
        ))
        self.connection.commit()

    def get_receipt_details(self, payment_id: int) -> Optional[Dict]:
        """Fetch full details of a receipt including allocations."""
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        fee_payments_has_receiving_account_id = self._table_has_column('fee_payments', 'receiving_account_id')
        receipts_has_school_id = self._table_has_column('fee_receipts', 'school_id')
        allocations_has_school_id = self._table_has_column('fee_payment_allocations', 'school_id')

        def _resolve_student_class_name(admno: int) -> Optional[str]:
            """Resolve class display name across new and legacy allocation schemas."""
            class_queries = [
                (
                    """
                    SELECT c.display_name as class_name
                    FROM class_allocation ca
                    JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
                    WHERE ca.student_id = %s AND ca.is_current = TRUE AND ca.school_id = %s
                    ORDER BY ca.id DESC
                    LIMIT 1
                    """,
                    (admno, self.school_id),
                ),
                (
                    """
                    SELECT c.display_name as class_name
                    FROM class_allocation ca
                    JOIN classes c ON ca.class_id = c.classID
                    WHERE ca.student_id = %s AND ca.is_current = TRUE
                    ORDER BY ca.id DESC
                    LIMIT 1
                    """,
                    (admno,),
                ),
                (
                    """
                    SELECT c.display_name as class_name
                    FROM classallocation lca
                    JOIN classes c ON lca.classID = c.classID AND lca.school_id = c.school_id
                    WHERE lca.AdmNo = %s AND lca.school_id = %s
                    ORDER BY lca.AllcDate DESC
                    LIMIT 1
                    """,
                    (admno, self.school_id),
                ),
                (
                    """
                    SELECT c.display_name as class_name
                    FROM classallocation lca
                    JOIN classes c ON lca.classID = c.classID
                    WHERE lca.AdmNo = %s
                    ORDER BY lca.AllcDate DESC
                    LIMIT 1
                    """,
                    (admno,),
                ),
            ]

            for query, params in class_queries:
                try:
                    self.cursor.execute(query, params)
                    row = self.cursor.fetchone()
                    if row and row.get('class_name'):
                        return row['class_name']
                except pymysql.Error:
                    continue
            return None

        if fee_payments_has_school_id and receipts_has_school_id:
            account_select = ""
            account_join = ""
            if fee_payments_has_receiving_account_id:
                account_select = ", receiving_account.code AS receiving_account_code, receiving_account.name AS receiving_account_name"
                account_join = " LEFT JOIN finance_accounts receiving_account ON fp.receiving_account_id = receiving_account.id AND fp.school_id = receiving_account.school_id"
            self.cursor.execute(f"""
                SELECT fp.*, fr.receipt_no, fr.issued_at, si.FName, si.MName, si.SName,
                       ay.year as year_name, utd.term_number,
                       u.username as issued_by_name, fl.academic_year_id, fl.term_id,
                       fl.balance_after, COALESCE(fl.reference_no, fp.reference_number) as reference_no{account_select}
                FROM fee_payments fp
                JOIN fee_receipts fr ON fp.id = fr.payment_id AND fp.school_id = fr.school_id
                JOIN studentinfo si ON fp.admno = si.AdmNo AND fp.school_id = si.school_id
                JOIN fee_ledger fl ON fp.ledger_id = fl.id AND fp.school_id = fl.school_id
                LEFT JOIN academic_years ay ON fl.academic_year_id = ay.id AND fl.school_id = ay.school_id
                LEFT JOIN uniform_term_dates utd ON fl.term_id = utd.id AND fl.school_id = utd.school_id
                LEFT JOIN users u ON fp.received_by = u.userNo
                {account_join}
                WHERE fp.id = %s AND fp.school_id = %s
            """, (payment_id, self.school_id))
        else:
            self.cursor.execute("""
                SELECT fp.*, fr.receipt_no, fr.issued_at, si.FName, si.MName, si.SName,
                       ay.year as year_name, utd.term_number,
                       u.username as issued_by_name, fl.academic_year_id, fl.term_id,
                       fl.balance_after, COALESCE(fl.reference_no, fp.reference_number) as reference_no
                FROM fee_payments fp
                JOIN fee_receipts fr ON fp.id = fr.payment_id
                JOIN fee_ledger fl ON fp.ledger_id = fl.id AND fl.school_id = %s
                JOIN studentinfo si ON fp.admno = si.AdmNo AND si.school_id = fl.school_id
                LEFT JOIN academic_years ay ON fl.academic_year_id = ay.id AND ay.school_id = fl.school_id
                LEFT JOIN uniform_term_dates utd ON fl.term_id = utd.id AND utd.school_id = fl.school_id
                LEFT JOIN users u ON fp.received_by = u.userNo
                WHERE fp.id = %s
            """, (self.school_id, payment_id))
        receipt = self.cursor.fetchone()
        
        if receipt:
            receipt['display_name'] = _resolve_student_class_name(receipt['admno'])
            # Get allocations
            if allocations_has_school_id:
                self.cursor.execute("""
                    SELECT fpa.*, fv.name as votehead_name
                    FROM fee_payment_allocations fpa
                    JOIN fee_voteheads fv ON fpa.votehead_id = fv.id AND fpa.school_id = fv.school_id
                    WHERE fpa.payment_id = %s AND fpa.school_id = %s
                """, (payment_id, self.school_id))
            else:
                self.cursor.execute("""
                    SELECT fpa.*, fv.name as votehead_name
                    FROM fee_payment_allocations fpa
                    JOIN fee_voteheads fv ON fpa.votehead_id = fv.id
                    WHERE fpa.payment_id = %s AND fv.school_id = %s
                """, (payment_id, self.school_id))
            receipt['allocations'] = self.cursor.fetchall()
            
        return receipt

    def update_payment_details(self, payment_id: int, mode: str, reference: str, bank: str, date: str, user_id: int) -> bool:
        """Update non-amount fields of a payment."""
        try:
            fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
            self.connection.begin()
            
            # Check if payment exists and isn't voided
            if fee_payments_has_school_id:
                self.cursor.execute("SELECT ledger_id, status FROM fee_payments WHERE id = %s AND school_id = %s", (payment_id, self.school_id))
            else:
                self.cursor.execute("""
                    SELECT fp.ledger_id, fp.status
                    FROM fee_payments fp
                    JOIN fee_ledger fl ON fp.ledger_id = fl.id
                    WHERE fp.id = %s AND fl.school_id = %s
                """, (payment_id, self.school_id))
            payment = self.cursor.fetchone()
            if not payment:
                raise FeesError("Payment record not found.")
            if payment['status'] in ['CANCELLED', 'REVERSED']:
                raise FeesError("Cannot edit a voided/reversed receipt.")

            # Update fee_payments
            if fee_payments_has_school_id:
                self.cursor.execute("""
                    UPDATE fee_payments 
                    SET payment_mode = %s, reference_number = %s, bank_name = %s, payment_date = %s
                    WHERE id = %s AND school_id = %s
                """, (mode, reference, bank, date, payment_id, self.school_id))
            else:
                self.cursor.execute("""
                    UPDATE fee_payments 
                    SET payment_mode = %s, reference_number = %s, bank_name = %s, payment_date = %s
                    WHERE id = %s
                """, (mode, reference, bank, date, payment_id))
            
            # Update fee_ledger description and reference
            self.cursor.execute("""
                UPDATE fee_ledger 
                SET description = %s, reference_no = %s, transaction_date = %s
                WHERE id = %s AND school_id = %s
            """, (f"Payment via {mode}", reference, date, payment['ledger_id'], self.school_id))
            
            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Update failed: {str(e)}")

    @audit_log('void_fee_receipt')
    def void_receipt(self, payment_id: int, user_id: int, reason: str) -> bool:
        """Void a receipt by reversing its effects on student's ledger."""
        try:
            fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
            self.connection.begin()
            
            # 1. Fetch original payment
            if fee_payments_has_school_id:
                self.cursor.execute("SELECT * FROM fee_payments WHERE id = %s AND school_id = %s", (payment_id, self.school_id))
            else:
                self.cursor.execute("""
                    SELECT fp.*
                    FROM fee_payments fp
                    JOIN fee_ledger fl ON fp.ledger_id = fl.id
                    WHERE fp.id = %s AND fl.school_id = %s
                """, (payment_id, self.school_id))
            payment = self.cursor.fetchone()
            if not payment:
                raise FeesError("Payment record not found.")
            if payment['status'] != 'COMPLETED':
                raise FeesError(f"Receipt is already {payment['status']}.")

            reason = (reason or '').strip()
            if not reason:
                raise FeesError('A cancellation reason is required.')

            allocations_has_school_id = self._table_has_column('fee_payment_allocations', 'school_id')
            if allocations_has_school_id:
                self.cursor.execute("""
                    SELECT votehead_id, amount FROM fee_payment_allocations
                    WHERE payment_id = %s AND school_id = %s
                    ORDER BY id ASC
                """, (payment_id, self.school_id))
            else:
                self.cursor.execute("""
                    SELECT votehead_id, amount FROM fee_payment_allocations
                    WHERE payment_id = %s ORDER BY id ASC
                """, (payment_id,))
            allocations = self.cursor.fetchall()

            admno = payment['admno']
            amount = Decimal(str(payment['amount']))
            
            # 2. Get period details from original ledger entry
            self.cursor.execute("SELECT academic_year_id, term_id FROM fee_ledger WHERE id = %s AND school_id = %s", (payment['ledger_id'], self.school_id))
            ledger = self.cursor.fetchone()
            
            # 3. Create reversal ledger entry
            current_balance = self.get_student_balance(admno)
            new_balance = current_balance + amount # Restore balance (adding back the credit)
            
            void_ref = f"VOID-{payment['reference_number']}"
            self.cursor.execute("""
                INSERT INTO fee_ledger (admno, academic_year_id, term_id, type, amount, balance_after, description, reference_no, transaction_date, created_by, school_id)
                VALUES (%s, %s, %s, 'ADJUSTMENT', %s, %s, %s, %s, CURDATE(), %s, %s)
            """, (admno, ledger['academic_year_id'], ledger['term_id'], amount, new_balance, 
                 f"VOID RECEIPT: {reason} (Ref: {payment['reference_number']})", void_ref, user_id, self.school_id))
            
            # 4. Update payment status
            if fee_payments_has_school_id:
                self.cursor.execute("UPDATE fee_payments SET status = 'CANCELLED' WHERE id = %s AND school_id = %s", (payment_id, self.school_id))
            else:
                self.cursor.execute("UPDATE fee_payments SET status = 'CANCELLED' WHERE id = %s", (payment_id,))
            
            snapshot = {
                'payment': payment,
                'allocations': allocations,
                'reversal_reference': void_ref,
            }
            self.cursor.execute("""
                INSERT INTO fee_receipt_lifecycle_events
                    (school_id, payment_id, event_type, status_after, reason, actor_user_id, correlation_id, snapshot_json)
                VALUES (%s, %s, 'CANCELLED', 'CANCELLED', %s, %s, %s, %s)
            """, (
                self.school_id, payment_id, reason, user_id, str(uuid.uuid4()),
                json.dumps(snapshot, default=str, sort_keys=True),
            ))

            self.connection.commit()
            return True
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Voiding failed: {str(e)}")


    # =========================================================================
    # 4. REPORTING
    # =========================================================================

    def get_collection_summary(self, start_date: str, end_date: str) -> Dict:
        """Daily/Weekly/Monthly collection summary."""
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        if fee_payments_has_school_id:
            self.cursor.execute("""
                SELECT 
                    payment_mode, 
                    SUM(amount) as total_amount,
                    COUNT(*) as count
                FROM fee_payments
                WHERE payment_date BETWEEN %s AND %s AND status = 'COMPLETED' AND school_id = %s
                GROUP BY payment_mode
            """, (start_date, end_date, self.school_id))
        else:
            self.cursor.execute("""
                SELECT 
                    fp.payment_mode,
                    SUM(fp.amount) as total_amount,
                    COUNT(*) as count
                FROM fee_payments fp
                JOIN fee_ledger fl ON fp.ledger_id = fl.id
                WHERE fp.payment_date BETWEEN %s AND %s
                  AND fp.status = 'COMPLETED'
                  AND fl.school_id = %s
                GROUP BY fp.payment_mode
            """, (start_date, end_date, self.school_id))
        return self.cursor.fetchall()

    def get_collection_status_summary(self, start_date: str, end_date: str) -> List[Dict]:
        """Summarize the current status of receipts posted within a reporting window."""
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        if fee_payments_has_school_id:
            self.cursor.execute("""
                SELECT status, payment_mode, SUM(amount) AS total_amount, COUNT(*) AS count
                FROM fee_payments
                WHERE payment_date BETWEEN %s AND %s AND school_id = %s
                GROUP BY status, payment_mode
                ORDER BY status ASC, payment_mode ASC
            """, (start_date, end_date, self.school_id))
        else:
            self.cursor.execute("""
                SELECT fp.status, fp.payment_mode, SUM(fp.amount) AS total_amount, COUNT(*) AS count
                FROM fee_payments fp
                JOIN fee_ledger fl ON fp.ledger_id = fl.id
                WHERE fp.payment_date BETWEEN %s AND %s AND fl.school_id = %s
                GROUP BY fp.status, fp.payment_mode
                ORDER BY fp.status ASC, fp.payment_mode ASC
            """, (start_date, end_date, self.school_id))
        return self.cursor.fetchall()

    def get_collection_category_summary(self, start_date: str, end_date: str) -> List[Dict]:
        """Summarize completed collections by the student's current category."""
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        if fee_payments_has_school_id:
            self.cursor.execute("""
                SELECT COALESCE(students.category, 'Unclassified') AS category,
                       SUM(payments.amount) AS total_amount, COUNT(*) AS count
                FROM fee_payments payments
                JOIN studentinfo students
                  ON payments.admno = students.AdmNo AND payments.school_id = students.school_id
                WHERE payments.payment_date BETWEEN %s AND %s
                  AND payments.status = 'COMPLETED' AND payments.school_id = %s
                GROUP BY students.category
                ORDER BY total_amount DESC, category ASC
            """, (start_date, end_date, self.school_id))
        else:
            self.cursor.execute("""
                SELECT COALESCE(students.category, 'Unclassified') AS category,
                       SUM(payments.amount) AS total_amount, COUNT(*) AS count
                FROM fee_payments payments
                JOIN fee_ledger ledger ON payments.ledger_id = ledger.id
                JOIN studentinfo students ON payments.admno = students.AdmNo AND ledger.school_id = students.school_id
                WHERE payments.payment_date BETWEEN %s AND %s
                  AND payments.status = 'COMPLETED' AND ledger.school_id = %s
                GROUP BY students.category
                ORDER BY total_amount DESC, category ASC
            """, (start_date, end_date, self.school_id))
        return self.cursor.fetchall()

    def get_arrears_report(self, class_id: Optional[int] = None) -> List[Dict]:
        """Get list of students with outstanding balances."""
        query = """
            SELECT si.AdmNo, si.FName, si.SName, c.display_name,
                   (SELECT balance_after FROM fee_ledger WHERE admno = si.AdmNo AND school_id = %s ORDER BY id DESC LIMIT 1) as balance
            FROM studentinfo si
            JOIN class_allocation ca ON si.AdmNo = ca.student_id AND ca.is_current = TRUE AND si.school_id = ca.school_id
            JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            WHERE si.blocked = 'NO' AND si.school_id = %s
        """
        params = [self.school_id, self.school_id]
        if class_id:
            query += " AND ca.class_id = %s"
            params.append(class_id)
        
        query += " HAVING balance > 0 ORDER BY balance DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    # =========================================================================
    # 5. ACADEMIC YEAR ROLL-UP
    # =========================================================================

    def carry_forward_balances(self, old_year_id: int, new_year_id: int, new_term_id: int, user_id: int) -> int:
        """Move outstanding balances to the new year as 'Arrears'."""
        try:
            # 1. Find all students with outstanding balances
            self.cursor.execute("""
                SELECT AdmNo, (SELECT balance_after FROM fee_ledger WHERE admno = studentinfo.AdmNo AND school_id = %s ORDER BY id DESC LIMIT 1) as balance
                FROM studentinfo
                WHERE school_id = %s
            """, (self.school_id, self.school_id))
            debtors = [d for d in self.cursor.fetchall() if d['balance'] and Decimal(str(d['balance'])) != 0]
            
            if not debtors:
                return 0

            self.connection.begin()
            
            # Find or create Arrears votehead
            self.cursor.execute("SELECT id FROM fee_voteheads WHERE name = 'Arrears' AND school_id = %s LIMIT 1", (self.school_id,))
            arrears_vh = self.cursor.fetchone()
            vh_id = arrears_vh['id'] if arrears_vh else self.create_votehead("Arrears", priority=0)

            count = 0
            for student in debtors:
                balance = Decimal(str(student['balance']))
                # Post to new year
                self.cursor.execute("""
                    INSERT INTO fee_ledger (admno, academic_year_id, term_id, type, votehead_id, amount, balance_after, description, reference_no, transaction_date, created_by, school_id)
                    VALUES (%s, %s, %s, 'CHARGE', %s, %s, %s, %s, %s, CURDATE(), %s, %s)
                """, (student['AdmNo'], new_year_id, new_term_id, vh_id, balance, balance, "Carried forward balance (Arrears)", f"ROLLUP-{old_year_id}", user_id, self.school_id))
                count += 1

            self.connection.commit()
            return count
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Roll-up failed: {str(e)}")

    def get_fee_balances_report(self, academic_year_id: Optional[int] = None, class_id: Optional[int] = None, stream: Optional[str] = None) -> List[Dict]:
        """Detailed report of student balances with filtering."""
        # Query that unions current and legacy allocations to ensure all students are captured
        allocation_query = f"""
            SELECT student_id, class_id, is_current, academic_year_id, school_id FROM class_allocation WHERE school_id = %s
            UNION ALL
            SELECT lca.AdmNo as student_id, lca.classID as class_id, ay.is_current as is_current, ay.id as academic_year_id, lca.school_id
            FROM classallocation lca
            JOIN academic_years ay ON lca.thisYear = ay.year AND lca.school_id = ay.school_id
            WHERE lca.school_id = %s AND lca.AdmNo NOT IN (SELECT student_id FROM class_allocation WHERE school_id = %s)
        """
        
        query = f"""
            SELECT 
                si.AdmNo, 
                si.FName, 
                si.SName, 
                c.display_name as class_name,
                c.stream_code,
                (SELECT balance_after FROM fee_ledger WHERE admno = si.AdmNo AND school_id = %s ORDER BY id DESC LIMIT 1) as current_balance
            FROM studentinfo si
            JOIN ({allocation_query}) ca ON si.AdmNo = ca.student_id AND si.school_id = ca.school_id
            JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            WHERE si.blocked = 'NO' AND si.school_id = %s
        """
        params = [self.school_id, self.school_id, self.school_id, self.school_id, self.school_id, self.school_id]
        
        if academic_year_id:
            query += " AND c.academic_year_id = %s"
            params.append(academic_year_id)
        else:
            query += " AND ca.is_current = TRUE"
            
        if class_id:
            query += " AND c.classID = %s"
            params.append(class_id)
            
        if stream:
            query += " AND c.stream_code = %s"
            params.append(stream)
            
        query += " HAVING current_balance IS NOT NULL ORDER BY c.display_name, si.AdmNo"
        
        self.cursor.execute(query, params)
        return self.cursor.fetchall()


    def get_arrears_aging_report(self) -> List[Dict]:
        """Categorize student arrears by term depth (This Term, 1 Term Ago, 2+ Terms Ago)."""
        query = """
            SELECT 
                si.AdmNo, si.FName, si.SName, c.display_name as class_name,
                (SELECT balance_after FROM fee_ledger WHERE admno = si.AdmNo AND school_id = %s ORDER BY id DESC LIMIT 1) as total_balance,
                (SELECT SUM(amount) FROM fee_ledger WHERE admno = si.AdmNo AND type = 'CHARGE' AND term_id = (SELECT id FROM uniform_term_dates WHERE curdate() BETWEEN start_date AND end_date AND school_id = %s) AND school_id = %s) as current_term_charges,
                (SELECT SUM(amount) FROM fee_payments WHERE admno = si.AdmNo AND status = 'COMPLETED' AND school_id = %s) as total_paid
            FROM studentinfo si
            JOIN class_allocation ca ON si.AdmNo = ca.student_id AND ca.is_current = TRUE AND si.school_id = ca.school_id
            JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            WHERE si.blocked = 'NO' AND si.school_id = %s
            HAVING total_balance > 0
            ORDER BY total_balance DESC
        """
        self.cursor.execute(query, (self.school_id, self.school_id, self.school_id, self.school_id, self.school_id))
        results = self.cursor.fetchall()
        
        # Post-process for aging (simplified logic for demonstration)
        for r in results:
            total = Decimal(str(r['total_balance']))
            current = Decimal(str(r['current_term_charges'] or 0))
            
            if total <= current:
                r['aging'] = '0-30 Days (Current)'
            elif total <= (current * 2):
                r['aging'] = '31-90 Days (1 Term)'
            else:
                r['aging'] = '90+ Days (2+ Terms)'
                
        return results

    # =========================================================================
    # 6. M-PESA RECONCILIATION & VERIFICATION
    # =========================================================================

    def import_mpesa_statement(self, transactions: List[Dict]) -> Dict:
        """
        Import transactions from M-Pesa statement (CSV).
        Expected dict keys: transaction_no, amount, sender_name, sender_phone, transaction_time
        Returns summary of import.
        """
        imported = 0
        skipped = 0
        errors = 0
        
        for tx in transactions:
            try:
                # Check if exists
                self.cursor.execute("SELECT id FROM mpesa_verifications WHERE transaction_no = %s AND school_id = %s", (tx['transaction_no'], self.school_id))
                if self.cursor.fetchone():
                    skipped += 1
                    continue
                
                self.cursor.execute("""
                    INSERT INTO mpesa_verifications (transaction_no, amount, sender_name, sender_phone, transaction_time, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (tx['transaction_no'], tx['amount'], tx['sender_name'], tx['sender_phone'], tx['transaction_time'], self.school_id))
                imported += 1
            except Exception as e:
                logger.error(f"Error importing M-Pesa TX {tx.get('transaction_no')}: {str(e)}")
                errors += 1
        
        self.connection.commit()
        return {'imported': imported, 'skipped': skipped, 'errors': errors}

    def get_mpesa_reconciliation_report(self) -> List[Dict]:
        """
        Returns a list of M-Pesa transactions and their status:
        - UNMATCHED: Not in fee_ledger
        - MATCHED: In fee_ledger with correct amount
        - DISCREPANCY: In fee_ledger but amount differs
        """
        query = """
            SELECT 
                mv.*, 
                fl.admno, 
                fl.amount as ledger_amount,
                COALESCE(fl.description, 'Not Found') as ledger_desc,
                CASE 
                    WHEN fl.id IS NULL THEN 'UNMATCHED'
                    WHEN fl.amount = mv.amount THEN 'MATCHED'
                    ELSE 'DISCREPANCY'
                END as status
            FROM mpesa_verifications mv
            LEFT JOIN fee_ledger fl ON mv.transaction_no = fl.reference_no AND fl.type = 'PAYMENT' AND mv.school_id = fl.school_id
            WHERE mv.school_id = %s
            ORDER BY mv.transaction_time DESC
        """
        self.cursor.execute(query, (self.school_id,))
        return self.cursor.fetchall()

    # =========================================================================
    # 7. WAIVERS & SCHOLARSHIPS
    # =========================================================================

    def get_waiver_categories(self, active_only: bool = True) -> List[Dict]:
        """Fetch all fee waiver categories."""
        query = "SELECT * FROM fee_waiver_categories WHERE school_id = %s"
        params = [self.school_id]
        if active_only:
            query += " AND is_active = TRUE"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def assign_waiver_to_student(self, admno: int, category_id: int, year_id: int, term_id: int, user_id: int,
                                 votehead_ids: Optional[List[int]] = None) -> int:
        """Assign a waiver/scholarship to a student and apply it to their ledger."""
        if votehead_ids:
            return self._assign_votehead_waiver_to_student(
                admno, category_id, year_id, term_id, user_id, votehead_ids,
            )
        try:
            self._assert_student_belongs_to_school(admno)
            self._assert_academic_year_belongs_to_school(year_id)
            self._assert_term_belongs_to_school(term_id, year_id)
            self._assert_waiver_category_belongs_to_school(category_id)
            # 1. Check if already assigned for this term
            self.cursor.execute("""
                SELECT id FROM student_waivers 
                WHERE admno = %s AND academic_year_id = %s AND term_id = %s AND status = 'ACTIVE' AND school_id = %s
            """, (admno, year_id, term_id, self.school_id))
            if self.cursor.fetchone():
                raise FeesError("Student already has an active waiver for this term.")

            # 2. Get category details
            self.cursor.execute("SELECT * FROM fee_waiver_categories WHERE id = %s AND school_id = %s", (category_id, self.school_id))
            cat = self.cursor.fetchone()
            if not cat:
                raise FeesError("Invalid waiver category.")

            self.connection.begin()

            # 3. Create assignment record
            self.cursor.execute("""
                INSERT INTO student_waivers (admno, category_id, academic_year_id, term_id, assigned_by, school_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (admno, category_id, year_id, term_id, user_id, self.school_id))
            assignment_id = self.cursor.lastrowid

            # 4. Calculate amount
            # Need current charges or balance to calculate percentage-based waivers
            # For simplicity, we calculate it against the 'Tuition' charge for this term
            self.cursor.execute("""
                SELECT amount FROM fee_ledger 
                WHERE admno = %s AND academic_year_id = %s AND term_id = %s AND type = 'CHARGE'
                AND votehead_id = (SELECT id FROM fee_voteheads WHERE name = 'Tuition' AND school_id = %s LIMIT 1)
                AND school_id = %s
            """, (admno, year_id, term_id, self.school_id, self.school_id))
            res = self.cursor.fetchone()
            tuition_amount = Decimal(str(res['amount'])) if res else Decimal("0.00")

            waiver_amount = Decimal("0.00")
            if cat['discount_type'] == 'PERCENTAGE':
                waiver_amount = (Decimal(str(cat['value'])) / 100) * tuition_amount
            else:
                waiver_amount = Decimal(str(cat['value']))

            # 5. Post to Ledger as 'CREDIT'
            current_balance = self.get_student_balance(admno)
            new_balance = current_balance - waiver_amount

            self.cursor.execute("""
                INSERT INTO fee_ledger (admno, academic_year_id, term_id, type, amount, balance_after, description, reference_no, transaction_date, created_by, school_id)
                VALUES (%s, %s, %s, 'CREDIT', %s, %s, %s, %s, CURDATE(), %s, %s)
            """, (admno, year_id, term_id, waiver_amount, new_balance, f"Waiver Application: {cat['name']}", f"WVR-{assignment_id}", user_id, self.school_id))
            ledger_id = self.cursor.lastrowid
            self.cursor.execute(
                "UPDATE student_waivers SET ledger_id = %s WHERE id = %s AND school_id = %s",
                (ledger_id, assignment_id, self.school_id),
            )

            self.connection.commit()
            return assignment_id
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Failed to assign waiver: {str(e)}")

    def _assign_votehead_waiver_to_student(self, admno: int, category_id: int, year_id: int,
                                            term_id: int, user_id: int,
                                            votehead_ids: List[int], manage_transaction: bool = True) -> int:
        """Apply one waiver across selected voteheads with ledger links for later reversal."""
        if not self._table_has_column('student_waivers', 'allocation_mode'):
            raise FeesError('Apply migration 040 before assigning votehead-specific waivers.')

        selected_votehead_ids = list(dict.fromkeys(
            self._required_int(votehead_id, 'votehead_id') for votehead_id in votehead_ids
        ))
        if not selected_votehead_ids:
            raise FeesError('Select at least one votehead for this waiver.')

        try:
            self._assert_student_belongs_to_school(admno)
            self._assert_academic_year_belongs_to_school(year_id)
            self._assert_term_belongs_to_school(term_id, year_id)
            self._assert_waiver_category_belongs_to_school(category_id)
            self._assert_voteheads_belong_to_school(selected_votehead_ids)
            self.cursor.execute("""
                SELECT id FROM student_waivers
                WHERE admno = %s AND academic_year_id = %s AND term_id = %s
                  AND status = 'ACTIVE' AND school_id = %s
            """, (admno, year_id, term_id, self.school_id))
            if self.cursor.fetchone():
                raise FeesError('Student already has an active waiver for this term.')

            self.cursor.execute(
                'SELECT * FROM fee_waiver_categories WHERE id = %s AND school_id = %s',
                (category_id, self.school_id),
            )
            category = self.cursor.fetchone()
            if not category:
                raise FeesError('Invalid waiver category.')

            placeholders = ', '.join(['%s'] * len(selected_votehead_ids))
            self.cursor.execute(f"""
                SELECT ledger.votehead_id, voteheads.name, SUM(ledger.amount) AS charge_amount
                FROM fee_ledger ledger
                JOIN fee_voteheads voteheads
                  ON ledger.votehead_id = voteheads.id AND ledger.school_id = voteheads.school_id
                WHERE ledger.admno = %s AND ledger.academic_year_id = %s AND ledger.term_id = %s
                  AND ledger.type = 'CHARGE' AND ledger.school_id = %s
                  AND ledger.votehead_id IN ({placeholders})
                GROUP BY ledger.votehead_id, voteheads.name, voteheads.priority
                ORDER BY voteheads.priority ASC, voteheads.name ASC
            """, (admno, year_id, term_id, self.school_id, *selected_votehead_ids))
            charges = self.cursor.fetchall()
            if not charges:
                raise FeesError('The selected voteheads have no charges for this student and term.')

            allocation_rows = []
            if category['discount_type'] == 'PERCENTAGE':
                percentage = Decimal(str(category['value'])) / Decimal('100')
                allocation_rows = [
                    (row['votehead_id'], row['name'], Decimal(str(row['charge_amount'])) * percentage)
                    for row in charges
                ]
            else:
                remaining = Decimal(str(category['value']))
                for row in charges:
                    charge_amount = Decimal(str(row['charge_amount']))
                    allocated_amount = min(charge_amount, remaining)
                    if allocated_amount > 0:
                        allocation_rows.append((row['votehead_id'], row['name'], allocated_amount))
                        remaining -= allocated_amount
                if remaining > 0:
                    raise FeesError('The fixed waiver exceeds the selected voteheads\' total charges.')

            allocation_rows = [row for row in allocation_rows if row[2] > 0]
            if not allocation_rows:
                raise FeesError('This waiver does not produce a positive selected-votehead credit.')

            if manage_transaction:
                self.connection.begin()
            self.cursor.execute("""
                INSERT INTO student_waivers
                    (admno, category_id, academic_year_id, term_id, assigned_by, allocation_mode, school_id)
                VALUES (%s, %s, %s, %s, %s, 'VOTEHEADS', %s)
            """, (admno, category_id, year_id, term_id, user_id, self.school_id))
            waiver_id = self.cursor.lastrowid
            balance = self.get_student_balance(admno)
            first_ledger_id = None
            for votehead_id, votehead_name, amount in allocation_rows:
                balance -= amount
                self.cursor.execute("""
                    INSERT INTO fee_ledger
                        (admno, academic_year_id, term_id, type, votehead_id, amount, balance_after,
                         description, reference_no, transaction_date, created_by, school_id)
                    VALUES (%s, %s, %s, 'CREDIT', %s, %s, %s, %s, %s, CURDATE(), %s, %s)
                """, (
                    admno, year_id, term_id, votehead_id, amount, balance,
                    f'Waiver Application: {category["name"]} - {votehead_name}',
                    f'WVR-{waiver_id}-{votehead_id}', user_id, self.school_id,
                ))
                ledger_id = self.cursor.lastrowid
                first_ledger_id = first_ledger_id or ledger_id
                self.cursor.execute("""
                    INSERT INTO fee_waiver_allocations (waiver_id, votehead_id, ledger_id, amount, school_id)
                    VALUES (%s, %s, %s, %s, %s)
                """, (waiver_id, votehead_id, ledger_id, amount, self.school_id))
            self.cursor.execute(
                'UPDATE student_waivers SET ledger_id = %s WHERE id = %s AND school_id = %s',
                (first_ledger_id, waiver_id, self.school_id),
            )
            if manage_transaction:
                self.connection.commit()
            return waiver_id
        except Exception as exc:
            if manage_transaction:
                self.connection.rollback()
            if isinstance(exc, FeesError):
                raise
            raise FeesError(f'Failed to assign votehead waiver: {str(exc)}')

    def assign_waiver_to_student_group(self, student_group_id: int, category_id: int, year_id: int,
                                        term_id: int, user_id: int, votehead_ids: List[int]) -> Dict:
        """Atomically assign a selected-votehead waiver to eligible students in one group."""
        if not self._table_has_column('student_waivers', 'allocation_mode'):
            raise FeesError('Apply migration 040 before assigning votehead-specific waivers.')
        self._assert_student_group_belongs_to_school(student_group_id)
        self._assert_waiver_category_belongs_to_school(category_id)
        self._assert_academic_year_belongs_to_school(year_id)
        self._assert_term_belongs_to_school(term_id, year_id)
        selected_votehead_ids = list(dict.fromkeys(
            self._required_int(votehead_id, 'votehead_id') for votehead_id in votehead_ids
        ))
        if not selected_votehead_ids:
            raise FeesError('Select at least one votehead for this waiver.')
        self._assert_voteheads_belong_to_school(selected_votehead_ids)
        self.cursor.execute("""
            SELECT students.AdmNo
            FROM studentinfo students
            WHERE students.student_group_id = %s AND students.school_id = %s AND students.blocked = 'NO'
              AND NOT EXISTS (
                  SELECT 1 FROM student_waivers waivers
                  WHERE waivers.admno = students.AdmNo AND waivers.academic_year_id = %s
                    AND waivers.term_id = %s AND waivers.status = 'ACTIVE'
                    AND waivers.school_id = students.school_id
              )
            ORDER BY students.AdmNo
        """, (student_group_id, self.school_id, year_id, term_id))
        student_ids = [row['AdmNo'] for row in self.cursor.fetchall()]
        if not student_ids:
            raise FeesError('No eligible students without an active term waiver were found in this group.')

        try:
            self.connection.begin()
            waiver_ids = []
            for admno in student_ids:
                waiver_ids.append(self._assign_votehead_waiver_to_student(
                    admno, category_id, year_id, term_id, user_id, selected_votehead_ids,
                    manage_transaction=False,
                ))
            self.connection.commit()
            return {'assigned_count': len(waiver_ids), 'waiver_ids': waiver_ids}
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, FeesError):
                raise
            raise FeesError(f'Failed to assign group waiver: {str(exc)}')

    def get_student_waivers(self, admno: int) -> List[Dict]:
        """Fetch waiver history for a student."""
        self.cursor.execute("""
            SELECT sw.*, fwc.name as category_name, ay.year as year_name, utd.term_number
            FROM student_waivers sw
            JOIN fee_waiver_categories fwc ON sw.category_id = fwc.id AND sw.school_id = fwc.school_id
            JOIN academic_years ay ON sw.academic_year_id = ay.id AND sw.school_id = ay.school_id
            JOIN uniform_term_dates utd ON sw.term_id = utd.id AND sw.school_id = utd.school_id
            WHERE sw.admno = %s AND sw.school_id = %s
            ORDER BY sw.created_at DESC
        """, (admno, self.school_id))
        return self.cursor.fetchall()

    def get_waiver_register(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                            status: Optional[str] = None) -> List[Dict]:
        """Return auditable waiver assignments for the active school."""
        has_allocation_mode = self._table_has_column('student_waivers', 'allocation_mode')
        if has_allocation_mode:
            query = """
                SELECT waivers.id, waivers.admno, waivers.status, waivers.allocation_mode,
                       waivers.created_at, waivers.revoked_at, waivers.revocation_reason,
                       students.FName, students.SName, categories.name AS category_name,
                       years.year AS academic_year, terms.term_number,
                       COALESCE(SUM(allocations.amount), linked_ledger.amount, 0) AS waiver_amount,
                       COUNT(allocations.id) AS allocation_count
                FROM student_waivers waivers
                JOIN studentinfo students ON waivers.admno = students.AdmNo AND waivers.school_id = students.school_id
                JOIN fee_waiver_categories categories ON waivers.category_id = categories.id AND waivers.school_id = categories.school_id
                JOIN academic_years years ON waivers.academic_year_id = years.id AND waivers.school_id = years.school_id
                JOIN uniform_term_dates terms ON waivers.term_id = terms.id AND waivers.school_id = terms.school_id
                LEFT JOIN fee_ledger linked_ledger ON waivers.ledger_id = linked_ledger.id AND waivers.school_id = linked_ledger.school_id
                LEFT JOIN fee_waiver_allocations allocations ON waivers.id = allocations.waiver_id AND waivers.school_id = allocations.school_id
                WHERE waivers.school_id = %s
            """
        else:
            query = """
                SELECT waivers.id, waivers.admno, waivers.status, 'SINGLE' AS allocation_mode,
                       waivers.created_at, waivers.revoked_at, waivers.revocation_reason,
                       students.FName, students.SName, categories.name AS category_name,
                       years.year AS academic_year, terms.term_number,
                       COALESCE(linked_ledger.amount, 0) AS waiver_amount, 0 AS allocation_count
                FROM student_waivers waivers
                JOIN studentinfo students ON waivers.admno = students.AdmNo AND waivers.school_id = students.school_id
                JOIN fee_waiver_categories categories ON waivers.category_id = categories.id AND waivers.school_id = categories.school_id
                JOIN academic_years years ON waivers.academic_year_id = years.id AND waivers.school_id = years.school_id
                JOIN uniform_term_dates terms ON waivers.term_id = terms.id AND waivers.school_id = terms.school_id
                LEFT JOIN fee_ledger linked_ledger ON waivers.ledger_id = linked_ledger.id AND waivers.school_id = linked_ledger.school_id
                WHERE waivers.school_id = %s
            """
        filters = []
        params = [self.school_id]
        if start_date:
            filters.append('DATE(waivers.created_at) >= %s')
            params.append(start_date)
        if end_date:
            filters.append('DATE(waivers.created_at) <= %s')
            params.append(end_date)
        if status:
            filters.append('waivers.status = %s')
            params.append(status)
        if filters:
            query += ' AND ' + ' AND '.join(filters)
        if has_allocation_mode:
            query += ' GROUP BY waivers.id, linked_ledger.amount'
        query += ' ORDER BY waivers.created_at DESC, waivers.id DESC'
        self.cursor.execute(query, tuple(params))
        return self.cursor.fetchall()

    def revoke_waiver(self, waiver_id: int, reason: str, user_id: int) -> None:
        """Revoke a linked active waiver by posting an immutable debit adjustment."""
        reason = (reason or '').strip()
        if not reason:
            raise FeesError('A revocation reason is required.')
        try:
            has_allocation_mode = self._table_has_column('student_waivers', 'allocation_mode')
            allocation_mode_select = 'sw.allocation_mode,' if has_allocation_mode else "'SINGLE' AS allocation_mode,"
            self.cursor.execute("""
                SELECT sw.id, sw.admno, sw.academic_year_id, sw.term_id, sw.ledger_id, sw.status,
                       {allocation_mode_select} fwc.name AS category_name, fl.amount AS waiver_amount
                FROM student_waivers sw
                JOIN fee_waiver_categories fwc ON sw.category_id = fwc.id AND sw.school_id = fwc.school_id
                LEFT JOIN fee_ledger fl ON sw.ledger_id = fl.id AND sw.school_id = fl.school_id
                WHERE sw.id = %s AND sw.school_id = %s
                FOR UPDATE
            """.format(allocation_mode_select=allocation_mode_select), (waiver_id, self.school_id))
            waiver = self.cursor.fetchone()
            if not waiver:
                raise FeesError('Waiver was not found for the active school.')
            if waiver['status'] != 'ACTIVE':
                raise FeesError('Only active waivers can be revoked.')

            if waiver.get('allocation_mode', 'SINGLE') == 'VOTEHEADS':
                self.cursor.execute("""
                    SELECT allocations.id, allocations.votehead_id, allocations.amount, voteheads.name AS votehead_name
                    FROM fee_waiver_allocations allocations
                    JOIN fee_voteheads voteheads
                      ON allocations.votehead_id = voteheads.id AND allocations.school_id = voteheads.school_id
                    WHERE allocations.waiver_id = %s AND allocations.school_id = %s
                    FOR UPDATE
                """, (waiver_id, self.school_id))
                allocations = self.cursor.fetchall()
                if not allocations:
                    raise FeesError('This votehead waiver has no linked allocation records.')

                balance = self.get_student_balance(waiver['admno'])
                for allocation in allocations:
                    amount = Decimal(str(allocation['amount']))
                    balance += amount
                    self.cursor.execute("""
                        INSERT INTO fee_ledger
                            (admno, academic_year_id, term_id, type, votehead_id, amount, balance_after,
                             description, reference_no, transaction_date, created_by, school_id)
                        VALUES (%s, %s, %s, 'ADJUSTMENT', %s, %s, %s, %s, %s, CURDATE(), %s, %s)
                    """, (
                        waiver['admno'], waiver['academic_year_id'], waiver['term_id'], allocation['votehead_id'],
                        amount, balance,
                        f'WAIVER REVERSAL: {waiver["category_name"]} - {allocation["votehead_name"]} - {reason}',
                        f'WVR-REV-{waiver_id}-{allocation["votehead_id"]}', user_id, self.school_id,
                    ))
                    self.cursor.execute("""
                        UPDATE fee_waiver_allocations SET revocation_ledger_id = %s
                        WHERE id = %s AND school_id = %s
                    """, (self.cursor.lastrowid, allocation['id'], self.school_id))
                self.cursor.execute("""
                    UPDATE student_waivers
                    SET status = 'REVOKED', revoked_by = %s, revoked_at = NOW(), revocation_reason = %s
                    WHERE id = %s AND school_id = %s
                """, (user_id, reason, waiver_id, self.school_id))
                self.connection.commit()
                return

            if not waiver.get('ledger_id') or waiver.get('waiver_amount') is None:
                raise FeesError('This legacy waiver has no linked ledger credit and cannot be revoked automatically.')

            amount = Decimal(str(waiver['waiver_amount']))
            current_balance = self.get_student_balance(waiver['admno'])
            reference = f'WVR-REV-{waiver_id}'
            self.cursor.execute("""
                INSERT INTO fee_ledger
                    (admno, academic_year_id, term_id, type, amount, balance_after, description,
                     reference_no, transaction_date, created_by, school_id)
                VALUES (%s, %s, %s, 'ADJUSTMENT', %s, %s, %s, %s, CURDATE(), %s, %s)
            """, (
                waiver['admno'], waiver['academic_year_id'], waiver['term_id'], amount,
                current_balance + amount, f'WAIVER REVERSAL: {waiver["category_name"]} - {reason}',
                reference, user_id, self.school_id,
            ))
            self.cursor.execute("""
                UPDATE student_waivers
                SET status = 'REVOKED', revoked_by = %s, revoked_at = NOW(), revocation_reason = %s
                WHERE id = %s AND school_id = %s
            """, (user_id, reason, waiver_id, self.school_id))
            self.connection.commit()
        except Exception as exc:
            self.connection.rollback()
            if isinstance(exc, FeesError):
                raise
            raise FeesError(f'Failed to revoke waiver: {str(exc)}')

    # =========================================================================
    # 6. ENHANCED STRUCTURE MANAGEMENT (YEARLY)
    # =========================================================================

    def get_student_fee_structure(self, admno: int, term_id: Optional[int] = None) -> List[Dict]:
        """
        Identify the correct fee structure and voteheads for a student.
        Follows hierarchy: Specific Class -> Class Group -> 'all' fallback.
        """
        # 1. Get student category and class
        self.cursor.execute("""
            SELECT si.category, ca.class_id, c.class_group_code
            FROM studentinfo si
            JOIN class_allocation ca ON si.AdmNo = ca.student_id AND ca.is_current = TRUE AND si.school_id = ca.school_id
            JOIN classes c ON ca.class_id = c.classID AND ca.school_id = c.school_id
            WHERE si.AdmNo = %s AND si.school_id = %s
        """, (admno, self.school_id))
        student = self.cursor.fetchone()
        
        # Fallback for legacy students if not in class_allocation
        if not student:
            self.cursor.execute("""
                SELECT si.category, lca.classID as class_id, c.class_group_code
                FROM studentinfo si
                JOIN classallocation lca ON si.AdmNo = lca.AdmNo AND si.school_id = lca.school_id
                JOIN classes c ON lca.classID = c.classID AND lca.school_id = c.school_id
                JOIN academic_years ay ON ay.year = lca.thisYear AND ay.is_current = TRUE AND lca.school_id = ay.school_id
                WHERE si.AdmNo = %s AND si.school_id = %s
            """, (admno, self.school_id))
            student = self.cursor.fetchone()

        if not student:
            return []

        # Find current term if not provided
        if not term_id:
            self.cursor.execute("SELECT id FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date AND school_id = %s LIMIT 1", (self.school_id,))
            term_res = self.cursor.fetchone()
            term_id = term_res['id'] if term_res else None
        
        if not term_id:
            return []

        category = student['category'] or 'Regular'
        class_id = student['class_id']
        group = student['class_group_code']

        # Hierarchical lookup for structure ID
        # 1. Specific Class
        self.cursor.execute("""
            SELECT id FROM fee_structures 
            WHERE term_id = %s AND class_id = %s AND student_category = %s AND school_id = %s
        """, (term_id, class_id, category, self.school_id))
        res = self.cursor.fetchone()

        if not res:
            # 2. Class Group
            self.cursor.execute("""
                SELECT id FROM fee_structures 
                WHERE term_id = %s AND class_group_code = %s AND student_category = %s AND school_id = %s
                AND (class_id IS NULL OR class_id = 0)
            """, (term_id, group, category, self.school_id))
            res = self.cursor.fetchone()
        
        if not res:
            # 3. 'all' fallback
            self.cursor.execute("""
                SELECT id FROM fee_structures 
                WHERE term_id = %s AND class_group_code = 'all' AND student_category = %s AND school_id = %s
                AND (class_id IS NULL OR class_id = 0)
            """, (term_id, category, self.school_id))
            res = self.cursor.fetchone()

        if not res:
            return []

        # Get items for this structure
        self.cursor.execute("""
            SELECT fsi.amount, fv.name as votehead_name, fv.id as votehead_id, fv.priority, fv.is_mandatory
            FROM fee_structure_items fsi
            JOIN fee_voteheads fv ON fsi.votehead_id = fv.id AND fsi.school_id = fv.school_id
            WHERE fsi.fee_structure_id = %s AND fsi.school_id = %s
            ORDER BY fv.priority ASC
        """, (res['id'], self.school_id))
        return self.cursor.fetchall()

    def calculate_term_total(self, admno: int, term_id: int) -> Decimal:
        """Sum of all charges for a specific student in a term."""
        items = self.get_student_fee_structure(admno, term_id)
        return sum(Decimal(str(i['amount'])) for i in items)

    def calculate_votehead_breakdown(self, admno: int, year_id: Optional[int] = None) -> List[Dict]:
        """Get per-votehead totals for the entire year for a student."""
        # This requires summing across all terms for the year
        if not year_id:
            self.cursor.execute("SELECT id FROM academic_years WHERE is_current = TRUE AND school_id = %s LIMIT 1", (self.school_id,))
            y_res = self.cursor.fetchone()
            year_id = y_res['id'] if y_res else None

        if not year_id:
            return []

        # Fetch all terms for the year
        self.cursor.execute("SELECT id FROM uniform_term_dates WHERE academic_year_id = %s AND school_id = %s", (year_id, self.school_id))
        terms = self.cursor.fetchall()
        
        breakdown = {}
        for term in terms:
            items = self.get_student_fee_structure(admno, term['id'])
            for item in items:
                vname = item['votehead_name']
                if vname not in breakdown:
                    breakdown[vname] = {'name': vname, 'total': Decimal("0.00"), 'priority': item['priority']}
                breakdown[vname]['total'] += Decimal(str(item['amount']))
        
        return sorted(breakdown.values(), key=lambda x: x['priority'])

    def create_yearly_fee_structure(self, year_id: int, class_id: Optional[int], group_code: str, category: str, term_amounts: Dict, user_id: int):
        """
        Creates/Updates structures for all 3 terms in one go.
        term_amounts: {votehead_id: {'t1': amount, 't2': amount, 't3': amount}}
        """
        try:
            self.connection.begin()
            
            # 1. Get terms for the year
            self.cursor.execute("SELECT id, term_number FROM uniform_term_dates WHERE academic_year_id = %s AND school_id = %s ORDER BY term_number", (year_id, self.school_id))
            terms = self.cursor.fetchall()
            term_map = {t['term_number']: t['id'] for t in terms}

            for t_num, t_id in term_map.items():
                logger.info(f"Processing yearly structure for Year {year_id}, Term {t_num} (ID: {t_id})")
                # Check if structure already exists and is locked
                self.cursor.execute("""
                    SELECT id, is_locked FROM fee_structures 
                    WHERE academic_year_id = %s AND term_id = %s 
                    AND (class_id = %s OR (class_id IS NULL AND %s IS NULL))
                    AND (class_group_code = %s)
                    AND student_category = %s
                    AND school_id = %s
                """, (year_id, t_id, class_id, class_id, group_code, category, self.school_id))
                existing = self.cursor.fetchone()
                
                if existing and existing['is_locked']:
                    logger.info(f"Term {t_num} is locked, skipping.")
                    continue # Skip locked terms
                
                # Upsert structure
                if existing:
                    struct_id = existing['id']
                    logger.info(f"Updating existing structure ID {struct_id} for Term {t_num}")
                    # Clear items for fresh insert
                    self.cursor.execute("DELETE FROM fee_structure_items WHERE fee_structure_id = %s AND school_id = %s", (struct_id, self.school_id))
                else:
                    logger.info(f"Creating new structure for Term {t_num}")
                    self.cursor.execute("""
                        INSERT INTO fee_structures (academic_year_id, term_id, class_id, class_group_code, student_category, created_by, school_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (year_id, t_id, class_id, group_code, category, user_id, self.school_id))
                    struct_id = self.cursor.lastrowid
                
                total_term = Decimal("0.00")
                for vid, amounts in term_amounts.items():
                    amt_str = amounts.get(f't{t_num}', '0') or '0'
                    try:
                        amt = Decimal(str(amt_str))
                    except:
                        amt = Decimal("0.00")
                        
                    if amt > 0:
                        self.cursor.execute("""
                            INSERT INTO fee_structure_items (fee_structure_id, votehead_id, amount, school_id)
                            VALUES (%s, %s, %s, %s)
                        """, (struct_id, vid, amt, self.school_id))
                        total_term += amt
                
                # Update total
                self.cursor.execute("UPDATE fee_structures SET total_amount = %s WHERE id = %s AND school_id = %s", (total_term, struct_id, self.school_id))

            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise FeesError(f"Failed to create yearly structure: {str(e)}")

    def toggle_structure_lock(self, structure_id: int, lock: bool):
        """Lock or unlock a structure to prevent edits."""
        self.cursor.execute("UPDATE fee_structures SET is_locked = %s WHERE id = %s AND school_id = %s", (1 if lock else 0, structure_id, self.school_id))
        self.connection.commit()


def _get_invoice_replacement_register(self, start_date: Optional[str] = None,
                                                                            end_date: Optional[str] = None) -> List[Dict]:
        """Return category-driven invoice replacement chains for the active school."""
        query = """
                SELECT replacements.*, students.FName, students.SName, years.year AS academic_year,
                             terms.term_number, old_groups.name AS previous_group_name,
                             new_groups.name AS new_group_name, users.username AS changed_by_name
                FROM fee_invoice_replacements replacements
                JOIN studentinfo students
                    ON replacements.admno = students.AdmNo AND replacements.school_id = students.school_id
                JOIN academic_years years
                    ON replacements.academic_year_id = years.id AND replacements.school_id = years.school_id
                JOIN uniform_term_dates terms
                    ON replacements.term_id = terms.id AND replacements.school_id = terms.school_id
                LEFT JOIN student_groups old_groups
                    ON replacements.previous_student_group_id = old_groups.id AND replacements.school_id = old_groups.school_id
                LEFT JOIN student_groups new_groups
                    ON replacements.new_student_group_id = new_groups.id AND replacements.school_id = new_groups.school_id
                LEFT JOIN users ON replacements.changed_by = users.userNo AND replacements.school_id = users.school_id
                WHERE replacements.school_id = %s
        """
        params = [self.school_id]
        if start_date:
                query += " AND DATE(replacements.created_at) >= %s"
                params.append(start_date)
        if end_date:
                query += " AND DATE(replacements.created_at) <= %s"
                params.append(end_date)
        query += " ORDER BY replacements.id DESC"
        self.cursor.execute(query, params)
        return self.cursor.fetchall()


FeesService.get_invoice_replacement_register = _get_invoice_replacement_register


def _get_collection_class_summary(self, start_date: str, end_date: str) -> List[Dict]:
        """Summarize completed collections by each student's current class and stream."""
        fee_payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        if fee_payments_has_school_id:
                self.cursor.execute("""
                        SELECT COALESCE(classes.display_name, 'Unassigned') AS class_name,
                                     COALESCE(classes.stream_code, '-') AS stream_code,
                                     SUM(payments.amount) AS total_amount, COUNT(*) AS count
                        FROM fee_payments payments
                        LEFT JOIN class_allocation allocations
                            ON payments.admno = allocations.student_id AND payments.school_id = allocations.school_id
                            AND allocations.is_current = TRUE
                        LEFT JOIN classes ON allocations.class_id = classes.classID
                            AND allocations.school_id = classes.school_id
                        WHERE payments.payment_date BETWEEN %s AND %s
                            AND payments.status = 'COMPLETED' AND payments.school_id = %s
                        GROUP BY classes.display_name, classes.stream_code
                        ORDER BY total_amount DESC, class_name ASC
                """, (start_date, end_date, self.school_id))
        else:
                self.cursor.execute("""
                        SELECT COALESCE(classes.display_name, 'Unassigned') AS class_name,
                                     COALESCE(classes.stream_code, '-') AS stream_code,
                                     SUM(payments.amount) AS total_amount, COUNT(*) AS count
                        FROM fee_payments payments
                        JOIN fee_ledger ledger ON payments.ledger_id = ledger.id
                        LEFT JOIN class_allocation allocations
                            ON payments.admno = allocations.student_id AND ledger.school_id = allocations.school_id
                            AND allocations.is_current = TRUE
                        LEFT JOIN classes ON allocations.class_id = classes.classID
                            AND allocations.school_id = classes.school_id
                        WHERE payments.payment_date BETWEEN %s AND %s
                            AND payments.status = 'COMPLETED' AND ledger.school_id = %s
                        GROUP BY classes.display_name, classes.stream_code
                        ORDER BY total_amount DESC, class_name ASC
                """, (start_date, end_date, self.school_id))
        return self.cursor.fetchall()


FeesService.get_collection_class_summary = _get_collection_class_summary


def _get_collection_votehead_summary(self, start_date: str, end_date: str) -> List[Dict]:
        """Summarize completed payment allocations by votehead."""
        allocations_has_school_id = self._table_has_column('fee_payment_allocations', 'school_id')
        payments_has_school_id = self._table_has_column('fee_payments', 'school_id')
        if allocations_has_school_id and payments_has_school_id:
                self.cursor.execute("""
                        SELECT voteheads.name AS votehead_name, SUM(allocations.amount) AS total_amount,
                                     COUNT(DISTINCT payments.id) AS receipt_count
                        FROM fee_payment_allocations allocations
                        JOIN fee_payments payments
                            ON allocations.payment_id = payments.id AND allocations.school_id = payments.school_id
                        JOIN fee_voteheads voteheads
                            ON allocations.votehead_id = voteheads.id AND allocations.school_id = voteheads.school_id
                        WHERE payments.payment_date BETWEEN %s AND %s
                            AND payments.status = 'COMPLETED' AND payments.school_id = %s
                        GROUP BY voteheads.id, voteheads.name
                        ORDER BY total_amount DESC, votehead_name ASC
                """, (start_date, end_date, self.school_id))
        else:
                self.cursor.execute("""
                        SELECT voteheads.name AS votehead_name, SUM(allocations.amount) AS total_amount,
                                     COUNT(DISTINCT payments.id) AS receipt_count
                        FROM fee_payment_allocations allocations
                        JOIN fee_payments payments ON allocations.payment_id = payments.id
                        JOIN fee_ledger ledger ON payments.ledger_id = ledger.id
                        JOIN fee_voteheads voteheads
                            ON allocations.votehead_id = voteheads.id AND voteheads.school_id = ledger.school_id
                        WHERE payments.payment_date BETWEEN %s AND %s
                            AND payments.status = 'COMPLETED' AND ledger.school_id = %s
                        GROUP BY voteheads.id, voteheads.name
                        ORDER BY total_amount DESC, votehead_name ASC
                """, (start_date, end_date, self.school_id))
        return self.cursor.fetchall()


FeesService.get_collection_votehead_summary = _get_collection_votehead_summary
