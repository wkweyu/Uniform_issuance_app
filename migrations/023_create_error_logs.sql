CREATE TABLE IF NOT EXISTS error_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    school_id INT NULL,
    user_id INT NULL,
    platform_user_id INT NULL,
    endpoint VARCHAR(255) NULL,
    method VARCHAR(10) NULL,
    error_message TEXT NOT NULL,
    stack_trace TEXT NULL,
    request_data JSON NULL,
    ip_address VARCHAR(64) NULL,
    user_agent VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_errorlogs_school (school_id),
    INDEX idx_errorlogs_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
