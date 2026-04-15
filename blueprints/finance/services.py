"""
=============================================================================
PRODUCTION-GRADE FINANCE & ACCOUNTING SERVICE
Module: finance_management_service.py
Database: schoolmngt

Features:
- General Ledger & Double Entry
- Chart of Accounts (COA)
- Payment Vouchers & Cheque Register
- Financial Reporting (Trial Balance, PL, Balance Sheet)
=============================================================================
"""

import pymysql
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import logging
import uuid
from core.audit import audit_log
from core.tenancy import require_current_school_id
from flask import g

logger = logging.getLogger(__name__)

class FinanceError(Exception):
    pass

class FinanceService:
    def __init__(self, connection: pymysql.Connection, school_id: Optional[int] = None):
        self.connection = connection
        self.school_id = school_id or require_current_school_id()
        self.cursor = connection.cursor(pymysql.cursors.DictCursor)

    def _assert_account_belongs_to_school(self, account_id: int) -> None:
        self.cursor.execute(
            "SELECT id FROM finance_accounts WHERE id = %s AND school_id = %s LIMIT 1",
            (account_id, self.school_id),
        )
        if not self.cursor.fetchone():
            raise FinanceError("Selected account does not belong to the active school.")

    def _assert_accounts_belong_to_school(self, account_ids: List[int]) -> None:
        filtered_ids = [account_id for account_id in account_ids if account_id]
        if not filtered_ids:
            return
        placeholders = ', '.join(['%s'] * len(filtered_ids))
        self.cursor.execute(
            f"SELECT id FROM finance_accounts WHERE id IN ({placeholders}) AND school_id = %s",
            tuple(filtered_ids) + (self.school_id,),
        )
        found_ids = {row['id'] for row in self.cursor.fetchall()}
        missing_ids = [account_id for account_id in filtered_ids if account_id not in found_ids]
        if missing_ids:
            raise FinanceError("One or more accounts do not belong to the active school.")

    def _assert_supplier_belongs_to_school(self, supplier_id: int) -> None:
        self.cursor.execute(
            "SELECT supplierID FROM suppliers WHERE supplierID = %s AND school_id = %s LIMIT 1",
            (supplier_id, self.school_id),
        )
        if not self.cursor.fetchone():
            raise FinanceError("Supplier not found for the active school.")

    def _get_purchase_order_for_school(self, po_id: int) -> Dict:
        self.cursor.execute(
            "SELECT payment_status, total_amount, po_number FROM purchase_orders WHERE id = %s AND school_id = %s",
            (po_id, self.school_id),
        )
        po = self.cursor.fetchone()
        if not po:
            raise FinanceError("Purchase order not found for the active school.")
        return po

    # =========================================================================
    # 0. AUDIT & CONTROLS
    # =========================================================================

    def log_audit(self, table_name: str, record_id: int, action: str, changes: Dict, user_id: int):
        """Record a system change for audit compliance."""
        import json
        try:
            self.cursor.execute("""
                INSERT INTO audit_records (table_name, record_id, action, changes, user_id, school_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (table_name, record_id, action, json.dumps(changes), user_id, self.school_id))
            self.connection.commit()
        except Exception as e:
            logger.error(f"Audit failed: {str(e)}")

    def check_budget(self, account_id: int, amount: Decimal) -> bool:
        """Check if expenditure falls within the allocated budget."""
        fiscal_year = datetime.now().year
        self.cursor.execute("""
            SELECT annual_amount, spent_amount 
            FROM finance_budgets 
            WHERE account_id = %s AND fiscal_year = %s AND school_id = %s
        """, (account_id, fiscal_year, self.school_id))
        budget = self.cursor.fetchone()
        
        if not budget:
            return True # No budget set, allow (or could be strict)
            
        remaining = Decimal(str(budget['annual_amount'])) - Decimal(str(budget['spent_amount']))
        if amount > remaining:
            raise FinanceError(f"Budget Exceeded! Account {account_id} only has {remaining} remaining for {fiscal_year}.")
        return True

    # =========================================================================
    # 1. CHART OF ACCOUNTS
    # =========================================================================

    def get_accounts(self) -> List[Dict]:
        """Fetch full chart of accounts."""
        self.cursor.execute("SELECT * FROM finance_accounts WHERE school_id = %s ORDER BY code ASC", (self.school_id,))
        return self.cursor.fetchall()

    def create_account(self, code: str, name: str, type: str, parent_id: Optional[int] = None) -> int:
        """Create a new COA account."""
        try:
            if parent_id:
                self._assert_account_belongs_to_school(parent_id)
            self.cursor.execute(
                "INSERT INTO finance_accounts (code, name, type, parent_id, school_id) VALUES (%s, %s, %s, %s, %s)",
                (code, name, type, parent_id, self.school_id)
            )
            self.connection.commit()
            return self.cursor.lastrowid
        except Exception as e:
            raise FinanceError(f"Failed to create account: {str(e)}")

    # =========================================================================
    # 2. GENERAL LEDGER TRANSACTIONS
    # =========================================================================

    @audit_log('record_gl_transaction')
    def record_transaction(self, date: str, reference: str, description: str, entries: List[Dict], user_id: int) -> int:
        """
        Record a double-entry transaction.
        Entries: list of {'account_id': id, 'debit': D, 'credit': C, 'note': text,
                          'votehead_id': int (optional), 'fund_id': int (optional)}
        Debits must equal Credits.
        """
        try:
            self._assert_accounts_belong_to_school([entry['account_id'] for entry in entries])

            # 1. Validate Balance
            total_debit = sum(Decimal(str(e.get('debit', 0))) for e in entries)
            total_credit = sum(Decimal(str(e.get('credit', 0))) for e in entries)
            
            if total_debit != total_credit:
                raise FinanceError(f"Transaction out of balance: Dr {total_debit} / Cr {total_credit}")

            self.connection.begin()
            
            # 2. Create Transaction Header
            self.cursor.execute("""
                INSERT INTO finance_transactions (transaction_date, reference_no, description, created_by, school_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (date, reference, description, user_id, self.school_id))
            txn_id = self.cursor.lastrowid
            
            # 3. Create Ledger Entries (with optional votehead_id and fund_id)
            for entry in entries:
                self.cursor.execute("""
                    INSERT INTO finance_ledger_entries
                        (transaction_id, account_id, debit, credit, note, votehead_id, fund_id, school_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (txn_id, entry['account_id'], entry.get('debit', 0), entry.get('credit', 0),
                      entry.get('note', ''), entry.get('votehead_id'), entry.get('fund_id'), self.school_id))
                
            self.connection.commit()
            return txn_id
        except Exception as e:
            self.connection.rollback()
            raise FinanceError(str(e))

    # =========================================================================
    # 3. PAYMENT VOUCHERS
    # =========================================================================

    @audit_log('create_payment_voucher')
    def create_voucher(self, payee: str, amount: Decimal, mode: str, account_id: int, cheque_no: str, description: str, user_id: int, supplier_id: Optional[int] = None, po_id: Optional[int] = None, source_account_id: Optional[int] = None, vat: Decimal = 0, wht: Decimal = 0) -> int:
        """Issue a payment voucher draft for multi-level approval."""
        try:
            self._assert_account_belongs_to_school(account_id)
            if supplier_id:
                self._assert_supplier_belongs_to_school(supplier_id)

            po = None
            if po_id:
                po = self._get_purchase_order_for_school(po_id)

            self.connection.begin()
            
            # Budget Check
            self.check_budget(account_id, amount)

            # Prevent duplicate PO payment
            if po_id:
                if po and po['payment_status'] == 'PAID':
                    raise FinanceError(f"Purchase Order {po['po_number']} has already been fully paid.")
                
                self.cursor.execute("SELECT SUM(amount) as paid FROM supplier_payments WHERE po_id = %s AND school_id = %s", (po_id, self.school_id))
                paid_res = self.cursor.fetchone()
                current_paid = Decimal(str(paid_res['paid'] if paid_res['paid'] else 0))
                remaining = Decimal(str(po['total_amount'])) - current_paid
                
                if amount > remaining:
                    raise FinanceError(f"Payment amount ({amount}) exceeds remaining PO balance ({remaining}).")

            voucher_no = f"PV-{datetime.now().strftime('%y%m')}-{uuid.uuid4().hex[:4].upper()}"
            
            if supplier_id and not payee:
                self.cursor.execute("SELECT company FROM suppliers WHERE supplierID = %s AND school_id = %s", (supplier_id, self.school_id))
                sup = self.cursor.fetchone()
                if sup: payee = sup['company']

            # Insert with PENDING_VERIFICATION status
            # amount in 'amount' column should be the NET PAYABLE (Gross - WHT)
            net_payable = amount - wht
            
            self.cursor.execute("""
                INSERT INTO finance_payment_vouchers (
                    voucher_no, payee_name, amount, gross_amount, vat_amount, withholding_tax, 
                    account_id, supplier_id, po_id, payment_mode, cheque_no, description, 
                    created_by, status, school_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING_VERIFICATION', %s)
            """, (voucher_no, payee, net_payable, amount, vat, wht, account_id, supplier_id, po_id, mode, cheque_no, description, user_id, self.school_id))
            
            voucher_id = self.cursor.lastrowid
            self.log_audit('finance_payment_vouchers', voucher_id, 'INSERT', {'status': 'PENDING_VERIFICATION', 'amount': float(amount)}, user_id)
            
            self.connection.commit()
            return voucher_id
        except Exception as e:
            self.connection.rollback()
            raise FinanceError(f"Voucher creation failed: {str(e)}")

    @audit_log('verify_payment_voucher')
    def verify_voucher(self, voucher_id: int, user_id: int):
        """Verifier level check."""
        try:
            self.connection.begin()
            self.cursor.execute("UPDATE finance_payment_vouchers SET status='PENDING_PAYMENT', verified_by=%s WHERE id=%s AND school_id = %s", (user_id, voucher_id, self.school_id))
            self.log_audit('finance_payment_vouchers', voucher_id, 'UPDATE', {'status': 'PENDING_PAYMENT'}, user_id)
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise FinanceError(str(e))

    @audit_log('authorize_payment_voucher')
    def authorize_voucher(self, voucher_id: int, user_id: int, source_account_id: Optional[int] = None):
        """Final authorization and GL Posting."""
        try:
            self.connection.begin()
            
            # Fetch voucher details
            self.cursor.execute("SELECT * FROM finance_payment_vouchers WHERE id = %s AND school_id = %s", (voucher_id, self.school_id))
            v = self.cursor.fetchone()
            if not v or v['status'] != 'PENDING_PAYMENT':
                raise FinanceError("Voucher not ready for payment.")

            # 1. Update status
            self.cursor.execute("UPDATE finance_payment_vouchers SET status='PAID', authorized_by=%s WHERE id=%s AND school_id = %s", (user_id, voucher_id, self.school_id))
            
            # 2. Update Budget
            self.cursor.execute("""
                UPDATE finance_budgets 
                SET spent_amount = spent_amount + %s 
                WHERE account_id = %s AND fiscal_year = YEAR(CURDATE()) AND school_id = %s
            """, (v['amount'], v['account_id'], self.school_id))

            # 3. Post to GL
            self.cursor.execute("""
                INSERT INTO finance_transactions (transaction_date, reference_no, description, created_by, school_id)
                VALUES (CURDATE(), %s, %s, %s, %s)
            """, (v['voucher_no'], v['description'] or f"Payment to {v['payee_name']}", user_id, self.school_id))
            txn_id = self.cursor.lastrowid
            
            self.cursor.execute("UPDATE finance_payment_vouchers SET transaction_id=%s WHERE id=%s AND school_id = %s", (txn_id, voucher_id, self.school_id))

            # Update PO payment status if linked
            if v['po_id']:
                self.cursor.execute("""
                    INSERT INTO supplier_payments (po_id, amount, payment_date, payment_mode, reference_no, created_by, school_id)
                    VALUES (%s, %s, CURDATE(), %s, %s, %s, %s)
                """, (v['po_id'], v['amount'], v['payment_mode'], v['voucher_no'], user_id, self.school_id))
                
                self.cursor.execute("SELECT SUM(amount) as total_paid FROM supplier_payments WHERE po_id = %s AND school_id = %s", (v['po_id'], self.school_id))
                total_paid = Decimal(str(self.cursor.fetchone()['total_paid']))
                self.cursor.execute("SELECT total_amount FROM purchase_orders WHERE id = %s AND school_id = %s", (v['po_id'], self.school_id))
                po_data = self.cursor.fetchone()
                new_status = 'PAID' if total_paid >= Decimal(str(po_data['total_amount'])) else 'PARTIAL'
                self.cursor.execute("UPDATE purchase_orders SET payment_status = %s WHERE id = %s AND school_id = %s", (new_status, v['po_id'], self.school_id))

            # GL ENTRIES
            self.cursor.execute("SELECT id FROM finance_accounts WHERE (name LIKE '%%Accounts Payable%%' OR name LIKE '%%Suppliers%%') AND school_id = %s ORDER BY id ASC LIMIT 1", (self.school_id,))
            ap_acc = self.cursor.fetchone()
            tracking_account_id = (ap_acc['id'] if ap_acc else 6) if v['supplier_id'] else v['account_id']

            # DR Liability/Expense
            self.cursor.execute("""
                INSERT INTO finance_ledger_entries (transaction_id, account_id, supplier_id, debit, credit, note, school_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (txn_id, tracking_account_id, v['supplier_id'], v['amount'], 0, f"Voucher {v['voucher_no']}", self.school_id))

            # CR Bank/Cash
            if source_account_id:
                self._assert_account_belongs_to_school(source_account_id)
            else:
                self.cursor.execute("SELECT id FROM finance_accounts WHERE (name LIKE '%%Bank%%' OR name LIKE '%%Cash%%') AND school_id = %s ORDER BY id ASC LIMIT 1", (self.school_id,))
                bank_acc = self.cursor.fetchone()
                if not bank_acc:
                    raise FinanceError("No tenant-scoped bank or cash account is configured for this school.")
                source_account_id = bank_acc['id']

            self.cursor.execute("""
                INSERT INTO finance_ledger_entries (transaction_id, account_id, debit, credit, note, school_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (txn_id, source_account_id, 0, v['amount'], f"Payment via {v['payment_mode']} - {v['voucher_no']}", self.school_id))

            self.log_audit('finance_payment_vouchers', voucher_id, 'POST', {'status': 'PAID', 'txn_id': txn_id}, user_id)
            self.connection.commit()
            return txn_id
        except Exception as e:
            self.connection.rollback()
            raise FinanceError(f"Authorization failed: {str(e)}")
        except Exception as e:
            self.connection.rollback()
            raise FinanceError(f"Voucher creation failed: {str(e)}")

    def amount_to_words(self, amount: Decimal) -> str:
        """Convert decimal amount to words for cheque printing."""
        units = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine")
        teens = ("Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen")
        tens = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")
        thousands = ("", "Thousand", "Million", "Billion")

        def _convert_group(n):
            res = ""
            h = n // 100
            t = (n % 100) // 10
            u = n % 10
            if h:
                res += units[h] + " Hundred "
            if t == 1:
                res += teens[u]
            else:
                if t: res += tens[t] + " "
                if u: res += units[u]
            return res.strip()

        integer_part = int(amount)
        decimal_part = int(round((amount - integer_part) * 100))
        
        if integer_part == 0:
            words = "Zero"
        else:
            words = ""
            group_idx = 0
            while integer_part > 0:
                group = integer_part % 1000
                if group:
                    group_word = _convert_group(group)
                    words = group_word + " " + thousands[group_idx] + " " + words
                integer_part //= 1000
                group_idx += 1
        
        words = words.strip() + " Shillings"
        if decimal_part > 0:
            words += f" and {decimal_part}/100 Cents"
        else:
            words += " Only"
            
        return words.upper()

    # =========================================================================
    # 4. FINANCIAL STATEMENTS
    # =========================================================================

    def get_trial_balance(self, end_date: str) -> List[Dict]:
        """Generate Trial Balance up to date."""
        self.cursor.execute("""
            SELECT 
                a.code, a.name, a.type,
                SUM(le.debit) as total_debit, 
                SUM(le.credit) as total_credit
            FROM finance_accounts a
            LEFT JOIN finance_ledger_entries le ON a.id = le.account_id AND a.school_id = le.school_id
            LEFT JOIN finance_transactions t ON le.transaction_id = t.id AND le.school_id = t.school_id
            WHERE a.school_id = %s AND (t.transaction_date <= %s OR t.id IS NULL)
            GROUP BY a.id
            HAVING total_debit > 0 OR total_credit > 0
            ORDER BY a.code ASC
        """, (self.school_id, end_date))
        return self.cursor.fetchall()

    def get_income_statement(self, start_date: str, end_date: str) -> Dict:
        """Profit and Loss report."""
        self.cursor.execute("""
            SELECT a.type, a.name, SUM(le.debit) as total_debit, SUM(le.credit) as total_credit
            FROM finance_accounts a
            JOIN finance_ledger_entries le ON a.id = le.account_id AND a.school_id = le.school_id
            JOIN finance_transactions t ON le.transaction_id = t.id AND le.school_id = t.school_id
            WHERE a.school_id = %s AND a.type IN ('INCOME', 'EXPENSE')
            AND t.transaction_date BETWEEN %s AND %s
            GROUP BY a.id, a.type, a.name
        """, (self.school_id, start_date, end_date))
        rows = self.cursor.fetchall()
        
        income = []
        expenses = []
        total_income = Decimal('0.00')
        total_expenses = Decimal('0.00')
        
        for row in rows:
            if row['type'] == 'INCOME':
                net = row['total_credit'] - row['total_debit']
                income.append({'name': row['name'], 'amount': net})
                total_income += net
            else: # EXPENSE
                net = row['total_debit'] - row['total_credit']
                expenses.append({'name': row['name'], 'amount': net})
                total_expenses += net
                
        return {
            'income': income,
            'expenses': expenses,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'net_profit': total_income - total_expenses
        }

    def get_balance_sheet(self, end_date: str) -> Dict:
        """Balance Sheet as at date. Aggregates by account type."""
        # Sum balances per account up to end_date
        self.cursor.execute(
            """
            SELECT a.id, a.code, a.name, a.type,
                   SUM(le.debit - le.credit) AS balance
            FROM finance_accounts a
            LEFT JOIN finance_ledger_entries le ON a.id = le.account_id AND a.school_id = le.school_id
            LEFT JOIN finance_transactions t ON le.transaction_id = t.id AND le.school_id = t.school_id
            WHERE a.school_id = %s AND (t.transaction_date <= %s OR t.id IS NULL)
            GROUP BY a.id
            """,
            (self.school_id, end_date)
        )
        rows = self.cursor.fetchall()

        assets = []
        liabilities = []
        equity = []
        for r in rows:
            if r['type'] == 'ASSET':
                assets.append(r)
            elif r['type'] == 'LIABILITY':
                # Convention: liabilities typically have credit balances
                liabilities.append(r)
            elif r['type'] in ('EQUITY', 'CAPITAL', 'RETAINED_EARNINGS'):
                equity.append(r)

        def total(items: List[Dict]) -> Decimal:
            return sum((r['balance'] or 0) for r in items)

        return {
            'assets': assets,
            'liabilities': liabilities,
            'equity': equity,
            'total_assets': total(assets),
            'total_liabilities': total(liabilities),
            'total_equity': total(equity)
        }

    # =========================================================================
    # 5. DASHBOARD AGGREGATIONS
    # =========================================================================

    def get_dashboard_summary(self) -> Dict:
        """Overview for Finance Hub."""
        today = datetime.now()
        first_day_month = today.replace(day=1).strftime('%Y-%m-%d')
        
        # Monthly Income
        self.cursor.execute("""
            SELECT SUM(le.credit - le.debit) as total
            FROM finance_ledger_entries le
            JOIN finance_accounts a ON le.account_id = a.id AND le.school_id = a.school_id
            JOIN finance_transactions t ON le.transaction_id = t.id AND le.school_id = t.school_id
            WHERE le.school_id = %s AND a.type = 'INCOME' AND t.transaction_date >= %s
        """, (self.school_id, first_day_month))
        income = self.cursor.fetchone()['total'] or Decimal('0.00')
        
        # Monthly Expenses
        self.cursor.execute("""
            SELECT SUM(le.debit - le.credit) as total
            FROM finance_ledger_entries le
            JOIN finance_accounts a ON le.account_id = a.id AND le.school_id = a.school_id
            JOIN finance_transactions t ON le.transaction_id = t.id AND le.school_id = t.school_id
            WHERE le.school_id = %s AND a.type = 'EXPENSE' AND t.transaction_date >= %s
        """, (self.school_id, first_day_month))
        expenses = self.cursor.fetchone()['total'] or Decimal('0.00')
        
        # Pending Vouchers
        self.cursor.execute("SELECT COUNT(*) as count, SUM(amount) as total FROM finance_payment_vouchers WHERE status != 'PAID' AND school_id = %s", (self.school_id,))
        pending = self.cursor.fetchone()
        
        # Bank Balance (Accounts with 'Bank' or 'Cash' in name)
        self.cursor.execute("""
            SELECT SUM(le.debit - le.credit) as balance
            FROM finance_ledger_entries le
            JOIN finance_accounts a ON le.account_id = a.id AND le.school_id = a.school_id
            WHERE le.school_id = %s AND (a.name LIKE '%%Bank%%' OR a.name LIKE '%%Cash%%')
        """, (self.school_id,))
        cash = self.cursor.fetchone()['balance'] or Decimal('0.00')

        return {
            'monthly_income': income,
            'monthly_expenses': expenses,
            'pending_vouchers_count': pending['count'],
            'pending_vouchers_amount': pending['total'] or 0,
            'cash_on_hand': cash
        }

    def get_recent_transactions(self, limit: int = 10) -> List[Dict]:
        """Fetch recent GL transactions for the active school."""
        self.cursor.execute(
            """
            SELECT ft.*, SUM(le.debit) as total_debit, SUM(le.credit) as total_credit,
                   u.username as created_by_name
            FROM finance_transactions ft
            JOIN finance_ledger_entries le ON ft.id = le.transaction_id AND ft.school_id = le.school_id
            LEFT JOIN users u ON ft.created_by = u.userNo AND ft.school_id = u.school_id
            WHERE ft.school_id = %s
            GROUP BY ft.id
            ORDER BY ft.id DESC
            LIMIT %s
            """,
            (self.school_id, limit),
        )
        return self.cursor.fetchall()

    def get_vouchers(self) -> List[Dict]:
        """Fetch payment vouchers with tenant-scoped joins for related entities."""
        self.cursor.execute(
            """
            SELECT v.*, u.username as created_by_name, a.name as account_name,
                   s.company as supplier_name, po.po_number, 'VOUCHER' as source_type
            FROM finance_payment_vouchers v
            LEFT JOIN users u ON v.created_by = u.userNo AND v.school_id = u.school_id
            LEFT JOIN finance_accounts a ON v.account_id = a.id AND v.school_id = a.school_id
            LEFT JOIN suppliers s ON v.supplier_id = s.supplierID AND v.school_id = s.school_id
            LEFT JOIN purchase_orders po ON v.po_id = po.id AND v.school_id = po.school_id
            WHERE v.school_id = %s
            ORDER BY v.created_at DESC
            """,
            (self.school_id,),
        )
        return self.cursor.fetchall()

    def get_voucher_for_print(self, voucher_id: int) -> Optional[Dict]:
        """Fetch a single voucher with tenant-scoped joins for printing."""
        self.cursor.execute(
            """
            SELECT v.*, a.name as account_name,
                   u1.username as created_by_name,
                   u2.username as verified_by_name,
                   u3.username as authorized_by_name,
                   po.po_number
            FROM finance_payment_vouchers v
            LEFT JOIN finance_accounts a ON v.account_id = a.id AND v.school_id = a.school_id
            LEFT JOIN users u1 ON v.created_by = u1.userNo AND v.school_id = u1.school_id
            LEFT JOIN users u2 ON v.verified_by = u2.userNo AND v.school_id = u2.school_id
            LEFT JOIN users u3 ON v.authorized_by = u3.userNo AND v.school_id = u3.school_id
            LEFT JOIN purchase_orders po ON v.po_id = po.id AND v.school_id = po.school_id
            WHERE v.id = %s AND v.school_id = %s
            """,
            (voucher_id, self.school_id),
        )
        return self.cursor.fetchone()

    def get_voucher_for_cheque(self, voucher_id: int) -> Optional[Dict]:
        """Fetch the raw voucher needed for cheque printing."""
        self.cursor.execute(
            "SELECT * FROM finance_payment_vouchers WHERE id = %s AND school_id = %s",
            (voucher_id, self.school_id),
        )
        return self.cursor.fetchone()

    def get_pending_purchase_orders(self) -> List[Dict]:
        """Fetch receipted purchase orders that still have an outstanding payable balance."""
        self.cursor.execute(
            "SELECT id, po_number, supplier_id, total_amount FROM purchase_orders WHERE payment_status != 'PAID' AND status = 'RECEIVED' AND school_id = %s",
            (self.school_id,),
        )
        return self.cursor.fetchall()

    def upsert_budget(self, account_id: int, annual_amount: Decimal, fiscal_year: int, created_by: int) -> None:
        """Create or update a tenant-scoped budget row."""
        self._assert_account_belongs_to_school(account_id)
        self.cursor.execute(
            """
            INSERT INTO finance_budgets (account_id, annual_amount, fiscal_year, created_by, school_id)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE annual_amount = %s
            """,
            (account_id, annual_amount, fiscal_year, created_by, self.school_id, annual_amount),
        )
        self.connection.commit()

    def get_budgets(self) -> List[Dict]:
        """Fetch tenant-scoped budgets with account metadata."""
        self.cursor.execute(
            "SELECT b.*, a.name as account_name, a.code as account_code FROM finance_budgets b JOIN finance_accounts a ON b.account_id = a.id AND b.school_id = a.school_id WHERE b.school_id = %s ORDER BY b.fiscal_year DESC, a.code ASC",
            (self.school_id,),
        )
        return self.cursor.fetchall()
