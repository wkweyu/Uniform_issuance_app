-- Advanced Procurement Module Enhancements

-- 1. Inventory Categories & Stock Enhancements
-- Check if current_stock is enough, but adding category
ALTER TABLE item_stock ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'Uniform';
ALTER TABLE item_stock ADD COLUMN IF NOT EXISTS unit_of_measure VARCHAR(20) DEFAULT 'Pcs';

-- 2. Purchase Requisitions (Internal Staff Requests)
CREATE TABLE IF NOT EXISTS procurement_requisitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    req_number VARCHAR(20) UNIQUE NOT NULL, -- REQ-0001-26
    department_id INT,
    requested_by INT NOT NULL,
    request_date DATE NOT NULL,
    total_estimated_amount DECIMAL(15, 2) DEFAULT 0.00,
    status ENUM('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'CONVERTED_TO_PO') DEFAULT 'DRAFT',
    justification TEXT,
    approved_by INT,
    approved_at DATETIME,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (requested_by) REFERENCES users(userNo)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS procurement_requisition_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    requisition_id INT NOT NULL,
    description VARCHAR(255) NOT NULL,
    quantity DECIMAL(10, 2) NOT NULL,
    estimated_unit_price DECIMAL(15, 2) DEFAULT 0.00,
    item_id INT, -- Link to item_stock if known
    FOREIGN KEY (requisition_id) REFERENCES procurement_requisitions(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 3. Quotation Management (Comparison)
CREATE TABLE IF NOT EXISTS procurement_quotations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    requisition_id INT, -- Can link to REQ or be free
    supplier_id INT NOT NULL,
    quotation_reference VARCHAR(100),
    quotation_date DATE,
    amount DECIMAL(15, 2) NOT NULL,
    valid_until DATE,
    is_winner TINYINT(1) DEFAULT 0,
    notes TEXT,
    file_path VARCHAR(255),
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplierID),
    FOREIGN KEY (requisition_id) REFERENCES procurement_requisitions(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 4. Goods Received Notes (GRNs) - Supports Partial Deliveries
CREATE TABLE IF NOT EXISTS procurement_grns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    grn_number VARCHAR(20) UNIQUE NOT NULL, -- GRN-0001-26
    po_id INT NOT NULL,
    received_date DATE NOT NULL,
    received_by INT NOT NULL,
    delivery_note_ref VARCHAR(100),
    notes TEXT,
    file_path VARCHAR(255), -- Scan of delivery note
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (po_id) REFERENCES purchase_orders(id),
    FOREIGN KEY (received_by) REFERENCES users(userNo)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS procurement_grn_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    grn_id INT NOT NULL,
    po_item_id INT NOT NULL,
    quantity_received DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (grn_id) REFERENCES procurement_grns(id) ON DELETE CASCADE,
    FOREIGN KEY (po_item_id) REFERENCES purchase_order_items(id)
) ENGINE=InnoDB;

-- 5. Asset Management registry
CREATE TABLE IF NOT EXISTS assets_registry (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asset_name VARCHAR(255) NOT NULL,
    tag_number VARCHAR(100) UNIQUE,
    category VARCHAR(50), -- Furniture, Electronics, etc.
    purchase_date DATE,
    purchase_value DECIMAL(15, 2),
    location VARCHAR(100),
    condition_status ENUM('EXCELLENT', 'GOOD', 'FAIR', 'POOR', 'DISPOSED') DEFAULT 'EXCELLENT',
    assigned_to_staff_id INT,
    grn_item_id INT, -- Link back to procurement if bought recently
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 6. Departmental Budgets (Basic budgetary control)
CREATE TABLE IF NOT EXISTS procurement_budgets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    academic_year_id INT NOT NULL,
    category VARCHAR(50) NOT NULL, -- Stationery, Sports, etc.
    allocated_amount DECIMAL(15, 2) NOT NULL,
    spent_amount DECIMAL(15, 2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY (department_id, academic_year_id, category)
) ENGINE=InnoDB;
