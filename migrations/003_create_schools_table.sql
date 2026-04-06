-- Migration: Create schools table for multi-tenant architecture (STEP 1)
-- This migration is additive and does not modify existing tables.

CREATE TABLE IF NOT EXISTS `schools` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(255) NOT NULL,
  `code` VARCHAR(20) NOT NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `subscription_end` DATE NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_schools_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
