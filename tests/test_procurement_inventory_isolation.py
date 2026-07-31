from datetime import datetime
from decimal import Decimal
import json

import pytest
import pymysql

from blueprints.classes.services import ClassManagementService
from blueprints.dashboard.services import DashboardService
from blueprints.farm.services import FarmManagementService
from blueprints.exams.services import ExamManagementError
from blueprints.exams.services import ExamManagementService
from blueprints.finance.services import FinanceError
from blueprints.finance.services import FinanceService
from blueprints.fees.services import FeesError
from blueprints.fees.services import FeesService
from blueprints.inventory.services import InventoryService
from blueprints.procurement.services import ProcurementService
from blueprints.procurement.services import ProcurementError
from blueprints.students.services import StudentService
from blueprints.transport.services import TransportService


class RecordingCursor:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.executed = []
        self.lastrowid = 0

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if not self.responses:
            return None
        response_type, value = self.responses.pop(0)
        if response_type != 'one':
            raise AssertionError(f'Expected fetchone response, got {response_type}')
        return value

    def fetchall(self):
        if not self.responses:
            return []
        response_type, value = self.responses.pop(0)
        if response_type != 'all':
            raise AssertionError(f'Expected fetchall response, got {response_type}')
        return value


class RecordingConnection:
    def __init__(self, responses=None):
        self.cursor_obj = RecordingCursor(responses=responses)
        self.commit_calls = 0
        self.rollback_calls = 0
        self.begin_calls = 0

    def cursor(self, *_args, **_kwargs):
        return self.cursor_obj

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def begin(self):
        self.begin_calls += 1


def test_finance_service_scopes_trial_balance_and_income_statement_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'code': '4000', 'name': 'Tuition', 'total_debit': 0, 'total_credit': Decimal('5000.00')}]),
            ('all', [
                {'type': 'INCOME', 'name': 'Tuition', 'total_debit': Decimal('0.00'), 'total_credit': Decimal('5000.00')},
                {'type': 'EXPENSE', 'name': 'Utilities', 'total_debit': Decimal('1200.00'), 'total_credit': Decimal('0.00')},
            ]),
        ]
    )
    service = FinanceService(connection, school_id=18)

    trial_balance = service.get_trial_balance('2026-03-31')
    income_statement = service.get_income_statement('2026-03-01', '2026-03-31')

    assert trial_balance == [{'code': '4000', 'name': 'Tuition', 'total_debit': 0, 'total_credit': Decimal('5000.00')}]
    assert income_statement['total_income'] == Decimal('5000.00')
    assert income_statement['total_expenses'] == Decimal('1200.00')
    assert income_statement['net_profit'] == Decimal('3800.00')

    trial_query, trial_params = connection.cursor_obj.executed[0]
    income_query, income_params = connection.cursor_obj.executed[1]

    assert trial_params == (18, '2026-03-31')
    assert 'a.school_id = le.school_id' in trial_query
    assert 'le.transaction_id = t.id and le.school_id = t.school_id' in trial_query.lower()
    assert 'where a.school_id = %s' in trial_query.lower()

    assert income_params == (18, '2026-03-01', '2026-03-31')
    assert 'a.id = le.account_id and a.school_id = le.school_id' in income_query.lower()
    assert 'le.transaction_id = t.id and le.school_id = t.school_id' in income_query.lower()
    assert "where a.school_id = %s and a.type in ('income', 'expense')" in income_query.lower()


def test_finance_service_configures_tenant_payment_mode_receiving_accounts():
    connection = RecordingConnection(
        responses=[
            ('all', [{'payment_mode': 'MPESA', 'account_id': 17, 'account_code': '1010', 'account_name': 'Mobile Money'}]),
            ('one', {'id': 17}),
        ]
    )
    service = FinanceService(connection, school_id=18)

    mappings = service.get_payment_mode_receiving_accounts()
    service.configure_payment_mode_receiving_account('mpesa', 17, configured_by=8)

    assert mappings[0]['account_id'] == 17
    assert connection.commit_calls == 1
    mappings_query, mappings_params = connection.cursor_obj.executed[0]
    account_query, account_params = connection.cursor_obj.executed[1]
    upsert_query, upsert_params = connection.cursor_obj.executed[2]
    assert mappings_params == (18,)
    assert 'config.school_id = %s' in mappings_query.lower()
    assert account_params == (17, 18)
    assert 'finance_accounts where id = %s and school_id = %s' in account_query.lower()
    assert upsert_params == (18, 'MPESA', 17, True, 8)
    assert 'on duplicate key update' in upsert_query.lower()


def test_finance_service_rejects_payment_mode_account_from_another_school():
    connection = RecordingConnection(responses=[('one', None)])
    service = FinanceService(connection, school_id=18)

    with pytest.raises(FinanceError, match='does not belong'):
        service.configure_payment_mode_receiving_account('CASH', 99, configured_by=8)

    assert connection.commit_calls == 0


def test_finance_service_closes_cashier_session_with_cash_variance():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 7}),
            ('one', {'expected_cash': Decimal('1500.00')}),
        ]
    )
    service = FinanceService(connection, school_id=18)

    result = service.close_cashier_session(7, cashier_user_id=8, actual_cash=Decimal('1450.00'), closed_by=8, notes='Short cash')

    assert result == {
        'expected_cash': Decimal('1500.00'),
        'actual_cash': Decimal('1450.00'),
        'variance': Decimal('-50.00'),
        'status': 'PENDING_APPROVAL',
    }
    assert connection.commit_calls == 1
    session_query, session_params = connection.cursor_obj.executed[0]
    total_query, total_params = connection.cursor_obj.executed[1]
    update_query, update_params = connection.cursor_obj.executed[2]
    assert session_params == (7, 18, 8)
    assert "status = 'open'" in session_query.lower()
    assert total_params == (7, 18)
    assert "payment_mode = 'cash'" in total_query.lower()
    assert update_params == ('PENDING_APPROVAL', 8, Decimal('1500.00'), Decimal('1450.00'), Decimal('-50.00'), 'Short cash', 7, 18)
    assert 'update cashier_sessions' in update_query.lower()


def test_dashboard_service_scopes_summary_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'count': 240}),
            ('one', {'count': 18}),
            ('one', {'total': Decimal('18500.00')}),
        ]
    )
    service = DashboardService(connection, school_id=54)

    summary = service.get_summary()

    assert summary == {
        'total_students': 240,
        'total_staff': 18,
        'today_collections': Decimal('18500.00'),
    }

    students_query, students_params = connection.cursor_obj.executed[0]
    staff_query, staff_params = connection.cursor_obj.executed[1]
    collections_query, collections_params = connection.cursor_obj.executed[2]

    assert students_params == (54,)
    assert 'from studentinfo where school_id = %s' in students_query.lower()
    assert staff_params == (54,)
    assert 'from users where school_id = %s' in staff_query.lower()
    assert collections_params == (54,)
    assert 'from fee_collections' in collections_query.lower()
    assert 'where school_id = %s and date(collection_date) = curdate()' in collections_query.lower()


def test_finance_service_scopes_balance_sheet_and_dashboard_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [
                {'id': 1, 'code': '1000', 'name': 'Bank', 'type': 'ASSET', 'balance': Decimal('7000.00')},
                {'id': 2, 'code': '2000', 'name': 'Payables', 'type': 'LIABILITY', 'balance': Decimal('-2500.00')},
                {'id': 3, 'code': '3000', 'name': 'Capital', 'type': 'EQUITY', 'balance': Decimal('-4500.00')},
            ]),
            ('one', {'total': Decimal('9000.00')}),
            ('one', {'total': Decimal('2500.00')}),
            ('one', {'count': 3, 'total': Decimal('1750.00')}),
            ('one', {'balance': Decimal('6400.00')}),
        ]
    )
    service = FinanceService(connection, school_id=27)

    balance_sheet = service.get_balance_sheet('2026-03-31')
    summary = service.get_dashboard_summary()

    assert balance_sheet['total_assets'] == Decimal('7000.00')
    assert balance_sheet['total_liabilities'] == Decimal('-2500.00')
    assert balance_sheet['total_equity'] == Decimal('-4500.00')
    assert summary['monthly_income'] == Decimal('9000.00')
    assert summary['monthly_expenses'] == Decimal('2500.00')
    assert summary['pending_vouchers_count'] == 3
    assert summary['cash_on_hand'] == Decimal('6400.00')

    balance_query, balance_params = connection.cursor_obj.executed[0]
    income_query, income_params = connection.cursor_obj.executed[1]
    expense_query, expense_params = connection.cursor_obj.executed[2]
    pending_query, pending_params = connection.cursor_obj.executed[3]
    cash_query, cash_params = connection.cursor_obj.executed[4]

    assert balance_params == (27, '2026-03-31')
    assert 'a.school_id = le.school_id' in balance_query
    assert 'le.transaction_id = t.id and le.school_id = t.school_id' in balance_query.lower()
    assert 'where a.school_id = %s' in balance_query.lower()

    assert income_params[0] == 27
    assert isinstance(income_params[1], str)
    assert 'where le.school_id = %s and a.type = ' in income_query.lower()
    assert 'le.account_id = a.id and le.school_id = a.school_id' in income_query.lower()

    assert expense_params[0] == 27
    assert isinstance(expense_params[1], str)
    assert 'where le.school_id = %s and a.type = ' in expense_query.lower()
    assert pending_params == (27,)
    assert 'where status != ' in pending_query.lower()
    assert 'school_id = %s' in pending_query.lower()
    assert cash_params == (27,)
    assert 'where le.school_id = %s and (a.name like ' in cash_query.lower()


def test_finance_service_scopes_recent_transactions_and_voucher_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'id': 9, 'reference_no': 'PV-2604-ABCD', 'created_by_name': 'bursar'}]),
            ('all', [{'id': 5, 'voucher_no': 'PV-2604-ABCD', 'supplier_name': 'Acme Supplies'}]),
            ('one', {'id': 5, 'voucher_no': 'PV-2604-ABCD', 'account_name': 'Utilities'}),
        ]
    )
    service = FinanceService(connection, school_id=45)

    recent = service.get_recent_transactions(limit=7)
    vouchers = service.get_vouchers()
    voucher = service.get_voucher_for_print(5)

    assert recent == [{'id': 9, 'reference_no': 'PV-2604-ABCD', 'created_by_name': 'bursar'}]
    assert vouchers == [{'id': 5, 'voucher_no': 'PV-2604-ABCD', 'supplier_name': 'Acme Supplies'}]
    assert voucher == {'id': 5, 'voucher_no': 'PV-2604-ABCD', 'account_name': 'Utilities'}

    recent_query, recent_params = connection.cursor_obj.executed[0]
    vouchers_query, vouchers_params = connection.cursor_obj.executed[1]
    voucher_query, voucher_params = connection.cursor_obj.executed[2]

    assert recent_params == (45, 7)
    assert 'ft.id = le.transaction_id and ft.school_id = le.school_id' in recent_query.lower()
    assert 'ft.created_by = u.userno and ft.school_id = u.school_id' in recent_query.lower()
    assert 'where ft.school_id = %s' in recent_query.lower()

    assert vouchers_params == (45,)
    assert 'v.created_by = u.userno and v.school_id = u.school_id' in vouchers_query.lower()
    assert 'v.account_id = a.id and v.school_id = a.school_id' in vouchers_query.lower()
    assert 'v.supplier_id = s.supplierid and v.school_id = s.school_id' in vouchers_query.lower()
    assert 'v.po_id = po.id and v.school_id = po.school_id' in vouchers_query.lower()
    assert 'where v.school_id = %s' in vouchers_query.lower()

    assert voucher_params == (5, 45)
    assert 'v.account_id = a.id and v.school_id = a.school_id' in voucher_query.lower()
    assert 'v.created_by = u1.userno and v.school_id = u1.school_id' in voucher_query.lower()
    assert 'v.verified_by = u2.userno and v.school_id = u2.school_id' in voucher_query.lower()
    assert 'v.authorized_by = u3.userno and v.school_id = u3.school_id' in voucher_query.lower()
    assert 'v.po_id = po.id and v.school_id = po.school_id' in voucher_query.lower()
    assert 'where v.id = %s and v.school_id = %s' in voucher_query.lower()


def test_finance_service_scopes_budget_and_pending_po_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'id': 1, 'po_number': 'PO-001', 'total_amount': Decimal('5000.00')}]),
            ('one', {'id': 2, 'voucher_no': 'PV-001'}),
            ('all', [{'account_name': 'Utilities', 'account_code': '5000'}]),
        ]
    )
    service = FinanceService(connection, school_id=54)

    pending_pos = service.get_pending_purchase_orders()
    cheque = service.get_voucher_for_cheque(2)
    budgets = service.get_budgets()

    assert pending_pos == [{'id': 1, 'po_number': 'PO-001', 'total_amount': Decimal('5000.00')}]
    assert cheque == {'id': 2, 'voucher_no': 'PV-001'}
    assert budgets == [{'account_name': 'Utilities', 'account_code': '5000'}]

    pending_query, pending_params = connection.cursor_obj.executed[0]
    cheque_query, cheque_params = connection.cursor_obj.executed[1]
    budgets_query, budgets_params = connection.cursor_obj.executed[2]

    assert pending_params == (54,)
    assert "payment_status != 'paid'" in pending_query.lower()
    assert 'school_id = %s' in pending_query.lower()

    assert cheque_params == (2, 54)
    assert 'where id = %s and school_id = %s' in cheque_query.lower()

    assert budgets_params == (54,)
    assert 'b.account_id = a.id and b.school_id = a.school_id' in budgets_query.lower()
    assert 'where b.school_id = %s' in budgets_query.lower()


def test_finance_service_upsert_budget_persists_school_id():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 7}),
        ]
    )
    service = FinanceService(connection, school_id=54)

    service.upsert_budget(account_id=7, annual_amount=Decimal('120000.00'), fiscal_year=2026, created_by=9)

    assert connection.commit_calls == 1
    query, params = connection.cursor_obj.executed[1]
    assert 'insert into finance_budgets' in query.lower()
    assert 'school_id' in query.lower()
    assert params == (7, Decimal('120000.00'), 2026, 9, 54, Decimal('120000.00'))


def test_finance_service_rejects_voucher_create_with_foreign_account():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = FinanceService(connection, school_id=54)

    with pytest.raises(FinanceError, match='Selected account does not belong to the active school'):
        FinanceService.create_voucher.__wrapped__(
            service,
            payee='Acme Supplies',
            amount=Decimal('2500.00'),
            mode='BANK',
            account_id=77,
            cheque_no='',
            description='Payment',
            user_id=9,
        )


def test_finance_service_rejects_voucher_create_with_foreign_supplier():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 14}),
            ('one', None),
        ]
    )
    service = FinanceService(connection, school_id=54)

    with pytest.raises(FinanceError, match='Supplier not found for the active school'):
        FinanceService.create_voucher.__wrapped__(
            service,
            payee='',
            amount=Decimal('2500.00'),
            mode='BANK',
            account_id=14,
            cheque_no='',
            description='Payment',
            user_id=9,
            supplier_id=33,
        )


def test_finance_service_rejects_voucher_create_with_foreign_purchase_order():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 14}),
            ('one', None),
        ]
    )
    service = FinanceService(connection, school_id=54)

    with pytest.raises(FinanceError, match='Purchase order not found for the active school'):
        FinanceService.create_voucher.__wrapped__(
            service,
            payee='Acme Supplies',
            amount=Decimal('2500.00'),
            mode='BANK',
            account_id=14,
            cheque_no='',
            description='Payment',
            user_id=9,
            po_id=88,
        )


def test_finance_service_rejects_budget_upsert_with_foreign_account():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = FinanceService(connection, school_id=54)

    with pytest.raises(FinanceError, match='Selected account does not belong to the active school'):
        service.upsert_budget(account_id=99, annual_amount=Decimal('120000.00'), fiscal_year=2026, created_by=9)


def test_finance_service_rejects_voucher_authorization_with_foreign_source_account():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 5,
                'status': 'PENDING_PAYMENT',
                'amount': Decimal('3200.00'),
                'account_id': 14,
                'voucher_no': 'PV-2604-ABCD',
                'description': 'Supplier payment',
                'payee_name': 'Acme Supplies',
                'po_id': None,
                'supplier_id': None,
                'payment_mode': 'BANK',
            }),
            ('one', {'id': 9}),
            ('one', None),
        ]
    )
    service = FinanceService(connection, school_id=54)

    with pytest.raises(FinanceError, match='Selected account does not belong to the active school'):
        FinanceService.authorize_voucher.__wrapped__(service, voucher_id=5, user_id=9, source_account_id=99)

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    query, params = connection.cursor_obj.executed[-1]
    assert 'select id from finance_accounts where id = %s and school_id = %s limit 1' in query.lower()
    assert params == (99, 54)


def test_fees_service_scopes_mpesa_reconciliation_report_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'transaction_no': 'QWE123', 'status': 'MATCHED', 'admno': '1001'}]),
        ]
    )
    service = FeesService(connection, school_id=55)

    rows = service.get_mpesa_reconciliation_report()

    assert rows == [{'transaction_no': 'QWE123', 'status': 'MATCHED', 'admno': '1001'}]
    query, params = connection.cursor_obj.executed[0]
    assert params == (55,)
    assert 'mv.transaction_no = fl.reference_no' in query.lower()
    assert "fl.type = 'payment'" in query.lower()
    assert 'mv.school_id = fl.school_id' in query.lower()
    assert 'where mv.school_id = %s' in query.lower()


def test_fees_service_duplicate_payment_lookup_scopes_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'school_id'}]),
            ('all', [{'Field': 'school_id'}]),
            ('one', {
                'id': 11,
                'admno': 1001,
                'amount': Decimal('1500.00'),
                'payment_date': '2026-07-30',
                'status': 'COMPLETED',
                'receipt_no': 'RCP-2026-00011',
            }),
        ]
    )
    service = FeesService(connection, school_id=55)

    duplicate = service.find_duplicate_payment('MPESA', 'QWE123')

    assert duplicate['receipt_no'] == 'RCP-2026-00011'
    query, params = connection.cursor_obj.executed[-1]
    assert params == ('MPESA', 'QWE123', 55)
    assert 'fp.school_id = %s' in query.lower()
    assert 'fr.school_id = fp.school_id' in query.lower()


def test_fees_service_term_summary_is_scoped_to_student_term_and_school():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'charges': Decimal('1500.00'),
                'debits': Decimal('50.00'),
                'payments': Decimal('1000.00'),
                'credits': Decimal('100.00'),
            }),
        ]
    )
    service = FeesService(connection, school_id=55)

    summary = service.get_student_term_summary(1001, 3)

    assert summary == {
        'charges': Decimal('1500.00'),
        'debits': Decimal('50.00'),
        'payments': Decimal('1000.00'),
        'credits': Decimal('100.00'),
        'net_due': Decimal('450.00'),
    }
    query, params = connection.cursor_obj.executed[0]
    assert params == (1001, 3, 55)
    assert 'where admno = %s and term_id = %s and school_id = %s' in query.lower()
    assert "description like 'debit note:%%'" in query.lower()
    assert "description like 'credit note:%%'" in query.lower()
    assert "description like 'void receipt:%%'" in query.lower()


def test_fees_service_statement_summary_is_scoped_and_classifies_ledger_events():
    connection = RecordingConnection(
        responses=[
            ('all', [{'academic_year': 2026, 'term_number': 1, 'charges': Decimal('1500.00'),
                      'debits': Decimal('50.00'), 'payments': Decimal('1000.00'),
                      'credits': Decimal('100.00'), 'waivers': Decimal('200.00'),
                      'refunds': Decimal('0.00'), 'opening_balance': Decimal('0.00'),
                      'closing_balance': Decimal('250.00'), 'transaction_count': 5}]),
        ]
    )
    service = FeesService(connection, school_id=55)

    summary = service.get_student_statement_summary(1001, year_id=4)

    assert summary[0]['closing_balance'] == Decimal('250.00')
    query, params = connection.cursor_obj.executed[0]
    assert params == [1001, 55, 4]
    assert 'where fl.admno = %s and fl.school_id = %s' in query.lower()
    assert 'fl.academic_year_id = %s' in query.lower()
    assert "reference_no like 'wvr-%%'" in query.lower()
    assert "description like 'void receipt:%%'" in query.lower()


def test_fees_service_term_invoices_are_scoped_to_student_term_and_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'reference_no': 'INV-1001-2026-3', 'issued_on': '2026-01-15', 'amount': Decimal('1500.00'), 'item_count': 2}]),
        ]
    )
    service = FeesService(connection, school_id=55)

    invoices = service.get_student_term_invoices(1001, 3)

    assert invoices == [{'reference_no': 'INV-1001-2026-3', 'issued_on': '2026-01-15', 'amount': Decimal('1500.00'), 'item_count': 2}]
    query, params = connection.cursor_obj.executed[0]
    assert params == (1001, 3, 55)
    assert "type = 'charge'" in query.lower()
    assert "reference_no like 'inv-%%'" in query.lower()
    assert 'and school_id = %s' in query.lower()


def test_fees_service_saves_allocation_template_with_tenant_scoped_voteheads():
    connection = RecordingConnection(
        responses=[
            ('all', [{'id': 4}, {'id': 7}]),
        ]
    )
    connection.cursor_obj.lastrowid = 12
    service = FeesService(connection, school_id=55)

    template = service.create_allocation_template(
        'Boarding Split',
        [{'votehead_id': 4, 'amount': '1000.00'}, {'votehead_id': 7, 'amount': '500.00'}],
        user_id=9,
    )

    assert template == {
        'id': 12,
        'name': 'Boarding Split',
        'items': [
            {'votehead_id': 4, 'amount': Decimal('1000.00')},
            {'votehead_id': 7, 'amount': Decimal('500.00')},
        ],
    }
    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    votehead_query, votehead_params = connection.cursor_obj.executed[0]
    assert votehead_params == (4, 7, 55)
    assert 'from fee_voteheads where id in (%s, %s) and school_id = %s' in votehead_query.lower()
    template_query, template_params = connection.cursor_obj.executed[1]
    assert template_params == (55, 'Boarding Split', 9)
    assert 'insert into fee_allocation_templates' in template_query.lower()
    item_queries = connection.cursor_obj.executed[2:]
    assert all('insert into fee_allocation_template_items' in query.lower() for query, _ in item_queries)
    assert item_queries[0][1] == (12, 4, Decimal('1000.00'), 55)
    assert item_queries[1][1] == (12, 7, Decimal('500.00'), 55)


def test_fees_service_rejects_duplicate_payment_before_ledger_write():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}),
            ('one', {'id': 2026}),
            ('one', {'id': 3}),
            ('one', {
                'id': 11,
                'admno': 1001,
                'amount': Decimal('1500.00'),
                'payment_date': '2026-07-30',
                'status': 'COMPLETED',
                'receipt_no': 'RCP-2026-00011',
            }),
        ]
    )
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {
        'fee_payments': {'school_id'},
        'fee_payment_allocations': {'school_id'},
        'fee_receipts': {'school_id'},
    }

    with pytest.raises(FeesError, match="already exists for MPESA"):
        FeesService.record_payment.__wrapped__(
            service,
            admno=1001,
            amount=Decimal('1500.00'),
            mode='MPESA',
            reference='QWE123',
            bank='',
            date='2026-07-30',
            year_id=2026,
            term_id=3,
            user_id=9,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    assert all('insert into fee_ledger' not in query.lower() for query, _ in connection.cursor_obj.executed)


def test_fees_service_rejects_payment_with_unmapped_receiving_account_before_transaction():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}),
            ('one', {'id': 2026}),
            ('one', {'id': 3}),
            ('one', None),
            ('one', None),
        ]
    )
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {
        'fee_payments': {'school_id', 'receiving_account_id'},
        'fee_payment_allocations': {'school_id'},
        'fee_receipts': {'school_id'},
    }

    with pytest.raises(FeesError, match="No active receiving account is configured for payment mode 'MPESA'"):
        FeesService.record_payment.__wrapped__(
            service,
            admno=1001,
            amount=Decimal('1500.00'),
            mode='MPESA',
            reference='QWE123',
            bank='',
            date='2026-07-30',
            year_id=2026,
            term_id=3,
            user_id=9,
        )

    assert connection.begin_calls == 0
    assert all('insert into fee_ledger' not in query.lower() for query, _ in connection.cursor_obj.executed)


def test_fees_service_rejects_cash_payment_without_open_cashier_session():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}),
            ('one', {'id': 2026}),
            ('one', {'id': 3}),
            ('one', None),
            ('one', {'account_id': 17}),
            ('one', None),
        ]
    )
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {
        'fee_payments': {'school_id', 'receiving_account_id', 'cashier_session_id'},
        'fee_payment_allocations': {'school_id'},
        'fee_receipts': {'school_id'},
    }

    with pytest.raises(FeesError, match='Open a cashier session before posting a cash receipt'):
        FeesService.record_payment.__wrapped__(
            service, admno=1001, amount=Decimal('1500.00'), mode='CASH', reference='CASH-1',
            bank='', date='2026-07-31', year_id=2026, term_id=3, user_id=9,
        )

    assert connection.begin_calls == 0
    assert all('insert into fee_ledger' not in query.lower() for query, _ in connection.cursor_obj.executed)


def test_fees_service_void_receipt_records_immutable_lifecycle_snapshot():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 12, 'ledger_id': 45, 'admno': 1001, 'amount': Decimal('1500.00'),
                'payment_mode': 'CASH', 'reference_number': 'CASH-1', 'status': 'COMPLETED',
            }),
            ('all', [{'votehead_id': 4, 'amount': Decimal('1500.00')}]),
            ('one', {'academic_year_id': 2026, 'term_id': 3}),
            ('one', {'balance_after': Decimal('500.00')}),
        ]
    )
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {
        'fee_payments': {'school_id'},
        'fee_payment_allocations': {'school_id'},
    }

    assert FeesService.void_receipt.__wrapped__(service, 12, user_id=9, reason='Wrong student') is True

    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    lifecycle_query, lifecycle_params = connection.cursor_obj.executed[-1]
    assert 'insert into fee_receipt_lifecycle_events' in lifecycle_query.lower()
    assert lifecycle_params[:6] == (55, 12, 'Wrong student', 9, lifecycle_params[4], lifecycle_params[5])
    snapshot = json.loads(lifecycle_params[5])
    assert snapshot['payment']['reference_number'] == 'CASH-1'
    assert snapshot['allocations'] == [{'amount': '1500.00', 'votehead_id': 4}]
    assert snapshot['reversal_reference'] == 'VOID-CASH-1'


def test_fees_service_record_payment_records_posted_lifecycle_snapshot():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}),
            ('one', {'id': 2026}),
            ('one', {'id': 3}),
            ('one', None),
            ('one', {'account_id': 17}),
            ('one', {'balance_after': Decimal('2000.00')}),
            ('all', []),
            ('one', {'id': 4}),
        ]
    )
    connection.cursor_obj.lastrowid = 12
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {
        'fee_payments': {'school_id', 'receiving_account_id'},
        'fee_payment_allocations': {'school_id'},
        'fee_receipts': {'school_id'},
    }

    result = FeesService.record_payment.__wrapped__(
        service, admno=1001, amount=Decimal('1500.00'), mode='MPESA', reference='MPESA-1',
        bank='', date='2026-07-31', year_id=2026, term_id=3, user_id=9,
    )

    assert result['receipt_no'] == 'RCP-2026-00012'
    assert connection.commit_calls == 1
    lifecycle_query, lifecycle_params = connection.cursor_obj.executed[-1]
    assert 'insert into fee_receipt_lifecycle_events' in lifecycle_query.lower()
    assert lifecycle_params[:4] == (55, 12, 9, lifecycle_params[3])
    snapshot = json.loads(lifecycle_params[4])
    assert snapshot['receipt_no'] == 'RCP-2026-00012'
    assert snapshot['payment']['receiving_account_id'] == 17
    assert snapshot['allocations'] == [{'amount': '1500.00', 'votehead_id': 4}]


def test_fees_service_reposts_cancelled_receipt_through_normal_payment_posting():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 12, 'admno': 1001, 'amount': Decimal('1500.00'), 'payment_mode': 'MPESA',
                'bank_name': '', 'status': 'CANCELLED', 'academic_year_id': 2026, 'term_id': 3,
            }),
        ]
    )
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {'fee_payments': {'school_id'}}
    captured = {}

    def record_payment(**kwargs):
        captured.update(kwargs)
        return {'payment_id': 88, 'receipt_no': 'RCP-2026-00088'}

    service.record_payment = record_payment
    result = FeesService.repost_cancelled_receipt.__wrapped__(
        service, payment_id=12, new_reference='MPESA-NEW', posting_date='2026-07-31', user_id=9,
    )

    assert result == {'payment_id': 88, 'receipt_no': 'RCP-2026-00088'}
    assert captured['admno'] == 1001
    assert captured['amount'] == Decimal('1500.00')
    assert captured['mode'] == 'MPESA'
    assert captured['reference'] == 'MPESA-NEW'
    assert captured['year_id'] == 2026
    assert captured['term_id'] == 3
    assert captured['lifecycle_source_payment_id'] == 12
    assert captured['lifecycle_correlation_id']


def test_fees_service_reallocation_recalculates_both_student_ledger_balances():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}),
            ('one', {'AdmNo': 1002}),
            ('one', {'id': 12, 'ledger_id': 45, 'amount': Decimal('1500.00'), 'status': 'COMPLETED'}),
            ('all', [{'id': 10, 'type': 'CHARGE', 'amount': Decimal('2000.00'), 'description': 'Term fees'}]),
            ('all', [
                {'id': 20, 'type': 'CHARGE', 'amount': Decimal('3000.00'), 'description': 'Term fees'},
                {'id': 45, 'type': 'PAYMENT', 'amount': Decimal('1500.00'), 'description': 'Payment via MPESA'},
            ]),
        ]
    )
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {'fee_payments': {'school_id'}}

    service.reallocate_payment('MPESA-1', 1001, 1002, user_id=9, reason='Wrong sibling')

    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    audit_query, audit_params = connection.cursor_obj.executed[3]
    assert 'insert into fee_reallocation_log' in audit_query.lower()
    assert audit_params[:8] == (1001, 1002, 'MPESA-1', Decimal('1500.00'), 12, 'Wrong sibling', 9, 55)
    balance_updates = [(query, params) for query, params in connection.cursor_obj.executed if 'update fee_ledger set balance_after' in query.lower()]
    assert [params for _, params in balance_updates] == [
        (Decimal('2000.00'), 10, 55),
        (Decimal('3000.00'), 20, 55),
        (Decimal('1500.00'), 45, 55),
    ]
    lifecycle_query, lifecycle_params = connection.cursor_obj.executed[-1]
    assert 'insert into fee_receipt_lifecycle_events' in lifecycle_query.lower()
    assert lifecycle_params[:4] == (55, 12, 'Wrong sibling', 9)


def test_fees_service_posts_credit_note_with_linked_adjustment_ledger_entry():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}),
            ('one', {'id': 2026}),
            ('one', {'id': 3}),
            ('all', [{'id': 4}]),
            ('one', {'balance_after': Decimal('2000.00')}),
        ]
    )
    connection.cursor_obj.lastrowid = 31
    service = FeesService(connection, school_id=55)

    adjustment_id = service.create_account_adjustment(
        admno=1001, adjustment_type='CREDIT', votehead_id=4, amount=Decimal('250.00'),
        year_id=2026, term_id=3, effective_date='2026-07-31', reason='Approved overcharge correction',
        supporting_reference='CASE-42', user_id=9,
    )

    assert adjustment_id == 31
    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    adjustment_query, adjustment_params = connection.cursor_obj.executed[4]
    assert 'insert into fee_adjustments' in adjustment_query.lower()
    assert adjustment_params == (1001, 2026, 3, 4, Decimal('250.00'), 'CREDIT', 'Approved overcharge correction', '2026-07-31', 'CASE-42', 9, 9, 55)
    ledger_query, ledger_params = connection.cursor_obj.executed[6]
    assert "'adjustment'" in ledger_query.lower()
    assert ledger_params[5] == Decimal('1750.00')
    assert ledger_params[6] == 'CREDIT NOTE: Approved overcharge correction'
    assert ledger_params[7] == 'CRE-31'


def test_fees_service_receipts_register_scopes_search_and_lifecycle_filters():
    connection = RecordingConnection(responses=[('all', [])])
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {'fee_payments': {'school_id'}, 'fee_receipts': {'school_id'}}

    assert service.get_receipts_register(
        start_date='2026-07-01', end_date='2026-07-31', admno=1001,
        mode='MPESA', query_text='RCP-001', status='CANCELLED',
    ) == []

    query, params = connection.cursor_obj.executed[0]
    assert params == [55, '2026-07-01', '2026-07-31', 1001, 'MPESA', 'CANCELLED', '%RCP-001%', '%RCP-001%', '%RCP-001%']
    assert 'fp.school_id = %s' in query.lower()
    assert 'fp.status = %s' in query.lower()
    assert 'fr.receipt_no like %s' in query.lower()
    assert 'fp.reference_number like %s' in query.lower()


def test_fees_service_lifecycle_register_scopes_events_and_filters():
    connection = RecordingConnection(responses=[('all', [])])
    service = FeesService(connection, school_id=55)

    assert service.get_receipt_lifecycle_register('2026-07-01', '2026-07-31', 'CANCELLED') == []

    query, params = connection.cursor_obj.executed[0]
    assert params == [55, '2026-07-01', '2026-07-31', 'CANCELLED']
    assert 'events.school_id = %s' in query.lower()
    assert 'events.event_type = %s' in query.lower()
    assert 'payments.school_id = receipts.school_id' in query.lower()


def test_fees_service_reallocation_register_scopes_source_and_destination_students():
    connection = RecordingConnection(responses=[('all', [])])
    service = FeesService(connection, school_id=55)

    assert service.get_reallocation_register('2026-07-01', '2026-07-31') == []

    query, params = connection.cursor_obj.executed[0]
    assert params == [55, '2026-07-01', '2026-07-31']
    assert 'reallocations.school_id = %s' in query.lower()
    assert 'reallocations.school_id = source.school_id' in query.lower()
    assert 'reallocations.school_id = destination.school_id' in query.lower()
    assert 'reallocations.school_id = receipts.school_id' in query.lower()


def test_fees_service_collection_status_summary_scopes_receipt_statuses_to_school():
    connection = RecordingConnection(responses=[('all', [])])
    service = FeesService(connection, school_id=55)
    service._table_columns_cache = {'fee_payments': {'school_id'}}

    assert service.get_collection_status_summary('2026-07-01', '2026-07-31') == []

    query, params = connection.cursor_obj.executed[0]
    assert params == ('2026-07-01', '2026-07-31', 55)
    assert 'where payment_date between %s and %s and school_id = %s' in query.lower()
    assert 'group by status, payment_mode' in query.lower()


def test_fees_service_category_change_preflight_blocks_paid_term_allocations():
    connection = RecordingConnection(responses=[
        ('one', {'AdmNo': 1001}), ('one', {'id': 4}), ('one', {'id': 3}),
        ('all', [{'reference_no': 'INV-1001-4-3'}]), ('one', {'allocation_count': 1}), ('one', {'locked_count': 0}),
    ])
    service = FeesService(connection, school_id=55)

    result = service.get_category_change_preflight(1001, 4, 3)

    assert result['eligible'] is False
    assert result['has_current_term_invoice'] is True
    assert 'Completed payment allocations exist' in result['blockers'][0]
    allocation_query, allocation_params = connection.cursor_obj.executed[4]
    assert allocation_params == (1001, 4, 3, 55)
    assert 'allocations.school_id = payments.school_id' in allocation_query.lower()


def test_fees_service_category_invoice_replacement_stops_before_writes_when_paid():
    connection = RecordingConnection(responses=[
        ('one', {'AdmNo': 1001}), ('one', {'id': 4}), ('one', {'id': 3}),
        ('all', [{'reference_no': 'INV-1001-4-3'}]), ('one', {'allocation_count': 1}), ('one', {'locked_count': 0}),
    ])
    service = FeesService(connection, school_id=55)

    with pytest.raises(FeesError, match='Completed payment allocations exist'):
        service.replace_category_invoice(1001, 4, 3, 'Boarding', None, 'Boarding correction', user_id=9)

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert all('insert into fee_ledger' not in query.lower() for query, _ in connection.cursor_obj.executed)


def test_fees_service_records_reprint_event_after_prior_print():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 12}),
            ('one', {'print_count': 1}),
        ]
    )
    service = FeesService(connection, school_id=55)

    event_type = service.record_receipt_print(12, user_id=9)

    assert event_type == 'REPRINTED'
    assert connection.commit_calls == 1
    insert_query, insert_params = connection.cursor_obj.executed[-1]
    assert 'insert into fee_receipt_lifecycle_events' in insert_query.lower()
    assert insert_params[:5] == (55, 12, 'REPRINTED', 'COMPLETED', 9)


def test_fees_service_archives_receipt_without_changing_payment():
    connection = RecordingConnection(responses=[('one', {'id': 12}), ('one', None)])
    service = FeesService(connection, school_id=55)

    service.archive_receipt(12, 'End of year retention', user_id=9)

    assert connection.commit_calls == 1
    assert all('update fee_payments' not in query.lower() for query, _ in connection.cursor_obj.executed)
    insert_query, insert_params = connection.cursor_obj.executed[-1]
    assert 'insert into fee_receipt_lifecycle_events' in insert_query.lower()
    assert insert_params[:5] == (55, 12, 'End of year retention', 9, insert_params[4])


def test_fees_service_rejects_structure_create_with_foreign_votehead():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 2026}),
            ('one', {'id': 3}),
            ('all', []),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='voteheads do not belong to the active school'):
        service.create_fee_structure(
            year_id=2026,
            term_id=3,
            class_group='Grade 4-6',
            category='Day',
            items=[{'votehead_id': 99, 'amount': '1500.00'}],
            user_id=4,
        )

    assert connection.commit_calls == 0
    assert connection.begin_calls == 0


def test_fees_service_rejects_structure_create_with_invalid_votehead_id_before_transaction():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 2026}),
            ('one', {'id': 3}),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='votehead_id must be a valid integer'):
        service.create_fee_structure(
            year_id=2026,
            term_id=3,
            class_group='Grade 4-6',
            category='Day',
            items=[{'votehead_id': 'bad', 'amount': '1500.00'}],
            user_id=4,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0


def test_fees_service_rejects_custom_invoice_with_foreign_votehead():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001'}),
            ('one', {'id': 2026}),
            ('one', {'id': 1}),
            ('one', {'year': 2026}),
            ('one', {'term_number': 1}),
            ('all', []),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='voteheads do not belong to the active school'):
        FeesService.invoice_student.__wrapped__(
            service,
            admno=1001,
            year_id=2026,
            term_id=1,
            structure_id=0,
            user_id=4,
            custom_items=[{'votehead_id': 99, 'amount': '750.00', 'votehead_name': 'Transport'}],
        )


def test_fees_service_rejects_custom_invoice_with_invalid_votehead_id_before_structure_lookup():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001'}),
            ('one', {'id': 2026}),
            ('one', {'id': 1}),
            ('one', {'year': 2026}),
            ('one', {'term_number': 1}),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='votehead_id must be a valid integer'):
        FeesService.invoice_student.__wrapped__(
            service,
            admno=1001,
            year_id=2026,
            term_id=1,
            structure_id=0,
            user_id=4,
            custom_items=[{'votehead_id': 'bad', 'amount': '750.00', 'votehead_name': 'Transport'}],
        )


def test_fees_service_rejects_waiver_assignment_with_foreign_category():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001'}),
            ('one', {'id': 2026}),
            ('one', {'id': 1}),
            ('one', None),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='Invalid waiver category'):
        service.assign_waiver_to_student(admno=1001, category_id=77, year_id=2026, term_id=1, user_id=4)


def test_fees_service_revokes_linked_waiver_with_a_debit_adjustment():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 44, 'admno': 1001, 'academic_year_id': 4, 'term_id': 3, 'ledger_id': 91,
                     'status': 'ACTIVE', 'category_name': 'Bursary Award', 'waiver_amount': Decimal('500.00')}),
            ('one', {'balance_after': Decimal('250.00')}),
        ]
    )
    service = FeesService(connection, school_id=55)

    service.revoke_waiver(44, 'Award criteria no longer apply', user_id=8)

    insert_query, insert_params = connection.cursor_obj.executed[2]
    assert "'adjustment'" in insert_query.lower()
    assert insert_params[4] == Decimal('750.00')
    assert insert_params[5].startswith('WAIVER REVERSAL: Bursary Award')
    assert connection.commit_calls == 1


def test_fees_service_rejects_votehead_create_with_foreign_student_group():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='Student group not found for the active school'):
        service.create_votehead('Lunch', priority=5, group_id=77, description='Lunch fees')

    assert connection.commit_calls == 0


def test_fees_service_rejects_bulk_structure_create_with_foreign_class():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 2026}),
            ('one', {'id': 1}),
            ('all', [{'id': 10}]),
            ('all', []),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='One or more classes do not belong to the active school'):
        service.create_bulk_fee_structures(
            year_id=2026,
            term_id=1,
            class_groups=[],
            categories=['Day'],
            items=[{'votehead_id': 10, 'amount': '1500.00'}],
            user_id=4,
            class_ids=[99],
        )


def test_fees_service_rejects_payment_record_with_foreign_student_before_transaction():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='Student not found for the active school'):
        FeesService.record_payment.__wrapped__(
            service,
            admno=9999,
            amount=Decimal('2500.00'),
            mode='BANK',
            reference='REF-1',
            bank='KCB',
            date='2026-04-03',
            year_id=2026,
            term_id=1,
            user_id=4,
        )

    assert connection.begin_calls == 0
    assert connection.rollback_calls == 1


def test_fees_service_rejects_payment_reallocation_with_foreign_target_student():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001'}),
            ('one', None),
        ]
    )
    service = FeesService(connection, school_id=58)

    with pytest.raises(FeesError, match='Student not found for the active school'):
        service.reallocate_payment('REF-1', 1001, 9999, user_id=4, reason='Correction')

    assert connection.begin_calls == 0
    assert connection.rollback_calls == 1


def test_fees_service_scopes_structure_queries_to_school_joins():
    connection = RecordingConnection(
        responses=[
            ('all', [{'id': 1, 'year_name': 2026, 'specific_class_name': 'Grade 4 A'}]),
            ('one', {'id': 1, 'year_name': 2026, 'specific_class_name': 'Grade 4 A'}),
            ('all', [{'votehead_name': 'Tuition', 'amount': Decimal('1500.00')}]),
        ]
    )
    service = FeesService(connection, school_id=58)

    structures = service.get_fee_structures(year_id=2026)
    structure = service.get_fee_structure_details(1)

    assert structures == [{'id': 1, 'year_name': 2026, 'specific_class_name': 'Grade 4 A'}]
    assert structure['id'] == 1
    assert structure['items'] == [{'votehead_name': 'Tuition', 'amount': Decimal('1500.00')}]

    structures_query, structures_params = connection.cursor_obj.executed[0]
    details_query, details_params = connection.cursor_obj.executed[1]
    items_query, items_params = connection.cursor_obj.executed[2]

    assert structures_params == [58, 2026]
    assert 'fs.academic_year_id = ay.id and fs.school_id = ay.school_id' in structures_query.lower()
    assert 'fs.term_id = utd.id and fs.school_id = utd.school_id' in structures_query.lower()
    assert 'fs.class_id = c.classid and fs.school_id = c.school_id' in structures_query.lower()

    assert details_params == (1, 58)
    assert 'fs.academic_year_id = ay.id and fs.school_id = ay.school_id' in details_query.lower()
    assert 'fs.term_id = utd.id and fs.school_id = utd.school_id' in details_query.lower()
    assert 'fs.class_id = c.classid and fs.school_id = c.school_id' in details_query.lower()

    assert items_params == (1, 58)
    assert 'fsi.votehead_id = fv.id and fsi.school_id = fv.school_id' in items_query.lower()


def test_procurement_service_create_supplier_requires_school_scoped_supplier_and_persists_school_id():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'supplierID'}, {'Field': 'company'}, {'Field': 'school_id'}]),
        ]
    )
    connection.cursor_obj.lastrowid = 44
    service = ProcurementService(connection, school_id=12)

    supplier_id = ProcurementService.create_supplier.__wrapped__(
        service,
        company='Acme Supplies',
        contact_person='Jane Buyer',
        email='acme@example.com',
        phone='0712345678',
        address='Nairobi',
        cert_no='CERT-9',
        pin_no='PIN-9',
    )

    assert supplier_id == 44
    assert connection.commit_calls == 1
    insert_query, insert_params = connection.cursor_obj.executed[1]
    assert 'insert into suppliers' in insert_query.lower()
    assert 'school_id' in insert_query.lower()
    assert insert_params[-1] == 12


def test_procurement_service_rejects_purchase_order_create_for_other_school_supplier():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'supplierID'}, {'Field': 'school_id'}]),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=63)

    with pytest.raises(ProcurementError, match='Supplier not found for the active school'):
        ProcurementService.create_purchase_order.__wrapped__(
            service,
            supplier_id=99,
            order_date='2026-03-31',
            items=[{'description': 'Desk', 'quantity': 2, 'unit_price': '500.00'}],
            user_id=5,
        )

    assert connection.begin_calls == 0
    assert connection.rollback_calls == 1
    supplier_query, supplier_params = connection.cursor_obj.executed[3]
    assert supplier_params == (99, 63)
    assert 'where supplierid = %s and school_id = %s' in supplier_query.lower()


def test_procurement_service_rejects_requisition_create_for_foreign_department():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'deptID'}, {'Field': 'school_id'}]),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=63)

    with pytest.raises(ProcurementError, match='Department not found for the active school'):
        ProcurementService.create_requisition.__wrapped__(
            service,
            department_id=99,
            items=[{'description': 'Desk', 'quantity': 2, 'estimated_unit_price': '500.00'}],
            user_id=5,
            justification='Need desks',
            category='General',
            academic_year_id=2026,
        )

    assert connection.begin_calls == 0
    assert connection.rollback_calls == 1


def test_procurement_service_rejects_purchase_order_create_for_foreign_department():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'supplierID'}, {'Field': 'school_id'}]),
            ('one', {'supplierID': 9}),
            ('all', [{'Field': 'deptID'}, {'Field': 'school_id'}]),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=63)

    with pytest.raises(ProcurementError, match='Department not found for the active school'):
        ProcurementService.create_purchase_order.__wrapped__(
            service,
            supplier_id=9,
            order_date='2026-03-31',
            items=[{'description': 'Desk', 'quantity': 2, 'unit_price': '500.00'}],
            user_id=5,
            department_id=99,
            academic_year_id=2026,
        )

    assert connection.begin_calls == 0
    assert connection.rollback_calls == 1


def test_procurement_service_rejects_requisition_create_for_foreign_academic_year():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'deptID'}, {'Field': 'school_id'}]),
            ('one', {'deptID': 5}),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=63)

    with pytest.raises(ProcurementError, match='Academic year not found for the active school'):
        ProcurementService.create_requisition.__wrapped__(
            service,
            department_id=5,
            items=[{'description': 'Desk', 'quantity': 2, 'estimated_unit_price': '500.00'}],
            user_id=5,
            justification='Need desks',
            category='General',
            academic_year_id=2026,
        )

    assert connection.begin_calls == 1
    assert connection.rollback_calls == 1


def test_procurement_service_scopes_purchase_order_updates_and_item_refresh_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'supplierID'}, {'Field': 'school_id'}]),
            ('one', {'supplierID': 9}),
            ('one', {'status': 'DRAFT'}),
        ]
    )
    service = ProcurementService(connection, school_id=70)

    updated = ProcurementService.update_purchase_order.__wrapped__(
        service,
        po_id=14,
        supplier_id=9,
        order_date='2026-03-31',
        items=[{'item_id': 4, 'description': 'Desk', 'quantity': 2, 'unit_price': '500.00'}],
        notes='Repriced',
    )

    assert updated is True
    assert connection.begin_calls == 1
    assert connection.commit_calls == 1

    status_query, status_params = connection.cursor_obj.executed[4]
    update_query, update_params = connection.cursor_obj.executed[5]
    delete_query, delete_params = connection.cursor_obj.executed[6]
    insert_query, insert_params = connection.cursor_obj.executed[7]

    assert status_params == (14, 70)
    assert 'where id = %s and school_id = %s' in status_query.lower()

    assert update_params[-2:] == (14, 70)
    assert 'where id = %s and school_id = %s' in update_query.lower()

    assert delete_params == (14, 70)
    assert 'delete from purchase_order_items where po_id = %s and school_id = %s' in delete_query.lower()

    assert insert_params[-1] == 70
    assert 'insert into purchase_order_items' in insert_query.lower()
    assert 'school_id' in insert_query.lower()


def test_procurement_service_scopes_purchase_order_deletes_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('one', {'status': 'DRAFT'}),
        ]
    )
    service = ProcurementService(connection, school_id=81)

    deleted = ProcurementService.delete_purchase_order.__wrapped__(service, 22)

    assert deleted is True
    assert connection.begin_calls == 1
    assert connection.commit_calls == 1

    status_query, status_params = connection.cursor_obj.executed[2]
    items_delete_query, items_delete_params = connection.cursor_obj.executed[3]
    order_delete_query, order_delete_params = connection.cursor_obj.executed[4]

    assert status_params == (22, 81)
    assert 'where id = %s and school_id = %s' in status_query.lower()
    assert items_delete_params == (22, 81)
    assert 'delete from purchase_order_items where po_id = %s and school_id = %s' in items_delete_query.lower()
    assert order_delete_params == (22, 81)
    assert 'delete from purchase_orders where id = %s and school_id = %s' in order_delete_query.lower()


def test_procurement_service_rejects_po_status_update_with_invalid_item_quantity():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'item_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'item_id'}, {'Field': 'school_id'}]),
            ('one', {'id': 15, 'status': 'ORDERED', 'po_number': 'PO-0015-26', 'total_amount': Decimal('5000.00'), 'supplier_id': 9, 'category': 'General', 'academic_year_id': 2026, 'department_id': 5}),
            ('one', {'id': 1}),
            ('one', {'id': 6}),
            ('all', [{'id': 101, 'item_id': 11, 'description': 'Blazer', 'quantity': 'bad'}]),
            ('one', {'current_stock': 4}),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    with pytest.raises(ProcurementError, match='Failed to update PO status: quantity must be a valid integer'):
        service.update_po_status(15, 'RECEIVED', 8)

    assert connection.begin_calls == 1
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1


def test_procurement_service_scopes_supplier_lists_and_po_register_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'supplierID'}, {'Field': 'company'}, {'Field': 'school_id'}]),
            ('all', [{'supplierID': 9, 'company': 'Acme Supplies'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'id': 15, 'po_number': 'PO-0015-26', 'supplier_name': 'Acme Supplies'}]),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    suppliers = service.get_suppliers()
    purchase_orders = service.get_purchase_orders(status='ORDERED', supplier_id=9)

    assert suppliers == [{'supplierID': 9, 'company': 'Acme Supplies'}]
    assert purchase_orders == [{'id': 15, 'po_number': 'PO-0015-26', 'supplier_name': 'Acme Supplies'}]

    suppliers_query, suppliers_params = connection.cursor_obj.executed[1]
    orders_query, orders_params = connection.cursor_obj.executed[3]

    assert suppliers_params == [52]
    assert 'where school_id = %s and in_operation = ' in suppliers_query.lower()

    assert orders_params == [52, 'ORDERED', 9]
    assert 'po.school_id = s.school_id' in orders_query
    assert 'po.created_by = u.userno and po.school_id = u.school_id' in orders_query.lower()
    assert 'where po.school_id = %s' in orders_query.lower()


def test_procurement_service_scopes_dashboard_and_reference_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'status': 'RECEIVED', 'count': 4}]),
            ('all', [{'Field': 'deptID'}, {'Field': 'school_id'}]),
            ('all', [{'deptID': 1, 'dept': 'Procurement'}]),
            ('all', [{'id': 2026, 'year': 2026}]),
            ('one', {'id': 2026}),
            ('all', [{'Field': 'supplierID'}, {'Field': 'school_id'}]),
            ('one', {'supplierID': 5, 'company': 'Acme Supplies'}),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'id': 1, 'payment_mode': 'BANK'}]),
            ('all', [{'item_id': 9, 'item_name': 'Blazer', 'current_stock': 4}]),
            ('all', [{'item_name': 'Tie', 'item_id': 3, 'current_stock': 12}]),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    assert service.get_purchase_order_status_counts() == [{'status': 'RECEIVED', 'count': 4}]
    assert service.get_departments() == [{'deptID': 1, 'dept': 'Procurement'}]
    assert service.get_academic_years() == [{'id': 2026, 'year': 2026}]
    assert service.get_current_academic_year_id() == 2026
    assert service.get_supplier_by_id(5) == {'supplierID': 5, 'company': 'Acme Supplies'}
    assert service.get_purchase_order_payments(10) == [{'id': 1, 'payment_mode': 'BANK'}]
    assert service.get_stock_items() == [{'item_id': 9, 'item_name': 'Blazer', 'current_stock': 4}]
    assert service.get_uniform_items_with_stock() == [{'item_name': 'Tie', 'item_id': 3, 'current_stock': 12}]

    stats_query, stats_params = connection.cursor_obj.executed[1]
    departments_query, departments_params = connection.cursor_obj.executed[3]
    years_query, years_params = connection.cursor_obj.executed[4]
    current_year_query, current_year_params = connection.cursor_obj.executed[5]
    supplier_query, supplier_params = connection.cursor_obj.executed[7]
    payments_query, payments_params = connection.cursor_obj.executed[9]
    stock_query, stock_params = connection.cursor_obj.executed[10]
    uniform_query, uniform_params = connection.cursor_obj.executed[11]

    assert stats_params == (52,)
    assert 'where school_id = %s group by status' in stats_query.lower()
    assert departments_params == (52,)
    assert 'from staffdepts where school_id = %s' in departments_query.lower()
    assert years_params == (52,)
    assert 'from academic_years where school_id = %s' in years_query.lower()
    assert current_year_params == (52,)
    assert 'is_current = 1 and school_id = %s' in current_year_query.lower()
    assert supplier_params == (5, 52)
    assert 'where supplierid = %s and school_id = %s' in supplier_query.lower()
    assert payments_params == (10, 52)
    assert 'where po_id = %s and school_id = %s' in payments_query.lower()
    assert stock_params == (52,)
    assert 'from item_stock where school_id = %s' in stock_query.lower()
    assert uniform_params == (52,)
    assert 'where p.school_id = %s' in uniform_query.lower()


def test_procurement_service_rejects_po_payment_with_foreign_source_account():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    with pytest.raises(ProcurementError, match='Selected account does not belong to the active school'):
        ProcurementService.record_po_payment.__wrapped__(
            service,
            po_id=15,
            amount=Decimal('2500.00'),
            mode='BANK',
            reference='REF-1',
            date='2026-04-01',
            user_id=8,
            source_account_id=44,
        )

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    query, params = connection.cursor_obj.executed[5]
    assert 'select id from finance_accounts where id = %s and school_id = %s limit 1' in query.lower()
    assert params == (44, 52)


def test_procurement_service_rejects_record_grn_without_school_scoped_tables():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_item_id'}]),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    with pytest.raises(ProcurementError, match='Tenant isolation requires school_id on: procurement_grn_items'):
        ProcurementService.record_grn.__wrapped__(
            service,
            po_id=15,
            received_by=8,
            items=[{'po_item_id': 101, 'quantity': '2'}],
            delivery_note_ref='DN-1',
            notes='Partial delivery',
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0


def test_procurement_service_rejects_po_payment_for_unknown_purchase_order_before_insert():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('one', {'id': 44}),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    with pytest.raises(ProcurementError, match='Purchase order not found'):
        ProcurementService.record_po_payment.__wrapped__(
            service,
            po_id=15,
            amount=Decimal('2500.00'),
            mode='BANK',
            reference='REF-1',
            date='2026-04-01',
            user_id=8,
            source_account_id=44,
        )

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    assert not any('insert into supplier_payments' in query.lower() for query, _ in connection.cursor_obj.executed)


def test_procurement_service_scopes_po_detail_items_and_grns_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'supplierID'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_item_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}, {'Field': 'school_id'}]),
            ('one', {'id': 15, 'supplier_name': 'Acme Supplies'}),
            ('all', [{'id': 101, 'description': 'Blazer', 'total_received': 4}]),
            ('all', [{'id': 201, 'grn_number': 'GRN-0001-26'}]),
        ]
    )
    service = ProcurementService(connection, school_id=77)

    po = service.get_po_details(15)

    assert po['id'] == 15
    assert po['po_items'] == [{'id': 101, 'description': 'Blazer', 'total_received': 4}]
    assert po['grns'] == [{'id': 201, 'grn_number': 'GRN-0001-26'}]

    po_query, po_params = connection.cursor_obj.executed[5]
    items_query, items_params = connection.cursor_obj.executed[6]
    grns_query, grns_params = connection.cursor_obj.executed[7]

    assert po_params == (15, 77)
    assert 'po.school_id = s.school_id' in po_query
    assert 'where po.id = %s' in po_query.lower()
    assert 'and po.school_id = %s' in po_query.lower()

    assert items_params == (15, 77)
    assert 'poi.school_id = gi.school_id' in items_query
    assert 'where poi.po_id = %s and poi.school_id = %s' in items_query.lower()

    assert grns_params == (15, 77)
    assert 'where po_id = %s and school_id = %s' in grns_query.lower()


def test_procurement_service_scopes_supplier_aging_report_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'supplierID'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}, {'Field': 'school_id'}]),
            ('all', [{'supplierID': 9, 'supplier_name': 'Acme Supplies', 'total_owed': 2500}]),
        ]
    )
    service = ProcurementService(connection, school_id=91)

    aging = service.get_suppliers_aging()

    assert aging == [{'supplierID': 9, 'supplier_name': 'Acme Supplies', 'total_owed': 2500}]
    query, params = connection.cursor_obj.executed[3]
    assert params == (91, 91)
    assert 'from supplier_payments' in query.lower()
    assert 'where school_id = %s' in query.lower()
    assert 'po.school_id = s.school_id' in query
    assert 'and po.school_id = %s' in query.lower()


def test_procurement_service_rejects_supplier_list_without_school_scoped_table():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'supplierID'}, {'Field': 'company'}]),
        ]
    )
    service = ProcurementService(connection, school_id=91)

    with pytest.raises(ProcurementError, match='Tenant isolation requires school_id on: suppliers'):
        service.get_suppliers()


def test_procurement_service_rejects_po_details_without_school_scoped_grn_tables():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'supplierID'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_item_id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'po_id'}]),
        ]
    )
    service = ProcurementService(connection, school_id=91)

    with pytest.raises(ProcurementError, match='Tenant isolation requires school_id on: procurement_grns'):
        service.get_po_details(15)


def test_inventory_service_scopes_stock_movement_and_ledger_queries_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'movement_type': 'PURCHASE', 'item_name': 'Blazer'}]),
            ('all', [{'movement_type': 'ISSUANCE', 'item_id': 8}]),
        ]
    )
    service = InventoryService(connection, school_id=33)

    movements = service.get_stock_movements(start_date='2026-01-01', end_date='2026-01-31')
    ledger = service.get_stock_ledger('Blazer', start_date='2026-01-01', end_date='2026-01-31')

    assert movements == [{'movement_type': 'PURCHASE', 'item_name': 'Blazer'}]
    assert ledger == [{'movement_type': 'ISSUANCE', 'item_id': 8}]

    movements_query, movements_params = connection.cursor_obj.executed[0]
    ledger_query, ledger_params = connection.cursor_obj.executed[1]

    assert movements_params == [33, '2026-01-01', '2026-01-31']
    assert 'sm.school_id = is.school_id' in movements_query
    assert 'u.school_id = sm.school_id' in movements_query
    assert 'where sm.school_id = %s' in movements_query.lower()

    assert ledger_params == ['Blazer', 33, '2026-01-01', '2026-01-31']
    assert 'sm.school_id = ist.school_id' in ledger_query
    assert 'u.school_id = sm.school_id' in ledger_query
    assert 'where ist.item_name = %s and sm.school_id = %s' in ledger_query.lower()


def test_fees_service_create_student_group_persists_school_id():
    connection = RecordingConnection()
    connection.cursor_obj.lastrowid = 41
    service = FeesService(connection, school_id=58)

    group_id = service.create_student_group('Boarders', 'Boarding students')

    assert group_id == 41
    assert connection.commit_calls == 1
    query, params = connection.cursor_obj.executed[0]
    assert 'insert into student_groups' in query.lower()
    assert params == ('Boarders', 'Boarding students', 58)


def test_inventory_service_scopes_student_and_receipt_register_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001', 'display_name': 'Grade 4 A', 'class_group': 'Grade 4-6'}),
            ('all', [{'receipt_no': 'UNI-0001-26', 'AdmNo': '1001'}]),
        ]
    )
    service = InventoryService(connection, school_id=64)

    student = service.get_student_by_admno('1001')
    receipts = service.get_receipts_register(start_date='2026-01-01', end_date='2026-01-31')

    assert student == {'AdmNo': '1001', 'display_name': 'Grade 4 A', 'class_group': 'Grade 4-6'}
    assert receipts == [{'receipt_no': 'UNI-0001-26', 'AdmNo': '1001'}]

    student_query, student_params = connection.cursor_obj.executed[0]
    receipts_query, receipts_params = connection.cursor_obj.executed[1]

    assert student_params == ('1001', 64)
    assert 'ca.school_id = si.school_id' in student_query
    assert 'c.school_id = si.school_id' in student_query
    assert 'cgs.school_id = si.school_id' in student_query
    assert 'where si.admno = %s and si.school_id = %s' in student_query.lower()

    assert receipts_params == [64, '2026-01-01', '2026-01-31']
    assert 'ur.school_id = si.school_id' in receipts_query
    assert 'ur.school_id = u.school_id' in receipts_query
    assert 'where ur.school_id = %s' in receipts_query.lower()


def test_inventory_service_scopes_class_group_and_item_name_reference_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'code': 'Grade 1-3', 'name': 'Grade 1-3'}]),
            ('all', [{'item_name': 'Blazer'}]),
        ]
    )
    service = InventoryService(connection, school_id=64)

    class_groups = service.get_class_groups()
    items = service.get_item_name_options()

    assert class_groups == [{'code': 'Grade 1-3', 'name': 'Grade 1-3'}]
    assert items == [{'item_name': 'Blazer'}]

    groups_query, groups_params = connection.cursor_obj.executed[0]
    items_query, items_params = connection.cursor_obj.executed[1]

    assert groups_params == (64,)
    assert 'from class_group_settings where school_id = %s' in groups_query.lower()
    assert items_params == (64,)
    assert 'from uniform_prices where school_id = %s' in items_query.lower()


def test_inventory_service_rejects_issuance_for_foreign_student_before_stock_mutation():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = InventoryService(connection, school_id=64)

    with pytest.raises(ValueError, match='Student not found for the active school'):
        InventoryService.process_issuance.__wrapped__(
            service,
            '9999',
            [{'item_name': 'Blazer', 'quantity': 1, 'price': 1200, 'total': 1200}],
            10,
            'UNI-0001-26',
            1200,
        )

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    query, params = connection.cursor_obj.executed[0]
    assert params == ('9999', 64)
    assert 'where si.admno = %s and si.school_id = %s' in query.lower()


def test_inventory_service_rejects_issuance_for_item_outside_active_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001', 'display_name': 'Grade 4 A', 'class_group': 'Grade 4-6'}),
            ('one', None),
        ]
    )
    service = InventoryService(connection, school_id=64)

    with pytest.raises(ValueError, match='Item not found for the active school'):
        InventoryService.process_issuance.__wrapped__(
            service,
            '1001',
            [{'item_name': 'Blazer', 'quantity': 1, 'price': 1200, 'total': 1200}],
            10,
            'UNI-0001-26',
            1200,
        )

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    ownership_query, ownership_params = connection.cursor_obj.executed[1]
    assert ownership_params == ('Blazer', 64)
    assert 'select item_id from item_stock where item_name = %s and school_id = %s' in ownership_query.lower()


def test_inventory_service_rejects_invalid_issuance_item_payload_before_writes():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001', 'display_name': 'Grade 4 A', 'class_group': 'Grade 4-6'}),
        ]
    )
    service = InventoryService(connection, school_id=64)

    with pytest.raises(ValueError, match='Each issuance item must have a quantity greater than zero'):
        InventoryService.process_issuance.__wrapped__(
            service,
            '1001',
            [{'item_name': 'Blazer', 'quantity': 0, 'price': 1200, 'total': 1200}],
            10,
            'UNI-0001-26',
            1200,
        )

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1


def test_student_service_scopes_fee_and_exam_aggregates_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'total_billed': Decimal('10000.00'), 'total_paid': Decimal('6500.00'), 'current_balance': Decimal('3500.00')}),
            ('all', [{'rcptno': 'RCP-001', 'payment_id': 10}]),
            ('all', [{'exam_id': 3, 'exam_name': 'Midterm', 'mean_mark': Decimal('72.5')}]),
        ]
    )
    service = StudentService(connection, school_id=66)

    fee_summary = service.get_fee_summary(1001)
    payments = service.get_payment_history(1001)
    exams = service.get_exam_summaries(1001)

    assert fee_summary['current_balance'] == Decimal('3500.00')
    assert payments == [{'rcptno': 'RCP-001', 'payment_id': 10}]
    assert exams == [{'exam_id': 3, 'exam_name': 'Midterm', 'mean_mark': Decimal('72.5')}]

    fee_query, fee_params = connection.cursor_obj.executed[0]
    payments_query, payments_params = connection.cursor_obj.executed[1]
    exams_query, exams_params = connection.cursor_obj.executed[2]

    assert fee_params == (1001, 66, 1001, 66, 1001, 66)
    assert 'from fee_ledger where admno = %s and type = ' in fee_query.lower()
    assert 'from fee_payments where admno = %s and status = ' in fee_query.lower()
    assert 'from fee_ledger where admno = %s and school_id = %s order by id desc limit 1' in fee_query.lower()

    assert payments_params == (1001, 66)
    assert 'fp.ledger_id = fl.id and fp.school_id = fl.school_id' in payments_query.lower()
    assert 'fp.id = fr.payment_id and fp.school_id = fr.school_id' in payments_query.lower()
    assert 'fl.academic_year_id = ay.id and fl.school_id = ay.school_id' in payments_query.lower()
    assert 'where fp.admno = %s and fp.school_id = %s' in payments_query.lower()

    assert exams_params == ('1001', 66)
    assert 'm.exam_id = e.id and m.school_id = e.school_id' in exams_query.lower()
    assert 'e.academic_year_id = ay.id and e.school_id = ay.school_id' in exams_query.lower()
    assert 'where m.student_id = %s and m.school_id = %s' in exams_query.lower()


def test_exam_service_rejects_exam_creation_for_foreign_class():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 2026}),
            ('all', []),
        ]
    )
    service = ExamManagementService(connection, school_id=67)

    with pytest.raises(ExamManagementError, match='classes do not belong to the active school'):
        ExamManagementService.create_exam_series.__wrapped__(
            service,
            name='Midterm',
            academic_year_id=2026,
            term=1,
            created_by=4,
            class_ids=[99],
        )


def test_exam_service_rejects_mark_save_for_invalid_exam_student_subject_link():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 5, 'is_locked': 0, 'academic_year_id': 2026}),
            ('all', []),
            ('one', None),
        ]
    )
    service = ExamManagementService(connection, school_id=67)

    with pytest.raises(ExamManagementError, match='Student, subject, and exam assignment do not match'):
        ExamManagementService.save_mark.__wrapped__(
            service,
            exam_id=5,
            student_id='1001',
            subject_id=12,
            mark=70,
            is_absent=False,
            remarks='',
        )

    assert connection.commit_calls == 0


def test_student_service_scopes_admission_form_profile_queries_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001', 'Fullname': 'Jane Doe', 'class_name': 'Grade 4 A', 'route_name': 'Route 1', 'route_amount': 2500}),
            ('one', {'pName': 'John Doe', 'phone1': '0700000000'}),
            ('all', [{'AdmNo': '1002', 'Fullname': 'John Junior', 'class_name': 'Grade 2 A'}]),
        ]
    )
    service = StudentService(connection, school_id=68)

    profile = service.get_admission_form_profile('1001')
    parent = service.get_parent_contact_for_student('1001', 55)
    siblings = service.get_sibling_profiles(55, '1001')

    assert profile['class_name'] == 'Grade 4 A'
    assert parent['pName'] == 'John Doe'
    assert siblings == [{'AdmNo': '1002', 'Fullname': 'John Junior', 'class_name': 'Grade 2 A'}]

    profile_query, profile_params = connection.cursor_obj.executed[0]
    parent_query, parent_params = connection.cursor_obj.executed[1]
    siblings_query, siblings_params = connection.cursor_obj.executed[2]

    assert profile_params == ('1001', 68)
    assert 's.admno = ca.student_id and ca.is_current = true and s.school_id = ca.school_id' in profile_query.lower()
    assert 'ca.class_id = c.classid and ca.school_id = c.school_id' in profile_query.lower()
    assert 's.route_id = tr.id and s.school_id = tr.school_id' in profile_query.lower()
    assert 'where s.admno = %s and s.school_id = %s' in profile_query.lower()

    assert parent_params == ('1001', 68)
    assert 'from parentinfo where admno = %s and school_id = %s' in parent_query.lower()

    assert siblings_params == (55, '1001', 68)
    assert 's.admno = ca.student_id and ca.is_current = true and s.school_id = ca.school_id' in siblings_query.lower()
    assert 'ca.class_id = c.classid and ca.school_id = c.school_id' in siblings_query.lower()
    assert 'where s.parentid = %s and s.admno != %s and s.school_id = %s' in siblings_query.lower()


def test_student_service_scopes_subject_clear_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 22}),
        ]
    )
    service = StudentService(connection, school_id=69)

    service.clear_student_subject_enrollments(22)

    assert connection.commit_calls == 1
    lookup_query, lookup_params = connection.cursor_obj.executed[0]
    query, params = connection.cursor_obj.executed[1]
    assert lookup_params == (22, 69)
    assert 'from class_allocation where id = %s and school_id = %s' in lookup_query.lower()
    assert 'update student_subjects set is_active = false' in query.lower()
    assert 'where class_allocation_id = %s and school_id = %s' in query.lower()
    assert params == (22, 69)


def test_student_service_rejects_subject_clear_for_foreign_allocation():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = StudentService(connection, school_id=69)

    with pytest.raises(ValueError, match='Class allocation not found for the active school'):
        service.clear_student_subject_enrollments(999)

    assert connection.commit_calls == 0
    query, params = connection.cursor_obj.executed[0]
    assert params == (999, 69)
    assert 'from class_allocation where id = %s and school_id = %s' in query.lower()


def test_student_service_scopes_reference_and_subject_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'stream_code': 'A', 'academic_year_id': 2026}),
            ('one', {'name': 'Route 1', 'amount': Decimal('2500.00')}),
            ('one', {'id': 3}),
            ('all', [{'admno': '1001', 'full_name': 'Jane Doe', 'class_id': 5, 'display_name': 'Grade 4 A'}]),
            ('all', [{'AdmNo': '1001', 'FName': 'Jane', 'LName': 'Doe', 'class_name': 'Grade 4 A'}]),
            ('one', {'id': 22, 'class_id': 5, 'display_name': 'Grade 4 A', 'classID': 5, 'year': 2026}),
            ('all', [{'id': 11, 'code': 'MAT', 'name': 'Mathematics', 'is_compulsory': 1}]),
            ('all', [{'subject_id': 11}, {'subject_id': 12}]),
        ]
    )
    service = StudentService(connection, school_id=69)

    class_info = service.get_class_details(5)
    route = service.get_transport_route_by_id(7)
    current_term_id = service.get_current_term_id()
    subject_students = service.get_students_for_subject_enrollment()
    searched_students = service.search_students_for_subjects('Jane')
    allocation = service.get_current_allocation(1001)
    subjects = service.get_available_subjects_for_class(5)
    enrolled_ids = service.get_enrolled_subject_ids(22)

    assert class_info == {'stream_code': 'A', 'academic_year_id': 2026}
    assert route == {'name': 'Route 1', 'amount': Decimal('2500.00')}
    assert current_term_id == 3
    assert subject_students == [{'admno': '1001', 'full_name': 'Jane Doe', 'class_id': 5, 'display_name': 'Grade 4 A'}]
    assert searched_students == [{'AdmNo': '1001', 'FName': 'Jane', 'LName': 'Doe', 'class_name': 'Grade 4 A'}]
    assert allocation['id'] == 22
    assert subjects == [{'id': 11, 'code': 'MAT', 'name': 'Mathematics', 'is_compulsory': 1}]
    assert enrolled_ids == [11, 12]

    class_query, class_params = connection.cursor_obj.executed[0]
    route_query, route_params = connection.cursor_obj.executed[1]
    term_query, term_params = connection.cursor_obj.executed[2]
    subject_students_query, subject_students_params = connection.cursor_obj.executed[3]
    search_query, search_params = connection.cursor_obj.executed[4]
    allocation_query, allocation_params = connection.cursor_obj.executed[5]
    subjects_query, subjects_params = connection.cursor_obj.executed[6]
    enrolled_query, enrolled_params = connection.cursor_obj.executed[7]

    assert class_params == (5, 69)
    assert 'where classid = %s and school_id = %s' in class_query.lower()
    assert route_params == (7, 69)
    assert 'where id = %s and school_id = %s' in route_query.lower()
    assert term_params == (69,)
    assert 'between start_date and end_date and school_id = %s' in term_query.lower()
    assert subject_students_params == (69,)
    assert 'ca.is_current = true' in subject_students_query.lower()
    assert 's.school_id = %s' in subject_students_query.lower()
    assert search_params == ('%Jane%', '%Jane%', '%Jane%', 69)
    assert 'where (s.admno like %s or s.fname like %s or s.sname like %s)' in search_query.lower()
    assert 'and s.school_id = %s' in search_query.lower()
    assert 'left join class_allocation modern_ca on s.admno = modern_ca.student_id and modern_ca.is_current = true and s.school_id = modern_ca.school_id' in search_query.lower()
    assert 'left join classes c_current on modern_ca.class_id = c_current.classid and modern_ca.school_id = c_current.school_id' in search_query.lower()
    assert 'left join classallocation legacy_ca on s.admno = legacy_ca.admno and s.school_id = legacy_ca.school_id' in search_query.lower()
    assert allocation_params == (1001, 69)
    assert 'join classes c on ca.class_id = c.classid and ca.school_id = c.school_id' in allocation_query.lower()
    assert 'join academic_years ay on ca.academic_year_id = ay.id and ca.school_id = ay.school_id' in allocation_query.lower()
    assert 'where ca.student_id = %s and ca.is_current = true and ca.school_id = %s' in allocation_query.lower()
    assert subjects_params == (5, 69, 69)
    assert 'join subjects s on cs.subject_id = s.subjectno and cs.school_id = s.school_id' in subjects_query.lower()
    assert 'cs.school_id = %s and s.school_id = %s' in subjects_query.lower()
    assert enrolled_params == (22, 69)
    assert 'where class_allocation_id = %s and is_active = true and school_id = %s' in enrolled_query.lower()


def test_student_service_prefers_modern_class_allocation_in_class_info_and_sibling_reads():
    connection = RecordingConnection(
        responses=[
            ('all', [{'AdmNo': '1002', 'FName': 'John', 'MName': 'K', 'LName': 'Doe', 'class_name': 'Grade 4 A'}]),
            ('all', [{'AdmNo': '1002', 'FName': 'John', 'MName': 'K', 'LName': 'Doe', 'class_name': 'Grade 4 A'}]),
            ('one', {'pName': 'Jane Doe', 'email': 'parent@example.com', 'phone1': '0700000000', 'address': 'Town', 'hometown': 'Village', 'nationalID': '12345678'}),
            ('one', {'class_name': 'Grade 4 A', 'class_group': 'Grade 4-6', 'classID': 14, 'stream': 'A', 'thisYear': 2026}),
        ]
    )
    service = StudentService(connection, school_id=69)

    siblings = service.get_siblings('0700000000', '1001')
    siblings_by_phone, parent = service.get_parent_info_and_siblings_by_phone('0700000000')
    class_info = service.get_student_class_info('1001')

    assert siblings == [{'AdmNo': '1002', 'FName': 'John', 'MName': 'K', 'LName': 'Doe', 'class_name': 'Grade 4 A'}]
    assert siblings_by_phone == [{'AdmNo': '1002', 'FName': 'John', 'MName': 'K', 'LName': 'Doe', 'class_name': 'Grade 4 A'}]
    assert parent == {'pName': 'Jane Doe', 'email': 'parent@example.com', 'phone1': '0700000000', 'address': 'Town', 'hometown': 'Village', 'nationalID': '12345678'}
    assert class_info == {'class_name': 'Grade 4 A', 'class_group': 'Grade 4-6', 'classID': 14, 'stream': 'A', 'thisYear': 2026}

    siblings_query, siblings_params = connection.cursor_obj.executed[0]
    parent_siblings_query, parent_siblings_params = connection.cursor_obj.executed[1]
    parent_query, parent_params = connection.cursor_obj.executed[2]
    class_info_query, class_info_params = connection.cursor_obj.executed[3]

    assert siblings_params == ('0700000000', '1001', 69)
    assert 'left join class_allocation modern_ca on s.admno = modern_ca.student_id and modern_ca.is_current = true and s.school_id = modern_ca.school_id' in siblings_query.lower()
    assert 'left join classes c_current on modern_ca.class_id = c_current.classid and modern_ca.school_id = c_current.school_id' in siblings_query.lower()
    assert 'left join classallocation legacy_ca on s.admno = legacy_ca.admno and s.school_id = legacy_ca.school_id' in siblings_query.lower()

    assert parent_siblings_params == ('0700000000', 69)
    assert 'left join class_allocation modern_ca on s.admno = modern_ca.student_id and modern_ca.is_current = true and s.school_id = modern_ca.school_id' in parent_siblings_query.lower()
    assert 'left join classes c_current on modern_ca.class_id = c_current.classid and modern_ca.school_id = c_current.school_id' in parent_siblings_query.lower()
    assert parent_params == ('0700000000', 69)
    assert 'from parentinfo' in parent_query.lower()

    assert class_info_params == ('1001', 69)
    assert 'from studentinfo s' in class_info_query.lower()
    assert 'left join class_allocation modern_ca on s.admno = modern_ca.student_id and modern_ca.is_current = true and s.school_id = modern_ca.school_id' in class_info_query.lower()
    assert 'left join classes c_current on modern_ca.class_id = c_current.classid and modern_ca.school_id = c_current.school_id' in class_info_query.lower()
    assert 'left join classallocation legacy_ca on s.admno = legacy_ca.admno and s.school_id = legacy_ca.school_id' in class_info_query.lower()


def test_student_service_prefers_modern_class_allocation_in_unfiltered_student_list():
    connection = RecordingConnection(
        responses=[
            ('all', [{'AdmNo': '1001', 'FName': 'Jane', 'MName': 'W', 'LName': 'Doe', 'Gender': 'F', 'Status': 'NO', 'class_name': 'Grade 4 A', 'class_group': 'Grade 4-6', 'thisYear': 2026}]),
        ]
    )
    service = StudentService(connection, school_id=69)

    students = service.get_students_list(query=None, year_cur=None)

    assert students == [{'AdmNo': '1001', 'FName': 'Jane', 'MName': 'W', 'LName': 'Doe', 'Gender': 'F', 'Status': 'NO', 'class_name': 'Grade 4 A', 'class_group': 'Grade 4-6', 'thisYear': 2026}]

    query, params = connection.cursor_obj.executed[0]
    assert params == (69,)
    assert 'left join class_allocation modern_ca on s.admno = modern_ca.student_id and modern_ca.is_current = true and s.school_id = modern_ca.school_id' in query.lower()
    assert 'left join classes c_current on modern_ca.class_id = c_current.classid and modern_ca.school_id = c_current.school_id' in query.lower()
    assert 'left join classallocation legacy_ca on s.admno = legacy_ca.admno and s.school_id = legacy_ca.school_id' in query.lower()


def test_student_service_prefers_modern_class_allocation_for_academic_history_with_legacy_fallback():
    connection = RecordingConnection(
        responses=[
            ('all', [
                {'thisYear': 2026, 'AllcDate': '2026-01-10', 'class_name': 'Grade 4 A', 'class_group': 'Grade 4-6'},
                {'thisYear': 2025, 'AllcDate': '2025-01-08', 'class_name': 'Grade 3 A', 'class_group': 'Grade 1-3'},
            ]),
        ]
    )
    service = StudentService(connection, school_id=69)

    history = service.get_student_academic_history('1001')

    assert history == [
        {'thisYear': 2026, 'AllcDate': '2026-01-10', 'class_name': 'Grade 4 A', 'class_group': 'Grade 4-6'},
        {'thisYear': 2025, 'AllcDate': '2025-01-08', 'class_name': 'Grade 3 A', 'class_group': 'Grade 1-3'},
    ]

    query, params = connection.cursor_obj.executed[0]

    assert params == ('1001', 69, '1001', 69)
    assert 'from class_allocation ca' in query.lower()
    assert 'join academic_years ay on ca.academic_year_id = ay.id and ca.school_id = ay.school_id' in query.lower()
    assert 'join classes c on ca.class_id = c.classid and ca.school_id = c.school_id' in query.lower()
    assert 'from classallocation a' in query.lower()
    assert 'not exists' in query.lower()
    assert 'where ca2.student_id = a.admno' in query.lower()
    assert 'and ay2.year = a.thisyear' in query.lower()


def test_procurement_service_rejects_vendor_statement_for_foreign_supplier():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'supplierID'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    with pytest.raises(ProcurementError, match='Supplier not found for the active school'):
        service.get_vendor_statement(99, '2026-04-01', '2026-04-30')


def test_procurement_service_rejects_asset_registration_with_foreign_purchase_order():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    with pytest.raises(ProcurementError, match='Purchase order not found'):
        ProcurementService.register_asset.__wrapped__(
            service,
            {
                'asset_name': 'Generator',
                'tag_number': 'AST-1',
                'category': 'Equipment',
                'purchase_date': '2026-04-01',
                'purchase_value': Decimal('150000.00'),
                'location': 'Main Campus',
                'condition_status': 'NEW',
                'po_id': 88,
            },
            user_id=8,
        )

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    assert not any('insert into assets_registry' in query.lower() for query, _ in connection.cursor_obj.executed)


def test_procurement_service_rejects_budget_write_with_foreign_department():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'deptID'}, {'Field': 'school_id'}]),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    with pytest.raises(ProcurementError, match='Department not found for the active school'):
        service.set_budget(77, 2026, 'General', Decimal('50000.00'))

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1


def test_procurement_service_rejects_budget_write_with_foreign_academic_year():
    connection = RecordingConnection(
        responses=[
            ('all', [{'Field': 'id'}, {'Field': 'school_id'}]),
            ('all', [{'Field': 'deptID'}, {'Field': 'school_id'}]),
            ('one', {'deptID': 7}),
            ('one', None),
        ]
    )
    service = ProcurementService(connection, school_id=52)

    with pytest.raises(ProcurementError, match='Academic year not found for the active school'):
        service.set_budget(7, 2026, 'General', Decimal('50000.00'))

    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1


def test_class_management_service_scopes_dashboard_and_summary_aggregates_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'count': 2}),
            ('one', {'count': 6}),
            ('one', {'count': 240}),
            ('one', {'count': 14}),
            ('one', {'year': 2026}),
            ('all', [{'display_name': 'Grade 4 A', 'year': 2026, 'students': 40}]),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    stats = service.get_dashboard_stats()
    summary = service.get_class_summary_report()

    assert stats['academic_years_count'] == 2
    assert stats['total_classes'] == 6
    assert stats['total_students'] == 240
    assert stats['current_year'] == 2026
    assert summary == [{'display_name': 'Grade 4 A', 'year': 2026, 'students': 40}]

    for query, params in connection.cursor_obj.executed[:5]:
        assert params == (71,)
        assert 'school_id = %s' in query.lower()

    summary_query, summary_params = connection.cursor_obj.executed[5]
    assert summary_params == (71,)
    assert 'c.classid = ca.class_id and ca.is_current = true and ca.school_id = c.school_id' in summary_query.lower()
    assert 'c.academic_year_id = ay.id and ay.school_id = c.school_id' in summary_query.lower()
    assert 'where c.school_id = %s' in summary_query.lower()


def test_class_management_service_rejects_subject_allocation_for_foreign_subject():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 12, 'academic_year_id': 2026}),
            ('all', []),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match='subjects do not belong to the active school'):
        service.allocate_subjects_to_class(12, [99])

    assert connection.commit_calls == 0


def test_class_management_service_rejects_teacher_assignment_for_foreign_teacher():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 12, 'academic_year_id': 2026}),
            ('one', None),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match='Teacher not found for the active school'):
        service.set_class_teacher(12, 44, 2026)


def test_class_management_service_rejects_student_subject_enrollment_for_foreign_allocation():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match='Class allocation not found for the active school'):
        service.enroll_student_in_subjects(333, [5])


def test_class_management_service_rejects_student_subject_enrollment_for_non_class_subject():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 22, 'class_id': 7}),
            ('all', [{'id': 5}]),
            ('all', []),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match="One or more subjects are not allocated to the student's class"):
        service.enroll_student_in_subjects(22, [5])

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    class_subject_query, class_subject_params = connection.cursor_obj.executed[2]
    assert class_subject_params == (7, 5, 71)
    assert 'from class_subjects where class_id = %s and subject_id in (%s) and is_active = true and school_id = %s' in class_subject_query.lower()


def test_class_management_service_rejects_subject_replacement_for_non_class_subject_before_clear():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 22, 'class_id': 7}),
            ('all', [{'id': 5}]),
            ('all', []),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match="One or more subjects are not allocated to the student's class"):
        service.replace_student_subject_enrollments(22, [5])

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    class_subject_query, class_subject_params = connection.cursor_obj.executed[2]
    assert class_subject_params == (7, 5, 71)
    assert 'from class_subjects where class_id = %s and subject_id in (%s) and is_active = true and school_id = %s' in class_subject_query.lower()


def test_class_management_service_rejects_batch_subject_enrollment_for_non_class_subject():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 7, 'academic_year_id': 2026}),
            ('all', [{'id': 22}, {'id': 23}]),
            ('all', [{'id': 5}]),
            ('all', []),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match="One or more subjects are not allocated to the student's class"):
        service.enroll_all_students_in_class_subjects(7, [5])

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    class_subject_query, class_subject_params = connection.cursor_obj.executed[3]
    assert class_subject_params == (7, 5, 71)
    assert 'from class_subjects where class_id = %s and subject_id in (%s) and is_active = true and school_id = %s' in class_subject_query.lower()


def test_class_management_service_rejects_class_create_for_foreign_year_and_stream():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match='Academic year not found for the active school'):
        service.create_class(2027, 'Grade 4-6', 'A', 4, 'Grade 4')


def test_class_management_service_rejects_update_for_foreign_class_and_stream():
    connection = RecordingConnection(
        responses=[
            ('one', None),
            ('one', {'classID': 12, 'academic_year_id': 2026}),
            ('one', None),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match='Class not found for the active school'):
        service.update_class(999, 'Grade 4', 'Grade 4-6', 'A')

    with pytest.raises(Exception, match='Stream not found for the active school'):
        service.update_class(12, 'Grade 4', 'Grade 4-6', 'Z')

    assert connection.commit_calls == 0
    foreign_query, foreign_params = connection.cursor_obj.executed[0]
    stream_lookup_query, stream_lookup_params = connection.cursor_obj.executed[2]
    assert foreign_params == (999, 71)
    assert 'from classes where classid = %s and school_id = %s' in foreign_query.lower()
    assert stream_lookup_params == ('Z', 71)
    assert 'from stream_settings where code = %s and school_id = %s and is_active = true' in stream_lookup_query.lower()


def test_class_management_service_scopes_create_class_readback_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 2026}),
            ('one', {'id': 1}),
            ('one', {'classID': 44, 'display_name': 'Grade 4 - Stream A', 'school_id': 71}),
        ]
    )
    connection.cursor_obj.lastrowid = 44
    service = ClassManagementService(connection, school_id=71)

    created = ClassManagementService.create_class.__wrapped__(service, 2026, 'Grade 4-6', 'A', 4, 'Grade 4')

    assert created['classID'] == 44
    assert connection.begin_calls == 1
    assert connection.commit_calls == 1

    create_query, create_params = connection.cursor_obj.executed[2]
    readback_query, readback_params = connection.cursor_obj.executed[3]

    assert 'insert into classes' in create_query.lower()
    assert create_params[-1] == 71
    assert 'select * from classes where classid = %s and school_id = %s' in readback_query.lower()
    assert readback_params == (44, 71)


def test_class_management_service_rejects_foreign_stream_toggle_and_delete():
    connection = RecordingConnection(
        responses=[
            ('one', None),
            ('one', None),
        ]
    )
    service = ClassManagementService(connection, school_id=71)

    with pytest.raises(Exception, match='Stream not found for the active school'):
        service.toggle_stream(99)

    with pytest.raises(Exception, match='Stream not found for the active school'):
        service.delete_stream(99)


def test_student_service_admit_student_writes_parent_and_class_allocation_for_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'stream_code': 'A', 'academic_year_id': 2026}),
            ('one', {'id': 2026}),
            ('one', {'name': 'Route 1', 'amount': Decimal('2500.00')}),
            ('one', {'id': 3}),
            ('one', None),
            ('one', {'next_id': 42}),
            ('one', None),
            ('one', None),
        ]
    )
    service = StudentService(connection, school_id=74)

    StudentService.admit_student.__wrapped__(
        service,
        {
            'admno': '1001',
            'fname': 'Jane',
            'mname': 'W',
            'lname': 'Doe',
            'gender': 'F',
            'dob': '2014-01-01',
            'birth_cert': 'BC123',
            'religion': 'Christian',
            'boarding': 'NO',
            'category': 'Day',
            'route_id': 9,
            'alt_contact': '0712345678',
            'stream': 'A',
            'student_group_id': 3,
        },
        {
            'pName': 'Janet Doe',
            'phone1': '0700000000',
            'email': 'parent@example.com',
            'nationalID': '12345678',
            'address': 'Town',
            'hometown': 'Village',
        },
        15,
        2026,
    )

    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0

    class_query, class_params = connection.cursor_obj.executed[0]
    year_query, year_params = connection.cursor_obj.executed[1]
    route_query, route_params = connection.cursor_obj.executed[2]
    student_group_query, student_group_params = connection.cursor_obj.executed[3]
    parent_phone_query, parent_phone_params = connection.cursor_obj.executed[4]
    student_insert_query, student_insert_params = connection.cursor_obj.executed[6]
    parent_lookup_query, parent_lookup_params = connection.cursor_obj.executed[7]
    parent_insert_query, parent_insert_params = connection.cursor_obj.executed[8]
    legacy_lookup_query, legacy_lookup_params = connection.cursor_obj.executed[9]
    legacy_insert_query, legacy_insert_params = connection.cursor_obj.executed[10]
    allocation_insert_query, allocation_insert_params = connection.cursor_obj.executed[11]

    assert class_params == (15, 74)
    assert 'where classid = %s and school_id = %s' in class_query.lower()
    assert year_params == (2026, 74)
    assert 'from academic_years where id = %s and school_id = %s' in year_query.lower()
    assert route_params == (9, 74)
    assert 'where id = %s and school_id = %s' in route_query.lower()
    assert student_group_params == (3, 74)
    assert 'from student_groups where id = %s and school_id = %s' in student_group_query.lower()

    assert parent_phone_params == ('0700000000', 74)
    assert 'where phone1 = %s and school_id = %s' in parent_phone_query.lower()

    assert 'insert into studentinfo' in student_insert_query.lower()
    assert student_insert_params[-1] == 74
    assert student_insert_params[0] == '1001'
    assert student_insert_params[1] == 42

    assert parent_lookup_params == ('1001', 74)
    assert 'where admno = %s and school_id = %s' in parent_lookup_query.lower()

    assert 'insert into parentinfo' in parent_insert_query.lower()
    assert parent_insert_params[0] == 42
    assert parent_insert_params[1] == '1001'
    assert parent_insert_params[-1] == 74

    assert legacy_lookup_params == ('1001', 2026, 74)
    assert 'from classallocation where admno = %s and thisyear = %s and school_id = %s' in legacy_lookup_query.lower()
    assert 'insert into classallocation' in legacy_insert_query.lower()
    assert legacy_insert_params == ('1001', 15, 2026, 74)

    assert 'insert into class_allocation' in allocation_insert_query.lower()
    assert allocation_insert_params == ('1001', 15, 2026, 74)


def test_student_service_update_student_updates_parent_and_both_allocation_tables_for_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001'}),
            ('one', {'stream_code': 'B', 'academic_year_id': 2026}),
            ('one', {'id': 2026}),
            ('one', {'parentid': 42}),
            ('one', {'allocationID': 88}),
            ('one', {'id': 99}),
        ]
    )
    service = StudentService(connection, school_id=75)

    StudentService.update_student.__wrapped__(
        service,
        '1001',
        {
            'fname': 'Jane',
            'mname': 'W',
            'lname': 'Doe',
            'gender': 'F',
            'dob': '2014-01-01',
            'birth_cert': 'BC123',
            'religion': 'Christian',
            'category': 'Day',
            'alt_contact': '0712345678',
            'email': 'student@example.com',
            'notes': 'Updated',
            'stream': 'B',
            'boarding': 'NO',
        },
        {
            'pName': 'Janet Doe',
            'phone1': '0700000000',
            'email': 'parent@example.com',
            'nationalID': '12345678',
            'address': 'Town',
            'hometown': 'Village',
        },
        17,
        2026,
    )

    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0

    student_lookup_query, student_lookup_params = connection.cursor_obj.executed[0]
    class_lookup_query, class_lookup_params = connection.cursor_obj.executed[1]
    year_lookup_query, year_lookup_params = connection.cursor_obj.executed[2]
    student_update_query, student_update_params = connection.cursor_obj.executed[3]
    parent_lookup_query, parent_lookup_params = connection.cursor_obj.executed[4]
    parent_update_query, parent_update_params = connection.cursor_obj.executed[5]
    legacy_lookup_query, legacy_lookup_params = connection.cursor_obj.executed[6]
    legacy_update_query, legacy_update_params = connection.cursor_obj.executed[7]
    modern_lookup_query, modern_lookup_params = connection.cursor_obj.executed[8]
    modern_update_query, modern_update_params = connection.cursor_obj.executed[9]

    assert student_lookup_params == ('1001', 75)
    assert 'from studentinfo where admno = %s and school_id = %s' in student_lookup_query.lower()
    assert class_lookup_params == (17, 75)
    assert 'where classid = %s and school_id = %s' in class_lookup_query.lower()
    assert year_lookup_params == (2026, 75)
    assert 'from academic_years where id = %s and school_id = %s' in year_lookup_query.lower()

    assert 'update studentinfo set' in student_update_query.lower()
    assert student_update_params[-2:] == ('1001', 75)

    assert parent_lookup_params == ('1001', 75)
    assert 'where admno = %s and school_id = %s' in parent_lookup_query.lower()

    assert 'update parentinfo' in parent_update_query.lower()
    assert parent_update_params[-2:] == ('1001', 75)

    assert legacy_lookup_params == ('1001', datetime.now().year, 75)
    assert 'from classallocation where admno = %s and thisyear = %s and school_id = %s' in legacy_lookup_query.lower()
    assert legacy_update_params == (17, 88, 75)
    assert 'update classallocation set classid = %s where allocationid = %s and school_id = %s' in legacy_update_query.lower()

    assert modern_lookup_params == ('1001', 2026, 75)
    assert 'from class_allocation' in modern_lookup_query.lower()
    assert modern_update_params == (17, 99, 75)
    assert 'update class_allocation set class_id = %s where id = %s and school_id = %s' in modern_update_query.lower()


def test_student_service_rejects_admission_for_foreign_class_before_writes():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = StudentService(connection, school_id=74)

    with pytest.raises(ValueError, match='Class not found for the active school'):
        StudentService.admit_student.__wrapped__(
            service,
            {
                'admno': '1001',
                'fname': 'Jane',
                'mname': 'W',
                'lname': 'Doe',
                'gender': 'F',
                'dob': '2014-01-01',
                'birth_cert': 'BC123',
                'religion': 'Christian',
                'boarding': 'NO',
                'category': 'Day',
                'route_id': None,
                'alt_contact': '0712345678',
                'stream': 'A',
                'student_group_id': None,
            },
            {'phone1': ''},
            999,
            2026,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    query, params = connection.cursor_obj.executed[0]
    assert params == (999, 74)
    assert 'where classid = %s and school_id = %s' in query.lower()


def test_student_service_rejects_admission_for_foreign_route_before_writes():
    connection = RecordingConnection(
        responses=[
            ('one', {'stream_code': 'A', 'academic_year_id': 2026}),
            ('one', {'id': 2026}),
            ('one', None),
        ]
    )
    service = StudentService(connection, school_id=74)

    with pytest.raises(ValueError, match='Transport route not found for the active school'):
        StudentService.admit_student.__wrapped__(
            service,
            {
                'admno': '1001',
                'fname': 'Jane',
                'mname': 'W',
                'lname': 'Doe',
                'gender': 'F',
                'dob': '2014-01-01',
                'birth_cert': 'BC123',
                'religion': 'Christian',
                'boarding': 'NO',
                'category': 'Transport',
                'route_id': 999,
                'alt_contact': '0712345678',
                'stream': 'A',
                'student_group_id': None,
            },
            {'phone1': ''},
            15,
            2026,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    query, params = connection.cursor_obj.executed[2]
    assert params == (999, 74)
    assert 'from transport_routes where id = %s and school_id = %s' in query.lower()


def test_student_service_rejects_admission_for_foreign_student_group_before_writes():
    connection = RecordingConnection(
        responses=[
            ('one', {'stream_code': 'A', 'academic_year_id': 2026}),
            ('one', {'id': 2026}),
            ('one', None),
        ]
    )
    service = StudentService(connection, school_id=74)

    with pytest.raises(ValueError, match='Student group not found for the active school'):
        StudentService.admit_student.__wrapped__(
            service,
            {
                'admno': '1001',
                'fname': 'Jane',
                'mname': 'W',
                'lname': 'Doe',
                'gender': 'F',
                'dob': '2014-01-01',
                'birth_cert': 'BC123',
                'religion': 'Christian',
                'boarding': 'NO',
                'category': 'Day',
                'route_id': None,
                'alt_contact': '0712345678',
                'stream': 'A',
                'student_group_id': 999,
            },
            {'phone1': ''},
            15,
            2026,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    query, params = connection.cursor_obj.executed[2]
    assert params == (999, 74)
    assert 'from student_groups where id = %s and school_id = %s' in query.lower()


def test_student_service_rejects_admission_for_foreign_academic_year_before_writes():
    connection = RecordingConnection(
        responses=[
            ('one', {'stream_code': 'A', 'academic_year_id': 2026}),
            ('one', None),
        ]
    )
    service = StudentService(connection, school_id=74)

    with pytest.raises(ValueError, match='Academic year not found for the active school'):
        StudentService.admit_student.__wrapped__(
            service,
            {
                'admno': '1001',
                'fname': 'Jane',
                'mname': 'W',
                'lname': 'Doe',
                'gender': 'F',
                'dob': '2014-01-01',
                'birth_cert': 'BC123',
                'religion': 'Christian',
                'boarding': 'NO',
                'category': 'Day',
                'route_id': None,
                'alt_contact': '0712345678',
                'stream': 'A',
                'student_group_id': None,
            },
            {'phone1': ''},
            15,
            999,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    query, params = connection.cursor_obj.executed[1]
    assert params == (999, 74)
    assert 'from academic_years where id = %s and school_id = %s' in query.lower()


def test_student_service_rejects_update_for_mismatched_academic_year_before_writes():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001'}),
            ('one', {'stream_code': 'B', 'academic_year_id': 2026}),
            ('one', {'id': 2027}),
        ]
    )
    service = StudentService(connection, school_id=75)

    with pytest.raises(ValueError, match='Academic year does not match the selected class'):
        StudentService.update_student.__wrapped__(
            service,
            '1001',
            {
                'fname': 'Jane',
                'mname': 'W',
                'lname': 'Doe',
                'gender': 'F',
                'dob': '2014-01-01',
                'birth_cert': 'BC123',
                'religion': 'Christian',
                'category': 'Day',
                'alt_contact': '0712345678',
                'email': 'student@example.com',
                'notes': 'Updated',
                'stream': 'B',
                'boarding': 'NO',
            },
            {'phone1': ''},
            17,
            2027,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    query, params = connection.cursor_obj.executed[2]
    assert params == (2027, 75)
    assert 'from academic_years where id = %s and school_id = %s' in query.lower()


def test_student_service_rejects_update_for_foreign_student_before_writes():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = StudentService(connection, school_id=75)

    with pytest.raises(ValueError, match='Student not found for the active school'):
        StudentService.update_student.__wrapped__(
            service,
            '9999',
            {
                'fname': 'Jane',
                'mname': 'W',
                'lname': 'Doe',
                'gender': 'F',
                'dob': '2014-01-01',
                'birth_cert': 'BC123',
                'religion': 'Christian',
                'category': 'Day',
                'alt_contact': '0712345678',
                'email': 'student@example.com',
                'notes': 'Updated',
                'stream': 'B',
                'boarding': 'NO',
            },
            {'phone1': ''},
            17,
            2026,
        )

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    query, params = connection.cursor_obj.executed[0]
    assert params == ('9999', 75)
    assert 'from studentinfo where admno = %s and school_id = %s' in query.lower()


def test_student_service_bulk_import_students_scopes_successful_rows_and_counts_skips():
    connection = RecordingConnection(
        responses=[
            ('one', None),
            ('one', {'stream_code': 'A', 'academic_year_id': 2026}),
            ('one', None),
            ('one', {'next_id': 55}),
            ('one', None),
            ('one', None),
            ('one', {'AdmNo': '1002'}),
        ]
    )
    service = StudentService(connection, school_id=76)

    success_count, error_count = StudentService.bulk_import_students.__wrapped__(
        service,
        {
            'admno[]': ['1001', '1002'],
            'fname[]': ['Jane', 'John'],
            'mname[]': ['W', 'K'],
            'lname[]': ['Doe', 'Smith'],
            'gender[]': ['Female', 'Male'],
            'dob[]': ['2014-01-01', '2013-03-03'],
            'religion[]': ['Christian', 'Christian'],
            'category[]': ['Day', 'Boarding'],
            'class_id[]': [15, 16],
            'parent_name[]': ['Janet Doe', 'John Smith Sr'],
            'parent_phone[]': ['0700000000', '0711111111'],
            'parent_email[]': ['parent1@example.com', 'parent2@example.com'],
            'parent_id_no[]': ['12345678', '87654321'],
            'home_address[]': ['Town', 'City'],
            'residency[]': ['Village', 'Estate'],
        },
    )

    assert success_count == 1
    assert error_count == 1
    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0

    duplicate_check_query, duplicate_check_params = connection.cursor_obj.executed[0]
    class_lookup_query, class_lookup_params = connection.cursor_obj.executed[1]
    student_insert_query, student_insert_params = connection.cursor_obj.executed[4]
    parent_insert_query, parent_insert_params = connection.cursor_obj.executed[6]
    legacy_lookup_query, legacy_lookup_params = connection.cursor_obj.executed[7]
    legacy_insert_query, legacy_insert_params = connection.cursor_obj.executed[8]
    allocation_insert_query, allocation_insert_params = connection.cursor_obj.executed[9]
    second_duplicate_check_query, second_duplicate_check_params = connection.cursor_obj.executed[10]

    assert duplicate_check_params == ('1001', 76)
    assert 'from studentinfo where admno = %s and school_id = %s' in duplicate_check_query.lower()
    assert class_lookup_params == (15, 76)
    assert 'from classes where classid = %s and school_id = %s' in class_lookup_query.lower()

    assert 'insert into studentinfo' in student_insert_query.lower()
    assert student_insert_params[0] == '1001'
    assert student_insert_params[-1] == 76

    assert 'insert into parentinfo' in parent_insert_query.lower()
    assert parent_insert_params[0] == 55
    assert parent_insert_params[1] == '1001'
    assert parent_insert_params[-1] == 76

    assert legacy_lookup_params == ('1001', 2026, 76)
    assert 'from classallocation where admno = %s and thisyear = %s and school_id = %s' in legacy_lookup_query.lower()
    assert 'insert into classallocation' in legacy_insert_query.lower()
    assert legacy_insert_params == ('1001', 15, 2026, 76)

    assert 'insert into class_allocation' in allocation_insert_query.lower()
    assert allocation_insert_params == ('1001', 15, 2026, 76)

    assert second_duplicate_check_params == ('1002', 76)
    assert 'from studentinfo where admno = %s and school_id = %s' in second_duplicate_check_query.lower()


def test_student_service_update_student_uses_academic_year_for_legacy_sync():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': '1001'}),
            ('one', {'stream_code': 'B', 'academic_year_id': 2027}),
            ('one', {'id': 2027}),
            ('one', {'parentid': 42}),
            ('one', None),
            ('one', None),
        ]
    )
    service = StudentService(connection, school_id=75)

    StudentService.update_student.__wrapped__(
        service,
        '1001',
        {
            'fname': 'Jane',
            'mname': 'W',
            'lname': 'Doe',
            'gender': 'F',
            'dob': '2014-01-01',
            'birth_cert': 'BC123',
            'religion': 'Christian',
            'category': 'Day',
            'alt_contact': '0712345678',
            'email': 'student@example.com',
            'notes': 'Updated',
            'stream': 'B',
            'boarding': 'NO',
        },
        {
            'pName': 'Janet Doe',
            'phone1': '0700000000',
            'email': 'parent@example.com',
            'nationalID': '12345678',
            'address': 'Town',
            'hometown': 'Village',
        },
        17,
        2027,
    )

    legacy_lookup_query, legacy_lookup_params = connection.cursor_obj.executed[6]
    legacy_insert_query, legacy_insert_params = connection.cursor_obj.executed[7]

    assert legacy_lookup_params == ('1001', 2027, 75)
    assert 'from classallocation where admno = %s and thisyear = %s and school_id = %s' in legacy_lookup_query.lower()
    assert 'insert into classallocation' in legacy_insert_query.lower()
    assert legacy_insert_params == ('1001', 17, 2027, 75)


def test_inventory_service_rejects_delete_uniform_item_for_missing_or_foreign_item():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = InventoryService(connection, school_id=81)

    with pytest.raises(ValueError, match='Item name is required'):
        service.delete_uniform_item('   ')

    with pytest.raises(ValueError, match='Item not found for the active school'):
        service.delete_uniform_item('Blazer')

    assert connection.commit_calls == 0
    query, params = connection.cursor_obj.executed[0]
    assert params == ('Blazer', 81)
    assert 'from uniform_prices where item_name = %s and school_id = %s' in query.lower()


def test_class_management_service_promotes_students_with_school_scoped_updates():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 1, 'academic_year_id': 1, 'year': 2025}),
            ('one', {'classID': 2, 'academic_year_id': 2, 'year': 2026, 'ay_id': 2}),
            ('all', [{'id': 10, 'student_id': '1001'}, {'id': 11, 'student_id': '1002'}]),
        ]
    )
    service = ClassManagementService(connection, school_id=77)

    result = ClassManagementService.promote_students.__wrapped__(service, 1, 2, 9, 'EOY promotion')

    assert result['success'] is True
    assert result['students_promoted'] == 2
    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0

    old_class_query, old_class_params = connection.cursor_obj.executed[0]
    new_class_query, new_class_params = connection.cursor_obj.executed[1]
    students_query, students_params = connection.cursor_obj.executed[2]
    first_insert_query, first_insert_params = connection.cursor_obj.executed[3]
    second_insert_query, second_insert_params = connection.cursor_obj.executed[4]
    update_old_query, update_old_params = connection.cursor_obj.executed[5]
    promotion_log_query, promotion_log_params = connection.cursor_obj.executed[6]

    assert old_class_params == (1, 77)
    assert 'where c.classid = %s and c.school_id = %s' in old_class_query.lower()
    assert new_class_params == (2, 77)
    assert 'where c.classid = %s and c.school_id = %s' in new_class_query.lower()
    assert students_params == (1, 77)
    assert 'where class_id = %s and is_current = true and school_id = %s' in students_query.lower()

    assert 'insert into class_allocation' in first_insert_query.lower()
    assert first_insert_params == ('1001', 2, 2, 10, 77)
    assert 'insert into class_allocation' in second_insert_query.lower()
    assert second_insert_params == ('1002', 2, 2, 11, 77)

    assert update_old_params == (1, 77)
    assert 'update class_allocation set is_current = false' in update_old_query.lower()
    assert 'where class_id = %s and is_current = true and school_id = %s' in update_old_query.lower()

    assert 'insert into class_promotion_log' in promotion_log_query.lower()
    assert promotion_log_params[1:] == (1, 2, 2, 9, 'EOY promotion', 77)


def test_class_management_service_allocates_students_to_class_with_school_scoped_validation():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 12, 'academic_year_id': 2026}),
            ('one', {'id': 2026}),
            ('all', [{'AdmNo': '1001'}, {'AdmNo': '1002'}]),
            ('all', []),
        ]
    )
    service = ClassManagementService(connection, school_id=78)

    count = service.allocate_students_to_class(12, ['1001', '1002'])

    assert count == 2
    assert connection.begin_calls == 1
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0

    class_lookup_query, class_lookup_params = connection.cursor_obj.executed[0]
    year_lookup_query, year_lookup_params = connection.cursor_obj.executed[1]
    students_lookup_query, students_lookup_params = connection.cursor_obj.executed[2]
    duplicate_lookup_query, duplicate_lookup_params = connection.cursor_obj.executed[3]
    first_insert_query, first_insert_params = connection.cursor_obj.executed[4]
    second_insert_query, second_insert_params = connection.cursor_obj.executed[5]

    assert class_lookup_params == (12, 78)
    assert 'from classes where classid = %s and school_id = %s' in class_lookup_query.lower()
    assert year_lookup_params == (2026, 78)
    assert 'from academic_years where id = %s and school_id = %s' in year_lookup_query.lower()
    assert students_lookup_params == ('1001', '1002', 78)
    assert 'from studentinfo where admno in (%s, %s) and school_id = %s' in students_lookup_query.lower()
    assert duplicate_lookup_params == (2026, '1001', '1002', 78)
    assert 'from class_allocation where academic_year_id = %s and is_current = true and student_id in (%s, %s) and school_id = %s' in duplicate_lookup_query.lower()
    assert 'insert into class_allocation' in first_insert_query.lower()
    assert first_insert_params == ('1001', 12, 2026, 78)
    assert 'insert into class_allocation' in second_insert_query.lower()
    assert second_insert_params == ('1002', 12, 2026, 78)


def test_class_management_service_rejects_allocate_students_to_class_for_foreign_student():
    connection = RecordingConnection(
        responses=[
            ('one', {'classID': 12, 'academic_year_id': 2026}),
            ('one', {'id': 2026}),
            ('all', [{'AdmNo': '1001'}]),
        ]
    )
    service = ClassManagementService(connection, school_id=78)

    with pytest.raises(Exception, match='One or more students do not belong to the active school'):
        service.allocate_students_to_class(12, ['1001', '9999'])

    assert connection.begin_calls == 0
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 0
    student_lookup_query, student_lookup_params = connection.cursor_obj.executed[2]
    assert student_lookup_params == ('1001', '9999', 78)
    assert 'from studentinfo where admno in (%s, %s) and school_id = %s' in student_lookup_query.lower()


def test_class_management_service_remove_and_delete_class_stay_school_scoped():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 44, 'class_id': 12}),
            ('one', {'classID': 12, 'academic_year_id': 2026}),
            ('one', {'count': 0}),
        ]
    )
    service = ClassManagementService(connection, school_id=78)

    service.remove_student_from_class(44)
    service.delete_class(12)

    assert connection.commit_calls == 2

    remove_lookup_query, remove_lookup_params = connection.cursor_obj.executed[0]
    remove_query, remove_params = connection.cursor_obj.executed[1]
    delete_lookup_query, delete_lookup_params = connection.cursor_obj.executed[2]
    delete_count_query, delete_count_params = connection.cursor_obj.executed[3]
    delete_query, delete_params = connection.cursor_obj.executed[4]

    assert remove_lookup_params == (44, 78)
    assert 'from class_allocation where id = %s and school_id = %s' in remove_lookup_query.lower()

    assert remove_params == (44, 78)
    assert 'update class_allocation set is_current = false where id = %s and school_id = %s' in remove_query.lower()

    assert delete_lookup_params == (12, 78)
    assert 'from classes where classid = %s and school_id = %s' in delete_lookup_query.lower()

    assert delete_count_params == (12, 78)
    assert 'select count(*) as count from class_allocation where class_id = %s and school_id = %s' in delete_count_query.lower()
    assert delete_params == (12, 78)
    assert 'delete from classes where classid = %s and school_id = %s' in delete_query.lower()


def test_class_management_service_rejects_remove_student_for_foreign_allocation():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = ClassManagementService(connection, school_id=78)

    with pytest.raises(Exception, match='Class allocation not found for the active school'):
        service.remove_student_from_class(99)

    assert connection.commit_calls == 0
    query, params = connection.cursor_obj.executed[0]
    assert params == (99, 78)
    assert 'from class_allocation where id = %s and school_id = %s' in query.lower()


def test_class_management_service_rejects_delete_class_for_foreign_class():
    connection = RecordingConnection(
        responses=[
            ('one', None),
        ]
    )
    service = ClassManagementService(connection, school_id=78)

    with pytest.raises(Exception, match='Class not found for the active school'):
        service.delete_class(999)

    assert connection.commit_calls == 0
    query, params = connection.cursor_obj.executed[0]
    assert params == (999, 78)
    assert 'from classes where classid = %s and school_id = %s' in query.lower()


def test_transport_service_scopes_reporting_and_dashboard_reads_to_school():
    connection = RecordingConnection(
        responses=[
            ('all', [{'id': 3, 'reg_no': 'KAA 123A'}]),
            ('all', [{'voucher_no': 'FV-2026-0001', 'reg_no': 'KAA 123A'}]),
            ('one', {'voucher_no': 'FV-2026-0001', 'reg_no': 'KAA 123A', 'issued_by': 'transport-officer'}),
            ('one', {'count': 4}),
            ('one', {'total': Decimal('125000.00')}),
            ('one', {'total': Decimal('48000.00')}),
        ]
    )
    service = TransportService(connection, school_id=73)

    history = service.get_service_history(bus_id=3)
    vouchers = service.get_fuel_vouchers(start_date='2026-01-01', end_date='2026-01-31')
    voucher = service.get_fuel_voucher_for_print('FV-2026-0001')
    stats = service.get_fleet_dashboard_summary()

    assert history == [{'id': 3, 'reg_no': 'KAA 123A'}]
    assert vouchers == [{'voucher_no': 'FV-2026-0001', 'reg_no': 'KAA 123A'}]
    assert voucher['issued_by'] == 'transport-officer'
    assert stats['bus_count'] == 4
    assert stats['fuel_cost_total'] == Decimal('125000.00')
    assert stats['service_cost_total'] == Decimal('48000.00')

    history_query, history_params = connection.cursor_obj.executed[0]
    vouchers_query, vouchers_params = connection.cursor_obj.executed[1]
    voucher_query, voucher_params = connection.cursor_obj.executed[2]

    assert history_params == [73, 3]
    assert 's.bus_id = b.id and s.school_id = b.school_id' in history_query.lower()
    assert 'where s.school_id = %s' in history_query.lower()

    assert vouchers_params == [73, '2026-01-01', '2026-01-31']
    assert 'v.bus_id = b.id and v.school_id = b.school_id' in vouchers_query.lower()
    assert 'where v.school_id = %s' in vouchers_query.lower()

    assert voucher_params == ('FV-2026-0001', 73)
    assert 'v.bus_id = b.id and v.school_id = b.school_id' in voucher_query.lower()
    assert 'left join users u on v.issued_by = u.userno and v.school_id = u.school_id' in voucher_query.lower()
    assert 'where v.voucher_no = %s and v.school_id = %s' in voucher_query.lower()

    for query, params in connection.cursor_obj.executed[3:6]:
        assert params == (73,)
        assert 'school_id = %s' in query.lower()


def test_transport_service_write_paths_enforce_bus_ownership_and_scope_updates():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 4}),
            ('one', {'count': 0}),
            ('one', {'id': 4}),
        ]
    )
    service = TransportService(connection, school_id=73)

    voucher_no = TransportService.issue_fuel.__wrapped__(
        service,
        {
            'bus_id': 4,
            'date_issued': '2026-01-01',
            'fuel_type': 'Diesel',
            'quantity': 50,
            'unit_price': 180,
            'total_cost': 9000,
            'current_mileage': 120000,
            'issued_by': 5,
        },
    )
    TransportService.record_service.__wrapped__(
        service,
        {
            'bus_id': 4,
            'service_date': '2026-01-02',
            'service_type': 'Oil Change',
            'description': 'Routine',
            'cost': 7000,
            'garage_name': 'Garage X',
            'mileage_at_service': 120500,
        },
    )

    assert voucher_no.startswith('FV-')
    assert connection.commit_calls == 2

    assert connection.cursor_obj.executed[0][1] == (4, 73)
    assert 'select id from buses where id = %s and school_id = %s' in connection.cursor_obj.executed[0][0].lower()
    assert connection.cursor_obj.executed[2][1][-1] == 73
    assert 'insert into fuel_vouchers' in connection.cursor_obj.executed[2][0].lower()
    assert connection.cursor_obj.executed[3][1] == (120000, 4, 73)
    assert 'update buses set current_mileage = greatest' in connection.cursor_obj.executed[3][0].lower()

    assert connection.cursor_obj.executed[4][1] == (4, 73)
    assert 'select id from buses where id = %s and school_id = %s' in connection.cursor_obj.executed[4][0].lower()
    assert connection.cursor_obj.executed[5][1][-1] == 73
    assert 'insert into bus_services' in connection.cursor_obj.executed[5][0].lower()
    assert connection.cursor_obj.executed[6][1] == (120500, 4, 73)


def test_transport_service_rejects_writes_for_other_school_bus():
    connection = RecordingConnection(responses=[('one', None)])
    service = TransportService(connection, school_id=73)

    with pytest.raises(ValueError, match='Bus not found for the active school'):
        TransportService.record_service.__wrapped__(
            service,
            {
                'bus_id': 99,
                'service_date': '2026-01-02',
                'service_type': 'Oil Change',
                'description': 'Routine',
                'cost': 7000,
                'garage_name': 'Garage X',
                'mileage_at_service': 120500,
            },
        )

    query, params = connection.cursor_obj.executed[0]
    assert params == (99, 73)
    assert 'select id from buses where id = %s and school_id = %s' in query.lower()


def test_transport_service_rejects_update_and_delete_for_other_school_bus_and_route():
    update_connection = RecordingConnection(responses=[('one', None)])
    update_service = TransportService(update_connection, school_id=73)

    with pytest.raises(ValueError, match='Bus not found for the active school'):
        TransportService.update_bus.__wrapped__(
            update_service,
            41,
            {
                'reg_no': 'KAA 123A',
                'model': 'Isuzu',
                'capacity': 44,
                'current_mileage': 150000,
                'driver_name': 'Driver A',
            },
        )

    assert update_connection.commit_calls == 0
    update_query, update_params = update_connection.cursor_obj.executed[0]
    assert update_params == (41, 73)
    assert 'select id from buses where id = %s and school_id = %s' in update_query.lower()

    delete_connection = RecordingConnection(responses=[('one', None)])
    delete_service = TransportService(delete_connection, school_id=73)

    with pytest.raises(ValueError, match='Bus not found for the active school'):
        TransportService.delete_bus.__wrapped__(delete_service, 42)

    assert delete_connection.commit_calls == 0
    delete_query, delete_params = delete_connection.cursor_obj.executed[0]
    assert delete_params == (42, 73)
    assert 'select id from buses where id = %s and school_id = %s' in delete_query.lower()

    route_connection = RecordingConnection(responses=[('one', None)])
    route_service = TransportService(route_connection, school_id=73)

    with pytest.raises(ValueError, match='Route not found for the active school'):
        TransportService.delete_route.__wrapped__(route_service, 17)

    assert route_connection.commit_calls == 0
    route_query, route_params = route_connection.cursor_obj.executed[0]
    assert route_params == (17, 73)
    assert 'select id from transport_routes where id = %s and school_id = %s' in route_query.lower()


def test_farm_service_scopes_financial_summary_aggregates_to_school():
    connection = RecordingConnection(
        responses=[
            ('one', {'total_produced': Decimal('120.00'), 'total_spoilage': Decimal('5.00'), 'total_internal': Decimal('10.00')}),
            ('one', {'total_sales': Decimal('54000.00')}),
            ('one', {'total_expenses': Decimal('17000.00')}),
        ]
    )
    service = FarmManagementService(connection, school_id=88)

    summary = service.get_financial_summary(activity_id=4, start_date='2026-01-01', end_date='2026-01-31')

    assert summary['revenue'] == 54000.0
    assert summary['expenses'] == 17000.0
    assert summary['profit'] == 37000.0
    assert summary['production']['total_produced'] == 120.0

    production_query, production_params = connection.cursor_obj.executed[0]
    sales_query, sales_params = connection.cursor_obj.executed[1]
    expenses_query, expenses_params = connection.cursor_obj.executed[2]

    assert production_params == (88, 4, '2026-01-01', '2026-01-31')
    assert 'from income_production_log' in production_query.lower()
    assert 'where school_id = %s' in production_query.lower()
    assert 'and activity_id = %s' in production_query.lower()

    assert sales_params == (88, 4, '2026-01-01', '2026-01-31')
    assert 'from income_sales where school_id = %s' in sales_query.lower()
    assert 'and activity_id = %s' in sales_query.lower()

    assert expenses_params == (88, 4, '2026-01-01', '2026-01-31')
    assert 'from income_expenses where school_id = %s and status in (' in expenses_query.lower()
    assert 'and activity_id = %s' in expenses_query.lower()


def test_farm_service_write_paths_enforce_activity_ownership_and_scope_inserts():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 3}),
            ('one', {'id': 3}),
            ('one', {'id': 3}),
        ]
    )
    connection.cursor_obj.lastrowid = 17
    service = FarmManagementService(connection, school_id=88)

    production_id = service.record_production(3, Decimal('12.0'), Decimal('1.0'), Decimal('2.0'), 5, 'Morning')
    sale_id = service.record_sale(3, 'Market Buyer', Decimal('5.0'), Decimal('400.0'), 5)
    expense_id = service.request_expense(3, 'Feeds', Decimal('1500.0'), 'Layer mash', 5)

    assert production_id == 17
    assert sale_id == 17
    assert expense_id == 17
    assert connection.commit_calls == 3

    assert connection.cursor_obj.executed[0][1] == (3, 88)
    assert connection.cursor_obj.executed[1][1][0] == 88
    assert 'insert into income_production_log' in connection.cursor_obj.executed[1][0].lower()

    assert connection.cursor_obj.executed[2][1] == (3, 88)
    assert connection.cursor_obj.executed[3][1][0] == 88
    assert 'insert into income_sales' in connection.cursor_obj.executed[3][0].lower()

    assert connection.cursor_obj.executed[4][1] == (3, 88)
    assert connection.cursor_obj.executed[5][1][0] == 88
    assert 'insert into income_expenses' in connection.cursor_obj.executed[5][0].lower()


def test_farm_service_rejects_writes_for_other_school_activity():
    connection = RecordingConnection(responses=[('one', None)])
    service = FarmManagementService(connection, school_id=88)

    with pytest.raises(ValueError, match='Activity not found for the active school'):
        service.record_sale(9, 'Buyer', Decimal('1.0'), Decimal('100.0'), 5)

    query, params = connection.cursor_obj.executed[0]
    assert params == (9, 88)
    assert 'select id from income_activities where id = %s and school_id = %s' in query.lower()


def test_farm_service_approve_expense_fails_closed_for_foreign_expense():
    connection = RecordingConnection(responses=[('one', None)])
    service = FarmManagementService(connection, school_id=88)

    approved = service.approve_expense(14, 5)

    assert approved is False
    assert connection.commit_calls == 0
    assert connection.rollback_calls == 1
    query, params = connection.cursor_obj.executed[0]
    assert params == (14, 88)
    assert 'select id from income_expenses where id = %s and school_id = %s' in query.lower()


def test_farm_service_approve_expense_scopes_update_to_school():
    connection = RecordingConnection(responses=[('one', {'id': 14})])
    service = FarmManagementService(connection, school_id=88)

    approved = service.approve_expense(14, 5)

    assert approved is True
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0
    ownership_query, ownership_params = connection.cursor_obj.executed[0]
    update_query, update_params = connection.cursor_obj.executed[1]
    assert ownership_params == (14, 88)
    assert 'select id from income_expenses where id = %s and school_id = %s' in ownership_query.lower()
    assert update_params == (5, 14, 88)
    assert "update income_expenses set status = 'approved', approved_by = %s where id = %s and school_id = %s" in update_query.lower()