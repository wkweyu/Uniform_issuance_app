-- Migration 030: Payroll Payment Vouchers
-- Table for payroll-specific payment vouchers, one per votehead/statutory body per run

CREATE TABLE IF NOT EXISTS payroll_payment_vouchers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    school_id INT NOT NULL,
    run_id INT NOT NULL,
    voucher_no VARCHAR(30) NOT NULL,
    votehead_id INT NOT NULL,
    fund_id INT NULL,
    payee_type ENUM('net_salary','paye','nssf','shif','housing_levy','other_deductions') NOT NULL,
    payee_name VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    gross_amount DECIMAL(15,2) NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    payment_mode ENUM('BANK_TRANSFER','CHEQUE','CASH','MPESA') DEFAULT 'BANK_TRANSFER',
    status ENUM('draft','verified','authorized','paid','cancelled') DEFAULT 'draft',
    verified_by INT NULL,
    verified_at DATETIME NULL,
    authorized_by INT NULL,
    authorized_at DATETIME NULL,
    created_by INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_voucher_no (school_id, voucher_no),
    KEY idx_ppv_run (run_id),
    KEY idx_ppv_votehead (votehead_id),
    KEY idx_ppv_type (payee_type),
    CONSTRAINT fk_ppv_votehead FOREIGN KEY (votehead_id) REFERENCES payroll_voteheads(id),
    CONSTRAINT fk_ppv_fund FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
