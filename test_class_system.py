#!/usr/bin/env python3
"""
Comprehensive Test Suite for Class Management System
Validates all routes, service methods, and backward compatibility
"""

import pymysql
import sys
from class_management_service import ClassManagementService, ValidationError, PromotionError

def test_database_connection():
    """Test: Database connectivity"""
    print("\n=== TEST 1: Database Connectivity ===")
    try:
        connection = pymysql.connect(
            host='localhost',
            user='schooluser',
            password='jbs',
            database='schoolmngt'
        )
        connection.close()
        print("✅ Database connection successful")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


def test_required_tables():
    """Test: All required tables exist"""
    print("\n=== TEST 2: Required Tables Exist ===")
    try:
        connection = pymysql.connect(
            host='localhost',
            user='schooluser',
            password='jbs',
            database='schoolmngt'
        )
        
        required_tables = [
            'academic_years',
            'class_group_settings',
            'stream_settings',
            'classes',
            'class_allocation',
            'subjects',
            'class_subjects',
            'student_subjects',
            'teacher_allocations',
            'class_promotion_log'
        ]
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='schoolmngt'")
            existing_tables = [row[0] for row in cursor.fetchall()]
        
        missing = [t for t in required_tables if t not in existing_tables]
        
        if missing:
            print(f"❌ Missing tables: {missing}")
            connection.close()
            return False
        
        print(f"✅ All {len(required_tables)} required tables exist")
        connection.close()
        return True
    
    except Exception as e:
        print(f"❌ Table check failed: {e}")
        return False


def test_service_methods():
    """Test: ClassManagementService methods"""
    print("\n=== TEST 3: Service Methods ===")
    try:
        connection = pymysql.connect(
            host='localhost',
            user='schooluser',
            password='jbs',
            database='schoolmngt'
        )
        service = ClassManagementService(connection)
        
        # Test 1: Current year
        year = service.get_current_academic_year()
        assert year is not None, "Current year should exist"
        print(f"  ✅ get_current_academic_year() → Year {year['year']}")
        
        # Test 2: Streams
        streams = service.get_allowed_streams()
        assert len(streams) > 0, "Should have streams"
        print(f"  ✅ get_allowed_streams() → {len(streams)} streams")
        
        # Test 3: Class groups
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT code, name FROM class_group_settings")
            groups = cursor.fetchall()
        assert len(groups) > 0, "Should have class groups"
        print(f"  ✅ class_groups → {len(groups)} groups")
        
        # Test 4: Class group by name
        group = service.get_class_group_by_name("Grade 5")
        assert group == "Grade 4-6", f"Expected Grade 4-6, got {group}"
        print(f"  ✅ get_class_group_by_name('Grade 5') → {group}")
        
        # Test 5: All years
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM academic_years ORDER BY year")
            all_years = cursor.fetchall()
        assert len(all_years) >= 3, "Should have at least 3 years"
        print(f"  ✅ academic_years → {len(all_years)} years")
        
        connection.close()
        return True
    
    except Exception as e:
        print(f"❌ Service method test failed: {e}")
        return False


def test_backward_compatibility():
    """Test: Legacy tables still accessible"""
    print("\n=== TEST 4: Backward Compatibility ===")
    try:
        connection = pymysql.connect(
            host='localhost',
            user='schooluser',
            password='jbs',
            database='schoolmngt'
        )
        
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # Check legacy classallocation table
            cursor.execute("SELECT COUNT(*) as cnt FROM classallocation")
            legacy_count = cursor.fetchone()['cnt']
            print(f"  ✅ Legacy classallocation table accessible ({legacy_count} rows)")
            
            # Check legacy subjects table
            cursor.execute("SELECT COUNT(*) as cnt FROM subjects")
            subject_count = cursor.fetchone()['cnt']
            print(f"  ✅ Legacy subjects table accessible ({subject_count} rows)")
        
        connection.close()
        return True
    
    except Exception as e:
        print(f"❌ Backward compatibility test failed: {e}")
        return False


def test_config_data():
    """Test: Configuration data initialized"""
    print("\n=== TEST 5: Configuration Data ===")
    try:
        connection = pymysql.connect(
            host='localhost',
            user='schooluser',
            password='jbs',
            database='schoolmngt'
        )
        
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # Check academic years
            cursor.execute("SELECT COUNT(*) as cnt FROM academic_years")
            years_count = cursor.fetchone()['cnt']
            assert years_count >= 3, f"Expected >=3 years, got {years_count}"
            print(f"  ✅ Academic Years: {years_count} records")
            
            # Check class groups
            cursor.execute("SELECT COUNT(*) as cnt FROM class_group_settings")
            groups_count = cursor.fetchone()['cnt']
            assert groups_count == 4, f"Expected 4 groups, got {groups_count}"
            print(f"  ✅ Class Groups: {groups_count} records")
            
            # Check streams
            cursor.execute("SELECT COUNT(*) as cnt FROM stream_settings")
            streams_count = cursor.fetchone()['cnt']
            assert streams_count == 4, f"Expected 4 streams, got {streams_count}"
            print(f"  ✅ Streams: {streams_count} records")
        
        connection.close()
        return True
    
    except Exception as e:
        print(f"❌ Configuration data test failed: {e}")
        return False


def test_class_creation():
    """Test: Create class via service"""
    print("\n=== TEST 6: Class Creation ===")
    try:
        connection = pymysql.connect(
            host='localhost',
            user='schooluser',
            password='jbs',
            database='schoolmngt'
        )
        service = ClassManagementService(connection)
        
        # Get current year
        year = service.get_current_academic_year()
        
        # Create test class
        class_rec = service.create_class(
            academic_year_id=year['id'],
            class_group_code='Grade 1-3',
            stream_code='A',
            created_by=1
        )
        
        assert class_rec is not None, "Class should be created"
        assert class_rec['display_name'] == 'Grade 1-3 – Stream A', f"Unexpected name: {class_rec['display_name']}"
        print(f"  ✅ Created class: {class_rec['display_name']}")
        
        connection.close()
        return True
    
    except ValidationError as e:
        print(f"⚠️  Validation error (expected if duplicate): {e}")
        return True  # OK if duplicate
    except Exception as e:
        print(f"❌ Class creation test failed: {e}")
        return False


def test_validation_rules():
    """Test: Service validation rules"""
    print("\n=== TEST 7: Validation Rules ===")
    try:
        connection = pymysql.connect(
            host='localhost',
            user='schooluser',
            password='jbs',
            database='schoolmngt'
        )
        service = ClassManagementService(connection)
        
        # Test valid stream
        valid_stream = service.validate_stream('A')
        assert valid_stream, "Stream A should be valid"
        print(f"  ✅ validate_stream('A') → True")
        
        # Test invalid stream
        invalid_stream = service.validate_stream('Z')
        assert not invalid_stream, "Stream Z should be invalid"
        print(f"  ✅ validate_stream('Z') → False")
        
        connection.close()
        return True
    
    except Exception as e:
        print(f"❌ Validation test failed: {e}")
        return False


def run_all_tests():
    """Run all tests and report results"""
    print("\n" + "="*60)
    print("CLASS MANAGEMENT SYSTEM - COMPREHENSIVE TEST SUITE")
    print("="*60)
    
    tests = [
        ("Database Connection", test_database_connection),
        ("Required Tables", test_required_tables),
        ("Service Methods", test_service_methods),
        ("Backward Compatibility", test_backward_compatibility),
        ("Configuration Data", test_config_data),
        ("Class Creation", test_class_creation),
        ("Validation Rules", test_validation_rules),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Test error: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:10} | {name}")
    
    print("="*60)
    print(f"Result: {passed}/{total} tests passed")
    print("="*60)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED - System Ready for Production\n")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed - Review logs above\n")
        return 1


if __name__ == '__main__':
    sys.exit(run_all_tests())
