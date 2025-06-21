from flask import Flask, render_template, request, redirect, url_for, flash,jsonify
import pymysql
from datetime import datetime,timedelta
from decimal import Decimal


app = Flask(__name__, static_folder='static')
def format_currency(value):
    try:
        # Handle None or empty values
        if value is None:
            return "0.00"
        # Convert to float first to handle string inputs
        num = float(value)
        # Format with thousand separators and 2 decimal places
        return "{:,.2f}".format(num)
    except (ValueError, TypeError):
        return "0.00"

# Register the filter with Jinja
app.jinja_env.filters['currency'] = format_currency
app.secret_key = 'your_secret_key'
app.jinja_env.globals['datetime'] = datetime


# DB connection
def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='jbs',
        database='schoolmngt',
        cursorclass=pymysql.cursors.DictCursor
    )
# Class group mapping
CLASS_GROUPS = {
    'Playgroup': 'Playgroup-PP2',
    'Pre-Primary 1': 'Playgroup-PP2',
    'Pre-Primary 2': 'Playgroup-PP2',
    'Grade 1': 'Grade 1-3',
    'Grade 2': 'Grade 1-3',
    'Grade 3': 'Grade 1-3',
    'Grade 4': 'Grade 4-6',
    'Grade 5': 'Grade 4-6',
    'Grade 6': 'Grade 4-6',
    'Grade 7': 'Grade 7-9',
    'Grade 8': 'Grade 7-9',
    'Grade 9': 'Grade 7-9'
}
#Get current term
def get_current_term_and_year():
    today = datetime.now().date()
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    cursor.execute("""
        SELECT term_number, year 
        FROM uniform_term_dates 
        WHERE %s BETWEEN start_date AND end_date 
        ORDER BY year DESC, term_number DESC LIMIT 1
    """, (today,))
    result = cursor.fetchone()
    connection.close()
    if result:
        return result['term_number'], result['year']
    else:
        return None, None  # or raise an error or default


def get_class_group(class_name):
    return CLASS_GROUPS.get(class_name)

def generate_receipt_number(year):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT receipt_no FROM uniform_receipts 
        WHERE yr = %s AND receipt_no IS NOT NULL 
        ORDER BY id DESC LIMIT 1
    """, (year,))
    last_receipt = cursor.fetchone()

    if last_receipt and last_receipt['receipt_no']:
        try:
            last_number = int(last_receipt['receipt_no'].split('-')[1])
            next_number = last_number + 1
        except (IndexError, ValueError):
            next_number = 1  
# Fallback to 1 if unexpected format
    else:
        next_number = 1

    year_suffix = str(year)[-2:]
    new_receipt_no = f"UNI-{next_number:04d}-{year_suffix}"

    connection.close()
    return new_receipt_no

# Home page
@app.route('/')
def index():
    return render_template('index.html')

# Uniform issuance form
@app.route('/issue_uniform', methods=['GET', 'POST'])
def issue_uniform():
    if request.method == 'GET':
        return render_template('issue_search.html')
    
    try:
        admno = request.form.get('admno')
        if not admno:
            flash('Please enter an admission number', 'error')
            return redirect(url_for('issue_uniform'))
        
        # Get current term and year
        term, year = get_current_term_and_year()
        if not term:
            flash('No active school term configured for today\'s date.', 'error')
            return redirect(url_for('issue_uniform'))

        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Fetch student info
            cursor.execute("""
                SELECT s.FName, c.class_name 
                FROM studentinfo s 
                JOIN classallocation ca ON s.AdmNo = ca.AdmNo 
                JOIN classes c ON ca.classID = c.classID 
                WHERE s.AdmNo = %s AND ca.thisYear = %s
            """, (admno, year))
            student = cursor.fetchone()
            
            if not student:
                flash('Student not found', 'error')
                return redirect(url_for('issue_uniform'))
            
            # Get uniform items for class group
            class_name = student['class_name']
            class_group = get_class_group(class_name)
            cursor.execute("SELECT item_name, price FROM uniform_prices WHERE class_group = %s", (class_group,))
            items = cursor.fetchall()
            
            return render_template('issue_form.html',
                                   admno=admno,
                                   student_name=student['FName'],
                                   class_name=class_name,
                                   year=year,
                                   term=term,
                                   items=items)

    except Exception as e:
        app.logger.error(f"Database error: {str(e)}")
        flash('An error occurred while fetching student data.', 'error')
        return redirect(url_for('issue_uniform'))
    finally:
        if 'connection' in locals():
            connection.close()

@app.route('/submit_issuance', methods=['POST'])
def submit_issuance():
    try:
        data = request.get_json()
        connection = get_db_connection()
        with connection.cursor() as cursor:
            receipt_no = generate_receipt_number(data['year'])

            total_amount = 0  # Track total for fodebit

            for item in data['items']:
                if item['quantity'] > 0:
                    line_total = item['quantity'] * item['price']
                    total_amount += line_total

                    cursor.execute("""
                        INSERT INTO uniform_receipts 
                        (AdmNo, student_name, class_name, item_name, quantity, price, total, yr, term, receipt_no, issued_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        data['admno'],
                        data['student_name'],
                        data['class_name'],
                        item['item_name'],
                        item['quantity'],
                        item['price'],
                        line_total,
                        data['year'],
                        data['term'],
                        receipt_no,
                        "System"
                    ))

            # === fodebit update logic ===
            if total_amount > 0:
                cursor.execute("""
                    SELECT amount FROM fodebit 
                    WHERE AdmNo=%s AND yr=%s AND term=%s AND r_for='Uniform'
                """, (data['admno'], data['year'], data['term']))
                existing = cursor.fetchone()

                if existing:
                    new_amount = existing['amount'] + total_amount
                    cursor.execute("""
                        UPDATE fodebit SET amount=%s, _date=NOW() 
                        WHERE AdmNo=%s AND yr=%s AND term=%s AND r_for='Uniform'
                    """, (new_amount, data['admno'], data['year'], data['term']))
                else:
                    cursor.execute("""
                        INSERT INTO fodebit 
                        (AdmNo, yr, term, r_for, amount, state, _date, acc, cmode, ccode)
                        VALUES (%s, %s, %s, 'Uniform', %s, 0, NOW(), 1, 'UniformApp', '0')
                    """, (data['admno'], data['year'], data['term'], total_amount))

            connection.commit()

            return jsonify({
                'success': True,
                'admno': data['admno'],
                'year': data['year'],
                'term': data['term'],
                'receipt_no': receipt_no
            })

    except pymysql.Error as e:
        return jsonify({
            'success': False,
            'message': f"Database error ({e.args[0]}): {e.args[1]}",
            'error_code': e.args[0]
        }), 500
    finally:
        if 'connection' in locals():
            connection.close()
# After issuing uniform, show receipt
# This is a helper function — no route decorator needed
def get_uniform_items_for_class(class_name):
    connection = get_db_connection()
    cursor = connection.cursor()  # removed dictionary=True

    # Map class_name to class_group
    if class_name in ['Playgroup', 'PP1', 'PP2']:
        class_group = 'Playgroup-PP2'
    elif class_name in ['Grade 1', 'Grade 2', 'Grade 3']:
        class_group = 'Grade 1-3'
    elif class_name in ['Grade 4', 'Grade 5', 'Grade 6']:
        class_group = 'Grade 4-6'
    elif class_name in ['Grade 7', 'Grade 8', 'Grade 9']:
        class_group = 'Grade 7-9'
    else:
        class_group = 'Other'

    cursor.execute("SELECT item_name, price FROM uniform_prices WHERE class_group = %s", (class_group,))
    items = cursor.fetchall()

    cursor.close()
    connection.close()

    return items

# This is your actual route function
@app.route('/receipt', methods=['POST'])
def receipt():
    admno = request.form['admno']
    student_name = request.form['student_name']
    class_name = request.form['class_name']
    year = request.form['yr']
    term = 2  # or dynamic if needed

    items = get_uniform_items_for_class(class_name)
    total_amount = 0

    connection = get_db_connection()
    cursor = connection.cursor()

    for item in items:
        quantity = int(request.form.get(f'quantity_{item["item_name"]}', 0))
        price = float(item['price'])
        item_total = quantity * price

        if quantity > 0:
            cursor.execute("""
                INSERT INTO uniform_receipts (AdmNo, yr, term, item_name, price, quantity, total, issued_on)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """, (admno, year, term, item['item_name'], price, quantity, item_total))

            total_amount += item_total

    if total_amount == 0:
        flash('No items selected.', 'warning')
        return redirect(url_for('issue_form', admno=admno))

    # Update or insert in fodebit
    cursor.execute("""
        SELECT amount FROM fodebit 
        WHERE AdmNo=%s AND yr=%s AND term=%s AND r_for='Uniform'
    """, (admno, year, term))
    result = cursor.fetchone()

    if result:
        new_amount = result['amount'] + total_amount
        cursor.execute("""
            UPDATE fodebit SET amount=%s, _date=NOW() 
            WHERE AdmNo=%s AND yr=%s AND term=%s AND r_for='Uniform'
        """, (new_amount, admno, year, term))
    else:
        cursor.execute("""
            INSERT INTO fodebit (AdmNo, yr, term, r_for, amount, state, _date, acc, cmode, ccode)
            VALUES (%s, %s, %s, 'Uniform', %s, 0, NOW(), 1, 'UniformApp', '0')
        """, (admno, year, term, total_amount))

    connection.commit()
    cursor.close()
    connection.close()

    # Redirect to print receipt view
    return redirect(url_for('print_receipt', admno=admno, year=year, term=term))

def get_class_name(cursor, admno, year):
    try:
        cursor.execute("""
            SELECT c.class_name 
            FROM classallocation a 
            JOIN classes c ON a.classID = c.classID 
            WHERE a.AdmNo = %s AND a.thisYear = %s
            LIMIT 1
        """, (admno, year))
        class_row = cursor.fetchone()
        if class_row:
            return class_row['class_name']
        else:
            return None
    except Exception as e:
        print(f"Failed to fetch class name for {admno}, {year}: {e}")
        return None


@app.route("/print_receipt")
def print_receipt():
    admno = request.args.get("admno")
    year = request.args.get("year")
    term = request.args.get("term")
    receipt_no = request.args.get("receipt_no")

    if not all([admno, year, term, receipt_no]):
        return "Missing parameters", 400

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        # Fetch student info
        cursor.execute("SELECT FName FROM studentinfo WHERE AdmNo = %s", (admno,))
        student = cursor.fetchone()
        if not student:
            return f"No student found with AdmNo {admno}", 404
        student_name = student['FName']

        # Fetch class name
        class_name = get_class_name(cursor, admno, year)
        if not class_name:
            return f"No class allocation found for AdmNo {admno} in {year}", 404

        # Fetch issued items for that specific receipt
        cursor.execute("""
            SELECT item_name, quantity, price, (quantity * price) AS total
            FROM uniform_receipts
            WHERE AdmNo = %s AND yr = %s AND term = %s AND receipt_no = %s
        """, (admno, year, term, receipt_no))
        issued_items = cursor.fetchall()

        if not issued_items:
            return f"No uniform issuance records for receipt {receipt_no}", 404

        total_amount = sum(item['total'] for item in issued_items)

        return render_template(
            "receipt.html",
            admno=admno,
            student_name=student_name,
            class_name=class_name,
            year=year,
            term=term,
            receipt_no=receipt_no,
            issued_items=[(item['item_name'], item['quantity'], item['price'], item['total']) for item in issued_items],
            total_amount=total_amount
        )

    except Exception as e:
        print(f"Database error: {e}")
        return "Database operation failed", 500

    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()


@app.route('/manage_prices', methods=['GET', 'POST'])
def manage_prices():
    connection = get_db_connection()
    cursor = connection.cursor()

    # Dynamically fetch all unique items from the uniform_prices table
    cursor.execute("SELECT DISTINCT item_name FROM uniform_prices ORDER BY item_name")
    uniform_items = [row['item_name'] for row in cursor.fetchall()]

    class_groups = ['Playgroup-PP2', 'Grade 1-3', 'Grade 4-6', 'Grade 7-9']

    if request.method == 'POST':
        for item in uniform_items:
            for group in class_groups:
                price = request.form.get(f'price_{item}_{group}')
                if price is not None:
                    cursor.execute("""
                        INSERT INTO uniform_prices (item_name, class_group, price)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE price = VALUES(price)
                    """, (item, group, price))
        connection.commit()
        flash("Prices updated successfully.")
        return redirect(url_for('manage_prices'))

    # Fetch existing prices
    cursor.execute("SELECT * FROM uniform_prices")
    price_rows = cursor.fetchall()

    # Map prices for easy access in template
    price_dict = {}
    for row in price_rows:
        price_dict[(row['item_name'], row['class_group'])] = row['price']

    connection.close()

    return render_template(
        'manage_prices.html',
        uniform_items=uniform_items,
        class_groups=class_groups,
        prices=price_dict
    )

@app.route("/reports/issued_summary", methods=['GET', 'POST'])
def issued_summary():
    connection = get_db_connection()
    summary_data = []
    grand_total = 0
    today = datetime.now().date()
    
    # Set defaults
    date_from = request.form.get('date_from') or today.strftime('%Y-%m-%d')
    date_to = request.form.get('date_to') or today.strftime('%Y-%m-%d')

    # Include the full 'to' date by adding 23:59:59 time
    to_datetime = f"{date_to} 23:59:59"

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                item_name, 
                SUM(quantity) AS total_qty, 
                SUM(total) AS total_value
            FROM uniform_receipts
            WHERE issued_on BETWEEN %s AND %s
            GROUP BY item_name
            ORDER BY item_name
        """, (date_from, to_datetime))
        summary_data = cursor.fetchall()

    if summary_data:
        grand_total = sum(row['total_value'] for row in summary_data)

    connection.close()

    return render_template("report_issued_summary.html",
                           summary_data=summary_data,
                           date_from=date_from,
                           date_to=date_to,
                           grand_total=grand_total)


#Report Dashboard
@app.route('/reports')
def reports_dashboard():
    return render_template('reports_dashboard.html')
#Student uniform report

@app.route("/reports/student_history/<admno>")
def student_history(admno):
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT receipt_no, item_name, quantity, price, total, yr, term, issued_on
            FROM uniform_receipts
            WHERE AdmNo = %s
            ORDER BY issued_on DESC
        """, (admno,))
        records = cursor.fetchall()

    connection.close()
    return render_template("report_student_history.html", admno=admno, records=records)


#Items total by class report
@app.route("/reports/item_totals")
def item_totals():
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                item_name, 
                SUM(quantity) AS total_issued, 
                SUM(total) AS total_value 
            FROM uniform_receipts
            GROUP BY item_name
            ORDER BY item_name
        """)
        totals = cursor.fetchall()
    connection.close()

    return render_template("report_item_totals.html", totals=totals)

#Receipt register

@app.route("/reports/receipts_register", methods=["GET"])
def receipts_register():
    filters = {
        "admno": request.args.get("admno"),
        "receipt_no": request.args.get("receipt_no"),
        "class_name": request.args.get("class_name"),
        "term": request.args.get("term"),
        "from_date": request.args.get("from_date"),
        "to_date": request.args.get("to_date")
    }

    query = """
        SELECT 
            receipt_no, AdmNo, student_name, class_name, yr, term, 
            SUM(total) AS total_amount, issued_on 
        FROM uniform_receipts
        WHERE 1=1
    """
    params = []

    # Dynamic filters
    if filters["admno"]:
        query += " AND AdmNo = %s"
        params.append(filters["admno"])

    if filters["receipt_no"]:
        query += " AND receipt_no = %s"
        params.append(filters["receipt_no"])

    if filters["class_name"]:
        query += " AND class_name = %s"
        params.append(filters["class_name"])

    if filters["term"]:
        query += " AND term = %s"
        params.append(filters["term"])

    if filters["from_date"]:
        query += " AND issued_on >= %s"
        params.append(filters["from_date"])

    if filters["to_date"]:
        query += " AND issued_on <= %s"
        params.append(filters["to_date"])

    query += " GROUP BY receipt_no ORDER BY issued_on DESC"

    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
    connection.close()

    return render_template("report_receipts_register.html", records=records, filters=filters)


#Student search report
@app.route("/reports/student_search", methods=["GET", "POST"])
def student_search():
    if request.method == "POST":
        admno = request.form.get("admno")
        if not admno:
            flash("Please enter an admission number.", "error")
            return redirect(url_for("student_search"))
        return redirect(url_for("student_history", admno=admno))

    return render_template("report_student_search.html")
#cancel receipt
@app.route("/cancel_receipt/<receipt_no>", methods=["POST"])
def cancel_receipt(receipt_no):
    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # 1. Get current date and active term
        today = datetime.now().date()
        cursor.execute("""
            SELECT term_number FROM uniform_term_dates 
            WHERE %s BETWEEN start_date AND end_date
        """, (today,))
        term_row = cursor.fetchone()

        if not term_row:
            return "Current term not configured. Set it under Term Management.", 400

        current_term = term_row['term_number']

        # 2. Fetch receipt info — NO GROUP BY needed
        cursor.execute("""
            SELECT AdmNo, yr, term, SUM(total) AS total_amount 
            FROM uniform_receipts 
            WHERE receipt_no = %s
        """, (receipt_no,))
        receipt = cursor.fetchone()

        if not receipt:
            return f"Receipt {receipt_no} not found.", 404

        if receipt['term'] != current_term:
            return f"Cannot cancel a receipt outside the current term ({current_term}).", 400

        admno = receipt['AdmNo']
        year = receipt['yr']
        term = receipt['term']
        total_amount = Decimal(str(receipt['total_amount']))

        # 3. Delete records in uniform_receipts
        cursor.execute("DELETE FROM uniform_receipts WHERE receipt_no = %s", (receipt_no,))

        # 4. Adjust fodebit
        cursor.execute("""
            SELECT amount FROM fodebit 
            WHERE AdmNo=%s AND yr=%s AND term=%s AND r_for='Uniform'
        """, (admno, year, term))
        fodebit = cursor.fetchone()

        if fodebit:
            fodebit_amount = Decimal(str(fodebit['amount']))
            new_amount = fodebit_amount - total_amount
            if new_amount > 0:
                cursor.execute("""
                    UPDATE fodebit SET amount=%s, _date=NOW() 
                    WHERE AdmNo=%s AND yr=%s AND term=%s AND r_for='Uniform'
                """, (new_amount, admno, year, term))
            else:
                cursor.execute("""
                    DELETE FROM fodebit 
                    WHERE AdmNo=%s AND yr=%s AND term=%s AND r_for='Uniform'
                """, (admno, year, term))

        connection.commit()
        return jsonify({'success': True, 'message': f'Receipt {receipt_no} cancelled successfully.'})

    except Exception as e:
        connection.rollback()
        print(f"Error cancelling receipt: {e}")
        return jsonify({'success': False, 'message': 'Failed to cancel receipt.'}), 500

    finally:
        cursor.close()
        connection.close()
        
#Uniform dashboard
@app.route('/uniform_dashboard')
def uniform_dashboard():
    return render_template('uniform_dashboard.html')

"""@app.route("/routes")
def show_routes():
    output = []
    for rule in app.url_map.iter_rules():
        methods = ",".join(rule.methods)
        line = f"{rule.endpoint:30s} {methods:20s} {rule}"
        output.append(line)
    return "<pre>" + "\n".join(sorted(output)) + "</pre>"
"""

"""**************************************************************************************************************
                                                   FLEET MANAGEMENT
****************************************************************************************************************"""
#record service

@app.route('/fleet/record_service', methods=['GET', 'POST'])
def record_service():
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        bus_id = request.form.get('bus_id')
        service_date = request.form.get('service_date')
        service_type = request.form.get('service_type')
        description = request.form.get('description')
        cost = request.form.get('cost')
        garage_name = request.form.get('garage_name')
        mileage = int(request.form.get('mileage_at_service'))

        # Get current mileage
        cursor.execute("SELECT current_mileage FROM buses WHERE id=%s", (bus_id,))
        bus = cursor.fetchone()
        if not bus:
            flash("Invalid bus selected.", "error")
            return redirect(request.url)

        current_mileage = bus['current_mileage']

        if mileage < current_mileage:
            flash(f"Service mileage ({mileage} KM) cannot be less than the current mileage ({current_mileage} KM).", "error")
            return redirect(request.url)

        # Insert service record
        cursor.execute("""
            INSERT INTO service_records (bus_id, service_date, service_type, description, cost, garage_name, mileage_at_service)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (bus_id, service_date, service_type, description, cost, garage_name, mileage))

        # Update bus current mileage
        cursor.execute("UPDATE buses SET current_mileage=%s WHERE id=%s", (mileage, bus_id))

        connection.commit()
        connection.close()

        flash("Service record saved successfully.", "success")
        return redirect(url_for('service_register'))

    # Load buses for dropdown
    cursor.execute("SELECT id, reg_no FROM buses WHERE active=1 ORDER BY reg_no")
    buses = cursor.fetchall()
    connection.close()

    return render_template('record_service.html', buses=buses)

#Fleet dashboard
@app.route('/fleet/fleet_dashboard')
def fleet_dashboard():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT id, reg_no FROM buses WHERE active=1 ORDER BY reg_no")
    buses = cursor.fetchall()
    connection.close()

    return render_template('fleet_dashboard.html', buses=buses)


#Buses creation

@app.route('/fleet/buses', methods=['GET', 'POST'])
def manage_buses():
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        reg_no = request.form.get('reg_no').upper()
        make = request.form.get('make')
        capacity = request.form.get('capacity')
        driver = request.form.get('driver_name')
        current_mileage = request.form.get('current_mileage')

        # Check if reg_no already exists
        cursor.execute("SELECT COUNT(*) AS count FROM buses WHERE reg_no = %s", (reg_no,))
        existing = cursor.fetchone()['count']

        if existing > 0:
            flash(f'A bus with registration number {reg_no} already exists.', 'error')
        else:
            cursor.execute("""
                INSERT INTO buses (reg_no, make, capacity, driver_name,current_mileage)
                VALUES (%s, %s, %s, %s,%s)
            """, (reg_no, make, capacity, driver,current_mileage))
            connection.commit()
            flash('Bus added successfully.', 'success')

    # Fetch buses for display
    cursor.execute("SELECT * FROM buses WHERE active=1")
    buses = cursor.fetchall()

    connection.close()
    return render_template('manage_buses.html', buses=buses)


#Edit bus

@app.route('/fleet/edit_bus/<int:bus_id>', methods=['GET', 'POST'])
def edit_bus(bus_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        reg_no = request.form.get('reg_no')
        make = request.form.get('make')
        capacity = request.form.get('capacity')
        driver = request.form.get('driver_name')
        current_mileage = request.form.get('current_mileage')

        # Validate required fields
        if not reg_no:
            flash("Registration number cannot be empty.", 'error')
            return redirect(request.url)

        # Check for duplicate reg_no (excluding current bus)
        cursor.execute("""
            SELECT COUNT(*) AS count FROM buses 
            WHERE reg_no = %s AND id != %s
        """, (reg_no, bus_id))
        existing = cursor.fetchone()['count']

        if existing > 0:
            flash(f'A bus with registration number {reg_no} already exists.', 'error')
        else:
            cursor.execute("""
                UPDATE buses 
                SET reg_no=%s, make=%s, capacity=%s, driver_name=%s,current_mileage=%s 
                WHERE id=%s
            """, (reg_no, make, capacity, driver,current_mileage, bus_id))
            connection.commit()
            flash('Bus details updated successfully.', 'success')
            return redirect(url_for('manage_buses'))

    cursor.execute("SELECT * FROM buses WHERE id=%s AND active=1", (bus_id,))
    bus = cursor.fetchone()
    connection.close()

    if not bus:
        flash('Bus not found.', 'error')
        return redirect(url_for('manage_buses'))

    return render_template('edit_bus.html', bus=bus)

#Delete bus

@app.route('/fleet/delete_bus/<int:bus_id>', methods=['POST'])
def delete_bus(bus_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("UPDATE buses SET active=0 WHERE id=%s", (bus_id,))
    connection.commit()
    connection.close()

    flash('Bus deleted successfully.', 'success')
    return redirect(url_for('manage_buses'))

#Fuel voucher issuance 
@app.route('/fleet/issue_fuel', methods=['GET', 'POST'])
def issue_fuel():
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        bus_id = request.form.get('bus_id')
        remarks = request.form.get('remarks')
        issued_by = 'System'

        # Generate voucher number
        cursor.execute("SELECT COUNT(*) as count FROM fuel_vouchers")
        count = cursor.fetchone()['count']
        voucher_no = f'FUEL-{count + 1:04d}'

        # 🔧 Fixed: Removed driver_name from INSERT statement
        cursor.execute("""
            INSERT INTO fuel_vouchers (voucher_no, bus_id, issued_by, remarks)
            VALUES (%s, %s, %s, %s)
        """, (voucher_no, bus_id, issued_by, remarks))

        connection.commit()
        connection.close()

        flash(f'Fuel voucher {voucher_no} issued successfully. <a href="{url_for("print_voucher", voucher_no=voucher_no)}" target="_blank" class="underline text-blue-600">Print Now</a>', 'success')
        return redirect(url_for('issue_fuel'))

    # Load buses for dropdown
    cursor.execute("SELECT id, reg_no, driver_name FROM buses WHERE active=1")
    buses = cursor.fetchall()

    connection.close()
    return render_template('issue_fuel.html', buses=buses)

#Create fuel voucher print
@app.route('/fleet/print_voucher/<voucher_no>')
def print_voucher(voucher_no):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT fv.*, b.reg_no, b.driver_name 
        FROM fuel_vouchers fv
        JOIN buses b ON fv.bus_id = b.id
        WHERE fv.voucher_no = %s
    """, (voucher_no,))
    voucher = cursor.fetchone()

    if not voucher:
        flash(f"Voucher {voucher_no} not found.", 'error')
        return redirect(url_for('issue_fuel'))

    connection.close()
    return render_template('print_fuel_voucher.html', voucher=voucher)
#Fuel voucher number generation function
def generate_voucher_no():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT voucher_no FROM fuel_vouchers 
        ORDER BY id DESC LIMIT 1
    """)
    last_voucher = cursor.fetchone()

    if last_voucher and last_voucher['voucher_no']:
        try:
            last_number = int(last_voucher['voucher_no'].split('-')[1])
            next_number = last_number + 1
        except (IndexError, ValueError):
            next_number = 1
    else:
        next_number = 1

    new_voucher_no = f"FUEL-{next_number:04d}"
    connection.close()
    return new_voucher_no
#Fuel voucher register

@app.route("/fuel/voucher_register", methods=['GET', 'POST'])
def voucher_register():
    connection = get_db_connection()
    filters = {}
    vouchers = []
    total_litres = 0
    total_cost = 0

    # Get current date and first day of month
    today = datetime.now().date()
    first_of_month = today.replace(day=1)
    
    # Handle date parameters
    if request.method == 'POST':
        filters['reg_no'] = request.form.get('reg_no')
        filters['driver_name'] = request.form.get('driver_name')
        filters['voucher_no'] = request.form.get('voucher_no')
        date_from = request.form.get('date_from') or str(first_of_month)
        to_date = request.form.get('to_date') or str(today)
    else:
        date_from = str(first_of_month)
        to_date = str(today)

    to_datetime = f"{to_date} 23:59:59"

    query = """
        SELECT 
            fv.id,
            fv.voucher_no, 
            fv.issued_on, 
            COALESCE(fi.actual_litres, fv.litres, 0) AS litres,
            COALESCE(fi.amount_paid, fv.total_cost, 0) AS total_cost,
            b.reg_no, 
            b.driver_name,
            CASE WHEN fi.id IS NOT NULL THEN 'Yes' ELSE 'No' END AS invoiced
        FROM fuel_vouchers fv
        JOIN buses b ON fv.bus_id = b.id
        LEFT JOIN fuel_invoices fi ON fv.id = fi.voucher_id
        WHERE fv.issued_on BETWEEN %s AND %s
    """
    params = [date_from, to_datetime]

    if filters.get('reg_no'):
        query += " AND b.reg_no = %s"
        params.append(filters['reg_no'])
    if filters.get('driver_name'):
        query += " AND b.driver_name LIKE %s"
        params.append(f"%{filters['driver_name']}%")
    if filters.get('voucher_no'):
        query += " AND fv.voucher_no = %s"
        params.append(filters['voucher_no'])

    query += " ORDER BY fv.issued_on DESC"

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        vouchers = cursor.fetchall()

        # Calculate totals using the same COALESCE logic
        total_litres = sum(float(v['litres'] or 0) for v in vouchers)
        total_cost = sum(float(v['total_cost'] or 0) for v in vouchers)

    connection.close()

    return render_template("fuel_voucher_register.html",
                         vouchers=vouchers,
                         filters=filters,
                         date_from=date_from,
                         to_date=to_date,
                         total_litres=total_litres,
                         total_cost=total_cost,
                         report_title="Fuel Voucher Register",
                         current_date=datetime.now().strftime("%d-%m-%Y %H:%M"),
                         date_range=f"{date_from} to {to_date}")

#Oil records register
@app.route("/oil/register")
def oil_register():
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT o.*, b.reg_no 
            FROM oil_records o 
            JOIN buses b ON o.bus_id = b.id
            ORDER BY o.date DESC
        """)
        records = cursor.fetchall()
    connection.close()

    return render_template("oil_register.html", records=records)
#Record fuel invoice

@app.route('/fleet/record_fuel_invoice', methods=['GET', 'POST'])
def record_fuel_invoice():
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        voucher_id = request.form.get('voucher_id')
        date = request.form.get('date')
        actual_litres = float(request.form.get('actual_litres'))
        amount_paid = float(request.form.get('amount_paid'))
        petrol_station = request.form.get('petrol_station')
        odometer_reading = request.form.get('odometer_reading')
        remarks = request.form.get('remarks', '')

        try:
            connection.begin()

            # 1. Get bus_id and validate voucher
            cursor.execute("SELECT bus_id FROM fuel_vouchers WHERE id=%s", (voucher_id,))
            bus_row = cursor.fetchone()
            if not bus_row:
                flash("Invalid voucher selected.", "error")
                return redirect(request.url)
            bus_id = bus_row['bus_id']

            # 2. Validate odometer reading
            cursor.execute("""
                SELECT MAX(fi.odometer_reading) AS last_odometer
                FROM fuel_invoices fi
                JOIN fuel_vouchers fv ON fi.voucher_id = fv.id
                WHERE fv.bus_id = %s
            """, (bus_id,))
            last_odometer = cursor.fetchone()['last_odometer'] or 0

            if odometer_reading and odometer_reading.isdigit():
                odometer_reading = int(odometer_reading)
                if odometer_reading < last_odometer:
                    flash(f"Odometer reading must be greater than the last recorded value: {last_odometer} KM.", 'error')
                    return redirect(request.url)
            else:
                flash("Please enter a valid numeric odometer reading.", "error")
                return redirect(request.url)

            # 3. Record the invoice
            cursor.execute("""
                INSERT INTO fuel_invoices 
                (voucher_id, date, actual_litres, amount_paid, petrol_station, odometer_reading, remarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (voucher_id, date, actual_litres, amount_paid, petrol_station, odometer_reading, remarks))

            # 4. Update the voucher (removed last_updated column)
            cursor.execute("""
                UPDATE fuel_vouchers 
                SET litres = %s, 
                    total_cost = %s
                WHERE id = %s
            """, (actual_litres, amount_paid, voucher_id))

            connection.commit()
            flash('Fuel invoice recorded and voucher updated successfully!', 'success')
            return redirect(url_for('voucher_register'))

        except Exception as e:
            connection.rollback()
            flash(f'Error recording invoice: {str(e)}', 'error')
            return redirect(request.url)
        finally:
            connection.close()

    # GET request handling remains the same
    cursor.execute("""
        SELECT fv.id, fv.voucher_no, b.reg_no 
        FROM fuel_vouchers fv
        JOIN buses b ON fv.bus_id = b.id
        WHERE NOT EXISTS (
            SELECT 1 FROM fuel_invoices WHERE voucher_id = fv.id
        )
        ORDER BY fv.issued_on DESC
    """)
    vouchers = cursor.fetchall()
    connection.close()
    
    return render_template('record_fuel_invoice.html', vouchers=vouchers)

#Fuel consumption report
@app.route('/fleet/fuel_consumption_report', methods=['GET', 'POST'])
def fuel_consumption_report():
    connection = get_db_connection()
    cursor = connection.cursor()

    # Get current date and first day of month
    today = datetime.now().date()
    first_of_month = today.replace(day=1)
    
    # Handle date parameter
    if request.method == 'POST':
        # Use form dates if submitted, otherwise default to current month
        from_date = request.form.get('from_date') or str(first_of_month)
        to_date = request.form.get('to_date') or str(today)
    else:
        # Default to current month when first loading the page
        from_date = str(first_of_month)
        to_date = str(today)

   

    cursor.execute("""
        SELECT 
            b.reg_no,
            COUNT(fv.id) AS vouchers_issued,
            IFNULL(SUM(fi.actual_litres),0) AS total_litres,
            IFNULL(SUM(fi.amount_paid),0) AS total_amount
        FROM buses b
        LEFT JOIN fuel_vouchers fv ON b.id = fv.bus_id
        LEFT JOIN fuel_invoices fi ON fv.id = fi.voucher_id
        WHERE fv.issued_on BETWEEN %s AND %s
        GROUP BY b.id
        ORDER BY b.reg_no
    """, (from_date, f"{to_date} 23:59:59"))

    report = cursor.fetchall()
    connection.close()

    # Calculate grand totals
    grand_total_litres = sum(float(item['total_litres']) for item in report)
    grand_total_amount = sum(float(item['total_amount']) for item in report)

    return render_template(
        'fuel_consumption_report.html',
        report=report,
        from_date=from_date,
        to_date=to_date,
        grand_total_litres=grand_total_litres,
        grand_total_amount=grand_total_amount,
        report_title="Cumulative Fuel Consumption Report",
        current_date=datetime.now().strftime("%d-%m-%Y %H:%M"),
        date_range=f"{from_date} to {to_date}",
        back_url=url_for('fleet_dashboard')
    )
@app.route('/fleet/get_driver/<int:bus_id>')
def get_driver(bus_id):
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT driver_name FROM buses WHERE id=%s AND active=1", (bus_id,))
        bus = cursor.fetchone()
    connection.close()
    return jsonify({'driver_name': bus['driver_name'] if bus else ''})

#Service register
@app.route('/fleet/service_register')
def service_register():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT s.id, b.reg_no, s.service_date, s.service_type, s.description, s.cost, s.garage_name, s.mileage_at_service
        FROM service_records s
        JOIN buses b ON s.bus_id = b.id
        ORDER BY s.service_date DESC
    """)
    services = cursor.fetchall()
    connection.close()

    return render_template('service_register.html', services=services)
#Service reminders
@app.route('/fleet/service_reminders')
def service_reminders():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT b.reg_no, 
               MAX(s.service_date) as last_service_date,
               MAX(s.mileage_at_service) as mileage_at_service,
               b.current_mileage, 
               DATEDIFF(CURDATE(), MAX(s.service_date)) as days_since_service,
               MAX(s.mileage_at_service) + 5000 as next_service_mileage
        FROM service_records s
        JOIN buses b ON s.bus_id = b.id
        GROUP BY b.id
        HAVING next_service_mileage <= b.current_mileage OR days_since_service >= 180
        ORDER BY b.reg_no
    """)
    reminders = cursor.fetchall()
    connection.close()

    return render_template('service_reminders.html', reminders=reminders)


#Service cost report
@app.route('/fleet/service_costs_report', methods=['GET', 'POST'])
def service_costs_report():
    connection = get_db_connection()
    cursor = connection.cursor()

    date_from = request.form.get('date_from') or '2024-01-01'
    date_to = request.form.get('date_to') or datetime.now().strftime('%Y-%m-%d')

    query = """
        SELECT 
            b.reg_no,
            COUNT(s.id) AS service_count,
            SUM(s.cost) AS total_service_cost
        FROM service_records s
        JOIN buses b ON s.bus_id = b.id
        WHERE s.service_date BETWEEN %s AND %s
        GROUP BY b.id
        ORDER BY b.reg_no
    """
    cursor.execute(query, (date_from, date_to))
    services = cursor.fetchall()

    connection.close()
    return render_template('service_costs_report.html', services=services, date_from=date_from, date_to=date_to)

@app.route('/fleet/fuel_consumption_efficiency')
def fuel_consumption_efficiency():
    connection = get_db_connection()
    cursor = connection.cursor()

# Get current date and first day of month
    today = datetime.now().date()
    first_of_month = today.replace(day=1)
    
    # Handle date parameter
    if request.method == 'POST':
        # Use form dates if submitted, otherwise default to current month
        date_from = request.form.get('date_from') or str(first_of_month)
        date_to = request.form.get('date_to') or str(today)
    else:
        # Default to current month when first loading the page
        date_from = str(first_of_month)
        date_to = str(today)

   


    # Fetch all fuel invoices sorted by bus and date
    cursor.execute("""
        SELECT 
            b.reg_no,
            fi.date,
            fi.actual_litres,
            fi.odometer_reading
        FROM fuel_invoices fi
        JOIN fuel_vouchers fv ON fi.voucher_id = fv.id
        JOIN buses b ON fv.bus_id = b.id
        WHERE b.active = 1
        ORDER BY b.reg_no, fi.date ASC
    """)

    records = cursor.fetchall()

    report = {}
    for row in records:
        reg_no = row['reg_no']
        litres = float(row['actual_litres'] or 0)
        odometer = int(row['odometer_reading'] or 0)

        if reg_no not in report:
            report[reg_no] = {
                'total_litres': 0.0,
                'total_distance': 0,
                'last_odometer': None
            }

        if report[reg_no]['last_odometer'] is not None:
            distance = odometer - report[reg_no]['last_odometer']
            if distance > 0:
                report[reg_no]['total_distance'] += distance

        report[reg_no]['total_litres'] += litres
        report[reg_no]['last_odometer'] = odometer

    final_report = []
    for reg_no, data in report.items():
        if data['total_litres'] > 0:
            consumption = round(data['total_distance'] / data['total_litres'], 2)
        else:
            consumption = 'N/A'
        final_report.append({
            'reg_no': reg_no,
            'total_litres': data['total_litres'],
            'total_distance': data['total_distance'],
            'consumption': consumption
        })

    connection.close()

    return render_template(
        'fuel_efficiency_report.html', 
        records=final_report,
        report_title="Fuel Efficiency Report (KM/Litre)",
        date_from=date_from,
        date_to=date_to,
        current_date=datetime.now().strftime("%d-%m-%Y %H:%M"),
        date_range=f"{
        date_from} to {date_to}",
        back_url=url_for('fleet_dashboard')
    )



@app.route('/fleet/fuel_efficiency_report', methods=['GET', 'POST'])
def fuel_efficiency_report():
    connection = get_db_connection()
    cursor = connection.cursor()

# Get current date and first day of month
    today = datetime.now().date()
    first_of_month = today.replace(day=1)
    
    # Handle date parameter
    if request.method == 'POST':
        # Use form dates if submitted, otherwise default to current month
        date_from = request.form.get('date_from') or str(first_of_month)
        date_to = request.form.get('date_to') or str(today)
    else:
        # Default to current month when first loading the page
        date_from = str(first_of_month)
        date_to = str(today)

   



    #date_from = request.form.get('date_from') or '2024-01-01'
    #date_to = request.form.get('date_to') or datetime.now().strftime('%Y-%m-%d')

    query = """
        SELECT 
            b.reg_no,
            SUM(fi.actual_litres) AS total_litres,
            (MAX(fi.odometer_reading) - MIN(fi.odometer_reading)) AS distance_covered,
            (MAX(fi.odometer_reading) - MIN(fi.odometer_reading)) / SUM(fi.actual_litres) AS km_per_litre
        FROM fuel_invoices fi
        JOIN fuel_vouchers fv ON fi.voucher_id = fv.id
        JOIN buses b ON fv.bus_id = b.id
        WHERE fi.date BETWEEN %s AND %s
        GROUP BY b.reg_no
        ORDER BY b.reg_no
    """
    cursor.execute(query, (date_from, date_to))
    records = cursor.fetchall()

    connection.close()
    return render_template('fuel_efficiency_report.html',
                           records=records,
                           date_from=date_from,
                           date_to=date_to
                           )
    


@app.route("/test-css")
def test_css():
    return "<link rel='stylesheet' href='/static/css/tailwind.min.css'>Test Page"

@app.route('/fleet/fuel_consumption_chart')
def fuel_consumption_chart():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT b.reg_no, SUM(fi.actual_litres) AS total_litres
        FROM fuel_invoices fi
        JOIN fuel_vouchers fv ON fi.voucher_id = fv.id
        JOIN buses b ON fv.bus_id = b.id
        GROUP BY b.reg_no
        ORDER BY b.reg_no
    """)
    data = cursor.fetchall()
    connection.close()

    labels = [row['reg_no'] for row in data]
    litres = [float(row['total_litres']) for row in data]

    return render_template('fuel_consumption_chart.html', labels=labels, litres=litres)

@app.route('/fleet/print_fuel_consumption_report')
def print_fuel_consumption_report():
    from_date = request.args.get('from_date') or '2024-01-01'
    to_date = request.args.get('to_date') or datetime.now().strftime('%Y-%m-%d')

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT 
            b.reg_no,
            COUNT(fv.id) AS vouchers_issued,
            IFNULL(SUM(fi.actual_litres),0) AS total_litres,
            IFNULL(SUM(fi.amount_paid),0) AS total_amount
        FROM buses b
        LEFT JOIN fuel_vouchers fv ON b.id = fv.bus_id
        LEFT JOIN fuel_invoices fi ON fv.id = fi.voucher_id
        WHERE fv.issued_on BETWEEN %s AND %s
        GROUP BY b.id
        ORDER BY b.reg_no
    """, (from_date, f"{to_date} 23:59:59"))

    report = cursor.fetchall()
    connection.close()

    return render_template(
        'print_fuel_consumption_report.html',
        report=report,
        from_date=from_date,
        to_date=to_date,
        report_title="Cumulative Fuel Consumption Report",
        current_date=datetime.now().strftime("%d-%m-%Y"),
        back_url=url_for('fuel_consumption_report')
    )


@app.route('/fleet/fuel_expenses_report', methods=['GET', 'POST'])
def fuel_expenses_report():
    connection = get_db_connection()
    cursor = connection.cursor()

    date_from = request.form.get('date_from') or '2024-01-01'
    date_to = request.form.get('date_to') or datetime.now().strftime('%Y-%m-%d')

    query = """
        SELECT 
            b.reg_no,
            COUNT(fv.id) AS vouchers_issued,
            IFNULL(SUM(fv.total_cost), 0) AS total_expense
        FROM fuel_vouchers fv
        JOIN buses b ON fv.bus_id = b.id
        WHERE fv.issued_on BETWEEN %s AND %s
        GROUP BY b.id
        ORDER BY b.reg_no
    """
    cursor.execute(query, (date_from, f"{date_to} 23:59:59"))
    expenses = cursor.fetchall()

    connection.close()

    return render_template(
        'fuel_expenses_report.html',
        expenses=expenses,
        date_from=date_from,
        date_to=date_to
    )
#Get invoices
@app.route('/fleet/fuel_invoices/<reg_no>/<from_date>/<to_date>')
def get_fuel_invoices(reg_no, from_date, to_date):
    connection = get_db_connection()
    cursor = connection.cursor()

    query = """
        SELECT 
            fi.date, 
            fi.actual_litres, 
            fi.amount_paid, 
            fi.petrol_station, 
            fi.odometer_reading
        FROM fuel_invoices fi
        JOIN fuel_vouchers fv ON fi.voucher_id = fv.id
        JOIN buses b ON fv.bus_id = b.id
        WHERE b.reg_no = %s AND fi.date BETWEEN %s AND %s
        ORDER BY fi.date ASC
    """
    cursor.execute(query, (reg_no, from_date, to_date))
    invoices = cursor.fetchall()
    connection.close()

    return jsonify(invoices)

#Bus statement
@app.route('/fleet/bus_statement')
def bus_statement():
    bus_id = request.args.get('bus_id')
    if not bus_id:
        flash("Please select a bus.", "error")
        return redirect(url_for('fleet_dashboard'))

    connection = get_db_connection()
    cursor = connection.cursor()

# Get current date and first day of month
    today = datetime.now().date()
    first_of_month = today.replace(day=1)
    
    # Handle date parameter
    from_date = request.args.get('from_date') or str(first_of_month)
    to_date = request.args.get('to_date') or str(today)


    


    # Fetch bus info
    cursor.execute("SELECT reg_no FROM buses WHERE id=%s", (bus_id,))
    bus = cursor.fetchone()
    if not bus:
        flash("Bus not found.", "error")
        return redirect(url_for('fleet_dashboard'))

    reg_no = bus['reg_no']

    # Fetch fuel invoices
    cursor.execute("""
    SELECT fi.date, fi.actual_litres, fi.amount_paid, fi.petrol_station, fi.odometer_reading
    FROM fuel_invoices fi
    JOIN fuel_vouchers fv ON fi.voucher_id = fv.id
    WHERE fv.bus_id = %s
      AND fi.date BETWEEN %s AND %s
    ORDER BY fi.date ASC
""", (bus_id, from_date, to_date))
    fuel_records = cursor.fetchall()

    # Fetch service records
    cursor.execute("""
    SELECT service_date, service_type, description, cost, garage_name, mileage_at_service
    FROM service_records
    WHERE bus_id = %s
      AND service_date BETWEEN %s AND %s
    ORDER BY service_date ASC
""", (bus_id, from_date, to_date))

    service_records = cursor.fetchall()

    connection.close()

    return render_template('bus_statement.html',
                           reg_no=reg_no,
                           fuel_records=fuel_records,
                           service_records=service_records,
                           from_date=from_date,
                           to_date=to_date)

#Edit Invoice
@app.route('/fleet/edit_invoice/<int:voucher_id>', methods=['GET', 'POST'])
def edit_invoice(voucher_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    # Fetch existing invoice
    cursor.execute("""
        SELECT fi.*, b.reg_no, fv.voucher_no
        FROM fuel_invoices fi
        JOIN fuel_vouchers fv ON fi.voucher_id = fv.id
        JOIN buses b ON fv.bus_id = b.id
        WHERE fv.id = %s
        ORDER BY fi.date DESC
        LIMIT 1
    """, (voucher_id,))
    invoice = cursor.fetchone()

    if not invoice:
        flash("No existing invoice found for this voucher.", "error")
        return redirect(url_for('voucher_register'))

    if request.method == 'POST':
        date = request.form.get('date')
        actual_litres = float(request.form.get('actual_litres'))
        amount_paid = float(request.form.get('amount_paid'))
        petrol_station = request.form.get('petrol_station')
        odometer_reading = int(request.form.get('odometer_reading'))
        remarks = request.form.get('remarks')

        cursor.execute("""
            UPDATE fuel_invoices
            SET date=%s, actual_litres=%s, amount_paid=%s, petrol_station=%s, odometer_reading=%s, remarks=%s
            WHERE id=%s
        """, (date, actual_litres, amount_paid, petrol_station, odometer_reading, remarks, invoice['id']))

        connection.commit()
        connection.close()

        flash("Invoice updated successfully.", "success")
        return redirect(url_for('voucher_register'))

    connection.close()
    return render_template('edit_invoice.html', invoice=invoice)
#Print Invoice

@app.route('/fleet/print_invoice/<int:voucher_id>')
def print_invoice(voucher_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT fi.*, b.reg_no, fv.voucher_no
        FROM fuel_invoices fi
        JOIN fuel_vouchers fv ON fi.voucher_id = fv.id
        JOIN buses b ON fv.bus_id = b.id
        WHERE fv.id = %s
    """, (voucher_id,))
    invoice = cursor.fetchone()
    connection.close()

    if not invoice:
        flash("Invoice not found.", "error")
        return redirect(url_for('voucher_register'))

    return render_template('print_invoice.html', invoice=invoice)

#Delete invoice

@app.route('/fleet/delete_invoice/<int:voucher_id>', methods=['POST'])
def delete_invoice(voucher_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("DELETE FROM fuel_invoices WHERE voucher_id = %s", (voucher_id,))
    connection.commit()
    connection.close()

    flash("Invoice deleted successfully.", "success")
    return redirect(url_for('voucher_register'))

# Edit Service Record
@app.route('/fleet/edit_service/<int:service_id>', methods=['GET', 'POST'])
def edit_service(service_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    # Fetch the service record
    cursor.execute("SELECT * FROM service_records WHERE id = %s", (service_id,))
    service = cursor.fetchone()
    if not service:
        flash("Service record not found.", "error")
        return redirect(url_for('service_register'))

    if request.method == 'POST':
        service_date = request.form.get('service_date')
        service_type = request.form.get('service_type')
        description = request.form.get('description')
        cost = float(request.form.get('cost') or 0)
        garage_name = request.form.get('garage_name')
        mileage = int(request.form.get('mileage_at_service') or 0)

        cursor.execute("""
            UPDATE service_records
            SET service_date=%s, service_type=%s, description=%s, cost=%s, garage_name=%s, mileage_at_service=%s
            WHERE id=%s
        """, (service_date, service_type, description, cost, garage_name, mileage, service_id))

        connection.commit()
        connection.close()

        flash("Service record updated successfully.", "success")
        return redirect(url_for('service_register'))

    connection.close()
    return render_template('edit_service.html', service=service)


# Delete Service Record
@app.route('/fleet/delete_service/<int:service_id>', methods=['POST'])
def delete_service(service_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("DELETE FROM service_records WHERE id = %s", (service_id,))
    connection.commit()
    connection.close()

    flash("Service record deleted.", "success")
    return redirect(url_for('service_register'))


@app.route('/debug/templates')
def debug_templates():
    try:
        from flask import render_template
        # Test rendering the template directly
        return render_template('fuel_consumption_report.html',
                            report=[],
                            from_date='2025-01-01',
                            to_date='2025-12-31',
                            report_title="Test",
                            current_date="01-01-2025",
                            date_range="Test Range",
                            back_url="#")
    except Exception as e:
        return f"Template error: {str(e)}", 500



if __name__ == '__main__':
     app.run(host='0.0.0.0', port=5000, debug=True)
     
     