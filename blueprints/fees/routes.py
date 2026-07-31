from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify, make_response, current_app
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from core.permissions import admin_required, login_required
from blueprints.fees.services import FeesService, FeesError
from blueprints.classes.services import ClassManagementService
import csv
import io

fees_bp = Blueprint('fees', __name__)


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


def _optional_int(value, field_name):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid integer.")


def _parse_decimal(value, field_name, default=None):
    if value in (None, ''):
        if default is not None:
            return Decimal(str(default))
        raise ValueError(f"{field_name} is required and must be a valid number.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")


def _build_fee_structure_items(votehead_ids, amounts):
    items = []
    for index, (votehead_id, amount) in enumerate(zip(votehead_ids, amounts), start=1):
        if amount in (None, ''):
            continue
        parsed_amount = _parse_decimal(amount, f'amount[{index}]')
        if parsed_amount > 0:
            items.append({'votehead_id': _required_int(votehead_id, f'votehead_id[{index}]'), 'amount': float(parsed_amount)})
    return items

def get_db_connection():
    from core.db import get_db_connection
    return get_db_connection()

def get_current_term_and_year():
    from core.helpers import get_current_term_and_year
    return get_current_term_and_year()

@fees_bp.route('/admin/fees')
@login_required
@admin_required
def fees_dashboard():
    connection = get_db_connection()
    service = FeesService(connection)

    today = datetime.now().date()
    dashboard_totals = service.get_dashboard_totals(today)
    connection.close()
    return render_template('fees_dashboard.html', **dashboard_totals)

@fees_bp.route('/admin/fees/reports/collection')
@login_required
@admin_required
def fees_collection_report():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-01'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        data = service.get_collection_summary(start_date, end_date)
        status_data = service.get_collection_status_summary(start_date, end_date)
        category_data = service.get_collection_category_summary(start_date, end_date)
        class_data = service.get_collection_class_summary(start_date, end_date)
        votehead_data = service.get_collection_votehead_summary(start_date, end_date)
        return render_template(
            'fees_collection_report.html', data=data, status_data=status_data, category_data=category_data,
            class_data=class_data, votehead_data=votehead_data,
            start_date=start_date, end_date=end_date,
        )
    finally:
        connection.close()


@fees_bp.route('/admin/fees/reports/revenue-analysis')
@login_required
@admin_required
def fee_revenue_analysis_report():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-01'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        records = service.get_fee_revenue_analysis(start_date, end_date)
        return render_template(
            'fee_revenue_analysis_report.html', records=records,
            start_date=start_date, end_date=end_date,
        )
    finally:
        connection.close()


@fees_bp.route('/admin/fees/reports/ledger-summary')
@login_required
@admin_required
def fee_ledger_summary_report():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-01'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        records = service.get_fee_ledger_summary(start_date, end_date)
        return render_template(
            'fee_ledger_summary_report.html', records=records,
            start_date=start_date, end_date=end_date,
        )
    finally:
        connection.close()

@fees_bp.route('/admin/fees/reports/receipt-lifecycle')
@login_required
@admin_required
def receipt_lifecycle_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    event_type = request.args.get('event_type')
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        records = service.get_receipt_lifecycle_register(start_date, end_date, event_type)
        return render_template(
            'receipt_lifecycle_report.html',
            records=records,
            start_date=start_date or '',
            end_date=end_date or '',
            event_type=event_type or '',
            event_types=('POSTED', 'PRINTED', 'REPRINTED', 'CANCELLED', 'TRANSFERRED', 'REPOSTED', 'ARCHIVED'),
        )
    finally:
        connection.close()

@fees_bp.route('/admin/fees/reports/reallocations')
@login_required
@admin_required
def fee_reallocation_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        records = service.get_reallocation_register(start_date, end_date)
        return render_template(
            'fee_reallocation_report.html',
            records=records,
            start_date=start_date or '',
            end_date=end_date or '',
        )
    finally:
        connection.close()

@fees_bp.route('/admin/fees/reports/invoice-replacements')
@login_required
@admin_required
def invoice_replacement_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        records = service.get_invoice_replacement_register(start_date, end_date)
        return render_template(
            'fee_invoice_replacement_report.html', records=records,
            start_date=start_date or '', end_date=end_date or '',
        )
    finally:
        connection.close()

@fees_bp.route('/admin/fees/reports/balances')
@login_required
@admin_required
def fee_balances_report():
    academic_year_id = request.args.get('academic_year_id')
    class_id = request.args.get('class_id')
    stream = request.args.get('stream')

    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)

    try:
        data = service.get_fee_balances_report(
            academic_year_id=int(academic_year_id) if academic_year_id else None,
            class_id=int(class_id) if class_id else None,
            stream=stream if stream else None
        )

        years = class_service.get_all_academic_years()
        classes = class_service.get_active_classes()
        streams = service.get_distinct_stream_codes()

        return render_template('report_fee_balances.html',
                             data=data, years=years, classes=classes, streams=streams,
                             academic_year_id=int(academic_year_id) if academic_year_id else None,
                             class_id=int(class_id) if class_id else None, stream=stream)
    finally:
        connection.close()

@fees_bp.route("/admin/fees/reports/aging")
@login_required
@admin_required
def fee_arrears_aging_report():
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        data = service.get_arrears_aging_report()
        return render_template("fees_aging_report.html", data=data)
    finally:
        connection.close()

@fees_bp.route('/admin/fees/voteheads', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_voteheads():
    connection = get_db_connection()
    service = FeesService(connection)

    if request.method == 'POST':
        try:
            service.create_votehead(
                name=_required_text(request.form.get('name'), 'name'),
                priority=_required_int(request.form.get('priority', 99), 'priority'),
                description=request.form.get('description', '').strip()
            )
            flash("Votehead created.", "success")
        except (ValueError, FeesError) as e:
            flash(str(e), "error")
        except Exception as e:
            flash(str(e), "error")

    voteheads = service.get_voteheads()
    connection.close()
    return render_template('manage_voteheads.html', voteheads=voteheads)

@fees_bp.route('/admin/fees/student_groups', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_student_groups():
    connection = get_db_connection()
    service = FeesService(connection)

    if request.method == 'POST':
        try:
            service.create_student_group(
                _required_text(request.form.get('name'), 'name'),
                (request.form.get('description') or '').strip(),
            )
            flash("Student Group created.", "success")
        except (ValueError, FeesError) as e:
            flash(f"Error: {str(e)}", "error")
        except Exception as e:
            flash(f"Error: {str(e)}", "error")

    student_groups = service.get_student_groups(active_only=False)
    connection.close()
    return render_template('manage_student_groups.html', student_groups=student_groups)

@fees_bp.route('/admin/fees/mpesa/reconcile')
@login_required
@admin_required
def fees_mpesa_reconcile():
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        report = service.get_mpesa_reconciliation_report()
        return render_template('mpesa_reconciliation.html', report=report)
    finally:
        connection.close()

@fees_bp.route('/api/fees/import-mpesa', methods=['POST'])
@login_required
@admin_required
def api_import_mpesa():
    file = request.files.get('file')
    if not file or not (file.filename or '').lower().endswith('.csv'):
        return jsonify({'success': False, 'message': 'Invalid file format. Upload CSV'}), 400

    transactions = []
    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        for row in csv_input:
            tx = {
                'transaction_no': row.get('Receipt No') or row.get('transaction_no'),
                'amount': Decimal((row.get('Paid In') or row.get('Amount', '0')).replace(',', '')),
                'sender_name': row.get('Details') or row.get('Sender Name', 'Unknown'),
                'sender_phone': row.get('Sender Phone', ''),
                'transaction_time': row.get('Completion Time') or row.get('transaction_time')
            }
            if tx['transaction_no']: transactions.append(tx)
    except (UnicodeDecodeError, csv.Error, InvalidOperation, AttributeError, TypeError, ValueError) as e:
        return jsonify({'success': False, 'message': f'Error parsing CSV: {str(e)}'}), 400

    if not transactions:
        return jsonify({'success': False, 'message': 'No valid transactions found in CSV.'}), 400

    connection = get_db_connection()
    service = FeesService(connection)
    try:
        summary = service.import_mpesa_statement(transactions)
        return jsonify({'success': True, 'summary': summary})
    except FeesError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

@fees_bp.route('/admin/fees/waivers')
@login_required
@admin_required
def fees_waiver_management():
    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    try:
        categories = service.get_waiver_categories()
        voteheads = service.get_voteheads()
        student_groups = service.get_student_groups()
        years = class_service.get_all_academic_years()
        recent_waivers = service.get_recent_waivers(limit=50)
        terms = service.get_recent_terms(limit=10)

        return render_template('fee_waiver_management.html',
                             categories=categories, voteheads=voteheads, student_groups=student_groups, years=years, terms=terms,
                             recent_waivers=recent_waivers)
    finally:
        connection.close()

@fees_bp.route('/admin/fees/reports/waivers')
@login_required
@admin_required
def fee_waiver_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status = request.args.get('status')
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        records = service.get_waiver_register(start_date, end_date, status)
        return render_template(
            'fee_waiver_report.html', records=records, start_date=start_date or '',
            end_date=end_date or '', status=status or '',
        )
    finally:
        connection.close()

@fees_bp.route('/fees/waiver/assign', methods=['POST'])
@login_required
@admin_required
def assign_waiver():
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        assignment = {
            'category_id': _required_int(request.form.get('category_id'), 'category_id'),
            'year_id': _required_int(request.form.get('year_id'), 'year_id'),
            'term_id': _required_int(request.form.get('term_id'), 'term_id'),
            'user_id': session.get('userNo'),
        }
        selected_voteheads = request.form.getlist('votehead_ids')
        if request.form.get('student_group_id'):
            if not selected_voteheads:
                raise ValueError('Select at least one votehead for a group waiver.')
            result = service.assign_waiver_to_student_group(
                student_group_id=_required_int(request.form.get('student_group_id'), 'student_group_id'),
                votehead_ids=[_required_int(votehead_id, 'votehead_id') for votehead_id in selected_voteheads],
                **assignment,
            )
            flash(f"Waiver assigned to {result['assigned_count']} eligible students.", "success")
        else:
            assignment['admno'] = _required_int(request.form.get('admno'), 'admno')
            if selected_voteheads:
                assignment['votehead_ids'] = [
                    _required_int(votehead_id, 'votehead_id') for votehead_id in selected_voteheads
                ]
            service.assign_waiver_to_student(**assignment)
            flash("Waiver assigned successfully.", "success")
    except ValueError as e:
        flash(str(e), "error")
    except FeesError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('fees.fees_waiver_management'))

@fees_bp.route('/fees/waiver/<int:waiver_id>/revoke', methods=['POST'])
@login_required
@admin_required
def revoke_waiver(waiver_id):
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        service.revoke_waiver(waiver_id, request.form.get('reason'), session.get('userNo'))
        flash('Waiver revoked and a debit adjustment was posted.', 'success')
    except FeesError as e:
        flash(str(e), 'error')
    finally:
        connection.close()
    return redirect(url_for('fees.fees_waiver_management'))

@fees_bp.route('/admin/fees/adjustments', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_fee_adjustments():
    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    try:
        if request.method == 'POST':
            service.create_account_adjustment(
                admno=_required_int(request.form.get('admno'), 'admno'),
                adjustment_type=_required_text(request.form.get('adjustment_type'), 'adjustment_type'),
                votehead_id=_required_int(request.form.get('votehead_id'), 'votehead_id'),
                amount=_parse_decimal(request.form.get('amount'), 'amount'),
                year_id=_required_int(request.form.get('year_id'), 'year_id'),
                term_id=_required_int(request.form.get('term_id'), 'term_id'),
                effective_date=_required_text(request.form.get('effective_date'), 'effective_date'),
                reason=_required_text(request.form.get('reason'), 'reason'),
                supporting_reference=_required_text(request.form.get('supporting_reference'), 'supporting_reference'),
                user_id=session['userNo'],
            )
            flash('Account adjustment posted.', 'success')
            return redirect(url_for('fees.manage_fee_adjustments'))
        return render_template(
            'manage_fee_adjustments.html',
            voteheads=service.get_voteheads(), years=class_service.get_all_academic_years(),
            terms=service.get_recent_terms(), now=datetime.now(),
        )
    except (ValueError, FeesError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('fees.manage_fee_adjustments'))
    finally:
        connection.close()

@fees_bp.route('/admin/fees/structures', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_fee_structures():
    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)

    if request.method == 'POST':
        try:
            votehead_ids = request.form.getlist('votehead_id')
            amounts = request.form.getlist('amount')
            items = _build_fee_structure_items(votehead_ids, amounts)

            if not items: flash("Enter at least one votehead amount.", "error")
            else:
                results = service.create_bulk_fee_structures(
                    year_id=_required_int(request.form.get('year_id'), 'year_id'),
                    term_id=_required_int(request.form.get('term_id'), 'term_id'),
                    class_groups=request.form.getlist('class_groups'),
                    categories=request.form.getlist('categories'),
                    items=items,
                    user_id=session['userNo'],
                    class_ids=[_required_int(cid, 'specific_classes') for cid in request.form.getlist('specific_classes')] if request.form.getlist('specific_classes') else None
                )
                flash(f"{results['success']} structures created, {results['skipped']} skipped.", "success")
        except (ValueError, FeesError) as e:
            flash(str(e), "error")
        except Exception as e:
            flash(str(e), "error")

    structures_raw = service.get_fee_structures()
    # Grouping logic remains in route as it's purely for display
    grouped_structures = {}
    for s in structures_raw:
        label = s['specific_class_name'] if s['class_id'] else s['class_group_code']
        key = (s['academic_year_id'], label, s['student_category'])
        if key not in grouped_structures:
            grouped_structures[key] = {
                'id': s['id'], 'year_name': s['year_name'], 'academic_year_id': s['academic_year_id'],
                'label': label, 'class_id': s['class_id'], 'class_group_code': s['class_group_code'],
                'student_category': s['student_category'], 'terms': [], 'total_year': 0
            }
        grouped_structures[key]['terms'].append(s['term_number'])
        grouped_structures[key]['total_year'] += float(s['total_amount'])

    structures = sorted(grouped_structures.values(), key=lambda x: (x['year_name'], x['label']), reverse=True)

    terms = service.get_recent_terms()

    context = {
        'structures': structures,
        'voteheads': service.get_voteheads(),
        'years': class_service.get_all_academic_years(),
        'terms': terms,
        'class_groups': [{'code': k, 'name': v['name']} for k, v in class_service.get_class_groups().items()],
        'all_classes': class_service.get_active_classes(),
        'categories': ['Day', 'Boarding', 'Normal', 'Special', 'Transport', 'all']
    }
    connection.close()
    return render_template('manage_fee_structures.html', **context)

@fees_bp.route('/admin/fees/structures/edit/<int:structure_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_fee_structure(structure_id):
    connection = get_db_connection()
    service = FeesService(connection)

    if request.method == 'POST':
        try:
            votehead_ids = request.form.getlist('votehead_id')
            amounts = request.form.getlist('amount')
            items = _build_fee_structure_items(votehead_ids, amounts)
            service.update_fee_structure(structure_id, items, session['userNo'])
            flash("Fee structure updated successfully.", "success")
            return redirect(url_for('fees.manage_fee_structures'))
        except (ValueError, FeesError) as e:
            flash(str(e), "error")
        except Exception as e:
            flash(str(e), "error")

    structure = service.get_fee_structure_details(structure_id)
    if not structure:
        flash("Structure not found.", "error")
        connection.close()
        return redirect(url_for('fees.manage_fee_structures'))

    voteheads = service.get_voteheads()
    amount_map = {item['votehead_id']: item['amount'] for item in structure['items']}
    connection.close()
    return render_template('edit_fee_structure.html', s=structure, voteheads=voteheads, amount_map=amount_map)

@fees_bp.route('/admin/fees/structures/delete/<int:structure_id>', methods=['POST'])
@login_required
@admin_required
def delete_fee_structure(structure_id):
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        service.delete_fee_structure(structure_id)
        flash("Fee structure deleted.", "info")
    except FeesError as e:
        flash(str(e), "error")
    except Exception as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('fees.manage_fee_structures'))

@fees_bp.route('/admin/fees/structures/card')
@login_required
def fee_structure_card():
    year_id = request.args.get('year_id')
    group_code = request.args.get('group_code')
    class_id = request.args.get('class_id')
    category = request.args.get('category', 'Day')

    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)

    if not year_id:
        ay = class_service.get_current_academic_year()
        year_id = ay['id'] if ay else None

    terms = service.get_terms_for_academic_year(year_id)

    voteheads = service.get_voteheads()
    data = {v['id']: {'name': v['name'], 'terms': {t['id']: 0 for t in terms}, 'yearly': 0} for v in voteheads}

    is_locked = False
    items = service.get_structure_card_items(year_id, category, class_id=int(class_id) if class_id else None, group_code=group_code)
    for item in items:
        if item['votehead_id'] in data:
            data[item['votehead_id']]['terms'][item['term_id']] = item['amount']
            data[item['votehead_id']]['yearly'] += item['amount']
            if item.get('is_locked'):
                is_locked = True

    filtered_data = {k: v for k, v in data.items() if v['yearly'] > 0}
    all_classes = class_service.get_active_classes()
    selected_label = group_code
    if class_id:
        sel_c = next((c for c in all_classes if str(c['classID']) == str(class_id)), None)
        selected_label = sel_c['display_name'] if sel_c else "Class"

    connection.close()
    return render_template('fee_structure_card.html',
                         data=filtered_data, terms=terms, years=class_service.get_all_academic_years(),
                         class_groups=class_service.get_class_groups(), all_classes=all_classes,
                         year_id=year_id, group_code=group_code, class_id=class_id, category=category,
                         selected_label=selected_label, is_locked=is_locked)

@fees_bp.route('/admin/fees/structures/download')
@login_required
def fee_structure_download():
    # Similar to card, but for PDF generation. Keep logic here but call a helper if possible.
    return "PDF generation placeholder"

@fees_bp.route('/admin/fees/structures/overview')
@login_required
@admin_required
def fee_structures_overview():
    year_id = request.args.get('year_id')
    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    if not year_id:
        ay = class_service.get_current_academic_year()
        year_id = ay['id'] if ay else None

    terms = service.get_terms_for_academic_year(year_id)
    rows = service.get_structure_overview_rows(year_id)

    years = class_service.get_all_academic_years()
    term_ids = [t['id'] for t in terms]
    matrix = {}
    for r in rows:
        label = r['specific_class_name'] if r['class_id'] else r['class_group_code']
        key = (label, r['student_category'], r['class_group_code'], r['class_id'])
        if key not in matrix: matrix[key] = {tid: 0 for tid in term_ids}
        matrix[key][r['term_id']] = r['total_amount']

    connection.close()
    return render_template('fee_structure_overview.html', year_id=year_id, years=years, terms=terms, matrix=matrix)

@fees_bp.route('/admin/fees/structures/copy', methods=['POST'])
@login_required
@admin_required
def copy_fee_structure():
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        service.copy_fee_structure(
            _required_int(request.form.get('from_structure_id'), 'from_structure_id'),
            _required_int(request.form.get('target_year_id'), 'target_year_id'),
            _required_int(request.form.get('target_term_id'), 'target_term_id'),
            session['userNo'],
        )
        flash("Fee structure copied successfully.", "success")
    except (ValueError, FeesError) as e:
        flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(url_for('fees.manage_fee_structures'))

@fees_bp.route('/admin/fees/structures/yearly/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_yearly_fee_structure_route():
    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    if request.method == 'POST':
        try:
            year_id = _required_int(request.form.get('year_id'), 'year_id')
            class_id = _optional_int(request.form.get('class_id'), 'class_id')
            voteheads = service.get_voteheads()
            term_amounts = {v['id']: {f't{t}': request.form.get(f"v_{v['id']}_t{t}", 0) for t in [1,2,3]} for v in voteheads}
            service.create_yearly_fee_structure(year_id, class_id, request.form.get('group_code'), request.form.get('category'), term_amounts, session['userNo'])
            flash("Yearly fee structure updated.", "success")
        except (ValueError, FeesError) as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")
        finally:
            connection.close()
        return redirect(url_for('fees.fee_structures_overview'))

    context = {
        'years': class_service.get_all_academic_years(),
        'classes': class_service.get_active_classes(),
        'student_groups': service.get_student_groups(),
        'voteheads': service.get_voteheads()
    }
    connection.close()
    return render_template('create_yearly_fee_structure.html', **context)

@fees_bp.route('/admin/fees/structures/lock/<int:structure_id>', methods=['POST'])
@login_required
@admin_required
def toggle_structure_lock(structure_id):
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        service.toggle_structure_lock(structure_id, request.form.get('lock') == '1')
        flash("Structure status updated.", "success")
    except FeesError as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(request.referrer or url_for('fees.fee_structures_overview'))

@fees_bp.route('/admin/fees/collect', methods=['GET', 'POST'])
@login_required
@admin_required
def collect_fees():
    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)

    if request.method == 'POST':
        # Check if caller wants AJAX response
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
        try:
            if request.is_json:
                data = request.get_json() or {}
                admno_val = data.get('admno')
                amount_val = data.get('amount')
                mode_val = data.get('mode')
                reference_val = data.get('reference')
                bank_val = data.get('bank')
                date_val = data.get('date')
                year_id_val = data.get('year_id')
                term_id_val = data.get('term_id')
                allocation_mode = data.get('allocation_mode', 'AUTOMATIC')
                manual_allocations = data.get('manual_allocations')
            else:
                admno_val = request.form.get('admno')
                amount_val = request.form.get('amount')
                mode_val = request.form.get('mode')
                reference_val = request.form.get('reference')
                bank_val = request.form.get('bank')
                date_val = request.form.get('date')
                year_id_val = request.form.get('year_id')
                term_id_val = request.form.get('term_id')
                allocation_mode = request.form.get('allocation_mode', 'AUTOMATIC')
                manual_allocations = None

            if manual_allocations is not None and not isinstance(manual_allocations, list):
                raise ValueError('manual_allocations must be a list.')

            result = service.record_payment(
                admno=_required_int(admno_val, 'admno'),
                amount=_parse_decimal(amount_val, 'amount'),
                mode=mode_val,
                reference=reference_val.strip() if reference_val else '',
                bank=bank_val.strip() if bank_val else '',
                date=date_val,
                year_id=_required_int(year_id_val, 'year_id'),
                term_id=_required_int(term_id_val, 'term_id'),
                user_id=session['userNo'],
                allocation_mode=allocation_mode,
                manual_allocations=manual_allocations,
            )

            if is_ajax:
                return jsonify({
                    'success': True,
                    'message': f"Payment received. Receipt No: {result['receipt_no']}",
                    'receipt_no': result['receipt_no'],
                    'payment_id': result['payment_id'],
                    'balance': float(result['balance']) if result['balance'] is not None else 0.0,
                    'allocations': result.get('allocations', []),
                })

            flash(f"Payment received. Receipt No: {result['receipt_no']}", "success")
            return redirect(url_for('fees.print_fee_receipt', payment_id=result['payment_id']))
        except (ValueError, FeesError) as e:
            if is_ajax:
                return jsonify({'success': False, 'message': str(e)}), 400
            flash(str(e), "error")
        except Exception as e:
            if is_ajax:
                return jsonify({'success': False, 'message': str(e)}), 500
            flash(str(e), "error")

    try:
        years = class_service.get_all_academic_years()
        terms = service.get_recent_terms()
        curr_term_id = service.get_current_term_id()
        payment_mode_accounts = service.get_payment_mode_receiving_account_labels()
        connection.close()
        return render_template('collect_fees.html', years=years, terms=terms, current_year_id=next((y['id'] for y in years if y['is_current']), None),
                     current_term_id=curr_term_id, now=datetime.now(), payment_mode_accounts=payment_mode_accounts)
    except Exception:
        current_app.logger.exception("Failed to load bursar workspace")
        try:
            connection.close()
        except Exception:
            pass
        return "Unable to load the bursar workspace. Please try again later.", 500

@fees_bp.route('/admin/fees/bulk_post', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_post_fees():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file: flash('Upload a CSV file.', 'error'); return redirect(url_for('fees.bulk_post_fees'))
        connection = get_db_connection(); service = FeesService(connection); posted = 0; row_errors = []
        try:
            stream = io.TextIOWrapper(file.stream, encoding='utf-8')
            reader = csv.DictReader(stream)
            for line_number, row in enumerate(reader, start=2):
                try:
                    service.record_payment(
                        _required_int(row.get('admno'), 'admno'),
                        _parse_decimal(row.get('amount'), 'amount'),
                        (row.get('mode') or 'CASH').strip() or 'CASH',
                        (row.get('reference') or '').strip(),
                        (row.get('bank') or '').strip(),
                        (row.get('date') or datetime.now().strftime('%Y-%m-%d')).strip(),
                        _required_int(row.get('year_id'), 'year_id'),
                        _required_int(row.get('term_id'), 'term_id'),
                        session['userNo'],
                    )
                    posted += 1
                except (ValueError, FeesError) as e:
                    row_errors.append(f"Row {line_number}: {str(e)}")
                except Exception as e:
                    row_errors.append(f"Row {line_number}: {str(e)}")
            if posted:
                flash(f"Bulk posting complete. Posted: {posted}", 'success')
            if row_errors:
                preview = '; '.join(row_errors[:5])
                if len(row_errors) > 5:
                    preview = f"{preview}; and {len(row_errors) - 5} more"
                flash(f"Bulk posting encountered {len(row_errors)} row error(s). {preview}", 'error')
            if not posted and not row_errors:
                flash('No rows found in CSV.', 'error')
        except (UnicodeDecodeError, csv.Error) as e:
            flash(f'Error parsing CSV: {str(e)}', 'error')
        finally: connection.close()
        return redirect(url_for('fees.fees_dashboard'))
    return render_template('bulk_post_fees.html')

@fees_bp.route('/admin/fees/bulk_debit', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_debit_term():
    connection = get_db_connection()
    service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    if request.method == 'POST':
        try:
            count = service.bulk_invoice_classes(
                [_required_int(cid, 'class_ids') for cid in request.form.getlist('class_ids')],
                _required_int(request.form.get('year_id'), 'year_id'),
                _required_int(request.form.get('term_id'), 'term_id'),
                session['userNo'],
            )
            flash(f"Debited term fees for {count} students.", 'success')
        except (ValueError, FeesError) as e:
            flash(str(e), 'error')
        finally:
            connection.close()
        return redirect(url_for('fees.bulk_debit_term'))

    terms = service.get_recent_terms()
    context = {'years': class_service.get_all_academic_years(), 'terms': terms, 'classes': class_service.get_active_classes()}
    connection.close()
    return render_template('bulk_debit_term.html', **context)

@fees_bp.route('/api/fees/recent_payments')
@login_required
def api_recent_payments():
    admno = request.args.get('admno')
    if not admno: return jsonify([])
    connection = get_db_connection(); service = FeesService(connection)
    try: return jsonify(service.get_recent_payments(int(admno)))
    finally: connection.close()

@fees_bp.route('/api/fees/statement')
@login_required
def api_statement():
    admno = request.args.get('admno')
    if not admno: return jsonify([])
    connection = get_db_connection(); service = FeesService(connection)
    try:
        return jsonify(service.get_student_statement(_required_int(admno, 'admno'), _optional_int(request.args.get('year_id'), 'year_id')))
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    finally: connection.close()

@fees_bp.route('/api/fees/statement-summary')
@login_required
def api_statement_summary():
    admno = request.args.get('admno')
    if not admno:
        return jsonify([])
    connection = get_db_connection(); service = FeesService(connection)
    try:
        return jsonify(service.get_student_statement_summary(
            _required_int(admno, 'admno'),
            _optional_int(request.args.get('year_id'), 'year_id'),
        ))
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    finally:
        connection.close()

@fees_bp.route('/api/fees/category-change-preflight')
@login_required
@admin_required
def api_category_change_preflight():
    try:
        admno = _required_int(request.args.get('admno'), 'admno')
        year_id = _required_int(request.args.get('year_id'), 'year_id')
        term_id = _required_int(request.args.get('term_id'), 'term_id')
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        return jsonify({'success': True, **service.get_category_change_preflight(admno, year_id, term_id)})
    except FeesError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    finally:
        connection.close()

@fees_bp.route('/admin/fees/student/<int:admno>/replace-category-invoice', methods=['POST'])
@login_required
@admin_required
def replace_category_invoice(admno):
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        result = service.replace_category_invoice(
            admno=admno,
            year_id=_required_int(request.form.get('year_id'), 'year_id'),
            term_id=_required_int(request.form.get('term_id'), 'term_id'),
            new_category=_required_text(request.form.get('category'), 'category'),
            new_student_group_id=_optional_int(request.form.get('student_group_id'), 'student_group_id'),
            reason=_required_text(request.form.get('reason'), 'reason'),
            user_id=session['userNo'],
        )
        return jsonify({'success': True, **result})
    except (ValueError, FeesError) as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    finally:
        connection.close()

@fees_bp.route('/api/fees/payment-duplicate')
@login_required
def api_payment_duplicate():
    try:
        mode = _required_text(request.args.get('mode'), 'mode').upper()
        reference = _required_text(request.args.get('reference'), 'reference')
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    connection = get_db_connection()
    service = FeesService(connection)
    try:
        payment = service.find_duplicate_payment(mode, reference)
        if not payment:
            return jsonify({'duplicate': False})
        return jsonify({
            'duplicate': True,
            'payment': {
                'id': payment['id'],
                'admno': payment['admno'],
                'amount': float(payment['amount']),
                'payment_date': payment['payment_date'].isoformat() if hasattr(payment['payment_date'], 'isoformat') else payment['payment_date'],
                'receipt_no': payment.get('receipt_no'),
            },
        })
    finally:
        connection.close()

@fees_bp.route('/api/fees/allocation-templates', methods=['GET', 'POST'])
@login_required
def api_allocation_templates():
    if request.method == 'POST' and not session.get('is_admin', False):
        return jsonify({'success': False, 'message': 'Administrator access is required.'}), 403

    connection = get_db_connection()
    service = FeesService(connection)
    try:
        if request.method == 'GET':
            templates = service.get_allocation_templates()
            return jsonify({'templates': templates})

        data = request.get_json() or {}
        template = service.create_allocation_template(
            data.get('name'),
            data.get('allocations'),
            session['userNo'],
        )
        return jsonify({'success': True, 'template': template}), 201
    except (ValueError, FeesError) as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    finally:
        connection.close()

@fees_bp.route('/api/fees/student-context')
@login_required
def api_fees_student_context():
    admno_param = request.args.get('admno')
    if not admno_param:
        return jsonify({'success': False, 'message': 'admno is required'}), 400
    try:
        admno = int(admno_param)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid admno format'}), 400

    connection = get_db_connection()
    fees_service = FeesService(connection)
    from blueprints.students.services import StudentService
    student_service = StudentService(connection, school_id=fees_service.school_id)
    class_service = ClassManagementService(connection, school_id=fees_service.school_id)

    try:
        student = student_service.get_student_by_admno(admno)
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404

        class_info = student_service.get_student_class_info(admno)
        balance = fees_service.get_student_balance(admno)
        recent_receipts = fees_service.get_recent_payments(admno, limit=5)
        outstanding_voteheads = fees_service.get_outstanding_voteheads(admno)
        
        # Get active term / structure totals
        term_id = fees_service.get_current_term_id()
        structure_items = []
        term_summary = None
        term_invoices = []
        if term_id:
            structure_items = fees_service.get_student_fee_structure(admno, term_id)
            term_summary = fees_service.get_student_term_summary(admno, term_id)
            term_invoices = fees_service.get_student_term_invoices(admno, term_id)

        financial_alerts = []
        balance_value = float(balance) if balance is not None else 0.0
        if student.get('blocked') == 'YES':
            financial_alerts.append({
                'code': 'BLOCKED_ACCOUNT',
                'severity': 'warning',
                'message': 'This student account is blocked. Confirm the account status before posting.',
            })
        if balance_value < 0:
            financial_alerts.append({
                'code': 'CREDIT_BALANCE',
                'severity': 'info',
                'message': f'This student has a credit balance of KES {abs(balance_value):,.2f}.',
            })
        elif balance_value == 0:
            financial_alerts.append({
                'code': 'FULLY_PAID',
                'severity': 'info',
                'message': 'This student has no outstanding ledger balance.',
            })

        # Standardize student name & contact info
        student_context = {
            'success': True,
            'admno': student.get('AdmNo'),
            'first_name': student.get('FName', ''),
            'middle_name': student.get('MName', ''),
            'success_name': student.get('SName', ''),
            'full_name': f"{student.get('FName', '')} {student.get('MName', '') or ''} {student.get('SName', '')}".replace('  ', ' ').strip(),
            'gender': student.get('Sex', 'N/A'),
            'category': student.get('category', 'Day'),
            'blocked': student.get('blocked', 'NO'),
            'parent_name': student.get('parent_name', 'N/A'),
            'parent_phone': student.get('parent_phone', 'N/A'),
            'parent_email': student.get('parent_email', 'N/A'),
            'home_address': student.get('home_address', 'N/A'),
            'residency': student.get('residency', 'N/A'),
            'class_name': class_info.get('class_name') if class_info else 'Not Assigned',
            'class_group': class_info.get('class_group') if class_info else 'N/A',
            'stream': (class_info or {}).get('stream') or student.get('stream') or 'N/A',
            'student_group': student.get('student_group_name') or 'Not Assigned',
            'outstanding_balance': balance_value,
            'recent_receipts': recent_receipts,
            'financial_alerts': financial_alerts,
            'outstanding_voteheads': [
                {
                    'votehead_id': item['votehead_id'],
                    'votehead_name': item['votehead_name'],
                    'amount': float(item['outstanding']),
                    'priority': item['priority'],
                } for item in outstanding_voteheads
            ],
            'structure_items': [
                {
                    'votehead_id': item['votehead_id'],
                    'votehead_name': item['votehead_name'],
                    'amount': float(item['amount']),
                    'priority': item['priority']
                } for item in structure_items
            ],
            'term_id': term_id,
            'term_summary': (
                {
                    'charges': float(term_summary['charges']),
                    'debits': float(term_summary['debits']),
                    'payments': float(term_summary['payments']),
                    'credits': float(term_summary['credits']),
                    'net_due': float(term_summary['net_due']),
                } if term_summary else None
            ),
            'term_invoices': [
                {
                    'reference_no': invoice['reference_no'],
                    'issued_on': invoice['issued_on'].isoformat() if hasattr(invoice['issued_on'], 'isoformat') else invoice['issued_on'],
                    'amount': float(invoice['amount']),
                    'item_count': invoice['item_count'],
                } for invoice in term_invoices
            ],
        }

        # Resolve some dummy values mock allocation preview
        # Prepopulate live allocation previews
        allocated = []
        remaining = float(balance) if balance is not None else 0.0
        student_context['projected_balance'] = remaining
        
        return jsonify(student_context)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

@fees_bp.route('/admin/fees/receipt/<int:payment_id>')
@login_required
def print_fee_receipt(payment_id):
    connection = get_db_connection(); service = FeesService(connection)
    try:
        receipt = service.get_receipt_details(payment_id)
        if not receipt:
            flash("Receipt not found.", "error")
            return redirect(url_for('fees.fees_dashboard'))

        # Normalize optional keys used in templates to avoid render-time KeyError.
        receipt.setdefault('MName', '')
        receipt.setdefault('display_name', receipt.get('class_name') or 'N/A')
        receipt.setdefault('reference_no', receipt.get('reference_number') or '')
        receipt.setdefault('allocations', [])
        receipt['Fullname'] = f"{receipt['FName']} {receipt.get('MName', '') or ''} {receipt['SName']}".strip().replace('  ', ' ')
        service.record_receipt_print(payment_id, session['userNo'])

        return render_template(
            'print_fee_receipt.html',
            receipt=receipt,
            allocations=receipt.get('allocations', []),
            now=datetime.now(),
        )
    except Exception as e:
        current_app.logger.exception("Failed to render fee receipt %s", payment_id)
        flash(f"Receipt rendering failed: {str(e)}", "error")
        return redirect(url_for('fees.fees_dashboard'))
    finally: connection.close()

@fees_bp.route('/admin/fees/receipts')
@login_required
@admin_required
def fee_receipts_register():
    connection = get_db_connection(); service = FeesService(connection)
    try:
        records = service.get_receipts_register(
            request.args.get('start_date'), request.args.get('end_date'),
            _optional_int(request.args.get('admno'), 'admno'), request.args.get('mode'),
            request.args.get('q'), request.args.get('status'),
        )
    except ValueError as e:
        flash(str(e), 'error')
        records = []
    connection.close()
    return render_template('fee_receipts_register.html', records=records, filters=request.args)

@fees_bp.route('/admin/fees/receipt/<int:payment_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_fee_receipt(payment_id):
    connection = get_db_connection(); service = FeesService(connection)
    if request.method == 'POST':
        try:
            service.update_payment_details(payment_id, request.form.get('mode'), request.form.get('reference'), request.form.get('bank'), request.form.get('date'), session['userNo'])
            flash("Receipt updated.", "success")
        except FeesError as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")
        finally:
            connection.close()
        return redirect(url_for('fees.fee_receipts_register'))
    receipt = service.get_receipt_details(payment_id)
    connection.close()
    return render_template('edit_fee_receipt.html', receipt=receipt)

@fees_bp.route('/admin/fees/receipt/<int:payment_id>/void', methods=['POST'])
@login_required
@admin_required
def void_fee_receipt(payment_id):
    connection = get_db_connection(); service = FeesService(connection)
    try:
        service.void_receipt(payment_id, session['userNo'], request.form.get('reason', 'System cancellation'))
        flash("Receipt voided.", "success")
    except FeesError as e: flash(str(e), "error")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(request.referrer or url_for('fees.fee_receipts_register'))

@fees_bp.route('/admin/fees/receipt/<int:payment_id>/lifecycle')
@login_required
@admin_required
def receipt_lifecycle(payment_id):
    connection = get_db_connection(); service = FeesService(connection)
    try:
        receipt = service.get_receipt_details(payment_id)
        if not receipt:
            flash('Receipt not found.', 'error')
            return redirect(url_for('fees.fee_receipts_register'))
        return render_template(
            'fee_receipt_lifecycle.html',
            receipt=receipt,
            events=service.get_receipt_lifecycle(payment_id),
            now=datetime.now(),
        )
    except Exception:
        current_app.logger.exception('Failed to load receipt lifecycle for payment %s', payment_id)
        flash('Receipt lifecycle could not be loaded.', 'error')
        return redirect(url_for('fees.fee_receipts_register'))
    finally:
        connection.close()

@fees_bp.route('/admin/fees/receipt/<int:payment_id>/repost', methods=['POST'])
@login_required
@admin_required
def repost_fee_receipt(payment_id):
    connection = get_db_connection(); service = FeesService(connection)
    try:
        result = service.repost_cancelled_receipt(
            payment_id=payment_id,
            new_reference=_required_text(request.form.get('reference'), 'reference'),
            posting_date=request.form.get('posting_date') or datetime.now().strftime('%Y-%m-%d'),
            user_id=session['userNo'],
        )
        flash(f"Receipt reposted as {result['receipt_no']}.", 'success')
        return redirect(url_for('fees.print_fee_receipt', payment_id=result['payment_id']))
    except (ValueError, FeesError) as e:
        flash(str(e), 'error')
        return redirect(url_for('fees.receipt_lifecycle', payment_id=payment_id))
    finally:
        connection.close()

@fees_bp.route('/admin/fees/receipt/<int:payment_id>/archive', methods=['POST'])
@login_required
@admin_required
def archive_fee_receipt(payment_id):
    connection = get_db_connection(); service = FeesService(connection)
    try:
        service.archive_receipt(payment_id, _required_text(request.form.get('reason'), 'reason'), session['userNo'])
        flash('Receipt archived.', 'success')
    except (ValueError, FeesError) as exc:
        flash(str(exc), 'error')
    finally:
        connection.close()
    return redirect(url_for('fees.receipt_lifecycle', payment_id=payment_id))

@fees_bp.route('/api/mpesa/callback', methods=['POST'])
def mpesa_callback():
    # logic from app.py
    return jsonify({'success': True})

@fees_bp.route('/admin/fees/rollup', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_fees_rollup():
    connection = get_db_connection(); service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    if request.method == 'POST':
        try:
            count = service.carry_forward_balances(
                _required_int(request.form.get('old_year_id'), 'old_year_id'),
                _required_int(request.form.get('new_year_id'), 'new_year_id'),
                1,
                session['userNo'],
            )
            flash(f'Successfully rolled up balances for {count} students.', 'success')
        except (ValueError, FeesError) as e: flash(f'Error: {str(e)}', 'error')
        except Exception as e: flash(f'Error: {str(e)}', 'error')
    years = class_service.get_all_academic_years()
    connection.close()
    return render_template('admin_rollup.html', years=years)

@fees_bp.route('/admin/fees/reallocate', methods=['GET', 'POST'])
@login_required
@admin_required
def reallocate_fee_payment():
    if request.method == 'POST':
        connection = get_db_connection(); service = FeesService(connection)
        try:
            service.reallocate_payment(
                _required_text(request.form.get('reference_no'), 'reference_no'),
                _required_int(request.form.get('from_admno'), 'from_admno'),
                _required_int(request.form.get('to_admno'), 'to_admno'),
                session['userNo'],
                _required_text(request.form.get('reason'), 'reason'),
            )
            flash("Payment reallocated.", "success")
        except (ValueError, FeesError) as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")
        finally: connection.close()
    return render_template('payment_reallocation.html')

@fees_bp.route('/admin/fees/invoice', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_invoice():
    connection = get_db_connection(); service = FeesService(connection)
    class_service = ClassManagementService(connection, school_id=service.school_id)
    if request.method == 'POST':
        try:
            vh = request.form.get('specific_votehead_id'); amt = request.form.get('specific_amount')
            count = service.bulk_invoice_classes(
                [_required_int(cid, 'class_ids') for cid in request.form.getlist('class_ids')],
                _required_int(request.form.get('year_id'), 'year_id'),
                _required_int(request.form.get('term_id'), 'term_id'),
                session['userNo'],
                specific_votehead_id=_optional_int(vh, 'specific_votehead_id'),
                specific_amount=_parse_decimal(amt, 'specific_amount') if amt else None,
            )
            flash(f"Bulk invoicing complete. {count} students invoiced.", "success")
        except (ValueError, FeesError) as e: flash(str(e), "error")
        except Exception as e: flash(str(e), "error")

    terms = service.get_recent_terms()
    context = {'years': class_service.get_all_academic_years(), 'terms': terms, 'classes': class_service.get_active_classes(), 'voteheads': service.get_voteheads()}
    connection.close()
    return render_template('bulk_invoice.html', **context)
