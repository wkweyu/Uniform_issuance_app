from app import get_db_connection
from fees_management_service import FeesService, FeesError
from decimal import Decimal

def test_yearly_creation():
    connection = get_db_connection()
    service = FeesService(connection)
    
    # Mock data for academic year 3 (2026), class 23, all categories
    year_id = 3
    class_id = 23
    group_code = 'Grade 1-3'
    category = 'Day'
    user_id = 32
    
    # Mock votehead data
    term_amounts = {
        1: {'t1': 10000, 't2': 8000, 't3': 5000},
        2: {'t1': 3000, 't2': 3000, 't3': 3000},
        3: {'t1': 5000, 't2': 5000, 't3': 5000}
    }
    
    try:
        print("Starting yearly structure creation test...")
        service.create_yearly_fee_structure(year_id, class_id, group_code, category, term_amounts, user_id)
        print("✓ Created successfully (Check DB)")
        
        # Verify
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, term_id, total_amount FROM fee_structures WHERE academic_year_id = 3 AND class_id = 23")
            rows = cursor.fetchall()
            print(f"Rows found for class 23: {len(rows)}")
            for r in rows:
                print(f"Structure ID: {r['id']}, Term ID: {r['term_id']}, Total: {r['total_amount']}")
                
    except Exception as e:
        print(f"Error: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    test_yearly_creation()
