-- Migration: Add school_id to fleet, inventory, and finance tables (STEP 12)
-- Ensures multi-tenancy for buses, fuel, service, inventory, and prices.

-- 1. Buses
ALTER TABLE `buses` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1 AFTER `current_mileage`;
ALTER TABLE `buses` ADD KEY `idx_buses_school_id` (`school_id`);
ALTER TABLE `buses` ADD CONSTRAINT `fk_buses_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);
ALTER TABLE `buses` ADD COLUMN `active` TINYINT(1) DEFAULT 1;

-- 2. Fuel Vouchers
ALTER TABLE `fuel_vouchers` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `fuel_vouchers` ADD KEY `idx_fuel_vouchers_school_id` (`school_id`);
ALTER TABLE `fuel_vouchers` ADD CONSTRAINT `fk_fuel_vouchers_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- 3. Fuel Invoices
ALTER TABLE `fuel_invoices` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `fuel_invoices` ADD KEY `idx_fuel_invoices_school_id` (`school_id`);
ALTER TABLE `fuel_invoices` ADD CONSTRAINT `fk_fuel_invoices_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- 4. Service Records
ALTER TABLE `service_records` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `service_records` ADD KEY `idx_service_records_school_id` (`school_id`);
ALTER TABLE `service_records` ADD CONSTRAINT `fk_service_records_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- 5. Oil Records
ALTER TABLE `oil_records` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `oil_records` ADD KEY `idx_oil_records_school_id` (`school_id`);
ALTER TABLE `oil_records` ADD CONSTRAINT `fk_oil_records_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- 6. Item Stock
ALTER TABLE `item_stock` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `item_stock` ADD KEY `idx_item_stock_school_id` (`school_id`);
ALTER TABLE `item_stock` ADD CONSTRAINT `fk_item_stock_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);
-- Remove unique constraint on item_name to allow same named items across schools
ALTER TABLE `item_stock` DROP INDEX `item_name`;
ALTER TABLE `item_stock` ADD UNIQUE KEY `idx_item_stock_name_school` (`item_name`, `school_id`);

-- 7. Stock Movements
ALTER TABLE `stock_movements` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `stock_movements` ADD KEY `idx_stock_movements_school_id` (`school_id`);
ALTER TABLE `stock_movements` ADD CONSTRAINT `fk_stock_movements_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- 8. Uniform Receipts
ALTER TABLE `uniform_receipts` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `uniform_receipts` ADD KEY `idx_uniform_receipts_school_id` (`school_id`);
ALTER TABLE `uniform_receipts` ADD CONSTRAINT `fk_uniform_receipts_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- 9. Uniform Prices (Correcting if ADD COLUMN school_id failed or was missing)
-- If uniform_prices already has school_id from SQLAlchemy, this might fail, but let's be safe.
-- We check for existence first in a real migration tool, but here we'll use a script.
-- For this direct SQL, let's assume it might be missing or needs the index/FK.
ALTER TABLE `uniform_prices` ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `uniform_prices` ADD KEY IF NOT EXISTS `idx_uniform_prices_school_id` (`school_id`);
-- ALTER TABLE `uniform_prices` ADD CONSTRAINT `fk_uniform_prices_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);

-- 10. Academic Years
ALTER TABLE `academic_years` ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `academic_years` ADD KEY IF NOT EXISTS `idx_academic_years_school_id` (`school_id`);

-- 11. Fee Ledger
ALTER TABLE `fee_ledger` ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `fee_ledger` ADD KEY IF NOT EXISTS `idx_fee_ledger_school_id` (`school_id`);

-- 12. Fodebit (legacy finance table)
ALTER TABLE `fodebit` ADD COLUMN `school_id` INT NOT NULL DEFAULT 1;
ALTER TABLE `fodebit` ADD KEY `idx_fodebit_school_id` (`school_id`);
ALTER TABLE `fodebit` ADD CONSTRAINT `fk_fodebit_school_id` FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`);
