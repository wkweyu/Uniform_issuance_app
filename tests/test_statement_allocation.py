from decimal import Decimal
import pytest
from blueprints.fees.services import FeesService, FeesError
from tests.test_exam_fee_isolation import RecordingConnection

def test_record_payment_allocates_by_votehead_priority():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}), # student check
            ('one', {'id': 2026}), # year check
            ('one', {'id': 1}), # term check
            ('one', None), # duplicate check
            ('one', {'receiving_account_id': 1}), # account chain
            ('one', {'balance_after': Decimal("15000.00")}), # get_student_balance
            ('all', [
                {'votehead_id': 10, 'outstanding': Decimal("10000.00")}, # Tuition (Priority 1)
                {'votehead_id': 12, 'outstanding': Decimal("5000.00")}   # Activity (Priority 2)
            ]) # liabilities
        ]
    )
    service = FeesService(connection, school_id=10)
    service._table_columns_cache = {
        'fee_payments': {'school_id', 'receiving_account_id', 'cashier_session_id'},
        'fee_payment_allocations': {'school_id'},
        'fee_receipts': {'school_id'}
    }

    result = service.record_payment(
        admno=1001,
        amount=Decimal("12000.00"),
        mode="MPESA",
        reference="MP123456",
        bank="",
        date="2026-02-01",
        year_id=2026,
        term_id=1,
        user_id=1
    )

    assert result['receipt_no'] is not None
    assert len(result['allocations']) == 2
    # First 10,000 allocated to Tuition (votehead 10)
    assert result['allocations'][0]['votehead_id'] == 10
    assert result['allocations'][0]['amount'] == 10000.0
    # Remaining 2,000 allocated to Activity (votehead 12)
    assert result['allocations'][1]['votehead_id'] == 12
    assert result['allocations'][1]['amount'] == 2000.0
