-- Migration 029: Configurable statutory computation formulas
-- Allows schools to change HOW statutory deductions are computed,
-- not just the rates (which are already configurable).

CREATE TABLE IF NOT EXISTS payroll_statutory_formulas (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    school_id       INT NOT NULL,
    deduction_code  VARCHAR(30) NOT NULL,         -- PAYE, SHIF, NSSF, HOUSING_LEVY, TAXABLE_INCOME
    label           VARCHAR(100) NOT NULL,
    computation     ENUM('progressive_bands','flat_rate','tiered','formula') NOT NULL,
    -- For 'flat_rate': uses `flat_rate_expr` (e.g. "gross * 0.0275")
    -- For 'progressive_bands': uses bands from payroll_statutory_rates table
    -- For 'tiered': uses tiers from payroll_statutory_rates table
    -- For 'formula': uses `flat_rate_expr` as a free-form expression
    flat_rate_expr  VARCHAR(500) DEFAULT NULL,
    input_variable  VARCHAR(50) NOT NULL DEFAULT 'gross',  -- what variable feeds this computation
    employer_match  TINYINT(1) NOT NULL DEFAULT 0,         -- does employer pay same amount?
    employer_expr   VARCHAR(500) DEFAULT NULL,              -- if employer has different formula
    -- Taxable income: which deductions are subtracted before PAYE
    pre_tax_deductions TEXT DEFAULT NULL,                    -- JSON array e.g. ["shif","nssf_ee","housing_levy_ee"]
    -- Caps
    pension_cap     DECIMAL(15,2) DEFAULT 30000.00,
    mortgage_cap    DECIMAL(15,2) DEFAULT 30000.00,
    personal_relief DECIMAL(15,2) DEFAULT 2400.00,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_school_deduction (school_id, deduction_code),
    INDEX idx_psf_school (school_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
