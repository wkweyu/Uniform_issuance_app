-- 📦 Term management
CREATE TABLE IF NOT EXISTS uniform_term_dates (
  id INT PRIMARY KEY AUTO_INCREMENT,
  term INT NOT NULL,
  year INT NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL
);

-- 📦 Student records (if not already existing in your main DB)
CREATE TABLE IF NOT EXISTS studentinfo (
  AdmNo VARCHAR(20) PRIMARY KEY,
  FName VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS classallocation (
  id INT PRIMARY KEY AUTO_INCREMENT,
  AdmNo VARCHAR(20),
  classID INT,
  thisYear INT,
  FOREIGN KEY (AdmNo) REFERENCES studentinfo(AdmNo)
);

CREATE TABLE IF NOT EXISTS classes (
  classID INT PRIMARY KEY AUTO_INCREMENT,
  class_name VARCHAR(50)
);

-- 📦 Uniform price management
CREATE TABLE IF NOT EXISTS uniform_prices (
  id INT PRIMARY KEY AUTO_INCREMENT,
  item_name VARCHAR(255),
  class_group VARCHAR(255),
  price DECIMAL(10,2),
  UNIQUE KEY (item_name, class_group)
);

-- 📦 Uniform issuance records
CREATE TABLE IF NOT EXISTS uniform_receipts (
  id INT PRIMARY KEY AUTO_INCREMENT,
  AdmNo VARCHAR(20),
  student_name VARCHAR(255),
  class_name VARCHAR(255),
  item_name VARCHAR(255),
  price DECIMAL(10,2),
  quantity INT,
  total DECIMAL(10,2),
  yr INT,
  term INT,
  issued_on DATETIME DEFAULT CURRENT_TIMESTAMP,
  receipt_no VARCHAR(20),
  issued_by VARCHAR(50)
);

-- 📦 Student ledger (debts)
CREATE TABLE IF NOT EXISTS fodebit (
  id INT PRIMARY KEY AUTO_INCREMENT,
  AdmNo VARCHAR(20),
  yr INT,
  term INT,
  r_for VARCHAR(50),
  amount DECIMAL(10,2),
  state INT,
  _date DATETIME DEFAULT CURRENT_TIMESTAMP,
  acc INT,
  cmode VARCHAR(50),
  ccode VARCHAR(50)
);

-- ===========================
-- 📦 NEW: Bus Management
-- ===========================

-- 📦 Buses master list
CREATE TABLE IF NOT EXISTS buses (
  id INT PRIMARY KEY AUTO_INCREMENT,
  reg_no VARCHAR(20) UNIQUE NOT NULL,
  make VARCHAR(50),
  capacity INT,
  driver_name VARCHAR(50),
  current_mileage INT DEFAULT 0
);

-- 📦 Fuel purchase vouchers (before fueling happens)
CREATE TABLE IF NOT EXISTS fuel_vouchers (
  id INT PRIMARY KEY AUTO_INCREMENT,
  bus_id INT,
  date DATE NOT NULL,
  litres DECIMAL(10,2),
  unit_price DECIMAL(10,2),
  total_amount DECIMAL(10,2),
  issued_by VARCHAR(50),
  status VARCHAR(20) DEFAULT 'Pending',
  FOREIGN KEY (bus_id) REFERENCES buses(id)
);

-- 📦 Fuel invoices (after fueling completed)
CREATE TABLE IF NOT EXISTS fuel_invoices (
  id INT PRIMARY KEY AUTO_INCREMENT,
  voucher_id INT,
  date DATE NOT NULL,
  actual_litres DECIMAL(10,2),
  amount_paid DECIMAL(10,2),
  petrol_station VARCHAR(255),
  FOREIGN KEY (voucher_id) REFERENCES fuel_vouchers(id)
);

-- 📦 Service & maintenance records
CREATE TABLE IF NOT EXISTS service_records (
  id INT PRIMARY KEY AUTO_INCREMENT,
  bus_id INT,
  service_date DATE NOT NULL,
  service_type VARCHAR(100),
  description TEXT,
  cost DECIMAL(10,2),
  garage_name VARCHAR(255),
  mileage_at_service INT,
  FOREIGN KEY (bus_id) REFERENCES buses(id)
);

-- 📦 Oil purchase records
CREATE TABLE IF NOT EXISTS oil_records (
  id INT PRIMARY KEY AUTO_INCREMENT,
  bus_id INT,
  date DATE NOT NULL,
  description VARCHAR(255),
  litres DECIMAL(10,2),
  unit_price DECIMAL(10,2),
  total_amount DECIMAL(10,2),
  FOREIGN KEY (bus_id) REFERENCES buses(id)
);
