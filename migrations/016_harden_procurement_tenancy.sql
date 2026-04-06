-- Migration: tenant hardening for procurement and legacy finance reference tables.
-- Adds school ownership columns used by the procurement service layer and backfills
-- existing rows to the default tenant so legacy data remains accessible.

ALTER TABLE `suppliers`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `_date`;
UPDATE `suppliers` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `suppliers`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_suppliers_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_suppliers_school_company` (`school_id`, `company`);

ALTER TABLE `purchase_orders`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `department_id`;
UPDATE `purchase_orders` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `purchase_orders`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_purchase_orders_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_purchase_orders_school_status` (`school_id`, `status`),
  ADD KEY IF NOT EXISTS `idx_purchase_orders_school_supplier` (`school_id`, `supplier_id`);

ALTER TABLE `purchase_order_items`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `total_price`;
UPDATE `purchase_order_items` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `purchase_order_items`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_purchase_order_items_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_purchase_order_items_school_po` (`school_id`, `po_id`);

ALTER TABLE `procurement_grns`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `created_at`;
UPDATE `procurement_grns` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `procurement_grns`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_procurement_grns_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_procurement_grns_school_po` (`school_id`, `po_id`);

ALTER TABLE `procurement_grn_items`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `quantity_received`;
UPDATE `procurement_grn_items` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `procurement_grn_items`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_procurement_grn_items_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_procurement_grn_items_school_grn` (`school_id`, `grn_id`),
  ADD KEY IF NOT EXISTS `idx_procurement_grn_items_school_po_item` (`school_id`, `po_item_id`);

ALTER TABLE `supplier_payments`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `created_by`;
UPDATE `supplier_payments` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `supplier_payments`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_supplier_payments_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_supplier_payments_school_po` (`school_id`, `po_id`);

ALTER TABLE `assets_registry`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `po_id`;
UPDATE `assets_registry` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `assets_registry`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_assets_registry_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_assets_registry_school_po` (`school_id`, `po_id`);

ALTER TABLE `procurement_budgets`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `created_at`;
UPDATE `procurement_budgets` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `procurement_budgets`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_procurement_budgets_school_id` (`school_id`),
  ADD UNIQUE KEY IF NOT EXISTS `uq_procurement_budgets_scope` (`school_id`, `department_id`, `academic_year_id`, `category`);

ALTER TABLE `procurement_requisitions`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `academic_year_id`;
UPDATE `procurement_requisitions` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `procurement_requisitions`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_procurement_requisitions_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_procurement_requisitions_school_status` (`school_id`, `status`);

ALTER TABLE `procurement_requisition_items`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `item_id`;
UPDATE `procurement_requisition_items` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `procurement_requisition_items`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_procurement_requisition_items_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_procurement_requisition_items_school_req` (`school_id`, `requisition_id`);

ALTER TABLE `finance_accounts`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `created_at`;
UPDATE `finance_accounts` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `finance_accounts`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_finance_accounts_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_finance_accounts_school_type` (`school_id`, `type`);

ALTER TABLE `finance_transactions`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `created_at`;
UPDATE `finance_transactions` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `finance_transactions`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_finance_transactions_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_finance_transactions_school_date` (`school_id`, `transaction_date`);

ALTER TABLE `finance_ledger_entries`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `is_reconciled`;
UPDATE `finance_ledger_entries` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `finance_ledger_entries`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_finance_ledger_entries_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_finance_ledger_entries_school_txn` (`school_id`, `transaction_id`),
  ADD KEY IF NOT EXISTS `idx_finance_ledger_entries_school_supplier` (`school_id`, `supplier_id`);

ALTER TABLE `staffdepts`
  ADD COLUMN IF NOT EXISTS `school_id` INT NULL DEFAULT 1 AFTER `_date`;
UPDATE `staffdepts` SET `school_id` = 1 WHERE `school_id` IS NULL;
ALTER TABLE `staffdepts`
  MODIFY COLUMN `school_id` INT NOT NULL DEFAULT 1,
  ADD KEY IF NOT EXISTS `idx_staffdepts_school_id` (`school_id`),
  ADD KEY IF NOT EXISTS `idx_staffdepts_school_name` (`school_id`, `dept`);