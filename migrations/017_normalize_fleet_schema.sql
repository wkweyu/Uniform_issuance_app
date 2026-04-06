-- Migration: normalize legacy fleet tables to the active transport service contract.
-- Goals:
-- 1. Standardize buses on model/current transport fields while keeping legacy make data readable.
-- 2. Promote service_records to bus_services and leave a compatibility view behind.
-- 3. Align fuel_vouchers with voucher_no/date_issued/quantity/total_cost style columns.

ALTER TABLE `buses`
  ADD COLUMN IF NOT EXISTS `model` VARCHAR(255) NULL AFTER `reg_no`;
UPDATE `buses`
SET `model` = COALESCE(`model`, `make`)
WHERE `model` IS NULL;
UPDATE `buses`
SET `make` = COALESCE(`make`, `model`)
WHERE `make` IS NULL;
ALTER TABLE `buses`
  ADD KEY IF NOT EXISTS `idx_buses_school_reg_no` (`school_id`, `reg_no`);

SET @has_service_records_table = (
  SELECT COUNT(*)
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'service_records'
    AND TABLE_TYPE = 'BASE TABLE'
);
SET @has_bus_services_table = (
  SELECT COUNT(*)
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'bus_services'
    AND TABLE_TYPE = 'BASE TABLE'
);
SET @rename_service_records_sql = IF(
  @has_service_records_table = 1 AND @has_bus_services_table = 0,
  'RENAME TABLE `service_records` TO `bus_services`',
  'SELECT 1'
);
PREPARE stmt FROM @rename_service_records_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_service_records_table = (
  SELECT COUNT(*)
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'service_records'
    AND TABLE_TYPE = 'BASE TABLE'
);
SET @has_bus_services_table = (
  SELECT COUNT(*)
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'bus_services'
    AND TABLE_TYPE = 'BASE TABLE'
);
SET @copy_service_records_sql = IF(
  @has_service_records_table = 1 AND @has_bus_services_table = 1,
  'INSERT INTO `bus_services` (`id`, `bus_id`, `service_date`, `service_type`, `description`, `cost`, `garage_name`, `mileage_at_service`, `school_id`) SELECT sr.`id`, sr.`bus_id`, sr.`service_date`, sr.`service_type`, sr.`description`, sr.`cost`, sr.`garage_name`, sr.`mileage_at_service`, sr.`school_id` FROM `service_records` sr LEFT JOIN `bus_services` bs ON bs.`id` = sr.`id` WHERE bs.`id` IS NULL',
  'SELECT 1'
);
PREPARE stmt FROM @copy_service_records_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE `bus_services`
  ADD KEY IF NOT EXISTS `idx_bus_services_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_bus_services_school_date` (`school_id`, `service_date`);

SET @has_service_records_table = (
  SELECT COUNT(*)
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'service_records'
    AND TABLE_TYPE = 'BASE TABLE'
);
SET @has_service_records_view = (
  SELECT COUNT(*)
  FROM information_schema.VIEWS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'service_records'
);
SET @has_bus_services_table = (
  SELECT COUNT(*)
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'bus_services'
    AND TABLE_TYPE = 'BASE TABLE'
);
SET @create_service_records_view_sql = IF(
  @has_service_records_table = 0 AND @has_service_records_view = 0 AND @has_bus_services_table = 1,
  'CREATE VIEW `service_records` AS SELECT `id`, `bus_id`, `service_date`, `service_type`, `description`, `cost`, `garage_name`, `mileage_at_service`, `school_id` FROM `bus_services`',
  'SELECT 1'
);
PREPARE stmt FROM @create_service_records_view_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE `fuel_vouchers`
  ADD COLUMN IF NOT EXISTS `voucher_no` VARCHAR(50) NULL AFTER `id`,
  ADD COLUMN IF NOT EXISTS `date_issued` DATETIME NULL AFTER `bus_id`,
  ADD COLUMN IF NOT EXISTS `fuel_type` VARCHAR(50) NULL AFTER `date_issued`,
  ADD COLUMN IF NOT EXISTS `quantity` DECIMAL(10,2) NULL AFTER `fuel_type`,
  ADD COLUMN IF NOT EXISTS `total_cost` DECIMAL(10,2) NULL AFTER `unit_price`,
  ADD COLUMN IF NOT EXISTS `current_mileage` INT NULL AFTER `total_cost`,
  ADD COLUMN IF NOT EXISTS `remarks` TEXT NULL AFTER `issued_by`;

UPDATE `fuel_vouchers`
SET `quantity` = COALESCE(`quantity`, `litres`)
WHERE `quantity` IS NULL;
UPDATE `fuel_vouchers`
SET `litres` = COALESCE(`litres`, `quantity`)
WHERE `litres` IS NULL;
UPDATE `fuel_vouchers`
SET `total_cost` = COALESCE(`total_cost`, `total_amount`)
WHERE `total_cost` IS NULL;
UPDATE `fuel_vouchers`
SET `total_amount` = COALESCE(`total_amount`, `total_cost`)
WHERE `total_amount` IS NULL;
UPDATE `fuel_vouchers`
SET `fuel_type` = COALESCE(`fuel_type`, 'Fuel')
WHERE `fuel_type` IS NULL;
UPDATE `fuel_vouchers`
SET `voucher_no` = CONCAT('FV-LEGACY-', `id`)
WHERE `voucher_no` IS NULL OR `voucher_no` = '';

SET @has_fuel_issued_on = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'fuel_vouchers'
    AND COLUMN_NAME = 'issued_on'
);
SET @has_fuel_date = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'fuel_vouchers'
    AND COLUMN_NAME = 'date'
);
SET @backfill_date_issued_sql = IF(
  @has_fuel_issued_on = 1,
  'UPDATE `fuel_vouchers` SET `date_issued` = COALESCE(`date_issued`, `issued_on`) WHERE `date_issued` IS NULL',
  IF(
    @has_fuel_date = 1,
    'UPDATE `fuel_vouchers` SET `date_issued` = COALESCE(`date_issued`, `date`) WHERE `date_issued` IS NULL',
    'SELECT 1'
  )
);
PREPARE stmt FROM @backfill_date_issued_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sync_issued_on_sql = IF(
  @has_fuel_issued_on = 1,
  'UPDATE `fuel_vouchers` SET `issued_on` = COALESCE(`issued_on`, `date_issued`) WHERE `issued_on` IS NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sync_issued_on_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sync_legacy_date_sql = IF(
  @has_fuel_date = 1,
  'UPDATE `fuel_vouchers` SET `date` = COALESCE(`date`, DATE(`date_issued`)) WHERE `date` IS NULL',
  'SELECT 1'
);
PREPARE stmt FROM @sync_legacy_date_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE `fuel_vouchers`
  ADD UNIQUE KEY IF NOT EXISTS `uq_fuel_vouchers_voucher_no` (`voucher_no`),
  ADD KEY IF NOT EXISTS `idx_fuel_vouchers_school_date_issued` (`school_id`, `date_issued`);