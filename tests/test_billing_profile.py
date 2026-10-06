import pytest
from blueprints.fees.services import FeesService, FeesError
from tests.test_exam_fee_isolation import RecordingConnection

def test_create_student_billing_profile_replaces_previous_overlapping_profile():
    connection = RecordingConnection(
        responses=[
            ('one', {'AdmNo': 1001}), # student check
            ('one', {'id': 2026}), # year check
            ('one', {'classID': 5}), # class check
            ('one', {'id': 2}), # billing group check
            ('one', None), # replace query
            ('one', None), # insert query
            ('one', None)  # optional service link query
        ]
    )
    service = FeesService(connection, school_id=10)

    profile_id = service.create_student_billing_profile(
        student_id=1001,
        academic_year_id=2026,
        effective_date="2026-05-01",
        class_id=5,
        billing_group_id=2,
        optional_service_ids=[8]
    )

    assert profile_id is not None
    executed = connection.cursor_obj.executed
    assert "update student_billing_profiles" in executed[4][0].lower()
    assert "insert into student_billing_profiles" in executed[5][0].lower()
    assert "insert into student_billing_profile_optional_services" in executed[6][0].lower()


def test_get_student_active_billing_profile_filters_by_effective_date():
    connection = RecordingConnection(
        responses=[
            ('one', {
                'id': 15,
                'student_id': 1001,
                'effective_date': '2026-01-01',
                'discount_profile_name': 'Staff Discount',
                'class_name': 'Grade 5',
                'billing_group_name': 'Boarders'
            }), # profile query
            ('all', [
                {'id': 10, 'service_name': 'Transport Route 1', 'default_amount': 12000, 'billing_frequency': 'TERMLY'}
            ]) # optional services query
        ]
    )
    service = FeesService(connection, school_id=10)

    profile = service.get_student_active_billing_profile(1001, value_date="2026-03-01")

    assert profile is not None
    assert profile['id'] == 15
    assert profile['discount_profile_name'] == 'Staff Discount'
    assert len(profile['optional_services']) == 1
    assert profile['optional_services'][0]['service_name'] == 'Transport Route 1'
