-- ERP Audit Compliance Migration
-- Date: 2026-02-01

-- 1. Audit Records Table
CREATE TABLE IF NOT EXISTS audit_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    table_name VARCHAR(50) NOT NULL,
    record_id INT NOT NULL,
    action ENUM('INSERT', 'UPDATE', 'DELETE') NOT NULL,
    changes JSON,
    user_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (table_name, record_id),
    INDEX (user_id)
);

-- 2. Budgeting Table
CREATE TABLE IF NOT EXISTS finance_budgets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    fiscal_year INT NOT NULL,
    annual_amount DECIMAL(15,2) NOT NULL,
    spent_amount DECIMAL(15,2) DEFAULT 0.00,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY (account_id, fiscal_year)
);

-- 3. Update Suppliers
ALTER TABLE suppliers 
ADD COLUMN IF NOT EXISTS credit_limit DECIMAL(15,2) DEFAULT 0.00;

-- 4. Update Ledger Entries for Reconciliation
ALTER TABLE finance_ledger_entries 
ADD COLUMN IF NOT EXISTS is_reconciled BOOLEAN DEFAULT FALSE;

-- 5. Update Payment Vouchers for 3-Tier Workflow and Taxation
-- First, map old 'APPROVED' status to 'PENDING_PAYMENT' to avoid truncation
UPDATE finance_payment_vouchers SET status = 'DRAFT' WHERE status = 'APPROVED';

ALTER TABLE finance_payment_vouchers 
MODIFY COLUMN status ENUM('DRAFT', 'PENDING_VERIFICATION', 'PENDING_PAYMENT', 'PAID', 'CANCELLED') DEFAULT 'DRAFT',
ADD COLUMN IF NOT EXISTS verified_by INT DEFAULT NULL,
ADD COLUMN IF NOT EXISTS authorized_by INT DEFAULT NULL,
ADD COLUMN IF NOT EXISTS gross_amount DECIMAL(15,2) DEFAULT 0.00,
ADD COLUMN IF NOT EXISTS vat_amount DECIMAL(15,2) DEFAULT 0.00,
ADD COLUMN IF NOT EXISTS withholding_tax DECIMAL(15,2) DEFAULT 0.00,
ADD COLUMN IF NOT EXISTS attachment_path VARCHAR(255) DEFAULT NULL;
