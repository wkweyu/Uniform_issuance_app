# Quick Start Guide: Class Management System

**Purpose**: Get the new class management system up and running in 30 minutes

**Audience**: Developers implementing the system

---

## 5-Minute Overview

This system adds:
1. **Settings-driven class groups & streams** (no hardcoding)
2. **Academic year separation** (supports multi-year history)
3. **Class promotion engine** (atomic transactions with audit trail)
4. **3-level subject allocation** (class → student → teacher)

**Key Benefit**: Flexible, scalable, production-grade with full backward compatibility.

---

## Installation (15 minutes)

### Step 1: Backup Database (2 min)
```bash
cd /home/frappe-user/uniform\ issuance\ app
cp .env.example .env
# Edit `.env` and set DB_HOST, DB_USER, DB_PASSWORD, DB_NAME (do not commit `.env`).
echo "Edit .env now and then run the backup command below. You'll be prompted for the DB password."
mysqldump -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" > backup_$(date +%Y%m%d_%H%M%S).sql
echo "✓ Backup created"
```

### Step 2: Run Migration Script (5 min)
```bash
mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" < school_management_migration_v1.sql
echo "✓ Tables created"
```

### Step 3: Verify Migration (2 min)
```bash
mysql -u schooluser -p schoolmngt -e "
  SELECT 'academic_years' as table_name, COUNT(*) as count FROM academic_years
  UNION ALL
  SELECT 'class_group_settings', COUNT(*) FROM class_group_settings
  UNION ALL
  SELECT 'stream_settings', COUNT(*) FROM stream_settings;
"
```

You should see:
```
+------------------------+-------+
| table_name             | count |
+------------------------+-------+
| academic_years         |     3 |
| class_group_settings   |     4 |
| stream_settings        |     4 |
+------------------------+-------+
```

### Step 4: Copy Service Module (1 min)
```bash
# Already in project root; verify:
ls -la class_management_service.py
```

### Step 5: Update app.py (5 min)
Add these imports at the top:
```python
# Add after existing imports (line ~2)
from class_management_service import (
    ClassManagementService,
    ClassManagementException,
    ValidationError,
    PromotionError
)
```

---

## Testing (10 minutes)

### Test 1: Python Service (3 min)
```bash
cd /home/frappe-user/uniform\ issuance\ app
source venv/bin/activate
python3 << 'EOF'
import pymysql
from class_management_service import ClassManagementService

  import os
  conn = pymysql.connect(
    host=os.environ.get('DB_HOST', 'localhost'),
    user=os.environ.get('DB_USER'),
    password=os.environ.get('DB_PASSWORD'),
    database=os.environ.get('DB_NAME')
  )
    service = ClassManagementService(conn)
    
    # Test 1: Get current academic year
    ay = service.get_current_academic_year()
    print(f"✓ Current year: {ay['name']} (ID: {ay['id']})")
    
    # Test 2: Get allowed streams
    streams = service.get_allowed_streams()
    print(f"✓ Allowed streams: {[s['code'] for s in streams]}")
    
    # Test 3: Get class group by name
    group = service.get_class_group_by_name("Grade 5")
    print(f"✓ Grade 5 → {group}")
    
    # Test 4: Validate stream
    valid = service.validate_stream("A")
    print(f"✓ Stream A valid: {valid}")
    
    print("\n✅ All tests passed!")
    
except Exception as e:
    print(f"❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()
EOF
```

**Expected output**:
```
✓ Current year: 2025-2026 (ID: 1)
✓ Allowed streams: ['A', 'B', 'C', 'D']
✓ Grade 5 → Grade 4-6
✓ Stream A valid: True

✅ All tests passed!
```

### Test 2: Create Class (3 min)
```bash
python3 << 'EOF'
import pymysql
from class_management_service import ClassManagementService

conn = pymysql.connect(
  host=os.environ.get('DB_HOST', 'localhost'),
  user=os.environ.get('DB_USER'),
  password=os.environ.get('DB_PASSWORD'),
  database=os.environ.get('DB_NAME')
)
service = ClassManagementService(conn)

try:
    ay = service.get_current_academic_year()
    
    # Create a test class
    class_rec = service.create_class(
        academic_year_id=ay['id'],
        class_group_code='Grade 1-3',
        stream_code='A',
        created_by=1  # Admin user
    )
    
    print(f"✓ Class created: {class_rec['display_name']}")
    print(f"  - ID: {class_rec['classID']}")
    print(f"  - Stream: {class_rec['stream_code']}")
    print(f"  - Year: {ay['year']}")
    
except Exception as e:
    print(f"❌ Error: {str(e)}")
finally:
    conn.close()
EOF
```

**Expected output**:
```
✓ Class created: Grade 1 to Grade 3 – Stream A
  - ID: [ID]
  - Stream: A
  - Year: 2025
```

### Test 3: Backward Compatibility (2 min)
```bash
# Run queries against the DB specified in your `.env` (you will be prompted for the password):
mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" -e "SELECT COUNT(*) as legacy_classes FROM classallocation LIMIT 1; SELECT COUNT(*) as new_classes FROM class_allocation LIMIT 1;"
```

Both queries should work (or return 0 if tables are empty).

### Test 4: Flask App Still Runs (2 min)
```bash
cd /home/frappe-user/uniform\ issuance\ app
python3 app.py &
sleep 3
curl -s http://localhost:5000/login | head -20
kill %1  # Stop Flask
```

Should see HTML login page (no errors).

---

## Next Steps

### Immediate (Day 1)
1. ✅ Run database migration
2. ✅ Run all 4 tests above
3. ✅ Verify no errors in app.py logs
4. ✅ Test existing uniform issuance works

### Short-Term (Week 1)
1. Create Flask routes (see `FLASK_INTEGRATION_GUIDE.md`)
2. Create HTML templates
3. Test class creation via UI
4. Test student promotion via UI
5. User acceptance testing

### Medium-Term (Week 2-4)
1. Deploy to staging
2. Monitor for 48-72 hours
3. Train staff on new features
4. Deploy to production

---

## Troubleshooting

### Problem: "Access denied for user 'schooluser'@'localhost'"
**Solution**: Ensure MySQL is running and credentials are correct.
```bash
mysql -u schooluser -p
# Should prompt for password (jbs)
```

### Problem: "Table 'schoolmngt.academic_years' doesn't exist"
**Solution**: Re-run migration script.
```bash
mysql -u schooluser -p schoolmngt < school_management_migration_v1.sql
```

### Problem: "Foreign key constraint fails"
**Solution**: Ensure tables created in correct order (migration script handles this).
```bash
mysql -u schooluser -p schoolmngt -e "SHOW TABLES;" | grep academic
```

### Problem: "No module named 'class_management_service'"
**Solution**: Ensure file is in correct directory.
```bash
ls -la class_management_service.py
# Should be in /home/frappe-user/uniform\ issuance\ app/
```

### Problem: "ValidationError: Academic year ID X not found"
**Solution**: Academic year doesn't exist. Create it first.
```python
service.create_academic_year(2026, "2026-01-01", "2026-12-31")
```

---

## Quick Commands Reference

### Verify Migration
```bash
mysql -u schooluser -p schoolmngt -e "
  SELECT 'Migration Status' AS Check, 
         CASE WHEN COUNT(*) > 0 THEN '✓ OK' ELSE '✗ FAIL' END AS Status
  FROM academic_years
  UNION ALL
  SELECT 'Class Groups', 
         CASE WHEN COUNT(*) = 4 THEN '✓ OK' ELSE '✗ FAIL' END
  FROM class_group_settings
  UNION ALL
  SELECT 'Streams', 
         CASE WHEN COUNT(*) >= 2 THEN '✓ OK' ELSE '✗ FAIL' END
  FROM stream_settings;
"
```

### View Current Academic Year
```bash
mysql -u schooluser -p schoolmngt -e "
  SELECT * FROM academic_years WHERE is_current = TRUE;
"
```

### List All Classes with Students
```bash
mysql -u schooluser -p schoolmngt -e "
  SELECT c.display_name, c.stream_code, COUNT(ca.id) as students
  FROM classes c
  LEFT JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE
  WHERE c.is_active = TRUE
  GROUP BY c.classID
  ORDER BY c.display_name;
"
```

### Check Promotion Audit Log
```bash
mysql -u schooluser -p schoolmngt -e "
  SELECT batch_id, old_class_id, new_class_id, student_count, promotion_date
  FROM class_promotion_log
  ORDER BY promotion_date DESC
  LIMIT 5;
"
```

---

## Architecture Quick Ref

```
┌─────────────────────────────────────────┐
│         Flask App (app.py)              │
├─────────────────────────────────────────┤
│  ClassManagementService (Python)        │
│  - Validates input                      │
│  - Handles transactions                 │
│  - Logs to audit trail                  │
├─────────────────────────────────────────┤
│         MySQL Database                  │
├─────────────────────────────────────────┤
│ academic_years (master)                 │
│ class_group_settings (config)           │
│ stream_settings (config)                │
│ classes (entities)                      │
│ class_allocation (history)              │
│ subjects, class_subjects (catalog)      │
│ student_subjects (enrollments)          │
│ teacher_allocations (assignments)       │
│ class_promotion_log (audit)             │
└─────────────────────────────────────────┘
```

---

## Critical Files

| File | Purpose | When to Use |
|------|---------|------------|
| `school_management_migration_v1.sql` | Database setup | First, once |
| `class_management_service.py` | Business logic | Always imported in Flask |
| `SCHEMA_DESIGN.md` | Understanding schema | Reference for questions |
| `FLASK_INTEGRATION_GUIDE.md` | Route patterns | Implementing new routes |
| `IMPLEMENTATION_ROADMAP.md` | Full checklist | Project management |
| `.github/copilot-instructions.md` | AI guidance | AI coding assistance |

---

## Success Criteria

✅ **You're ready for production when**:

1. ✓ All 4 tests pass
2. ✓ Existing uniform issuance still works
3. ✓ Existing fleet system still works
4. ✓ Database migration verified
5. ✓ Flask routes added and tested
6. ✓ Templates created and styled
7. ✓ Promotion audit log working
8. ✓ Subject validation working
9. ✓ No errors in Flask logs for 24+ hours
10. ✓ User acceptance testing passed

---

## Getting Help

### For Database Issues
→ See `SCHEMA_DESIGN.md` section "Validation Rules"

### For Integration Issues
→ See `FLASK_INTEGRATION_GUIDE.md` section "Troubleshooting"

### For Implementation Questions
→ See `IMPLEMENTATION_ROADMAP.md` section "Testing Checklist"

### For Usage Questions
→ See `class_management_service.py` docstrings and examples

---

**Total Setup Time**: 30 minutes ⏱️

**Confidence Level**: High ✅

**Ready to begin**: YES 🚀

---

Need help? Review the linked documentation files or search for specific keywords in the codebase.
