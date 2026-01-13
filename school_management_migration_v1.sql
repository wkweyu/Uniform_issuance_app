-- =============================================================================
-- PRODUCTION MIGRATION SCRIPT: Class Management System v1.0
-- Database: schoolmngt
-- Author: AI Assistant
-- Date: 2026-01-12
-- 
-- ⚠️  BACKUP DATABASE BEFORE RUNNING THIS SCRIPT ⚠️
-- 
-- Execution Steps:
-- 1. Backup existing database: mysqldump -u schooluser -p schoolmngt > backup.sql
-- 2. Connect to MySQL: mysql -u schooluser -p schoolmngt
-- 3. Execute this script: source school_management_migration_v1.sql
-- 4. Verify data integrity
-- =============================================================================

-- ============================================================================
-- PHASE 1: Create Configuration Tables (Settings-Driven)
-- ============================================================================

-- Create academic_years table
CREATE TABLE IF NOT EXISTS `academic_years` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `year` INT(11) UNIQUE NOT NULL COMMENT 'e.g., 2025, 2026',
  `name` VARCHAR(50) NOT NULL COMMENT 'e.g., 2025-2026',
  `start_date` DATE NOT NULL,
  `end_date` DATE NOT NULL,
  `is_current` BOOLEAN DEFAULT FALSE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_year` (`year`),
  INDEX `idx_is_current` (`is_current`)
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='Master table for academic years; supports multi-year history';

-- Create class_group_settings table
CREATE TABLE IF NOT EXISTS `class_group_settings` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `code` VARCHAR(20) NOT NULL UNIQUE COMMENT 'e.g., Playgroup-PP2, Grade 1-3',
  `name` VARCHAR(100) NOT NULL COMMENT 'Full name of class group',
  `min_grade` VARCHAR(50) COMMENT 'e.g., Playgroup',
  `max_grade` VARCHAR(50) COMMENT 'e.g., Pre-Primary 2',
  `display_order` INT(11) DEFAULT 0 COMMENT 'Sort order in UI',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_code` (`code`),
  INDEX `idx_display_order` (`display_order`)
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='Centralized class group configuration; replaces hardcoded mappings';

-- Create stream_settings table
CREATE TABLE IF NOT EXISTS `stream_settings` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `school_id` INT(11) COMMENT 'For multi-school support; default 1',
  `code` VARCHAR(10) NOT NULL COMMENT 'e.g., A, B, C, D',
  `name` VARCHAR(100) NOT NULL COMMENT 'e.g., Stream A',
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_stream_code` (`code`),
  UNIQUE KEY `unique_stream_per_school` (`school_id`, `code`),
  INDEX `idx_is_active` (`is_active`)
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='School-specific stream configuration; enforces allowlist';

-- ============================================================================
-- PHASE 2: Modify Master Data Tables
-- ============================================================================

-- Modify classes table (add new columns, preserve old structure temporarily)
ALTER TABLE `classes` 
ADD COLUMN IF NOT EXISTS `academic_year_id` INT(11) COMMENT 'FK → academic_years(id)' AFTER `classID`,
ADD COLUMN IF NOT EXISTS `class_group_code` VARCHAR(20) COMMENT 'FK → class_group_settings(code)' AFTER `class_group`,
ADD COLUMN IF NOT EXISTS `stream_code` VARCHAR(10) COMMENT 'FK → stream_settings(code)' AFTER `class_group_code`,
ADD COLUMN IF NOT EXISTS `display_name` VARCHAR(100) COMMENT 'Generated: Grade 1 - Stream A' AFTER `stream_code`,
ADD COLUMN IF NOT EXISTS `is_active` BOOLEAN DEFAULT TRUE AFTER `display_name`,
ADD COLUMN IF NOT EXISTS `created_by` INT(11) AFTER `is_active`,
ADD COLUMN IF NOT EXISTS `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP AFTER `created_by`,
ADD COLUMN IF NOT EXISTS `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER `created_at`;

-- Add keys separately
ALTER TABLE `classes`
ADD UNIQUE KEY IF NOT EXISTS `unique_class_per_year` (`academic_year_id`, `class_group_code`, `stream_code`),
ADD KEY IF NOT EXISTS `idx_academic_year` (`academic_year_id`),
ADD KEY IF NOT EXISTS `idx_class_group_code` (`class_group_code`),
ADD KEY IF NOT EXISTS `idx_stream_code` (`stream_code`);

-- ============================================================================
-- PHASE 3: Create New Transactional Tables
-- ============================================================================

-- Create class_allocation table (replacement for classallocation)
CREATE TABLE IF NOT EXISTS `class_allocation` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `student_id` INT(11) NOT NULL COMMENT 'FK → studentinfo.AdmNo (will be migrated to INT id)',
  `class_id` INT(11) NOT NULL COMMENT 'FK → classes(classID)',
  `academic_year_id` INT(11) NOT NULL COMMENT 'FK → academic_years(id)',
  `allocation_date` DATE NOT NULL,
  `promoted_from_id` INT(11) COMMENT 'FK → class_allocation(id) for promotion history',
  `is_current` BOOLEAN DEFAULT TRUE COMMENT 'Only one per student per year',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_student_year` (`student_id`, `academic_year_id`),
  KEY `idx_academic_year` (`academic_year_id`),
  KEY `idx_class_id` (`class_id`),
  KEY `idx_is_current` (`is_current`),
  KEY `idx_promoted_from` (`promoted_from_id`),
  FOREIGN KEY (`class_id`) REFERENCES `classes` (`classID`) ON DELETE RESTRICT,
  FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`) ON DELETE RESTRICT,
  FOREIGN KEY (`promoted_from_id`) REFERENCES `class_allocation` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='New class allocation with academic year separation and promotion history';

-- ============================================================================
-- PHASE 4: Create Subject & Teacher Allocation Tables
-- ============================================================================

-- Create subjects table
CREATE TABLE IF NOT EXISTS `subjects` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `code` VARCHAR(50) NOT NULL UNIQUE COMMENT 'e.g., ENG, MATH, SCI',
  `name` VARCHAR(100) NOT NULL COMMENT 'e.g., English Language',
  `description` TEXT,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_code` (`code`),
  INDEX `idx_is_active` (`is_active`)
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='Master list of subjects; school-wide catalog';

-- Create class_subjects table
CREATE TABLE IF NOT EXISTS `class_subjects` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `class_id` INT(11) NOT NULL COMMENT 'FK → classes(classID)',
  `subject_id` INT(11) NOT NULL COMMENT 'FK → subjects(id)',
  `is_compulsory` BOOLEAN DEFAULT TRUE,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_class_subject` (`class_id`, `subject_id`),
  KEY `idx_class_id` (`class_id`),
  KEY `idx_subject_id` (`subject_id`),
  FOREIGN KEY (`class_id`) REFERENCES `classes` (`classID`) ON DELETE CASCADE,
  FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='Maps subjects to a class; enforces class-level subject constraints';

-- Create student_subjects table
CREATE TABLE IF NOT EXISTS `student_subjects` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `class_allocation_id` INT(11) NOT NULL COMMENT 'FK → class_allocation(id)',
  `subject_id` INT(11) NOT NULL COMMENT 'FK → subjects(id)',
  `enrollment_date` DATE NOT NULL,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_student_subject` (`class_allocation_id`, `subject_id`),
  KEY `idx_class_allocation` (`class_allocation_id`),
  KEY `idx_subject_id` (`subject_id`),
  FOREIGN KEY (`class_allocation_id`) REFERENCES `class_allocation` (`id`) ON DELETE CASCADE,
  FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='Flexible student-level subject selection; must be subset of class subjects';

-- Create teacher_allocations table
CREATE TABLE IF NOT EXISTS `teacher_allocations` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `teacher_id` INT(11) NOT NULL COMMENT 'FK → users(userNo)',
  `class_id` INT(11) NOT NULL COMMENT 'FK → classes(classID)',
  `subject_id` INT(11) NOT NULL COMMENT 'FK → subjects(id)',
  `academic_year_id` INT(11) NOT NULL COMMENT 'FK → academic_years(id)',
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_teacher_class_subject` (`class_id`, `subject_id`, `academic_year_id`),
  KEY `idx_teacher_id` (`teacher_id`),
  KEY `idx_class_id` (`class_id`),
  KEY `idx_subject_id` (`subject_id`),
  KEY `idx_academic_year` (`academic_year_id`),
  FOREIGN KEY (`teacher_id`) REFERENCES `users` (`userNo`) ON DELETE RESTRICT,
  FOREIGN KEY (`class_id`) REFERENCES `classes` (`classID`) ON DELETE CASCADE,
  FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`id`) ON DELETE RESTRICT,
  FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='Maps teachers to class-subject combinations; enforces one teacher per combo';

-- ============================================================================
-- PHASE 5: Create Audit & History Tables
-- ============================================================================

-- Create class_promotion_log table
CREATE TABLE IF NOT EXISTS `class_promotion_log` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `batch_id` VARCHAR(50) NOT NULL COMMENT 'Transaction batch identifier',
  `old_class_id` INT(11) NOT NULL COMMENT 'FK → classes(classID)',
  `new_class_id` INT(11) NOT NULL COMMENT 'FK → classes(classID)',
  `student_count` INT(11) DEFAULT 0,
  `promotion_date` DATE NOT NULL,
  `promoted_by` INT(11) COMMENT 'FK → users(userNo)',
  `notes` TEXT,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_batch_id` (`batch_id`),
  KEY `idx_promotion_date` (`promotion_date`),
  KEY `idx_old_class` (`old_class_id`),
  KEY `idx_new_class` (`new_class_id`),
  FOREIGN KEY (`old_class_id`) REFERENCES `classes` (`classID`) ON DELETE RESTRICT,
  FOREIGN KEY (`new_class_id`) REFERENCES `classes` (`classID`) ON DELETE RESTRICT,
  FOREIGN KEY (`promoted_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci'
COMMENT='Audit trail for promotion batches; enables rollback and reporting';

-- ============================================================================
-- PHASE 6: Initialize Configuration Data
-- ============================================================================

-- Insert academic years (current + 2 future years)
INSERT IGNORE INTO `academic_years` (`year`, `name`, `start_date`, `end_date`, `is_current`)
VALUES
  (2025, '2025-2026', '2025-01-01', '2025-12-31', TRUE),
  (2026, '2026-2027', '2026-01-01', '2026-12-31', FALSE),
  (2027, '2027-2028', '2027-01-01', '2027-12-31', FALSE);

-- Insert class group settings
INSERT IGNORE INTO `class_group_settings` (`code`, `name`, `min_grade`, `max_grade`, `display_order`)
VALUES
  ('Playgroup-PP2', 'Playgroup to Pre-Primary 2', 'Playgroup', 'Pre-Primary 2', 1),
  ('Grade 1-3', 'Grade 1 to Grade 3', 'Grade 1', 'Grade 3', 2),
  ('Grade 4-6', 'Grade 4 to Grade 6', 'Grade 4', 'Grade 6', 3),
  ('Grade 7-9', 'Grade 7 to Grade 9', 'Grade 7', 'Grade 9', 4);

-- Insert stream settings
INSERT IGNORE INTO `stream_settings` (`school_id`, `code`, `name`, `is_active`)
VALUES
  (1, 'A', 'Stream A', TRUE),
  (1, 'B', 'Stream B', TRUE),
  (1, 'C', 'Stream C', FALSE),
  (1, 'D', 'Stream D', FALSE);

-- ============================================================================
-- PHASE 7: Migration of Existing Data (if needed)
-- ============================================================================

-- NOTE: This phase is MANUAL and context-dependent.
-- Uncomment and adapt the following queries based on your existing data:

-- Map existing classes to new schema
-- UPDATE classes SET 
--   academic_year_id = (SELECT id FROM academic_years WHERE year = 2025 LIMIT 1),
--   class_group_code = class_group,
--   stream_code = 'A',
--   display_name = CONCAT(class_name, ' - Stream A')
-- WHERE academic_year_id IS NULL;

-- Migrate classallocation to class_allocation
-- INSERT INTO class_allocation (student_id, class_id, academic_year_id, allocation_date, is_current)
-- SELECT AdmNo, classID, (SELECT id FROM academic_years WHERE year = 2025), AllcDate, TRUE
-- FROM classallocation
-- WHERE NOT EXISTS (SELECT 1 FROM class_allocation WHERE class_allocation.class_id = classallocation.classID);

-- ============================================================================
-- PHASE 8: Create Views for Backward Compatibility
-- ============================================================================

-- Legacy view: classallocation (for backward compatibility)
CREATE OR REPLACE VIEW `v_classallocation_legacy` AS
SELECT 
  ca.id,
  ca.student_id AS AdmNo,
  ca.class_id AS classID,
  ca.academic_year_id,
  ca.allocation_date AS AllcDate,
  ca.is_current
FROM `class_allocation` ca
WHERE ca.is_current = TRUE;

-- Reporting view: current class assignments
CREATE OR REPLACE VIEW `v_current_class_assignments` AS
SELECT 
  ca.id,
  ca.student_id,
  si.FName,
  si.SName,
  c.classID,
  c.display_name AS class_name,
  c.class_group_code,
  ay.year AS academic_year,
  ay.name AS academic_year_name,
  ca.allocation_date
FROM `class_allocation` ca
JOIN `studentinfo` si ON ca.student_id = si.AdmNo
JOIN `classes` c ON ca.class_id = c.classID
JOIN `academic_years` ay ON ca.academic_year_id = ay.id
WHERE ca.is_current = TRUE AND ay.is_current = TRUE;

-- ============================================================================
-- PHASE 9: Validation Queries (Run After Migration)
-- ============================================================================

-- Check data integrity
-- SELECT 'Classes without academic year' AS check_name, COUNT(*) AS count 
-- FROM classes WHERE academic_year_id IS NULL;

-- SELECT 'Class allocations without student' AS check_name, COUNT(*) AS count 
-- FROM class_allocation WHERE student_id NOT IN (SELECT AdmNo FROM studentinfo);

-- SELECT 'Class allocations without class' AS check_name, COUNT(*) AS count 
-- FROM class_allocation WHERE class_id NOT IN (SELECT classID FROM classes);

-- ============================================================================
-- EXECUTION SUMMARY
-- ============================================================================

-- Tables Created:
-- 1. academic_years - Master academic year configuration
-- 2. class_group_settings - Class group mappings
-- 3. stream_settings - Allowed streams per school
-- 4. classes (MODIFIED) - Enhanced with new columns
-- 5. class_allocation - New allocation table with history
-- 6. subjects - Master subjects catalog
-- 7. class_subjects - Class-subject mapping
-- 8. student_subjects - Student-subject allocation
-- 9. teacher_allocations - Teacher-class-subject mapping
-- 10. class_promotion_log - Audit trail for promotions
-- 11. v_classallocation_legacy - Backward compatibility view
-- 12. v_current_class_assignments - Reporting view

-- Data Initialized:
-- - 3 Academic Years (2025, 2026, 2027)
-- - 4 Class Groups (Playgroup-PP2, Grade 1-3, Grade 4-6, Grade 7-9)
-- - 4 Streams (A, B, C, D)

-- ⚠️  IMPORTANT POST-MIGRATION STEPS ⚠️
-- 1. Run validation queries above to check data integrity
-- 2. Test backward compatibility with existing routes
-- 3. Verify uniform pricing still works (class_group_code mapping)
-- 4. Test fleet and issuance systems
-- 5. Run integration tests
-- 6. Only after 48-72 hours validation: archive old classallocation table

-- ============================================================================
