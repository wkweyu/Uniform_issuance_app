-- Fee Structure Expansion & Accounting Integration
USE schoolmngt;

-- 1. Student Groups (Categories like Day, Boarding, etc.)
CREATE TABLE IF NOT EXISTS fee_student_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    is_active TINYINT(1) DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed basic groups if empty
INSERT IGNORE INTO fee_student_groups (name) VALUES ('Day'), ('Boarding'), ('New Student'), ('Staff Child');

-- 2. Enhance Voteheads
ALTER TABLE fee_voteheads ADD COLUMN IF NOT EXISTS ledger_account_id VARCHAR(50) DEFAULT NULL AFTER applicable_student_group_id;
ALTER TABLE fee_voteheads ADD COLUMN IF NOT EXISTS is_active TINYINT(1) DEFAULT 1;

-- 3. Structure Locking (for read-only feature)
ALTER TABLE fee_structures ADD COLUMN IF NOT EXISTS is_locked TINYINT(1) DEFAULT 0;

-- 4. Invoicing History Mapping (to prevent duplicate structure applications)
-- (Already handled by index in app logic, but good to have a dedicated audit if needed)

-- Update studentinfo to use these groups (if needed, currently uses varchar category)
-- For now we'll match by name to preserve backward compatibility.
