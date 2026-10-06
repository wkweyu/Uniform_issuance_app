from decimal import Decimal
import pytest
from blueprints.fees.services import FeesService, FeesError
from tests.test_exam_fee_isolation import RecordingConnection

def test_create_optional_service_validates_and_inserts():
    connection = RecordingConnection(
        responses=[
            ('all', [{'id': 5}]), # votehead check
            ('one', None) # insert
        ]
    )
    service = FeesService(connection, school_id=10)

    service_id = service.create_optional_service(
        name="Transport Route 1",
        votehead_id=5,
        default_amount=Decimal("12000.00"),
        billing_frequency="TERMLY",
        code="TR1",
        description="Daily pickup"
    )

    assert service_id is not None
    executed = connection.cursor_obj.executed
    assert "insert into fee_optional_services" in executed[1][0].lower()
    assert executed[1][1] == (10, "Transport Route 1", "TR1", 5, Decimal("12000.00"), "TERMLY", "Daily pickup", None)


def test_subscribe_student_optional_service_checks_service_and_student():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}), # student check
            ('one', {'id': 2, 'name': 'Lunch', 'is_active': 1}), # service check
        ]
    )
    service = FeesService(connection, school_id=10)

    sub_id = service.subscribe_student_optional_service(
        student_id=1001,
        optional_service_id=2,
        effective_from="2026-01-15",
        effective_to="2026-11-30",
        custom_amount=Decimal("5000.00")
    )

    assert sub_id is not None
    executed = connection.cursor_obj.executed
    assert "insert into student_optional_service_subscriptions" in executed[2][0].lower()


def test_bill_optional_services_evaluates_effective_dates_and_cycle_key():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}), # student check
            ('one', {'id': 2026}), # year check
            ('one', {'id': 1}), # term check
            ('all', [
                {
                    'id': 10,
                    'optional_service_id': 2,
                    'service_name': 'Transport Route A',
                    'service_code': 'TR-A',
                    'billing_frequency': 'TERMLY',
                    'default_amount': Decimal("15000.00"),
                    'custom_amount': None,
                    'effective_from': '2026-01-01',
                    'effective_to': '2026-12-31',
                    'votehead_id': 5,
                    'status': 'ACTIVE'
                }
            ]), # subscriptions
            ('one', None), # charge duplicate check (not billed yet)
            ('one', {'balance_after': Decimal('0.00')}), # get student balance
            ('one', None), # ledger insert
            ('one', None)  # charge insert
        ]
    )
    service = FeesService(connection, school_id=10)

    charges = service.bill_optional_service_subscriptions(
        student_id=1001,
        academic_year_id=2026,
        term_id=1,
        value_date="2026-02-01"
    )

    assert len(charges) == 1
    assert charges[0]['service_name'] == 'Transport Route A'
    assert charges[0]['amount'] == Decimal("15000.00")
    assert charges[0]['billing_cycle_key'] == 'TERMLY-10-2026-1'


def test_bill_optional_services_skips_when_already_charged():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}), # student check
            ('one', {'id': 2026}), # year check
            ('one', {'id': 1}), # term check
            ('all', [
                {
                    'id': 10,
                    'optional_service_id': 2,
                    'service_name': 'Transport Route A',
                    'service_code': 'TR-A',
                    'billing_frequency': 'TERMLY',
                    'default_amount': Decimal("15000.00"),
                    'custom_amount': None,
                    'effective_from': '2026-01-01',
                    'effective_to': '2026-12-31',
                    'votehead_id': 5,
                    'status': 'ACTIVE'
                }
            ]), # subscriptions
            ('one', {'id': 99}), # charge duplicate check (already charged!)
        ]
    )
    service = FeesService(connection, school_id=10)

    charges = service.bill_optional_service_subscriptions(
        student_id=1001,
        academic_year_id=2026,
        term_id=1,
        value_date="2026-02-01"
    )

    assert len(charges) == 0 # Skipped because already charged
