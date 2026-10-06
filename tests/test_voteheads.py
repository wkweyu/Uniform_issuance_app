import pytest
from blueprints.fees.services import FeesService, FeesError
from tests.test_exam_fee_isolation import RecordingConnection

def test_update_votehead_updates_name_and_priority():
    connection = RecordingConnection(
        responses=[
            ('one', {'id': 5, 'name': 'Old Tuition'}), # votehead check
            ('all', [{'Field': 'id'}, {'Field': 'name'}, {'Field': 'code'}]), # SHOW COLUMNS
            ('one', None) # update query
        ]
    )
    service = FeesService(connection, school_id=10)

    res = service.update_votehead(
        votehead_id=5,
        name="Updated Tuition",
        priority=1,
        is_mandatory=True,
        description="Core tuition",
        code="TUI"
    )

    assert res is True
    executed = connection.cursor_obj.executed
    assert "update fee_voteheads" in executed[2][0].lower()


def test_update_votehead_rejects_nonexistent_votehead():
    connection = RecordingConnection(
        responses=[
            ('one', None) # votehead not found
        ]
    )
    service = FeesService(connection, school_id=10)

    with pytest.raises(FeesError, match="Votehead not found"):
        service.update_votehead(votehead_id=999, name="Invalid")
