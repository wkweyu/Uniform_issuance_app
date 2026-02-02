-- =============================================================================
-- EXAM MANAGEMENT SYSTEM MIGRATION
-- Database: schoolmngt
-- =============================================================================

-- Phase 1: Create Grading Tables
CREATE TABLE IF NOT EXISTS `grading_scales` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(100) NOT NULL UNIQUE,
  `description` TEXT,
  `is_default` BOOLEAN DEFAULT FALSE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

CREATE TABLE IF NOT EXISTS `grading_details` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `scale_id` INT(11) NOT NULL,
  `grade` VARCHAR(5) NOT NULL,
  `min_mark` DECIMAL(5,2) NOT NULL,
  `max_mark` DECIMAL(5,2) NOT NULL,
  `points` INT(11) DEFAULT 0,
  `remarks` VARCHAR(100),
  PRIMARY KEY (`id`),
  FOREIGN KEY (`scale_id`) REFERENCES `grading_scales` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Phase 2: Create Exam Series Table
CREATE TABLE IF NOT EXISTS `exam_series` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(100) NOT NULL,
  `academic_year_id` INT(11) NOT NULL,
  `term` INT(11) NOT NULL COMMENT '1, 2, or 3',
  `is_active` BOOLEAN DEFAULT TRUE,
  `is_locked` BOOLEAN DEFAULT FALSE COMMENT 'Locked exams cannot have marks edited',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `created_by` INT(11),
  PRIMARY KEY (`id`),
  FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`),
  FOREIGN KEY (`created_by`) REFERENCES `users` (`userNo`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Phase 3: Create Marks Table
CREATE TABLE IF NOT EXISTS `exam_marks` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `exam_id` INT(11) NOT NULL,
  `student_id` INT(11) NOT NULL COMMENT 'FK to studentinfo.AdmNo',
  `subject_id` INT(11) NOT NULL,
  `mark` DECIMAL(5,2),
  `grade_id` INT(11),
  `is_absent` BOOLEAN DEFAULT FALSE,
  `remarks` VARCHAR(255),
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_student_exam_subject` (`exam_id`, `student_id`, `subject_id`),
  FOREIGN KEY (`exam_id`) REFERENCES `exam_series` (`id`) ON DELETE CASCADE,
  FOREIGN KEY (`student_id`) REFERENCES `studentinfo` (`AdmNo`),
  FOREIGN KEY (`subject_id`) REFERENCES `subjects` (`subjectNo`),
  FOREIGN KEY (`grade_id`) REFERENCES `grading_details` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Initial Grading Data
INSERT IGNORE INTO `grading_scales` (`name`, `description`, `is_default`) VALUES ('Standard Primary Grading', 'Default grading scale for primary school', TRUE);

SET @scale_id = LAST_INSERT_ID();

INSERT IGNORE INTO `grading_details` (`scale_id`, `grade`, `min_mark`, `max_mark`, `points`, `remarks`) VALUES
(@scale_id, 'A', 80, 100, 12, 'Excellent'),
(@scale_id, 'A-', 75, 79.99, 11, 'Very Good'),
(@scale_id, 'B+', 70, 74.99, 10, 'Good'),
(@scale_id, 'B', 65, 69.99, 9, 'Fairly Good'),
(@scale_id, 'B-', 60, 64.99, 8, 'Above Average'),
(@scale_id, 'C+', 55, 59.99, 7, 'Average'),
(@scale_id, 'C', 50, 54.99, 6, 'Below Average'),
(@scale_id, 'C-', 45, 49.99, 5, 'Weak'),
(@scale_id, 'D+', 40, 44.99, 4, 'Very Weak'),
(@scale_id, 'D', 35, 39.99, 3, 'Poor'),
(@scale_id, 'D-', 30, 34.99, 2, 'Very Poor'),
(@scale_id, 'E', 0, 29.99, 1, 'Fail');
