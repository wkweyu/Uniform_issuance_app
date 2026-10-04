-- Repair migration:
-- Migration 050 was baselined without executing SQL.
-- This migration restores missing exam workflow schema safely.

-- ==========================================================
-- exam_series workflow columns
-- ==========================================================

SET @db := DATABASE();

SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN workflow_status VARCHAR(24) NOT NULL DEFAULT ''marks_open'' AFTER is_locked',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='workflow_status'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN submitted_by INT NULL AFTER workflow_status',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='submitted_by'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN submitted_at DATETIME NULL AFTER submitted_by',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='submitted_at'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN verified_by INT NULL AFTER submitted_at',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='verified_by'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN verified_at DATETIME NULL AFTER verified_by',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='verified_at'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN approved_by INT NULL AFTER verified_at',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='approved_by'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN approved_at DATETIME NULL AFTER approved_by',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='approved_at'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN published_by INT NULL AFTER approved_at',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='published_by'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN published_at DATETIME NULL AFTER published_by',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='published_at'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


SET @sql = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE exam_series ADD COLUMN workflow_updated_at DATETIME NULL AFTER published_at',
        'SELECT 1'
    )
    FROM information_schema.columns
    WHERE table_schema=@db
      AND table_name='exam_series'
      AND column_name='workflow_updated_at'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


-- ==========================================================
-- Missing tables
-- ==========================================================

CREATE TABLE IF NOT EXISTS exam_assessment_components (
  id BIGINT NOT NULL AUTO_INCREMENT,
  school_id INT NOT NULL,
  exam_id INT NOT NULL,
  class_id INT NOT NULL,
  subject_id INT NOT NULL,
  name VARCHAR(80) NOT NULL,
  category VARCHAR(24) NOT NULL,
  maximum_mark DECIMAL(7,2) NOT NULL,
  weight_percent DECIMAL(6,3) NULL,
  display_order SMALLINT NOT NULL DEFAULT 0,
  is_required TINYINT(1) NOT NULL DEFAULT 1,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY(id),
  UNIQUE KEY uq_exam_component_name
    (school_id,exam_id,class_id,subject_id,name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS exam_component_marks (
  id BIGINT NOT NULL AUTO_INCREMENT,
  school_id INT NOT NULL,
  component_id BIGINT NOT NULL,
  student_id VARCHAR(32) NOT NULL,
  mark DECIMAL(7,2) NULL,
  is_absent TINYINT(1) NOT NULL DEFAULT 0,
  remarks VARCHAR(500),
  created_by INT NULL,
  updated_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY(id),
  UNIQUE KEY uq_exam_component_student
    (school_id,component_id,student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS exam_grading_overrides (
  id BIGINT NOT NULL AUTO_INCREMENT,
  school_id INT NOT NULL,
  exam_id INT NOT NULL,
  class_id INT NOT NULL,
  grading_scale_id INT NOT NULL,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(id),
  UNIQUE KEY uq_exam_grading_override
    (school_id,exam_id,class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS exam_result_bundles (
  id BIGINT NOT NULL AUTO_INCREMENT,
  school_id INT NOT NULL,
  name VARCHAR(100) NOT NULL,
  calculation_method VARCHAR(16) NOT NULL DEFAULT 'equal',
  ranking_metric VARCHAR(24) NOT NULL DEFAULT 'percentage',
  ranking_scope VARCHAR(16) NOT NULL DEFAULT 'class',
  ranking_style VARCHAR(16) NOT NULL DEFAULT 'competition',
  ranking_tie_breakers JSON NULL,
  term_scope VARCHAR(24) NULL,
  effective_from DATE NULL,
  effective_to DATE NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY(id),
  UNIQUE KEY uq_exam_result_bundle_name
    (school_id,name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS exam_result_bundle_exams (
  id BIGINT NOT NULL AUTO_INCREMENT,
  school_id INT NOT NULL,
  bundle_id BIGINT NOT NULL,
  exam_id INT NOT NULL,
  display_order SMALLINT NOT NULL DEFAULT 0,
  weight_percent DECIMAL(6,3) NULL,
  PRIMARY KEY(id),
  UNIQUE KEY uq_exam_result_bundle_exam
    (school_id,bundle_id,exam_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;