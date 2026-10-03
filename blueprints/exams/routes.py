from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, g, jsonify, send_file, abort
from werkzeug.exceptions import HTTPException
import pymysql
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.exams.services import ExamManagementService, ExamManagementError
from blueprints.exams.access import (
    ExamAccessError,
    ExamAccessService,
    exam_permission_required,
)
from blueprints.exams.audit import record_exam_event
from blueprints.exams.workflow import ExamWorkflowService
from blueprints.classes.services import ClassManagementService
import csv
import hashlib
import io
from io import StringIO, BytesIO
from datetime import datetime
from core.tenancy import get_current_school_id
from blueprints.exams.workbook import (
    MAX_WORKBOOK_BYTES,
    ExamWorkbookError,
    build_component_marks_workbook,
    validate_component_marks_workbook,
)

exams_bp = Blueprint('exams', __name__)


def _required_int(value, field_name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} is required and must be a valid integer.")


def _spreadsheet_safe_cell(value):
    if value is None:
        return ''
    text = str(value)
    if text.lstrip(' \t\r\n')[:1] in {'=', '+', '-', '@'}:
        return "'" + text
    return text


def _get_editable_exam_classes(class_service, exam):
    classes = class_service.get_active_classes()
    active_class_ids = {cls['classID'] for cls in classes}
    classes.extend(
        cls for cls in exam['classes']
        if cls['classID'] not in active_class_ids
    )
    return sorted(classes, key=lambda cls: cls['display_name'])


def _get_exam_access_service(connection):
    if session.get('is_admin') or session.get('is_super_admin'):
        return None
    school_id = get_current_school_id()
    user_id = session.get('userNo')
    if school_id is None or user_id is None:
        abort(403)
    return ExamAccessService(connection, int(school_id), int(user_id))


def _filter_accessible_subjects(access_service, exam_id, class_id, subjects):
    if access_service is None:
        return subjects
    return [
        subject
        for subject in subjects
        if access_service.has_permission(
            'marks.view',
            exam_id=exam_id,
            class_id=class_id,
            subject_id=subject['id'],
        )
    ]


def _normalize_marks_csv_header(header):
    normalized = (header or '').replace('\ufeff', '').strip().casefold()
    normalized = '_'.join(normalized.replace('-', ' ').split())
    aliases = {
        'adm_no': 'student_id',
        'admno': 'student_id',
        'admission_no': 'student_id',
        'admission_number': 'student_id',
        'score': 'mark',
        'marks': 'mark',
        'absent': 'is_absent',
        'isabsent': 'is_absent',
        'subject_remarks': 'remarks',
        'class_teacher_remarks': 'ct_remarks',
        'c/t_remarks': 'ct_remarks',
        'principal_remarks': 'p_remarks',
        'head_teacher_remarks': 'p_remarks',
        'h/t_remarks': 'p_remarks',
    }
    return aliases.get(normalized, normalized)


def _parse_marks_csv(file_storage):
    raw_data = file_storage.stream.read()
    if not raw_data:
        raise ExamManagementError("The uploaded CSV file is empty.")
    if raw_data.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = raw_data.decode('utf-16')
    else:
        try:
            text = raw_data.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            try:
                text = raw_data.decode('cp1252')
            except UnicodeDecodeError:
                raise ExamManagementError(
                    "The CSV encoding is not supported. Save it as UTF-8 CSV and try again."
                ) from exc

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        first_line = next((line for line in text.splitlines() if line.strip()), '')
        delimiter = max(
            (',', ';', '\t'),
            key=lambda candidate: first_line.count(candidate),
        )
        reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter)
    else:
        reader = csv.reader(io.StringIO(text, newline=''), dialect)
    try:
        original_headers = next(reader)
    except StopIteration as exc:
        raise ExamManagementError("The uploaded CSV file has no header row.") from exc
    headers = [_normalize_marks_csv_header(header) for header in original_headers]
    if len(headers) != len(set(headers)):
        raise ExamManagementError(
            "The CSV contains duplicate column headers after normalization."
        )

    rows = []
    for values in reader:
        row_number = reader.line_num
        if not any(value.strip() for value in values):
            continue
        if len(values) > len(headers) and any(
            value.strip() for value in values[len(headers):]
        ):
            raise ExamManagementError(
                f"CSV row {row_number} has more values than the header row."
            )
        padded_values = values[:len(headers)] + [''] * max(
            0, len(headers) - len(values)
        )
        rows.append((
            row_number,
            dict(zip(headers, (value.strip() for value in padded_values))),
        ))
    return headers, rows


def _get_component_workbook_context(service, exam_id, class_id):
    contexts = {}
    subjects = service.get_exam_subjects_for_class(exam_id, class_id)
    for subject in subjects:
        components = service.get_exam_assessment_components(
            exam_id, class_id, subject['id']
        )
        if not components:
            continue
        contexts[subject['id']] = {
            'subject': subject,
            'components': components,
            'students': service.get_marks_for_class_subject(
                exam_id, class_id, subject['id']
            ),
        }
    return contexts


@exams_bp.route('/api/exams/<int:exam_id>/class/<int:class_id>/subjects-status')
@login_required
def get_exam_subjects_status(exam_id, class_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        access_service = _get_exam_access_service(connection)
        subjects = service.get_exam_subjects_status(exam_id, class_id)
        return jsonify({
            'success': True,
            'subjects': _filter_accessible_subjects(
                access_service, exam_id, class_id, subjects
            ),
        })
    except ExamManagementError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    finally: connection.close()


@exams_bp.route('/admin/exams/access/request', methods=['GET', 'POST'])
@login_required
def exam_access_request():
    connection = get_db_connection()
    service = ExamManagementService(connection)
    school_id = get_current_school_id()
    user_id = session.get('userNo')
    if school_id is None or user_id is None:
        connection.close()
        abort(403)
    access_service = ExamAccessService(connection, int(school_id), int(user_id))
    try:
        if request.method == 'POST':
            exam_id = _required_int(request.form.get('exam_id'), 'exam_id')
            class_id = _required_int(request.form.get('class_id'), 'class_id')
            subject_id = _required_int(request.form.get('subject_id'), 'subject_id')
            access_service.request_access(
                exam_id,
                class_id,
                subject_id,
                request.form.get('permission', ''),
                request.form.get('reason', ''),
            )
            flash("Examination access request submitted for review.", "success")
            return redirect(url_for(
                'exams.exam_access_request',
                exam_id=exam_id,
                class_id=class_id,
            ))

        exams = service.get_all_exams()
        selected_exam_id = request.args.get('exam_id', type=int)
        selected_class_id = request.args.get('class_id', type=int)
        selected_exam = (
            service.get_exam_series(selected_exam_id)
            if selected_exam_id is not None else None
        )
        classes = (
            service.get_exam_classes(selected_exam_id)
            if selected_exam else []
        )
        selected_class = next(
            (
                class_row for class_row in classes
                if class_row['classID'] == selected_class_id
            ),
            None,
        )
        subjects = (
            service.get_exam_subjects_for_class(
                selected_exam_id, selected_class_id
            )
            if selected_exam and selected_class else []
        )
        return render_template(
            'exam_access_request.html',
            exams=exams,
            selected_exam=selected_exam,
            selected_class=selected_class,
            classes=classes,
            subjects=subjects,
        )
    except (ExamAccessError, ExamManagementError, TypeError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for(
            'exams.exam_access_request',
            exam_id=request.values.get('exam_id'),
            class_id=request.values.get('class_id'),
        ))
    finally:
        connection.close()


@exams_bp.route('/admin/exams/access/requests', methods=['GET', 'POST'])
@login_required
@admin_required
def review_exam_access_requests():
    connection = get_db_connection()
    try:
        school_id = get_current_school_id()
        user_id = session.get('userNo')
        if school_id is None or user_id is None:
            abort(403)
        access_service = ExamAccessService(
            connection, int(school_id), int(user_id)
        )
        if request.method == 'POST':
            grant_id = _required_int(request.form.get('grant_id'), 'grant_id')
            access_service.review_access_request(
                grant_id,
                request.form.get('decision', ''),
                request.form.get('reason', ''),
            )
            flash("Examination access request updated.", "success")
            return redirect(url_for('exams.review_exam_access_requests'))

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT g.id, g.user_id, g.exam_id, g.class_id, g.subject_id,
                       g.permission_key, g.status, g.request_reason, g.created_at,
                       u.username, e.name AS exam_name, c.display_name AS class_name
                FROM exam_access_grants g
                JOIN users u ON u.userNo = g.user_id
                JOIN exam_series e ON e.id = g.exam_id AND e.school_id = g.school_id
                JOIN classes c ON c.classID = g.class_id AND c.school_id = g.school_id
                WHERE g.school_id = %s AND g.status IN ('requested', 'approved')
                ORDER BY g.created_at DESC, g.id DESC
                """,
                (school_id,),
            )
            grants = cursor.fetchall()
        return render_template('exam_access_requests.html', grants=grants)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for('exams.review_exam_access_requests'))
    finally:
        connection.close()


@exams_bp.route('/admin/grading-scales')
@login_required
@admin_required
def manage_grading_scales():
    connection = get_db_connection(); service = ExamManagementService(connection)
    scales = service.get_all_grading_scales()
    connection.close()
    return render_template('manage_grading_scales.html', scales=scales)

@exams_bp.route('/admin/grading-scales/add', methods=['POST'])
@login_required
@admin_required
def add_grading_scale():
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        service.create_grading_scale(request.form.get('name'), request.form.get('description'), request.form.get('is_default') == 'on')
        flash("Grading scale created.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('exams.manage_grading_scales'))

@exams_bp.route('/admin/grading-scales/<int:scale_id>')
@login_required
@admin_required
def edit_grading_scale(scale_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        scale = service.get_grading_scale(scale_id)
        if not scale:
            abort(404)
        grades = service.get_grading_details(scale_id)
        return render_template('edit_grading_scale.html', scale=scale, grades=grades)
    finally:
        connection.close()

@exams_bp.route('/admin/grading-scales/<int:scale_id>/save-grades', methods=['POST'])
@login_required
@admin_required
def save_grading_details(scale_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        grade_names = request.form.getlist('grade[]')
        minimums = request.form.getlist('min_mark[]')
        maximums = request.form.getlist('max_mark[]')
        points = request.form.getlist('points[]')
        remarks = request.form.getlist('remarks[]')
        class_teacher_remarks = request.form.getlist('class_teacher_remarks[]')
        principal_remarks = request.form.getlist('principal_remarks[]')
        lengths = {
            len(grade_names), len(minimums), len(maximums), len(points),
            len(remarks), len(class_teacher_remarks), len(principal_remarks),
        }
        if len(lengths) != 1 or not grade_names:
            raise ExamManagementError("Provide at least one complete grade row.")
        grades = []
        for index, name in enumerate(grade_names):
            grades.append({
                'grade': name.strip(),
                'min_mark': minimums[index],
                'max_mark': maximums[index],
                'points': points[index] or 0,
                'remarks': remarks[index],
                'class_teacher_remarks': class_teacher_remarks[index],
                'principal_remarks': principal_remarks[index],
            })
        service.save_grading_details(scale_id, grades)
        flash("Grading rules updated.", "success")
    except (ValueError, ExamManagementError) as e:
        flash(str(e), "error")
    except Exception as e:
        flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('exams.edit_grading_scale', scale_id=scale_id))

@exams_bp.route('/admin/grading-scales/assign')
@login_required
@admin_required
def assign_class_grading():
    connection = get_db_connection()
    try:
        service = ExamManagementService(connection)
        class_service = ClassManagementService(connection, school_id=service.school_id)
        classes = class_service.get_active_classes()
        scales = service.get_all_grading_scales()
        return render_template(
            'assign_class_grading.html',
            classes=classes,
            scales=scales,
        )
    finally:
        connection.close()

@exams_bp.route('/admin/grading-scales/save-assignments', methods=['POST'])
@login_required
@admin_required
def save_class_grading_assignments():
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        assignments = {}
        for key, value in request.form.items():
            if not key.startswith('scale_'):
                continue
            class_id = _required_int(key[len('scale_'):], 'class_id')
            scale_id = _required_int(value, 'scale_id') if value else None
            if class_id in assignments:
                raise ExamManagementError(
                    f"Class {class_id} was submitted more than once."
                )
            assignments[class_id] = scale_id
        service.assign_scales_to_classes(assignments)
        flash("Grading scales assigned to classes.", "success")
    except (ValueError, ExamManagementError) as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('exams.assign_class_grading'))

@exams_bp.route('/admin/exams')
@login_required
@exam_permission_required('exam.report')
def exams_dashboard():
    connection = get_db_connection(); service = ExamManagementService(connection)
    exams = service.get_all_exams()
    connection.close()
    return render_template('exams_dashboard.html', exams=exams)


@exams_bp.route('/admin/exams/access', methods=['GET', 'POST'])
@login_required
@admin_required
def exam_access_roles():
    connection = get_db_connection()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            if request.method == 'POST':
                user_id = _required_int(request.form.get('user_id'), 'user_id')
                allowed_roles = {
                    'examination_officer',
                    'academic_administrator',
                }
                selected_roles = set(request.form.getlist('role_key'))
                if selected_roles - allowed_roles:
                    raise ValueError("One or more examination roles are invalid.")

                cursor.execute(
                    "SELECT userNo, username FROM users "
                    "WHERE userNo = %s AND school_id = %s",
                    (user_id, session['school_id']),
                )
                user = cursor.fetchone()
                if not user:
                    abort(404)

                connection.begin()
                cursor.execute(
                    """
                    SELECT role_key FROM exam_user_roles
                    WHERE school_id = %s AND user_id = %s AND is_active = TRUE
                    """,
                    (session['school_id'], user_id),
                )
                previous_roles = sorted(row['role_key'] for row in cursor.fetchall())
                cursor.execute(
                    """
                    UPDATE exam_user_roles
                    SET is_active = FALSE, granted_by = %s
                    WHERE school_id = %s AND user_id = %s
                      AND role_key IN ('examination_officer', 'academic_administrator')
                    """,
                    (session['userNo'], session['school_id'], user_id),
                )
                for role_key in sorted(selected_roles):
                    cursor.execute(
                        """
                        INSERT INTO exam_user_roles
                            (school_id, user_id, role_key, is_active, granted_by)
                        VALUES (%s, %s, %s, TRUE, %s)
                        ON DUPLICATE KEY UPDATE
                            is_active = TRUE, granted_by = VALUES(granted_by),
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            session['school_id'],
                            user_id,
                            role_key,
                            session['userNo'],
                        ),
                    )
                record_exam_event(
                    cursor,
                    session['school_id'],
                    'exam_roles_updated',
                    'user',
                    user_id,
                    actor_user_id=session['userNo'],
                    old_values={'roles': previous_roles},
                    new_values={'roles': sorted(selected_roles)},
                )
                connection.commit()
                flash(f"Examination roles updated for {user['username']}.", "success")
                return redirect(url_for('exams.exam_access_roles'))

            cursor.execute(
                """
                SELECT userNo, username, StaffID, TA
                FROM users
                WHERE school_id = %s
                ORDER BY username, userNo
                """,
                (session['school_id'],),
            )
            users = cursor.fetchall()
            cursor.execute(
                """
                SELECT user_id, role_key
                FROM exam_user_roles
                WHERE school_id = %s AND is_active = TRUE
                """,
                (session['school_id'],),
            )
            roles_by_user = {}
            for role in cursor.fetchall():
                roles_by_user.setdefault(role['user_id'], set()).add(role['role_key'])
            for user in users:
                user['exam_roles'] = roles_by_user.get(user['userNo'], set())
            return render_template('exam_access_roles.html', users=users)
    except (ValueError, pymysql.Error) as exc:
        connection.rollback()
        current_app.logger.exception("Unable to update examination roles")
        flash(f"Unable to update examination roles: {exc}", "error")
        return redirect(url_for('exams.exam_access_roles'))
    finally:
        connection.close()

@exams_bp.route('/admin/exams/create', methods=['GET', 'POST'])
@login_required
@exam_permission_required('exam.create')
def create_exam():
    connection = get_db_connection()
    service = ExamManagementService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    try:
        if request.method == 'POST':
            class_ids = [
                _required_int(cid, 'class_ids')
                for cid in request.form.getlist('class_ids')
            ]
            if not class_ids:
                raise ExamManagementError("Select at least one participating class.")
            service.create_exam_series(
                name=request.form.get('name'),
                academic_year_id=_required_int(request.form.get('academic_year_id'), 'academic_year_id'),
                term=_required_int(request.form.get('term'), 'term'),
                created_by=session['userNo'],
                class_ids=class_ids
            )
            flash("Exam series created.", "success")
            return redirect(url_for('exams.exams_dashboard'))

        years = class_service.get_all_academic_years()
        classes = class_service.get_active_classes()
        return render_template(
            'create_exam.html',
            years=years,
            classes=classes,
            form_name=request.form.get('name', ''),
            form_term=request.form.get('term', '1'),
            selected_year_id=request.form.get('academic_year_id', ''),
            selected_class_ids=request.form.getlist('class_ids'),
        )
    except (ValueError, ExamManagementError) as e:
        flash(str(e), "error")
        return render_template(
            'create_exam.html',
            years=class_service.get_all_academic_years(),
            classes=class_service.get_active_classes(),
            form_name=request.form.get('name', ''),
            form_term=request.form.get('term', '1'),
            selected_year_id=request.form.get('academic_year_id', ''),
            selected_class_ids=request.form.getlist('class_ids'),
        )
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for('exams.exams_dashboard'))
    finally:
        connection.close()


@exams_bp.route('/admin/exams/<int:exam_id>/grading-scales', methods=['GET', 'POST'])
@login_required
@exam_permission_required('exam.grade.configure')
def configure_exam_grading_scales(exam_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        if request.method == 'POST':
            assignments = {}
            for class_row in exam['classes']:
                field_name = f"scale_{class_row['classID']}"
                if field_name not in request.form:
                    continue
                raw_scale_id = request.form.get(field_name, '').strip()
                assignments[class_row['classID']] = (
                    _required_int(raw_scale_id, field_name)
                    if raw_scale_id else None
                )
            service.assign_exam_grading_scales(
                exam_id,
                assignments,
                int(session['userNo']),
            )
            flash("Exam grading-scale overrides updated.", "success")
            return redirect(url_for(
                'exams.configure_exam_grading_scales',
                exam_id=exam_id,
            ))

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT c.classID, c.display_name, c.grading_scale_id,
                       override.grading_scale_id AS override_scale_id,
                       COALESCE(override.grading_scale_id, c.grading_scale_id,
                           default_scale.id) AS effective_scale_id
                FROM exam_classes ec
                JOIN classes c
                  ON c.classID = ec.class_id AND c.school_id = ec.school_id
                JOIN exam_series e
                  ON e.id = ec.exam_id AND e.school_id = ec.school_id
                LEFT JOIN exam_grading_overrides override
                  ON override.school_id = e.school_id
                 AND override.exam_id = e.id AND override.class_id = c.classID
                LEFT JOIN (
                    SELECT school_id, MIN(id) AS id
                    FROM grading_scales
                    WHERE is_default = TRUE
                    GROUP BY school_id
                ) default_scale ON default_scale.school_id = e.school_id
                WHERE e.id = %s AND e.school_id = %s
                ORDER BY c.display_name, c.classID
                """,
                (exam_id, service.school_id),
            )
            classes = cursor.fetchall()
        return render_template(
            'exam_grading_overrides.html',
            exam=exam,
            classes=classes,
            scales=service.get_all_grading_scales(),
        )
    except (ExamManagementError, TypeError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for('exams.exams_dashboard'))
    finally:
        connection.close()


@exams_bp.route('/admin/exams/<int:exam_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_exam(exam_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        if exam['is_locked']:
            flash("Unlock the exam series before editing it.", "error")
            return redirect(url_for('exams.exams_dashboard'))

        if request.method == 'POST':
            class_ids = [
                _required_int(cid, 'class_ids')
                for cid in request.form.getlist('class_ids')
            ]
            if not class_ids:
                raise ExamManagementError("Select at least one participating class.")
            service.update_exam_series(
                exam_id,
                request.form.get('name', ''),
                class_ids,
            )
            flash("Exam series updated.", "success")
            return redirect(url_for('exams.exams_dashboard'))

        return render_template(
            'edit_exam.html',
            exam=exam,
            classes=_get_editable_exam_classes(class_service, exam),
            selected_class_ids=[str(cls['classID']) for cls in exam['classes']],
        )
    except (ValueError, ExamManagementError) as e:
        flash(str(e), "error")
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        return render_template(
            'edit_exam.html',
            exam=exam,
            classes=_get_editable_exam_classes(class_service, exam),
            selected_class_ids=request.form.getlist('class_ids'),
            form_name=request.form.get('name', exam['name']),
        )
    except HTTPException:
        raise
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for('exams.exams_dashboard'))
    finally:
        connection.close()

@exams_bp.route('/admin/exams/<int:exam_id>/toggle-lock', methods=['POST'])
@login_required
def toggle_exam_status(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        lock = request.form.get('lock') == 'true'
        target_status = 'locked' if lock else 'published'
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        current_status = exam.get('workflow_status') or (
            'locked' if exam.get('is_locked') else 'marks_open'
        )
        permission = ExamWorkflowService.permission_for_transition(
            target_status, current_status
        )
        access_service = _get_exam_access_service(connection)
        if access_service is not None and not access_service.has_permission(
            permission, exam_id=exam_id
        ):
            abort(403)
        service.transition_exam_workflow(
            exam_id,
            target_status,
            int(session['userNo']),
            request.form.get('reason', ''),
        )
        flash("Exam workflow status updated.", "success")
    except (ExamManagementError, ValueError) as e:
        flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('exams.exams_dashboard'))


@exams_bp.route('/admin/exams/<int:exam_id>/workflow', methods=['POST'])
@login_required
def transition_exam_workflow(exam_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        target_status = request.form.get('target_status', '')
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        current_status = exam.get('workflow_status') or (
            'locked' if exam.get('is_locked') else 'marks_open'
        )
        permission = ExamWorkflowService.permission_for_transition(
            target_status, current_status
        )
        access_service = _get_exam_access_service(connection)
        if access_service is not None and not access_service.has_permission(
            permission, exam_id=exam_id
        ):
            abort(403)
        service.transition_exam_workflow(
            exam_id,
            target_status,
            int(session['userNo']),
            request.form.get('reason', ''),
        )
        flash("Exam workflow status updated.", "success")
    except (ExamManagementError, ValueError) as exc:
        flash(str(exc), "error")
    finally:
        connection.close()
    return redirect(url_for('exams.exams_dashboard'))

@exams_bp.route('/admin/exams/<int:exam_id>/marks/select', methods=['GET'])
@login_required
def marks_entry_select(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        access_service = _get_exam_access_service(connection)
        classes = []
        for class_row in service.get_exam_classes(exam_id):
            subjects = service.get_exam_subjects_for_class(
                exam_id, class_row['classID']
            )
            if _filter_accessible_subjects(
                access_service, exam_id, class_row['classID'], subjects
            ):
                classes.append(class_row)
        return render_template('marks_entry_select.html', exam=exam, classes=classes)
    finally:
        connection.close()


@exams_bp.route('/admin/exams/<int:exam_id>/completion', methods=['GET'])
@login_required
def exam_marks_completion(exam_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        access_service = _get_exam_access_service(connection)
        class_rows = []
        for class_row in service.get_exam_classes(exam_id):
            subjects = service.get_exam_subjects_status(
                exam_id, class_row['classID']
            )
            visible_subjects = _filter_accessible_subjects(
                access_service,
                exam_id,
                class_row['classID'],
                subjects,
            )
            if visible_subjects:
                class_rows.append({
                    'class_info': class_row,
                    'subjects': visible_subjects,
                    'student_count': max(
                        (subject['student_count'] for subject in visible_subjects),
                        default=0,
                    ),
                    'entered_count': sum(
                        subject['entered_count'] for subject in visible_subjects
                    ),
                    'expected_count': sum(
                        subject['student_count'] for subject in visible_subjects
                    ),
                })
        return render_template(
            'exam_marks_completion.html',
            exam=exam,
            class_rows=class_rows,
        )
    finally:
        connection.close()


@exams_bp.route('/admin/exams/<int:exam_id>/marks/entry', methods=['GET'])
@login_required
@exam_permission_required('marks.view')
def marks_entry(exam_id):
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        if class_id is None or subject_id is None:
            flash("Select a class and subject before entering marks.", "error")
            return redirect(url_for('exams.marks_entry_select', exam_id=exam_id))
        if request.args.get('entry_type') == 'components':
            return redirect(url_for(
                'exams.component_marks_entry',
                exam_id=exam_id,
                class_id=class_id,
                subject_id=subject_id,
            ))
        search_term = request.args.get('student', '').strip()
        page = request.args.get('page', default=1, type=int)
        page_size = 100
        class_info = service.get_exam_class_info(exam_id, class_id)
        subject = service.get_exam_subject(exam_id, class_id, subject_id)
        students = service.get_marks_for_class_subject(
            exam_id,
            class_id,
            subject_id,
            search_term=search_term,
            page=page,
            page_size=page_size,
        )
        total_students = service.count_exam_eligible_students(
            exam_id, class_id, subject_id, search_term=search_term
        )
        return render_template(
            'marks_entry.html',
            exam=exam,
            students=students,
            class_id=class_id,
            subject_id=subject_id,
            class_info=class_info,
            subject=subject,
            student_search=search_term,
            page=page,
            page_size=page_size,
            total_students=total_students,
            page_count=max(1, (total_students + page_size - 1) // page_size),
        )
    except ExamManagementError as e:
        flash(str(e), "error")
        return redirect(url_for('exams.marks_entry_select', exam_id=exam_id))
    finally:
        connection.close()


@exams_bp.route(
    '/admin/exams/<int:exam_id>/class/<int:class_id>/subject/<int:subject_id>/components',
    methods=['GET', 'POST'],
)
@login_required
@exam_permission_required('exam.grade.configure')
def configure_exam_assessment_components(exam_id, class_id, subject_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        class_info = service.get_exam_class_info(exam_id, class_id)
        subject = service.get_exam_subject(exam_id, class_id, subject_id)
        if request.method == 'POST':
            names = request.form.getlist('component_name')
            categories = request.form.getlist('component_category')
            maximums = request.form.getlist('component_maximum')
            weights = request.form.getlist('component_weight')
            if not (len(names) == len(categories) == len(maximums) == len(weights)):
                raise ExamManagementError(
                    "Assessment component fields are incomplete. Please try again."
                )
            components = [
                {
                    'name': name,
                    'category': categories[index],
                    'maximum_mark': maximums[index],
                    'weight_percent': weights[index] or None,
                    'display_order': index,
                    'is_required': True,
                }
                for index, name in enumerate(names)
                if name.strip() or maximums[index].strip() or weights[index].strip()
            ]
            saved_count = service.save_exam_assessment_components(
                exam_id,
                class_id,
                subject_id,
                components,
                int(session['userNo']),
            )
            flash(f"Saved {saved_count} assessment components.", "success")
            return redirect(url_for(
                'exams.configure_exam_assessment_components',
                exam_id=exam_id,
                class_id=class_id,
                subject_id=subject_id,
            ))
        components = service.get_exam_assessment_components(
            exam_id, class_id, subject_id
        )
        return render_template(
            'exam_assessment_components.html',
            exam=exam,
            class_info=class_info,
            subject=subject,
            components=components,
        )
    except ExamManagementError as exc:
        flash(str(exc), "error")
        return redirect(url_for('exams.marks_entry_select', exam_id=exam_id))
    finally:
        connection.close()


@exams_bp.route('/admin/exams/bundles', methods=['GET', 'POST'])
@login_required
@exam_permission_required('exam.grade.configure')
def manage_exam_bundles():
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        if request.method == 'POST':
            bundle_id = request.form.get('bundle_id', type=int)
            exam_ids = request.form.getlist('exam_id')
            exams = [
                {
                    'exam_id': exam_id,
                    'weight_percent': request.form.get(f'weight_{exam_id}') or None,
                }
                for exam_id in exam_ids
            ]
            tie_breakers = []
            for key, direction in zip(
                request.form.getlist('tie_breaker_key'),
                request.form.getlist('tie_breaker_direction'),
            ):
                if key:
                    tie_breakers.append({'key': key, 'direction': direction})
            saved_id = service.save_exam_bundle(
                bundle_id,
                request.form.get('name', ''),
                request.form.get('calculation_method', ''),
                request.form.get('ranking_metric', ''),
                request.form.get('ranking_scope', ''),
                request.form.get('ranking_style', ''),
                exams,
                int(session['userNo']),
                ranking_tie_breakers=tie_breakers,
                term_scope=request.form.get('term_scope') or None,
                effective_from=request.form.get('effective_from') or None,
                effective_to=request.form.get('effective_to') or None,
            )
            flash("Exam result bundle saved.", "success")
            return redirect(url_for('exams.manage_exam_bundles', bundle_id=saved_id))

        bundles = service.get_exam_bundles()
        selected_id = request.args.get('bundle_id', type=int)
        selected = next(
            (bundle for bundle in bundles if bundle['id'] == selected_id),
            None,
        )
        if selected_id is not None and selected is None:
            abort(404)
        return render_template(
            'exam_bundles.html',
            bundles=bundles,
            selected_bundle=selected,
            exam_options=service.get_exam_bundle_options(),
        )
    except ExamManagementError as exc:
        flash(str(exc), "error")
        return redirect(url_for('exams.manage_exam_bundles'))
    finally:
        connection.close()


@exams_bp.route(
    '/admin/exams/<int:exam_id>/class/<int:class_id>/subject/<int:subject_id>/component-marks',
    methods=['GET'],
)
@login_required
@exam_permission_required('marks.view')
def component_marks_entry(exam_id, class_id, subject_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        class_info = service.get_exam_class_info(exam_id, class_id)
        subject = service.get_exam_subject(exam_id, class_id, subject_id)
        components = service.get_exam_assessment_components(
            exam_id, class_id, subject_id
        )
        if not components:
            flash("Configure assessment components before entering component marks.", "error")
            return redirect(url_for(
                'exams.configure_exam_assessment_components',
                exam_id=exam_id,
                class_id=class_id,
                subject_id=subject_id,
            ))
        page_size = max(1, min(100, 1000 // len(components)))
        students = service.get_marks_for_class_subject(
            exam_id,
            class_id,
            subject_id,
            search_term=request.args.get('student', '').strip(),
            page=request.args.get('page', default=1, type=int),
            page_size=page_size,
        )
        search_term = request.args.get('student', '').strip()
        page = request.args.get('page', default=1, type=int)
        total_students = service.count_exam_eligible_students(
            exam_id, class_id, subject_id, search_term=search_term
        )
        marks = service.get_exam_component_marks_for_class(
            exam_id,
            class_id,
            subject_id,
            [str(student['AdmNo']) for student in students],
        )
        return render_template(
            'exam_component_marks.html',
            exam=exam,
            class_info=class_info,
            subject=subject,
            components=components,
            students=students,
            component_marks=marks,
            student_search=search_term,
            page=page,
            page_size=page_size,
            total_students=total_students,
            page_count=max(1, (total_students + page_size - 1) // page_size),
        )
    except ExamManagementError as exc:
        flash(str(exc), "error")
        return redirect(url_for('exams.marks_entry_select', exam_id=exam_id))
    finally:
        connection.close()


@exams_bp.route(
    '/admin/exams/<int:exam_id>/class/<int:class_id>/component-marks-template.xlsx',
    methods=['GET'],
)
@login_required
@exam_permission_required('marks.view')
def export_component_marks_workbook(exam_id, class_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        class_info = service.get_exam_class_info(exam_id, class_id)
        contexts = _get_component_workbook_context(service, exam_id, class_id)
        content = build_component_marks_workbook(list(contexts.values()))
        return send_file(
            BytesIO(content),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f"exam-{exam_id}-class-{class_id}-component-marks.xlsx",
        )
    except (ExamManagementError, ExamWorkbookError) as exc:
        flash(str(exc), "error")
        return redirect(url_for('exams.marks_entry_select', exam_id=exam_id))
    finally:
        connection.close()


@exams_bp.route(
    '/admin/exams/<int:exam_id>/class/<int:class_id>/component-marks-import',
    methods=['GET', 'POST'],
)
@login_required
@exam_permission_required('marks.edit')
def import_component_marks_workbook(exam_id, class_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        class_info = service.get_exam_class_info(exam_id, class_id)
        contexts = _get_component_workbook_context(service, exam_id, class_id)
        if request.method == 'GET':
            return render_template(
                'exam_workbook_import.html',
                exam=exam,
                class_info=class_info,
                result=None,
            )

        uploaded = request.files.get('file')
        if uploaded is None or not uploaded.filename:
            raise ExamWorkbookError("Choose an .xlsx workbook to upload.")
        if not uploaded.filename.lower().endswith('.xlsx'):
            raise ExamWorkbookError("The marks workbook must use the .xlsx format.")
        content = uploaded.stream.read(MAX_WORKBOOK_BYTES + 1)
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ExamWorkbookError("Workbook exceeds the 10 MiB upload limit.")
        validation = validate_component_marks_workbook(content, contexts)
        mode = request.form.get('mode', 'validate')
        if mode == 'apply' and validation['valid']:
            imported = service.save_exam_workbook_component_marks(
                exam_id,
                class_id,
                validation['prepared_marks'],
                int(session['userNo']),
                hashlib.sha256(content).hexdigest(),
                validation['row_count'],
            )
            flash(
                f"Imported {imported['mark_count']} component marks "
                f"(batch {imported['batch_id']}).",
                "success",
            )
            return redirect(url_for(
                'exams.import_component_marks_workbook',
                exam_id=exam_id,
                class_id=class_id,
            ))
        if mode not in {'validate', 'apply'}:
            raise ExamWorkbookError("Choose validation or import mode.")
        validation.pop('prepared_marks', None)
        validation['mode'] = mode
        return render_template(
            'exam_workbook_import.html',
            exam=exam,
            class_info=class_info,
            result=validation,
        )
    except (ExamManagementError, ExamWorkbookError) as exc:
        flash(str(exc), "error")
        return redirect(url_for(
            'exams.import_component_marks_workbook',
            exam_id=exam_id,
            class_id=class_id,
        ))
    finally:
        connection.close()


@exams_bp.route(
    '/api/exams/<int:exam_id>/class/<int:class_id>/subject/<int:subject_id>/component-marks',
    methods=['POST'],
)
@login_required
@exam_permission_required('marks.edit')
def api_save_component_marks(exam_id, class_id, subject_id):
    data = request.get_json(silent=True) or {}
    marks = data.get('marks')
    if not isinstance(marks, list):
        return jsonify({
            'success': False,
            'message': 'marks must be a list of component mark entries.',
        }), 400
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        saved_count = service.save_exam_component_marks_bulk(
            exam_id,
            class_id,
            subject_id,
            marks,
            int(session['userNo']),
        )
        return jsonify({'success': True, 'saved_count': saved_count})
    except (TypeError, ValueError, ExamManagementError) as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        current_app.logger.exception(
            "Failed to save exam component marks for exam %s", exam_id
        )
        return jsonify({
            'success': False,
            'message': 'Component marks could not be saved. Please retry.',
        }), 500
    finally:
        connection.close()


@exams_bp.route('/api/exams/<int:exam_id>/save-mark', methods=['POST'])
@login_required
@exam_permission_required('marks.edit')
def api_save_mark(exam_id):
    data = request.get_json(silent=True) or {}
    student_id = str(data.get('student_id', '')).strip()
    if not student_id:
        return jsonify({'success': False, 'message': 'student_id is required.'}), 400
    if data.get('subject_id') in (None, ''):
        return jsonify({'success': False, 'message': 'subject_id is required.'}), 400
    is_absent = data.get('is_absent', False)
    if not isinstance(is_absent, bool):
        return jsonify({'success': False, 'message': 'is_absent must be true or false.'}), 400
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        subject_id = _required_int(data.get('subject_id'), 'subject_id')
        service.save_mark(
            exam_id,
            student_id,
            subject_id,
            data.get('mark'),
            is_absent,
            data.get('remarks', ''),
            data.get('ct_remarks', ''),
            data.get('p_remarks', ''),
        )
        feedback = service.get_mark_feedback(
            exam_id, student_id, subject_id, data.get('mark'), is_absent
        )
        return jsonify({'success': True, **feedback})
    except (TypeError, ValueError, ExamManagementError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500
    finally: connection.close()


@exams_bp.route(
    '/api/exams/<int:exam_id>/override-subject-remark',
    methods=['POST'],
)
@login_required
@exam_permission_required('marks.edit')
def api_override_subject_remark(exam_id):
    data = request.get_json(silent=True) or {}
    student_id = str(data.get('student_id') or '').strip()
    if not student_id:
        return jsonify({'success': False, 'message': 'student_id is required.'}), 400
    try:
        subject_id = _required_int(data.get('subject_id'), 'subject_id')
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        service.override_exam_subject_remark(
            exam_id,
            student_id,
            subject_id,
            data.get('remarks', ''),
            data.get('reason', ''),
            int(session['userNo']),
        )
        return jsonify({'success': True, 'message': 'Subject remark override saved.'})
    except ExamManagementError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        current_app.logger.exception(
            "Failed to override subject remark for exam %s", exam_id
        )
        return jsonify({
            'success': False,
            'message': 'Subject remark could not be saved. Please retry.',
        }), 500
    finally:
        connection.close()


@exams_bp.route(
    '/admin/exams/<int:exam_id>/class/<int:class_id>/subject/<int:subject_id>/marks-template.csv',
    methods=['GET'],
)
@login_required
@exam_permission_required('marks.view')
def export_marks_template(exam_id, class_id, subject_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        service.get_exam_series(exam_id)
        class_info = service.get_exam_class_info(exam_id, class_id)
        subject = service.get_exam_subject(exam_id, class_id, subject_id)
        students = service.get_marks_for_class_subject(exam_id, class_id, subject_id)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'student_id', 'student_name', 'mark', 'is_absent',
            'remarks', 'ct_remarks', 'p_remarks',
        ])
        for student in students:
            writer.writerow([
                student['AdmNo'],
                f"{student['FName']} {student['LName']}",
                student['mark'] if student['mark'] is not None else '',
                'true' if student['is_absent'] else 'false',
                student.get('remarks') or '',
                student.get('ct_remarks') or '',
                student.get('p_remarks') or '',
            ])
        filename = (
            f"marks-{exam_id}-{class_info['classID']}-{subject['id']}.csv"
        )
        return send_file(
            BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename,
        )
    except ExamManagementError as e:
        flash(str(e), "error")
        return redirect(url_for('exams.marks_entry_select', exam_id=exam_id))
    finally:
        connection.close()


@exams_bp.route(
    '/admin/exams/<int:exam_id>/class/<int:class_id>/subject/<int:subject_id>/marks.csv',
    methods=['POST'],
)
@login_required
@exam_permission_required('marks.edit')
def import_marks_csv(exam_id, class_id, subject_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        uploaded_file = request.files.get('file')
        if uploaded_file is None or not uploaded_file.filename:
            raise ExamManagementError("Choose a CSV file to upload.")
        if not uploaded_file.filename.lower().endswith('.csv'):
            raise ExamManagementError("The marks file must be a CSV.")

        service.get_exam_series(exam_id)
        service.get_exam_class_info(exam_id, class_id)
        service.get_exam_subject(exam_id, class_id, subject_id)
        headers, csv_rows = _parse_marks_csv(uploaded_file)
        required_columns = {'student_id', 'mark', 'is_absent'}
        if not required_columns.issubset(headers):
            raise ExamManagementError(
                "CSV must include student_id, mark, and is_absent columns. "
                "Accepted aliases include admission number, score, and absent. "
                "Use the downloaded template."
            )

        marks = []
        seen_student_ids = set()
        for line_number, row in csv_rows:
            student_id = row.get('student_id', '').strip()
            if not student_id:
                raise ExamManagementError(
                    f"CSV row {line_number} is missing a student ID."
                )
            if student_id in seen_student_ids:
                raise ExamManagementError(
                    f"CSV row {line_number} duplicates student ID {student_id}."
                )
            seen_student_ids.add(student_id)

            absent_value = (row.get('is_absent') or '').strip().casefold()
            if not absent_value:
                absent_value = 'false'
            if absent_value not in {'true', 'false', '1', '0', 'yes', 'no'}:
                raise ExamManagementError(
                    f"Invalid is_absent value on CSV row {line_number}."
                )
            mark_value = row.get('mark', '').strip()
            if absent_value in {'true', '1', 'yes'} and mark_value:
                raise ExamManagementError(
                    f"CSV row {line_number} has both a score and is_absent=true."
                )
            if mark_value:
                try:
                    numeric_mark = float(mark_value)
                except ValueError as exc:
                    raise ExamManagementError(
                        f"CSV row {line_number} has an invalid score."
                    ) from exc
                if not 0 <= numeric_mark <= 100:
                    raise ExamManagementError(
                        f"CSV row {line_number} score must be between 0 and 100."
                    )
            marks.append({
                'student_id': student_id,
                'subject_id': subject_id,
                'mark': mark_value,
                'is_absent': absent_value in {'true', '1', 'yes'},
                'remarks': row.get('remarks', ''),
                'ct_remarks': row.get('ct_remarks', ''),
                'p_remarks': row.get('p_remarks', ''),
            })
        saved_count = service.save_marks_bulk(exam_id, marks)
        flash(f"Marks imported for {saved_count} students.", "success")
    except (ValueError, ExamManagementError) as e:
        flash(str(e), "error")
    except Exception as e:
        flash(f"Unable to import marks: {e}", "error")
    finally:
        connection.close()
    return redirect(url_for(
        'exams.marks_entry',
        exam_id=exam_id,
        class_id=class_id,
        subject_id=subject_id,
    ))

@exams_bp.route('/admin/exams/<int:exam_id>/tabulation', methods=['GET'])
@login_required
def exam_tabulation(exam_id):
    class_id = request.args.get('class_id', type=int)
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        access_service = _get_exam_access_service(connection)
        classes = [
            class_row for class_row in service.get_exam_classes(exam_id)
            if access_service is None or access_service.has_permission(
                'report.class',
                exam_id=exam_id,
                class_id=class_row['classID'],
            )
        ]
        if class_id is not None and class_id not in {
            class_row['classID'] for class_row in classes
        }:
            abort(403)
        tab_data = service.get_class_tabulation(exam_id, class_id) if class_id else None
        class_info = tab_data['class_info'] if tab_data else None
        return render_template(
            'exam_tabulation.html',
            exam=exam,
            classes=classes,
            tabulation_data=tab_data,
            class_id=class_id,
            class_info=class_info,
        )
    except ExamManagementError as e:
        flash(str(e), "error")
        return redirect(url_for('exams.exam_tabulation', exam_id=exam_id))
    finally:
        connection.close()

@exams_bp.route('/admin/exams/<int:exam_id>/student/<student_id>/report', methods=['GET'])
@login_required
@exam_permission_required('report.student')
def student_report_card(exam_id, student_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        data = service.get_report_card_data(student_id, exam_id)
        return render_template('report_card.html', **data)
    except ExamManagementError:
        abort(404)
    finally: connection.close()

@exams_bp.route('/admin/exams/<int:exam_id>/reports/series', methods=['GET'])
@login_required
@exam_permission_required('exam.report')
def exam_series_report(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        class_rankings = []
        for cls in exam['classes']:
            class_rankings.append({'class_name': cls['display_name'], 'students': service.get_exam_rankings(exam_id, class_id=cls['classID'], limit=3)})
        return render_template('exam_series_report.html', exam=exam, class_rankings=class_rankings, overall_top_3=service.get_exam_rankings(exam_id, limit=3), subject_winners=service.get_subject_winners(exam_id), most_improved=service.get_most_improved(exam_id))
    finally: connection.close()


@exams_bp.route('/admin/exams/analytics', methods=['GET'])
@login_required
@exam_permission_required('exam.analytics')
def exam_analytics_dashboard():
    connection = get_db_connection()
    try:
        service = ExamManagementService(connection)
        exams = service.get_all_exams()
        selected_exam_id = request.args.get('exam_id', type=int)
        overview = None
        if selected_exam_id is not None:
            if not service.get_exam_series(selected_exam_id):
                abort(404)
            overview = service.get_exam_analytics_overview(selected_exam_id)
        return render_template(
            'exam_analytics_dashboard.html',
            exams=exams,
            selected_exam_id=selected_exam_id,
            overview=overview,
        )
    finally:
        connection.close()


@exams_bp.route('/admin/exams/analytics/export.csv', methods=['GET'])
@login_required
@exam_permission_required('exam.analytics')
def export_exam_analytics_csv():
    exam_id = request.args.get('exam_id', type=int)
    view = request.args.get('view', 'subjects')
    if exam_id is None:
        abort(400, description="An exam series is required for analytics export.")
    if view not in {'classes', 'subjects', 'streams', 'top_students'}:
        abort(400, description="Choose a supported analytics export.")

    connection = get_db_connection()
    try:
        service = ExamManagementService(connection)
        if not service.get_exam_series(exam_id):
            abort(404)
        overview = service.get_exam_analytics_overview(exam_id)
        if view == 'classes':
            headings = [
                'Class', 'Class group', 'Stream', 'Learners', 'Eligible learners',
                'Scored learners', 'Mean score (%)', 'Marks entered',
                'Marks expected',
            ]
            rows = (
                [
                    item['class_name'], item['class_group'], item.get('stream_code'),
                    item['student_count'], item['eligible_student_count'],
                    item['scored_student_count'], item['mean_score'],
                    item['entered_mark_count'], item['expected_mark_count'],
                ]
                for item in overview['classes']
            )
        elif view == 'subjects':
            headings = [
                'Subject', 'Code', 'Scored learners', 'Eligible learners',
                'Recorded marks', 'Absent subjects', 'Absent components',
                'Missing subjects', 'Missing components', 'Mean', 'Median',
                'Mode(s)', 'Lowest', 'Highest', 'Variance',
                'Standard deviation', 'Q1', 'Q3', 'Grade distribution',
            ]
            rows = (
                [
                    item['name'], item['code'], item['count'],
                    item.get('eligible_count', item['statistics']['eligible_count']),
                    item['entered_count'], item['absent_count'],
                    item['absent_component_count'], item['missing_count'],
                    item['missing_component_count'], item['average'],
                    item['statistics']['median'],
                    ', '.join(map(str, item['statistics']['mode'])),
                    item['statistics']['lowest'], item['statistics']['highest'],
                    item['statistics']['variance'],
                    item['statistics']['standard_deviation'],
                    item['statistics']['quartiles']['q1'],
                    item['statistics']['quartiles']['q3'],
                    ', '.join(
                        f"{grade}: {count}"
                        for grade, count in sorted(
                            item['statistics']['grade_distribution'].items()
                        )
                    ),
                ]
                for item in overview['subject_stats']
            )
        elif view == 'streams':
            headings = [
                'Class group', 'Stream', 'Classes', 'Eligible learners',
                'Mean score (%)',
            ]
            rows = (
                [
                    group['class_group'], stream['stream'],
                    ', '.join(stream['classes']), stream['student_count'],
                    stream['mean_score'],
                ]
                for group in overview['stream_comparisons']
                for stream in group['streams']
            )
        else:
            headings = [
                'Rank', 'Learner', 'Admission number', 'Class',
                'Subjects marked', 'Average (%)',
            ]
            rows = (
                [
                    student['rank'], student['name'], student['admno'],
                    student['class_name'], student['numeric_subjects'],
                    student['average'],
                ]
                for student in overview['top_students']
            )

        output = StringIO()
        writer = csv.writer(output, lineterminator='\r\n')
        writer.writerow([_spreadsheet_safe_cell(value) for value in headings])
        writer.writerows(
            [_spreadsheet_safe_cell(value) for value in row]
            for row in rows
        )

        school_id = get_current_school_id()
        if school_id is None:
            abort(403)
        connection.begin()
        audit_committed = False
        try:
            record_exam_event(
                connection.cursor(),
                int(school_id),
                'analytics.exported',
                'exam_series',
                entity_id=str(exam_id),
                actor_user_id=session.get('userNo'),
                new_values={'format': 'csv', 'view': view},
            )
            connection.commit()
            audit_committed = True
        finally:
            if not audit_committed:
                connection.rollback()

        return send_file(
            BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f"exam-{exam_id}-{view}-analytics.csv",
        )
    finally:
        connection.close()


@exams_bp.route('/admin/exams/<int:exam_id>/class/<int:class_id>/reports', methods=['GET'])
@login_required
@exam_permission_required('report.class')
def class_exam_report(exam_id, class_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        class_info = service.get_exam_class_info(exam_id, class_id)
        stats = service.get_class_performance_distribution(exam_id, class_id)
        return render_template('class_exam_report.html', exam=exam, class_info=class_info, stats=stats, top_3=service.get_exam_rankings(exam_id, class_id=class_id, limit=3), subject_winners=service.get_subject_winners(exam_id, class_id=class_id), most_improved=service.get_most_improved(exam_id, class_id=class_id))
    except ExamManagementError:
        abort(404)
    finally: connection.close()


@exams_bp.route(
    '/admin/exams/<int:exam_id>/class/<int:class_id>/reports.csv',
    methods=['GET'],
)
@login_required
@exam_permission_required('report.class')
def export_class_exam_marksheet_csv(exam_id, class_id):
    connection = get_db_connection()
    try:
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        class_info = service.get_exam_class_info(exam_id, class_id)
        tabulation = service.get_class_tabulation(exam_id, class_id)
        subject_names = {
            subject['id']: (subject.get('code', ''), subject['name'])
            for subject in tabulation['subjects']
        }
        output = StringIO()
        writer = csv.writer(output, lineterminator='\r\n')
        writer.writerow([
            'Learner', 'Admission number', 'Class', 'Subject code', 'Subject',
            'Mark state', 'Mark (%)', 'Grade', 'Total', 'Average (%)', 'Rank',
        ])
        for student in tabulation['tabulation']:
            for mark in student['marks']:
                subject_code, subject_name = subject_names.get(
                    mark['subject_id'], ('', '')
                )
                writer.writerow([
                    _spreadsheet_safe_cell(student['name']),
                    _spreadsheet_safe_cell(student['admno']),
                    _spreadsheet_safe_cell(class_info['display_name']),
                    _spreadsheet_safe_cell(subject_code),
                    _spreadsheet_safe_cell(subject_name),
                    _spreadsheet_safe_cell(mark.get('state')),
                    _spreadsheet_safe_cell(mark.get('mark')),
                    _spreadsheet_safe_cell(mark.get('grade')),
                    _spreadsheet_safe_cell(student.get('total')),
                    _spreadsheet_safe_cell(student.get('average')),
                    _spreadsheet_safe_cell(student.get('rank')),
                ])

        school_id = get_current_school_id()
        if school_id is None:
            abort(403)
        connection.begin()
        audit_committed = False
        try:
            record_exam_event(
                connection.cursor(),
                int(school_id),
                'marksheet.exported',
                'exam_class',
                entity_id=f'{exam_id}:{class_id}',
                actor_user_id=session.get('userNo'),
                new_values={'format': 'csv'},
            )
            connection.commit()
            audit_committed = True
        finally:
            if not audit_committed:
                connection.rollback()

        return send_file(
            BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f"exam-{exam_id}-class-{class_id}-marksheet.csv",
        )
    except ExamManagementError:
        abort(404)
    finally:
        connection.close()


@exams_bp.route('/admin/exams/<int:exam_id>/stream-analysis', methods=['GET'])
@login_required
@admin_required
def stream_analysis(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        analysis = service.get_stream_performance_comparison(exam_id)
        return render_template('stream_analysis.html', exam=exam, analysis=analysis)
    finally: connection.close()
