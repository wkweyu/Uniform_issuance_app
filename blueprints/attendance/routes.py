from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from blueprints.attendance.services import ALLOWED_ATTENDANCE_STATUSES, AttendanceService, default_attendance_date
from core.permissions import admin_required, login_required


attendance_bp = Blueprint('attendance', __name__)


def get_db_connection():
    from core.db import get_db_connection
    return get_db_connection()


def _required_int(value, field_name):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} is required and must be a valid integer.')


def _optional_int(value, field_name):
    if value in (None, ''):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid integer.')


def _parse_date(value, field_name):
    parsed = (value or '').strip()
    if not parsed:
        raise ValueError(f'{field_name} is required.')
    try:
        return datetime.strptime(parsed, '%Y-%m-%d').date().isoformat()
    except ValueError:
        raise ValueError(f'{field_name} must be a valid date in YYYY-MM-DD format.')


def _normalize_status(value):
    status = (value or '').strip().lower()
    if status not in ALLOWED_ATTENDANCE_STATUSES:
        raise ValueError('status must be one of: present, absent, late, excused.')
    return status


@attendance_bp.route('/attendance')
@login_required
def attendance_dashboard():
    connection = get_db_connection()
    service = AttendanceService(connection)
    try:
        classes = service.get_classes()
        recent_summary = service.get_recent_attendance_summary()
        return render_template(
            'attendance_dashboard.html',
            classes=classes,
            recent_summary=recent_summary,
        )
    finally:
        connection.close()


@attendance_bp.route('/attendance/take', methods=['GET', 'POST'])
@login_required
def take_attendance():
    connection = get_db_connection()
    service = AttendanceService(connection)
    selected_class_id = None
    attendance_date = default_attendance_date()
    students = []

    try:
        if request.method == 'POST':
            try:
                selected_class_id = _required_int(request.form.get('class_id'), 'class_id')
                attendance_date = _parse_date(request.form.get('attendance_date'), 'attendance_date')
                student_ids = request.form.getlist('student_id')
                statuses = request.form.getlist('status')
                remarks_list = request.form.getlist('remarks')

                if not student_ids:
                    raise ValueError('At least one student attendance row is required.')
                if len(student_ids) != len(statuses) or len(student_ids) != len(remarks_list):
                    raise ValueError('Attendance form submission is incomplete.')

                records = []
                for index, student_id in enumerate(student_ids, start=1):
                    records.append(
                        {
                            'student_id': _required_int(student_id, f'student_id[{index}]'),
                            'status': _normalize_status(statuses[index - 1]),
                            'remarks': (remarks_list[index - 1] or '').strip(),
                        }
                    )

                service.record_attendance(selected_class_id, attendance_date, records, session.get('userNo'))
                flash('Attendance saved successfully.', 'success')
                return redirect(url_for('attendance.take_attendance', class_id=selected_class_id, attendance_date=attendance_date))
            except ValueError as error:
                flash(str(error), 'error')

        if request.method == 'GET':
            try:
                selected_class_id = _optional_int(request.args.get('class_id'), 'class_id')
                if request.args.get('attendance_date'):
                    attendance_date = _parse_date(request.args.get('attendance_date'), 'attendance_date')
            except ValueError as error:
                flash(str(error), 'error')
                selected_class_id = None
                attendance_date = default_attendance_date()

        if selected_class_id is not None:
            students = service.get_class_attendance_register(selected_class_id, attendance_date)

        classes = service.get_classes()
        return render_template(
            'take_attendance.html',
            classes=classes,
            students=students,
            selected_class_id=selected_class_id,
            attendance_date=attendance_date,
            status_options=ALLOWED_ATTENDANCE_STATUSES,
        )
    finally:
        connection.close()


@attendance_bp.route('/attendance/report')
@admin_required
def attendance_report():
    connection = get_db_connection()
    service = AttendanceService(connection)
    start_date = request.args.get('start_date') or default_attendance_date()
    end_date = request.args.get('end_date') or default_attendance_date()
    selected_class_id = None
    rows = []

    try:
        try:
            start_date = _parse_date(start_date, 'start_date')
            end_date = _parse_date(end_date, 'end_date')
            selected_class_id = _optional_int(request.args.get('class_id'), 'class_id')
            rows = service.get_attendance_summary(start_date, end_date, class_id=selected_class_id)
        except ValueError as error:
            flash(str(error), 'error')

        classes = service.get_classes()
        return render_template(
            'attendance_report.html',
            classes=classes,
            rows=rows,
            selected_class_id=selected_class_id,
            start_date=start_date,
            end_date=end_date,
        )
    finally:
        connection.close()