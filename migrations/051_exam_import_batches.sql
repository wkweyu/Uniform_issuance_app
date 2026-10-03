CREATE TABLE `exam_import_batches` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `exam_id` INT NOT NULL,
  `class_id` INT NOT NULL,
  `created_by` INT NULL,
  `source_type` VARCHAR(24) NOT NULL,
  `source_sha256` CHAR(64) NOT NULL,
  `row_count` INT NOT NULL DEFAULT 0,
  `mark_count` INT NOT NULL DEFAULT 0,
  `status` VARCHAR(16) NOT NULL DEFAULT 'applied',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_exam_import_batch_scope` (`school_id`, `exam_id`, `class_id`, `created_at`),
  CONSTRAINT `fk_exam_import_batch_school`
    FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_import_batch_exam`
    FOREIGN KEY (`exam_id`) REFERENCES `exam_series` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_import_batch_class`
    FOREIGN KEY (`class_id`) REFERENCES `classes` (`classID`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_import_batch_actor`
    FOREIGN KEY (`created_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL,
  CONSTRAINT `chk_exam_import_batch_source`
    CHECK (`source_type` IN ('xlsx_components')),
  CONSTRAINT `chk_exam_import_batch_status`
    CHECK (`status` IN ('applied'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
