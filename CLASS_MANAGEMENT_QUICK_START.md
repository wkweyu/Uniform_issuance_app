# Class Management System — Quick Start Guide

## ✅ All Features Complete & Ready to Use

### Three Core Workflows

#### 1️⃣ **Allocate Subjects to Class**
**URL**: Admin → Classes → Manage Class Subjects

- Select class
- Check subjects you want that class to offer
- Submit
- Result: Subjects available for student enrollment

#### 2️⃣ **Allocate Teacher to Subject** ⭐ NEW DROPDOWN
**URL**: Admin → Classes → Allocate Teacher

**Changes in this session**:
- ✅ Teacher field is now a **dropdown** (not text input)
- ✅ Shows teacher username + staff ID
- ✅ Only active users shown
- ✅ Easy to find the right teacher

**Steps**:
1. Select academic year, class, and (optionally) subject
2. **Pick teacher from dropdown** ← Much better!
3. Optionally check "Assign as Class Teacher"
4. Submit
5. Result: Teacher can teach that subject (or entire class)

#### 3️⃣ **Enroll Student in Subjects**
**URL**: Admin → Classes → Student Enrollment

- Select student
- See their current class and available subjects
- Check which subjects they take
- Submit
- Result: Student enrolled (can only take subjects offered by class)

---

## 🚀 Quick Test (2 mins)

### Prerequisites
- At least 1 academic year (e.g., 2025)
- 1 class created (e.g., Grade 1 – Stream A)
- 2-3 subjects in system (e.g., English, Math)
- 2-3 teacher users created (Admin → Users → Create)

### Test Script
```
1. Go to Admin → Classes
   ✓ See dashboard with stats

2. Manage Class Subjects
   → Select "Grade 1 – Stream A"
   → Check English, Math
   → Submit
   ✓ "✅ Subjects allocated to class"

3. Allocate Teacher
   → Year: 2025
   → Class: Grade 1 – Stream A
   → Teacher: [Dropdown—should show your teachers!] ← NEW!
   → Subject: English
   → Submit
   ✓ "✅ Teacher allocated to subject"

4. Student Enrollment (if students exist)
   → Select a student
   → Check Math
   → Submit
   ✓ "✅ Student enrolled in subjects"
```

---

## 📚 What Was Implemented

### Routes
| Route | Method | Purpose | Status |
|-------|--------|---------|--------|
| `/admin/manage_classes` | GET | Dashboard | ✅ Complete |
| `/admin/class/<id>/subjects` | GET/POST | Allocate subjects | ✅ Complete |
| `/admin/teacher/allocate` | GET/POST | Allocate teacher | ✅ Updated w/ dropdown |
| `/admin/get-teachers` | GET | Teachers API | ✅ NEW |
| `/admin/student/<id>/subjects` | GET/POST | Enroll student | ✅ Complete |

### Templates
| Template | Change | Status |
|----------|--------|--------|
| `allocate_teacher.html` | Text input → Dropdown | ✅ Updated |
| `manage_class_subjects.html` | No change needed | ✅ Complete |
| `enroll_student_subjects.html` | No change needed | ✅ Complete |

### Backend
- All 3 route POST handlers complete
- GET endpoints provide form data
- Error handling with rollback
- Graceful fallback for missing `class_teachers` table

---

## ⚠️ Before You Start

### Check These Prerequisites

1. **Database tables exist**:
   ```bash
   # In MySQL
   SHOW TABLES LIKE '%subject%';  # Should show: class_subjects, student_subjects, subjects
   SHOW TABLES LIKE '%teacher%';  # Should show: teacher_allocations (class_teachers optional)
   SHOW TABLES LIKE '%allocation%'; # Should show: class_allocation
   ```

2. **At least one teacher user exists**:
   ```bash
   # In MySQL
   SELECT COUNT(*) FROM users WHERE access_flag = 1;  # Should be > 0
   ```

3. **Academic years are set up**:
   ```bash
   # In MySQL
   SELECT COUNT(*) FROM academic_years;  # Should be > 0
   ```

4. **Subjects exist**:
   ```bash
   # In MySQL
   SELECT COUNT(*) FROM subjects WHERE is_active = 1;  # Should be > 0
   ```

### If Any Missing
- **No tables?** Run migration:
  ```bash
  cd /home/frappe-user/uniform\ issuance\ app
  mysql -u schooluser -p schoolmngt < school_management_migration_v1.sql
  ```
  
- **No teachers?** Admin → Users → Create User
  
- **No academic years?** Admin → Classes → (will suggest adding)
  
- **No subjects?** Need to add to database:
  ```sql
  INSERT INTO subjects (code, name, is_active) VALUES
  ('ENG', 'English Language', TRUE),
  ('MATH', 'Mathematics', TRUE),
  ('SCI', 'Science', TRUE);
  ```

---

## 🎯 Common Issues & Fixes

### "Error allocating teacher: Unknown column 'id' in 'SELECT'"
**Fix applied**: Updated `ClassManagementService` to use `SELECT 1` instead of `SELECT id`
- Restart app: `python3 app.py`
- Run migration if needed

### "No teachers showing in dropdown"
**Check**:
- Are users created? Admin → Users
- Are users **active**? (access_flag = 1)
- SQL: `SELECT * FROM users WHERE access_flag = 1;`

### "Subject must be allocated to this class"
**Expected behavior** when:
- Trying to assign teacher to subject that class doesn't offer
- Fix: Go to Manage Class Subjects first, add that subject

### Missing `class_teachers` table
**Expected** — system gracefully falls back to `teacher_allocations`
- Optional enhancement: Run migration to add `class_teachers`

---

## 📊 Database Schema (Key Tables)

```
classes
├── classID, class_name, display_name
├── academic_year_id → academic_years
├── class_group_code → class_group_settings
└── stream_code → stream_settings

class_subjects (Class → Subject)
├── class_id → classes
├── subject_id → subjects
└── is_compulsory

teacher_allocations (Teacher → Class → Subject)
├── teacher_id → users.userNo
├── class_id → classes
├── subject_id → subjects
├── academic_year_id → academic_years
└── UNIQUE(class_id, subject_id, academic_year_id)

class_allocation (Student → Class)
├── student_id → students
├── class_id → classes
├── academic_year_id → academic_years
└── is_current

student_subjects (Student → Subject)
├── class_allocation_id → class_allocation
└── subject_id → subjects
```

---

## 🔧 Support

### Debug Endpoints

**Check data availability**:
```
GET /admin/teacher/allocate-debug
```
Returns: academic_years, classes, subjects status

**Fetch teachers via API**:
```
GET /admin/get-teachers
```
Returns: `{ "success": true, "teachers": [...] }`

### Logs
- Check app console for errors during allocation
- Look for: `Allocate teacher error:`, `Manage class subjects error:`

---

## 🎓 Next Steps

After testing:
- [ ] Run end-to-end test with real data
- [ ] Test error scenarios (invalid class, missing subject)
- [ ] Create reports for teacher workload
- [ ] Bulk upload students to classes
- [ ] Add subject/teacher editing + deletion

---

**Last Updated**: January 15, 2026  
**Version**: 1.0 Complete  
**Status**: ✅ Ready for Production Testing
