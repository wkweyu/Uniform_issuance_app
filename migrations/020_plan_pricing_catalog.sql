ALTER TABLE plans
    ADD COLUMN IF NOT EXISTS bundle_family VARCHAR(32) NOT NULL DEFAULT 'combined' AFTER billing_period,
    ADD COLUMN IF NOT EXISTS pricing_model VARCHAR(32) NOT NULL DEFAULT 'student_band' AFTER bundle_family;

CREATE TABLE IF NOT EXISTS module_catalog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    family VARCHAR(32) NOT NULL,
    is_core BOOLEAN NOT NULL DEFAULT TRUE,
    is_addon BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_module_catalog_family (family),
    INDEX idx_module_catalog_active (is_active)
);

CREATE TABLE IF NOT EXISTS student_bands (
    id INT AUTO_INCREMENT PRIMARY KEY,
    label VARCHAR(64) NOT NULL UNIQUE,
    min_students INT NOT NULL,
    max_students INT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_student_bands_active (is_active)
);

CREATE TABLE IF NOT EXISTS plan_modules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plan_id INT NOT NULL,
    module_id INT NOT NULL,
    is_included BOOLEAN NOT NULL DEFAULT TRUE,
    addon_price_cents INT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_plan_modules_plan FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
    CONSTRAINT fk_plan_modules_module FOREIGN KEY (module_id) REFERENCES module_catalog(id) ON DELETE CASCADE,
    CONSTRAINT uq_plan_module UNIQUE (plan_id, module_id)
);

CREATE TABLE IF NOT EXISTS plan_band_prices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plan_id INT NOT NULL,
    student_band_id INT NOT NULL,
    price_cents INT NOT NULL DEFAULT 0,
    currency VARCHAR(16) NOT NULL DEFAULT 'KES',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_plan_band_prices_plan FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
    CONSTRAINT fk_plan_band_prices_band FOREIGN KEY (student_band_id) REFERENCES student_bands(id) ON DELETE CASCADE,
    CONSTRAINT uq_plan_band_price UNIQUE (plan_id, student_band_id)
);

INSERT IGNORE INTO module_catalog (code, name, family, is_core, is_addon, sort_order) VALUES
('students', 'Students Management', 'academic', TRUE, FALSE, 10),
('classes', 'Classes And Streams', 'academic', TRUE, FALSE, 20),
('exams', 'Exams And Grading', 'academic', TRUE, FALSE, 30),
('attendance', 'Attendance Tracking', 'academic', TRUE, FALSE, 40),
('fees', 'Fees Collection And Management', 'accounting', TRUE, FALSE, 50),
('finance', 'Financial Accounting', 'accounting', TRUE, FALSE, 60),
('inventory_uniform', 'Inventory And Uniform Issuance', 'operations', FALSE, TRUE, 70),
('procurement_assets', 'Procurement And Assets', 'operations', FALSE, TRUE, 80),
('fleet_transport', 'Fleet And Transport', 'operations', FALSE, TRUE, 90),
('farm_operations', 'Farm Operations', 'operations', FALSE, TRUE, 100);

INSERT IGNORE INTO student_bands (label, min_students, max_students, sort_order) VALUES
('1-300', 1, 300, 10),
('301-700', 301, 700, 20),
('701-1500', 701, 1500, 30),
('1500+', 1501, NULL, 40);

UPDATE plans SET bundle_family = COALESCE(bundle_family, 'combined'), pricing_model = COALESCE(pricing_model, 'student_band');

INSERT IGNORE INTO plan_band_prices (plan_id, student_band_id, price_cents, currency)
SELECT p.id, sb.id, p.price_cents, 'KES'
FROM plans p
CROSS JOIN student_bands sb;