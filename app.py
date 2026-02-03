
import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, make_response, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql, hashlib, csv
import urllib.parse as urlparse

# Use environment variables for DB credentials
_db_url = os.environ.get('DATABASE_URL') or os.environ.get('DB_HOST')

if _db_url and '://' in _db_url:
    url = urlparse.urlparse(_db_url)
    DB_HOST = url.hostname
    DB_USER = url.username
    DB_PASSWORD = url.password
    DB_NAME = url.path.lstrip('/')
    DB_PORT = url.port or 3306
else:
    DB_HOST = os.environ.get('DB_HOST', 'serverless-eu-west-3.sysp0000.db1.skysql.com')
    DB_USER = os.environ.get('DB_USER', 'dbpwf28831395')
    DB_PASSWORD = os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS', '4FjBYp4aP0p3g{cx5?GCHbs')
    DB_NAME = os.environ.get('DB_NAME', 'schoolmngt')
    DB_PORT = int(os.environ.get('DB_PORT', 4018))

# Construct SQLALCHEMY_DATABASE_URI
DEFAULT_DB_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', DEFAULT_DB_URI)

# Ensure the URI uses the correct driver and format
if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
elif SQLALCHEMY_DATABASE_URI.startswith("mysql://"):
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("mysql://", "mysql+pymysql://", 1)

from io import StringIO, BytesIO
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from class_management_service import ClassManagementService, ValidationError, PromotionError
from fees_management_service import FeesService, FeesError
from exam_management_service import ExamManagementService, ExamManagementError
from finance_management_service import FinanceService, FinanceError
from procurement_service import ProcurementService, ProcurementError

db = SQLAlchemy()
csrf = CSRFProtect()
migrate = Migrate()



def create_app():
    app = Flask(__name__, static_folder='static')
    
    # Configuration
    app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_please_change_in_production')
    app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
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
    try:
        # SkySQL/MariaDB Cloud often requires SSL
        ssl_config = None
        if 'skysql.com' in DB_HOST.lower():
            ssl_config = {'ssl': {}} # Basic SSL enablement
        
        connection = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            ssl=ssl_config or ({'ssl': True} if os.environ.get('USE_SSL') == 'true' else None)
        )
        return connection
    except Exception as e:
        # This will show up in Render Logs
        print(f"CRITICAL: Database connection failed for {DB_USER}@{DB_HOST}:{DB_PORT}. Error: {e}")
        raise e

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

from werkzeug.security import generate_password_hash, check_password_hash

def verify_legacy_password(input_password, stored_password, user_id=None):
    """
    Supports:
    - Secure Bcrypt/PBKDF2 hashes (Primary)
    - Plain text passwords (Legacy - Auto-upgrades to secure hash on match)
    - MD5 hashed passwords (Legacy - Auto-upgrades to secure hash on match)
    """
    if not stored_password:
        return False

    # 1. Primary: Secure Hash check (Werkzeug default)
    if stored_password.startswith(('pbkdf2:sha256:', 'scrypt:', 'bcrypt:')):
        return check_password_hash(stored_password, input_password)

    # 2. Legacy: Plain text match
    is_match = False
    if input_password == stored_password:
        is_match = True
    
    # 3. Legacy: MD5 match
    if not is_match:
        md5_pass = hashlib.md5(input_password.encode()).hexdigest()
        if md5_pass == stored_password:
            is_match = True

    # Auto-Upgrade logic
    if is_match and user_id:
        try:
            secure_hash = generate_password_hash(input_password)
            connection = get_db_connection()
            with connection.cursor() as cursor:
                cursor.execute("UPDATE users SET pwd = %s WHERE userNo = %s", (secure_hash, user_id))
            connection.commit()
            connection.close()
            print(f"DEBUG: Password for user {user_id} upgraded to secure hash.")
        except Exception as e:
            print(f"DEBUG: Password upgrade failed: {e}")

    return is_match

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

        if not verify_legacy_password(password, user['pwd'], user['userNo']):
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
    flash("Logged out successfully.", "successfully")
    return redirect(url_for('login'))

@app.route('/health')
def health_check():
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
        connection.close()
        return jsonify({"status": "healthy", "database": "connected", "result": result}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500



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

    # Student Count
    cursor.execute("SELECT COUNT(*) AS count FROM studentinfo")
    total_students = cursor.fetchone()['count']

    # Staff Count
    cursor.execute("SELECT COUNT(*) AS count FROM users")
    total_staff = cursor.fetchone()['count']

    # Active Classes
    cursor.execute("SELECT COUNT(*) AS count FROM classes")
    total_classes = cursor.fetchone()['count']

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
        
        # Total Collections Today
        cursor.execute("SELECT SUM(total) AS total FROM uniform_receipts WHERE DATE(issued_on) = CURDATE()")
        today_collections = cursor.fetchone()['total'] or 0
    else:
        uniform_issued = 0
        today_collections = 0

    connection.close()

    return render_template('index.html',
                           active_buses=active_buses,
                           vouchers_today=vouchers_today,
                           uniform_issued=uniform_issued,
                           total_students=total_students,
                           total_staff=total_staff,
                           total_classes=total_classes,
                           today_collections=today_collections,
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
            
            # 4. Update fodebit (legacy logic) + fee_ledger (modern logic)
            if total_amount > 0:
                # 4.1 Update fodebit (legacy tracking)
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

                # 4.2 Update fee_ledger (modern integration)
                try:
                    # Get academic_year_id and term_id
                    cursor.execute("SELECT id FROM academic_years WHERE year = %s", (data['year'],))
                    ay_row = cursor.fetchone()
                    ay_id = ay_row['id'] if ay_row else 1 # Fallback if not configured

                    cursor.execute("SELECT id FROM uniform_term_dates WHERE term_number = %s AND year = %s", (data['term'], data['year']))
                    term_row = cursor.fetchone()
                    term_id = term_row['id'] if term_row else 1 # Fallback if not configured

                    # Calculate running balance
                    cursor.execute("SELECT balance_after FROM fee_ledger WHERE admno = %s ORDER BY id DESC LIMIT 1", (data['admno'],))
                    bal_row = cursor.fetchone()
                    
                    # Convert to Decimal for safety
                    prev_balance = Decimal(str(bal_row['balance_after'])) if bal_row and bal_row['balance_after'] else Decimal("0.00")
                    new_balance = prev_balance + Decimal(str(total_amount))

                    cursor.execute("""
                        INSERT INTO fee_ledger (admno, academic_year_id, term_id, type, amount, balance_after, description, reference_no, transaction_date, created_by)
                        VALUES (%s, %s, %s, 'CHARGE', %s, %s, %s, %s, CURDATE(), %s)
                    """, (data['admno'], ay_id, term_id, total_amount, new_balance, f"Uniform Issuance: {receipt_no}", receipt_no, session.get('userNo')))
                except Exception as e:
                    print(f"Fee ledger sync error: {e}")
                    # Don't fail the whole issuance if ledger sync fails, but log it
            
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
@app.route('/admin/manage_prices', methods=['GET', 'POST'])
@login_required
def manage_prices():
    """Manage uniform prices - Main endpoint"""
    if not session.get('is_admin'):
        flash("Admin access required.", "error")
        return redirect(url_for('index'))
    
    connection = get_db_connection()
    
    try:
        with connection.cursor() as cursor:
            # Get all uniform items
            cursor.execute("SELECT DISTINCT item_name FROM uniform_prices ORDER BY item_name")
            items = cursor.fetchall()
            uniform_items = [row['item_name'] for row in items]
            
            # Get all class groups
            cursor.execute("SELECT DISTINCT class_group FROM uniform_prices ORDER BY class_group")
            groups = cursor.fetchall()
            class_groups = [row['class_group'] for row in groups]
            
            if request.method == 'POST':
                # Update prices
                for item in uniform_items:
                    for group in class_groups:
                        price = request.form.get(f'price_{item}_{group}')
                        if price is not None and price.strip():
                            try:
                                price_val = float(price)
                                cursor.execute("""
                                    INSERT INTO uniform_prices (item_name, class_group, price)
                                    VALUES (%s, %s, %s)
                                    ON DUPLICATE KEY UPDATE price = VALUES(price)
                                """, (item, group, price_val))
                            except ValueError:
                                continue
                
                connection.commit()
                flash("Prices updated successfully.", "success")
                return redirect(url_for('manage_prices'))
            
            # Fetch existing prices
            cursor.execute("SELECT * FROM uniform_prices")
            price_rows = cursor.fetchall()
            
            # Map prices for easy access in template
            price_dict = {}
            for row in price_rows:
                price_dict[(row['item_name'], row['class_group'])] = row['price']
            
            return render_template(
                'manage_prices.html',
                uniform_items=uniform_items,
                class_groups=class_groups,
                prices=price_dict
            )
    
    except Exception as e:
        app.logger.error(f"Error in manage_prices: {str(e)}")
        flash(f"Error managing prices: {str(e)}", "error")
        return redirect(url_for('index'))
    
    finally:
        if connection:
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
    
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # Fetch constants needed for the dashboard/form
            cursor.execute("SELECT DISTINCT item_name FROM item_stock")
            uniform_items = [row['item_name'] for row in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT class_group FROM uniform_term_dates") # Sample fallback or usage
            # Actually use the predefined class groups
            class_groups = ['Playgroup-PP2', 'Grade 1-3', 'Grade 4-6', 'Grade 7-9']

            if request.method == 'POST':
                for item in uniform_items:
                    for group in class_groups:
                        price = request.form.get(f'price_{item}_{group}')
                        if price is not None and price.strip() != '':
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

            return render_template(
                'manage_prices.html',
                uniform_items=uniform_items,
                class_groups=class_groups,
                prices=price_dict
            )
    except Exception as e:
        flash(f"Error updating prices: {str(e)}", "error")
        return redirect(url_for('manage_prices'))
    finally:
        connection.close()

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

        # 4. Adjust fodebit (legacy) + fee_ledger (modern)
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
        
        # Modern integration: Add ADJUSTMENT to ledger to reverse the charge
        try:
            cursor.execute("SELECT id FROM academic_years WHERE year = %s", (year,))
            ay_row = cursor.fetchone()
            ay_id = ay_row['id'] if ay_row else 1
            
            cursor.execute("SELECT id FROM uniform_term_dates WHERE term_number = %s AND year = %s", (term, year))
            term_row = cursor.fetchone()
            term_id = term_row['id'] if term_row else 1
            
            cursor.execute("SELECT balance_after FROM fee_ledger WHERE admno = %s ORDER BY id DESC LIMIT 1", (admno,))
            bal_row = cursor.fetchone()
            prev_balance = Decimal(str(bal_row['balance_after'])) if bal_row and bal_row['balance_after'] else Decimal("0.00")
            new_balance = prev_balance - total_amount # Reducing the debt because charge is cancelled
            
            cursor.execute("""
                INSERT INTO fee_ledger (admno, academic_year_id, term_id, type, amount, balance_after, description, reference_no, transaction_date, created_by)
                VALUES (%s, %s, %s, 'ADJUSTMENT', %s, %s, %s, %s, CURDATE(), %s)
            """, (admno, ay_id, term_id, total_amount, new_balance, f"VOID UNIFORM RECEIPT: {receipt_no}", f"VOID-{receipt_no}", session.get('userNo')))
        except Exception as ledger_err:
            print(f"Fee ledger reversal error: {ledger_err}")

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
        # Student Info
        admno = request.form.get('admno').strip()
        fname = request.form.get('fname').strip()
        mname = request.form.get('mname', '').strip()
        lname = request.form.get('lname').strip()
        gender = request.form.get('gender')
        dob = request.form.get('dob')
        birth_cert = request.form.get('birth_cert', '').strip()
        religion = request.form.get('religion', 'Christianity')
        category = request.form.get('category', 'Day')
        student_group_id = request.form.get('student_group_id')
        route_id = request.form.get('route_id')
        alt_contact = request.form.get('alt_contact', '').strip()
        class_id = request.form.get('class_id')
        year = datetime.now().year

        # Get stream and academic year from classes table based on selected class_id to maintain sync
        cursor.execute("SELECT stream_code, academic_year_id FROM classes WHERE classID = %s", (class_id,))
        class_data = cursor.fetchone()
        stream = class_data['stream_code'] if class_data else ''
        academic_year_id = class_data['academic_year_id'] if class_data else None

        # Parent Info
        p_name = request.form.get('parent_name', '').strip()
        p_phone = request.form.get('parent_phone', '').strip()
        p_email = request.form.get('parent_email', '').strip()
        p_id = request.form.get('parent_id_no', '').strip()
        p_address = request.form.get('home_address', '').strip()
        p_residency = request.form.get('residency', '').strip()
        
        try:
            # Check if admission number already exists
            cursor.execute("SELECT AdmNo FROM studentinfo WHERE AdmNo = %s", (admno,))
            if cursor.fetchone():
                flash(f"Admission number {admno} already exists!", "error")
            else:
                connection.begin()

                # LOGIC: Use mobile number as unique sibling identifier
                final_parent_id = 0
                
                # Search for existing parent by mobile number (phone1)
                if p_phone:
                    cursor.execute("""
                        SELECT parentid FROM parentinfo 
                        WHERE phone1 = %s 
                        ORDER BY _date DESC LIMIT 1
                    """, (p_phone,))
                    existing_parent = cursor.fetchone()
                    if existing_parent:
                        final_parent_id = existing_parent['parentid']

                if final_parent_id == 0:
                    # No existing parent found by phone, generate new ID
                    cursor.execute("SELECT COALESCE(MAX(parentid), 0) + 1 as next_id FROM parentinfo")
                    final_parent_id = cursor.fetchone()['next_id']

                # Insert basics student info with expanded data
                cursor.execute("""
                    INSERT INTO studentinfo (
                        AdmNo, parentID, FName, MName, SName, Sex, DoB, birth, Religion, 
                        boarding, category, route_id, alt_contact, stream, blocked, Date_Adm, student_group_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, NOW(), %s)
                """, (
                    admno, final_parent_id, fname, mname, lname, gender, dob, birth_cert, religion,
                    'YES' if category == 'Boarding' else 'NO', 
                    category, route_id if category == 'Transport' else None, alt_contact, stream,
                    int(student_group_id) if student_group_id else None
                ))

                # Handle Parent Info
                if p_name:
                    cursor.execute("""
                        INSERT INTO parentinfo (parentid, admno, pName, phone1, email, nationalID, address, hometown, regDate)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON DUPLICATE KEY UPDATE 
                        pName=%s, phone1=%s, email=%s, nationalID=%s, address=%s, hometown=%s
                    """, (
                        final_parent_id, admno, p_name, p_phone, p_email, p_id, p_address, p_residency,
                        p_name, p_phone, p_email, p_id, p_address, p_residency
                    ))

                # Academic Years & Classes
                cursor.execute("""
                    INSERT INTO class_allocation (student_id, class_id, academic_year_id, allocation_date, is_current)
                    VALUES (%s, %s, %s, NOW(), TRUE)
                """, (admno, class_id, academic_year_id))

                # -----------------------------------------------------------
                # DEBIT TRANSPORT CHARGES (IF APPLICABLE)
                # -----------------------------------------------------------
                if category == 'Transport' and route_id:
                    cursor.execute("SELECT name, amount FROM transport_routes WHERE id = %s", (route_id,))
                    route_data = cursor.fetchone()
                    
                    if route_data:
                        # Find or create Transport votehead
                        votehead_name = f"Transport-{route_data['name']}"
                        cursor.execute("SELECT id FROM fee_voteheads WHERE name = %s", (votehead_name,))
                        vh_res = cursor.fetchone()
                        
                        if vh_res:
                            votehead_id = vh_res['id']
                        else:
                            cursor.execute("INSERT INTO fee_voteheads (name, description) VALUES (%s, %s)", 
                                         (votehead_name, f"Charges for route: {route_data['name']}"))
                            votehead_id = cursor.lastrowid
                        
                        # Get current term ID
                        cursor.execute("SELECT id FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date LIMIT 1")
                        term_res = cursor.fetchone()
                        term_id = term_res['id'] if term_res else None
                        
                        if academic_year_id and term_id:
                            # Use FeesService to handle ledger
                            fees_service = FeesService(connection)
                            fees_service.invoice_student(
                                admno=admno,
                                year_id=academic_year_id,
                                term_id=term_id,
                                structure_id=0, # Manual override
                                user_id=session.get('userNo'),
                                custom_items=[{
                                    'votehead_id': votehead_id,
                                    'votehead_name': votehead_name,
                                    'amount': route_data['amount']
                                }]
                            )

                connection.commit()
                flash(f"✓ Student admitted successfully. ID: {admno}", "success")
                return redirect(url_for('print_admission_form', admno=admno))

        except Exception as e:
            connection.rollback()
            flash(f"Error during admission: {str(e)}", "error")

    # Get data for form
    cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE ORDER BY display_name")
    classes = cursor.fetchall()
    
    cursor.execute("SELECT id, name, amount FROM transport_routes WHERE is_active = TRUE ORDER BY name")
    routes = cursor.fetchall()
    
    # Fetch student groups for selection
    fees_service = FeesService(connection)
    student_groups = fees_service.get_student_groups(active_only=True)
    connection.close()
    return render_template('student.html', classes=classes, routes=routes, student_groups=student_groups)

@app.route('/admit/bulk', methods=['GET', 'POST'])
@admin_required
def bulk_admit_students():
    connection = get_db_connection()
    cursor = connection.cursor()
    
    # Get all active classes for mapping in preview
    cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE ORDER BY display_name")
    available_classes = cursor.fetchall()

    if request.method == 'GET':
        connection.close()
        return render_template('bulk_admit.html')

    if 'file' not in request.files:
        flash("No file part", "error")
        connection.close()
        return redirect(request.url)
    
    file = request.files['file']
    if file.filename == '':
        flash("No selected file", "error")
        connection.close()
        return redirect(request.url)

    if file and file.filename.endswith('.csv'):
        # Parse CSV
        content = file.stream.read().decode("UTF-8")
        stream = StringIO(content, newline=None)
        csv_input = csv.DictReader(stream)
        
        parsed_data = []
        
        for row in csv_input:
            admno = row.get('admno', '').strip()
            if not admno: continue
            
            validation_errors = []
            class_id = None
            
            # 1. Check AdmNo Duplicates
            cursor.execute("SELECT AdmNo FROM studentinfo WHERE AdmNo = %s", (admno,))
            if cursor.fetchone():
                validation_errors.append(f"Admission number '{admno}' already exists in system.")

            # 2. Class Mapping
            class_name = row.get('class_name', '').strip()
            if class_name:
                # High-tolerance normalization for matching: "Grade 1 - A" -> "grade1a"
                def super_normalize(s):
                    if not s: return ""
                    # Remove "stream", dashes, spaces, and non-alphanumeric
                    s = s.lower().replace("stream", "").replace("–", "").replace("-", "")
                    return ''.join(e for e in s if e.isalnum())
                
                target = super_normalize(class_name)
                class_id = None
                
                # Step A: Check exact/normalized match
                for c in available_classes:
                    if super_normalize(c['display_name']) == target:
                        class_id = c['classID']
                        break
                
                # Step B: Keyword/Partial match if Step A fails
                if not class_id:
                    # e.g. "Grade 1" input should match "Grade 1 – Stream B"
                    for c in available_classes:
                        c_disp = c['display_name'].lower().replace("–", "-")
                        curr_cvs = class_name.lower().replace("–", "-")
                        if curr_cvs in c_disp or c_disp in curr_cvs:
                            class_id = c['classID']
                            break

                if not class_id:
                    validation_errors.append(f"Class '{class_name}' not found.")
            else:
                validation_errors.append("Class name is missing.")

            # 3. Sibling Detection (Potential)
            p_phone = row.get('parent_phone', '').strip()
            sibling_found = False
            if p_phone:
                cursor.execute("SELECT pName FROM parentinfo WHERE phone1 = %s LIMIT 1", (p_phone,))
                existing_p = cursor.fetchone()
                if existing_p:
                    sibling_found = True
            
            row['validation_errors'] = validation_errors
            row['class_id'] = class_id
            row['is_valid'] = (len(validation_errors) == 0)
            row['has_sibling'] = sibling_found
            parsed_data.append(row)
        
        connection.close()
        return render_template('bulk_import_preview.html', 
                               data=parsed_data, 
                               available_classes=available_classes)
            
    connection.close()
    return redirect(url_for('students_list'))

@app.route('/admit/bulk/process', methods=['POST'])
@admin_required
def finalize_bulk_import():
    data = request.form.to_dict(flat=False)
    # Form data comes as lists because multiple rows share input names
    admnos = data.get('admno[]', [])
    fnames = data.get('fname[]', [])
    mnames = data.get('mname[]', [])
    lnames = data.get('lname[]', [])
    genders = data.get('gender[]', [])
    dobs = data.get('dob[]', [])
    class_ids = data.get('class_id[]', [])
    categories = data.get('category[]', [])
    religions = data.get('religion[]', [])
    p_names = data.get('parent_name[]', [])
    p_phones = data.get('parent_phone[]', [])
    p_emails = data.get('parent_email[]', [])
    p_ids = data.get('parent_id_no[]', [])
    p_residencies = data.get('residency[]', [])
    p_addresses = data.get('home_address[]', [])
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    success_count = 0
    error_count = 0
    
    try:
        for i in range(len(admnos)):
            admno = admnos[i].strip()
            if not admno: continue
            
            try:
                # Re-validate critically important fields in transaction
                cursor.execute("SELECT AdmNo FROM studentinfo WHERE AdmNo = %s", (admno,))
                if cursor.fetchone():
                    error_count += 1
                    continue
                
                class_id = class_ids[i]
                if not class_id:
                    error_count += 1
                    continue
                
                # Get stream and year from classes
                cursor.execute("SELECT stream_code, academic_year_id FROM classes WHERE classID = %s", (class_id,))
                class_info = cursor.fetchone()
                
                # Parent logic
                p_phone = p_phones[i].strip()
                final_parent_id = 0
                if p_phone:
                    cursor.execute("SELECT parentid FROM parentinfo WHERE phone1 = %s ORDER BY _date DESC LIMIT 1", (p_phone,))
                    existing_p = cursor.fetchone()
                    if existing_p:
                        final_parent_id = existing_p['parentid']
                
                if final_parent_id == 0:
                    cursor.execute("SELECT COALESCE(MAX(parentid), 0) + 1 as next_id FROM parentinfo")
                    final_parent_id = cursor.fetchone()['next_id']

                connection.begin()
                
                cat = categories[i]
                
                # Insert Student
                cursor.execute("""
                    INSERT INTO studentinfo (
                        AdmNo, parentID, FName, MName, SName, Sex, DoB, Religion, 
                        boarding, category, stream, blocked, Date_Adm
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, NOW())
                """, (
                    admno, final_parent_id, fnames[i], mnames[i], lnames[i],
                    genders[i][:1].upper() if genders[i] else 'M',
                    dobs[i] if dobs[i] else None, religions[i],
                    'YES' if cat == 'Boarding' else 'NO', cat, class_info['stream_code']
                ))

                # Insert/Update Parent with current child link
                pn = p_names[i].strip()
                if pn:
                    cursor.execute("""
                        INSERT INTO parentinfo (parentid, admno, pName, phone1, email, nationalID, address, hometown, regDate)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON DUPLICATE KEY UPDATE pName=%s
                    """, (
                        final_parent_id, admno, pn, p_phone, p_emails[i],
                        p_ids[i], p_addresses[i], p_residencies[i], pn
                    ))

                # Allocate Class
                cursor.execute("""
                    INSERT INTO class_allocation (student_id, class_id, academic_year_id, allocation_date, is_current)
                    VALUES (%s, %s, %s, NOW(), TRUE)
                """, (admno, class_id, class_info['academic_year_id']))

                connection.commit()
                success_count += 1
                
            except Exception as e:
                connection.rollback()
                error_count += 1
                app.logger.error(f"Error importing {admno}: {str(e)}")

        flash(f"Success: {success_count} students admitted. {error_count} skipped/failed.", "success" if error_count == 0 else "warning")
    except Exception as e:
        flash(f"Major error during processing: {str(e)}", "error")
    finally:
        connection.close()
        
    return redirect(url_for('students_list'))

@app.route('/print_admission_form/<admno>')
@login_required
def print_admission_form(admno):
    """Generate printable admission form."""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # 1. Fetch student and basic info
        cursor.execute("""
            SELECT 
                s.*, 
                CONCAT(COALESCE(s.FName, ''), ' ', COALESCE(s.MName, ''), ' ', COALESCE(s.SName, '')) as Fullname,
                c.display_name as class_name, 
                tr.name as route_name,
                tr.amount as route_amount
            FROM studentinfo s
            LEFT JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE
            LEFT JOIN classes c ON ca.class_id = c.classID
            LEFT JOIN transport_routes tr ON s.route_id = tr.id
            WHERE s.AdmNo = %s
        """, (admno,))
        student_res = cursor.fetchone()
        
        if not student_res:
            flash("Student not found", "error")
            return redirect(url_for('index'))
        
        # Helper for date conversion
        def to_date(date_val):
            if not date_val: return None
            if isinstance(date_val, (datetime, datetime.date)): return date_val
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
        cursor.execute("""
            SELECT pName, phone1, phone2, email, address, hometown
            FROM parentinfo WHERE admno = %s
        """, (admno,))
        parent = cursor.fetchone()
        if not parent and student_res['parentID']:
            cursor.execute("SELECT pName, phone1, phone2, email, address, hometown FROM parentinfo WHERE parentid = %s LIMIT 1", (student_res['parentID'],))
            parent = cursor.fetchone()
        
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
            cursor.execute("""
                SELECT 
                    s.AdmNo, 
                    CONCAT(COALESCE(s.FName, ''), ' ', COALESCE(s.SName, '')) as Fullname,
                    c.display_name as class_name
                FROM studentinfo s
                LEFT JOIN class_allocation ca ON s.AdmNo = ca.student_id AND ca.is_current = TRUE
                LEFT JOIN classes c ON ca.class_id = c.classID
                WHERE s.parentID = %s AND s.AdmNo != %s
            """, (student_res['parentID'], admno))
            sib_res = cursor.fetchall()
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


@app.route('/student/<int:admno>/edit', methods=['GET', 'POST'])
@admin_required
def edit_student(admno):
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        # Student Info
        fname = request.form.get('fname').strip()
        mname = request.form.get('mname', '').strip()
        lname = request.form.get('lname').strip()
        gender = request.form.get('gender')
        dob = request.form.get('dob')
        birth_cert = request.form.get('birth_cert', '').strip()
        religion = request.form.get('religion')
        category = request.form.get('category')
        alt_contact = request.form.get('alt_contact', '').strip()
        email = request.form.get('email', '').strip()
        notes = request.form.get('notes', '').strip()
        class_id = request.form.get('class_id')
        
        # Parent Info
        p_name = request.form.get('parent_name', '').strip()
        p_phone = request.form.get('parent_phone', '').strip()
        p_email = request.form.get('parent_email', '').strip()
        p_id = request.form.get('parent_id_no', '').strip()
        p_address = request.form.get('home_address', '').strip()
        p_residency = request.form.get('residency', '').strip()

        try:
            connection.begin()

            # Get new stream and academic year based on selected class
            cursor.execute("SELECT stream_code, academic_year_id FROM classes WHERE classID = %s", (class_id,))
            class_data_row = cursor.fetchone()
            new_stream = class_data_row['stream_code'] if class_data_row else ''
            academic_year_id = class_data_row['academic_year_id'] if class_data_row else None

            # 1. Update studentinfo
            cursor.execute("""
                UPDATE studentinfo SET 
                    FName=%s, MName=%s, SName=%s, Sex=%s, DoB=%s, birth=%s, 
                    Religion=%s, category=%s, alt_contact=%s, email=%s, 
                    notes=%s, stream=%s, boarding=%s
                WHERE AdmNo = %s
            """, (
                fname, mname, lname, gender, dob, birth_cert, 
                religion, category, alt_contact, email, 
                notes, new_stream, 'YES' if category == 'Boarding' else 'NO',
                admno
            ))

            # 2. Update parentinfo (ON DUPLICATE KEY UPDATE via admno)
            if p_name or p_phone:
                cursor.execute("""
                    INSERT INTO parentinfo (admno, pName, phone1, email, nationalID, address, hometown, regDate, parentid)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), 0)
                    ON DUPLICATE KEY UPDATE 
                    pName=%s, phone1=%s, email=%s, nationalID=%s, address=%s, hometown=%s
                """, (
                    admno, p_name, p_phone, p_email, p_id, p_address, p_residency,
                    p_name, p_phone, p_email, p_id, p_address, p_residency
                ))

            # 3. Update Academic Placement (Class Allocation)
            # --- Legacy Table Sync ---
            current_year = datetime.now().year
            cursor.execute("""
                SELECT allocationID FROM classallocation WHERE AdmNo = %s AND thisYear = %s
            """, (admno, current_year))
            allocation = cursor.fetchone()

            if allocation:
                cursor.execute("""
                    UPDATE classallocation SET classID = %s WHERE allocationID = %s
                """, (class_id, allocation['allocationID']))
            else:
                cursor.execute("""
                    INSERT INTO classallocation (AdmNo, classID, thisYear, AllcDate)
                    VALUES (%s, %s, %s, NOW())
                """, (admno, class_id, current_year))

            # --- Modern Table Sync ---
            if academic_year_id:
                # Check if current allocation exists in modern table
                cursor.execute("""
                    SELECT id FROM class_allocation 
                    WHERE student_id = %s AND academic_year_id = %s AND is_current = TRUE
                """, (admno, academic_year_id))
                modern_allocation = cursor.fetchone()

                if modern_allocation:
                    cursor.execute("""
                        UPDATE class_allocation SET class_id = %s WHERE id = %s
                    """, (class_id, modern_allocation['id']))
                else:
                    # If this is a mistake or reassignment for the current year
                    cursor.execute("""
                        INSERT INTO class_allocation (student_id, class_id, academic_year_id, allocation_date, is_current)
                        VALUES (%s, %s, %s, NOW(), TRUE)
                    """, (admno, class_id, academic_year_id))

            connection.commit()
            flash(f"✓ Student profile for {fname} {lname} updated successfully.", "success")
            return redirect(url_for('student_profile', admno=admno))

        except Exception as e:
            connection.rollback()
            flash(f"Error updating profile: {str(e)}", "error")

    # GET Request: Fetch all info
    cursor.execute("""
        SELECT s.*, 
               p.pName as parent_name, 
               p.phone1 as parent_phone, 
               p.email as parent_email,
               p.address as home_address, 
               p.hometown as residency,
               p.nationalID as parent_id
        FROM studentinfo s
        LEFT JOIN parentinfo p ON s.AdmNo = p.admno
        WHERE s.AdmNo = %s
    """, (admno,))
    student = cursor.fetchone()

    if not student:
        flash("Student not found!", "error")
        return redirect(url_for('students_list'))

    # Get current class ID
    cursor.execute("""
        SELECT classID FROM classallocation 
        WHERE AdmNo = %s 
        ORDER BY thisYear DESC, AllcDate DESC LIMIT 1
    """, (admno,))
    class_row = cursor.fetchone()
    current_class_id = class_row['classID'] if class_row else None

    # Get available classes
    cursor.execute("""
        SELECT classID, display_name FROM classes 
        WHERE is_active = TRUE 
        ORDER BY display_name
    """)
    classes = cursor.fetchall()

    connection.close()
    return render_template('edit_student.html', 
                         student=student, 
                         classes=classes, 
                         current_class_id=current_class_id)

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
                        (SELECT display_name FROM classes WHERE classID = (
                            SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1
                        ) LIMIT 1),
                        (SELECT class_name FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1
                        ) LIMIT 1),
                        (SELECT class_name FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                        ) LIMIT 1)
                    ) AS class_name,
                    COALESCE(
                        (SELECT class_group FROM classes WHERE classID = (
                            SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1
                        ) LIMIT 1),
                        (SELECT class_group FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1
                        ) LIMIT 1),
                        (SELECT class_group FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                        ) LIMIT 1)
                    ) AS class_group,
                    COALESCE(
                        (SELECT academic_year_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1),
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
                    COALESCE(
                        (SELECT display_name FROM classes WHERE classID = (
                            SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1
                        ) LIMIT 1),
                        (SELECT class_name FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                        ) LIMIT 1)
                    ) AS class_name,
                    COALESCE(
                        (SELECT class_group FROM classes WHERE classID = (
                            SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1
                        ) LIMIT 1),
                        (SELECT class_group FROM classes WHERE classID = (
                            SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                        ) LIMIT 1)
                    ) AS class_group,
                    COALESCE(
                        (SELECT academic_year_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1),
                        (SELECT thisYear FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1)
                    ) AS thisYear
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
                    (SELECT display_name FROM classes WHERE classID = (
                        SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1
                    ) LIMIT 1),
                    (SELECT class_name FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1
                    ) LIMIT 1),
                    (SELECT class_name FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                    ) LIMIT 1)
                ) AS class_name,
                COALESCE(
                    (SELECT class_group FROM classes WHERE classID = (
                        SELECT class_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1
                    ) LIMIT 1),
                    (SELECT class_group FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo AND thisYear = %s LIMIT 1
                    ) LIMIT 1),
                    (SELECT class_group FROM classes WHERE classID = (
                        SELECT classID FROM classallocation WHERE AdmNo = s.AdmNo ORDER BY thisYear DESC LIMIT 1
                    ) LIMIT 1)
                ) AS class_group,
                COALESCE(
                    (SELECT academic_year_id FROM class_allocation WHERE student_id = s.AdmNo AND is_current = TRUE LIMIT 1),
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
    
    # 1. Basic Student Info + Parent Info
    cursor.execute("""
        SELECT s.*, 
               p.pName as parent_name, 
               p.phone1 as parent_phone, 
               p.email as parent_email,
               p.address as home_address, 
               p.hometown as residency,
               p.nationalID as parent_id
        FROM studentinfo s
        LEFT JOIN parentinfo p ON s.AdmNo = p.admno
        WHERE s.AdmNo = %s
    """, (admno,))
    student = cursor.fetchone()
    
    if not student:
        connection.close()
        flash("Student not found", "error")
        return redirect(url_for('students_list'))

    # 2. Fetch current class information
    cursor.execute("""
        SELECT c.class_name, c.class_group, c.classID, a.thisYear
        FROM classallocation a
        LEFT JOIN classes c ON a.classID = c.classID
        WHERE a.AdmNo = %s
        ORDER BY a.thisYear DESC, a.AllcDate DESC
        LIMIT 1
    """, (admno,))
    class_info = cursor.fetchone()
    if class_info:
        student['class_name'] = class_info.get('class_name')
        student['thisYear'] = class_info.get('thisYear')
        student['class_group'] = class_info.get('class_group')
        student['classID'] = class_info.get('classID')

    # 3. Fetch Full Academic History
    cursor.execute("""
        SELECT a.thisYear, a.AllcDate, c.class_name, c.class_group
        FROM classallocation a
        JOIN classes c ON a.classID = c.classID
        WHERE a.AdmNo = %s
        ORDER BY a.thisYear DESC
    """, (admno,))
    academic_history = cursor.fetchall()

    # 4. Fetch Uniform Issuance History (Summarized by Receipt)
    cursor.execute("""
        SELECT receipt_no, MAX(issued_on) as issued_on, SUM(total) as total, MAX(issued_by) as issued_by
        FROM uniform_receipts
        WHERE AdmNo = %s
        GROUP BY receipt_no
        ORDER BY issued_on DESC
    """, (str(admno),)) # AdmNo in receipts might be string or int
    issuance_history = cursor.fetchall()
    
    # 5. Fetch Enrolled Subjects
    cursor.execute("""
        SELECT s.subjName as subject_name, s.code as subject_code, ss.enrollment_date
        FROM student_subjects ss
        JOIN subjects s ON ss.subject_id = s.subjectNo
        JOIN class_allocation ca ON ss.class_allocation_id = ca.id
        WHERE ca.student_id = %s AND ca.is_current = TRUE
    """, (admno,))
    subjects = cursor.fetchall()

    # 6. Fetch Siblings (sharing same parent phone number)
    siblings = []
    if student and student.get('parent_phone'):
        cursor.execute("""
            SELECT s.AdmNo, s.FName, s.MName, s.SName as LName, c.class_name
            FROM studentinfo s
            JOIN parentinfo p ON s.AdmNo = p.admno
            LEFT JOIN classallocation ca ON s.AdmNo = ca.AdmNo
            LEFT JOIN classes c ON ca.classID = c.classID
            WHERE p.phone1 = %s AND s.AdmNo != %s
            GROUP BY s.AdmNo
        """, (student['parent_phone'], admno))
        siblings = cursor.fetchall()

    # 7. Fetch Fee History & Ledger Summary
    # Use the definitive Ledger system instead of legacy fees table
    cursor.execute("""
        SELECT 
            (SELECT SUM(amount) FROM fee_ledger WHERE admno = %s AND type = 'CHARGE') as total_billed,
            (SELECT SUM(amount) FROM fee_payments WHERE admno = %s AND status = 'COMPLETED') as total_paid,
            (SELECT balance_after FROM fee_ledger WHERE admno = %s ORDER BY id DESC LIMIT 1) as current_balance
    """, (admno, admno, admno))
    ledger_summary = cursor.fetchone()
    
    total_billed = ledger_summary['total_billed'] or 0
    total_paid = ledger_summary['total_paid'] or 0
    outstanding_balance = ledger_summary['current_balance'] or 0

    # Fetch Detailed Payment History from modern tables
    cursor.execute("""
        SELECT 
            fr.receipt_no as rcptno, 
            fp.id as payment_id,
            fp.payment_date as date_of_payment, 
            fp.amount as amount_paid, 
            fp.payment_mode, 
            fp.reference_number as chequeNo,
            fp.status,
            ay.year as fncYear
        FROM fee_payments fp
        JOIN fee_ledger fl ON fp.ledger_id = fl.id
        JOIN fee_receipts fr ON fp.id = fr.payment_id
        JOIN academic_years ay ON fl.academic_year_id = ay.id
        WHERE fp.admno = %s
        ORDER BY fp.payment_date DESC, fp.id DESC
    """, (admno,))
    fee_history = cursor.fetchall()

    # 8. Fetch Exam Results - GROUPED and SUMMARIZED
    cursor.execute("""
        SELECT 
            e.id as exam_id, e.name as exam_name, e.term, ay.year as academic_year,
            COUNT(m.id) as subjects_count,
            SUM(m.mark) as total_marks,
            AVG(m.mark) as mean_mark
        FROM exam_marks m
        JOIN exam_series e ON m.exam_id = e.id
        JOIN academic_years ay ON e.academic_year_id = ay.id
        WHERE m.student_id = %s
        GROUP BY e.id, e.name, e.term, ay.year
        ORDER BY ay.year DESC, e.term DESC
    """, (str(admno),))
    exam_summaries = cursor.fetchall()
    
    # Apply grading logic to each summary
    exam_service = ExamManagementService(connection)
    
    for summary in exam_summaries:
        scale_id = exam_service.get_class_grading_scale_id(student.get('classID'))
        grade_rec = exam_service.get_grade_for_mark(summary['mean_mark'], scale_id)
        summary['mean_grade'] = grade_rec['grade'] if grade_rec else '-'

    connection.close()
    
    return render_template('student_profile.html', 
                         student=student, 
                         academic_history=academic_history,
                         issuance_history=issuance_history,
                         subjects=subjects,
                         siblings=siblings,
                         fee_history=fee_history,
                         exam_summaries=exam_summaries,
                         total_paid=total_paid,
                         total_billed=total_billed,
                         outstanding_balance=outstanding_balance)

@app.route('/api/detect-siblings')
@login_required
def detect_siblings():
    """API endpoint to detect siblings and parent info by phone number."""
    phone = request.args.get('phone', '').strip()
    if not phone:
        return jsonify({'siblings': [], 'parent': None})
    
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        # 1. Get Siblings
        cursor.execute("""
            SELECT s.AdmNo, s.FName, s.SName as LName, c.class_name
            FROM studentinfo s
            JOIN parentinfo p ON s.AdmNo = p.admno
            LEFT JOIN classallocation ca ON s.AdmNo = ca.AdmNo
            LEFT JOIN classes c ON ca.classID = c.classID
            WHERE p.phone1 = %s
            GROUP BY s.AdmNo
        """, (phone,))
        siblings = cursor.fetchall()
        
        # 2. Get Parent Info (from most recent entry)
        cursor.execute("""
            SELECT pName, email, phone1, address, hometown, nationalID
            FROM parentinfo
            WHERE phone1 = %s
            ORDER BY regDate DESC
            LIMIT 1
        """, (phone,))
        parent = cursor.fetchone()
        
        return jsonify({
            'siblings': siblings,
            'parent': parent
        })
    except Exception as e:
        app.logger.error(f"Detect siblings error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

@app.route('/api/search_parents')
@login_required
def search_parents():
    """API endpoint to search for parents by name or phone."""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT parentid, pName, phone1, email, address, hometown, nationalID
            FROM parentinfo
            WHERE pName LIKE %s OR phone1 LIKE %s OR nationalID LIKE %s
            LIMIT 10
        """, (f"%{q}%", f"%{q}%", f"%{q}%"))
        parents = cursor.fetchall()
        return jsonify(parents)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        connection.close()

@app.route('/student/<int:admno>/toggle_status', methods=['POST'])
@admin_required
def toggle_student_status(admno):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        # Get current status
        cursor.execute("SELECT blocked FROM studentinfo WHERE AdmNo = %s", (admno,))
        row = cursor.fetchone()
        if not row:
            flash("Student not found", "error")
            return redirect(url_for('students_list'))

        new_status = 'YES' if row['blocked'] == 'NO' else 'NO'
        
        cursor.execute("UPDATE studentinfo SET blocked = %s WHERE AdmNo = %s", (new_status, admno))
        connection.commit()
        
        msg = f"Student {'blocked' if new_status == 'YES' else 'unblocked'} successfully."
        flash(msg, "success")
        
    except Exception as e:
        connection.rollback()
        flash(f"Error updating status: {str(e)}", "error")
    finally:
        connection.close()
        
    return redirect(url_for('student_profile', admno=admno))

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
                cursor.execute("SELECT id FROM academic_years WHERE year = %s", (year,))
                ay_row = cursor.fetchone()
                academic_year_id = ay_row['id'] if ay_row else None
                
                cursor.execute("""
                    INSERT INTO uniform_term_dates (term_number, year, academic_year_id, start_date, end_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (term_number, year, academic_year_id, start_date, end_date))
                flash("Term date added successfully.", "success")
        
        elif action == 'edit':
            term_id = request.form.get('term_id')
            term_number = request.form.get('term_number')
            year = request.form.get('year')
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            
            cursor.execute("SELECT id FROM academic_years WHERE year = %s", (year,))
            ay_row = cursor.fetchone()
            academic_year_id = ay_row['id'] if ay_row else None
            
            cursor.execute("""
                UPDATE uniform_term_dates 
                SET term_number=%s, year=%s, academic_year_id=%s, start_date=%s, end_date=%s
                WHERE id=%s
            """, (term_number, year, academic_year_id, start_date, end_date, term_id))
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
@admin_required
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
            
            # Get all classes with details - filtered to current academic year
            cursor.execute("""
                SELECT c.classID, c.class_name, c.class_group, c.stream_code, 
                       c.display_name, a.year, COUNT(ca.id) as student_count
                FROM classes c
                LEFT JOIN academic_years a ON c.academic_year_id = a.id
                LEFT JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE
                WHERE a.is_current = TRUE
                GROUP BY c.classID
                ORDER BY c.class_name ASC
            """)
            classes = cursor.fetchall()
            
            # Get all streams
            cursor.execute("""
                SELECT id, code, name, is_active FROM stream_settings 
                WHERE is_active = TRUE
                ORDER BY code
            """)
            streams = cursor.fetchall()
        
            # Classes missing subject allocation (wrapped in try-except)
            missing_subject_classes = []
            try:
                cursor.execute("""
                    SELECT c.display_name
                    FROM classes c
                    LEFT JOIN class_subjects cs ON c.classID = cs.class_id AND cs.is_active = TRUE
                    LEFT JOIN academic_years ay ON c.academic_year_id = ay.id
                    WHERE ay.is_current = TRUE AND c.is_active = TRUE
                    GROUP BY c.classID
                    HAVING COUNT(cs.subject_id) = 0
                """)
                missing_subject_classes = [row['display_name'] for row in cursor.fetchall()]
            except Exception as e:
                app.logger.warning(f"Could not fetch classes missing subjects: {str(e)}")
                missing_subject_classes = []

            # Classes missing any teacher allocation (prefer class_teachers table)
            missing_class_teachers = []
            try:
                cursor.execute("""
                    SELECT c.display_name
                    FROM classes c
                    LEFT JOIN academic_years ay ON c.academic_year_id = ay.id
                    LEFT JOIN class_teachers ct ON c.classID = ct.class_id AND ct.academic_year_id = ay.id AND ct.is_active = TRUE
                    WHERE ay.is_current = TRUE AND c.is_active = TRUE
                    GROUP BY c.classID
                    HAVING COUNT(ct.teacher_id) = 0
                """)
                missing_class_teachers = [row['display_name'] for row in cursor.fetchall()]
            except Exception:
                # Fallback to older teacher_allocations if class_teachers doesn't exist
                try:
                    cursor.execute("""
                        SELECT c.display_name
                        FROM classes c
                        LEFT JOIN teacher_allocations ta ON c.classID = ta.class_id AND ta.is_active = TRUE
                        LEFT JOIN academic_years ay ON c.academic_year_id = ay.id
                        WHERE ay.is_current = TRUE AND c.is_active = TRUE
                        GROUP BY c.classID
                        HAVING COUNT(ta.teacher_id) = 0
                    """)
                    missing_class_teachers = [row['display_name'] for row in cursor.fetchall()]
                except Exception as e:
                    app.logger.warning(f"Could not fetch classes missing teachers: {str(e)}")
                    missing_class_teachers = []

            # Class-subjects missing subject teacher
            missing_subject_teachers = []
            try:
                # Try new schema first
                cursor.execute("""
                    SELECT c.display_name, s.name as subject_name
                    FROM classes c
                    JOIN class_subjects cs ON c.classID = cs.class_id AND cs.is_active = TRUE
                    JOIN subjects s ON cs.subject_id = s.id
                    LEFT JOIN teacher_allocations ta ON c.classID = ta.class_id AND cs.subject_id = ta.subject_id AND ta.is_active = TRUE
                    LEFT JOIN academic_years ay ON c.academic_year_id = ay.id
                    WHERE ay.is_current = TRUE AND c.is_active = TRUE
                    GROUP BY c.classID, cs.subject_id
                    HAVING COUNT(ta.teacher_id) = 0
                """)
                missing_subject_teachers = [f"{row['display_name']} - {row['subject_name']}" for row in cursor.fetchall()]
            except Exception:
                try:
                    # Fallback to legacy schema (subjectNo, subjName)
                    cursor.execute("""
                        SELECT c.display_name, s.subjName as subject_name
                        FROM classes c
                        JOIN class_subjects cs ON c.classID = cs.class_id AND cs.is_active = TRUE
                        JOIN subjects s ON cs.subject_id = s.subjectNo
                        LEFT JOIN teacher_allocations ta ON c.classID = ta.class_id AND cs.subject_id = ta.subject_id AND ta.is_active = TRUE
                        LEFT JOIN academic_years ay ON c.academic_year_id = ay.id
                        WHERE ay.is_current = TRUE AND c.is_active = TRUE
                        GROUP BY c.classID, cs.subject_id
                        HAVING COUNT(ta.teacher_id) = 0
                    """)
                    missing_subject_teachers = [f"{row['display_name']} - {row['subject_name']}" for row in cursor.fetchall()]
                except Exception as e:
                    app.logger.warning(f"Could not fetch subject-teacher assignments: {str(e)}")
                    missing_subject_teachers = []

        return render_template('class_management_dashboard.html',
                             academic_years_count=academic_years_count,
                             total_classes=total_classes,
                             total_students=total_students,
                             total_subjects=total_subjects,
                             current_year=current_year,
                             classes=classes,
                             streams=streams,
                             missing_subject_classes=missing_subject_classes,
                             missing_class_teachers=missing_class_teachers,
                             missing_subject_teachers=missing_subject_teachers)
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
    stream_code = request.form.get('stream_code', '').strip()

    if not class_name:
        return jsonify({'error': 'Class name cannot be empty'}), 400
    if not stream_code:
        return jsonify({'error': 'Stream is required.'}), 400

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE classes SET class_name = %s, class_group = %s, stream_code = %s WHERE classID = %s
        """, (class_name, class_group, stream_code, class_id))
        connection.commit()
        connection.close()
        return jsonify({'success': True, 'message': f"Class updated to '{class_name}' ({class_group}, {stream_code})."})
    except Exception as e:
        connection.rollback()
        connection.close()
        # Duplicate entry error code is 1062
        if hasattr(e, 'args') and len(e.args) > 1 and '1062' in str(e.args[0]):
            return jsonify({'error': 'A class with this name already exists for the selected year. Please choose a different name.'}), 400
        return jsonify({'error': f'An error occurred: {str(e)}'}), 400


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

# ----------------------------------------------------------------------------
# TRANSPORT ROUTES MANAGEMENT
# ----------------------------------------------------------------------------

@app.route('/fleet/routes', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_transport_routes():
    """Manage transport routes and charges."""
    connection = get_db_connection()
    cursor = connection.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            name = request.form.get('name').strip()
            amount = request.form.get('amount', 0.00)
            description = request.form.get('description', '').strip()
            
            try:
                cursor.execute("""
                    INSERT INTO transport_routes (name, amount, description)
                    VALUES (%s, %s, %s)
                """, (name, amount, description))
                connection.commit()
                flash(f"✅ Route '{name}' added successfully", "success")
            except Exception as e:
                flash(f"Error adding route: {str(e)}", "error")
                
        elif action == 'edit':
            route_id = request.form.get('route_id')
            name = request.form.get('name').strip()
            amount = request.form.get('amount', 0.00)
            description = request.form.get('description', '').strip()
            
            try:
                cursor.execute("""
                    UPDATE transport_routes 
                    SET name = %s, amount = %s, description = %s 
                    WHERE id = %s
                """, (name, amount, description, route_id))
                connection.commit()
                flash("✅ Route updated successfully", "success")
            except Exception as e:
                flash(f"Error updating route: {str(e)}", "error")

        elif action == 'toggle':
            route_id = request.form.get('route_id')
            cursor.execute("SELECT is_active FROM transport_routes WHERE id = %s", (route_id,))
            res = cursor.fetchone()
            if res:
                new_status = not res['is_active']
                cursor.execute("UPDATE transport_routes SET is_active = %s WHERE id = %s", (new_status, route_id))
                connection.commit()
                flash("✅ Route status updated", "success")

    cursor.execute("SELECT * FROM transport_routes ORDER BY name")
    routes = cursor.fetchall()
    connection.close()
    return render_template('manage_routes.html', routes=routes)

@app.route('/fleet/delete_route/<int:route_id>', methods=['POST'])
@login_required
@admin_required
def delete_route(route_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    try:
        # Check if route is in use
        cursor.execute("SELECT COUNT(*) as count FROM studentinfo WHERE route_id = %s", (route_id,))
        if cursor.fetchone()['count'] > 0:
            return jsonify({'success': False, 'message': 'Route is in use by students and cannot be deleted.'}), 400
            
        cursor.execute("DELETE FROM transport_routes WHERE id = %s", (route_id,))
        connection.commit()
        return jsonify({'success': True, 'message': '✓ Route deleted successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        connection.close()

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
            # ONLY show items that are in uniform_prices or specifically tagged as inventory
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

# Selection page for Class Subjects allocation
@app.route('/admin/class_subjects_select', methods=['GET'])
@login_required
@admin_required
def class_subjects_select():
    """Page to select a class for subject allocation."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT classID, display_name, academic_year_id, class_group_code, stream_code
                FROM classes
                WHERE is_active = TRUE
                ORDER BY display_name
            """)
            classes = cursor.fetchall()
        return render_template('class_subjects_select.html', classes=classes)
    except Exception as e:
        app.logger.error(f"Class subjects select error: {str(e)}")
        flash(f'Error loading classes: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()

# Selection page for Student Subject Enrollment
@app.route('/admin/student_subjects_select', methods=['GET'])
@login_required
@admin_required
def student_subjects_select():
    """Page to select a student for subject enrollment."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT s.admno, s.full_name, ca.class_id, c.display_name
                FROM students s
                JOIN class_allocation ca ON s.admno = ca.student_id AND ca.is_current = TRUE
                JOIN classes c ON ca.class_id = c.classID
                WHERE s.is_active = TRUE
                ORDER BY s.full_name
            """)
            students = cursor.fetchall()
        return render_template('student_subjects_select.html', students=students)
    except Exception as e:
        app.logger.error(f"Student subjects select error: {str(e)}")
        flash(f'Error loading students: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()

# Simple Class Reports Dashboard
@app.route('/admin/class_reports', methods=['GET'])
@login_required
@admin_required
def class_reports():
    """Dashboard for class allocations, student enrollments, and promotion history."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Classes per year
            cursor.execute("""
                SELECT c.display_name, ay.year, COUNT(ca.id) as students
                FROM classes c
                LEFT JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE
                JOIN academic_years ay ON c.academic_year_id = ay.id
                GROUP BY c.classID, ay.year
                ORDER BY ay.year DESC, c.display_name
            """)
            class_summary = cursor.fetchall()

            # Promotion history
            cursor.execute("""
                SELECT old_class_id, new_class_id, student_count, promotion_date
                FROM class_promotion_log
                ORDER BY promotion_date DESC
                LIMIT 20
            """)
            promotions = cursor.fetchall()
        return render_template('class_reports.html', class_summary=class_summary, promotions=promotions)
    except Exception as e:
        app.logger.error(f"Class reports error: {str(e)}")
        flash(f'Error loading reports: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()

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
            try:
                class_rec = service.create_class(
                    academic_year_id=academic_year_id,
                    class_group_code=class_group_code,
                    stream_code=stream_code,
                    created_by=session.get('userNo'),
                    class_name=class_name
                )
                flash(f'✅ Class created: {class_rec["display_name"]}', 'success')
                return redirect(url_for('manage_classes'))
            except Exception as e:
                # Better duplicate handling
                if "Duplicate entry" in str(e) or "already exists" in str(e):
                    flash('Error: This class and stream combination already exists for this academic year.', 'error')
                    return redirect(url_for('create_class'))
                else:
                    flash(f'Error creating class: {str(e)}', 'error')
                    return redirect(url_for('create_class'))
        # GET: Show form
        years = service.get_all_academic_years()
        groups = [{'code': k, 'name': v['name']} for k, v in service.get_class_groups().items()]
        streams = service.get_allowed_streams()
        return render_template('create_class.html', years=years, groups=groups, streams=streams)
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
            try:
                cursor.execute("SELECT id, code, name FROM subjects WHERE is_active = TRUE ORDER BY code")
                subjects = cursor.fetchall()
            except Exception:
                try:
                    cursor.execute("SELECT id, code, name FROM subjects ORDER BY code")
                    subjects = cursor.fetchall()
                except Exception:
                    # Fallback to legacy schema
                    cursor.execute("SELECT subjectNo as id, code, subjName as name FROM subjects ORDER BY code")
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
            subject_id_val = request.form.get('subject_id', '')
            academic_year_id = int(request.form.get('academic_year_id'))
            is_class_teacher = request.form.get('is_class_teacher') == 'on'

            try:
                # If assigning as class teacher, persist into `class_teachers` table
                if is_class_teacher:
                    with connection.cursor() as cursor:
                        cursor.execute("""
                            UPDATE class_teachers
                            SET is_active = FALSE
                            WHERE class_id = %s AND academic_year_id = %s
                        """, (class_id, academic_year_id))

                        cursor.execute("""
                            INSERT INTO class_teachers (teacher_id, class_id, academic_year_id, is_active)
                            VALUES (%s, %s, %s, TRUE)
                        """, (teacher_id, class_id, academic_year_id))

                    connection.commit()

                    flash('✅ Class teacher assigned', 'success')

                # If a subject was selected, also allocate subject teacher
                if subject_id_val:
                    subject_id = int(subject_id_val)
                    service.allocate_teacher_to_class_subject(
                        teacher_id=teacher_id,
                        class_id=class_id,
                        subject_id=subject_id,
                        academic_year_id=academic_year_id
                    )

                    flash('✅ Teacher allocated to subject', 'success')

                return redirect(url_for('manage_classes'))

            except Exception as e:
                try:
                    connection.rollback()
                except Exception:
                    pass
                app.logger.error(f"Allocate teacher error: {str(e)}")
                flash(f'Error allocating teacher: {str(e)}', 'error')
                return redirect(url_for('manage_classes'))
        
        # GET: Show form with dropdowns
        service_obj = ClassManagementService(connection)
        years = service_obj.get_all_academic_years()
        
        with connection.cursor() as cursor:
            # Fetch active teachers from users table
            cursor.execute("""
                SELECT userNo, username, StaffID 
                FROM users 
                WHERE access_flag = 1 
                ORDER BY username
            """)
            teachers = cursor.fetchall()
            
            # Some deployments may not have `is_active` on these tables.
            try:
                cursor.execute("SELECT classID, display_name, class_group_code, stream_code FROM classes WHERE is_active = TRUE ORDER BY display_name")
            except Exception:
                cursor.execute("SELECT classID, class_name as display_name FROM classes ORDER BY class_name")
            classes = cursor.fetchall()

            # Try new schema first, fallback to legacy schema
            try:
                cursor.execute("SELECT id, code, name FROM subjects WHERE is_active = TRUE ORDER BY code")
                subjects = cursor.fetchall()
            except Exception:
                try:
                    cursor.execute("SELECT id, code, name FROM subjects ORDER BY code")
                    subjects = cursor.fetchall()
                except Exception:
                    # Fallback to legacy schema: subjectNo as id, subjName as name
                    cursor.execute("SELECT subjectNo as id, code, subjName as name FROM subjects ORDER BY code")
                    subjects = cursor.fetchall()
        
        return render_template('allocate_teacher.html',
                             years=years,
                             teachers=teachers,
                             classes=classes,
                             subjects=subjects)
    
    except Exception as e:
        app.logger.error(f"Allocate teacher error: {str(e)}")
        flash(f'Error allocating teacher: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()


@app.route('/admin/get-teachers', methods=['GET'])
@login_required
@admin_required
def get_teachers():
    """API endpoint to get list of active teachers."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT userNo, username, StaffID 
                FROM users 
                WHERE access_flag = 1 
                ORDER BY username
            """)
            teachers = cursor.fetchall()
        return jsonify({'success': True, 'teachers': teachers})
    except Exception as e:
        app.logger.error(f"Get teachers error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if connection:
            connection.close()


@app.route('/admin/teacher/allocate-debug', methods=['GET'])
def allocate_teacher_debug():
    """Debug endpoint to report availability of required data for Allocate Teacher page."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Try to fetch academic years
            try:
                cursor.execute("SELECT id, year, is_current FROM academic_years ORDER BY year DESC")
                years = cursor.fetchall()
            except Exception as e:
                years = {'error': str(e)}

            # Classes
            try:
                cursor.execute("SELECT classID, display_name FROM classes ORDER BY display_name")
                classes = cursor.fetchall()
            except Exception as e:
                classes = {'error': str(e)}

            # Subjects
            try:
                cursor.execute("SELECT id, code, name FROM subjects ORDER BY code")
                subjects = cursor.fetchall()
            except Exception as e:
                try:
                    cursor.execute("SELECT subjectNo as id, code, subjName as name FROM subjects ORDER BY code")
                    subjects = cursor.fetchall()
                except Exception as e2:
                    subjects = {'error': str(e2)}

        return jsonify({'years': years, 'classes': classes, 'subjects': subjects})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if connection:
            connection.close()


@app.route('/admin/student/subjects/select', methods=['GET'])
@login_required
@admin_required
def select_student_for_subjects():
    """Search for a student to manage their subject enrollment."""
    q = request.args.get('q', '').strip()
    students = []
    if q:
        connection = get_db_connection()
        cursor = connection.cursor()
        # Search by admno or name
        cursor.execute("""
            SELECT s.AdmNo, s.FName, s.MName, s.SName as LName, c.class_name
            FROM studentinfo s
            LEFT JOIN classallocation ca ON s.AdmNo = ca.AdmNo
            LEFT JOIN classes c ON ca.classID = c.classID
            WHERE s.AdmNo LIKE %s OR s.FName LIKE %s OR s.SName LIKE %s
            GROUP BY s.AdmNo
            LIMIT 20
        """, (f"%{q}%", f"%{q}%", f"%{q}%"))
        students = cursor.fetchall()
        connection.close()
    
    return render_template('enroll_student_subjects_select.html', students=students, q=q)

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
            
            # Get available subjects for this class (try new schema first, fallback to legacy)
            try:
                cursor.execute("""
                    SELECT s.id, s.code, s.name, cs.is_compulsory
                    FROM class_subjects cs
                    JOIN subjects s ON cs.subject_id = s.id
                    WHERE cs.class_id = %s AND cs.is_active = TRUE
                    ORDER BY s.code
                """, (allocation['class_id'],))
                available_subjects = cursor.fetchall()
            except Exception:
                # Fallback to legacy schema
                cursor.execute("""
                    SELECT s.subjectNo as id, s.code, s.subjName as name, cs.is_compulsory
                    FROM class_subjects cs
                    JOIN subjects s ON cs.subject_id = s.subjectNo
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


@app.route('/admin/class/<int:class_id>/manage', methods=['GET'])
@login_required
@admin_required
def manage_class_hub(class_id):
    """Modern, consolidated Class Management Hub."""
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        with connection.cursor() as cursor:
            # 1. Get Class Details
            cursor.execute("""
                SELECT c.*, ay.year as academic_year_name
                FROM classes c
                JOIN academic_years ay ON c.academic_year_id = ay.id
                WHERE c.classID = %s
            """, (class_id,))
            class_details = cursor.fetchone()
            
            if not class_details:
                flash("Class not found.", "error")
                return redirect(url_for('manage_classes'))
            
            # 2. Get Academic Year
            academic_year_id = class_details['academic_year_id']
            
            # 3. Get Class Teacher
            cursor.execute("""
                SELECT u.username, u.userNo, u.StaffID
                FROM class_teachers ct
                JOIN users u ON ct.teacher_id = u.userNo
                WHERE ct.class_id = %s AND ct.academic_year_id = %s AND ct.is_active = TRUE
                LIMIT 1
            """, (class_id, academic_year_id))
            class_teacher = cursor.fetchone()
            
            # 4. Get Allocated Subjects & their Teachers
            # Note: We use LEFT JOIN for teacher_allocations to show subjects even without teachers
            try:
                # Try new schema: id, name, is_active
                cursor.execute("""
                    SELECT 
                        s.id as subject_id, s.code, s.name, 
                        cs.is_compulsory,
                        u.username as teacher_name, u.userNo as teacher_id
                    FROM class_subjects cs
                    JOIN subjects s ON cs.subject_id = s.id
                    LEFT JOIN teacher_allocations ta ON ta.class_id = cs.class_id 
                        AND ta.subject_id = s.id AND ta.is_active = TRUE
                    LEFT JOIN users u ON ta.teacher_id = u.userNo
                    WHERE cs.class_id = %s AND cs.is_active = TRUE
                    ORDER BY s.name
                """, (class_id,))
                subjects = cursor.fetchall()
            except Exception:
                try:
                    # Fallback to legacy schema: subjectNo as subject_id, subjName as name
                    cursor.execute("""
                        SELECT 
                            s.subjectNo as subject_id, s.code, s.subjName as name, 
                            cs.is_compulsory,
                            u.username as teacher_name, u.userNo as teacher_id
                        FROM class_subjects cs
                        JOIN subjects s ON cs.subject_id = s.subjectNo
                        LEFT JOIN teacher_allocations ta ON ta.class_id = cs.class_id 
                            AND ta.subject_id = s.subjectNo AND ta.is_active = TRUE
                        LEFT JOIN users u ON ta.teacher_id = u.userNo
                        WHERE cs.class_id = %s AND cs.is_active = TRUE
                        ORDER BY s.subjName
                    """, (class_id,))
                    subjects = cursor.fetchall()
                except Exception as e:
                    app.logger.warning(f"Class Hub Subject Fetch Error: {str(e)}")
                    subjects = []
            
            # 5. Get Enrolled Students
            cursor.execute("""
                SELECT si.AdmNo, si.FName, si.SName, si.Sex as Gender, ca.id as allocation_id
                FROM class_allocation ca
                JOIN studentinfo si ON ca.student_id = si.AdmNo
                WHERE ca.class_id = %s AND ca.is_current = TRUE
                ORDER BY si.FName, si.SName
            """, (class_id,))
            students = cursor.fetchall()
            
            # 6. Metadata for Selects (All Teachers, All Subjects, Available Students)
            cursor.execute("SELECT userNo, username FROM users WHERE access_flag = 1 ORDER BY username")
            all_teachers = cursor.fetchall()
            
            try:
                # Try new schema first
                cursor.execute("SELECT id, code, name FROM subjects WHERE is_active = TRUE ORDER BY name")
                all_subjects = cursor.fetchall()
            except Exception:
                try:
                    # Try without is_active
                    cursor.execute("SELECT id, code, name FROM subjects ORDER BY name")
                    all_subjects = cursor.fetchall()
                except Exception:
                    # Try legacy schema
                    cursor.execute("SELECT subjectNo as id, code, subjName as name FROM subjects ORDER BY subjName")
                    all_subjects = cursor.fetchall()
            
            available_students = service.get_available_students(academic_year_id)
            
        return render_template('manage_class_master.html',
                             class_id=class_id,
                             class_details=class_details,
                             class_teacher=class_teacher,
                             subjects=subjects,
                             students=students,
                             all_teachers=all_teachers,
                             all_subjects=all_subjects,
                             available_students=available_students)
    except Exception as e:
        app.logger.error(f"Class hub error: {str(e)}")
        flash(f"Error loading class hub: {str(e)}", "error")
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()

# API Endpoints for the Hub
@app.route('/api/class/<int:class_id>/update-subjects', methods=['POST'])
@login_required
@admin_required
def api_update_class_subjects(class_id):
    data = request.json
    subject_ids = data.get('subject_ids', [])
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        service.allocate_subjects_to_class(class_id, [int(sid) for sid in subject_ids])
        return jsonify({'success': True, 'message': 'Subjects updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection: connection.close()

@app.route('/api/class/<int:class_id>/assign-teacher', methods=['POST'])
@login_required
@admin_required
def api_assign_teacher(class_id):
    data = request.json
    teacher_id = int(data.get('teacher_id'))
    subject_id = data.get('subject_id') # Can be None for Class Teacher
    is_class_teacher = data.get('is_class_teacher', False)
    
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        # Get academic year for the class
        with connection.cursor() as cursor:
            cursor.execute("SELECT academic_year_id FROM classes WHERE classID = %s", (class_id,))
            ay_id = cursor.fetchone()['academic_year_id']
            
        if is_class_teacher:
            service.set_class_teacher(class_id, teacher_id, ay_id)
        
        if subject_id:
            service.allocate_teacher_to_class_subject(teacher_id, class_id, int(subject_id), ay_id)
            
        return jsonify({'success': True, 'message': 'Teacher assigned successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection: connection.close()

@app.route('/api/class/<int:class_id>/add-students', methods=['POST'])
@login_required
@admin_required
def api_add_students(class_id):
    data = request.json
    student_ids = data.get('student_ids', [])
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT academic_year_id FROM classes WHERE classID = %s", (class_id,))
            ay_id = cursor.fetchone()['academic_year_id']
            
        count = service.allocate_students_to_class(class_id, [int(sid) for sid in student_ids], ay_id)
        return jsonify({'success': True, 'message': f'Successfully added {count} students'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection: connection.close()

@app.route('/api/student/<int:allocation_id>/subjects', methods=['GET'])
@login_required
@admin_required
def api_get_student_subjects(allocation_id):
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Get current enrollments
            cursor.execute("SELECT subject_id FROM student_subjects WHERE class_allocation_id = %s AND is_active = TRUE", (allocation_id,))
            enrolled = [row['subject_id'] for row in cursor.fetchall()]
            return jsonify({'success': True, 'enrolled_subject_ids': enrolled})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection: connection.close()

@app.route('/api/student/subjects/update', methods=['POST'])
@login_required
@admin_required
def api_update_student_subjects():
    data = request.json
    allocation_id = int(data.get('allocation_id'))
    subject_ids = [int(sid) for sid in data.get('subject_ids', [])]
    
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        
        # Clear existing
        with connection.cursor() as cursor:
            cursor.execute("UPDATE student_subjects SET is_active = FALSE WHERE class_allocation_id = %s", (allocation_id,))
            connection.commit()
            
        # Add new
        service.enroll_student_in_subjects(allocation_id, subject_ids)
        return jsonify({'success': True, 'message': 'Student subjects updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection: connection.close()

@app.route('/api/class/<int:class_id>/batch-enroll-subjects', methods=['POST'])
@login_required
@admin_required
def api_batch_enroll_subjects(class_id):
    data = request.json or {}
    subject_ids = data.get('subject_ids')
    
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        count = service.enroll_all_students_in_class_subjects(class_id, subject_ids)
        return jsonify({'success': True, 'message': f'Successfully enrolled students in {count} instances'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection: connection.close()

@app.route('/api/class/remove-student/<int:allocation_id>', methods=['POST'])
@login_required
@admin_required
def api_remove_student(allocation_id):
    connection = None
    try:
        connection = get_db_connection()
        service = ClassManagementService(connection)
        service.remove_student_from_class(allocation_id)
        return jsonify({'success': True, 'message': 'Student removed from class'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection: connection.close()

@app.route('/admin/class/<int:class_id>/get-subjects', methods=['GET'])
@login_required
def get_class_subjects(class_id):
    """API endpoint to get subjects for a class (for form population)."""
    connection = None
    try:
        connection = get_db_connection()
        
        with connection.cursor() as cursor:
            try:
                # Try new schema first
                cursor.execute("""
                    SELECT s.subjectNo as id, s.code, s.subjName as name
                    FROM class_subjects cs
                    JOIN subjects s ON cs.subject_id = s.subjectNo
                    WHERE cs.class_id = %s AND cs.is_active = TRUE
                    ORDER BY s.code
                """, (class_id,))
                subjects = cursor.fetchall()
            except Exception:
                # Fallback to legacy schema
                cursor.execute("""
                    SELECT s.subjectNo as id, s.code, s.subjName as name
                    FROM class_subjects cs
                    JOIN subjects s ON cs.subject_id = s.subjectNo
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

@app.route('/api/exams/<int:exam_id>/class/<int:class_id>/subjects-status')
@login_required
def get_exam_subjects_status(exam_id, class_id):
    """API to get subjects for a class with their marks entry status for a specific exam."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # Get total students in class
            cursor.execute("SELECT COUNT(*) as total FROM class_allocation WHERE class_id = %s AND is_current = TRUE", (class_id,))
            res_total = cursor.fetchone()
            total_students = res_total['total'] if res_total else 0
            
            # Get subjects for class
            cursor.execute("""
                SELECT s.subjectNo as id, s.subjName as name, s.code
                FROM subjects s
                JOIN class_subjects cs ON s.subjectNo = cs.subject_id
                WHERE cs.class_id = %s AND cs.is_active = TRUE
            """, (class_id,))
            subjects = cursor.fetchall()
            
            # For each subject, count entered marks in this exam
            for sub in subjects:
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM exam_marks 
                    WHERE exam_id = %s AND subject_id = %s AND student_id IN (
                        SELECT student_id FROM class_allocation WHERE class_id = %s AND is_current = TRUE
                    )
                """, (exam_id, sub['id'], class_id))
                marks_count = cursor.fetchone()['count']
                
                sub['marks_count'] = marks_count
                sub['total_students'] = total_students
                sub['is_complete'] = (marks_count >= total_students and total_students > 0)
                sub['status_text'] = f"{marks_count}/{total_students} entered"
                
        return jsonify({'success': True, 'subjects': subjects})
    except Exception as e:
        app.logger.error(f"Error getting subjects status: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection:
            connection.close()

# ============================================================================
# EXAM MANAGEMENT ROUTES
# ============================================================================

@app.route('/admin/grading-scales')
@login_required
@admin_required
def manage_grading_scales():
    connection = get_db_connection()
    service = ExamManagementService(connection)
    scales = service.get_all_grading_scales()
    connection.close()
    return render_template('manage_grading_scales.html', scales=scales)

@app.route('/admin/grading-scales/add', methods=['POST'])
@login_required
@admin_required
def add_grading_scale():
    name = request.form.get('name')
    description = request.form.get('description', '')
    is_default = request.form.get('is_default') == 'on'
    
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        service.create_grading_scale(name, description, is_default)
        flash(f"Grading scale '{name}' created successfully.", "success")
    except Exception as e:
        flash(f"Error creating scale: {str(e)}", "error")
    finally:
        connection.close()
    return redirect(url_for('manage_grading_scales'))

@app.route('/admin/grading-scales/<int:scale_id>')
@login_required
@admin_required
def edit_grading_scale(scale_id):
    connection = get_db_connection()
    service = ExamManagementService(connection)
    scale = service.get_grading_scale(scale_id)
    grades = service.get_grading_details(scale_id)
    connection.close()
    if not scale:
        flash("Scale not found.", "error")
        return redirect(url_for('manage_grading_scales'))
    return render_template('edit_grading_scale.html', scale=scale, grades=grades)

@app.route('/admin/grading-scales/<int:scale_id>/save-grades', methods=['POST'])
@login_required
@admin_required
def save_grading_details(scale_id):
    grades = []
    grade_names = request.form.getlist('grade[]')
    min_marks = request.form.getlist('min_mark[]')
    max_marks = request.form.getlist('max_mark[]')
    points_list = request.form.getlist('points[]')
    remarks_list = request.form.getlist('remarks[]')
    ct_remarks_list = request.form.getlist('class_teacher_remarks[]')
    p_remarks_list = request.form.getlist('principal_remarks[]')
    
    for i in range(len(grade_names)):
        if grade_names[i]:
            grades.append({
                'grade': grade_names[i],
                'min_mark': float(min_marks[i]),
                'max_mark': float(max_marks[i]),
                'points': int(points_list[i]) if points_list[i] else 0,
                'remarks': remarks_list[i] if remarks_list[i] else '',
                'class_teacher_remarks': ct_remarks_list[i] if i < len(ct_remarks_list) else '',
                'principal_remarks': p_remarks_list[i] if i < len(p_remarks_list) else ''
            })
    
    connection = get_db_connection()
    service = ExamManagementService(connection)
    try:
        service.save_grading_details(scale_id, grades)
        flash("Grading details updated successfully.", "success")
    except Exception as e:
        flash(f"Error saving grades: {str(e)}", "error")
    finally:
        connection.close()
    return redirect(url_for('edit_grading_scale', scale_id=scale_id))

@app.route('/admin/grading-scales/assign')
@login_required
@admin_required
def assign_class_grading():
    connection = get_db_connection()
    service = ExamManagementService(connection)
    
    cursor = connection.cursor()
    cursor.execute("SELECT classID, display_name, class_group, grading_scale_id FROM classes WHERE is_active = TRUE ORDER BY display_name")
    classes = cursor.fetchall()
    
    scales = service.get_all_grading_scales()
    connection.close()
    return render_template('assign_class_grading.html', classes=classes, scales=scales)

@app.route('/admin/grading-scales/save-assignments', methods=['POST'])
@login_required
@admin_required
def save_class_grading_assignments():
    connection = get_db_connection()
    service = ExamManagementService(connection)
    
    try:
        # Loop through all classes to find their assigned scales in the form
        cursor = connection.cursor()
        cursor.execute("SELECT classID FROM classes WHERE is_active = TRUE")
        classes = cursor.fetchall()
        
        for cls in classes:
            scale_id_raw = request.form.get(f"scale_{cls['classID']}")
            scale_id = int(scale_id_raw) if scale_id_raw else None
            service.assign_scale_to_class(cls['classID'], scale_id)
            
        flash("Class grading scales updated successfully.", "success")
    except Exception as e:
        flash(f"Error saving assignments: {str(e)}", "error")
    finally:
        connection.close()
    return redirect(url_for('assign_class_grading'))

@app.route('/admin/exams')
@login_required
@admin_required
def exams_dashboard():
    """Main dashboard for exam series."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exams = service.get_all_exams()
        return render_template('exams_dashboard.html', exams=exams)
    except Exception as e:
        app.logger.error(f"Exams dashboard error: {str(e)}")
        flash(f'Error loading exams: {str(e)}', 'error')
        return redirect(url_for('manage_classes'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_exam():
    """Create a new exam series."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        class_service = ClassManagementService(connection)
        
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            academic_year_id = int(request.form.get('academic_year_id'))
            term = int(request.form.get('term'))
            class_ids = request.form.getlist('class_ids')
            
            if not name:
                flash('Exam series name is required', 'error')
            else:
                exam_id = service.create_exam_series(
                    name=name,
                    academic_year_id=academic_year_id,
                    term=term,
                    created_by=session.get('userNo'),
                    class_ids=[int(cid) for cid in class_ids]
                )
                flash(f'✅ Exam series "{name}" created successfully', 'success')
                return redirect(url_for('exams_dashboard'))
                
        # GET: Show form
        years = class_service.get_all_academic_years()
        # Get active classes
        with connection.cursor() as cursor:
            cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE ORDER BY display_name")
            all_classes = cursor.fetchall()

        return render_template('create_exam.html', years=years, all_classes=all_classes)
    except Exception as e:
        app.logger.error(f"Create exam error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/aggregate/select', methods=['GET', 'POST'])
@login_required
@admin_required
def aggregate_report_select():
    """Selection page for aggregate reports."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        
        if request.method == 'POST':
            exam_ids = request.form.getlist('exam_ids')
            class_id = request.form.get('class_id')
            if not exam_ids or not class_id:
                flash('Please select at least one exam and a class', 'error')
            else:
                return redirect(url_for('aggregate_report_class', class_id=class_id, exam_ids=','.join(exam_ids)))
                
        # Get all exams and classes
        exams = service.get_all_exams()
        with connection.cursor() as cursor:
            cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE ORDER BY display_name")
            classes = cursor.fetchall()
            
        return render_template('aggregate_report_select.html', exams=exams, classes=classes)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/aggregate/class/<int:class_id>')
@login_required
@admin_required
def aggregate_report_class(class_id):
    """View aggregate results for a whole class."""
    exam_ids_str = request.args.get('exam_ids', '')
    if not exam_ids_str:
        return redirect(url_for('aggregate_report_select'))
        
    exam_ids = [int(eid) for eid in exam_ids_str.split(',')]
    
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        
        # Get class info
        with connection.cursor() as cursor:
            cursor.execute("SELECT display_name FROM classes WHERE classID = %s", (class_id,))
            res_cls = cursor.fetchone()
            class_name = res_cls['display_name'] if res_cls else "Unknown"
            
            # Get students in class
            cursor.execute("""
                SELECT student_id FROM class_allocation 
                WHERE class_id = %s AND is_current = TRUE
            """, (class_id,))
            students = cursor.fetchall()
            
        # Get exams info
        exams = []
        for eid in exam_ids:
            exams.append(service.get_exam_series(eid))
            
        # Compile reports for all students
        reports = []
        for s in students:
            reports.append(service.get_student_aggregate_report(exam_ids, s['student_id']))
            
        return render_template('aggregate_report_print.html', 
                             reports=reports, 
                             exams=exams, 
                             class_name=class_name,
                             now=datetime.now())
    except Exception as e:
        app.logger.error(f"Aggregate report error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('aggregate_report_select'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/toggle-lock', methods=['POST'])
@login_required
@admin_required
def toggle_exam_status(exam_id):
    """Lock or unlock an exam series."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        if exam:
            new_lock_state = not exam['is_locked']
            
            # If locking, check for missing marks
            if new_lock_state:
                missing = service.get_exam_missing_marks_report(exam_id)
                if missing and request.form.get('force') != 'true':
                    return render_template('exam_pre_lock_check.html', exam=exam, missing=missing)
            
            service.toggle_exam_lock(exam_id, new_lock_state)
            status = "locked" if new_lock_state else "unlocked"
            flash(f'✅ Exam series {status} successfully', 'success')
        return redirect(url_for('exams_dashboard'))
    except Exception as e:
        app.logger.error(f"Toggle exam lock error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/missing-marks')
@login_required
@admin_required
def exam_missing_marks(exam_id):
    """View missing marks for an exam."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        missing = service.get_exam_missing_marks_report(exam_id)
        return render_template('exam_missing_marks.html', exam=exam, missing=missing)
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/marks/select', methods=['GET'])
@login_required
@admin_required
def marks_entry_select(exam_id):
    """Page to select class and subject for marks entry."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        
        # Get classes assigned to this exam
        classes = service.get_exam_classes(exam_id)
        
        # Fallback to all active classes if none assigned (legacy support)
        if not classes:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT classID, display_name 
                    FROM classes 
                    WHERE is_active = TRUE 
                    ORDER BY display_name
                """)
                classes = cursor.fetchall()
            
        return render_template('marks_entry_select.html', exam=exam, classes=classes)
    except Exception as e:
        app.logger.error(f"Marks entry select error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/marks/entry', methods=['GET'])
@login_required
@admin_required
def marks_entry(exam_id):
    """Grid view for recording marks for a specific class and subject."""
    class_id = request.args.get('class_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    
    if not class_id or not subject_id:
        flash('Class and Subject are required', 'error')
        return redirect(url_for('marks_entry_select', exam_id=exam_id))
        
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        
        # Get class info
        with connection.cursor() as cursor:
            cursor.execute("SELECT classID, display_name FROM classes WHERE classID = %s", (class_id,))
            cls_info = cursor.fetchone()
            
            cursor.execute("SELECT subjectNo as id, subjName as name FROM subjects WHERE subjectNo = %s", (subject_id,))
            sub_info = cursor.fetchone()
            
        if not cls_info or not sub_info:
            flash('Invalid class or subject', 'error')
            return redirect(url_for('marks_entry_select', exam_id=exam_id))
            
        # Get student list with existing marks
        students = service.get_marks_for_class_subject(exam_id, class_id, subject_id)
        
        return render_template('marks_entry.html', 
                             exam=exam, 
                             class_info=cls_info, 
                             subject=sub_info,
                             students=students)
    except Exception as e:
        app.logger.error(f"Marks entry error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('marks_entry_select', exam_id=exam_id))
    finally:
        if connection:
            connection.close()

@app.route('/api/exams/<int:exam_id>/save-mark', methods=['POST'])
@login_required
@admin_required
def api_save_mark(exam_id):
    """API endpoint to save a single mark (auto-save)."""
    data = request.json
    student_id = data.get('student_id')
    subject_id = int(data.get('subject_id'))
    mark = data.get('mark')
    is_absent = data.get('is_absent', False)
    remarks = data.get('remarks', '')
    ct_remarks_param = data.get('ct_remarks', '')
    p_remarks_param = data.get('p_remarks', '')
    
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        
        # Save mark
        service.save_mark(
            exam_id=exam_id,
            student_id=student_id,
            subject_id=subject_id,
            mark=mark,
            is_absent=is_absent,
            remarks=remarks,
            ct_remarks=ct_remarks_param,
            p_remarks=p_remarks_param
        )
        
        # Determine grade and remarks for the response
        grade = None
        auto_remarks = ""
        ct_remarks = ""
        p_remarks = ""
        
        if not is_absent and mark is not None:
            # Get student's class to determine scale
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT class_id FROM class_allocation 
                    WHERE student_id = %s AND is_current = TRUE 
                    LIMIT 1
                """, (student_id,))
                alloc = cursor.fetchone()
                
            scale_id = service.get_class_grading_scale_id(alloc['class_id']) if alloc else None
            grade_rec = service.get_grade_for_mark(float(mark), scale_id)
            
            if grade_rec:
                grade = grade_rec['grade']
                auto_remarks = grade_rec.get('remarks', '')
                ct_remarks = grade_rec.get('class_teacher_remarks', '')
                p_remarks = grade_rec.get('principal_remarks', '')
                
        return jsonify({
            'success': True, 
            'grade': grade, 
            'remarks': auto_remarks,
            'ct_remarks': ct_remarks,
            'p_remarks': p_remarks
        })
    except Exception as e:
        app.logger.error(f"API save mark error: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/marks/export/<int:class_id>/<int:subject_id>')
@login_required
@admin_required
def export_marks_template(exam_id, class_id, subject_id):
    """Export a CSV template for marks entry."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        
        # Get exam info
        with connection.cursor() as cursor:
            cursor.execute("SELECT name FROM exam_series WHERE id = %s", (exam_id,))
            exam = cursor.fetchone()
            
            cursor.execute("SELECT subjName FROM subjects WHERE subjectNo = %s", (subject_id,))
            subject = cursor.fetchone()
            
            cursor.execute("SELECT display_name FROM classes WHERE classID = %s", (class_id,))
            cls = cursor.fetchone()
            
        if not exam or not subject or not cls:
            flash('Invalid parameters for export', 'error')
            return redirect(url_for('marks_entry_select', exam_id=exam_id))
            
        # Get students with current marks
        students = service.get_marks_for_class_subject(exam_id, class_id, subject_id)
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['AdmNo', 'Name', 'Score', 'IsAbsent', 'Remarks'])
        
        for s in students:
            name = f"{s['FName']} {s['LName']}"
            writer.writerow([s['AdmNo'], name, s['mark'] if s['mark'] is not None else '', 1 if s['is_absent'] else 0, s['remarks'] or ''])
        
        mem = BytesIO()
        mem.write(output.getvalue().encode('utf-8'))
        mem.seek(0)
        
        filename = f"Marks_{exam['name']}_{cls['display_name']}_{subject['subjName']}.csv".replace(' ', '_')
        return send_file(
            mem,
            as_attachment=True,
            download_name=filename,
            mimetype='text/csv'
        )
    except Exception as e:
        app.logger.error(f"Export error: {str(e)}")
        flash(f'Export error: {str(e)}', 'error')
        return redirect(url_for('marks_entry', exam_id=exam_id, class_id=class_id, subject_id=subject_id))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/marks/import/<int:class_id>/<int:subject_id>', methods=['POST'])
@login_required
@admin_required
def import_marks_csv(exam_id, class_id, subject_id):
    """Import marks from a CSV file."""
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('marks_entry', exam_id=exam_id, class_id=class_id, subject_id=subject_id))
        
    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('marks_entry', exam_id=exam_id, class_id=class_id, subject_id=subject_id))
        
    if not file.filename.endswith('.csv'):
        flash('Only CSV files are allowed', 'error')
        return redirect(url_for('marks_entry', exam_id=exam_id, class_id=class_id, subject_id=subject_id))
        
    connection = None
    try:
        content = file.read().decode('utf-8')
        stream = StringIO(content)
        reader = csv.DictReader(stream)
        
        connection = get_db_connection()
        service = ExamManagementService(connection)
        
        # Check lock status
        exam = service.get_exam_series(exam_id)
        if exam['is_locked']:
            flash('Cannot import marks: Exam is locked', 'error')
            return redirect(url_for('marks_entry', exam_id=exam_id, class_id=class_id, subject_id=subject_id))
            
        success_count = 0
        error_count = 0
        
        connection.begin()
        for row in reader:
            try:
                admno = row.get('AdmNo')
                score = row.get('Score')
                is_absent = row.get('IsAbsent') == '1'
                remarks = row.get('Remarks', '')
                
                # Validation
                if not admno: continue
                
                mark_val = None
                if score and not is_absent:
                    try:
                        mark_val = float(score)
                    except ValueError:
                        pass
                
                service.save_mark(
                    exam_id=exam_id,
                    student_id=admno,
                    subject_id=subject_id,
                    mark=mark_val,
                    is_absent=is_absent,
                    remarks=remarks
                )
                success_count += 1
            except Exception as e:
                error_count += 1
                app.logger.error(f"Row import error: {str(e)}")
                
        connection.commit()
        flash(f'Import complete: {success_count} succeeded, {error_count} failed.', 'success')
        
    except Exception as e:
        if connection: connection.rollback()
        app.logger.error(f"Import error: {str(e)}")
        flash(f'Import error: {str(e)}', 'error')
    finally:
        if connection:
            connection.close()
    
    return redirect(url_for('marks_entry', exam_id=exam_id, class_id=class_id, subject_id=subject_id))

@app.route('/admin/exams/<int:exam_id>/tabulation', methods=['GET'])
@login_required
@admin_required
def exam_tabulation(exam_id):
    """Tabulation sheet for a whole class."""
    class_id = request.args.get('class_id', type=int)
    
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        
        # Get all active classes for the dropdown
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT classID, display_name 
                FROM classes 
                WHERE is_active = TRUE 
                ORDER BY academic_year_id DESC, display_name
            """)
            classes = cursor.fetchall()
            
        tabulation_data = None
        cls_info = None
        if class_id:
            tabulation_data = service.get_class_tabulation(exam_id, class_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT display_name FROM classes WHERE classID = %s", (class_id,))
                cls_info = cursor.fetchone()
                
        return render_template('exam_tabulation.html', 
                             exam=exam, 
                             classes=classes, 
                             tabulation_data=tabulation_data,
                             class_info=cls_info,
                             class_id=class_id)
    except Exception as e:
        app.logger.error(f"Exam tabulation error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/student/<student_id>/report', methods=['GET'])
@login_required
def student_report_card(exam_id, student_id):
    """View academic report card for a student."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        
        report_data = service.get_report_card_data(student_id, exam_id)
        
        return render_template('report_card.html', **report_data)
    except Exception as e:
        app.logger.error(f"Report card error: {str(e)}")
        flash(f"Error generating report card: {str(e)}", "error")
        return redirect(url_for('student_profile', admno=student_id))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/reports/series', methods=['GET'])
@login_required
@admin_required
def exam_series_report(exam_id):
    """Overall summary report for an exam series."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        
        # 1. Best 3 students in each class
        class_rankings = []
        for cls in exam['classes']:
            top_3 = service.get_exam_rankings(exam_id, class_id=cls['classID'], limit=3)
            class_rankings.append({
                'class_name': cls['display_name'],
                'students': top_3
            })
            
        # 2. Best 3 students overall
        overall_top_3 = service.get_exam_rankings(exam_id, limit=3)
        
        # 3. Best student in each subject
        subject_winners = service.get_subject_winners(exam_id)
        
        # 4. Most improved students
        improved = service.get_most_improved(exam_id)
        
        return render_template('exam_series_report.html',
                             exam=exam,
                             class_rankings=class_rankings,
                             overall_top_3=overall_top_3,
                             subject_winners=subject_winners,
                             most_improved=improved,
                             now=datetime.now())
    except Exception as e:
        app.logger.error(f"Series report error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/class/<int:class_id>/reports', methods=['GET'])
@login_required
@admin_required
def class_exam_report(exam_id, class_id):
    """Detailed exam report for a single class."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        
        # 1. Distribution & Basic Stats
        stats = service.get_class_performance_distribution(exam_id, class_id)
        
        # 2. Top 3 students
        top_3 = service.get_exam_rankings(exam_id, class_id=class_id, limit=3)
        
        # 3. Best per subject
        subject_winners = service.get_subject_winners(exam_id, class_id=class_id)
        
        # 4. Most improved
        improved = service.get_most_improved(exam_id, class_id=class_id)
        
        # Get class name
        with connection.cursor() as cursor:
            cursor.execute("SELECT display_name FROM classes WHERE classID = %s", (class_id,))
            cls_info = cursor.fetchone()
            
        return render_template('class_exam_report.html',
                             exam=exam,
                             class_info=cls_info,
                             stats=stats,
                             top_3=top_3,
                             subject_winners=subject_winners,
                             most_improved=improved,
                             now=datetime.now())
    except Exception as e:
        app.logger.error(f"Class report error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

@app.route('/admin/exams/<int:exam_id>/stream-analysis', methods=['GET'])
@login_required
@admin_required
def stream_analysis(exam_id):
    """Side-by-side comparison of streams in an exam series."""
    connection = None
    try:
        connection = get_db_connection()
        service = ExamManagementService(connection)
        exam = service.get_exam_series(exam_id)
        
        analysis = service.get_stream_performance_comparison(exam_id)
        
        return render_template('stream_analysis.html',
                             exam=exam,
                             analysis=analysis,
                             now=datetime.now())
    except Exception as e:
        app.logger.error(f"Stream analysis error: {str(e)}")
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('exams_dashboard'))
    finally:
        if connection:
            connection.close()

# ============================================================================
# FEES MANAGEMENT ROUTES
# ============================================================================

@app.route('/admin/fees')
@login_required
@admin_required
def fees_dashboard():
    """Central dashboard for fees management."""
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    # Get summary stats
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    with connection.cursor() as cursor:
        # Today's Collection
        cursor.execute("SELECT SUM(amount) as total FROM fee_payments WHERE payment_date = %s AND status = 'COMPLETED'", (today,))
        res = cursor.fetchone()
        today_total = res['total'] if res and res['total'] else 0
        
        # Monthly Collection
        cursor.execute("SELECT SUM(amount) as total FROM fee_payments WHERE MONTH(payment_date) = MONTH(%s) AND YEAR(payment_date) = YEAR(%s) AND status = 'COMPLETED'", (today, today))
        res = cursor.fetchone()
        monthly_total = res['total'] if res and res['total'] else 0
        
        # Total Arrears (Sum of last balance_after for all students)
        cursor.execute("""
            SELECT SUM(fl.balance_after) as total
            FROM fee_ledger fl
            WHERE fl.id IN (SELECT MAX(id) FROM fee_ledger GROUP BY admno)
        """)
        res = cursor.fetchone()
        total_arrears = res['total'] if res and res['total'] else 0

    connection.close()
    return render_template('fees_dashboard.html', 
                         today_total=today_total, 
                         monthly_total=monthly_total, 
                         total_arrears=total_arrears)

@app.route('/admin/fees/reports/collection')
@login_required
@admin_required
def fees_collection_report():
    """Periodic fees collection by payment mode."""
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-01'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        data = fees_service.get_collection_summary(start_date, end_date)
        return render_template('fees_collection_report.html', data=data, start_date=start_date, end_date=end_date)
    finally:
        connection.close()

@app.route('/admin/fees/reports/balances')
@login_required
@admin_required
def fee_balances_report():
    """Fees balances per class and stream with filters."""
    academic_year_id = request.args.get('academic_year_id')
    class_id = request.args.get('class_id')
    stream = request.args.get('stream')
    
    connection = get_db_connection()
    fees_service = FeesService(connection)
    class_service = ClassManagementService(connection)
    
    try:
        data = fees_service.get_fee_balances_report(
            academic_year_id=int(academic_year_id) if academic_year_id else None,
            class_id=int(class_id) if class_id else None,
            stream=stream if stream else None
        )
        
        years = class_service.get_all_academic_years()
        with connection.cursor() as cursor:
            cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE ORDER BY display_name")
            classes = cursor.fetchall()
            cursor.execute("SELECT DISTINCT stream_code FROM classes WHERE stream_code IS NOT NULL AND stream_code != ''")
            streams = [s['stream_code'] for s in cursor.fetchall()]
            
        return render_template('report_fee_balances.html', 
                             data=data, 
                             years=years, 
                             classes=classes, 
                             streams=streams,
                             academic_year_id=int(academic_year_id) if academic_year_id else None,
                             class_id=int(class_id) if class_id else None,
                             stream=stream)
    finally:
        connection.close()

@app.route("/admin/fees/reports/aging")
@login_required
@admin_required
def fee_arrears_aging_report():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        data = fees_service.get_arrears_aging_report()
        return render_template("fees_aging_report.html", data=data)
    finally:
        connection.close()

@app.route('/admin/fees/voteheads', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_voteheads():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    if request.method == 'POST':
        name = request.form.get('name').strip()
        priority = int(request.form.get('priority', 99))
        is_mandatory = 1 if request.form.get('is_mandatory') else 0
        description = request.form.get('description', '').strip()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO fee_voteheads (name, priority, is_mandatory, description)
                    VALUES (%s, %s, %s, %s)
                """, (name, priority, is_mandatory, description))
            connection.commit()
            flash(f"✓ Votehead '{name}' created.", "success")
        except Exception as e:
            flash(str(e), "error")
            
    voteheads = fees_service.get_voteheads()
    connection.close()
    return render_template('manage_voteheads.html', voteheads=voteheads)

@app.route('/admin/fees/student_groups', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_student_groups():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    if request.method == 'POST':
        name = request.form.get('name').strip()
        description = request.form.get('description', '').strip()
        try:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO student_groups (name, description) VALUES (%s, %s)", (name, description))
            connection.commit()
            flash(f"✓ Student Group '{name}' created.", "success")
        except Exception as e:
            flash(f"Error: {str(e)}", "error")
            
    student_groups = fees_service.get_student_groups(active_only=False)
    connection.close()
    return render_template('manage_student_groups.html', student_groups=student_groups)

# --- M-PESA RECONCILIATION ---
@app.route('/admin/fees/mpesa/reconcile')
@login_required
@admin_required
def fees_mpesa_reconcile():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        report = fees_service.get_mpesa_reconciliation_report()
        return render_template('mpesa_reconciliation.html', report=report)
    finally:
        connection.close()

@app.route('/api/fees/import-mpesa', methods=['POST'])
@login_required
@admin_required
@csrf.exempt
def api_import_mpesa():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'})
    
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({'success': False, 'message': 'Invalid file format. Upload CSV'})

    import csv
    import io
    from decimal import Decimal
    
    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
    csv_input = csv.DictReader(stream)
    
    transactions = []
    for row in csv_input:
        # Map common M-Pesa CSV headers (Simplified for this demo)
        # Expected: Receipt No, Completion Time, Details, Paid In, Sender Name, Sender Phone
        try:
            tx = {
                'transaction_no': row.get('Receipt No') or row.get('transaction_no'),
                'amount': Decimal(row.get('Paid In') or row.get('Amount', '0').replace(',', '')),
                'sender_name': row.get('Details') or row.get('Sender Name', 'Unknown'),
                'sender_phone': row.get('Sender Phone', ''),
                'transaction_time': row.get('Completion Time') or row.get('transaction_time')
            }
            if tx['transaction_no']:
                transactions.append(tx)
        except:
            continue

    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        summary = fees_service.import_mpesa_statement(transactions)
        return jsonify({'success': True, 'summary': summary})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        connection.close()

# --- WAIVER & SCHOLARSHIP MANAGEMENT ---
@app.route('/admin/fees/waivers')
@login_required
@admin_required
def fees_waiver_management():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    class_service = ClassManagementService(connection)
    try:
        categories = fees_service.get_waiver_categories()
        years = class_service.get_all_academic_years()
        current_term_no, current_year_val = get_current_term_and_year()
        
        # Get current term ID
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM uniform_term_dates WHERE term_number = %s AND YEAR(start_date) = %s", (current_term_no, current_year_val))
            curr_term = cursor.fetchone()
            
            # Fetch recent assignments
            cursor.execute("""
                SELECT sw.*, si.FName, si.SName, fwc.name as category_name, ay.year as year_name, utd.term_number
                FROM student_waivers sw
                JOIN studentinfo si ON sw.admno = si.AdmNo
                JOIN fee_waiver_categories fwc ON sw.category_id = fwc.id
                JOIN academic_years ay ON sw.academic_year_id = ay.id
                JOIN uniform_term_dates utd ON sw.term_id = utd.id
                ORDER BY sw.created_at DESC LIMIT 50
            """)
            recent_waivers = cursor.fetchall()
            
            cursor.execute("SELECT * FROM uniform_term_dates ORDER BY start_date DESC LIMIT 10")
            terms = cursor.fetchall()

        return render_template('fee_waiver_management.html', 
                             categories=categories, 
                             years=years, 
                             terms=terms,
                             current_term=curr_term,
                             recent_waivers=recent_waivers)
    finally:
        connection.close()

@app.route('/fees/waiver/assign', methods=['POST'])
@login_required
@admin_required
def assign_waiver():
    admno = int(request.form.get('admno'))
    category_id = int(request.form.get('category_id'))
    year_id = int(request.form.get('year_id'))
    term_id = int(request.form.get('term_id'))
    user_id = session.get('userNo')
    
    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        fees_service.assign_waiver_to_student(admno, category_id, year_id, term_id, user_id)
        flash(f"✓ Waiver successfully assigned to Student {admno}.", "success")
    except FeesError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('fees_waiver_management'))


@app.route('/admin/fees/structures', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_fee_structures():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    class_service = ClassManagementService(connection)
    
    if request.method == 'POST':
        year_id = int(request.form.get('year_id'))
        term_id = int(request.form.get('term_id'))
        class_groups = request.form.getlist('class_groups')
        specific_classes = request.form.getlist('specific_classes')
        categories = request.form.getlist('categories')
        
        # Extract votehead items from form
        votehead_ids = request.form.getlist('votehead_id')
        amounts = request.form.getlist('amount')
        
        items = []
        for vid, amt in zip(votehead_ids, amounts):
            if amt and float(amt) > 0:
                items.append({'votehead_id': int(vid), 'amount': float(amt)})
        
        if not items:
            flash("Please enter at least one votehead amount.", "error")
        elif not class_groups and not specific_classes:
            flash("Please select at least one class group OR specific class.", "error")
        elif not categories:
            flash("Please select at least one student category.", "error")
        else:
            try:
                # Handle specific classes if provided
                c_ids = [int(cid) for cid in specific_classes] if specific_classes else None
                results = fees_service.create_bulk_fee_structures(year_id, term_id, class_groups, categories, items, session['userNo'], class_ids=c_ids)
                flash(f"✓ {results['success']} structures created, {results['skipped']} already existed.", "success")
            except Exception as e:
                flash(str(e), "error")
        
    structures_raw = fees_service.get_fee_structures()
    
    # Group structures by (Year, Class/Group, Category) for simplified view
    grouped_structures = {}
    for s in structures_raw:
        label = s['specific_class_name'] if s['class_id'] else s['class_group_code']
        key = (s['academic_year_id'], label, s['student_category'])
        if key not in grouped_structures:
            grouped_structures[key] = {
                'id': s['id'], # For backwards compatibility or primary entry
                'year_name': s['year_name'],
                'academic_year_id': s['academic_year_id'],
                'label': label,
                'class_id': s['class_id'],
                'class_group_code': s['class_group_code'],
                'student_category': s['student_category'],
                'terms': [],
                'total_year': 0
            }
        grouped_structures[key]['terms'].append(s['term_number'])
        grouped_structures[key]['total_year'] += float(s['total_amount'])
    
    structures = sorted(grouped_structures.values(), key=lambda x: (x['year_name'], x['label']), reverse=True)
    voteheads = fees_service.get_voteheads()

    years = class_service.get_all_academic_years()
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM uniform_term_dates ORDER BY year DESC, term_number DESC")
        terms = cursor.fetchall()
        cursor.execute("SELECT classID, display_name, class_group_code FROM classes WHERE is_active = TRUE ORDER BY display_name")
        all_classes = cursor.fetchall()
        
    class_groups = [{'code': k, 'name': v['name']} for k, v in class_service.get_class_groups().items()]
    categories_list = ['Day', 'Boarding', 'Normal', 'Special', 'Transport', 'all']
    
    connection.close()
    return render_template('manage_fee_structures.html', 
                         structures=structures, 
                         voteheads=voteheads,
                         years=years,
                         terms=terms,
                         class_groups=class_groups,
                         all_classes=all_classes,
                         categories=categories_list)

@app.route('/admin/fees/structures/edit/<int:structure_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_fee_structure(structure_id):
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    if request.method == 'POST':
        try:
            votehead_ids = request.form.getlist('votehead_id')
            amounts = request.form.getlist('amount')
            
            items = []
            for vid, amt in zip(votehead_ids, amounts):
                if amt and float(amt) > 0:
                    items.append({'votehead_id': int(vid), 'amount': float(amt)})
            
            fees_service.update_fee_structure(structure_id, items, session['userNo'])
            flash("✓ Fee structure updated successfully.", "success")
            return redirect(url_for('manage_fee_structures'))
        except FeesError as e:
            flash(str(e), "error")
        except Exception as e:
            flash(f"System error: {str(e)}", "error")
        finally:
            connection.close()

    # GET
    structure = fees_service.get_fee_structure_details(structure_id)
    if not structure:
        flash("Structure not found.", "error")
        connection.close()
        return redirect(url_for('manage_fee_structures'))
        
    voteheads = fees_service.get_voteheads()
    # Map current amounts to voteheads for the form
    amount_map = {item['votehead_id']: item['amount'] for item in structure['items']}
    
    connection.close()
    return render_template('edit_fee_structure.html', 
                         s=structure, voteheads=voteheads, amount_map=amount_map)

@app.route('/admin/fees/structures/delete/<int:structure_id>', methods=['POST'])
@login_required
@admin_required
def delete_fee_structure(structure_id):
    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        fees_service.delete_fee_structure(structure_id)
        flash("Fee structure deleted.", "info")
    except Exception as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('manage_fee_structures'))

@app.route('/admin/fees/structures/card')
@login_required
def fee_structure_card():
    """Detailed breakdown of fee structures by votehead for a group/class."""
    year_id = request.args.get('year_id')
    group_code = request.args.get('group_code')
    class_id = request.args.get('class_id')
    category = request.args.get('category', 'Day')
    
    connection = get_db_connection()
    fees_service = FeesService(connection)
    class_service = ClassManagementService(connection)
    
    if not year_id:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM academic_years WHERE is_current = TRUE LIMIT 1")
            row = cursor.fetchone()
            year_id = row['id'] if row else None
            
    # Get all terms for the year
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, term_number FROM uniform_term_dates WHERE academic_year_id = %s ORDER BY term_number", (year_id,))
        terms = cursor.fetchall()
        
    # Get all voteheads
    voteheads = fees_service.get_voteheads()
    
    # Build data matrix: votehead_id -> {term_id -> amount}
    data = {v['id']: {'name': v['name'], 'terms': {t['id']: 0 for t in terms}, 'yearly': 0} for v in voteheads}
    
    is_locked = False
    with connection.cursor() as cursor:
        query = """
            SELECT fsi.votehead_id, fsi.amount, fs.term_id, fs.is_locked
            FROM fee_structure_items fsi
            JOIN fee_structures fs ON fsi.fee_structure_id = fs.id
            WHERE fs.academic_year_id = %s AND fs.student_category = %s
        """
        params = [year_id, category]
        
        if class_id:
            query += " AND fs.class_id = %s"
            params.append(class_id)
        else:
            query += " AND fs.class_group_code = %s AND (fs.class_id IS NULL OR fs.class_id = 0)"
            params.append(group_code or 'all')
            
        cursor.execute(query, params)
        items = cursor.fetchall()
        
        for item in items:
            if item['votehead_id'] in data:
                data[item['votehead_id']]['terms'][item['term_id']] = item['amount']
                data[item['votehead_id']]['yearly'] += item['amount']
                if item.get('is_locked'):
                    is_locked = True
                
    # Filter out zero rows
    filtered_data = {k: v for k, v in data.items() if v['yearly'] > 0}
    
    years = class_service.get_all_academic_years()
    class_groups = class_service.get_class_groups()
    with connection.cursor() as cursor:
        cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE ORDER BY display_name")
        all_classes = cursor.fetchall()
    
    # Get selected label
    selected_label = ""
    if class_id:
        sel_c = next((c for c in all_classes if str(c['classID']) == str(class_id)), None)
        selected_label = sel_c['display_name'] if sel_c else "Class"
    else:
        selected_label = group_code
        
    connection.close()
    return render_template('fee_structure_card.html', 
                         data=filtered_data, 
                         terms=terms, 
                         years=years,
                         class_groups=class_groups,
                         all_classes=all_classes,
                         year_id=year_id,
                         group_code=group_code,
                         class_id=class_id,
                         category=category,
                         selected_label=selected_label,
                         is_locked=is_locked)

@app.route('/admin/fees/structures/download')
@login_required
def fee_structure_download():
    """Generate PDF for fee structure card."""
    year_id = request.args.get('year_id')
    group_code = request.args.get('group_code')
    class_id = request.args.get('class_id')
    category = request.args.get('category', 'Day')
    
    connection = get_db_connection()
    fees_service = FeesService(connection)
    class_service = ClassManagementService(connection)
    
    if not year_id:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM academic_years WHERE is_current = TRUE LIMIT 1")
            row = cursor.fetchone()
            year_id = row['id'] if row else None
            
    # Get all terms for the year
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, term_number FROM uniform_term_dates WHERE academic_year_id = %s ORDER BY term_number", (year_id,))
        terms = cursor.fetchall()
        
    voteheads = fees_service.get_voteheads()
    data = {v['id']: {'name': v['name'], 'terms': {t['id']: 0 for t in terms}, 'yearly': 0} for v in voteheads}
    
    with connection.cursor() as cursor:
        query = """
            SELECT fsi.votehead_id, fsi.amount, fs.term_id
            FROM fee_structure_items fsi
            JOIN fee_structures fs ON fsi.fee_structure_id = fs.id
            WHERE fs.academic_year_id = %s AND fs.student_category = %s
        """
        params = [year_id, category]
        
        if class_id:
            query += " AND fs.class_id = %s"
            params.append(class_id)
        else:
            query += " AND fs.class_group_code = %s AND (fs.class_id IS NULL OR fs.class_id = 0)"
            params.append(group_code or 'all')
            
        cursor.execute(query, params)
        items = cursor.fetchall()
        
        for item in items:
            if item['votehead_id'] in data:
                data[item['votehead_id']]['terms'][item['term_id']] = item['amount']
                data[item['votehead_id']]['yearly'] += item['amount']
                
    filtered_data = {k: v for k, v in data.items() if v['yearly'] > 0}
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT classID, display_name FROM classes WHERE classID = %s", (class_id,))
        sel_c = cursor.fetchone()
        selected_label = sel_c['display_name'] if sel_c else (group_code or 'all')
    
    connection.close()
    
    try:
        from weasyprint import HTML
        from datetime import datetime
        
        rendered = render_template('fee_structure_card.html', 
                                 data=filtered_data, 
                                 terms=terms, 
                                 year_id=year_id,
                                 group_code=group_code,
                                 class_id=class_id,
                                 category=category,
                                 selected_label=selected_label,
                                 is_pdf=True,
                                 datetime=datetime)
        
        pdf = HTML(string=rendered, base_url=request.base_url).write_pdf()
        
        filename = f"Fee_Structure_{selected_label}_{category}.pdf".replace(" ", "_")
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response
    except Exception as e:
        app.logger.error(f"PDF download error: {str(e)}")
        return f"Error generating PDF: {str(e)}", 500

@app.route('/admin/fees/structures/overview')
@login_required
@admin_required
def fee_structures_overview():
    """Show per-term totals per class group/category/specific class for a selected year."""
    year_id = request.args.get('year_id')
    connection = get_db_connection()
    if not year_id:
        # Default to current year
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM academic_years WHERE is_current = TRUE LIMIT 1")
            row = cursor.fetchone()
            year_id = row['id'] if row else None
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, term_number FROM uniform_term_dates WHERE academic_year_id = %s ORDER BY term_number", (year_id,))
        terms = cursor.fetchall()
        
        # Enhanced query to join specific class name
        cursor.execute("""
            SELECT fs.class_group_code, fs.class_id, fs.student_category, fs.term_id, fs.total_amount,
                   c.display_name as specific_class_name
            FROM fee_structures fs
            LEFT JOIN classes c ON fs.class_id = c.classID
            WHERE fs.academic_year_id = %s
        """, (year_id,))
        rows = cursor.fetchall()
        
        cursor.execute("SELECT id, year, is_current FROM academic_years ORDER BY year DESC")
        years = cursor.fetchall()
        
    # Build matrix
    term_ids = [t['id'] for t in terms]
    matrix = {}
    for r in rows:
        # Complex key to hold IDs for links
        label = r['specific_class_name'] if r['class_id'] else r['class_group_code']
        key = (label, r['student_category'], r['class_group_code'], r['class_id'])
        if key not in matrix:
            matrix[key] = {tid: 0 for tid in term_ids}
        matrix[key][r['term_id']] = r['total_amount']
        
    connection.close()
    return render_template('fee_structure_overview.html', year_id=year_id, years=years, terms=terms, matrix=matrix)

@app.route('/admin/fees/structures/copy', methods=['POST'])
@login_required
@admin_required
def copy_fee_structure():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    try:
        from_id = int(request.form.get('from_structure_id'))
        year_id = int(request.form.get('target_year_id'))
        term_id = int(request.form.get('target_term_id'))
        
        fees_service.copy_fee_structure(from_id, year_id, term_id, session['userNo'])
        flash("✓ Fee structure copied successfully.", "success")
    except FeesError as e:
        flash(str(e), "error")
        
    connection.close()
    return redirect(url_for('manage_fee_structures'))

@app.route('/admin/fees/structures/yearly/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_yearly_fee_structure_route():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    if request.method == 'POST':
        try:
            year_id = int(request.form.get('year_id'))
            class_id = request.form.get('class_id')
            class_id = int(class_id) if class_id else None
            group_code = request.form.get('group_code')
            category = request.form.get('category')
            
            # Extract votehead amounts
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM fee_voteheads WHERE is_active = 1")
                voteheads = cursor.fetchall()
            
            term_amounts = {}
            for v in voteheads:
                v_id = v['id']
                term_amounts[v_id] = {
                    't1': request.form.get(f'v_{v_id}_t1', 0),
                    't2': request.form.get(f'v_{v_id}_t2', 0),
                    't3': request.form.get(f'v_{v_id}_t3', 0)
                }
            
            fees_service.create_yearly_fee_structure(year_id, class_id, group_code, category, term_amounts, session['userNo'])
            flash("✓ Yearly fee structure created/updated successfully.", "success")
            return redirect(url_for('fee_structures_overview'))
        except FeesError as e:
            flash(str(e), "error")
        except Exception as e:
            flash(f"System error: {str(e)}", "error")
        finally:
            connection.close()
            return redirect(url_for('fee_structures_overview'))

    # GET
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, year, is_current FROM academic_years ORDER BY year DESC")
        years = cursor.fetchall()
        cursor.execute("SELECT classID, display_name, class_group_code FROM classes ORDER BY display_name")
        classes = cursor.fetchall()
        cursor.execute("SELECT name FROM fee_student_groups WHERE is_active = 1")
        student_groups = cursor.fetchall()
        cursor.execute("SELECT id, name, priority FROM fee_voteheads WHERE is_active = 1 ORDER BY priority ASC")
        voteheads = cursor.fetchall()
    
    connection.close()
    return render_template('create_yearly_fee_structure.html', 
                         years=years, classes=classes, 
                         student_groups=student_groups, voteheads=voteheads)

@app.route('/admin/fees/structures/lock/<int:structure_id>', methods=['POST'])
@login_required
@admin_required
def toggle_structure_lock(structure_id):
    connection = get_db_connection()
    fees_service = FeesService(connection)
    lock = request.form.get('lock') == '1'
    try:
        fees_service.toggle_structure_lock(structure_id, lock)
        flash("Structure status updated.", "success")
    except Exception as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(request.referrer or url_for('fee_structures_overview'))


@app.route('/admin/fees/collect', methods=['GET', 'POST'])
@login_required
@admin_required
def collect_fees():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    if request.method == 'POST':
        adm_val = request.form.get('admno')
        year_val = request.form.get('year_id')
        term_val = request.form.get('term_id')
        
        if not adm_val or not year_val or not term_val:
            flash("Missing required fields: Student, Academic Year, and Term must be selected.", "error")
            return redirect(url_for('collect_fees'))

        try:
            admno = int(adm_val)
            amount = Decimal(request.form.get('amount', '0'))
            mode = request.form.get('mode')
            reference = request.form.get('reference', '').strip()
            bank = request.form.get('bank', '').strip()
            date = request.form.get('date')
            year_id = int(year_val)
            term_id = int(term_val)
            
            result = fees_service.record_payment(admno, amount, mode, reference, bank, date, year_id, term_id, session['userNo'])
            flash(f"✓ Payment received. Receipt No: {result['receipt_no']}", "success")
            return redirect(url_for('print_fee_receipt', payment_id=result['payment_id']))
        except FeesError as e:
            flash(str(e), "error")
        except ValueError:
            flash("Invalid input: Please check your numbers and selections.", "error")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "error")
            
    class_service = ClassManagementService(connection)
    years = class_service.get_all_academic_years()
    
    # Identify current year/term
    current_year_id = None
    for y in years:
        if y.get('is_current'):
            current_year_id = y['id']
            break
            
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM uniform_term_dates ORDER BY year DESC, term_number DESC")
        terms = cursor.fetchall()
        
        # Current term from CURDATE
        cursor.execute("SELECT id FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date LIMIT 1")
        term_res = cursor.fetchone()
        current_term_id = term_res['id'] if term_res else (terms[0]['id'] if terms else None)
        
    connection.close()
    return render_template('collect_fees.html', 
                         years=years, 
                         terms=terms, 
                         current_year_id=current_year_id,
                         current_term_id=current_term_id,
                         now=datetime.now())

@app.route('/admin/fees/bulk_post', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_post_fees():
    """Bulk posting of receipts from CSV."""
    if request.method == 'GET':
        return render_template('bulk_post_fees.html')

    file = request.files.get('file')
    if not file:
        flash('Upload a CSV file.', 'error')
        return redirect(url_for('bulk_post_fees'))

    connection = get_db_connection()
    fees_service = FeesService(connection)
    posted = 0
    errors = []
    try:
        import csv, io
        stream = io.TextIOWrapper(file.stream, encoding='utf-8')
        reader = csv.DictReader(stream)
        for row in reader:
            try:
                fees_service.record_payment(
                    admno=int(row['admno']),
                    amount=Decimal(row['amount']),
                    mode=row.get('mode', 'CASH'),
                    reference=row.get('reference', '').strip(),
                    bank=row.get('bank', '').strip(),
                    date=row.get('date') or datetime.now().strftime('%Y-%m-%d'),
                    year_id=int(row['year_id']),
                    term_id=int(row['term_id']),
                    user_id=session['userNo']
                )
                posted += 1
            except Exception as e:
                errors.append(str(e))
        flash(f"✓ Bulk posting complete. Posted: {posted}. Errors: {len(errors)}", 'success')
    finally:
        connection.close()
    return redirect(url_for('fees_dashboard'))

@app.route('/admin/fees/bulk_debit', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_debit_term():
    """Bulk debit of term fees for selected classes using existing structures."""
    connection = get_db_connection()
    fees_service = FeesService(connection)
    class_service = ClassManagementService(connection)
    if request.method == 'POST':
        class_ids = [int(cid) for cid in request.form.getlist('class_ids')]
        year_id = int(request.form.get('year_id'))
        term_id = int(request.form.get('term_id'))
        count = fees_service.bulk_invoice_classes(class_ids, year_id, term_id, session['userNo'])
        connection.close()
        flash(f"✓ Debited term fees for {count} students.", 'success')
        return redirect(url_for('fees_dashboard'))
    years = class_service.get_all_academic_years()
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM uniform_term_dates ORDER BY year DESC, term_number DESC")
        terms = cursor.fetchall()
        cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE ORDER BY display_name")
        classes = cursor.fetchall()
    connection.close()
    return render_template('bulk_debit_term.html', years=years, terms=terms, classes=classes)

@app.route('/api/fees/recent_payments')
@login_required
def api_recent_payments():
    admno = request.args.get('admno')
    if not admno:
        return jsonify([])
    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        data = fees_service.get_recent_payments(int(admno), limit=5)
        return jsonify(data)
    finally:
        connection.close()

@app.route('/api/fees/statement')
@login_required
def api_statement():
    admno = request.args.get('admno')
    year_id = request.args.get('year_id')
    if not admno:
        return jsonify([])
    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        data = fees_service.get_student_statement(int(admno), int(year_id) if year_id else None)
        return jsonify(data)
    finally:
        connection.close()

@app.route('/admin/fees/receipt/<int:payment_id>')
@login_required
def print_fee_receipt(payment_id):
    connection = get_db_connection()
    fees_service = FeesService(connection)
    try:
        receipt = fees_service.get_receipt_details(payment_id)
        if not receipt:
            flash("Receipt not found.", "error")
            return redirect(url_for('fees_dashboard'))
        
        # Combine names for template
        receipt['Fullname'] = f"{receipt['FName']} {receipt['MName'] or ''} {receipt['SName']}".strip().replace('  ', ' ')
        
        return render_template('print_fee_receipt.html', receipt=receipt, allocations=receipt.get('allocations', []))
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for('fees_dashboard'))
    finally:
        connection.close()

@app.route('/admin/fees/receipts')
@login_required
@admin_required
def fee_receipts_register():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    admno = request.args.get('admno')
    mode = request.args.get('mode')
    
    records = fees_service.get_receipts_register(
        start_date=start_date,
        end_date=end_date,
        admno=int(admno) if admno else None,
        mode=mode
    )
    
    connection.close()
    return render_template('fee_receipts_register.html', records=records, filters=request.args)

@app.route('/admin/fees/receipt/<int:payment_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_fee_receipt(payment_id):
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    if request.method == 'POST':
        mode = request.form.get('mode')
        reference = request.form.get('reference')
        bank = request.form.get('bank')
        date = request.form.get('date')
        
        try:
            fees_service.update_payment_details(payment_id, mode, reference, bank, date, session['userNo'])
            flash("✓ Receipt details updated successfully.", "success")
        except Exception as e:
            flash(str(e), "error")
        finally:
            connection.close()
        return redirect(url_for('fee_receipts_register'))

    receipt = fees_service.get_receipt_details(payment_id)
    connection.close()
    
    if not receipt:
        flash("Receipt not found.", "error")
        return redirect(url_for('fee_receipts_register'))
        
    return render_template('edit_fee_receipt.html', receipt=receipt)

@app.route('/admin/fees/receipt/<int:payment_id>/void', methods=['POST'])
@login_required
@admin_required
def void_fee_receipt(payment_id):
    connection = get_db_connection()
    fees_service = FeesService(connection)
    reason = request.form.get('reason', 'System cancellation')
    
    try:
        fees_service.void_receipt(payment_id, session['userNo'], reason)
        flash("✓ Receipt has been voided and ledger adjusted.", "success")
    except Exception as e:
        flash(str(e), "error")
    finally:
        connection.close()
        
    return redirect(request.referrer or url_for('fee_receipts_register'))

# =========================================================================
# FINANCE & GENERAL LEDGER ROUTES
# =========================================================================

@app.route('/admin/finance')
@app.route('/admin/finance/dashboard')
@login_required
@admin_required
def finance_dashboard():
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    
    try:
        stats = finance_service.get_dashboard_summary()
        accounts = finance_service.get_accounts()
        
        # Summary of recent transactions
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT ft.*, SUM(le.debit) as total_debit, SUM(le.credit) as total_credit, u.username as created_by_name
                FROM finance_transactions ft
                JOIN finance_ledger_entries le ON ft.id = le.transaction_id
                LEFT JOIN users u ON ft.created_by = u.userNo
                GROUP BY ft.id
                ORDER BY ft.id DESC LIMIT 10
            """)
            recent_txns = cursor.fetchall()
            
        return render_template('finance_dashboard.html', 
                             stats=stats, 
                             accounts=accounts, 
                             recent_txns=recent_txns)
    finally:
        connection.close()

@app.route('/admin/finance/vouchers', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_vouchers():
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    procurement_service = ProcurementService(connection)
    
    if request.method == 'POST':
        try:
            payee = request.form.get('payee_name')
            supplier_id = request.form.get('supplier_id')
            po_id = request.form.get('po_id')
            
            supplier_id = int(supplier_id) if supplier_id else None
            po_id = int(po_id) if po_id else None
                
            amount = Decimal(request.form.get('amount') or 0)
            vat = Decimal(request.form.get('vat_amount') or 0)
            wht = Decimal(request.form.get('wht_amount') or 0)
            
            mode = request.form.get('payment_mode', 'CASH')
            account_id = int(request.form.get('account_id'))
            
            cheque_no = request.form.get('cheque_no', '')
            description = request.form.get('description')
            
            finance_service.create_voucher(payee, amount, mode, account_id, cheque_no, description, session['userNo'], supplier_id, po_id, None, vat, wht)
            flash("✓ Voucher created and submitted for verification.", "success")
        except Exception as e:
            flash(str(e), "error")
        except Exception as e:
            flash(str(e), "error")
            
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                v.id, v.voucher_no, v.payee_name, v.amount, v.payment_mode, v.cheque_no, 
                v.description, v.status, v.created_at, u.username as created_by_name, 
                a.name as account_name, s.company as supplier_name, po.po_number,
                'VOUCHER' as source_type
            FROM finance_payment_vouchers v 
            LEFT JOIN users u ON v.created_by = u.userNo 
            LEFT JOIN finance_accounts a ON v.account_id = a.id
            LEFT JOIN suppliers s ON v.supplier_id = s.supplierID
            LEFT JOIN purchase_orders po ON v.po_id = po.id
            
            UNION ALL
            
            SELECT 
                sp.id, sp.reference_no as voucher_no, s.company as payee_name, sp.amount, UPPER(sp.payment_mode) as payment_mode, 
                CASE WHEN UPPER(sp.payment_mode) = 'CHEQUE' THEN sp.reference_no ELSE '' END as cheque_no,
                CONCAT('Direct PO Payment Reference: ', sp.reference_no) as description, 
                'PAID' as status, sp.payment_date as created_at, u.username as created_by_name, 
                'Accounts Payable' as account_name, s.company as supplier_name, po.po_number,
                'PROCUREMENT' as source_type
            FROM supplier_payments sp
            JOIN purchase_orders po ON sp.po_id = po.id
            JOIN suppliers s ON po.supplier_id = s.supplierID
            LEFT JOIN users u ON sp.created_by = u.userNo
            WHERE sp.reference_no NOT LIKE 'PV-%'
            
            ORDER BY created_at DESC
        """)
        vouchers = cursor.fetchall()
        
    # Get active POS for dropdown
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, po_number, supplier_id, total_amount FROM purchase_orders WHERE payment_status != 'PAID' AND status = 'RECEIVED'")
        pending_pos = cursor.fetchall()

    accounts = finance_service.get_accounts()
    suppliers = procurement_service.get_suppliers(active_only=False)
    connection.close()
    return render_template('manage_vouchers.html', vouchers=vouchers, accounts=accounts, suppliers=suppliers, pending_pos=pending_pos)

@app.route('/admin/finance/vouchers/<int:voucher_id>/verify', methods=['POST'])
@login_required
@admin_required
def verify_voucher(voucher_id):
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    try:
        finance_service.verify_voucher(voucher_id, session['userNo'])
        flash("✓ Voucher verified successfully.", "success")
    except Exception as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('manage_vouchers'))

@app.route('/admin/finance/vouchers/<int:voucher_id>/authorize', methods=['POST'])
@login_required
@admin_required
def authorize_voucher(voucher_id):
    source_account_id = request.form.get('source_account_id')
    source_account_id = int(source_account_id) if source_account_id else None
    
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    try:
        finance_service.authorize_voucher(voucher_id, session['userNo'], source_account_id)
        flash("✓ Voucher authorized and posted to ledger.", "success")
    except Exception as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('manage_vouchers'))

@app.route('/admin/finance/vouchers/<int:voucher_id>/print_cheque')
@login_required
@admin_required
def print_cheque(voucher_id):
    source = request.args.get('source', 'VOUCHER')
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    
    if source == 'PROCUREMENT':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT sp.amount, sp.payment_date as created_at, sp.reference_no as cheque_no, 
                       s.company as payee_name, 'Direct PO Payment' as description
                FROM supplier_payments sp
                JOIN purchase_orders po ON sp.po_id = po.id
                JOIN suppliers s ON po.supplier_id = s.supplierID
                WHERE sp.id = %s
            """, (voucher_id,))
            voucher = cursor.fetchone()
    else:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM finance_payment_vouchers WHERE id = %s", (voucher_id,))
            voucher = cursor.fetchone()
    
    if not voucher or (source == 'VOUCHER' and voucher.get('payment_mode') != 'CHEQUE' and 'payment_mode' in voucher):
        # For procurement, we assume if you clicked print its a cheque or reference is the cheque
        pass 
        
    voucher['amount_in_words'] = finance_service.amount_to_words(voucher['amount'])
    connection.close()
    return render_template('print_cheque.html', voucher=voucher)

@app.route('/admin/finance/vouchers/<int:voucher_id>/print')
@login_required
@admin_required
def print_payment_voucher(voucher_id):
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT v.*, a.name as account_name, u1.username as created_by_name,
                   u2.username as verified_by_name, u3.username as authorized_by_name,
                   po.po_number
            FROM finance_payment_vouchers v
            LEFT JOIN finance_accounts a ON v.account_id = a.id
            LEFT JOIN users u1 ON v.created_by = u1.userNo
            LEFT JOIN users u2 ON v.verified_by = u2.userNo
            LEFT JOIN users u3 ON v.authorized_by = u3.userNo
            LEFT JOIN purchase_orders po ON v.po_id = po.id
            WHERE v.id = %s
        """, (voucher_id,))
        voucher = cursor.fetchone()
        
    if not voucher:
        flash("Voucher not found.", "error")
        return redirect(url_for('manage_vouchers'))
        
    amount_in_words = finance_service.amount_to_words(voucher['amount'])
    connection.close()
    return render_template('print_payment_voucher.html', voucher=voucher, amount_in_words=amount_in_words)

@app.route('/admin/finance/budgets', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_budgets():
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    
    if request.method == 'POST':
        account_id = int(request.form.get('account_id'))
        amount = Decimal(request.form.get('amount'))
        fiscal_year = int(request.form.get('fiscal_year'))
        
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO finance_budgets (account_id, annual_amount, fiscal_year, created_by)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE annual_amount = %s
            """, (account_id, amount, fiscal_year, session['userNo'], amount))
        connection.commit()
        flash("✓ Budget updated successfully.", "success")

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT b.*, a.name as account_name, a.code as account_code
            FROM finance_budgets b
            JOIN finance_accounts a ON b.account_id = a.id
            ORDER BY b.fiscal_year DESC, a.code ASC
        """)
        budgets = cursor.fetchall()
        
    accounts = finance_service.get_accounts()
    connection.close()
    return render_template('manage_budgets.html', budgets=budgets, accounts=accounts)

@app.route('/admin/finance/reports/trial_balance')
@login_required
@admin_required
def trial_balance_report():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    
    data = finance_service.get_trial_balance(date)
    connection.close()
    return render_template('report_trial_balance.html', data=data, date=date)

@app.route('/admin/finance/reports/income_statement')
@login_required
@admin_required
def income_statement_report():
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-01'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    try:
        data = finance_service.get_income_statement(start_date, end_date)
        return render_template('report_income_statement.html', data=data, start_date=start_date, end_date=end_date)
    finally:
        connection.close()

@app.route('/admin/finance/reports/balance_sheet')
@login_required
@admin_required
def balance_sheet_report():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    connection = get_db_connection()
    finance_service = FinanceService(connection)
    try:
        data = finance_service.get_balance_sheet(date)
        return render_template('report_balance_sheet.html', data=data, date=date)
    finally:
        connection.close()

# =========================================================================
# MPESA DARAJA INTEGRATION (Stubbed Webhook)
# =========================================================================

@app.route('/api/mpesa/callback', methods=['POST'])
@csrf.exempt
def mpesa_callback():
    """Receive Mpesa Daraja callbacks and post payment. Expects minimal fields.
    Payload example (simplified): { admno, amount, transaction_id, transaction_time }
    """
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid JSON'}), 400

    required = ['admno', 'amount', 'transaction_id']
    if not all(k in payload for k in required):
        return jsonify({'success': False, 'message': 'Missing fields'}), 400

    admno = int(payload['admno'])
    amount = Decimal(str(payload['amount']))
    reference = str(payload['transaction_id'])
    date = payload.get('transaction_time', datetime.now().strftime('%Y-%m-%d'))

    # Resolve current year/term
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, year FROM academic_years WHERE is_current = TRUE LIMIT 1")
        y = cursor.fetchone()
        cursor.execute("SELECT id FROM uniform_term_dates WHERE CURDATE() BETWEEN start_date AND end_date LIMIT 1")
        t = cursor.fetchone()
    if not y or not t:
        connection.close()
        return jsonify({'success': False, 'message': 'No active year/term'}), 400

    try:
        fees_service = FeesService(connection)
        result = fees_service.record_payment(
            admno=admno,
            amount=amount,
            mode='MPESA',
            reference=reference,
            bank='',
            date=date,
            year_id=y['id'],
            term_id=t['id'],
            user_id=0  # system user
        )
        return jsonify({'success': True, 'receipt_no': result['receipt_no']})
    except FeesError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    finally:
        connection.close()

@app.route('/admin/fees/rollup', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_fees_rollup():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    # Get academic years for selection
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, year, name FROM academic_years ORDER BY year DESC")
        years = cursor.fetchall()
        
    if request.method == 'POST':
        old_year_id = request.form.get('old_year_id')
        new_year_id = request.form.get('new_year_id')
        new_term_id = 1 # Default to term 1 for the new year
        
        if not all([old_year_id, new_year_id]):
            flash('Please select both source and destination years.', 'error')
            return redirect(url_for('admin_fees_rollup'))
            
        try:
            student_count = fees_service.carry_forward_balances(
                int(old_year_id), 
                int(new_year_id), 
                new_term_id, 
                session['userNo']
            )
            flash(f'Successfully rolled up balances for {student_count} students.', 'success')
            return redirect(url_for('admin_fees_rollup'))
        except Exception as e:
            flash(f'Error during roll-up: {str(e)}', 'error')
            
    return render_template('admin_rollup.html', years=years)

@app.route('/admin/fees/reallocate', methods=['GET', 'POST'])
@login_required
@admin_required
def reallocate_fee_payment():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    if request.method == 'POST':
        ref = request.form.get('reference_no').strip()
        from_adm = request.form.get('from_admno')
        to_adm = request.form.get('to_admno')
        reason = request.form.get('reason').strip()
        
        try:
            fees_service.reallocate_payment(ref, from_adm, to_adm, session['userNo'], reason)
            flash("✓ Payment successfully reallocated.", "success")
        except FeesError as e:
            flash(str(e), "error")
            
    connection.close()
    return render_template('payment_reallocation.html')


@app.route('/admin/fees/invoice', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_invoice():
    connection = get_db_connection()
    fees_service = FeesService(connection)
    class_service = ClassManagementService(connection)
    
    if request.method == 'POST':
        class_ids = [int(cid) for cid in request.form.getlist('class_ids')]
        year_id = int(request.form.get('year_id'))
        term_id = int(request.form.get('term_id'))
        
        # Check for specific votehead invoice
        specific_vh = request.form.get('specific_votehead_id')
        specific_amt = request.form.get('specific_amount')
        
        try:
            if specific_vh and specific_amt:
                count = fees_service.bulk_invoice_classes(
                    class_ids, year_id, term_id, session['userNo'], 
                    specific_votehead_id=int(specific_vh), 
                    specific_amount=Decimal(specific_amt)
                )
            else:
                count = fees_service.bulk_invoice_classes(class_ids, year_id, term_id, session['userNo'])
            flash(f"✓ Bulk invoicing complete. {count} students invoiced.", "success")
        except FeesError as e:
            flash(str(e), "error")
            
    years = class_service.get_all_academic_years()
    voteheads = fees_service.get_voteheads()
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM uniform_term_dates ORDER BY year DESC, term_number DESC")
        terms = cursor.fetchall()
        cursor.execute("SELECT classID, display_name FROM classes WHERE is_active = TRUE ORDER BY display_name")
        classes = cursor.fetchall()
        
    connection.close()
    return render_template('bulk_invoice.html', years=years, terms=terms, classes=classes, voteheads=voteheads)

@app.route('/student/<int:admno>/statement')
@login_required
def student_fee_statement(admno):
    connection = get_db_connection()
    fees_service = FeesService(connection)
    
    statement = fees_service.get_student_statement(admno)
    balance = fees_service.get_student_balance(admno)
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT FName, SName, AdmNo FROM studentinfo WHERE AdmNo = %s", (admno,))
        student = cursor.fetchone()
        
    connection.close()
    return render_template('fee_statement.html', statement=statement, balance=balance, student=student)

@app.route('/api/search_students_fees')
@login_required
def search_students_fees():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("""
        SELECT AdmNo, CONCAT(FName, ' ', SName) as name, AdmNo as id
        FROM studentinfo
        WHERE AdmNo LIKE %s OR FName LIKE %s OR SName LIKE %s
        LIMIT 10
    """, (f"%{q}%", f"%{q}%", f"%{q}%"))
    results = cursor.fetchall()
    connection.close()
    return jsonify(results)

@app.route('/api/search_students')
@login_required
def api_search_students():
    q = request.args.get('query', '').strip()
    if not q:
        return jsonify([])
    
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT si.AdmNo, si.FName, si.SName, c.display_name as class_name
                FROM studentinfo si
                LEFT JOIN class_allocation ca ON si.AdmNo = ca.student_id AND ca.is_current = TRUE
                LEFT JOIN classes c ON ca.class_id = c.classID
                WHERE si.AdmNo LIKE %s OR si.FName LIKE %s OR si.SName LIKE %s
                LIMIT 15
            """, (f"%{q}%", f"%{q}%", f"%{q}%"))
            return jsonify(cursor.fetchall())
    finally:
        connection.close()

# =========================================================================
# PROCUREMENT & REQUISITIONS ROUTES
# =========================================================================

@app.route('/admin/procurement/requisitions')
@login_required
@admin_required
def manage_requisitions():
    connection = get_db_connection()
    service = ProcurementService(connection)
    reqs = service.get_requisitions()
    connection.close()
    return render_template('manage_requisitions.html', requisitions=reqs)

@app.route('/admin/procurement/requisition/create', methods=['GET', 'POST'])
@login_required
def create_requisition():
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    if request.method == 'POST':
        dept_id = request.form.get('department_id')
        justification = request.form.get('justification')
        category = request.form.get('category', 'General')
        academic_year_id = request.form.get('academic_year_id')
        
        # Validation
        if not dept_id or not dept_id.strip():
            flash("Please specify a department for the requisition.", "error")
            return redirect(url_for('create_requisition'))
            
        try:
            # Convert to appropriate types
            dept_id = int(dept_id)
            academic_year_id = int(academic_year_id) if academic_year_id else None
        except ValueError:
            flash("Invalid department or academic year selected.", "error")
            return redirect(url_for('create_requisition'))
            
        descriptions = request.form.getlist('description[]')
        quantities = request.form.getlist('quantity[]')
        prices = request.form.getlist('price[]')
        
        items = []
        for d, q, p in zip(descriptions, quantities, prices):
            if d.strip() and q:
                items.append({
                    'description': d.strip(),
                    'quantity': float(q),
                    'estimated_unit_price': float(p) if p else 0
                })
        
        try:
            service.create_requisition(dept_id, items, session['userNo'], justification, category=category, academic_year_id=academic_year_id)
            flash("Requisition submitted for approval.", "success")
            return redirect(url_for('manage_requisitions'))
        except ProcurementError as e:
            flash(str(e), "error")
            
    # Fetch departments and academic years for the dropdown
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM staffdepts ORDER BY dept")
        depts = cursor.fetchall()
        cursor.execute("SELECT * FROM academic_years ORDER BY year DESC")
        academic_years = cursor.fetchall()
        
    connection.close()
    return render_template('create_requisition.html', depts=depts, academic_years=academic_years)
    return render_template('create_requisition.html', departments=depts)

@app.route('/admin/procurement/requisition/<int:req_id>')
@login_required
@admin_required
def view_requisition(req_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    req = service.get_requisition_details(req_id)
    
    if not req:
        flash("Requisition not found.", "error")
        connection.close()
        return redirect(url_for('manage_requisitions'))
    
    # If requisition is APPROVED, fetch suppliers for potential conversion to PO
    suppliers = []
    if req['status'] == 'APPROVED':
        with connection.cursor() as cursor:
            cursor.execute("SELECT supplierID, company FROM suppliers ORDER BY company")
            suppliers = cursor.fetchall()
            
    connection.close()
    return render_template('view_requisition.html', requisition=req, suppliers=suppliers)

@app.route('/admin/procurement/requisition/<int:req_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_requisition(req_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    try:
        service.update_requisition_status(req_id, 'APPROVED', session['userNo'])
        flash("✓ Requisition approved.", "success")
    except ProcurementError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('view_requisition', req_id=req_id))

@app.route('/admin/procurement/requisition/<int:req_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_requisition(req_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    try:
        service.update_requisition_status(req_id, 'REJECTED', session['userNo'])
        flash("✓ Requisition rejected.", "warning")
    except ProcurementError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('view_requisition', req_id=req_id))

@app.route('/admin/procurement/requisition/<int:req_id>/convert', methods=['POST'])
@login_required
@admin_required
def convert_requisition(req_id):
    supplier_id = request.form.get('supplier_id')
    if not supplier_id:
        flash("Please select a supplier for the Purchase Order.", "error")
        return redirect(url_for('view_requisition', req_id=req_id))

    connection = get_db_connection()
    service = ProcurementService(connection)
    try:
        po_info = service.convert_requisition_to_po(req_id, supplier_id, session['userNo'])
        flash(f"✓ Requisition converted to PO {po_info['po_number']}.", "success")
        return redirect(url_for('view_purchase_order', po_id=po_info['id']))
    except ProcurementError as e:
        flash(str(e), "error")
        return redirect(url_for('view_requisition', req_id=req_id))
    finally:
        connection.close()

@app.route('/admin/procurement/po/<int:po_id>/receive', methods=['GET', 'POST'])
@login_required
@admin_required
def receive_goods(po_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    po = service.get_po_details(po_id)
    
    if request.method == 'POST':
        item_ids = request.form.getlist('po_item_id[]')
        quantities = request.form.getlist('receive_qty[]')
        dn_ref = request.form.get('delivery_note_ref')
        notes = request.form.get('notes')
        
        items = []
        for i_id, q in zip(item_ids, quantities):
            if q and float(q) > 0:
                items.append({'po_item_id': int(i_id), 'quantity': float(q)})
        
        if not items:
            flash("Please specify quantities for items received.", "error")
        else:
            try:
                grn_no = service.record_grn(po_id, session['userNo'], items, dn_ref, notes)
                flash(f"✓ Goods Received Note {grn_no} recorded.", "success")
                return redirect(url_for('view_purchase_order', po_id=po_id))
            except ProcurementError as e:
                flash(str(e), "error")

    connection.close()
    return render_template('receive_goods.html', po=po)

@app.route('/admin/procurement/assets')
@login_required
@admin_required
def manage_assets():
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    category = request.args.get('category')
    condition = request.args.get('condition')
    filters = {}
    if category: filters['category'] = category
    if condition: filters['condition'] = condition
    
    assets = service.get_assets(filters)
    connection.close()
    return render_template('manage_assets.html', assets=assets)

@app.route('/admin/procurement/asset/register', methods=['GET', 'POST'])
@login_required
@admin_required
def register_asset():
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    if request.method == 'POST':
        data = {
            'asset_name': request.form.get('asset_name'),
            'tag_number': request.form.get('tag_number'),
            'category': request.form.get('category'),
            'purchase_date': request.form.get('purchase_date'),
            'purchase_value': float(request.form.get('purchase_value')),
            'location': request.form.get('location'),
            'condition_status': request.form.get('condition_status')
        }
        try:
            service.register_asset(data, session['userNo'])
            flash("✓ Asset registered successfully.", "success")
            return redirect(url_for('manage_assets'))
        except ProcurementError as e:
            flash(str(e), "error")
            
    connection.close()
    return render_template('register_asset.html')

@app.route('/admin/procurement/asset/<int:asset_id>/update', methods=['POST'])
@login_required
@admin_required
def update_asset(asset_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    new_cond = {
        'condition': request.form.get('condition_status'),
        'location': request.form.get('location')
    }
    
    try:
        service.update_asset_condition(asset_id, new_cond, session['userNo'])
        flash("✓ Asset updated.", "success")
    except ProcurementError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('manage_assets'))

# =========================================================================
# PROCUREMENT ROUTES
# =========================================================================

@app.route('/admin/procurement')
@login_required
@admin_required
def procurement_dashboard():
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    # Get Filters
    status_filter = request.args.get('status')
    po_number_filter = request.args.get('po_number')
    supplier_filter = request.args.get('supplier_id')
    
    pos = service.get_purchase_orders(
        status=status_filter, 
        po_number=po_number_filter, 
        supplier_id=int(supplier_filter) if supplier_filter else None
    )
    suppliers = service.get_suppliers()
    
    # Summary stats
    with connection.cursor() as cursor:
        cursor.execute("SELECT status, COUNT(*) as count FROM purchase_orders GROUP BY status")
        stats = cursor.fetchall()
        
    connection.close()
    return render_template('procurement_dashboard.html', pos=pos, suppliers=suppliers, stats=stats)

@app.route('/admin/procurement/budgets', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_procurement_budgets():
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    # Get Academic Year
    year_id = request.args.get('academic_year_id')
    if not year_id:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM academic_years WHERE is_current = 1 LIMIT 1")
            ay = cursor.fetchone()
            year_id = ay['id'] if ay else 1
            
    if request.method == 'POST':
        dept_id = request.form.get('department_id')
        category = request.form.get('category')
        amount = request.form.get('allocated_amount')
        
        try:
            service.set_budget(dept_id, year_id, category, Decimal(amount))
            flash(f"✓ Budget for {category} set successfully.", "success")
        except ProcurementError as e:
            flash(str(e), "error")
            
    budgets = service.get_budgets(year_id)
    
    # Context data
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM staffdepts ORDER BY dept")
        depts = cursor.fetchall()
        cursor.execute("SELECT * FROM academic_years ORDER BY year DESC")
        years = cursor.fetchall()
        
    connection.close()
    return render_template('procurement_budgets.html', 
                          budgets=budgets, 
                          departments=depts, 
                          academic_years=years,
                          current_year_id=int(year_id))

@app.route('/admin/procurement/reports/aging')
@login_required
@admin_required
def suppliers_aging_report():
    connection = get_db_connection()
    service = ProcurementService(connection)
    aging_data = service.get_suppliers_aging()
    connection.close()
    return render_template('suppliers_aging.html', aging_data=aging_data)

@app.route('/admin/procurement/suppliers', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_suppliers():
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    if request.method == 'POST':
        company = request.form.get('company')
        contact = request.form.get('contact_person')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')
        cert_no = request.form.get('cert_no', '')
        pin_no = request.form.get('pin_no', '')
        
        try:
            service.create_supplier(company, contact, email, phone, address, cert_no, pin_no)
            flash(f"✓ Supplier '{company}' added successfully.", "success")
        except ProcurementError as e:
            flash(str(e), "error")
            
    suppliers = service.get_suppliers(active_only=False)
    connection.close()
    return render_template('manage_suppliers.html', suppliers=suppliers)

@app.route('/admin/procurement/suppliers/<int:supplier_id>/statement')
@login_required
@admin_required
def vendor_statement(supplier_id):
    start_date = request.args.get('start_date', (datetime.now().replace(day=1)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    # Get supplier details
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM suppliers WHERE supplierID = %s", (supplier_id,))
        supplier = cursor.fetchone()
        
    if not supplier:
        connection.close()
        flash("Supplier not found.", "error")
        return redirect(url_for('manage_suppliers'))
        
    transactions = service.get_vendor_statement(supplier_id, start_date, end_date)
    connection.close()
    return render_template('vendor_statement.html', supplier=supplier, transactions=transactions, start_date=start_date, end_date=end_date)

@app.route('/admin/procurement/po/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_purchase_order():
    connection = get_db_connection()
    service = ProcurementService(connection)
    
    if request.method == 'POST':
        supplier_id = int(request.form.get('supplier_id'))
        order_date = request.form.get('order_date')
        notes = request.form.get('notes')
        
        # Parse dynamic items
        item_ids = request.form.getlist('item_id[]')
        descriptions = request.form.getlist('item_description[]')
        quantities = request.form.getlist('item_qty[]')
        unit_prices = request.form.getlist('item_price[]')
        
        items = []
        for i_id, d, q, p in zip(item_ids, descriptions, quantities, unit_prices):
            if d.strip() and q and p:
                items.append({
                    'item_id': int(i_id) if i_id and i_id.isdigit() else None,
                    'description': d.strip(),
                    'quantity': float(q),
                    'unit_price': float(p)
                })
        
        if not items:
            flash("Please add at least one item to the order.", "error")
        else:
            try:
                result = service.create_purchase_order(supplier_id, order_date, items, session['userNo'], notes)
                flash(f"✓ Purchase Order {result['po_number']} created.", "success")
                return redirect(url_for('view_purchase_order', po_id=result['id']))
            except ProcurementError as e:
                flash(str(e), "error")
                
    suppliers = service.get_suppliers()
    with connection.cursor() as cursor:
        # Fetch all catalog items for generic selection
        cursor.execute("SELECT item_id, item_name, current_stock FROM item_stock ORDER BY item_name")
        stock_items = cursor.fetchall()
        
        # Fetch only uniform items - Include all from uniform_prices even if stock is 0/missing
        cursor.execute("""
            SELECT DISTINCT p.item_name, s.item_id, COALESCE(s.current_stock, 0) as current_stock 
            FROM uniform_prices p
            LEFT JOIN item_stock s ON p.item_name = s.item_name
            ORDER BY p.item_name
        """)
        uniform_items = cursor.fetchall()

    connection.close()
    return render_template('create_purchase_order.html', suppliers=suppliers, stock_items=stock_items, uniform_items=uniform_items)

@app.route('/admin/procurement/po/<int:po_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_purchase_order(po_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    po = service.get_po_details(po_id)
    
    if not po:
        connection.close()
        flash("Purchase order not found.", "error")
        return redirect(url_for('procurement_dashboard'))
    
    if po['status'] not in ['DRAFT', 'PENDING_APPROVAL']:
        connection.close()
        flash(f"Cannot edit PO in {po['status']} status.", "error")
        return redirect(url_for('view_purchase_order', po_id=po_id))
    
    if request.method == 'POST':
        supplier_id = int(request.form.get('supplier_id'))
        order_date = request.form.get('order_date')
        notes = request.form.get('notes')
        
        # Parse dynamic items
        item_ids = request.form.getlist('item_id[]')
        descriptions = request.form.getlist('item_description[]')
        quantities = request.form.getlist('item_qty[]')
        unit_prices = request.form.getlist('item_price[]')
        
        items = []
        for i_id, d, q, p in zip(item_ids, descriptions, quantities, unit_prices):
            if d.strip() and q and p:
                items.append({
                    'item_id': int(i_id) if i_id and i_id.isdigit() else None,
                    'description': d.strip(),
                    'quantity': float(q),
                    'unit_price': float(p)
                })
        
        if not items:
            flash("Please add at least one item to the order.", "error")
        else:
            try:
                service.update_purchase_order(po_id, supplier_id, order_date, items, notes)
                flash(f"✓ Purchase Order {po['po_number']} updated.", "success")
                return redirect(url_for('view_purchase_order', po_id=po_id))
            except ProcurementError as e:
                flash(str(e), "error")
                
    suppliers = service.get_suppliers()
    with connection.cursor() as cursor:
        cursor.execute("SELECT item_id, item_name, current_stock FROM item_stock ORDER BY item_name")
        stock_items = cursor.fetchall()
        
    connection.close()
    return render_template('edit_purchase_order.html', po=po, suppliers=suppliers, stock_items=stock_items)

@app.route('/admin/procurement/po/<int:po_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_purchase_order(po_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    try:
        service.delete_purchase_order(po_id)
        flash("✓ Purchase Order deleted successfully.", "success")
    except ProcurementError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('procurement_dashboard'))

@app.route('/admin/procurement/po/<int:po_id>/print')
@login_required
@admin_required
def print_purchase_order(po_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    po = service.get_po_details(po_id)
    
    if not po:
        connection.close()
        flash("Purchase order not found.", "error")
        return redirect(url_for('procurement_dashboard'))
        
    connection.close()
    return render_template('print_purchase_order.html', po=po)

@app.route('/admin/procurement/po/<int:po_id>/download')
@login_required
@admin_required
def download_purchase_order(po_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    po = service.get_po_details(po_id)
    
    if not po:
        connection.close()
        flash("Purchase order not found.", "error")
        return redirect(url_for('procurement_dashboard'))
        
    connection.close()
    
    try:
        from weasyprint import HTML
        rendered = render_template('print_purchase_order.html', po=po, is_pdf=True)
        pdf = HTML(string=rendered, base_url=request.base_url).write_pdf()
        
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=PO-{po["po_number"]}.pdf'
        return response
    except Exception as e:
        flash(f"PDF Generation failed: {str(e)}", "error")
        return redirect(url_for('view_purchase_order', po_id=po_id))

@app.route('/admin/procurement/po/<int:po_id>')
@login_required
@admin_required
def view_purchase_order(po_id):
    connection = get_db_connection()
    service = ProcurementService(connection)
    finance_service = FinanceService(connection)
    po = service.get_po_details(po_id)
    
    if not po:
        connection.close()
        flash("Purchase order not found.", "error")
        return redirect(url_for('procurement_dashboard'))
        
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM supplier_payments WHERE po_id = %s ORDER BY payment_date DESC", (po_id,))
        payments = cursor.fetchall()

    accounts = finance_service.get_accounts()
    connection.close()
    return render_template('view_purchase_order.html', po=po, accounts=accounts, payments=payments)

@app.route('/admin/procurement/po/<int:po_id>/update_status', methods=['POST'])
@login_required
@admin_required
def update_po_status(po_id):
    new_status = request.form.get('status')
    connection = get_db_connection()
    service = ProcurementService(connection)
    try:
        service.update_po_status(po_id, new_status, session['userNo'])
        flash(f"✓ PO status updated to {new_status}.", "success")
    except ProcurementError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('view_purchase_order', po_id=po_id))

@app.route('/admin/procurement/po/<int:po_id>/pay', methods=['POST'])
@login_required
@admin_required
def record_po_payment(po_id):
    amount = Decimal(request.form.get('amount'))
    mode = request.form.get('payment_mode')
    reference = request.form.get('reference_no')
    date = request.form.get('payment_date')
    source_account_id = int(request.form.get('source_account_id'))
    
    connection = get_db_connection()
    service = ProcurementService(connection)
    try:
        service.record_po_payment(po_id, amount, mode, reference, date, session['userNo'], source_account_id)
        flash("✓ Payment recorded and posted to ledger.", "success")
    except ProcurementError as e:
        flash(str(e), "error")
    finally:
        connection.close()
    return redirect(url_for('view_purchase_order', po_id=po_id))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
