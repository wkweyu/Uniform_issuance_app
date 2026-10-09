-- Migration: 061_cashier_shift_pos_extension.sql
-- Description: Phase 2 Commercial POS Cashier Shift Extensions & Sales Grid Enhancements
-- Author: SkoolTrack Pro ERP
-- Date: 2026-10-08

SET FOREIGN_KEY_CHECKS = 0;

-- 1. Extend cashier_sessions for Business Unit & Store Location Context
ALTER TABLE `cashier_sessions`
  ADD COLUMN IF NOT EXISTS `business_unit_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `location_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `terminal_code` VARCHAR(50) DEFAULT 'POS-01',
  ADD KEY IF NOT EXISTS `idx_cs_bu` (`business_unit_id`),
  ADD KEY IF NOT EXISTS `idx_cs_loc` (`location_id`),
  ADD CONSTRAINT `fk_cs_bu` FOREIGN KEY (`business_unit_id`) REFERENCES `business_units`(`id`) ON DELETE SET NULL,
  ADD CONSTRAINT `fk_cs_loc` FOREIGN KEY (`location_id`) REFERENCES `inventory_locations`(`id`) ON DELETE SET NULL;

-- 2. Extend business_sales for Cashier Shift Linking & Financial Breakdown
ALTER TABLE `business_sales`
  ADD COLUMN IF NOT EXISTS `cashier_session_id` INT NULL,
  ADD COLUMN IF NOT EXISTS `subtotal_amount` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `discount_amount` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `tax_amount` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `amount_tendered` DECIMAL(12,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `change_due` DECIMAL(12,2) DEFAULT 0.00,
  ADD KEY IF NOT EXISTS `idx_bs_cs` (`cashier_session_id`),
  ADD CONSTRAINT `fk_bs_cs` FOREIGN KEY (`cashier_session_id`) REFERENCES `cashier_sessions`(`id`) ON DELETE SET NULL;

-- 3. Extend business_sales_items for Line Item Discounts & COGS Costs
ALTER TABLE `business_sales_items`
  ADD COLUMN IF NOT EXISTS `discount_pct` DECIMAL(5,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `tax_pct` DECIMAL(5,2) DEFAULT 0.00,
  ADD COLUMN IF NOT EXISTS `unit_cost` DECIMAL(12,2) DEFAULT 0.00;

SET FOREIGN_KEY_CHECKS = 1;
