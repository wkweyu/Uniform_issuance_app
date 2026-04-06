import blueprints.attendance.routes as attendance_routes

from models import School


class DummyConnection:
    def close(self):
        return None


class AttendanceServiceStub:
    last_instance = None
    record_error = None

    def __init__(self, _connection, school_id=None):
        self.school_id = school_id or 7
        self.calls = []
        AttendanceServiceStub.last_instance = self

    def get_classes(self):
        self.calls.append(('get_classes',))
        return [{'classID': 5, 'display_name': 'Grade 4 A'}]

    def get_recent_attendance_summary(self):
        self.calls.append(('get_recent_attendance_summary',))
        return [{'attendance_date': '2026-04-03', 'total_records': 32, 'absent_count': 2, 'late_count': 1}]

    def get_class_attendance_register(self, class_id, attendance_date):
        self.calls.append(('get_class_attendance_register', class_id, attendance_date))
        return [{'student_id': 1001, 'full_name': 'Jane Doe', 'status': 'present', 'remarks': ''}]

    def record_attendance(self, class_id, attendance_date, records, user_id):
        self.calls.append(('record_attendance', class_id, attendance_date, records, user_id))
        if self.record_error is not None:
            raise self.record_error

    def get_attendance_summary(self, start_date, end_date, class_id=None):
        self.calls.append(('get_attendance_summary', start_date, end_date, class_id))
        return [{'attendance_date': '2026-04-03', 'class_name': 'Grade 4 A', 'status': 'absent', 'total_students': 3}]


def _login_user(client):
    with client.session_transaction() as session:
        session['userNo'] = 10
        session['school_id'] = 7
        session['is_admin'] = True
        session['logged_in'] = True
        session['username'] = 'teacher'


def _ensure_school(db_session):
    school = db_session.get(School, 7)
    if school is None:
        school = School(id=7, name='Attendance Test School', code='ATS7')
        db_session.add(school)
        db_session.commit()
    return school


def test_attendance_dashboard_route_uses_service(client, db_session, monkeypatch):
    _ensure_school(db_session)
    _login_user(client)
    monkeypatch.setattr(attendance_routes, 'get_db_connection', lambda: DummyConnection())
    monkeypatch.setattr(attendance_routes, 'AttendanceService', AttendanceServiceStub)
    monkeypatch.setattr(attendance_routes, 'render_template', lambda template, **context: f"{template}:{len(context['classes'])}:{len(context['recent_summary'])}")

    response = client.get('/attendance')

    assert response.status_code == 200
    assert b'attendance_dashboard.html:1:1' in response.data
    assert AttendanceServiceStub.last_instance.calls == [('get_classes',), ('get_recent_attendance_summary',)]


def test_take_attendance_route_rejects_invalid_class_id_before_service_call(client, db_session, monkeypatch):
    _ensure_school(db_session)
    _login_user(client)
    monkeypatch.setattr(attendance_routes, 'get_db_connection', lambda: DummyConnection())
    monkeypatch.setattr(attendance_routes, 'AttendanceService', AttendanceServiceStub)
    monkeypatch.setattr(attendance_routes, 'render_template', lambda template, **context: f"{template}:{len(context['classes'])}:{len(context['students'])}")

    response = client.post(
        '/attendance/take',
        data={'class_id': 'bad', 'attendance_date': '2026-04-03', 'student_id': ['1001'], 'status': ['present'], 'remarks': ['']},
    )

    assert response.status_code == 200
    assert b'take_attendance.html:1:0' in response.data
    assert AttendanceServiceStub.last_instance.calls == [('get_classes',)]
    with client.session_transaction() as session:
        assert session.get('_flashes')[-1] == ('error', 'class_id is required and must be a valid integer.')


def test_take_attendance_route_submits_parsed_records_to_service(client, db_session, monkeypatch):
    _ensure_school(db_session)
    _login_user(client)
    monkeypatch.setattr(attendance_routes, 'get_db_connection', lambda: DummyConnection())
    monkeypatch.setattr(attendance_routes, 'AttendanceService', AttendanceServiceStub)

    response = client.post(
        '/attendance/take',
        data={
            'class_id': '5',
            'attendance_date': '2026-04-03',
            'student_id': ['1001', '1002'],
            'status': ['present', 'late'],
            'remarks': ['', 'Traffic'],
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert AttendanceServiceStub.last_instance.calls == [
        (
            'record_attendance',
            5,
            '2026-04-03',
            [
                {'student_id': 1001, 'status': 'present', 'remarks': ''},
                {'student_id': 1002, 'status': 'late', 'remarks': 'Traffic'},
            ],
            10,
        )
    ]


def test_attendance_report_route_rejects_invalid_class_filter(client, db_session, monkeypatch):
    _ensure_school(db_session)
    _login_user(client)
    monkeypatch.setattr(attendance_routes, 'get_db_connection', lambda: DummyConnection())
    monkeypatch.setattr(attendance_routes, 'AttendanceService', AttendanceServiceStub)
    monkeypatch.setattr(attendance_routes, 'render_template', lambda template, **context: f"{template}:{len(context['classes'])}:{len(context['rows'])}")

    response = client.get('/attendance/report?start_date=2026-04-01&end_date=2026-04-03&class_id=bad')

    assert response.status_code == 200
    assert b'attendance_report.html:1:0' in response.data
    assert AttendanceServiceStub.last_instance.calls == [('get_classes',)]
    with client.session_transaction() as session:
        assert session.get('_flashes')[-1] == ('error', 'class_id must be a valid integer.')