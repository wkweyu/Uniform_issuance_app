-- Migration: Add class_teachers table
CREATE TABLE IF NOT EXISTS `class_teachers` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `teacher_id` INT(11) NOT NULL COMMENT 'FK → users(userNo)',
  `class_id` INT(11) NOT NULL COMMENT 'FK → classes(classID)',
  `academic_year_id` INT(11) NOT NULL COMMENT 'FK → academic_years(id)',
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_class_year` (`class_id`, `academic_year_id`),
  KEY `idx_teacher_id` (`teacher_id`),
  KEY `idx_class_id` (`class_id`),
  KEY `idx_academic_year` (`academic_year_id`),
  FOREIGN KEY (`teacher_id`) REFERENCES `users` (`userNo`) ON DELETE RESTRICT,
  FOREIGN KEY (`class_id`) REFERENCES `classes` (`classID`) ON DELETE CASCADE,
  FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=1 COLLATE='latin1_swedish_ci';
