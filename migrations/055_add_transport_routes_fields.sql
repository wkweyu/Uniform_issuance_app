-- Migration: Add bus_id and school_id to transport_routes table
-- Ensures transport routes can be assigned to buses and scoped by school_id for multi-tenancy.

ALTER TABLE `transport_routes`
  ADD COLUMN IF NOT EXISTS `bus_id` INT NULL AFTER `description`,
  ADD COLUMN IF NOT EXISTS `school_id` INT NOT NULL DEFAULT 1 AFTER `bus_id`,
  ADD KEY IF NOT EXISTS `idx_transport_routes_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_transport_routes_bus_id` (`bus_id`);
