-- ============================================================================
-- Migration 024: Payroll Module
-- Kenyan-compliant payroll with PAYE, SHIF, NSSF, Housing Levy
-- All tables scoped by school_id for multi-tenancy
-- ============================================================================

-- 1. Employee payroll profiles
CREATE TABLE IF NOT EXISTS payroll_employees (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    staff_id        VARCHAR(12) NOT NULL,
    salary_source   ENUM('school','government','mixed') NOT NULL DEFAULT 'school',
    govt_salary_pct DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    basic_salary    DECIMAL(15,2) NOT NULL,
    kra_pin         VARCHAR(24) DEFAULT NULL,
    nhif_no         VARCHAR(20) DEFAULT NULL,
    nssf_no         VARCHAR(20) DEFAULT NULL,
    bank_name       VARCHAR(100) DEFAULT NULL,
    bank_branch     VARCHAR(100) DEFAULT NULL,
    bank_account    VARCHAR(50) DEFAULT NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    effective_from  DATE NOT NULL,
    created_by      INT DEFAULT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_school_staff (school_id, staff_id),
    INDEX idx_pe_school_active (school_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Employee salary change history (versioning)
CREATE TABLE IF NOT EXISTS payroll_employee_history (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    employee_id     INT NOT NULL,
    field_changed   VARCHAR(50) NOT NULL,
    old_value       VARCHAR(255) DEFAULT NULL,
    new_value       VARCHAR(255) DEFAULT NULL,
    effective_from  DATE DEFAULT NULL,
    changed_by      INT DEFAULT NULL,
    changed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_peh_employee (employee_id),
    CONSTRAINT fk_peh_employee FOREIGN KEY (employee_id) REFERENCES payroll_employees(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Payroll component catalog (earnings / deductions / statutory)
CREATE TABLE IF NOT EXISTS payroll_components (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    school_id        INT NOT NULL,
    name             VARCHAR(100) NOT NULL,
    code             VARCHAR(30) NOT NULL,
    type             ENUM('earning','deduction','statutory') NOT NULL,
    calculation_type ENUM('fixed','percentage','formula','manual') NOT NULL DEFAULT 'fixed',
    is_taxable       TINYINT(1) NOT NULL DEFAULT 0,
    is_statutory     TINYINT(1) NOT NULL DEFAULT 0,
    sort_order       INT NOT NULL DEFAULT 0,
    is_active        TINYINT(1) NOT NULL DEFAULT 1,
    UNIQUE KEY uq_school_code (school_id, code),
    INDEX idx_pc_school (school_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Per-employee component configuration
CREATE TABLE IF NOT EXISTS payroll_employee_components (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    employee_id     INT NOT NULL,
    component_id    INT NOT NULL,
    amount          DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    is_percent      TINYINT(1) NOT NULL DEFAULT 0,
    mode            ENUM('auto','manual','override') NOT NULL DEFAULT 'auto',
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    UNIQUE KEY uq_emp_comp (employee_id, component_id),
    CONSTRAINT fk_pec_employee FOREIGN KEY (employee_id) REFERENCES payroll_employees(id) ON DELETE CASCADE,
    CONSTRAINT fk_pec_component FOREIGN KEY (component_id) REFERENCES payroll_components(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Configurable statutory rate bands
CREATE TABLE IF NOT EXISTS payroll_statutory_rates (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    rate_type       ENUM('paye','shif','nssf_employee','nssf_employer',
                         'housing_levy_employee','housing_levy_employer',
                         'personal_relief') NOT NULL,
    band_from       DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    band_to         DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    rate            DECIMAL(8,5) NOT NULL DEFAULT 0.00000,
    fixed_amount    DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    effective_from  DATE NOT NULL,
    effective_to    DATE DEFAULT NULL,
    INDEX idx_psr_school_type (school_id, rate_type, effective_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. Payroll runs (monthly batches)
CREATE TABLE IF NOT EXISTS payroll_runs (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    school_id                   INT NOT NULL,
    pay_period                  VARCHAR(7) NOT NULL,
    status                      ENUM('draft','generated','approved','posted','reversed') NOT NULL DEFAULT 'draft',
    total_gross                 DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_net                   DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_paye                  DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_shif                  DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_nssf                  DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_housing_levy          DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_employer_nssf         DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_employer_housing_levy DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    gl_transaction_id           INT DEFAULT NULL,
    reversal_gl_transaction_id  INT DEFAULT NULL,
    is_reversed                 TINYINT(1) NOT NULL DEFAULT 0,
    reversal_of_id              INT DEFAULT NULL,
    generated_by                INT DEFAULT NULL,
    approved_by                 INT DEFAULT NULL,
    posted_by                   INT DEFAULT NULL,
    reversed_by                 INT DEFAULT NULL,
    created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    generated_at                DATETIME DEFAULT NULL,
    approved_at                 DATETIME DEFAULT NULL,
    posted_at                   DATETIME DEFAULT NULL,
    reversed_at                 DATETIME DEFAULT NULL,
    UNIQUE KEY uq_school_period (school_id, pay_period),
    INDEX idx_pr_school_status (school_id, status),
    CONSTRAINT fk_pr_reversal FOREIGN KEY (reversal_of_id) REFERENCES payroll_runs(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. Payroll lines (per-employee per-run detail)
CREATE TABLE IF NOT EXISTS payroll_lines (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    run_id                   INT NOT NULL,
    employee_id              INT NOT NULL,
    salary_source            ENUM('school','government','mixed') NOT NULL DEFAULT 'school',
    govt_salary_pct          DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    basic_salary             DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    gross_pay                DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    taxable_income           DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    paye                     DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    shif                     DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    nssf_employee            DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    nssf_employer            DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    housing_levy_employee    DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    housing_levy_employer    DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    total_deductions         DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    net_pay                  DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    breakdown_json           TEXT DEFAULT NULL,
    UNIQUE KEY uq_run_employee (run_id, employee_id),
    INDEX idx_pl_run (run_id),
    CONSTRAINT fk_pl_run FOREIGN KEY (run_id) REFERENCES payroll_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_pl_employee FOREIGN KEY (employee_id) REFERENCES payroll_employees(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. Payroll adjustments (bonuses, arrears, corrections)
CREATE TABLE IF NOT EXISTS payroll_adjustments (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    employee_id     INT NOT NULL,
    run_id          INT DEFAULT NULL,
    type            ENUM('earning','deduction') NOT NULL,
    name            VARCHAR(100) NOT NULL,
    amount          DECIMAL(15,2) NOT NULL,
    is_taxable      TINYINT(1) NOT NULL DEFAULT 0,
    is_recurring    TINYINT(1) NOT NULL DEFAULT 0,
    recur_until     DATE DEFAULT NULL,
    applied         TINYINT(1) NOT NULL DEFAULT 0,
    created_by      INT DEFAULT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes           TEXT DEFAULT NULL,
    INDEX idx_pa_school (school_id),
    INDEX idx_pa_employee_pending (employee_id, applied),
    CONSTRAINT fk_pa_employee FOREIGN KEY (employee_id) REFERENCES payroll_employees(id) ON DELETE CASCADE,
    CONSTRAINT fk_pa_run FOREIGN KEY (run_id) REFERENCES payroll_runs(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. Payroll audit logs (immutable)
CREATE TABLE IF NOT EXISTS payroll_audit_logs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    entity_type     VARCHAR(50) NOT NULL,
    entity_id       INT DEFAULT NULL,
    action          VARCHAR(50) NOT NULL,
    old_values      JSON DEFAULT NULL,
    new_values      JSON DEFAULT NULL,
    performed_by    INT NOT NULL,
    performed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address      VARCHAR(45) DEFAULT NULL,
    INDEX idx_pal_school (school_id),
    INDEX idx_pal_entity (entity_type, entity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. Payroll GL account mapping
CREATE TABLE IF NOT EXISTS payroll_gl_mapping (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    mapping_key     VARCHAR(50) NOT NULL,
    account_id      INT NOT NULL,
    UNIQUE KEY uq_school_mapping (school_id, mapping_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================================
-- SEED DATA: Kenyan statutory rates (Finance Act 2023, effective July 2023)
-- These are seeded per-school on first use by the service layer.
-- A school_id=0 row serves as the global template that gets copied.
-- ============================================================================

-- PAYE progressive bands (monthly)
INSERT IGNORE INTO payroll_statutory_rates (school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from) VALUES
(0, 'paye',       0.00,    24000.00,  10.00000, 0.00, '2023-07-01'),
(0, 'paye',   24000.01,    32333.00,  25.00000, 0.00, '2023-07-01'),
(0, 'paye',   32333.01,   500000.00,  30.00000, 0.00, '2023-07-01'),
(0, 'paye',  500000.01,   800000.00,  32.50000, 0.00, '2023-07-01'),
(0, 'paye',  800000.01, 99999999.99,  35.00000, 0.00, '2023-07-01');

-- Personal relief (monthly)
INSERT IGNORE INTO payroll_statutory_rates (school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from) VALUES
(0, 'personal_relief', 0.00, 0.00, 0.00000, 2400.00, '2023-07-01');

-- SHIF (2.75% of gross salary — SHA Act 2023, effective Oct 2024)
INSERT IGNORE INTO payroll_statutory_rates (school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from) VALUES
(0, 'shif', 0.00, 99999999.99, 2.75000, 0.00, '2024-10-01');

-- NSSF Tier I & II (employee contribution — 6% each tier)
INSERT IGNORE INTO payroll_statutory_rates (school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from) VALUES
(0, 'nssf_employee', 0.00,  7000.00, 6.00000, 0.00, '2024-02-01'),
(0, 'nssf_employee', 7000.01, 36000.00, 6.00000, 0.00, '2024-02-01');

-- NSSF employer contribution (matches employee)
INSERT IGNORE INTO payroll_statutory_rates (school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from) VALUES
(0, 'nssf_employer', 0.00,  7000.00, 6.00000, 0.00, '2024-02-01'),
(0, 'nssf_employer', 7000.01, 36000.00, 6.00000, 0.00, '2024-02-01');

-- Housing Levy (1.5% employee, 1.5% employer — Affordable Housing Act 2024)
INSERT IGNORE INTO payroll_statutory_rates (school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from) VALUES
(0, 'housing_levy_employee', 0.00, 99999999.99, 1.50000, 0.00, '2024-03-01');

INSERT IGNORE INTO payroll_statutory_rates (school_id, rate_type, band_from, band_to, rate, fixed_amount, effective_from) VALUES
(0, 'housing_levy_employer', 0.00, 99999999.99, 1.50000, 0.00, '2024-03-01');
