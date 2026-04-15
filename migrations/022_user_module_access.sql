-- User-level module access control
-- Each row grants a school user access to a specific module.
-- Users with NO entries are blocked from all modules (except super-admin TA=2).

CREATE TABLE IF NOT EXISTS user_module_access (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    school_id INT NOT NULL,
    module_code VARCHAR(50) NOT NULL,
    can_write BOOLEAN NOT NULL DEFAULT TRUE,
    granted_by INT NULL,
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_module (user_id, school_id, module_code),
    INDEX idx_uma_school (school_id),
    INDEX idx_uma_user_school (user_id, school_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
