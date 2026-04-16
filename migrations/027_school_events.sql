-- ============================================================================
-- Migration 027: School Events Calendar
-- ============================================================================

CREATE TABLE IF NOT EXISTS school_events (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    school_id   INT NOT NULL,
    title       VARCHAR(200) NOT NULL,
    description TEXT,
    event_date  DATE NOT NULL,
    end_date    DATE NULL,
    event_type  ENUM('academic','holiday','deadline','meeting','other') DEFAULT 'other',
    created_by  INT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_se_school_date (school_id, event_date),
    CONSTRAINT fk_se_school FOREIGN KEY (school_id) REFERENCES schools(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
