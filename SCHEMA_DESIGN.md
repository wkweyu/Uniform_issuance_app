# Production-Grade Class Management Schema Design

## Executive Summary

This document defines the normalized relational schema for implementing class groups, streams, promotion, and subject allocation while maintaining backward compatibility with existing uniform issuance and fleet management systems.

---

## Data Model Architecture

### 1. Configuration Tables (Settings-Driven)

#### `academic_years` (NEW)
```sql
id              INT PRIMARY KEY AUTO_INCREMENT
year            INT UNIQUE NOT NULL                   -- e.g., 2025, 2026
name            VARCHAR(50) NOT NULL                  -- e.g., "2025-2026"
start_date      DATE NOT NULL
end_date        DATE NOT NULL
is_current      BOOLEAN DEFAULT FALSE
created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```
**Purpose**: Define academic years; prevents hard-coding; supports multi-year history.

---

#### `class_group_settings` (NEW)
```sql
id              INT PRIMARY KEY AUTO_INCREMENT
code            VARCHAR(20) UNIQUE NOT NULL           -- e.g., "Playgroup-PP2", "Grade 1-3"
name            VARCHAR(100) NOT NULL
min_grade       VARCHAR(50)                           -- e.g., "Playgroup"
max_grade       VARCHAR(50)                           -- e.g., "Pre-Primary 2"
display_order   INT DEFAULT 0
created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```
**Purpose**: Centralized class group configuration; no hard-coded mappings.

---

#### `stream_settings` (NEW)
```sql
id              INT PRIMARY KEY AUTO_INCREMENT
school_id       INT                                   -- For multi-school support
code            VARCHAR(10) UNIQUE NOT NULL           -- e.g., "A", "B", "C", "D"
name            VARCHAR(100) NOT NULL                 -- e.g., "Stream A"
is_active       BOOLEAN DEFAULT TRUE
created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
UNIQUE KEY unique_stream (school_id, code)
```
**Purpose**: School-specific stream configuration; enforces allowlist at DB level.

---

### 2. Master Data Tables (Transactional)

#### `classes` (MODIFIED)
**Old Structure**: `classID`, `class_name`, `class_group`
**New Structure**:
```sql
id                  INT PRIMARY KEY AUTO_INCREMENT
academic_year_id    INT NOT NULL                      -- FK → academic_years(id)
class_group_code    VARCHAR(20) NOT NULL              -- FK → class_group_settings(code)
stream_code         VARCHAR(10) NOT NULL              -- FK → stream_settings(code)
display_name        VARCHAR(100) NOT NULL             -- e.g., "Grade 1 – Stream A"
is_active           BOOLEAN DEFAULT TRUE
created_by          INT
created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP

UNIQUE KEY unique_class (academic_year_id, class_group_code, stream_code)
FOREIGN KEY (academic_year_id) REFERENCES academic_years(id)
FOREIGN KEY (class_group_code) REFERENCES class_group_settings(code)
FOREIGN KEY (stream_code) REFERENCES stream_settings(code)
```
**Key Changes**:
- Tied to academic year (no duplicates across years)
- Stream is required and validated
- Class group is derived from class_group_settings
- Auto-generated display_name for consistency

---

#### `class_allocation` (REPLACEMENT for `classallocation`)
```sql
id                  INT PRIMARY KEY AUTO_INCREMENT
student_id          INT NOT NULL                      -- FK → studentinfo(id)
class_id            INT NOT NULL                      -- FK → classes(id)
academic_year_id    INT NOT NULL                      -- FK → academic_years(id)
allocation_date     DATE NOT NULL
promoted_from_id    INT                               -- FK → class_allocation(id) for history
is_current          BOOLEAN DEFAULT TRUE              -- Only one per student per year
created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP

UNIQUE KEY unique_student_year (student_id, academic_year_id)
FOREIGN KEY (student_id) REFERENCES studentinfo(id)
FOREIGN KEY (class_id) REFERENCES classes(id)
FOREIGN KEY (academic_year_id) REFERENCES academic_years(id)
FOREIGN KEY (promoted_from_id) REFERENCES class_allocation(id)
```
**Key Changes**:
- Links to academic year (not just class)
- `promoted_from_id` tracks promotion history
- `is_current` flag simplifies queries
- Enforces one allocation per student per year

---

### 3. Subjects & Teacher Allocation

#### `subjects` (NEW)
```sql
id                  INT PRIMARY KEY AUTO_INCREMENT
code                VARCHAR(50) UNIQUE NOT NULL       -- e.g., "ENG", "MATH", "SCI"
name                VARCHAR(100) NOT NULL             -- e.g., "English Language"
description         TEXT
is_active           BOOLEAN DEFAULT TRUE
created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```
**Purpose**: Master list of subjects; school-wide catalog.

---

#### `class_subjects` (NEW)
```sql
id                  INT PRIMARY KEY AUTO_INCREMENT
class_id            INT NOT NULL                      -- FK → classes(id)
subject_id          INT NOT NULL                      -- FK → subjects(id)
is_compulsory       BOOLEAN DEFAULT TRUE
is_active           BOOLEAN DEFAULT TRUE
created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP

UNIQUE KEY unique_class_subject (class_id, subject_id)
FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE
FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE RESTRICT
```
**Purpose**: Maps subjects to a class; enforces class-level subject constraints.

---

#### `student_subjects` (NEW)
```sql
id                  INT PRIMARY KEY AUTO_INCREMENT
class_allocation_id INT NOT NULL                      -- FK → class_allocation(id)
subject_id          INT NOT NULL                      -- FK → subjects(id)
enrollment_date     DATE NOT NULL
is_active           BOOLEAN DEFAULT TRUE
created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP

UNIQUE KEY unique_student_subject (class_allocation_id, subject_id)
FOREIGN KEY (class_allocation_id) REFERENCES class_allocation(id) ON DELETE CASCADE
FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE RESTRICT
```
**Purpose**: Flexible student-level subject selection; must be subset of class subjects.

---

#### `teacher_allocations` (NEW)
```sql
id                  INT PRIMARY KEY AUTO_INCREMENT
teacher_id          INT NOT NULL                      -- FK → users(id) or staff table
class_id            INT NOT NULL                      -- FK → classes(id)
subject_id          INT NOT NULL                      -- FK → subjects(id)
academic_year_id    INT NOT NULL                      -- FK → academic_years(id)
is_active           BOOLEAN DEFAULT TRUE
created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP

UNIQUE KEY unique_teacher_class_subject (class_id, subject_id, academic_year_id)
FOREIGN KEY (teacher_id) REFERENCES users(userNo)
FOREIGN KEY (class_id) REFERENCES classes(id)
FOREIGN KEY (subject_id) REFERENCES subjects(id)
FOREIGN KEY (academic_year_id) REFERENCES academic_years(id)
```
**Purpose**: Maps teachers to class-subject combinations; enforces one teacher per combo.

---

### 4. Audit & History

#### `class_promotion_log` (NEW)
```sql
id                  INT PRIMARY KEY AUTO_INCREMENT
batch_id            VARCHAR(50) NOT NULL              -- Transaction batch identifier
old_class_id        INT NOT NULL                      -- FK → classes(id)
new_class_id        INT NOT NULL                      -- FK → classes(id)
student_count       INT DEFAULT 0
promotion_date      DATE NOT NULL
promoted_by         INT                               -- FK → users(userNo)
notes               TEXT
created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP

FOREIGN KEY (old_class_id) REFERENCES classes(id)
FOREIGN KEY (new_class_id) REFERENCES classes(id)
FOREIGN KEY (promoted_by) REFERENCES users(userNo)
```
**Purpose**: Audit trail for promotion batches; enables rollback and reporting.

---

## Backward Compatibility Strategy

### Existing Tables to PRESERVE
- `uniform_receipts` — denormalized for legacy uniform system
- `buses`, `fuel_vouchers`, `service_records` — fleet management
- `studentinfo` — core student data
- `uniform_prices` — uniform pricing (references class_group_code via FK)

### Migration Approach
1. **Phase 1**: Create new tables (no data migration yet)
2. **Phase 2**: Populate `academic_years`, `class_group_settings`, `stream_settings`
3. **Phase 3**: Copy existing classes → new schema with default 2025 academic year
4. **Phase 4**: Update `classallocation` → `class_allocation` with history
5. **Phase 5**: Update app.py routes to query both schemas (dual-write, read-new)
6. **Phase 6**: Archive old tables after validation period

### Dual-Read Strategy (During Transition)
```python
def get_class_for_student(admno, year):
    """Query both old and new schema; prefer new."""
    try:
        # Try new schema first
        return query_class_allocation_new(admno, year)
    except:
        # Fall back to old schema
        return query_classallocation_old(admno, year)
```

---

## Data Integrity Constraints

### At Database Level
1. **Foreign key constraints** enforce referential integrity
2. **Unique keys** prevent duplicates (e.g., class per year/stream, one teacher per class-subject)
3. **Check constraints** (MySQL 8.0+) validate data ranges

### At Application Level
1. **Validation before insert**: Verify subject is in class_subjects
2. **Promotion safeguards**: Check destination class exists before promoting
3. **Audit logging**: Log all mutations to class_promotion_log

---

## Reporting Queries (Examples)

### Class List by Academic Year
```sql
SELECT c.id, c.display_name, cgs.name AS class_group, ss.code AS stream, ay.name AS year
FROM classes c
JOIN academic_years ay ON c.academic_year_id = ay.id
JOIN class_group_settings cgs ON c.class_group_code = cgs.code
JOIN stream_settings ss ON c.stream_code = ss.code
WHERE ay.year = 2025 AND c.is_active = TRUE
ORDER BY cgs.display_order, c.display_name;
```

### Students per Class (Current Year)
```sql
SELECT ca.student_id, si.FName, si.SName, c.display_name
FROM class_allocation ca
JOIN studentinfo si ON ca.student_id = si.id
JOIN classes c ON ca.class_id = c.id
JOIN academic_years ay ON ca.academic_year_id = ay.id
WHERE ay.is_current = TRUE AND ca.is_current = TRUE;
```

### Subjects per Student
```sql
SELECT ss.student_id, s.code, s.name
FROM student_subjects ss
JOIN subjects s ON ss.subject_id = s.id
WHERE ss.class_allocation_id IN (
    SELECT id FROM class_allocation WHERE student_id = ? AND academic_year_id = ?
);
```

### Teachers per Class-Subject
```sql
SELECT c.display_name, s.name, u.username
FROM teacher_allocations ta
JOIN classes c ON ta.class_id = c.id
JOIN subjects s ON ta.subject_id = s.id
JOIN users u ON ta.teacher_id = u.userNo
WHERE c.academic_year_id = ? AND ta.is_active = TRUE;
```

---

## Advantages

1. **Data Integrity**: No data duplication; enforced constraints
2. **Scalability**: Supports unlimited academic years and promotion cycles
3. **Auditability**: Full history via promotion_log and timestamp tracking
4. **Multi-Tenancy Ready**: school_id column for future expansion
5. **Settings-Driven**: No hard-coded class groups or streams
6. **Backward Compatible**: Existing uniform and fleet systems unaffected
7. **Performance**: Proper indexing on foreign keys and frequently queried fields

---

## Implementation Timeline

| Phase | Duration | Tasks |
|-------|----------|-------|
| Design | ✓ Completed | Schema + relationships |
| Database | 1-2 hours | Create tables, indexes, FK constraints |
| Migration | 2-3 hours | Populate new tables from legacy data |
| Business Logic | 4-6 hours | Python models, validators, promotion engine |
| UI Integration | 6-8 hours | Admin routes, class management, promotion UI |
| Testing | 2-3 hours | Unit tests, integration tests, data validation |
| Deployment | 1 hour | Backups, execute migration, verify |

**Total**: ~18-25 hours of development

---

## Next Steps

1. Review schema and get approval
2. Execute database migration script
3. Implement business logic (Python models)
4. Update app.py routes
5. Create admin UI for settings and promotion
6. Run integration tests
7. Deploy to production with rollback plan
