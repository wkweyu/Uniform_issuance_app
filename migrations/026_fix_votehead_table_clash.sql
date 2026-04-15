-- ============================================================================
-- Migration 026: Fix votehead table name clash with legacy voteheads
-- ============================================================================
-- The legacy "voteheads" table (fee voteheads) has a different schema.
-- Rename new payroll voteheads to "payroll_voteheads" to avoid conflict.

-- 1. Create the correct payroll_voteheads table
CREATE TABLE IF NOT EXISTS payroll_voteheads (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    school_id   INT NOT NULL,
    code        VARCHAR(30) NOT NULL,
    name        VARCHAR(100) NOT NULL,
    category    ENUM('salary','operations','capital','fees','other') DEFAULT 'other',
    is_active   TINYINT(1) DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_pvh (school_id, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Drop broken FK on finance_ledger_entries.votehead_id (may not exist)
-- The FK fk_ledger_votehead was supposed to reference voteheads(id) but that table has voteID PK
-- So this FK likely doesn't exist; safe to ignore error

-- 3. Add correct FK from finance_ledger_entries to payroll_voteheads
ALTER TABLE finance_ledger_entries
    ADD CONSTRAINT fk_ledger_payroll_votehead
    FOREIGN KEY (votehead_id) REFERENCES payroll_voteheads(id) ON DELETE SET NULL;

-- 4. Create payroll_votehead_allocations (failed in 025 due to FK clash)
CREATE TABLE IF NOT EXISTS payroll_votehead_allocations (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    payroll_line_id INT NOT NULL,
    votehead_id     INT NOT NULL,
    fund_id         INT NULL,
    amount          DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_pva_line (payroll_line_id),
    KEY idx_pva_votehead (votehead_id),
    CONSTRAINT fk_pva_line FOREIGN KEY (payroll_line_id) REFERENCES payroll_lines(id) ON DELETE CASCADE,
    CONSTRAINT fk_pva_votehead2 FOREIGN KEY (votehead_id) REFERENCES payroll_voteheads(id),
    CONSTRAINT fk_pva_fund FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Seed default payroll voteheads
INSERT INTO payroll_voteheads (school_id, code, name, category) VALUES
    (0, 'SAL_BASIC', 'Basic Salary', 'salary'),
    (0, 'SAL_ALLOW', 'Allowances', 'salary'),
    (0, 'SAL_EMPLOYER_STAT', 'Employer Statutory Contributions', 'salary'),
    (0, 'OPS_GENERAL', 'General Operations', 'operations'),
    (0, 'CAP_EQUIPMENT', 'Capital Equipment', 'capital')
ON DUPLICATE KEY UPDATE name = VALUES(name);
