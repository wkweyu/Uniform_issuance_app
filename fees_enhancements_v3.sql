-- 1. Waiver Categories (e.g. Staff 50%, Charity 100%, Sports 20%)
CREATE TABLE IF NOT EXISTS `fee_waiver_categories` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(100) NOT NULL UNIQUE,
    `discount_type` ENUM('PERCENTAGE', 'FIXED') NOT NULL,
    `value` DECIMAL(15, 2) NOT NULL,
    `is_active` BOOLEAN DEFAULT TRUE,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 2. Student Waiver Assignments
CREATE TABLE IF NOT EXISTS `student_waivers` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `admno` INT NOT NULL,
    `category_id` INT NOT NULL,
    `academic_year_id` INT NOT NULL,
    `term_id` INT NOT NULL,
    `status` ENUM('ACTIVE', 'EXPIRED', 'REVOKED') DEFAULT 'ACTIVE',
    `assigned_by` INT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`admno`) REFERENCES `studentinfo`(`AdmNo`),
    FOREIGN KEY (`category_id`) REFERENCES `fee_waiver_categories`(`id`),
    FOREIGN KEY (`academic_year_id`) REFERENCES `academic_years`(`id`)
) ENGINE=InnoDB;

-- 3. M-Pesa Reference Verification Cache (Mocking a real integration)
CREATE TABLE IF NOT EXISTS `mpesa_verifications` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `transaction_no` VARCHAR(50) UNIQUE NOT NULL,
    `amount` DECIMAL(15, 2) NOT NULL,
    `sender_name` VARCHAR(100),
    `sender_phone` VARCHAR(20),
    `transaction_time` DATETIME,
    `is_used` BOOLEAN DEFAULT FALSE,
    `used_for_admno` INT,
    `verified_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Initial Waiver data
INSERT IGNORE INTO `fee_waiver_categories` (name, discount_type, value) VALUES 
('Full Scholarship', 'PERCENTAGE', 100.00),
('Partial Scholarship (50%)', 'PERCENTAGE', 50.00),
('Staff Child Discount', 'PERCENTAGE', 25.00),
('Bursary Award', 'FIXED', 5000.00),
('Needy Student Waiver', 'FIXED', 2000.00);
