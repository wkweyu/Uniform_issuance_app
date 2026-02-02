-- Procurement Module Tables

-- Use existing suppliers table (it already exists in this database)

-- 1. Purchase Orders Table
CREATE TABLE IF NOT EXISTS `purchase_orders` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `po_number` VARCHAR(20) UNIQUE NOT NULL, -- Format: PO-0001-26
    `supplier_id` INT NOT NULL,
    `order_date` DATE NOT NULL,
    `expected_delivery_date` DATE,
    `total_amount` DECIMAL(15, 2) DEFAULT 0.00,
    `status` ENUM('DRAFT', 'PENDING_APPROVAL', 'ORDERED', 'RECEIVED', 'CANCELLED') DEFAULT 'DRAFT',
    `payment_status` ENUM('UNPAID', 'PARTIAL', 'PAID') DEFAULT 'UNPAID',
    `notes` TEXT,
    `approved_by` INT,
    `created_by` INT,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`supplier_id`) REFERENCES `suppliers`(`supplierID`)
) ENGINE=InnoDB;

-- 3. Purchase Order Items
CREATE TABLE IF NOT EXISTS `purchase_order_items` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `po_id` INT NOT NULL,
    `description` VARCHAR(255) NOT NULL,
    `quantity` DECIMAL(10, 2) NOT NULL,
    `unit_price` DECIMAL(15, 2) NOT NULL,
    `total_price` DECIMAL(15, 2) AS (quantity * unit_price) STORED,
    FOREIGN KEY (`po_id`) REFERENCES `purchase_orders`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 4. Supplier Payments (Linking Procurement to Finance)
CREATE TABLE IF NOT EXISTS `supplier_payments` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `po_id` INT NOT NULL,
    `transaction_id` INT, -- Link to finance_transactions
    `amount` DECIMAL(15, 2) NOT NULL,
    `payment_date` DATE NOT NULL,
    `payment_mode` VARCHAR(50),
    `reference_no` VARCHAR(100),
    `created_by` INT,
    FOREIGN KEY (`po_id`) REFERENCES `purchase_orders`(`id`)
) ENGINE=InnoDB;
