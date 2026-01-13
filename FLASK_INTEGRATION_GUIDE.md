# Flask Routes Integration Guide: Class Management System

## Overview

This guide shows how to integrate the `class_management_service.py` module into your existing Flask `app.py` with minimal disruption to uniform issuance and fleet management features.

---

## Integration Pattern

### 1. Import the Service

Add to top of `app.py`:

```python
from class_management_service import (
    ClassManagementService,
    ClassManagementException,
    ValidationError,
    PromotionError
)
```

---

### 2. Instantiate Service in Routes

```python
@app.route('/admin/classes/create', methods=['GET', 'POST'])
@admin_required
def create_class_route():
    """Create a new class with automatic group assignment."""
    connection = get_db_connection()
    service = ClassManagementService(connection)
    
    if request.method == 'GET':
        # Show form with:
        # - Academic year dropdown
        # - Stream dropdown (from settings)
        # - Class group dropdown
        ay = service.get_current_academic_year()
        streams = service.get_allowed_streams()
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT code, name FROM class_group_settings 
                ORDER BY display_order
            """)
            class_groups = cursor.fetchall()
        
        return render_template(
            'create_class.html',
            current_year=ay,
            streams=streams,
            class_groups=class_groups
        )
    
    elif request.method == 'POST':
        try:
            academic_year_id = request.form.get('academic_year_id')
            class_group_code = request.form.get('class_group_code')
            stream_code = request.form.get('stream_code')
            
            class_rec = service.create_class(
                academic_year_id=int(academic_year_id),
                class_group_code=class_group_code,
                stream_code=stream_code,
                created_by=session.get('userNo')
            )
            
            flash(f"✓ Class '{class_rec['display_name']}' created successfully.", "success")
            return redirect(url_for('manage_classes'))
            
        except ValidationError as e:
            flash(f"Validation Error: {str(e)}", "error")
        except ClassManagementException as e:
            flash(f"Error: {str(e)}", "error")
        finally:
            connection.close()
    
    return render_template('create_class.html')
```

---

### 3. Class Promotion Route

```python
@app.route('/admin/classes/promote', methods=['GET', 'POST'])
@admin_required
def promote_students_route():
    """Promote students from one class to another."""
    connection = get_db_connection()
    service = ClassManagementService(connection)
    
    if request.method == 'GET':
        # Get all classes grouped by year
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT c.classID, c.display_name, ay.year
                FROM classes c
                JOIN academic_years ay ON c.academic_year_id = ay.id
                WHERE c.is_active = TRUE
                ORDER BY ay.year DESC, c.display_name
            """)
            classes = cursor.fetchall()
        
        return render_template('promote_students.html', classes=classes)
    
    elif request.method == 'POST':
        try:
            old_class_id = request.form.get('old_class_id')
            new_class_id = request.form.get('new_class_id')
            notes = request.form.get('notes', '')
            
            result = service.promote_students(
                old_class_id=int(old_class_id),
                new_class_id=int(new_class_id),
                promoted_by=session.get('userNo'),
                notes=notes
            )
            
            if result['success']:
                flash(result['message'], "success")
                # Log promotion batch ID for audit
                app.logger.info(f"Promotion batch: {result['batch_id']}")
            
            return redirect(url_for('manage_classes'))
            
        except PromotionError as e:
            flash(f"Promotion Error: {str(e)}", "error")
        except ClassManagementException as e:
            flash(f"Error: {str(e)}", "error")
        finally:
            connection.close()
    
    return render_template('promote_students.html')
```

---

### 4. Subject Allocation Route

```python
@app.route('/admin/class/<int:class_id>/subjects', methods=['GET', 'POST'])
@admin_required
def manage_class_subjects(class_id):
    """Allocate subjects to a class."""
    connection = get_db_connection()
    service = ClassManagementService(connection)
    
    if request.method == 'GET':
        # Get current class-subject mappings
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT cs.id, s.id as subject_id, s.code, s.name, cs.is_compulsory
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.id
                WHERE cs.class_id = %s AND cs.is_active = TRUE
            """, (class_id,))
            current_subjects = cursor.fetchall()
            
            # Get all available subjects
            cursor.execute("""
                SELECT id, code, name FROM subjects 
                WHERE is_active = TRUE
                ORDER BY name
            """)
            all_subjects = cursor.fetchall()
        
        class_info = service.cursor.execute("""
            SELECT display_name FROM classes WHERE classID = %s
        """, (class_id,))
        class_name = service.cursor.fetchone()['display_name']
        
        return render_template(
            'manage_class_subjects.html',
            class_id=class_id,
            class_name=class_name,
            current_subjects=current_subjects,
            all_subjects=all_subjects
        )
    
    elif request.method == 'POST':
        try:
            subject_ids = [int(x) for x in request.form.getlist('subject_ids')]
            
            service.allocate_subjects_to_class(
                class_id=class_id,
                subject_ids=subject_ids,
                compulsory=True
            )
            
            flash("✓ Subjects allocated to class successfully.", "success")
            return redirect(url_for('manage_classes'))
            
        except ValidationError as e:
            flash(f"Error: {str(e)}", "error")
        finally:
            connection.close()
    
    return render_template('manage_class_subjects.html')
```

---

### 5. Teacher Allocation Route

```python
@app.route('/admin/teacher/allocate', methods=['GET', 'POST'])
@admin_required
def allocate_teacher():
    """Allocate teacher to class-subject."""
    connection = get_db_connection()
    service = ClassManagementService(connection)
    ay = service.get_current_academic_year()
    
    if request.method == 'GET':
        # Get teachers, classes, subjects
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT userNo, username FROM users 
                WHERE access_flag = 1 AND TA = 0
                ORDER BY username
            """)
            teachers = cursor.fetchall()
            
            cursor.execute("""
                SELECT classID, display_name FROM classes 
                WHERE academic_year_id = %s AND is_active = TRUE
                ORDER BY display_name
            """, (ay['id'],))
            classes = cursor.fetchall()
            
            cursor.execute("""
                SELECT id, code, name FROM subjects 
                WHERE is_active = TRUE
                ORDER BY name
            """)
            subjects = cursor.fetchall()
        
        return render_template(
            'allocate_teacher.html',
            teachers=teachers,
            classes=classes,
            subjects=subjects,
            year=ay
        )
    
    elif request.method == 'POST':
        try:
            teacher_id = request.form.get('teacher_id')
            class_id = request.form.get('class_id')
            subject_id = request.form.get('subject_id')
            
            service.allocate_teacher_to_class_subject(
                teacher_id=int(teacher_id),
                class_id=int(class_id),
                subject_id=int(subject_id),
                academic_year_id=ay['id']
            )
            
            flash("✓ Teacher allocated successfully.", "success")
            return redirect(url_for('manage_classes'))
            
        except ValidationError as e:
            flash(f"Error: {str(e)}", "error")
        finally:
            connection.close()
    
    return render_template('allocate_teacher.html')
```

---

### 6. Student Subject Enrollment

```python
@app.route('/admin/student/<int:admno>/subjects', methods=['GET', 'POST'])
@admin_required
def manage_student_subjects(admno):
    """Manage subjects for a specific student."""
    connection = get_db_connection()
    service = ClassManagementService(connection)
    
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT ca.id, c.display_name, c.classID
            FROM class_allocation ca
            JOIN classes c ON ca.class_id = c.classID
            WHERE ca.student_id = %s AND ca.is_current = TRUE
        """, (admno,))
        allocation = cursor.fetchone()
    
    if not allocation:
        flash("Student not currently allocated to any class.", "error")
        return redirect(url_for('students_list'))
    
    if request.method == 'GET':
        # Get class-allocated subjects
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT s.id, s.code, s.name, cs.is_compulsory
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.id
                WHERE cs.class_id = %s AND cs.is_active = TRUE
                ORDER BY s.name
            """, (allocation['classID'],))
            available_subjects = cursor.fetchall()
            
            # Get student's current enrollments
            cursor.execute("""
                SELECT subject_id FROM student_subjects
                WHERE class_allocation_id = %s AND is_active = TRUE
            """, (allocation['id'],))
            enrolled = {row['subject_id'] for row in cursor.fetchall()}
        
        return render_template(
            'manage_student_subjects.html',
            admno=admno,
            allocation_id=allocation['id'],
            class_name=allocation['display_name'],
            available_subjects=available_subjects,
            enrolled=enrolled
        )
    
    elif request.method == 'POST':
        try:
            subject_ids = [int(x) for x in request.form.getlist('subject_ids')]
            
            service.enroll_student_in_subjects(
                class_allocation_id=allocation['id'],
                subject_ids=subject_ids
            )
            
            flash("✓ Student subject enrollment updated.", "success")
            return redirect(url_for('students_list'))
            
        except ValidationError as e:
            flash(f"Error: {str(e)}", "error")
        finally:
            connection.close()
    
    return render_template('manage_student_subjects.html')
```

---

## Backward Compatibility

### Existing Uniform Issuance Routes

Your existing routes like `/issue_uniform` will continue to work because:

1. **Legacy `classallocation` table** still exists
2. **View `v_classallocation_legacy`** provides backward compatibility
3. **`get_class_group()` function** still works with `class_group_code`

Example (no changes needed):

```python
@app.route('/issue_uniform', methods=['GET', 'POST'])
@login_required
def issue_uniform():
    # Your existing code still works
    # The new system coexists with the old one
    
    cursor.execute("""
        SELECT s.FName, c.class_name 
        FROM studentinfo s 
        JOIN classallocation ca ON s.AdmNo = ca.AdmNo 
        JOIN classes c ON ca.classID = c.classID 
        WHERE s.AdmNo = %s
    """, (admno, year))
    
    # This still works because the old tables exist
```

---

## Migration Checklist

- [ ] Backup existing database
- [ ] Run `school_management_migration_v1.sql`
- [ ] Copy `class_management_service.py` to project root
- [ ] Add service import to `app.py`
- [ ] Add new routes to `app.py`
- [ ] Create new templates (see next section)
- [ ] Test existing uniform/fleet features
- [ ] Test new class management features
- [ ] Deploy with rollback plan

---

## Template Requirements (Placeholder)

You'll need these new templates in `templates/`:

1. **create_class.html** - Form to create new class with stream selection
2. **promote_students.html** - Class promotion UI with confirmation
3. **manage_class_subjects.html** - Allocate subjects to class
4. **allocate_teacher.html** - Teacher-class-subject assignment
5. **manage_student_subjects.html** - Student subject enrollment

Each should follow your existing design (Tailwind CSS, base.html inheritance, flash messages).

---

## Reporting Queries (Direct Access)

For your reports dashboard, use these direct queries:

```python
# Classes per year
cursor.execute("""
    SELECT c.display_name, COUNT(ca.id) as student_count
    FROM classes c
    LEFT JOIN class_allocation ca ON c.classID = ca.class_id AND ca.is_current = TRUE
    WHERE c.academic_year_id = %s
    GROUP BY c.classID
    ORDER BY c.display_name
""", (academic_year_id,))

# Student promotion history
cursor.execute("""
    SELECT ca.*, c.display_name, ay.year
    FROM class_allocation ca
    JOIN classes c ON ca.class_id = c.classID
    JOIN academic_years ay ON ca.academic_year_id = ay.id
    WHERE ca.student_id = %s
    ORDER BY ay.year DESC
""", (admno,))

# Teachers per subject per class
cursor.execute("""
    SELECT u.username, c.display_name, s.name
    FROM teacher_allocations ta
    JOIN users u ON ta.teacher_id = u.userNo
    JOIN classes c ON ta.class_id = c.classID
    JOIN subjects s ON ta.subject_id = s.id
    WHERE ta.academic_year_id = %s AND ta.is_active = TRUE
""", (academic_year_id,))
```

---

## Troubleshooting

### Foreign Key Constraint Errors

**Problem**: Cannot delete class because it has allocations.
**Solution**: The constraint is intentional. Soft-delete (set `is_active = FALSE`) or reassign students first.

### Subject Validation Errors

**Problem**: "Subject not allocated to this class."
**Solution**: Run `allocate_subjects_to_class()` before enrolling students.

### Promotion Fails

**Problem**: Cannot promote from year 2025 to 2027 (skip year).
**Solution**: Years must be consecutive. Create intermediate year class or adjust dates.

---

## Performance Notes

- **Index Strategy**: All foreign keys indexed; query plans optimized
- **Bulk Promotion**: Uses batch IDs for transactional integrity
- **View Queries**: Legacy views preserve O(n) performance on uniform/fleet features
- **Audit Trail**: Promotion log grows linearly; archive after 2+ years

---

## Next Steps

1. Review this integration guide with your team
2. Execute migration script on test database
3. Implement new routes following patterns above
4. Create required templates
5. Run integration tests
6. Deploy to staging for 48-72 hours validation
7. Go live with rollback procedure ready
