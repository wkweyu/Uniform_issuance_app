ALTER TABLE `exam_series`
  ADD COLUMN `workflow_status` VARCHAR(24) NOT NULL DEFAULT 'marks_open' AFTER `is_locked`,
  ADD COLUMN `submitted_by` INT NULL AFTER `workflow_status`,
  ADD COLUMN `submitted_at` DATETIME NULL AFTER `submitted_by`,
  ADD COLUMN `verified_by` INT NULL AFTER `submitted_at`,
  ADD COLUMN `verified_at` DATETIME NULL AFTER `verified_by`,
  ADD COLUMN `approved_by` INT NULL AFTER `verified_at`,
  ADD COLUMN `approved_at` DATETIME NULL AFTER `approved_by`,
  ADD COLUMN `published_by` INT NULL AFTER `approved_at`,
  ADD COLUMN `published_at` DATETIME NULL AFTER `published_by`,
  ADD COLUMN `workflow_updated_at` DATETIME NULL AFTER `published_at`;

UPDATE `exam_series`
SET `workflow_status` = IF(`is_locked` = TRUE, 'locked', 'marks_open'),
    `workflow_updated_at` = CURRENT_TIMESTAMP;

ALTER TABLE `exam_series`
  ADD KEY `idx_exam_series_workflow` (`school_id`, `workflow_status`, `id`),
  ADD CONSTRAINT `fk_exam_series_submitted_by`
    FOREIGN KEY (`submitted_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_exam_series_verified_by`
    FOREIGN KEY (`verified_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_exam_series_approved_by`
    FOREIGN KEY (`approved_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_exam_series_published_by`
    FOREIGN KEY (`published_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL;

CREATE TABLE `exam_assessment_components` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `exam_id` INT NOT NULL,
  `class_id` INT NOT NULL,
  `subject_id` INT NOT NULL,
  `name` VARCHAR(80) NOT NULL,
  `category` VARCHAR(24) NOT NULL,
  `maximum_mark` DECIMAL(7,2) NOT NULL,
  `weight_percent` DECIMAL(6,3) NULL,
  `display_order` SMALLINT NOT NULL DEFAULT 0,
  `is_required` TINYINT(1) NOT NULL DEFAULT 1,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_by` INT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exam_component_name` (`school_id`, `exam_id`, `class_id`, `subject_id`, `name`),
  KEY `idx_exam_component_lookup` (`school_id`, `exam_id`, `class_id`, `subject_id`, `is_active`),
  CONSTRAINT `fk_exam_component_school` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_component_exam` FOREIGN KEY (`exam_id`) REFERENCES `exam_series` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_component_class` FOREIGN KEY (`class_id`) REFERENCES `classes` (`classID`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_component_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL,
  CONSTRAINT `chk_exam_component_category` CHECK (`category` IN ('formative', 'summative')),
  CONSTRAINT `chk_exam_component_maximum` CHECK (`maximum_mark` > 0),
  CONSTRAINT `chk_exam_component_weight` CHECK (`weight_percent` IS NULL OR (`weight_percent` >= 0 AND `weight_percent` <= 100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `exam_component_marks` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `component_id` BIGINT NOT NULL,
  `student_id` VARCHAR(32) NOT NULL,
  `mark` DECIMAL(7,2) NULL,
  `is_absent` TINYINT(1) NOT NULL DEFAULT 0,
  `remarks` VARCHAR(500) NULL,
  `created_by` INT NULL,
  `updated_by` INT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exam_component_student` (`school_id`, `component_id`, `student_id`),
  KEY `idx_exam_component_marks_student` (`school_id`, `student_id`, `component_id`),
  CONSTRAINT `fk_exam_component_mark_school` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_component_mark_component` FOREIGN KEY (`component_id`) REFERENCES `exam_assessment_components` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_component_mark_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL,
  CONSTRAINT `fk_exam_component_mark_updater` FOREIGN KEY (`updated_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL,
  CONSTRAINT `chk_exam_component_mark_absence` CHECK (`is_absent` IN (0, 1)),
  CONSTRAINT `chk_exam_component_mark_nonnegative` CHECK (`mark` IS NULL OR `mark` >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `exam_grading_overrides` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `exam_id` INT NOT NULL,
  `class_id` INT NOT NULL,
  `grading_scale_id` INT NOT NULL,
  `created_by` INT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exam_grading_override` (`school_id`, `exam_id`, `class_id`),
  CONSTRAINT `fk_exam_grading_override_school` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_grading_override_exam` FOREIGN KEY (`exam_id`) REFERENCES `exam_series` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_grading_override_class` FOREIGN KEY (`class_id`) REFERENCES `classes` (`classID`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_grading_override_scale` FOREIGN KEY (`grading_scale_id`) REFERENCES `grading_scales` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_exam_grading_override_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `exam_result_bundles` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `calculation_method` VARCHAR(16) NOT NULL DEFAULT 'equal',
  `ranking_metric` VARCHAR(24) NOT NULL DEFAULT 'percentage',
  `ranking_scope` VARCHAR(16) NOT NULL DEFAULT 'class',
  `ranking_style` VARCHAR(16) NOT NULL DEFAULT 'competition',
  `ranking_tie_breakers` JSON NULL,
  `term_scope` VARCHAR(24) NULL,
  `effective_from` DATE NULL,
  `effective_to` DATE NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_by` INT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exam_result_bundle_name` (`school_id`, `name`),
  CONSTRAINT `fk_exam_result_bundle_school` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_result_bundle_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL,
  CONSTRAINT `chk_exam_result_bundle_calculation` CHECK (`calculation_method` IN ('equal', 'weighted')),
  CONSTRAINT `chk_exam_result_bundle_metric` CHECK (`ranking_metric` IN ('total_marks', 'total_points', 'average', 'percentage', 'mean_grade')),
  CONSTRAINT `chk_exam_result_bundle_scope` CHECK (`ranking_scope` IN ('stream', 'class', 'grade', 'school')),
  CONSTRAINT `chk_exam_result_bundle_style` CHECK (`ranking_style` IN ('dense', 'competition')),
  CONSTRAINT `chk_exam_result_bundle_effective_dates`
    CHECK (`effective_from` IS NULL OR `effective_to` IS NULL OR `effective_from` <= `effective_to`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `exam_result_bundle_exams` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `bundle_id` BIGINT NOT NULL,
  `exam_id` INT NOT NULL,
  `display_order` SMALLINT NOT NULL DEFAULT 0,
  `weight_percent` DECIMAL(6,3) NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exam_result_bundle_exam` (`school_id`, `bundle_id`, `exam_id`),
  KEY `idx_exam_result_bundle_order` (`school_id`, `bundle_id`, `display_order`),
  CONSTRAINT `fk_exam_result_bundle_exam_school` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_result_bundle_exam_bundle` FOREIGN KEY (`bundle_id`) REFERENCES `exam_result_bundles` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_result_bundle_exam_series` FOREIGN KEY (`exam_id`) REFERENCES `exam_series` (`id`) ON DELETE CASCADE,
  CONSTRAINT `chk_exam_result_bundle_exam_weight` CHECK (`weight_percent` IS NULL OR (`weight_percent` >= 0 AND `weight_percent` <= 100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
