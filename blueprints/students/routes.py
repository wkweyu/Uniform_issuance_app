from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify, current_app
from core.permissions import admin_required, login_required
from core.tenancy import require_current_school_id
from blueprints.students.services import StudentService
from blueprints.fees.services import FeesService
from blueprints.exams.services import ExamManagementService
from blueprints.classes.services import ClassManagementService
from datetime import date, datetime
import csv
import io

students_bp = Blueprint('students', __name__)

def get_db_connection():
    from core.db import get_db_connection
    return get_db_connection()

def _required_int(value, field_name):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid integer.')

def get_current_term_and_year():
    from core.helpers import get_current_term_and_year
    return get_current_term_and_year()

@students_bp.route('/admit', methods=['GET', 'POST'])
@admin_required
def admit_student():
    connection = get_db_connection()
    service = StudentService(connection)

    if request.method == 'POST':
        class_id = request.form.get('class_id')
        class_data = service.get_class_details(class_id)

        student_data = {
            'admno': request.form.get('admno').strip(),
            'fname': request.form.get('fname').strip(),
            'mname': request.form.get('mname', '').strip(),
            'lname': request.form.get('lname').strip(),
            'gender': request.form.get('gender'),
            'dob': request.form.get('dob'),
            'birth_cert': request.form.get('birth_cert', '').strip(),
            'religion': request.form.get('religion', 'Christianity'),
            'category': request.form.get('category', 'Day'),
            'boarding': 'YES' if request.form.get('category') == 'Boarding' else 'NO',
            'student_group_id': request.form.get('student_group_id'),
            'route_id': request.form.get('route_id') if request.form.get('category') == 'Transport' else None,
            'alt_contact': request.form.get('alt_contact', '').strip(),
            'stream': class_data['stream_code'] if class_data else '',
        }
        academic_year_id = class_data['academic_year_id'] if class_data else None

        parent_data = {
            'pName': request.form.get('parent_name', '').strip(),
            'phone1': request.form.get('parent_phone', '').strip(),
            'email': request.form.get('parent_email', '').strip(),
            'nationalID': request.form.get('parent_id_no', '').strip(),
            'address': request.form.get('home_address', '').strip(),
            'hometown': request.form.get('residency', '').strip(),
        }

        try:
            if service.check_admno_exists(student_data['admno']):
                flash(f"Admission number {student_data['admno']} already exists!", "error")
            else:
                service.admit_student(student_data, parent_data, class_id, academic_year_id)

                # Handling Fees invoicing if transport
                if student_data['category'] == 'Transport' and student_data['route_id']:
                    route_data = service.get_transport_route_by_id(student_data['route_id'])
                    if route_data:
                        votehead_name = f"Transport-{route_data['name']}"
                        votehead_id = service.get_or_create_votehead(votehead_name, f"Charges for route: {route_data['name']}")
                        term_id = service.get_current_term_id()

                        if academic_year_id and term_id:
                            fees_service = FeesService(connection, school_id=service.school_id)
                            fees_service.invoice_student(
                                admno=student_data['admno'],
                                year_id=academic_year_id,
                                term_id=term_id,
                                structure_id=0,
                                user_id=session.get('userNo'),
                                custom_items=[{'votehead_id': votehead_id, 'votehead_name': votehead_name, 'amount': route_data['amount']}]
                            )

                flash(f"Student admitted successfully. ID: {student_data['admno']}", "success")
                return redirect(url_for('print_admission_form', admno=student_data['admno']))
        except Exception as e:
            flash(f"Error during admission: {str(e)}", "error")

    classes = service.get_classes()
    routes = service.get_transport_routes()
    fees_service = FeesService(connection, school_id=service.school_id)
    student_groups = fees_service.get_student_groups(active_only=True)
    connection.close()
    return render_template('student.html', classes=classes, routes=routes, student_groups=student_groups)

@students_bp.route('/admit/bulk', methods=['GET', 'POST'])
@admin_required
def bulk_admit_students():
    connection = get_db_connection()
    service = StudentService(connection)
    if request.method == 'POST':
        file = request.files.get('csv_file')
        if not file:
            flash("No file uploaded", "error")
            return redirect(url_for('students.bulk_admit_students'))

        try:
            stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
            reader = csv.DictReader(stream)
            students = [row for row in reader]
            classes = service.get_classes()
            connection.close()
            return render_template('bulk_admit_verify.html', students=students, classes=classes)
        except Exception as e:
            flash(f"Error reading file: {str(e)}", "error")

    classes = service.get_classes()
    connection.close()
    return render_template('bulk_admit.html', classes=classes)

@students_bp.route('/admit/bulk/process', methods=['POST'])
@admin_required
def finalize_bulk_import():
    data = request.form.to_dict(flat=False)
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        success_count, error_count = service.bulk_import_students(data)
        flash(f"Success: {success_count} students admitted. {error_count} skipped/failed.", "success" if error_count == 0 else "warning")
    except Exception as e:
        flash(f"Major error during processing: {str(e)}", "error")
    finally:
        connection.close()
    return redirect(url_for('students.students_list'))

@students_bp.route('/api/search_students')
@login_required
def api_search_students():
    q = request.args.get('query', '').strip()
    if not q:
        return jsonify([])
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        return jsonify(service.search_students(q))
    finally:
        connection.close()

@students_bp.route('/student/<int:admno>/edit', methods=['GET', 'POST'])
@admin_required
def edit_student(admno):
    connection = get_db_connection()
    service = StudentService(connection)

    if request.method == 'POST':
        class_id = request.form.get('class_id')
        class_data = service.get_class_details(class_id)
        student_data = {
            'fname': request.form.get('fname').strip(),
            'mname': request.form.get('mname', '').strip(),
            'lname': request.form.get('lname').strip(),
            'gender': request.form.get('gender'),
            'dob': request.form.get('dob'),
            'birth_cert': request.form.get('birth_cert', '').strip(),
            'religion': request.form.get('religion'),
            'category': request.form.get('category'),
            'boarding': 'YES' if request.form.get('category') == 'Boarding' else 'NO',
            'alt_contact': request.form.get('alt_contact', '').strip(),
            'email': request.form.get('email', '').strip(),
            'notes': request.form.get('notes', '').strip(),
            'stream': class_data['stream_code'] if class_data else '',
        }
        academic_year_id = class_data['academic_year_id'] if class_data else None

        parent_data = {
            'pName': request.form.get('parent_name', '').strip(),
            'phone1': request.form.get('parent_phone', '').strip(),
            'email': request.form.get('parent_email', '').strip(),
            'nationalID': request.form.get('parent_id_no', '').strip(),
            'address': request.form.get('home_address', '').strip(),
            'hometown': request.form.get('residency', '').strip(),
        }

        try:
            service.update_student(admno, student_data, parent_data, class_id, academic_year_id)
            flash("Student profile updated successfully.", "success")
            return redirect(url_for('students.student_profile', admno=admno))
        except Exception as e:
            flash(f"Error updating profile: {str(e)}", "error")

    student = service.get_student_by_admno(admno)
    if not student:
        connection.close()
        flash("Student not found!", "error")
        return redirect(url_for('students.students_list'))

    class_info = service.get_student_class_info(admno)
    current_class_id = class_info['classID'] if class_info else None
    classes = service.get_classes()
    connection.close()
    return render_template('edit_student.html', student=student, classes=classes, current_class_id=current_class_id)

@students_bp.route('/students')
@login_required
def students_list():
    connection = get_db_connection()
    service = StudentService(connection)
    term_cur, year_cur = get_current_term_and_year()
    q = request.args.get('q', '').strip()
    students = service.get_students_list(query=q if q else None, year_cur=year_cur)
    connection.close()
    return render_template('student_list.html', students=students, q=q)

@students_bp.route('/student/<int:admno>')
@login_required
def student_profile(admno):
    connection = get_db_connection()
    service = StudentService(connection)
    student = service.get_student_by_admno(admno)

    if not student:
        connection.close()
        flash("Student not found", "error")
        return redirect(url_for('students.students_list'))

    class_info = service.get_student_class_info(admno)
    if class_info:
        student.update(class_info)

    academic_history = service.get_student_academic_history(admno)
    issuance_history = service.get_uniform_history(admno)
    subjects = service.get_enrolled_subjects(admno)
    siblings = service.get_siblings(student.get('parent_phone'), admno) if student.get('parent_phone') else []

    ledger_summary = service.get_fee_summary(admno)
    total_billed = ledger_summary['total_billed'] or 0
    total_paid = ledger_summary['total_paid'] or 0
    outstanding_balance = ledger_summary['current_balance'] or 0
    fee_history = service.get_payment_history(admno)

    exam_summaries = service.get_exam_summaries(admno)
    exam_service = ExamManagementService(connection, service.school_id)
    for summary in exam_summaries:
        scale_id = exam_service.get_class_grading_scale_id(student.get('classID'))
        grade_rec = exam_service.get_grade_for_mark(summary['mean_mark'], scale_id)
        summary['mean_grade'] = grade_rec['grade'] if grade_rec else '-'

    connection.close()
    return render_template('student_profile.html',
                         student=student, academic_history=academic_history, issuance_history=issuance_history,
                         subjects=subjects, siblings=siblings, fee_history=fee_history, exam_summaries=exam_summaries,
                         total_paid=total_paid, total_billed=total_billed, outstanding_balance=outstanding_balance)

@students_bp.route('/api/detect-siblings')
@login_required
def detect_siblings():
    phone = request.args.get('phone', '').strip()
    if not phone:
        return jsonify({'siblings': [], 'parent': None})
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        siblings, parent = service.get_parent_info_and_siblings_by_phone(phone)
        return jsonify({'siblings': siblings, 'parent': parent})
    finally:
        connection.close()

@students_bp.route('/api/search_parents')
@login_required
def search_parents():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        return jsonify(service.search_parents(q))
    finally:
        connection.close()

@students_bp.route('/student/<int:admno>/toggle_status', methods=['POST'])
@admin_required
def toggle_student_status(admno):
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        new_status = service.toggle_status(admno)
        if new_status is None:
            flash("Student not found", "error")
            return redirect(url_for('students.students_list'))
        flash(f"Student {'blocked' if new_status == 'YES' else 'unblocked'} successfully.", "success")
    except Exception as e:
        flash(f"Error updating status: {str(e)}", "error")
    finally:
        connection.close()
    return redirect(url_for('students.student_profile', admno=admno))

@students_bp.route('/student/<int:admno>/statement')
@login_required
def student_fee_statement(admno):
    connection = get_db_connection()
    fees_service = FeesService(connection, school_id=require_current_school_id())
    service = StudentService(connection)
    statement = fees_service.get_student_statement(admno)
    balance = fees_service.get_student_balance(admno)
    student = service.get_student_by_admno(admno)
    connection.close()
    return render_template('fee_statement.html', statement=statement, balance=balance, student=student)

@students_bp.route('/api/search_students_fees')
@login_required
def search_students_fees():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        return jsonify(service.search_students(q))
    except Exception:
        current_app.logger.exception('Bursar student lookup failed')
        return jsonify({
            'success': False,
            'message': 'Unable to search students. Please try again later.',
        }), 500
    finally:
        connection.close()

@students_bp.route('/admin/student_subjects_select', methods=['GET'])
@login_required
@admin_required
def student_subjects_select():
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        students = service.get_students_for_subject_enrollment()
        return render_template('student_subjects_select.html', students=students)
    finally:
        connection.close()

@students_bp.route('/admin/student/subjects/select', methods=['GET'])
@login_required
@admin_required
def select_student_for_subjects():
    q = request.args.get('q', '').strip()
    if not q:
        return render_template('enroll_student_subjects_select.html', students=[], q=q)
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        students = service.search_students_for_subjects(q)
        return render_template('enroll_student_subjects_select.html', students=students, q=q)
    finally:
        connection.close()

@students_bp.route('/admin/student/<int:student_id>/subjects', methods=['GET', 'POST'])
@login_required
@admin_required
def enroll_student_subjects(student_id):
    connection = get_db_connection()
    service = StudentService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)

    if request.method == 'POST':
        try:
            class_allocation_id = _required_int(request.form.get('class_allocation_id'), 'class_allocation_id')
            subject_ids = [_required_int(sid, 'subject_id') for sid in request.form.getlist('subject_ids')]
            class_service.enroll_student_in_subjects(class_allocation_id=class_allocation_id, subject_ids=subject_ids)
            flash('Student enrolled in subjects', 'success')
            return redirect(url_for('classes.manage_classes'))
        except ValueError as e:
            flash(f'Error enrolling student: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error enrolling student: {str(e)}', 'error')
        finally:
            connection.close()
        return redirect(url_for('students.students_list'))

    # GET
    try:
        allocation = service.get_current_allocation(student_id)
        if not allocation:
            flash('No current class allocation found', 'error')
            return redirect(url_for('students.students_list'))

        available_subjects = service.get_available_subjects_for_class(allocation['class_id'])
        enrolled_subject_ids = service.get_enrolled_subject_ids(allocation['id'])

        return render_template('enroll_student_subjects.html',
                             student_id=student_id,
                             allocation=allocation,
                             available_subjects=available_subjects,
                             enrolled_subject_ids=enrolled_subject_ids)
    finally:
        connection.close()

@students_bp.route('/api/class/<int:class_id>/add-students', methods=['POST'])
@login_required
@admin_required
def api_add_students(class_id):
    data = request.get_json(silent=True) or {}
    student_ids = data.get('student_ids')
    if not isinstance(student_ids, list) or not student_ids:
        return jsonify({'success': False, 'message': 'student_ids must be a non-empty list.'}), 400
    connection = get_db_connection()
    class_service = ClassManagementService(connection)
    try:
        count = class_service.allocate_students_to_class(class_id, [int(sid) for sid in student_ids])
        return jsonify({'success': True, 'message': f'Successfully added {count} students'})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

@students_bp.route('/api/student/<int:allocation_id>/subjects', methods=['GET'])
@login_required
@admin_required
def api_get_student_subjects(allocation_id):
    connection = get_db_connection()
    service = StudentService(connection)
    try:
        enrolled = service.get_enrolled_subject_ids(allocation_id)
        return jsonify({'success': True, 'enrolled_subject_ids': enrolled})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

@students_bp.route('/api/student/subjects/update', methods=['POST'])
@login_required
@admin_required
def api_update_student_subjects():
    data = request.get_json(silent=True) or {}
    if 'allocation_id' not in data:
        return jsonify({'success': False, 'message': 'allocation_id is required.'}), 400
    subject_ids = data.get('subject_ids')
    if not isinstance(subject_ids, list):
        return jsonify({'success': False, 'message': 'subject_ids must be a list.'}), 400
    connection = get_db_connection()
    class_service = ClassManagementService(connection)
    try:
        allocation_id = _required_int(data.get('allocation_id'), 'allocation_id')
        class_service.replace_student_subject_enrollments(allocation_id, [_required_int(sid, 'subject_id') for sid in subject_ids])
        return jsonify({'success': True, 'message': 'Student subjects updated successfully'})
    except (TypeError, ValueError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

@students_bp.route('/api/class/remove-student/<int:allocation_id>', methods=['POST'])
@login_required
@admin_required
def api_remove_student(allocation_id):
    connection = get_db_connection()
    class_service = ClassManagementService(connection)
    try:
        class_service.remove_student_from_class(allocation_id)
        return jsonify({'success': True, 'message': 'Student removed from class'})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()
@students_bp.route('/print_admission_form/<admno>')
@login_required
def print_admission_form(admno):
    """Generate printable admission form."""
    connection = get_db_connection()
    service = StudentService(connection)

    try:
        # 1. Fetch student and basic info
        student_res = service.get_admission_form_profile(admno)

        if not student_res:
            flash("Student not found", "error")
            return redirect(url_for('index'))

        # Helper for date conversion
        def to_date(date_val):
            if not date_val: return None
            if isinstance(date_val, (datetime, date)): return date_val
            try:
                return datetime.strptime(str(date_val), '%Y-%m-%d')
            except:
                try:
                    return datetime.strptime(str(date_val).split(' ')[0], '%Y-%m-%d')
                except:
                    return None

        # Map to template expectations
        student = {
            'admno': student_res['AdmNo'],
            'Fullname': student_res['Fullname'].strip().replace('  ', ' ') if student_res['Fullname'] else "Unnamed Student",
            'Sex': student_res['Sex'],
            'DOB': to_date(student_res['DoB']),
            'AdmissionDate': to_date(student_res['Date_Adm']),
            'CurrentClass': student_res['class_name'] or 'Not Assigned',
            'Stream': student_res['stream'],
            'Category': student_res['category'],
            'Nationality': student_res.get('Nationality', 'Kenyan')
        }

        # 2. Parent Info
        parent = service.get_parent_contact_for_student(admno, student_res['parentID'])

        # 3. Route Info
        route = None
        if student_res['route_name']:
            route = {
                'name': student_res['route_name'],
                'amount': student_res['route_amount']
            }

        # 4. Siblings
        siblings = []
        if student_res['parentID'] and str(student_res['parentID']) != '0':
            sib_res = service.get_sibling_profiles(student_res['parentID'], admno)
            for sib in sib_res:
                siblings.append({
                    'Fullname': sib['Fullname'].strip().replace('  ', ' ') if sib['Fullname'] else "Sibling",
                    'CurrentClass': sib['class_name'] or 'N/A'
                })

        current_year = datetime.now().year

        return render_template('print_admission_form.html',
                            student=student,
                            parent=parent or {},
                            route=route,
                            siblings=siblings,
                            current_year=current_year)
    finally:
        connection.close()
