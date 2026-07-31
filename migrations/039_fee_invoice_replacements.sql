-- Preserve the complete audit chain whenever a current-term invoice is
-- replaced after a student category or group correction.
CREATE TABLE IF NOT EXISTS `fee_invoice_replacements` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `admno` INT NOT NULL,
  `academic_year_id` INT NOT NULL,
  `term_id` INT NOT NULL,
  `original_invoice_reference` VARCHAR(100) NOT NULL,
  `reversal_reference` VARCHAR(100) NOT NULL,
  `replacement_invoice_reference` VARCHAR(100) NOT NULL,
  `previous_category` VARCHAR(100) NOT NULL,
  `new_category` VARCHAR(100) NOT NULL,
  `previous_student_group_id` INT NULL,
  `new_student_group_id` INT NULL,
  `reason` VARCHAR(500) NOT NULL,
  `changed_by` INT NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY `uq_fee_invoice_replacement_original` (`school_id`, `original_invoice_reference`),
  UNIQUE KEY `uq_fee_invoice_replacement_new` (`school_id`, `replacement_invoice_reference`),
  KEY `idx_fee_invoice_replacements_student_term` (`school_id`, `admno`, `academic_year_id`, `term_id`),
  KEY `idx_fee_invoice_replacements_changed_by` (`school_id`, `changed_by`)
) ENGINE=InnoDB;