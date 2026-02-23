from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, jsonify, make_response
from datetime import datetime, timedelta
from decimal import Decimal
from core.permissions import admin_required, login_required
from blueprints.fees.services import FeesService, FeesError
from blueprints.classes.services import ClassManagementService
import csv
import io

fees_bp = Blueprint('fees', __name__)

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

    with connection.cursor() as cursor:
        school_id = service.school_id
        cursor.execute("SELECT SUM(amount) as total FROM fee_payments WHERE payment_date = %s AND status = 'COMPLETED' AND school_id = %s", (today, school_id))
        today_total = cursor.fetchone()['total'] or 0

        cursor.execute("SELECT SUM(amount) as total FROM fee_payments WHERE MONTH(payment_date) = MONTH(%s) AND YEAR(payment_date) = YEAR(%s) AND status = 'COMPLETED' AND school_id = %s", (today, today, school_id))
        monthly_total = cursor.fetchone()['total'] or 0

        cursor.execute("""
            SELECT SUM(fl.balance_after) as total
            FROM fee_ledger fl
            WHERE fl.school_id = %s
              AND fl.id IN (SELECT MAX(id) FROM fee_ledger WHERE school_id = %s GROUP BY admno)
        """, (school_id, school_id))
        total_arrears = cursor.fetchone()['total'] or 0

    connection.close()
    return render_template('fees_dashboard.html', today_total=today_total, monthly_total=monthly_total, total_arrears=total_arrears)

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
        return render_template('fees_collection_report.html', data=data, start_date=start_date, end_date=end_date)
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
        with connection.cursor() as cursor:
            cursor.execute("SELECT DISTINCT stream_code FROM classes WHERE stream_code IS NOT NULL AND stream_code != '' AND school_id = %s", (service.school_id,))
            streams = [s['stream_code'] for s in cursor.fetchall()]

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
                name=request.form.get('name').strip(),
                priority=int(request.form.get('priority', 99)),
                description=request.form.get('description', '').strip()
            )
            flash("✓ Votehead created.", "success")
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
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO student_groups (name, description, school_id) VALUES (%s, %s, %s)",
                             (request.form.get('name').strip(), request.form.get('description').strip(), service.school_id))
            connection.commit()
            flash("✓ Student Group created.", "success")
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
    if not file or not file.filename.endswith('.csv'):
        return jsonify({'success': False, 'message': 'Invalid file format. Upload CSV'})

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
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error parsing CSV: {str(e)}'})

    connection = get_db_connection()
    service = FeesService(connection)
    try:
        summary = service.import_mpesa_statement(transactions)
        return jsonify({'success': True, 'summary': summary})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
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
        years = class_service.get_all_academic_years()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT sw.*, si.FName, si.SName, fwc.name as category_name, ay.year as year_name, utd.term_number
                FROM student_waivers sw
                JOIN studentinfo si ON sw.admno = si.AdmNo
                JOIN fee_waiver_categories fwc ON sw.category_id = fwc.id
                JOIN academic_years ay ON sw.academic_year_id = ay.id
                JOIN uniform_term_dates utd ON sw.term_id = utd.id
                WHERE sw.school_id = %s
                ORDER BY sw.created_at DESC LIMIT 50
            """, (service.school_id,))
            recent_waivers = cursor.fetchall()

            cursor.execute("SELECT * FROM uniform_term_dates WHERE school_id = %s ORDER BY start_date DESC LIMIT 10", (service.school_id,))
            terms = cursor.fetchall()

        return render_template('fee_waiver_management.html',
                             categories=categories, years=years, terms=terms, recent_waivers=recent_waivers)
    finally:
        connection.close()

@fees_bp.route('/fees/waiver/assign', methods=['POST'])
@login_required
@admin_required
def assign_waiver():
    connection = get_db_connection()
    service = FeesService(connection)
    try:
        service.assign_waiver_to_student(
            admno=int(request.form.get('admno')),
            category_id=int(request.form.get('category_id')),
            year_id=int(request.form.get('year_id')),
            term_id=int(request.form.get('term_id')),
            user_id=session.get('userNo')
        )
        flash("✓ Waiver assigned successfully.", "success")
    except FeesError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('fees.fees_waiver_management'))

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
            items = [{'votehead_id': int(vid), 'amount': float(amt)} for vid, amt in zip(votehead_ids, amounts) if amt and float(amt) > 0]

            if not items: flash("Enter at least one votehead amount.", "error")
            else:
                results = service.create_bulk_fee_structures(
                    year_id=int(request.form.get('year_id')),
                    term_id=int(request.form.get('term_id')),
                    class_groups=request.form.getlist('class_groups'),
                    categories=request.form.getlist('categories'),
                    items=items,
                    user_id=session['userNo'],
                    class_ids=[int(cid) for cid in request.form.getlist('specific_classes')] if request.form.getlist('specific_classes') else None
                )
                flash(f"✓ {results['success']} structures created, {results['skipped']} skipped.", "success")
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

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM uniform_term_dates WHERE school_id = %s ORDER BY year DESC, term_number DESC", (service.school_id,))
        terms = cursor.fetchall()

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
            items = [{'votehead_id': int(vid), 'amount': float(amt)} for vid, amt in zip(votehead_ids, amounts) if amt and float(amt) > 0]
            service.update_fee_structure(structure_id, items, session['userNo'])
            flash("✓ Fee structure updated successfully.", "success")
            return redirect(url_for('fees.manage_fee_structures'))
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

    with connection.cursor() as cursor:
        cursor.execute("SELECT id, term_number FROM uniform_term_dates WHERE academic_year_id = %s AND school_id = %s ORDER BY term_number", (year_id, service.school_id))
        terms = cursor.fetchall()

    voteheads = service.get_voteheads()
    data = {v['id']: {'name': v['name'], 'terms': {t['id']: 0 for t in terms}, 'yearly': 0} for v in voteheads}

    is_locked = False
    with connection.cursor() as cursor:
        query = """
            SELECT fsi.votehead_id, fsi.amount, fs.term_id, fs.is_locked
            FROM fee_structure_items fsi
            JOIN fee_structures fs ON fsi.fee_structure_id = fs.id
            WHERE fs.academic_year_id = %s AND fs.student_category = %s AND fs.school_id = %s
        """
        params = [year_id, category, service.school_id]
        if class_id:
            query += " AND fs.class_id = %s"; params.append(class_id)
        else:
            query += " AND fs.class_group_code = %s AND (fs.class_id IS NULL OR fs.class_id = 0)"; params.append(group_code or 'all')
        cursor.execute(query, params)
        items = cursor.fetchall()
        for item in items:
            if item['votehead_id'] in data:
                data[item['votehead_id']]['terms'][item['term_id']] = item['amount']
                data[item['votehead_id']]['yearly'] += item['amount']
                if item.get('is_locked'): is_locked = True

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

    with connection.cursor() as cursor:
        cursor.execute("SELECT id, term_number FROM uniform_term_dates WHERE academic_year_id = %s AND school_id = %s ORDER BY term_number", (year_id, service.school_id))
        terms = cursor.fetchall()
        cursor.execute("""
            SELECT fs.class_group_code, fs.class_id, fs.student_category, fs.term_id, fs.total_amount, c.display_name as specific_class_name
            FROM fee_structures fs LEFT JOIN classes c ON fs.class_id = c.classID WHERE fs.academic_year_id = %s AND fs.school_id = %s
        """, (year_id, service.school_id))
        rows = cursor.fetchall()

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
        service.copy_fee_structure(int(request.form.get('from_structure_id')), int(request.form.get('target_year_id')), int(request.form.get('target_term_id')), session['userNo'])
        flash("✓ Fee structure copied successfully.", "success")
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
            year_id = int(request.form.get('year_id'))
            class_id = int(request.form.get('class_id')) if request.form.get('class_id') else None
            voteheads = service.get_voteheads()
            term_amounts = {v['id']: {f't{t}': request.form.get(f"v_{v['id']}_t{t}", 0) for t in [1,2,3]} for v in voteheads}
            service.create_yearly_fee_structure(year_id, class_id, request.form.get('group_code'), request.form.get('category'), term_amounts, session['userNo'])
            flash("✓ Yearly fee structure updated.", "success")
        except Exception as e: flash(str(e), "error")
        finally: connection.close(); return redirect(url_for('fees.fee_structures_overview'))

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
        try:
            result = service.record_payment(
                admno=int(request.form.get('admno')),
                amount=Decimal(request.form.get('amount', '0')),
                mode=request.form.get('mode'),
                reference=request.form.get('reference', '').strip(),
                bank=request.form.get('bank', '').strip(),
                date=request.form.get('date'),
                year_id=int(request.form.get('year_id')),
                term_id=int(request.form.get('term_id')),
                user_id=session['userNo']
            )
            flash(f"✓ Payment received. Receipt No: {result['receipt_no']}", "success")
            return redirect(url_for('fees.print_fee_receipt', payment_id=result['payment_id']))
        except Exception as e: flash(str(e), "error")

    years = class_service.get_all_academic_years()
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM uniform_term_dates WHERE school_id = %s ORDER BY year DESC, term_number DESC", (service.school_id,))
        terms = cursor.fetchall()
        cursor.execute("SELECT id FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date AND school_id = %s LIMIT 1", (service.school_id,))
        curr_term = cursor.fetchone()

    connection.close()
    return render_template('collect_fees.html', years=years, terms=terms, current_year_id=next((y['id'] for y in years if y['is_current']), None),
                         current_term_id=curr_term['id'] if curr_term else None, now=datetime.now())

@fees_bp.route('/admin/fees/bulk_post', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_post_fees():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file: flash('Upload a CSV file.', 'error'); return redirect(url_for('fees.bulk_post_fees'))
        connection = get_db_connection(); service = FeesService(connection); posted = 0
        try:
            stream = io.TextIOWrapper(file.stream, encoding='utf-8')
            reader = csv.DictReader(stream)
            for row in reader:
                try:
                    service.record_payment(int(row['admno']), Decimal(row['amount']), row.get('mode', 'CASH'), row.get('reference','').strip(), row.get('bank','').strip(), row.get('date') or datetime.now().strftime('%Y-%m-%d'), int(row['year_id']), int(row['term_id']), session['userNo'])
                    posted += 1
                except: continue
            flash(f"✓ Bulk posting complete. Posted: {posted}", 'success')
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
        count = service.bulk_invoice_classes([int(cid) for cid in request.form.getlist('class_ids')], int(request.form.get('year_id')), int(request.form.get('term_id')), session['userNo'])
        connection.close()
        flash(f"✓ Debited term fees for {count} students.", 'success')
        return redirect(url_for('fees.fees_dashboard'))

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM uniform_term_dates WHERE school_id = %s ORDER BY year DESC, term_number DESC", (service.school_id,))
        terms = cursor.fetchall()
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
    try: return jsonify(service.get_student_statement(int(admno), int(request.args.get('year_id')) if request.args.get('year_id') else None))
    finally: connection.close()

@fees_bp.route('/admin/fees/receipt/<int:payment_id>')
@login_required
def print_fee_receipt(payment_id):
    connection = get_db_connection(); service = FeesService(connection)
    try:
        receipt = service.get_receipt_details(payment_id)
        if not receipt: flash("Receipt not found.", "error"); return redirect(url_for('fees.fees_dashboard'))
        receipt['Fullname'] = f"{receipt['FName']} {receipt.get('MName','') or ''} {receipt['SName']}".strip().replace('  ',' ')
        return render_template('print_fee_receipt.html', receipt=receipt, allocations=receipt.get('allocations', []))
    finally: connection.close()

@fees_bp.route('/admin/fees/receipts')
@login_required
@admin_required
def fee_receipts_register():
    connection = get_db_connection(); service = FeesService(connection)
    records = service.get_receipts_register(request.args.get('start_date'), request.args.get('end_date'), int(request.args.get('admno')) if request.args.get('admno') else None, request.args.get('mode'))
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
            flash("✓ Receipt updated.", "success")
        except Exception as e: flash(str(e), "error")
        finally: connection.close(); return redirect(url_for('fees.fee_receipts_register'))
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
        flash("✓ Receipt voided.", "success")
    except Exception as e: flash(str(e), "error")
    finally: connection.close()
    return redirect(request.referrer or url_for('fees.fee_receipts_register'))

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
            count = service.carry_forward_balances(int(request.form.get('old_year_id')), int(request.form.get('new_year_id')), 1, session['userNo'])
            flash(f'Successfully rolled up balances for {count} students.', 'success')
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
            service.reallocate_payment(request.form.get('reference_no').strip(), request.form.get('from_admno'), request.form.get('to_admno'), session['userNo'], request.form.get('reason').strip())
            flash("✓ Payment reallocated.", "success")
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
            count = service.bulk_invoice_classes([int(cid) for cid in request.form.getlist('class_ids')], int(request.form.get('year_id')), int(request.form.get('term_id')), session['userNo'], specific_votehead_id=int(vh) if vh else None, specific_amount=Decimal(amt) if amt else None)
            flash(f"✓ Bulk invoicing complete. {count} students invoiced.", "success")
        except Exception as e: flash(str(e), "error")

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM uniform_term_dates WHERE school_id = %s ORDER BY year DESC, term_number DESC", (service.school_id,))
        terms = cursor.fetchall()
    context = {'years': class_service.get_all_academic_years(), 'terms': terms, 'classes': class_service.get_active_classes(), 'voteheads': service.get_voteheads()}
    connection.close()
    return render_template('bulk_invoice.html', **context)
