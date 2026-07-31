-- Migration 032: Reusable tenant-scoped fee allocation templates.

CREATE TABLE IF NOT EXISTS `fee_allocation_templates` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `school_id` INT NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `created_by` INT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY `uq_fee_allocation_template_school_name` (`school_id`, `name`),
  KEY `idx_fee_allocation_templates_school` (`school_id`)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `fee_allocation_template_items` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `template_id` INT NOT NULL,
  `votehead_id` INT NOT NULL,
  `amount` DECIMAL(15, 2) NOT NULL,
  `school_id` INT NOT NULL,
  UNIQUE KEY `uq_fee_allocation_template_votehead` (`template_id`, `votehead_id`),
  KEY `idx_fee_allocation_template_items_school_template` (`school_id`, `template_id`),
  CONSTRAINT `fk_fee_allocation_template_item_template`
    FOREIGN KEY (`template_id`) REFERENCES `fee_allocation_templates` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_fee_allocation_template_item_votehead`
    FOREIGN KEY (`votehead_id`) REFERENCES `fee_voteheads` (`id`)
) ENGINE=InnoDB;