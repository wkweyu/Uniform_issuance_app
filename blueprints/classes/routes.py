from blueprints.classes.services import ClassManagementService, PromotionError, ValidationError
from flask import Blueprint, render_template, request, redirect, url_for, session, g, jsonify, flash
from core.flash_messages import flash_message
from core.permissions import admin_required, login_required

classes_bp = Blueprint('classes', __name__)


def _required_text(value, field_name):
    parsed = (value or '').strip()
    if not parsed:
        raise ValueError(f"{field_name} is required.")
    return parsed


def _required_int(value, field_name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} is required and must be a valid integer.")

def get_db_connection():
    from core.db import get_db_connection
    return get_db_connection()

@classes_bp.route('/admin/manage_classes', methods=['GET'])
@login_required
@admin_required
def manage_classes():
    connection = get_db_connection()
    service = ClassManagementService(connection)

    try:
        # Data aggregation for dashboard
        stats = service.get_dashboard_stats()
        classes = service.get_classes_with_details()
        streams = service.get_allowed_streams(school_id=service.school_id)

        alerts = {
            'missing_subjects': service.get_classes_missing_subjects(),
            'missing_class_teachers': service.get_classes_missing_teachers(),
            'missing_subject_teachers': service.get_class_subjects_missing_teachers()
        }

        return render_template('class_management_dashboard.html',
                             **stats,
                             classes=classes,
                             streams=streams,
                             **alerts)
    except Exception as e:
        flash_message(f"Error loading dashboard: {str(e)}", "error")
        return redirect(url_for('index'))
    finally:
        connection.close()

@classes_bp.route('/admin/classes/<int:class_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_class(class_id):
    class_name = request.form.get('class_name', '').strip()
    class_group = request.form.get('class_group', 'Grade 1-3')
    stream_code = request.form.get('stream_code', '').strip()

    if not class_name or not stream_code:
        return jsonify({'error': 'Class name and stream are required'}), 400

    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        service.update_class(class_id, class_name, class_group, stream_code)
        return jsonify({'success': True, 'message': f"Class updated successfully."})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    finally:
        connection.close()

@classes_bp.route('/admin/classes/<int:class_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_class(class_id):
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        service.delete_class(class_id)
        return jsonify({'message': 'Class deleted successfully.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

@classes_bp.route('/admin/class_subjects_select', methods=['GET'])
@login_required
@admin_required
def class_subjects_select():
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        classes = service.get_active_classes()
        return render_template('class_subjects_select.html', classes=classes)
    finally:
        connection.close()

@classes_bp.route('/admin/class_reports', methods=['GET'])
@login_required
@admin_required
def class_reports():
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        summary = service.get_class_summary_report()
        promotions = service.get_recent_promotions_log()
        return render_template('class_reports.html', class_summary=summary, promotions=promotions)
    finally:
        connection.close()

@classes_bp.route('/admin/classes/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_class():
    connection = get_db_connection()
    service = ClassManagementService(connection)
    if request.method == 'POST':
        try:
            service.create_class(
                academic_year_id=_required_int(request.form.get('academic_year_id'), 'academic_year_id'),
                class_group_code=request.form.get('class_group_code'),
                stream_code=request.form.get('stream_code'),
                created_by=session.get('userNo'),
                class_name=request.form.get('class_name', '').strip()
            )
            flash('Class created successfully', 'success')
            return redirect(url_for('classes.manage_classes'))
        except (ValueError, ValidationError) as e:
            flash(f'Error creating class: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error creating class: {str(e)}', 'error')

    years = service.get_all_academic_years()
    groups = [{'code': k, 'name': v['name']} for k, v in service.get_class_groups().items()]
    streams = service.get_allowed_streams(school_id=service.school_id)
    connection.close()
    return render_template('create_class.html', years=years, groups=groups, streams=streams)

@classes_bp.route('/admin/classes/promote', methods=['GET', 'POST'])
@login_required
@admin_required
def promote_students():
    connection = get_db_connection()
    service = ClassManagementService(connection)
    if request.method == 'POST':
        try:
            result = service.promote_students(
                old_class_id=_required_int(request.form.get('old_class_id'), 'old_class_id'),
                new_class_id=_required_int(request.form.get('new_class_id'), 'new_class_id'),
                promoted_by=session.get('userNo'),
                notes=request.form.get('notes', '')
            )
            flash(result['message'], 'success')
            return redirect(url_for('classes.manage_classes'))
        except (ValueError, ValidationError, PromotionError) as e:
            flash(f'Promotion failed: {str(e)}', 'error')
        except Exception as e:
            flash(f'Promotion failed: {str(e)}', 'error')

    years = service.get_all_academic_years()
    connection.close()
    return render_template('promote_students.html', years=years)

@classes_bp.route('/admin/manage_streams', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_streams():
    connection = get_db_connection()
    service = ClassManagementService(connection)
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add':
                service.add_stream(request.form.get('stream_code'), request.form.get('stream_name'))
                flash('Stream added successfully', 'success')
            elif action == 'toggle':
                service.toggle_stream(_required_int(request.form.get('stream_id'), 'stream_id'))
                flash('Stream status updated', 'success')
            elif action == 'delete':
                service.delete_stream(_required_int(request.form.get('stream_id'), 'stream_id'))
                flash('Stream deleted successfully', 'success')
        except (ValueError, ValidationError) as e:
            flash(str(e), 'error')
        except Exception as e:
            flash(str(e), 'error')

    streams = service.get_all_streams()
    connection.close()
    return render_template('manage_streams.html', streams=streams)

@classes_bp.route('/admin/class/<int:class_id>/subjects', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_class_subjects(class_id):
    connection = get_db_connection()
    service = ClassManagementService(connection)
    if request.method == 'POST':
        try:
            subject_ids = [_required_int(sid, 'subject_ids') for sid in request.form.getlist('subject_ids')]
            service.allocate_subjects_to_class(class_id, subject_ids, compulsory=(request.form.get('is_compulsory') == 'on'))
            flash('Subjects allocated to class', 'success')
            return redirect(url_for('classes.manage_classes'))
        except (ValueError, ValidationError) as e:
            flash(str(e), 'error')

    subjects = service.get_active_subjects()
    allocated = service.get_allocated_subject_ids(class_id)
    connection.close()
    return render_template('manage_class_subjects.html', class_id=class_id, subjects=subjects, allocated_subject_ids=allocated)

@classes_bp.route('/admin/teacher/allocate', methods=['GET', 'POST'])
@login_required
@admin_required
def allocate_teacher():
    connection = get_db_connection()
    service = ClassManagementService(connection)
    if request.method == 'POST':
        try:
            teacher_id = _required_int(request.form.get('teacher_id'), 'teacher_id')
            class_id = _required_int(request.form.get('class_id'), 'class_id')
            subject_id = request.form.get('subject_id')
            academic_year_id = _required_int(request.form.get('academic_year_id'), 'academic_year_id')

            if request.form.get('is_class_teacher') == 'on':
                service.set_class_teacher(class_id, teacher_id, academic_year_id)

            if subject_id:
                service.allocate_teacher_to_class_subject(teacher_id, class_id, _required_int(subject_id, 'subject_id'), academic_year_id)

            flash('Allocation successful', 'success')
            return redirect(url_for('classes.manage_classes'))
        except (ValueError, ValidationError) as e:
            flash(f'Error: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    context = {
        'years': service.get_all_academic_years(),
        'teachers': service.get_active_teachers(),
        'classes': service.get_active_classes(),
        'subjects': service.get_active_subjects()
    }
    connection.close()
    return render_template('allocate_teacher.html', **context)

@classes_bp.route('/admin/get-teachers', methods=['GET'])
@login_required
@admin_required
def get_teachers():
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        return jsonify({'success': True, 'teachers': service.get_active_teachers()})
    finally:
        connection.close()

@classes_bp.route('/admin/class/<int:class_id>/manage', methods=['GET'])
@login_required
@admin_required
def manage_class_hub(class_id):
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        data = service.get_class_hub_data(class_id)
        return render_template('manage_class_master.html', class_id=class_id, **data)
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('classes.manage_classes'))
    finally:
        connection.close()

@classes_bp.route('/api/class/<int:class_id>/update-subjects', methods=['POST'])
@login_required
@admin_required
def api_update_class_subjects(class_id):
    data = request.get_json(silent=True) or {}
    subject_ids = data.get('subject_ids')
    if not isinstance(subject_ids, list):
        return jsonify({'success': False, 'message': 'subject_ids must be a list.'}), 400
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        service.allocate_subjects_to_class(class_id, [_required_int(sid, 'subject_id') for sid in subject_ids])
        return jsonify({'success': True, 'message': 'Subjects updated successfully'})
    except (TypeError, ValueError, ValidationError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

@classes_bp.route('/api/class/<int:class_id>/assign-teacher', methods=['POST'])
@login_required
@admin_required
def api_assign_teacher(class_id):
    data = request.get_json(silent=True) or {}
    if not data.get('teacher_id'):
        return jsonify({'success': False, 'message': 'teacher_id is required.'}), 400
    if not data.get('is_class_teacher') and not data.get('subject_id'):
        return jsonify({'success': False, 'message': 'Either is_class_teacher or subject_id is required.'}), 400
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        teacher_id = _required_int(data.get('teacher_id'), 'teacher_id')
        ay_id = service.get_class_academic_year_id(class_id)
        if data.get('is_class_teacher'):
            service.set_class_teacher(class_id, teacher_id, ay_id)
        if data.get('subject_id'):
            service.allocate_teacher_to_class_subject(teacher_id, class_id, _required_int(data.get('subject_id'), 'subject_id'), ay_id)
        return jsonify({'success': True, 'message': 'Teacher assigned successfully'})
    except (TypeError, ValueError, ValidationError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

@classes_bp.route('/api/class/<int:class_id>/batch-enroll-subjects', methods=['POST'])
@login_required
@admin_required
def api_batch_enroll_subjects(class_id):
    data = request.get_json(silent=True) or {}
    subject_ids = data.get('subject_ids')
    if subject_ids is not None and not isinstance(subject_ids, list):
        return jsonify({'success': False, 'message': 'subject_ids must be a list when provided.'}), 400
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        parsed_subject_ids = [_required_int(sid, 'subject_id') for sid in subject_ids] if subject_ids is not None else None
        count = service.enroll_all_students_in_class_subjects(class_id, parsed_subject_ids)
        return jsonify({'success': True, 'message': f'Successfully enrolled students in {count} instances'})
    except (TypeError, ValueError, ValidationError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

@classes_bp.route('/admin/class/<int:class_id>/get-subjects', methods=['GET'])
@login_required
def get_class_subjects(class_id):
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        return jsonify({'success': True, 'subjects': service.get_subjects_for_class_form(class_id)})
    finally:
        connection.close()

@classes_bp.route('/admin/get-classes-by-year', methods=['GET'])
@login_required
def get_classes_by_year():
    year_id = request.args.get('year_id')
    if not year_id:
        return jsonify({'success': False, 'error': 'year_id required'})
    connection = get_db_connection()
    service = ClassManagementService(connection)
    try:
        return jsonify({'success': True, 'classes': service.get_classes_by_year(int(year_id))})
    finally:
        connection.close()
