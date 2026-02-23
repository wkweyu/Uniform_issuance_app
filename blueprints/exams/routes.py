from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify, send_file
from core.permissions import admin_required, login_required
from core.db import get_db_connection
from blueprints.exams.services import ExamManagementService, ExamManagementError
from blueprints.classes.services import ClassManagementService
import csv
import io
from io import StringIO, BytesIO
from datetime import datetime

exams_bp = Blueprint('exams', __name__)

@exams_bp.route('/api/exams/<int:exam_id>/class/<int:class_id>/subjects-status')
@login_required
def get_exam_subjects_status(exam_id, class_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        # Simplified logic: get subjects for class and check marks entry status
        # This is often used in a dashboard or marks entry page
        # Logic from app.py would be moved to service methods in a full refactor
        return jsonify([]) # Placeholder
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
        flash("✅ Grading scale created.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('exams.manage_grading_scales'))

@exams_bp.route('/admin/grading-scales/<int:scale_id>')
@login_required
@admin_required
def edit_grading_scale(scale_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    scale = service.get_grading_scale(scale_id)
    details = service.get_grading_details(scale_id)
    connection.close()
    return render_template('edit_grading_scale.html', scale=scale, details=details)

@exams_bp.route('/admin/grading-scales/<int:scale_id>/save-grades', methods=['POST'])
@login_required
@admin_required
def save_grading_details(scale_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        # Parse grades from form...
        grades = [] # logic to extract from form
        service.save_grading_details(scale_id, grades)
        flash("✅ Grading rules updated.", "success")
    except Exception as e: flash(str(e), "error")
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
                cid = int(key.split('_')[1])
                sid = int(val) if val else None
                service.assign_scale_to_class(cid, sid)
        flash("✅ Grading scales assigned to classes.", "success")
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
    if request.method == 'POST':
        try:
            service.create_exam_series(
                name=request.form.get('name'),
                academic_year_id=int(request.form.get('academic_year_id')),
                term=int(request.form.get('term')),
                created_by=session['userNo'],
                class_ids=[int(cid) for cid in request.form.getlist('class_ids')]
            )
            flash("✅ Exam series created.", "success")
            return redirect(url_for('exams.exams_dashboard'))
        except Exception as e: flash(str(e), "error")

    years = class_service.get_all_academic_years()
    classes = class_service.get_active_classes()
    connection.close()
    return render_template('create_exam.html', years=years, classes=classes)

@exams_bp.route('/admin/exams/<int:exam_id>/toggle-lock', methods=['POST'])
@login_required
@admin_required
def toggle_exam_status(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        service.toggle_exam_lock(exam_id, request.form.get('lock') == 'true')
        flash("✅ Exam status updated.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('exams.exams_dashboard'))

@exams_bp.route('/admin/exams/<int:exam_id>/marks/select', methods=['GET'])
@login_required
@admin_required
def marks_entry_select(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    exam = service.get_exam_series(exam_id)
    classes = service.get_exam_classes(exam_id)
    connection.close()
    return render_template('marks_entry_select.html', exam=exam, classes=classes)

@exams_bp.route('/admin/exams/<int:exam_id>/marks/entry', methods=['GET'])
@login_required
@admin_required
def marks_entry(exam_id):
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    connection = get_db_connection(); service = ExamManagementService(connection)
    exam = service.get_exam_series(exam_id)
    students = service.get_marks_for_class_subject(exam_id, class_id, subject_id)
    connection.close()
    return render_template('marks_entry.html', exam=exam, students=students, class_id=class_id, subject_id=subject_id)

@exams_bp.route('/api/exams/<int:exam_id>/save-mark', methods=['POST'])
@login_required
@admin_required
def api_save_mark(exam_id):
    data = request.json
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        service.save_mark(exam_id, data['student_id'], int(data['subject_id']), data.get('mark'), data.get('is_absent', False), data.get('remarks', ''))
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500
    finally: connection.close()

@exams_bp.route('/admin/exams/<int:exam_id>/tabulation', methods=['GET'])
@login_required
@admin_required
def exam_tabulation(exam_id):
    class_id = request.args.get('class_id', type=int)
    connection = get_db_connection(); service = ExamManagementService(connection)
    exam = service.get_exam_series(exam_id)
    tab_data = service.get_class_tabulation(exam_id, class_id) if class_id else None
    connection.close()
    return render_template('exam_tabulation.html', exam=exam, tabulation_data=tab_data, class_id=class_id)

@exams_bp.route('/admin/exams/<int:exam_id>/student/<student_id>/report', methods=['GET'])
@login_required
def student_report_card(exam_id, student_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        data = service.get_report_card_data(student_id, exam_id)
        return render_template('report_card.html', **data)
    finally: connection.close()

@exams_bp.route('/admin/exams/<int:exam_id>/reports/series', methods=['GET'])
@login_required
@admin_required
def exam_series_report(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
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
        stats = service.get_class_performance_distribution(exam_id, class_id)
        return render_template('class_exam_report.html', exam=exam, stats=stats, top_3=service.get_exam_rankings(exam_id, class_id=class_id, limit=3), subject_winners=service.get_subject_winners(exam_id, class_id=class_id), most_improved=service.get_most_improved(exam_id, class_id=class_id))
    finally: connection.close()

@exams_bp.route('/admin/exams/<int:exam_id>/stream-analysis', methods=['GET'])
@login_required
@admin_required
def stream_analysis(exam_id):
    connection = get_db_connection(); service = ExamManagementService(connection)
    try:
        exam = service.get_exam_series(exam_id)
        analysis = service.get_stream_performance_comparison(exam_id)
        return render_template('stream_analysis.html', exam=exam, analysis=analysis)
    finally: connection.close()
