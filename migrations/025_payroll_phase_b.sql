-- ============================================================================
-- Migration 025: Payroll Phase B — Voteheads, Funds, Payments, Bulk Ops
-- ============================================================================

-- ---------------------------------------------------------------------------
-- B1: GL Votehead Extension
-- ---------------------------------------------------------------------------

-- Add votehead_id to finance_ledger_entries (nullable — backward compatible)
ALTER TABLE finance_ledger_entries
    ADD COLUMN votehead_id INT NULL AFTER note;

-- General voteheads table (school-scoped, not just fees)
CREATE TABLE IF NOT EXISTS voteheads (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    school_id   INT NOT NULL,
    code        VARCHAR(30) NOT NULL,
    name        VARCHAR(100) NOT NULL,
    category    ENUM('salary','operations','capital','fees','other') DEFAULT 'other',
    is_active   TINYINT(1) DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_votehead (school_id, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- FK from ledger entries to voteheads
ALTER TABLE finance_ledger_entries
    ADD CONSTRAINT fk_ledger_votehead
    FOREIGN KEY (votehead_id) REFERENCES voteheads(id) ON DELETE SET NULL;

-- Payroll votehead allocations (split payroll line amounts by votehead)
CREATE TABLE IF NOT EXISTS payroll_votehead_allocations (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    payroll_line_id INT NOT NULL,
    votehead_id     INT NOT NULL,
    amount          DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_pva_line (payroll_line_id),
    KEY idx_pva_votehead (votehead_id),
    CONSTRAINT fk_pva_line FOREIGN KEY (payroll_line_id) REFERENCES payroll_lines(id) ON DELETE CASCADE,
    CONSTRAINT fk_pva_votehead FOREIGN KEY (votehead_id) REFERENCES voteheads(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------------
-- B2: IPSAS Fund Reporting
-- ---------------------------------------------------------------------------

-- Funds master table
CREATE TABLE IF NOT EXISTS funds (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    school_id   INT NOT NULL,
    code        VARCHAR(30) NOT NULL,
    name        VARCHAR(100) NOT NULL,
    fund_type   ENUM('general','restricted','designated','capital') DEFAULT 'general',
    is_active   TINYINT(1) DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_fund (school_id, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Add fund_id to finance_ledger_entries (nullable)
ALTER TABLE finance_ledger_entries
    ADD COLUMN fund_id INT NULL AFTER votehead_id;

ALTER TABLE finance_ledger_entries
    ADD CONSTRAINT fk_ledger_fund
    FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE SET NULL;

-- Add fund_id to payroll_votehead_allocations
ALTER TABLE payroll_votehead_allocations
    ADD COLUMN fund_id INT NULL AFTER votehead_id;

ALTER TABLE payroll_votehead_allocations
    ADD CONSTRAINT fk_pva_fund
    FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE SET NULL;


-- ---------------------------------------------------------------------------
-- B3: Payment Batching & Bank Grouping
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS payroll_payments (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    run_id          INT NOT NULL,
    employee_id     INT NOT NULL,
    amount          DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    bank_name       VARCHAR(100),
    bank_branch     VARCHAR(100),
    bank_account    VARCHAR(50),
    payment_ref     VARCHAR(100),
    payment_date    DATE NULL,
    status          ENUM('pending','paid','failed') DEFAULT 'pending',
    batch_id        VARCHAR(50) NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_pp_run (run_id),
    KEY idx_pp_employee (employee_id),
    KEY idx_pp_batch (batch_id),
    CONSTRAINT fk_pp_run FOREIGN KEY (run_id) REFERENCES payroll_runs(id),
    CONSTRAINT fk_pp_employee FOREIGN KEY (employee_id) REFERENCES payroll_employees(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ---------------------------------------------------------------------------
-- Seed default voteheads for salary category
-- ---------------------------------------------------------------------------
-- These are inserted with school_id=0 as global templates (copied per school)
INSERT INTO voteheads (school_id, code, name, category) VALUES
    (0, 'SAL_BASIC', 'Basic Salary', 'salary'),
    (0, 'SAL_ALLOW', 'Allowances', 'salary'),
    (0, 'SAL_EMPLOYER_STAT', 'Employer Statutory Contributions', 'salary'),
    (0, 'OPS_GENERAL', 'General Operations', 'operations'),
    (0, 'CAP_EQUIPMENT', 'Capital Equipment', 'capital')
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- Seed default funds
INSERT INTO funds (school_id, code, name, fund_type) VALUES
    (0, 'GF', 'General Fund', 'general'),
    (0, 'GOV', 'Government Grants Fund', 'restricted'),
    (0, 'CAP', 'Capital Development Fund', 'capital'),
    (0, 'BOM', 'BOM Operations Fund', 'designated')
ON DUPLICATE KEY UPDATE name = VALUES(name);
