from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify, send_file, abort
from werkzeug.exceptions import HTTPException
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.exams.services import ExamManagementService, ExamManagementError
from blueprints.classes.services import ClassManagementService
import csv
import io
from io import StringIO, BytesIO
from datetime import datetime

exams_bp = Blueprint('exams', __name__)


def _required_int(value, field_name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} is required and must be a valid integer.")


def _get_editable_exam_classes(class_service, exam):
    classes = class_service.get_active_classes()
    active_class_ids = {cls['classID'] for cls in classes}
    classes.extend(
        cls for cls in exam['classes']
        if cls['classID'] not in active_class_ids
    )
    return sorted(classes, key=lambda cls: cls['display_name'])


@exams_bp.route('/api/exams/<int:exam_id>/class/<int:class_id>/subjects-status')
@login_required
def get_exam_subjects_status(exam_id, class_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        return jsonify({
            'success': True,
            'subjects': service.get_exam_subjects_status(exam_id, class_id),
        })
    except ExamManagementError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    finally: connection.close()

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
    service = ExamManagementService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    classes = class_service.get_active_classes()
    scales = service.get_all_grading_scales()
    connection.close()
    return render_template('assign_grading_scales.html', classes=classes, scales=scales)

@exams_bp.route('/admin/grading-scales/save-assignments', methods=['POST'])
@login_required
@admin_required
def save_class_grading_assignments():
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        for key, val in request.form.items():
            if key.startswith('class_'):
                cid = _required_int(key.split('_')[1], 'class_id')
                sid = _required_int(val, 'scale_id') if val else None
                service.assign_scale_to_class(cid, sid)
        flash("Grading scales assigned to classes.", "success")
    except (ValueError, ExamManagementError) as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('exams.assign_class_grading'))

@exams_bp.route('/admin/exams')
@login_required
@admin_required
def exams_dashboard():
    connection = get_db_connection(); service = ExamManagementService(connection)
    exams = service.get_all_exams()
    connection.close()
    return render_template('exams_dashboard.html', exams=exams)

@exams_bp.route('/admin/exams/create', methods=['GET', 'POST'])
@login_required
@admin_required
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
@admin_required
def toggle_exam_status(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        service.toggle_exam_lock(exam_id, request.form.get('lock') == 'true')
        flash("Exam status updated.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('exams.exams_dashboard'))

@exams_bp.route('/admin/exams/<int:exam_id>/marks/select', methods=['GET'])
@login_required
@admin_required
def marks_entry_select(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        classes = service.get_exam_classes(exam_id)
        return render_template('marks_entry_select.html', exam=exam, classes=classes)
    finally:
        connection.close()

@exams_bp.route('/admin/exams/<int:exam_id>/marks/entry', methods=['GET'])
@login_required
@admin_required
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
        class_info = service.get_exam_class_info(exam_id, class_id)
        subject = service.get_exam_subject(exam_id, class_id, subject_id)
        students = service.get_marks_for_class_subject(exam_id, class_id, subject_id)
        return render_template(
            'marks_entry.html',
            exam=exam,
            students=students,
            class_id=class_id,
            subject_id=subject_id,
            class_info=class_info,
            subject=subject,
        )
    except ExamManagementError as e:
        flash(str(e), "error")
        return redirect(url_for('exams.marks_entry_select', exam_id=exam_id))
    finally:
        connection.close()

@exams_bp.route('/api/exams/<int:exam_id>/save-mark', methods=['POST'])
@login_required
@admin_required
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
    '/admin/exams/<int:exam_id>/class/<int:class_id>/subject/<int:subject_id>/marks-template.csv',
    methods=['GET'],
)
@login_required
@admin_required
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
@admin_required
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
        reader = csv.DictReader(
            io.TextIOWrapper(uploaded_file.stream, encoding='utf-8-sig', newline='')
        )
        required_columns = {'student_id', 'mark', 'is_absent'}
        if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
            raise ExamManagementError(
                "CSV must include student_id, mark, and is_absent columns. "
                "Use the downloaded template."
            )

        marks = []
        for line_number, row in enumerate(reader, start=2):
            absent_value = (row.get('is_absent') or '').strip().casefold()
            if absent_value not in {'true', 'false', '1', '0', 'yes', 'no'}:
                raise ExamManagementError(
                    f"Invalid is_absent value on CSV row {line_number}."
                )
            marks.append({
                'student_id': row.get('student_id', '').strip(),
                'subject_id': subject_id,
                'mark': row.get('mark', '').strip(),
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
@admin_required
def exam_tabulation(exam_id):
    class_id = request.args.get('class_id', type=int)
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        if not exam:
            abort(404)
        classes = service.get_exam_classes(exam_id)
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
@admin_required
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

@exams_bp.route('/admin/exams/<int:exam_id>/class/<int:class_id>/reports', methods=['GET'])
@login_required
@admin_required
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
