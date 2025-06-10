-- uniform_term_dates
CREATE TABLE IF NOT EXISTS `uniform_term_dates` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `term_number` INT(11) NOT NULL,
  `year` INT(11) NOT NULL,
  `start_date` DATE NOT NULL,
  `end_date` DATE NOT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';

-- uniform_receipts
CREATE TABLE IF NOT EXISTS `uniform_receipts` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `AdmNo` VARCHAR(20) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `student_name` VARCHAR(255) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `class_name` VARCHAR(255) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `item_name` VARCHAR(255) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `price` DECIMAL(10,2) DEFAULT NULL,
  `quantity` INT(11) DEFAULT NULL,
  `total` DECIMAL(10,2) DEFAULT NULL,
  `yr` INT(11) DEFAULT NULL,
  `term` INT(11) DEFAULT NULL,
  `issued_on` DATETIME DEFAULT current_timestamp(),
  `receipt_no` VARCHAR(20) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `issued_by` VARCHAR(50) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';

-- uniform_prices
CREATE TABLE IF NOT EXISTS `uniform_prices` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `class_group` VARCHAR(50) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `item_name` VARCHAR(100) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `price` DECIMAL(10,2) DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `unique_price` (`item_name`,`class_group`)
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';

-- service_records
CREATE TABLE IF NOT EXISTS `service_records` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `bus_id` INT(11) DEFAULT NULL,
  `service_date` DATE NOT NULL,
  `service_type` VARCHAR(100) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `description` TEXT DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `cost` DECIMAL(10,2) DEFAULT NULL,
  `garage_name` VARCHAR(255) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `mileage_at_service` INT(11) DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `bus_id` (`bus_id`),
  CONSTRAINT `service_records_ibfk_1` FOREIGN KEY (`bus_id`) REFERENCES `buses` (`id`) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';

-- oil_records
CREATE TABLE IF NOT EXISTS `oil_records` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `bus_id` INT(11) DEFAULT NULL,
  `date` DATE NOT NULL,
  `description` VARCHAR(255) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `litres` DECIMAL(10,2) DEFAULT NULL,
  `unit_price` DECIMAL(10,2) DEFAULT NULL,
  `total_amount` DECIMAL(10,2) DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `bus_id` (`bus_id`),
  CONSTRAINT `oil_records_ibfk_1` FOREIGN KEY (`bus_id`) REFERENCES `buses` (`id`) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';

-- fuel_vouchers
CREATE TABLE IF NOT EXISTS `fuel_vouchers` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `voucher_no` VARCHAR(50) NOT NULL COLLATE 'latin1_swedish_ci',
  `bus_id` INT(11) NOT NULL,
  `litres` DECIMAL(10,2) DEFAULT NULL,
  `cost_per_litre` DECIMAL(10,2) DEFAULT NULL,
  `total_cost` DECIMAL(10,2) DEFAULT NULL,
  `issued_by` VARCHAR(50) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `remarks` TEXT DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `issued_on` DATETIME DEFAULT current_timestamp(),
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `voucher_no` (`voucher_no`),
  KEY `bus_id` (`bus_id`),
  CONSTRAINT `fuel_vouchers_ibfk_1` FOREIGN KEY (`bus_id`) REFERENCES `buses` (`id`) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';

-- fuel_invoices
CREATE TABLE IF NOT EXISTS `fuel_invoices` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `voucher_id` INT(11) DEFAULT NULL,
  `date` DATE NOT NULL,
  `actual_litres` DECIMAL(10,2) DEFAULT NULL,
  `amount_paid` DECIMAL(10,2) DEFAULT NULL,
  `petrol_station` VARCHAR(255) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `odometer_reading` INT(11) DEFAULT NULL,
  `remarks` VARCHAR(255) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `voucher_id` (`voucher_id`),
  CONSTRAINT `fuel_invoices_ibfk_1` FOREIGN KEY (`voucher_id`) REFERENCES `fuel_vouchers` (`id`) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';

-- classes
CREATE TABLE IF NOT EXISTS `classes` (
  `classID` INT(11) NOT NULL,
  `class_name` VARCHAR(50) NOT NULL COLLATE 'latin1_swedish_ci',
  PRIMARY KEY (`classID`) USING BTREE
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';

-- buses
CREATE TABLE IF NOT EXISTS `buses` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `reg_no` VARCHAR(20) NOT NULL COLLATE 'latin1_swedish_ci',
  `make` VARCHAR(50) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `capacity` INT(11) DEFAULT NULL,
  `driver_name` VARCHAR(50) DEFAULT NULL COLLATE 'latin1_swedish_ci',
  `current_mileage` INT(11) DEFAULT '0',
  `active` TINYINT(1) DEFAULT '1',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `reg_no` (`reg_no`)
) ENGINE=InnoDB COLLATE='latin1_swedish_ci';
