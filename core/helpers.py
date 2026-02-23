from datetime import datetime
from flask import g
from core.db import get_db_connection

def get_current_term_and_year():
    """Get the currently active term and academic year for the current tenant."""
    school_id = g.school_id or 1
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT term_number, year
                FROM uniform_term_dates
                WHERE CURDATE() BETWEEN start_date AND end_date
                  AND school_id = %s
                LIMIT 1
            """, (school_id,))
            result = cursor.fetchone()
            if result:
                return result['term_number'], result['year']

            cursor.execute("""
                SELECT year FROM academic_years
                WHERE is_current = TRUE AND school_id = %s
                LIMIT 1
            """, (school_id,))
            res_year = cursor.fetchone()
            year = res_year['year'] if res_year else datetime.now().year
            return 1, year
    finally:
        connection.close()

def format_currency(amount):
    """Format a number as currency."""
    if amount is None:
        return "0.00"
    return "{:,.2f}".format(float(amount))



def get_class_group(class_name):
    return CLASS_GROUPS.get(class_name)




def generate_receipt_number(year, school_id):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT receipt_no FROM uniform_receipts
        WHERE yr = %s AND school_id = %s AND receipt_no IS NOT NULL
        ORDER BY id DESC LIMIT 1
    """, (year, school_id))
    last_receipt = cursor.fetchone()

    if last_receipt and last_receipt['receipt_no']:
        try:
            last_number = int(last_receipt['receipt_no'].split('-')[1])
            next_number = last_number + 1
        except (IndexError, ValueError):
            next_number = 1





# Uniform issuance form
#Enhance Submit issuance
# After issuing uniform, show receipt
# This is a helper function — no route decorator needed
# This is your actual route function
def get_class_name(cursor, admno, year):
    try:
        school_id = g.school_id or 1
        cursor.execute("""
            SELECT c.class_name
            FROM classallocation a
            JOIN classes c ON a.classID = c.classID
            WHERE a.AdmNo = %s AND a.thisYear = %s AND a.school_id = %s AND c.school_id = %s
            LIMIT 1
        """, (admno, year, school_id, school_id))
        class_row = cursor.fetchone()
        if class_row:
            return class_row['class_name']
        else:
            return None
    except Exception as e:
        print(f"Failed to fetch class name for {admno}, {year}: {e}")
        return None





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
    'Grade 9': 'Grade 7-9',
}
