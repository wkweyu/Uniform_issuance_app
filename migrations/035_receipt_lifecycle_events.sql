-- Migration 035: Immutable audit history for fee receipt lifecycle actions.

CREATE TABLE IF NOT EXISTS `fee_receipt_lifecycle_events` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `payment_id` INT NOT NULL,
  `event_type` ENUM('POSTED', 'PRINTED', 'REPRINTED', 'CANCELLED', 'TRANSFERRED', 'REPOSTED', 'ARCHIVED') NOT NULL,
  `status_after` VARCHAR(30) NOT NULL,
  `reason` VARCHAR(500) NULL,
  `actor_user_id` INT NOT NULL,
  `occurred_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `correlation_id` CHAR(36) NOT NULL,
  `replacement_payment_id` INT NULL,
  `snapshot_json` JSON NOT NULL,
  KEY `idx_fee_receipt_lifecycle_school_payment` (`school_id`, `payment_id`, `id`),
  KEY `idx_fee_receipt_lifecycle_correlation` (`school_id`, `correlation_id`),
  KEY `idx_fee_receipt_lifecycle_replacement` (`replacement_payment_id`)
) ENGINE=InnoDB;