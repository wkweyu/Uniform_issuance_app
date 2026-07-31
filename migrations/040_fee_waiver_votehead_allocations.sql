-- Migration 040: Preserve the exact votehead credits created by a fee waiver.
-- Each row is linked to its original credit and (on revocation) its debit reversal.
ALTER TABLE student_waivers
    ADD COLUMN IF NOT EXISTS allocation_mode VARCHAR(20) NOT NULL DEFAULT 'SINGLE';

CREATE TABLE IF NOT EXISTS fee_waiver_allocations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    waiver_id INT NOT NULL,
    votehead_id INT NOT NULL,
    ledger_id INT NOT NULL,
    revocation_ledger_id INT NULL,
    amount DECIMAL(15, 2) NOT NULL,
    school_id INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_fee_waiver_allocation_votehead (waiver_id, votehead_id, school_id),
    KEY idx_fee_waiver_allocations_school_waiver (school_id, waiver_id),
    KEY idx_fee_waiver_allocations_school_ledger (school_id, ledger_id),
    CONSTRAINT fk_fee_waiver_allocations_waiver FOREIGN KEY (waiver_id) REFERENCES student_waivers(id),
    CONSTRAINT fk_fee_waiver_allocations_votehead FOREIGN KEY (votehead_id) REFERENCES fee_voteheads(id),
    CONSTRAINT fk_fee_waiver_allocations_ledger FOREIGN KEY (ledger_id) REFERENCES fee_ledger(id),
    CONSTRAINT fk_fee_waiver_allocations_revocation_ledger FOREIGN KEY (revocation_ledger_id) REFERENCES fee_ledger(id)
) ENGINE=InnoDB;