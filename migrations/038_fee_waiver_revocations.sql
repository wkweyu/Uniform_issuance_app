-- Link each waiver assignment to its original ledger credit so revocations can
-- be posted as immutable debit adjustments instead of changing history.
ALTER TABLE student_waivers
    ADD COLUMN IF NOT EXISTS ledger_id INT NULL,
    ADD COLUMN IF NOT EXISTS revoked_by INT NULL,
    ADD COLUMN IF NOT EXISTS revoked_at DATETIME NULL,
    ADD COLUMN IF NOT EXISTS revocation_reason VARCHAR(500) NULL;

CREATE INDEX IF NOT EXISTS idx_student_waivers_ledger_school
    ON student_waivers (ledger_id, school_id);