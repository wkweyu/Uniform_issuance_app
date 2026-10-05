-- Migration: 055_transport_routes_schema.sql
-- Description: Safely ensure transport_routes table columns, default values, and indexes exist.

ALTER TABLE `transport_routes`
  ADD COLUMN IF NOT EXISTS `is_active` TINYINT(1) NOT NULL DEFAULT 1 AFTER `description`,
  ADD COLUMN IF NOT EXISTS `bus_id` INT NULL AFTER `amount`,
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL AFTER `bus_id`;

ALTER TABLE `transport_routes`
  ADD KEY IF NOT EXISTS `idx_transport_routes_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_transport_routes_bus_id` (`bus_id`);
