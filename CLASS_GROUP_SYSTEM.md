# Class Group Assignment System ✅

## Overview

Each class **MUST** belong to a class group. Class groups determine uniform pricing tiers.

## Class Groups

```
1. Playgroup-PP2       → Playgroup, PP1, PP2 students
2. Grade 1-3          → Grade 1, 2, 3 students  
3. Grade 4-6          → Grade 4, 5, 6 students
4. Grade 7-9          → Grade 7, 8, 9 students
```

## How It Works

### **Database Schema Update**
- `classes` table now includes `class_group` column
- All existing classes default to "Grade 1-3"
- Schema auto-migrates on next app startup

### **Admin Workflow**

1. **Manage Classes** (Admin Settings → Manage Classes)
   - Enter class name (e.g., "Grade 1A", "PP2")
   - Select class group from dropdown
   - Class is created with that group assignment

2. **Student Admission**
   - Admin admits student
   - Selects student's class (e.g., "Grade 1A")
   - System automatically knows it's in "Grade 1-3" group

3. **Uniform Issuance**
   - Staff issues uniform to student
   - System looks up student's class
   - Retrieves class group (e.g., "Grade 1-3")
   - Shows uniform prices for that group
   - Records ISSUANCE in stock ledger

### **Edit Classes**
- Click "Edit" on any class
- Can change class name AND class group
- Changes apply to all students in that class

### **Class Information Display**

| Field | Display | Purpose |
|-------|---------|---------|
| Class Name | "Grade 1A" | Identifies the actual class |
| Class Group | "Grade 1-3" (purple badge) | Determines uniform pricing |
| Students | "12" (blue badge) | Number of enrolled students |
| Class ID | "5" | Database identifier |

## Example Setup

```
Grade 1A   → Group: Grade 1-3  → 28 students
Grade 1B   → Group: Grade 1-3  → 25 students
Grade 2A   → Group: Grade 1-3  → 24 students
Grade 4A   → Group: Grade 4-6  → 22 students
Playgroup  → Group: Playgroup-PP2 → 30 students
```

All students in "Grade 1-3" group classes pay the same uniform prices, even though they're in different classes (1A, 1B, 2A).

## Database Changes

**Before:**
```sql
CREATE TABLE classes (
  classID INT PRIMARY KEY,
  class_name VARCHAR(50)
)
```

**After:**
```sql
CREATE TABLE classes (
  classID INT PRIMARY KEY AUTO_INCREMENT,
  class_name VARCHAR(50) NOT NULL,
  class_group VARCHAR(50) NOT NULL DEFAULT 'Grade 1-3'
)
```

## Updated Routes

- `GET /admin/manage_classes` - View all classes with groups
- `POST /admin/manage_classes` - Add new class with group
- `POST /admin/classes/<id>/edit` - Edit class name and group
- `POST /admin/classes/<id>/delete` - Delete class (if no students)

## Updated Templates

- `templates/manage_classes.html` - Class group selection in form and display in table

## Integration Points

✅ **Admin Settings** - Manage Classes card links here
✅ **Student Admission** - References classes (which have groups)
✅ **Uniform Issuance** - Uses class → group → prices lookup
✅ **Stock Ledger** - Records movements with student info
✅ **Reports** - Can filter by class or group

## Migration

If you have existing classes in the database:
1. The class_group column will be added with DEFAULT 'Grade 1-3'
2. Run: `ALTER TABLE classes ADD COLUMN class_group VARCHAR(50) NOT NULL DEFAULT 'Grade 1-3'`
3. Update class assignments as needed in Manage Classes UI

## Status

✅ Database schema updated
✅ Routes updated with class_group handling
✅ Template updated with class_group selection
✅ Info box explains class groups
✅ Edit modal includes class_group field
✅ Classes sorted by group and name

**Next Steps:**
1. Verify database migration runs successfully
2. Test adding classes with different groups
3. Verify student admission with class selection
4. Check uniform issuance uses correct group pricing
