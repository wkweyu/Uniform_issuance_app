from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import pymysql, hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from class_management_service import ClassManagementService, ValidationError, PromotionError

# Initialize extensions first (they'll be configured later)
db = SQLAlchemy()
csrf = CSRFProtect()
migrate = Migrate()



def create_app():
    app = Flask(__name__, static_folder='static')
    
    # Configuration
    app.secret_key = 'your_secret_key_please_change_in_production'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://schooluser:jbs@localhost/schoolmngt'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['WTF_CSRF_TIME_LIMIT'] = None  # CSRF token doesn't expire
    
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    
    # Custom filters and globals
    def format_currency(value):
        try:
            if value is None:
                return "0.00"
            num = float(value)
            return "{:,.2f}".format(num)
        except (ValueError, TypeError):
            return "0.00"
    
    app.jinja_env.filters['currency'] = format_currency
    app.jinja_env.globals['datetime'] = datetime
    
    # Make csrf_token available in all templates
    from flask_wtf.csrf import generate_csrf
    app.jinja_env.globals['csrf_token'] = generate_csrf
    
    return app

# Create the app
app = create_app()

# DB connection function (can stay outside or inside)
def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='schooluser',
        password='jbs',
        database='schoolmngt',
        cursorclass=pymysql.cursors.DictCursor
    )

# Add this model definition at the top of your file, after db = SQLAlchemy()

class UniformPrice(db.Model):
    __tablename__ = 'uniform_prices'
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(255))
    class_group = db.Column(db.String(255))
    price = db.Column(db.Numeric(10, 2))

# Then in your route, use the class name (not table name):
# existing = db.session.query(UniformPrice).filter_by(item_name=item_name).first()


# Rest of your routes...
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

def verify_legacy_password(input_password, stored_password):
    """
    Supports:
    - Plain text passwords
    - MD5 hashed passwords (legacy)
    """
    if not stored_password:
        return False

    # Plain text match
    if input_password == stored_password:
        return True

    # MD5 match
    md5_pass = hashlib.md5(input_password.encode()).hexdigest()
    return md5_pass == stored_password

from urllib.parse import quote

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            next_url = quote(request.url)
            return redirect(url_for('login', next=next_url))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'userNo' not in session:
            next_url = quote(request.url)
            return redirect(url_for('login', next=next_url))
        if not session.get('is_admin', False):
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'userNo' in session:
        return redirect(url_for('index'))

    next_url = request.args.get('next')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT userNo, username, pwd, access_flag, TA, StaffID
            FROM users
            WHERE username=%s
            LIMIT 1
        """, (username,))
        user = cursor.fetchone()
        connection.close()

        if not user or user['access_flag'] != 1:
            flash("Invalid username or password.", "error")
            return redirect(url_for('login'))

        if not verify_legacy_password(password, user['pwd']):
            flash("Invalid username or password.", "error")
            return redirect(url_for('login'))

        # ✅ Login success
        session['userNo'] = user['userNo']
        session['username'] = user['username']
        session['staff_id'] = user['StaffID']
        session['is_admin'] = bool(user['TA'])
        session['logged_in'] = True  # Add this flag

        # Set session to expire after 8 hours
        session.permanent = True
        app.permanent_session_lifetime = timedelta(hours=8)

        flash(f"Welcome {user['username']}", "success")

        return redirect(next_url or url_for('index'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('login'))



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
@login_required
def index():
    connection = get_db_connection()
    cursor = connection.cursor()

    # Active buses
    cursor.execute("SELECT COUNT(*) AS count FROM buses WHERE active=1")
    active_buses = cursor.fetchone()['count']

    # Today's fuel vouchers
    cursor.execute("SELECT COUNT(*) AS count FROM fuel_vouchers WHERE DATE(issued_on) = CURDATE()")
    vouchers_today = cursor.fetchone()['count']

    # Get current term_number and year from uniform_term_dates
    cursor.execute("""
        SELECT term_number, year 
        FROM uniform_term_dates 
        WHERE CURDATE() BETWEEN start_date AND end_date
        LIMIT 1
    """)
    term_info = cursor.fetchone()

    if term_info:
        term_number = term_info['term_number']
        year = term_info['year']
    else:
        term_number = None
        year = None

    # Pending uniform invoices for this term (if any)
    if term_info:
        cursor.execute("""
            SELECT COUNT(*) AS count 
            FROM uniform_receipts 
            WHERE term=%s AND yr=%s
        """, (term_number, year))
        uniform_issued = cursor.fetchone()['count']
    else:
        uniform_issued = 0

    connection.close()

    return render_template('index.html',
                           active_buses=active_buses,
                           vouchers_today=vouchers_today,
                           uniform_issued=uniform_issued,
                           term_number=term_number,
                           year=year)



# Uniform issuance form
@app.route('/issue_uniform', methods=['GET', 'POST'])
@login_required
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
            
            # Get uniform items for class group WITH STOCK INFO
            class_name = student['class_name']
            class_group = get_class_group(class_name)
            
            cursor.execute("""
                SELECT up.item_name, up.price, 
                       COALESCE(is.current_stock, 0) as current_stock,
                       COALESCE(is.reorder_level, 10) as reorder_level,
                       is.item_id
                FROM uniform_prices up
                LEFT JOIN item_stock is ON up.item_id = is.item_id
                WHERE up.class_group = %s
                ORDER BY up.item_name
            """, (class_group,))
            
            items = cursor.fetchall()
            
            # Check for low stock items
            low_stock_items = [item for item in items if item['current_stock'] <= item['reorder_level']]
            
            return render_template('issue_form.html',
                                   admno=admno,
                                   student_name=student['FName'],
                                   class_name=class_name,
                                   year=year,
                                   term=term,
                                   items=items,
                                   low_stock_items=low_stock_items)

    except Exception as e:
        app.logger.error(f"Database error: {str(e)}")
        flash('An error occurred while fetching student data.', 'error')
        return redirect(url_for('issue_uniform'))
    finally:
        if 'connection' in locals():
            connection.close()

#Enhance Submit issuance
@app.route('/submit_issuance', methods=['POST'])
@login_required
@csrf.exempt
def submit_issuance():
    try:
        data = request.get_json()
        connection = get_db_connection()
        
        with connection.cursor() as cursor:
            # 1. Generate receipt number
            receipt_no = generate_receipt_number(data['year'])
            total_amount = 0
            issuance_items = []
            
            # 2. First pass: Validate stock availability
            for item in data['items']:
                if item['quantity'] > 0:
                    cursor.execute("""
                        SELECT current_stock FROM item_stock 
                        WHERE item_name = %s
                    """, (item['item_name'],))
                    stock_info = cursor.fetchone()
                    
                    if not stock_info:
                        return jsonify({
                            'success': False,
                            'message': f'Item {item["item_name"]} not found in inventory'
                        }), 400
                    
                    if stock_info['current_stock'] < item['quantity']:
                        return jsonify({
                            'success': False,
                            'message': f'Insufficient stock for {item["item_name"]}. Available: {stock_info["current_stock"]}, Requested: {item["quantity"]}'
                        }), 400
                    
                    issuance_items.append({
                        'name': item['item_name'],
                        'quantity': item['quantity'],
                        'price': item['price']
                    })
            
            # 3. Second pass: Process issuance and deduct stock
            for item in issuance_items:
                line_total = item['quantity'] * item['price']
                total_amount += line_total
                
                # Insert into uniform_receipts
                cursor.execute("""
                    INSERT INTO uniform_receipts 
                    (AdmNo, student_name, class_name, item_name, quantity, price, total, yr, term, receipt_no, issued_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    data['admno'],
                    data['student_name'],
                    data['class_name'],
                    item['name'],
                    item['quantity'],
                    item['price'],
                    line_total,
                    data['year'],
                    data['term'],
                    receipt_no,
                    session.get('username', 'System')
                ))
                
                # Deduct from stock and record movement
                cursor.execute("""
                    UPDATE item_stock 
                    SET current_stock = current_stock - %s,
                        updated_at = NOW()
                    WHERE item_name = %s
                """, (item['quantity'], item['name']))
                
                # Get the updated stock level
                cursor.execute("""
                    SELECT current_stock FROM item_stock WHERE item_name = %s
                """, (item['name'],))
                new_stock = cursor.fetchone()['current_stock']
                
                # Record stock movement
                cursor.execute("""
                    INSERT INTO stock_movements 
                    (item_id, movement_type, quantity, previous_stock, new_stock, reference_no, student_admno, user_id, notes)
                    SELECT item_id, 'ISSUANCE', %s, current_stock + %s, %s, %s, %s, %s, %s
                    FROM item_stock 
                    WHERE item_name = %s
                """, (
                    item['quantity'],
                    item['quantity'],  # previous stock = new_stock + quantity
                    new_stock,
                    receipt_no,
                    data['admno'],
                    session.get('userNo'),
                    f"Issued to {data['student_name']} ({data['class_name']})",
                    item['name']
                ))
            
            # 4. Update fodebit (existing logic)
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
            
            # 5. Check for low stock alerts after issuance
            cursor.execute("""
                SELECT item_name, current_stock, reorder_level 
                FROM item_stock 
                WHERE current_stock <= reorder_level
            """)
            low_stock_items = cursor.fetchall()
            
            return jsonify({
                'success': True,
                'admno': data['admno'],
                'year': data['year'],
                'term': data['term'],
                'receipt_no': receipt_no,
                'total_amount': total_amount,
                'low_stock_warning': len(low_stock_items) > 0,
                'low_stock_items': low_stock_items
            })

    except pymysql.Error as e:
        if 'connection' in locals():
            connection.rollback()
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
@login_required
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
@login_required
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

@app.route('/admin/manage_uniform_items')
@login_required
def manage_uniform_items():
    """Manage uniform items with stock control - SINGLE SOURCE"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    connection = get_db_connection()
    
    try:
        with connection.cursor() as cursor:
            # Get all unique items with their prices and stock info
            cursor.execute("""
                SELECT 
                    up.item_name,
                    GROUP_CONCAT(DISTINCT up.class_group) as class_groups,
                    MAX(CASE WHEN up.class_group = 'Playgroup-PP2' THEN up.price ELSE NULL END) as price_pp2,
                    MAX(CASE WHEN up.class_group = 'Grade 1-3' THEN up.price ELSE NULL END) as price_13,
                    MAX(CASE WHEN up.class_group = 'Grade 4-6' THEN up.price ELSE NULL END) as price_46,
                    MAX(CASE WHEN up.class_group = 'Grade 7-9' THEN up.price ELSE NULL END) as price_79,
                    COALESCE(ist.current_stock, 0) as current_stock,
                    COALESCE(ist.reorder_level, 10) as reorder_level
                FROM uniform_prices up
                LEFT JOIN item_stock ist ON up.item_name = ist.item_name
                GROUP BY up.item_name
                ORDER BY up.item_name;
            """)
            
            items = cursor.fetchall()
            
            return render_template('manage_uniform_items.html', items=items)
    
    except Exception as e:
        app.logger.error(f"Error loading uniform items: {str(e)}")
        flash('An error occurred while loading uniform items', 'error')
        return redirect(url_for('index'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/add_uniform_item', methods=['POST'])
@login_required
def add_uniform_item():
    """Add new uniform item with proper stock initialization"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    try:
        item_name = request.form.get('item_name').strip()
        class_groups = request.form.getlist('class_groups[]')
        
        if not item_name:
            flash("Item name is required", "error")
            return redirect(url_for('manage_uniform_items'))
        
        if not class_groups:
            flash("Please select at least one class group", "error")
            return redirect(url_for('manage_uniform_items'))
        
        # Check for duplicate item (generic name only)
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM uniform_prices WHERE item_name = %s", (item_name,))
            existing = cursor.fetchone()['count']
            
            if existing > 0:
                flash(f"Item '{item_name}' already exists. Use 'Add Class Group' to add more groups.", "error")
                return redirect(url_for('manage_uniform_items'))
            
            # Start transaction
            connection.begin()
            
            # 1. Insert into item_stock
            cursor.execute("""
                INSERT INTO item_stock (item_name, current_stock, reorder_level)
                VALUES (%s, 0, 10)
            """, (item_name,))
            
            item_id = cursor.lastrowid
            
            # 2. Insert prices for each class group
            for group in class_groups:
                price_key = f'price_{group}'
                price_value = request.form.get(price_key, '0').strip()
                try:
                    price = float(price_value) if price_value else 0.0
                except ValueError:
                    price = 0.0
                
                cursor.execute("""
                    INSERT INTO uniform_prices (item_name, class_group, price, item_id)
                    VALUES (%s, %s, %s, %s)
                """, (item_name, group, price, item_id))
            
            connection.commit()
            flash(f"Item '{item_name}' added successfully with {len(class_groups)} class group(s)", "success")
            
    except Exception as e:
        if 'connection' in locals():
            connection.rollback()
        app.logger.error(f"Error adding item: {str(e)}")
        flash(f"Error adding item: {str(e)}", "error")
    finally:
        if 'connection' in locals():
            connection.close()
    
    return redirect(url_for('manage_uniform_items'))

@app.route('/admin/update_uniform_price', methods=['POST'])
@login_required
def update_uniform_price():
    """Update price for specific item and class group"""
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        data = request.get_json()
        item_name = data.get('item_name')
        class_group = data.get('class_group')
        price = float(data.get('price', 0))
        
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE uniform_prices 
                SET price = %s 
                WHERE item_name = %s AND class_group = %s
            """, (price, item_name, class_group))
            
            connection.commit()
            
            return jsonify({
                'success': True,
                'message': f'Price updated for {item_name} ({class_group})'
            })
            
    except Exception as e:
        app.logger.error(f"Error updating price: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error updating price: {str(e)}'
        }), 500
    finally:
        if 'connection' in locals():
            connection.close()

@app.route('/admin/add_class_group_to_item', methods=['POST'])
@login_required
def add_class_group_to_item():
    """Add new class group to existing item"""
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        item_name = request.form.get('item_name')
        class_group = request.form.get('class_group')
        price_value = request.form.get('price', '0').strip()
        try:
            price = float(price_value) if price_value else 0.0
        except ValueError:
            price = 0.0
        
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Check if already exists
            cursor.execute("""
                SELECT id FROM uniform_prices 
                WHERE item_name = %s AND class_group = %s
            """, (item_name, class_group))
            
            if cursor.fetchone():
                return jsonify({
                    'success': False,
                    'message': f'{class_group} already exists for {item_name}'
                })
            
            # Get item_id from stock table
            cursor.execute("SELECT item_id FROM item_stock WHERE item_name = %s", (item_name,))
            stock_item = cursor.fetchone()
            
            if not stock_item:
                return jsonify({
                    'success': False,
                    'message': f'Item {item_name} not found in inventory'
                })
            
            # Add the new class group
            cursor.execute("""
                INSERT INTO uniform_prices (item_name, class_group, price, item_id)
                VALUES (%s, %s, %s, %s)
            """, (item_name, class_group, price, stock_item['item_id']))
            
            connection.commit()
            
            return jsonify({
                'success': True,
                'message': f'{class_group} added to {item_name}'
            })
            
    except Exception as e:
        app.logger.error(f"Error adding class group: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error adding class group: {str(e)}'
        }), 500
    finally:
        if 'connection' in locals():
            connection.close()

@app.route('/admin/remove_class_group_from_item', methods=['POST'])
@login_required
def remove_class_group_from_item():
    """Remove class group from item"""
    if not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        item_name = request.form.get('item_name')
        class_group = request.form.get('class_group')
        
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Check if this is the last class group
            cursor.execute("""
                SELECT COUNT(*) as count FROM uniform_prices 
                WHERE item_name = %s
            """, (item_name,))
            
            group_count = cursor.fetchone()['count']
            
            if group_count <= 1:
                return jsonify({
                    'success': False,
                    'message': 'Cannot remove the last class group. Delete the item instead.'
                })
            
            # Remove the class group
            cursor.execute("""
                DELETE FROM uniform_prices 
                WHERE item_name = %s AND class_group = %s
            """, (item_name, class_group))
            
            connection.commit()
            
            return jsonify({
                'success': True,
                'message': f'{class_group} removed from {item_name}'
            })
            
    except Exception as e:
        app.logger.error(f"Error removing class group: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error removing class group: {str(e)}'
        }), 500
    finally:
        if 'connection' in locals():
            connection.close()

@app.route('/admin/delete_uniform_item', methods=['POST'])
@login_required
def delete_uniform_item():
    """Delete uniform item completely"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    try:
        item_name = request.form.get('item_name')
        
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Check if item has been issued
            cursor.execute("""
                SELECT COUNT(*) as count FROM uniform_receipts 
                WHERE item_name = %s
            """, (item_name,))
            
            issued_count = cursor.fetchone()['count']
            
            if issued_count > 0:
                flash(f'Cannot delete "{item_name}" - it has been issued to {issued_count} student(s)', 'error')
                return redirect(url_for('manage_uniform_items'))
            
            # Start transaction
            connection.begin()
            
            # Get item_id for cleanup
            cursor.execute("SELECT item_id FROM item_stock WHERE item_name = %s", (item_name,))
            stock_item = cursor.fetchone()
            
            if stock_item:
                # Delete from uniform_prices
                cursor.execute("DELETE FROM uniform_prices WHERE item_name = %s", (item_name,))
                
                # Delete from item_stock
                cursor.execute("DELETE FROM item_stock WHERE item_id = %s", (stock_item['item_id'],))
                
                # Delete from stock_movements
                cursor.execute("DELETE FROM stock_movements WHERE item_id = %s", (stock_item['item_id'],))
            
            connection.commit()
            flash(f'Item "{item_name}" deleted successfully', 'success')
            
    except Exception as e:
        if 'connection' in locals():
            connection.rollback()
        app.logger.error(f"Error deleting item: {str(e)}")
        flash(f'Error deleting item: {str(e)}', 'error')
    finally:
        if 'connection' in locals():
            connection.close()
    
    return redirect(url_for('manage_uniform_items'))

# Clean up duplicate items function
@app.route('/admin/cleanup_duplicate_items')
@login_required
def cleanup_duplicate_items():
    """Clean up duplicate items with grade-specific names"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Find items with grade-specific names
            cursor.execute("""
                SELECT DISTINCT item_name 
                FROM uniform_prices 
                WHERE item_name LIKE '%Grade 1%' 
                   OR item_name LIKE '%Grade 2%' 
                   OR item_name LIKE '%Grade 3%'
                   OR item_name LIKE '%Grade 4%'
                   OR item_name LIKE '%Grade 5%'
                   OR item_name LIKE '%Grade 6%'
                   OR item_name LIKE '%Grade 7%'
                   OR item_name LIKE '%Grade 8%'
                   OR item_name LIKE '%Grade 9%'
                   OR item_name LIKE '%Playgroup%'
                   OR item_name LIKE '%PP1%'
                   OR item_name LIKE '%PP2%'
            """)
            
            duplicate_items = [row['item_name'] for row in cursor.fetchall()]
            
            # For each duplicate, find the generic name
            for duplicate in duplicate_items:
                # Extract generic name (remove grade/class indicators)
                generic_name = duplicate.replace(' Grade 1', '').replace(' Grade 2', '').replace(' Grade 3', '')
                generic_name = generic_name.replace(' Grade 4', '').replace(' Grade 5', '').replace(' Grade 6', '')
                generic_name = generic_name.replace(' Grade 7', '').replace(' Grade 8', '').replace(' Grade 9', '')
                generic_name = generic_name.replace(' Playgroup', '').replace(' PP1', '').replace(' PP2', '')
                generic_name = generic_name.replace(' Playgroup-PP2', '').strip()
                
                # Check if generic item exists
                cursor.execute("SELECT COUNT(*) as count FROM uniform_prices WHERE item_name = %s", (generic_name,))
                generic_exists = cursor.fetchone()['count'] > 0
                
                if not generic_exists:
                    # Create generic item
                    # Get class group from duplicate name
                    class_group = None
                    if 'Grade 1' in duplicate or 'Grade 2' in duplicate or 'Grade 3' in duplicate:
                        class_group = 'Grade 1-3'
                    elif 'Grade 4' in duplicate or 'Grade 5' in duplicate or 'Grade 6' in duplicate:
                        class_group = 'Grade 4-6'
                    elif 'Grade 7' in duplicate or 'Grade 8' in duplicate or 'Grade 9' in duplicate:
                        class_group = 'Grade 7-9'
                    elif 'Playgroup' in duplicate or 'PP1' in duplicate or 'PP2' in duplicate:
                        class_group = 'Playgroup-PP2'
                    
                    if class_group:
                        # Get price from duplicate
                        cursor.execute("SELECT price FROM uniform_prices WHERE item_name = %s LIMIT 1", (duplicate,))
                        price_row = cursor.fetchone()
                        
                        if price_row:
                            # Create generic item
                            cursor.execute("""
                                INSERT IGNORE INTO item_stock (item_name, current_stock, reorder_level)
                                VALUES (%s, 0, 10)
                            """, (generic_name,))
                            
                            cursor.execute("SELECT item_id FROM item_stock WHERE item_name = %s", (generic_name,))
                            stock_item = cursor.fetchone()
                            
                            if stock_item:
                                cursor.execute("""
                                    INSERT INTO uniform_prices (item_name, class_group, price, item_id)
                                    VALUES (%s, %s, %s, %s)
                                """, (generic_name, class_group, price_row['price'], stock_item['item_id']))
            
            connection.commit()
            flash("Duplicate items cleaned up successfully", "success")
            
    except Exception as e:
        if 'connection' in locals():
            connection.rollback()
        app.logger.error(f"Error cleaning up duplicates: {str(e)}")
        flash(f"Error cleaning up duplicates: {str(e)}", "error")
    finally:
        if 'connection' in locals():
            connection.close()
    
    return redirect(url_for('manage_uniform_items'))

@app.route('/admin/prices/export')
@login_required
def export_prices():
    """Export prices to CSV"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("""
        SELECT item_name, class_group, price 
        FROM uniform_prices 
        ORDER BY item_name, class_group
    """)
    prices = cursor.fetchall()
    connection.close()
    
    # Generate CSV
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Item Name', 'Class Group', 'Price'])
    
    # Write data
    for price in prices:
        writer.writerow([price['item_name'], price['class_group'], price['price']])
    
    output.seek(0)
    
    # Create response
    from flask import Response
    response = Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=uniform_prices.csv"}
    )
    
    return response


@app.route('/admin/prices/import', methods=['GET', 'POST'])
@login_required
def import_prices():
    """Import prices from CSV"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
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
@login_required
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
@login_required
def reports_dashboard():
    return render_template('reports_dashboard.html')
#Student uniform report

@app.route("/reports/student_history/<admno>")
@login_required
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
@login_required
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
@login_required
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
@login_required
def student_search():
    results = []
    search_term = ""
    if request.method == "POST":
        search_term = request.form.get("search_term", "").strip()
        if not search_term:
            flash("Please enter an admission number or student name.", "error")
            return redirect(url_for("student_search"))
        
        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            # Search by admission number or name
            cursor.execute("""
                SELECT DISTINCT s.AdmNo, s.FName, s.MName, s.SName, 
                       c.class_name, a.thisYear
                FROM studentinfo s
                LEFT JOIN classallocation a ON s.AdmNo = a.AdmNo
                LEFT JOIN classes c ON a.classID = c.classID
                WHERE s.AdmNo LIKE %s 
                   OR CONCAT(s.FName, ' ', COALESCE(s.MName, ''), ' ', s.SName) LIKE %s
                ORDER BY s.FName, s.SName
                LIMIT 50
            """, (f"%{search_term}%", f"%{search_term}%"))
            results = cursor.fetchall()
        finally:
            connection.close()

    return render_template("report_student_search.html", results=results, search_term=search_term)
#cancel receipt
@app.route("/cancel_receipt/<receipt_no>", methods=["POST"])
@login_required
@csrf.exempt
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
@login_required
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
@login_required
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
@login_required
def fleet_dashboard():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT id, reg_no FROM buses WHERE active=1 ORDER BY reg_no")
    buses = cursor.fetchall()
    connection.close()

    return render_template('fleet_dashboard.html', buses=buses)


#Buses creation

@app.route('/fleet/buses', methods=['GET', 'POST'])
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
@csrf.exempt
def get_driver(bus_id):
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT driver_name FROM buses WHERE id=%s AND active=1", (bus_id,))
        bus = cursor.fetchone()
    connection.close()
    return jsonify({'driver_name': bus['driver_name'] if bus else ''})

#Service register
@app.route('/fleet/service_register')
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def test_css():
    return "<link rel='stylesheet' href='/static/css/tailwind.min.css'>Test Page"

@app.route('/fleet/fuel_consumption_chart')
@login_required
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
@login_required
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
@login_required
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
@login_required
@csrf.exempt
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def delete_service(service_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("DELETE FROM service_records WHERE id = %s", (service_id,))
    connection.commit()
    connection.close()

    flash("Service record deleted.", "success")
    return redirect(url_for('service_register'))


@app.route('/debug/templates')
@login_required
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
    
@app.route('/admit', methods=['GET', 'POST'])
@admin_required
def admit_student():
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        admno = request.form.get('admno').strip()
        fname = request.form.get('fname').strip()
        mname = request.form.get('mname', '').strip()
        lname = request.form.get('lname').strip()
        gender = request.form.get('gender')
        class_id = request.form.get('class_id')
        year = datetime.now().year

        try:
            # Check if admission number already exists
            cursor.execute("SELECT AdmNo FROM studentinfo WHERE AdmNo = %s", (admno,))
            if cursor.fetchone():
                flash(f"Admission number {admno} already exists!", "error")
            else:
                connection.begin()

                # Insert basic student info
                cursor.execute("""
                    INSERT INTO studentinfo (AdmNo, FName, MName, SName, Sex, blocked)
                    VALUES (%s, %s, %s, %s, %s, 0)
                """, (admno, fname, mname, lname, gender))

                # Assign to class
                cursor.execute("""
                    INSERT INTO classallocation (AdmNo, classID, thisYear, AllcDate)
                    VALUES (%s, %s, %s, NOW())
                """, (admno, class_id, year))

                connection.commit()
                flash(f"✓ Student {fname} {lname} admitted successfully. ID: {admno}", "success")
                return redirect(url_for('students_list'))

        except pymysql.IntegrityError as e:
            connection.rollback()
            flash(f"Admission number already in use. Choose another.", "error")
        except Exception as e:
            connection.rollback()
            flash(f"Error: {str(e)}", "error")

    # Get classes ordered by class_name
    cursor.execute("""
        SELECT classID, class_name FROM classes ORDER BY class_name
    """)
    classes = cursor.fetchall()
    connection.close()

    return render_template('student.html', classes=classes)

@app.route('/students')
@login_required
def students_list():
    connection = get_db_connection()
    cursor = connection.cursor()

    # Get current year
    term_cur, year_cur = get_current_term_and_year()

    # Optional search query from GET param `q` (admno or name)
    q = request.args.get('q', '').strip()
    if q:
        # Search by admission number or name, filtered by current year
        if year_cur:
            # Prefer allocation for current year, fall back to most recent allocation per student
            cursor.execute("""
                SELECT
                    s.AdmNo,
                    s.FName,
                    s.MName,
                    s.SName AS LName,
                    s.Sex AS Gender,
                    s.blocked AS Status,
                    COALESCE(
                        (SELECT class_name FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1
                        ) LIMIT 1),
                        (SELECT class_name FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                        ) LIMIT 1)
                    ) AS class_name,
                    COALESCE(
                        (SELECT class_group FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1
                        ) LIMIT 1),
                        (SELECT class_group FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                        ) LIMIT 1)
                    ) AS class_group,
                    COALESCE(
                        (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1),
                        (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1)
                    ) AS thisYear
                FROM studentinfo s
                WHERE s.AdmNo LIKE %s
                   OR CONCAT(s.FName, ' ', COALESCE(s.MName, ''), ' ', s.SName) LIKE %s
                ORDER BY s.FName, s.SName
                LIMIT 200
            """, (year_cur, year_cur, year_cur, f"%{q}%", f"%{q}%"))
        else:
            # If no current year, get most recent year
            # No current year defined - use most recent allocation per student
            cursor.execute("""
                SELECT
                    s.AdmNo,
                    s.FName,
                    s.MName,
                    s.SName AS LName,
                    s.Sex AS Gender,
                    s.blocked AS Status,
                    (SELECT class_name FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                    ) LIMIT 1) AS class_name,
                    (SELECT class_group FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                    ) LIMIT 1) AS class_group,
                    (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1) AS thisYear
                FROM studentinfo s
                WHERE s.AdmNo LIKE %s
                   OR CONCAT(s.FName, ' ', COALESCE(s.MName, ''), ' ', s.SName) LIKE %s
                ORDER BY s.FName, s.SName
                LIMIT 200
            """, (f"%{q}%", f"%{q}%"))

        students = cursor.fetchall()
        connection.close()
        return render_template('student_list.html', students=students, q=q)

    # Default listing (no search) - current year only
    if year_cur:
        cursor.execute("""
            SELECT
                s.AdmNo,
                s.FName,
                s.MName,
                s.SName AS LName,
                s.Sex AS Gender,
                s.blocked AS Status,
                COALESCE(
                    (SELECT class_name FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1
                    ) LIMIT 1),
                    (SELECT class_name FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                    ) LIMIT 1)
                ) AS class_name,
                COALESCE(
                    (SELECT class_group FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1
                    ) LIMIT 1),
                    (SELECT class_group FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                    ) LIMIT 1)
                ) AS class_group,
                COALESCE(
                    (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1),
                    (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1)
                ) AS thisYear
            FROM studentinfo s
            ORDER BY s.FName, s.SName
            LIMIT 20
        """, (year_cur, year_cur, year_cur))
    else:
        cursor.execute("""
            SELECT 
                s.AdmNo,
                s.FName,
                s.MName,
                s.SName AS LName,
                s.Sex AS Gender,
                s.blocked AS Status, 
                c.class_name,
                c.class_group,
                a.thisYear
            FROM studentinfo s
            LEFT JOIN classallocation a ON s.AdmNo = a.AdmNo
            LEFT JOIN classes c ON a.classID = c.classID
            ORDER BY a.AllcDate DESC, s.FName
            LIMIT 20
        """)
    students = cursor.fetchall()

    connection.close()
    return render_template('student_list.html', students=students, q='')

@app.route('/student/<int:admno>')
@login_required
def student_profile(admno):
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("SELECT * FROM studentinfo WHERE AdmNo = %s", (admno,))
    student = cursor.fetchone()
    
    # Fetch class information
    if student:
        cursor.execute("""
            SELECT c.class_name, c.class_group, c.classID, a.thisYear
            FROM classallocation a
            LEFT JOIN classes c ON a.classID = c.classID
            WHERE a.AdmNo = %s
            ORDER BY a.thisYear DESC
            LIMIT 1
        """, (admno,))
        class_info = cursor.fetchone()
        if class_info:
            student['class_name'] = class_info.get('class_name')
            student['thisYear'] = class_info.get('thisYear')
            student['class_group'] = class_info.get('class_group')
    
    connection.close()
    
    if not student:
        flash("Student not found", "error")
        return redirect(url_for('students_list'))
    
    return render_template('student_profile.html', student=student)

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')  # You'd need email field in users table
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        connection.close()
        
        if user:
            # Generate reset token (simplified)
            import secrets
            reset_token = secrets.token_urlsafe(32)
            
            # Store token in database (you need a password_resets table)
            # For now, just show a message
            flash("Password reset instructions would be sent to your email.", "info")
        else:
            flash("User not found.", "error")
        
        return redirect(url_for('login'))
    
    return render_template('reset_password.html')

@app.route('/profile')
@login_required
def user_profile():
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("""
        SELECT userNo, username, StaffID, TA, access_flag 
        FROM users 
        WHERE userNo = %s
    """, (session['userNo'],))
    user = cursor.fetchone()
    connection.close()
    
    return render_template('profile.html', user=user)

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for('change_password'))
        
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Verify current password
        cursor.execute("SELECT pwd FROM users WHERE userNo = %s", (session['userNo'],))
        user = cursor.fetchone()
        
        if not verify_legacy_password(current_password, user['pwd']):
            flash("Current password is incorrect.", "error")
            connection.close()
            return redirect(url_for('change_password'))
        
        # Update password (hash it properly)
        import hashlib
        hashed_password = hashlib.md5(new_password.encode()).hexdigest()
        
        cursor.execute("UPDATE users SET pwd = %s WHERE userNo = %s", 
                      (hashed_password, session['userNo']))
        connection.commit()
        connection.close()
        
        flash("Password changed successfully.", "success")
        return redirect(url_for('user_profile'))
    
    return render_template('change_password.html')

@app.route('/admin/settings')
@login_required
def admin_settings():
    """Admin settings dashboard"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    return render_template('admin_settings.html')

@app.route('/admin/term_dates', methods=['GET', 'POST'])
@login_required
def manage_term_dates():
    """Manage uniform term dates"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    now = datetime.now()

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            term_number = request.form.get('term_number')
            year = request.form.get('year')
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            
            # Validate dates
            if start_date >= end_date:
                flash("End date must be after start date.", "error")
            else:
                cursor.execute("""
                    INSERT INTO uniform_term_dates (term_number, year, start_date, end_date)
                    VALUES (%s, %s, %s, %s)
                """, (term_number, year, start_date, end_date))
                flash("Term date added successfully.", "success")
        
        elif action == 'edit':
            term_id = request.form.get('term_id')
            term_number = request.form.get('term_number')
            year = request.form.get('year')
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            
            cursor.execute("""
                UPDATE uniform_term_dates 
                SET term_number=%s, year=%s, start_date=%s, end_date=%s
                WHERE id=%s
            """, (term_number, year, start_date, end_date, term_id))
            flash("Term date updated successfully.", "success")
        
        elif action == 'delete':
            term_id = request.form.get('term_id')
            cursor.execute("DELETE FROM uniform_term_dates WHERE id=%s", (term_id,))
            flash("Term date deleted.", "success")
        
        connection.commit()
    
    # Get all term dates
    cursor.execute("""
        SELECT * FROM uniform_term_dates 
        ORDER BY year DESC, term_number DESC
    """)
    term_dates = cursor.fetchall()
    
    connection.close()
    return render_template('manage_term_dates.html', term_dates=term_dates,now=now)


@app.route('/admin/current_term')
@login_required
def current_term_status():
    """Show current term based on today's date"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    today = datetime.now().date()
    
    cursor.execute("""
        SELECT * FROM uniform_term_dates 
        WHERE %s BETWEEN start_date AND end_date
        LIMIT 1
    """, (today,))
    current_term = cursor.fetchone()
    
    cursor.execute("SELECT COUNT(*) as total FROM uniform_term_dates")
    total_terms = cursor.fetchone()['total']
    
    connection.close()
    
    return render_template('current_term.html', 
                          current_term=current_term, 
                          today=today,
                          total_terms=total_terms)


@app.route('/admin/manage_classes', methods=['GET'])
@login_required
@admin_required
def manage_classes():
    """Class Management Dashboard - Central hub for class administration"""
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        # Get statistics
        with connection.cursor() as cursor:
            # Academic years
            cursor.execute("SELECT COUNT(*) as count FROM academic_years")
            academic_years_count = cursor.fetchone()['count']
            
            # Total classes
            cursor.execute("SELECT COUNT(*) as count FROM classes")
            total_classes = cursor.fetchone()['count']
            
            # Total students
            cursor.execute("SELECT COUNT(*) as count FROM class_allocation WHERE is_current = TRUE")
            total_students = cursor.fetchone()['count']
            
            # Total subjects
            cursor.execute("SELECT COUNT(*) as count FROM subjects")
            total_subjects = cursor.fetchone()['count']
            
            # Current year
            cursor.execute("SELECT year FROM academic_years WHERE is_current = TRUE LIMIT 1")
            result = cursor.fetchone()
            current_year = result['year'] if result else None
            
            # Get all classes with details
            cursor.execute("""
                SELECT c.classID, c.class_name, c.class_group, c.stream_code, 
                       c.display_name, a.year, COUNT(ca.id) as student_count
                FROM classes c
                LEFT JOIN academic_years a ON c.academic_year_id = a.id
                LEFT JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE
                GROUP BY c.classID
                ORDER BY a.year DESC, c.class_name ASC
            """)
            classes = cursor.fetchall()
            
            # Get all streams
            cursor.execute("""
                SELECT id, code, name, is_active FROM stream_settings 
                WHERE is_active = TRUE
                ORDER BY code
            """)
            streams = cursor.fetchall()
        
        return render_template('class_management_dashboard.html',
                             academic_years_count=academic_years_count,
                             total_classes=total_classes,
                             total_students=total_students,
                             total_subjects=total_subjects,
                             current_year=current_year,
                             classes=classes,
                             streams=streams)
    except Exception as e:
        app.logger.error(f"Error loading class management dashboard: {str(e)}")
        flash(f"Error loading dashboard: {str(e)}", "error")
        return redirect(url_for('index'))
    finally:
        if connection:
            connection.close()


@app.route('/admin/classes/<int:class_id>/edit', methods=['POST'])
@login_required
def edit_class(class_id):
    """Edit class name and group"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Admin access required'}), 403
    
    class_name = request.form.get('class_name', '').strip()
    class_group = request.form.get('class_group', 'Grade 1-3')
    
    if not class_name:
        return jsonify({'error': 'Class name cannot be empty'}), 400
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        cursor.execute("""
            UPDATE classes SET class_name = %s, class_group = %s WHERE classID = %s
        """, (class_name, class_group, class_id))
        connection.commit()
        connection.close()
        flash(f"✓ Class updated to '{class_name}' ({class_group}).", "success")
        return redirect(url_for('manage_classes'))
    except Exception as e:
        connection.close()
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('manage_classes'))


@app.route('/admin/classes/<int:class_id>/delete', methods=['POST'])
@login_required
def delete_class(class_id):
    """Delete class"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Admin access required'}), 403
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # Check if class has students
        cursor.execute("""
            SELECT COUNT(*) as count FROM classallocation WHERE classID = %s
        """, (class_id,))
        result = cursor.fetchone()
        student_count = result['count'] if result else 0
        
        if student_count > 0:
            connection.close()
            return jsonify({
                'error': 'Cannot delete',
                'message': f'Class has {student_count} student(s). Reassign students first.'
            }), 400
        
        # Delete the class
        cursor.execute("DELETE FROM classes WHERE classID = %s", (class_id,))
        connection.commit()
        connection.close()
        
        return jsonify({'message': '✓ Class deleted successfully.'})
    except Exception as e:
        connection.close()
        return jsonify({'error': str(e)}), 500





@app.route('/admin/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    """User management system for administrators"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create':
            # Create new user
            username = request.form.get('username', '').strip()
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')
            staff_id = request.form.get('staff_id', '').strip()
            is_admin = 1 if request.form.get('is_admin') == 'on' else 0
            is_active = 1 if request.form.get('is_active') == 'on' else 0
            
            # Validate inputs
            if not username:
                flash("Username is required.", "error")
                connection.close()
                return redirect(url_for('manage_users'))
            
            if not password:
                flash("Password is required.", "error")
                connection.close()
                return redirect(url_for('manage_users'))
            
            if password != confirm_password:
                flash("Passwords do not match.", "error")
                connection.close()
                return redirect(url_for('manage_users'))
            
            # Check if username already exists
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE username = %s", (username,))
            existing_user = cursor.fetchone()['count']
            
            if existing_user > 0:
                flash(f"Username '{username}' already exists.", "error")
                connection.close()
                return redirect(url_for('manage_users'))
            
            # Hash the password (using MD5 for legacy compatibility)
            import hashlib
            hashed_password = hashlib.md5(password.encode()).hexdigest()
            
            # Create user
            cursor.execute("""
                INSERT INTO users (username, pwd, access_flag, TA, StaffID)
                VALUES (%s, %s, %s, %s, %s)
            """, (username, hashed_password, is_active, is_admin, staff_id))
            
            flash(f"User '{username}' created successfully.", "success")
        
        elif action == 'edit':
            # Edit existing user
            user_no = request.form.get('user_no')
            username = request.form.get('username', '').strip()
            staff_id = request.form.get('staff_id', '').strip()
            is_admin = 1 if request.form.get('is_admin') == 'on' else 0
            is_active = 1 if request.form.get('is_active') == 'on' else 0
            
            # Update user
            cursor.execute("""
                UPDATE users 
                SET username = %s, TA = %s, access_flag = %s, StaffID = %s
                WHERE userNo = %s
            """, (username, is_admin, is_active, staff_id, user_no))
            
            flash(f"User '{username}' updated successfully.", "success")
        
        elif action == 'change_password':
            # Change user password
            user_no = request.form.get('user_no')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
                connection.close()
                return redirect(url_for('manage_users'))
            
            import hashlib
            hashed_password = hashlib.md5(new_password.encode()).hexdigest()
            
            cursor.execute("""
                UPDATE users SET pwd = %s WHERE userNo = %s
            """, (hashed_password, user_no))
            
            # Get username for message
            cursor.execute("SELECT username FROM users WHERE userNo = %s", (user_no,))
            user = cursor.fetchone()
            flash(f"Password for '{user['username']}' changed successfully.", "success")
        
        elif action == 'toggle_status':
            # Toggle user active/inactive
            user_no = request.form.get('user_no')
            
            cursor.execute("""
                UPDATE users 
                SET access_flag = NOT access_flag 
                WHERE userNo = %s
            """, (user_no,))
            
            # Get username for message
            cursor.execute("SELECT username FROM users WHERE userNo = %s", (user_no,))
            user = cursor.fetchone()
            flash(f"User status for '{user['username']}' updated.", "success")
        
        elif action == 'delete':
            # Delete user (with confirmation)
            user_no = request.form.get('user_no')
            
            # Prevent deleting yourself
            if int(user_no) == session['userNo']:
                flash("You cannot delete your own account.", "error")
                connection.close()
                return redirect(url_for('manage_users'))
            
            # Get username before deletion
            cursor.execute("SELECT username FROM users WHERE userNo = %s", (user_no,))
            user = cursor.fetchone()
            username = user['username'] if user else 'Unknown'
            
            cursor.execute("DELETE FROM users WHERE userNo = %s", (user_no,))
            flash(f"User '{username}' deleted.", "success")
        
        connection.commit()
    
    # Get all users
    cursor.execute("""
        SELECT userNo, username, StaffID, TA as is_admin, access_flag as is_active,
               CASE 
                 WHEN userNo = %s THEN 1 
                 ELSE 0 
               END as is_current_user
        FROM users 
        ORDER BY username
    """, (session['userNo'],))
    
    users = cursor.fetchall()
    
    # Get user statistics
    cursor.execute("""
        SELECT 
            COUNT(*) as total_users,
            SUM(TA) as admin_count,
            SUM(access_flag) as active_count,
            SUM(CASE WHEN TA = 0 THEN 1 ELSE 0 END) as staff_count
        FROM users
    """)
    stats = cursor.fetchone()
    
    connection.close()
    
    return render_template('manage_users.html', users=users, stats=stats)


@app.route('/admin/users/<int:user_no>/edit')
@login_required
def edit_user_modal(user_no):
    """Return user data for editing in modal"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("""
        SELECT userNo, username, StaffID, TA as is_admin, access_flag as is_active
        FROM users WHERE userNo = %s
    """, (user_no,))
    
    user = cursor.fetchone()
    connection.close()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify(user)


@app.route('/admin/user_activity')
@login_required
def user_activity_log():
    """View user activity log (simplified version)"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    # You would need an activity_log table for this
    # For now, we'll show recent uniform issuances as example activity
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("""
        SELECT 
            ur.issued_by as username,
            COUNT(*) as activity_count,
            MAX(ur.issued_on) as last_activity,
            SUM(ur.total) as total_value
        FROM uniform_receipts ur
        WHERE ur.issued_by IS NOT NULL
        GROUP BY ur.issued_by
        ORDER BY last_activity DESC
        LIMIT 20
    """)
    
    activities = cursor.fetchall()
    connection.close()
    
    return render_template('user_activity.html', activities=activities)

@app.context_processor
def inject_now():
    """Make current datetime available in all templates as 'now'"""
    return {'now': datetime.utcnow()}

"""
@app.route('/admin/add_uniform_item', methods=['POST'])
@admin_required
def add_uniform_item():
    if request.method == 'POST':
        item_name = request.form.get('item_name')
        default_price = float(request.form.get('default_price', 0.00))
        category = request.form.get('category', '')
        description = request.form.get('description', '')
        
        # Get selected class groups (default to all if none selected)
        selected_groups = request.form.getlist('class_groups')
        if not selected_groups:
            # If no groups selected, default to all
            selected_groups = ['Playgroup-PP2', 'Grade 1-3', 'Grade 4-6', 'Grade 7-9']
        
        # Check if item already exists - FIXED: Use UniformPrice (class name), not uniform_prices (table name)
        existing = db.session.query(UniformPrice).filter_by(item_name=item_name).first()
        if existing:
            flash('Item already exists!', 'warning')
            return redirect(url_for('manage_uniform_prices'))
        
        # Add item with default price for selected class groups only
        for group in selected_groups:
            new_price = UniformPrice(
                item_name=item_name,
                class_group=group,
                price=default_price
            )
            db.session.add(new_price)
        
        db.session.commit()
        flash(f'Item "{item_name}" added successfully for {len(selected_groups)} class group(s)!', 'success')
        return redirect(url_for('manage_uniform_prices'))


@app.route('/admin/delete_uniform_item/<item_name>', methods=['DELETE'])
def delete_uniform_item(item_name):
    try:
        # FIXED: Use UniformPrice model class
        deleted_count = UniformPrice.query.filter_by(item_name=item_name).delete()
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Deleted "{item_name}" and {deleted_count} price records'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/admin/save_uniform_prices', methods=['POST'])
def save_uniform_prices():
    form_data = request.form
    
    for key, value in form_data.items():
        if key.startswith('price_'):
            parts = key.split('_')
            if len(parts) >= 3:
                item_name = parts[1]
                class_group = '_'.join(parts[2:])  # Handle groups with hyphens
                
                # Find or create price record - FIXED: Use UniformPrice model
                price_record = UniformPrice.query.filter_by(
                    item_name=item_name,
                    class_group=class_group
                ).first()
                
                if not price_record:
                    price_record = UniformPrice(
                        item_name=item_name,
                        class_group=class_group,
                        price=float(value) if value else 0.00
                    )
                    db.session.add(price_record)
                else:
                    price_record.price = float(value) if value else 0.00
    
    db.session.commit()
    flash('All prices saved successfully!', 'success')
    return redirect(url_for('manage_uniform_prices'))
"""

@app.route('/admin/export_uniform_prices')
def export_uniform_prices():
    # Export logic here
    pass

@app.route('/manage_stock', methods=['GET', 'POST'])
@login_required
def manage_stock():
    connection = get_db_connection()
    
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add_stock':
                item_name = request.form.get('item_name')
                quantity = int(request.form.get('quantity', 0))
                supplier = request.form.get('supplier', '')
                purchase_ref = request.form.get('purchase_ref', '')
                
                with connection.cursor() as cursor:
                    # Ensure item_stock row exists for this item (create if missing)
                    cursor.execute("SELECT item_id FROM item_stock WHERE item_name = %s", (item_name,))
                    stock_row = cursor.fetchone()
                    if not stock_row:
                        cursor.execute("INSERT INTO item_stock (item_name, current_stock, reorder_level, updated_at) VALUES (%s, 0, 10, NOW())", (item_name,))
                        # ensure row is available for subsequent SELECTs
                        connection.commit()
                        cursor.execute("SELECT item_id FROM item_stock WHERE item_name = %s", (item_name,))
                        stock_row = cursor.fetchone()
                    # Update stock
                    cursor.execute("""
                        UPDATE item_stock 
                        SET current_stock = current_stock + %s,
                            last_restock_date = CURDATE(),
                            updated_at = NOW()
                        WHERE item_name = %s
                    """, (quantity, item_name))
                    
                    # Record movement
                    cursor.execute("""
                        INSERT INTO stock_movements 
                        (item_id, movement_type, quantity, reference_no, notes, user_id)
                        SELECT item_id, 'PURCHASE', %s, %s, %s, %s
                        FROM item_stock 
                        WHERE item_name = %s
                    """, (quantity, purchase_ref, f"Restock from {supplier}", session.get('userNo'), item_name))
                    
                    connection.commit()
                    flash(f'Added {quantity} units to {item_name}', 'success')
            
            elif action == 'adjust_stock':
                item_name = request.form.get('item_name')
                new_quantity = int(request.form.get('new_quantity', 0))
                reason = request.form.get('reason', '')
                
                with connection.cursor() as cursor:
                    # Get current stock
                    cursor.execute("""
                        SELECT current_stock FROM item_stock WHERE item_name = %s
                    """, (item_name,))
                    current = cursor.fetchone()
                    # If no item_stock row exists, create it with 0 current_stock
                    if not current:
                        cursor.execute("INSERT INTO item_stock (item_name, current_stock, reorder_level, updated_at) VALUES (%s, 0, 10, NOW())", (item_name,))
                        connection.commit()
                        cursor.execute("SELECT current_stock FROM item_stock WHERE item_name = %s", (item_name,))
                        current = cursor.fetchone()

                    if current:
                        adjustment = new_quantity - current['current_stock']
                        
                        # Update stock
                        cursor.execute("""
                            UPDATE item_stock 
                            SET current_stock = %s,
                                updated_at = NOW()
                            WHERE item_name = %s
                        """, (new_quantity, item_name))
                        
                        # Record adjustment
                        cursor.execute("""
                            INSERT INTO stock_movements 
                            (item_id, movement_type, quantity, previous_stock, new_stock, notes, user_id)
                            SELECT item_id, 'ADJUSTMENT', %s, %s, %s, %s, %s
                            FROM item_stock 
                            WHERE item_name = %s
                        """, (adjustment, current['current_stock'], new_quantity, reason, session.get('userNo'), item_name))
                        
                        connection.commit()
                        flash(f'Stock adjusted for {item_name}', 'success')
            
            return redirect(url_for('manage_stock'))
        
        # GET request: Show stock management page
        with connection.cursor() as cursor:
            # Get all items with stock info
            cursor.execute("""
                SELECT up.item_name, 
                       GROUP_CONCAT(DISTINCT up.class_group ORDER BY up.class_group) as class_groups,
                       COALESCE(ist.current_stock, 0) as current_stock,
                       COALESCE(ist.reorder_level, 10) as reorder_level,
                       ist.last_restock_date
                FROM uniform_prices up
                LEFT JOIN item_stock ist ON up.item_name = ist.item_name
                GROUP BY up.item_name, ist.current_stock, ist.reorder_level, ist.last_restock_date
                ORDER BY up.item_name
            """)
            items = cursor.fetchall()
            
            # Get low stock items
            cursor.execute("""
                SELECT * FROM item_stock 
                WHERE current_stock <= reorder_level 
                ORDER BY current_stock ASC
            """)
            low_stock_items = cursor.fetchall()
            
            # Get recent stock movements
            cursor.execute("""
                SELECT sm.*, ist.item_name 
                FROM stock_movements sm
                JOIN item_stock ist ON sm.item_id = ist.item_id
                ORDER BY sm.movement_date DESC 
                LIMIT 50
            """)
            recent_movements = cursor.fetchall()
            
            return render_template('manage_stock.html',
                                   items=items,
                                   low_stock_items=low_stock_items,
                                   recent_movements=recent_movements)
    
    except Exception as e:
        app.logger.error(f"Stock management error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('manage_uniform_items'))  # Redirect to items list instead
    finally:
        if connection:
            connection.close()

@app.route('/stock_report')
@login_required
def stock_report():
    connection = get_db_connection()
    
    try:
        with connection.cursor() as cursor:
            # Get date range from request
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            # Build query with optional date filter
            query = """
                SELECT sm.movement_date, is.item_name, sm.movement_type, 
                       sm.quantity, sm.previous_stock, sm.new_stock,
                       sm.reference_no, sm.student_admno, sm.notes,
                       u.username
                FROM stock_movements sm
                JOIN item_stock is ON sm.item_id = is.item_id
                LEFT JOIN users u ON sm.user_id = u.id
                WHERE 1=1
            """
            params = []
            
            if start_date:
                query += " AND DATE(sm.movement_date) >= %s"
                params.append(start_date)
            
            if end_date:
                query += " AND DATE(sm.movement_date) <= %s"
                params.append(end_date)
            
            query += " ORDER BY sm.movement_date DESC"
            
            cursor.execute(query, params)
            movements = cursor.fetchall()
            
            # Get summary statistics
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT item_id) as total_items,
                    SUM(CASE WHEN current_stock <= reorder_level THEN 1 ELSE 0 END) as low_stock_count,
                    SUM(current_stock) as total_stock_value
                FROM item_stock
            """)
            summary = cursor.fetchone()
            
            return render_template('stock_report.html',
                                   movements=movements,
                                   summary=summary,
                                   start_date=start_date,
                                   end_date=end_date)
    
    except Exception as e:
        app.logger.error(f"Stock report error: {str(e)}")
        flash('An error occurred while generating stock report', 'error')
        return redirect(url_for('manage_stock'))
    finally:
        if connection:
            connection.close()


@app.route('/print_stock_levels')
@login_required
def print_stock_levels():
    """Printable view of current stock levels with reorder thresholds."""
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT up.item_name, 
                       GROUP_CONCAT(DISTINCT up.class_group ORDER BY up.class_group) as class_groups,
                       COALESCE(ist.current_stock, 0) as current_stock,
                       COALESCE(ist.reorder_level, 10) as reorder_level,
                       ist.last_restock_date
                FROM uniform_prices up
                LEFT JOIN item_stock ist ON up.item_name = ist.item_name
                GROUP BY up.item_name, ist.current_stock, ist.reorder_level, ist.last_restock_date
                ORDER BY up.item_name
            """)
            items = cursor.fetchall()

        from datetime import datetime
        return render_template('print_stock_levels.html', items=items, now=datetime.now())

    except Exception as e:
        app.logger.error(f"Print stock levels error: {str(e)}")
        flash('Error generating stock list', 'error')
        return redirect(url_for('manage_stock'))
    finally:
        if connection:
            connection.close()


@app.route('/stock_ledger')
@login_required
def stock_ledger():
    """Stock ledger showing IN (purchases) and OUT (issuances) for each item"""
    connection = get_db_connection()
    
    try:
        item_name = request.args.get('item_name')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        with connection.cursor() as cursor:
            # Get list of items
            cursor.execute("""
                SELECT DISTINCT item_name FROM uniform_prices 
                ORDER BY item_name
            """)
            items = cursor.fetchall()
            
            # Get ledger data for selected item
            ledger_data = []
            current_balance = 0
            
            if item_name:
                query = """
                    SELECT 
                        sm.movement_date,
                        sm.movement_type,
                        sm.quantity,
                        CASE WHEN sm.movement_type = 'ISSUANCE' THEN sm.quantity ELSE 0 END as stock_out,
                        CASE WHEN sm.movement_type IN ('PURCHASE', 'RETURN') THEN sm.quantity ELSE 0 END as stock_in,
                        sm.previous_stock,
                        sm.new_stock,
                        sm.reference_no,
                        sm.student_admno,
                        sm.notes,
                        u.username
                    FROM stock_movements sm
                    JOIN item_stock ist ON sm.item_id = ist.item_id
                    LEFT JOIN users u ON sm.user_id = u.userNo
                    WHERE ist.item_name = %s
                """
                params = [item_name]
                
                if date_from:
                    query += " AND DATE(sm.movement_date) >= %s"
                    params.append(date_from)
                
                if date_to:
                    query += " AND DATE(sm.movement_date) <= %s"
                    params.append(date_to)
                
                query += " ORDER BY sm.movement_date ASC, sm.movement_id ASC"
                
                cursor.execute(query, params)
                raw_ledger = cursor.fetchall()
                
                # Calculate running balance for each entry
                ledger_data = []
                running_balance = 0
                
                for row in raw_ledger:
                    # Calculate change based on movement type
                    if row['movement_type'] == 'ISSUANCE':
                        running_balance -= row['quantity']
                    elif row['movement_type'] in ('PURCHASE', 'RETURN'):
                        running_balance += row['quantity']
                    elif row['movement_type'] == 'ADJUSTMENT':
                        # For adjustments, calculate the difference
                        adjustment = row['new_stock'] - row['previous_stock']
                        running_balance = row['new_stock']
                    
                    # Add running_balance to row for template
                    row_dict = dict(row)
                    row_dict['running_balance'] = running_balance
                    ledger_data.append(row_dict)
                
                # Get current stock
                cursor.execute("SELECT current_stock FROM item_stock WHERE item_name = %s", (item_name,))
                stock_info = cursor.fetchone()
                current_balance = stock_info['current_stock'] if stock_info else 0
                
                # Calculate summary
                total_in = sum(row['stock_in'] for row in ledger_data)
                total_out = sum(row['stock_out'] for row in ledger_data)
            else:
                total_in = 0
                total_out = 0
            
            from datetime import datetime
            return render_template('stock_ledger.html',
                                   items=items,
                                   selected_item=item_name,
                                   ledger_data=ledger_data,
                                   current_balance=current_balance,
                                   total_in=total_in,
                                   total_out=total_out,
                                   date_from=date_from,
                                   date_to=date_to,
                                   now=datetime.now())
    
    except Exception as e:
        app.logger.error(f"Stock ledger error: {str(e)}")
        flash(f'Error loading stock ledger: {str(e)}', 'error')
        return redirect(url_for('manage_uniform_items'))
    finally:
        if connection:
            connection.close()


# ============================================================================
# CLASS MANAGEMENT ROUTES (Phase 3: Production-Ready Implementation)
# ============================================================================

@app.route('/admin/classes/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_class():
    """Create a new class with auto group assignment and stream selection."""
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        if request.method == 'POST':
            # Validate and create class
            class_name = request.form.get('class_name', '').strip()
            academic_year_id = int(request.form.get('academic_year_id'))
            class_group_code = request.form.get('class_group_code')
            stream_code = request.form.get('stream_code')
            
            # Validate class name
            if not class_name:
                flash('Class name is required', 'error')
                return redirect(url_for('create_class'))
            
            # Validate inputs
            if not service.validate_stream(stream_code):
                flash(f'Invalid stream: {stream_code}', 'error')
                return redirect(url_for('create_class'))
            
            # Create class
            class_rec = service.create_class(
                academic_year_id=academic_year_id,
                class_group_code=class_group_code,
                stream_code=stream_code,
                created_by=session.get('userNo'),
                class_name=class_name
            )
            
            flash(f'✅ Class created: {class_rec["display_name"]}', 'success')
            return redirect(url_for('manage_classes'))
        
        # GET: Show form
        years = service.get_all_academic_years()
        groups = [{'code': k, 'name': v['name']} for k, v in service.get_class_groups().items()]
        streams = service.get_allowed_streams()
        
        return render_template('create_class.html', 
                             years=years, 
                             groups=groups, 
                             streams=streams)
    
    except ValidationError as e:
        flash(f'Validation error: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    except Exception as e:
        app.logger.error(f"Create class error: {str(e)}")
        flash(f'Error creating class: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()


@app.route('/admin/classes/promote', methods=['GET', 'POST'])
@login_required
@admin_required
def promote_students():
    """Promote students from one class to another (atomic operation with audit)."""
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        if request.method == 'POST':
            old_class_id = int(request.form.get('old_class_id'))
            new_class_id = int(request.form.get('new_class_id'))
            
            # Execute promotion (atomic with rollback)
            result = service.promote_students(
                old_class_id=old_class_id,
                new_class_id=new_class_id,
                promoted_by=session.get('userNo'),
                notes=request.form.get('notes', '')
            )
            
            flash(f"✅ Promoted {result['students_promoted']} students (Batch: {result['batch_id']})", 'success')
            return redirect(url_for('manage_classes'))
        
        # GET: Show form with available classes
        years = service.get_all_academic_years()
        
        return render_template('promote_students.html', years=years)
    
    except PromotionError as e:
        flash(f'Promotion failed: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    except Exception as e:
        app.logger.error(f"Promote students error: {str(e)}")
        flash(f'Error promoting students: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()


@app.route('/admin/manage_streams', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_streams():
    """Manage available streams (A, B, C, D, etc.)."""
    connection = None
    try:
        connection = get_db_connection()
        
        with connection.cursor() as cursor:
            if request.method == 'POST':
                action = request.form.get('action')
                
                if action == 'add':
                    stream_code = request.form.get('stream_code', '').strip().upper()
                    stream_name = request.form.get('stream_name', '').strip()
                    
                    if not stream_code or not stream_name:
                        flash('Stream code and name are required', 'error')
                    elif len(stream_code) > 1:
                        flash('Stream code must be a single character', 'error')
                    else:
                        try:
                            cursor.execute("""
                                INSERT INTO stream_settings (school_id, code, name, is_active)
                                VALUES (1, %s, %s, TRUE)
                            """, (stream_code, stream_name))
                            connection.commit()
                            flash(f'✅ Stream {stream_code} added successfully', 'success')
                        except pymysql.IntegrityError:
                            flash(f'Stream {stream_code} already exists', 'error')
                
                elif action == 'toggle':
                    stream_id = int(request.form.get('stream_id'))
                    cursor.execute("SELECT is_active FROM stream_settings WHERE id = %s", (stream_id,))
                    result = cursor.fetchone()
                    if result:
                        new_status = not result['is_active']
                        cursor.execute("UPDATE stream_settings SET is_active = %s WHERE id = %s", 
                                     (new_status, stream_id))
                        connection.commit()
                        status_text = "activated" if new_status else "deactivated"
                        flash(f'✅ Stream {status_text} successfully', 'success')
                
                elif action == 'delete':
                    stream_id = int(request.form.get('stream_id'))
                    # Check if stream is in use
                    cursor.execute("SELECT COUNT(*) as count FROM classes WHERE stream_code = (SELECT code FROM stream_settings WHERE id = %s)", (stream_id,))
                    if cursor.fetchone()['count'] > 0:
                        flash('Cannot delete stream - it is currently in use by classes', 'error')
                    else:
                        cursor.execute("DELETE FROM stream_settings WHERE id = %s", (stream_id,))
                        connection.commit()
                        flash('✅ Stream deleted successfully', 'success')
            
            # Get all streams
            cursor.execute("""
                SELECT id, code, name, is_active 
                FROM stream_settings 
                WHERE school_id = 1
                ORDER BY code
            """)
            streams = cursor.fetchall()
        
        return render_template('manage_streams.html', streams=streams)
    
    except Exception as e:
        app.logger.error(f"Manage streams error: {str(e)}")
        flash(f'Error managing streams: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()


@app.route('/admin/class/<int:class_id>/subjects', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_class_subjects(class_id):
    """Allocate subjects to a class."""
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        if request.method == 'POST':
            subject_ids = request.form.getlist('subject_ids')
            is_compulsory = request.form.get('is_compulsory') == 'on'
            
            # Allocate subjects to class
            service.allocate_subjects_to_class(
                class_id=class_id,
                subject_ids=[int(sid) for sid in subject_ids],
                compulsory=is_compulsory
            )
            
            flash('✅ Subjects allocated to class', 'success')
            return redirect(url_for('manage_classes'))
        
        # GET: Show form with available subjects
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, code, name FROM subjects WHERE is_active = TRUE ORDER BY code")
            subjects = cursor.fetchall()
            
            # Get already allocated subjects
            cursor.execute("SELECT subject_id FROM class_subjects WHERE class_id = %s AND is_active = TRUE", (class_id,))
            allocated = [row['subject_id'] for row in cursor.fetchall()]
        
        return render_template('manage_class_subjects.html',
                             class_id=class_id,
                             subjects=subjects,
                             allocated_subject_ids=allocated)
    
    except Exception as e:
        app.logger.error(f"Manage class subjects error: {str(e)}")
        flash(f'Error managing subjects: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()


@app.route('/admin/teacher/allocate', methods=['GET', 'POST'])
@login_required
@admin_required
def allocate_teacher():
    """Assign a teacher to teach a subject in a class."""
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        if request.method == 'POST':
            teacher_id = int(request.form.get('teacher_id'))
            class_id = int(request.form.get('class_id'))
            subject_id = int(request.form.get('subject_id'))
            academic_year_id = int(request.form.get('academic_year_id'))
            
            # Allocate teacher
            service.allocate_teacher_to_class_subject(
                teacher_id=teacher_id,
                class_id=class_id,
                subject_id=subject_id,
                academic_year_id=academic_year_id
            )
            
            flash('✅ Teacher allocated successfully', 'success')
            return redirect(url_for('manage_classes'))
        
        # GET: Show form with dropdowns
        service_obj = ClassManagementService(connection)
        years = service_obj.get_all_academic_years()
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM classes WHERE is_active = TRUE ORDER BY display_name")
            classes = cursor.fetchall()
            
            cursor.execute("SELECT * FROM subjects WHERE is_active = TRUE ORDER BY code")
            subjects = cursor.fetchall()
        
        return render_template('allocate_teacher.html',
                             years=years,
                             classes=classes,
                             subjects=subjects)
    
    except Exception as e:
        app.logger.error(f"Allocate teacher error: {str(e)}")
        flash(f'Error allocating teacher: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()


@app.route('/admin/student/<int:student_id>/subjects', methods=['GET', 'POST'])
@login_required
@admin_required
def enroll_student_subjects(student_id):
    """Enroll student in subjects (validated against class subject allocation)."""
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        if request.method == 'POST':
            class_allocation_id = int(request.form.get('class_allocation_id'))
            subject_ids = request.form.getlist('subject_ids')
            
            # Enroll student in subjects
            service.enroll_student_in_subjects(
                class_allocation_id=class_allocation_id,
                subject_ids=[int(sid) for sid in subject_ids]
            )
            
            flash('✅ Student enrolled in subjects', 'success')
            return redirect(url_for('manage_classes'))
        
        # GET: Show form
        with connection.cursor() as cursor:
            # Get student's current allocation
            cursor.execute("""
                SELECT ca.*, c.display_name, c.classID, ay.year
                FROM class_allocation ca
                JOIN classes c ON ca.class_id = c.classID
                JOIN academic_years ay ON ca.academic_year_id = ay.id
                WHERE ca.student_id = %s AND ca.is_current = TRUE
                LIMIT 1
            """, (student_id,))
            allocation = cursor.fetchone()
            
            if not allocation:
                flash('No current class allocation found', 'error')
                return redirect(url_for('manage_classes'))
            
            # Get available subjects for this class
            cursor.execute("""
                SELECT s.id, s.code, s.name, cs.is_compulsory
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.id
                WHERE cs.class_id = %s AND cs.is_active = TRUE
                ORDER BY s.code
            """, (allocation['class_id'],))
            available_subjects = cursor.fetchall()
            
            # Get already enrolled subjects
            cursor.execute("""
                SELECT subject_id FROM student_subjects 
                WHERE class_allocation_id = %s AND is_active = TRUE
            """, (allocation['id'],))
            enrolled_subject_ids = [row['subject_id'] for row in cursor.fetchall()]
        
        return render_template('enroll_student_subjects.html',
                             student_id=student_id,
                             allocation=allocation,
                             available_subjects=available_subjects,
                             enrolled_subject_ids=enrolled_subject_ids)
    
    except Exception as e:
        app.logger.error(f"Enroll student subjects error: {str(e)}")
        flash(f'Error enrolling student: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()


@app.route('/admin/class/<int:class_id>/get-subjects', methods=['GET'])
@login_required
def get_class_subjects(class_id):
    """API endpoint to get subjects for a class (for form population)."""
    connection = None
    try:
        connection = get_db_connection()
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT s.id, s.code, s.name
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.id
                WHERE cs.class_id = %s AND cs.is_active = TRUE
                ORDER BY s.code
            """, (class_id,))
            subjects = cursor.fetchall()
        
        return jsonify({'success': True, 'subjects': subjects})
    
    except Exception as e:
        app.logger.error(f"Get class subjects error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        if connection:
            connection.close()


@app.route('/admin/get-classes-by-year', methods=['GET'])
@login_required
def get_classes_by_year():
    """API endpoint to fetch classes for a given academic year."""
    connection = None
    try:
        year_id = request.args.get('year_id')
        if not year_id:
            return jsonify({'success': False, 'error': 'year_id required'})
        
        connection = get_db_connection()
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT classID, display_name, class_group_code, stream_code
                FROM classes
                WHERE academic_year_id = %s AND is_active = TRUE
                ORDER BY display_name
            """, (year_id,))
            classes = cursor.fetchall()
        
        return jsonify({'success': True, 'classes': classes})
    
    except Exception as e:
        app.logger.error(f"Get classes by year error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        if connection:
            connection.close()


if __name__ == '__main__':
     app.run(host='0.0.0.0', port=5000, debug=True)
        