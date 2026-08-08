-- Migration 044: Immutable, tenant-scoped student fee refund audit records.
CREATE TABLE IF NOT EXISTS `fee_refunds` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `admno` INT NOT NULL,
  `academic_year_id` INT NOT NULL,
  `term_id` INT NOT NULL,
  `votehead_id` INT NOT NULL,
  `amount` DECIMAL(15, 2) NOT NULL,
  `refund_method` VARCHAR(30) NOT NULL,
  `refund_reference` VARCHAR(100) NOT NULL,
  `reason` VARCHAR(1000) NOT NULL,
  `effective_date` DATE NOT NULL,
  `ledger_id` BIGINT NULL,
  `refunded_by` INT NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY `uq_fee_refunds_reference` (`school_id`, `refund_reference`),
  KEY `idx_fee_refunds_student_date` (`school_id`, `admno`, `effective_date`),
  KEY `idx_fee_refunds_ledger` (`school_id`, `ledger_id`)
) ENGINE=InnoDB;
