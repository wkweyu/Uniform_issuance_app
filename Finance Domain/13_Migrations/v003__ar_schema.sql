-- MIG-FIN-003 | CAP-FIN-003 Accounts Receivable
-- Wave-1 | Additive schema + Dual-write | 2026-07-22

CREATE TABLE IF NOT EXISTS fin_ar_ledger_entries (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    admno           VARCHAR(50)     NOT NULL,
    entry_type      VARCHAR(20)     NOT NULL COMMENT 'debit|credit',
    source_type     VARCHAR(30)     NOT NULL COMMENT 'invoice|payment|reversal|adjustment',
    source_id       BIGINT UNSIGNED NOT NULL,
    votehead_id     BIGINT UNSIGNED NOT NULL,
    amount          DECIMAL(15,2)   NOT NULL,
    entry_date      DATE            NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    term_id         BIGINT UNSIGNED NOT NULL,
    posted_by       BIGINT UNSIGNED NOT NULL,
    posted_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reversal_of     BIGINT UNSIGNED NULL COMMENT 'FK to parent entry if this is a reversal',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ar_admno_term   (tenant_id, admno, term_id),
    INDEX idx_ar_entry_date   (tenant_id, entry_date),
    CONSTRAINT fk_ar_votehead FOREIGN KEY (votehead_id)    REFERENCES fin_voteheads(id),
    CONSTRAINT fk_ar_year     FOREIGN KEY (academic_year_id) REFERENCES fin_academic_years(id),
    CONSTRAINT fk_ar_term     FOREIGN KEY (term_id)         REFERENCES fin_terms(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_allocation_entries (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    payment_id      BIGINT UNSIGNED NOT NULL COMMENT 'FK to fin_payment_transactions.id',
    invoice_id      BIGINT UNSIGNED NOT NULL,
    invoice_line_id BIGINT UNSIGNED NULL,
    allocated_amount DECIMAL(15,2)  NOT NULL,
    allocation_date DATE            NOT NULL,
    allocated_by    BIGINT UNSIGNED NOT NULL,
    is_manual       TINYINT(1)      NOT NULL DEFAULT 0,
    reversal_of     BIGINT UNSIGNED NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_alloc_payment  (tenant_id, payment_id),
    INDEX idx_alloc_invoice  (tenant_id, invoice_id),
    CONSTRAINT fk_alloc_invoice FOREIGN KEY (invoice_id) REFERENCES fin_invoice_headers(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_statement_snapshots (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    admno           VARCHAR(50)     NOT NULL,
    from_date       DATE            NOT NULL,
    to_date         DATE            NOT NULL,
    opening_balance DECIMAL(15,2)   NOT NULL,
    closing_balance DECIMAL(15,2)   NOT NULL,
    generated_by    BIGINT UNSIGNED NOT NULL,
    generated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    statement_hash  VARCHAR(64)     NOT NULL,
    UNIQUE KEY uq_statement_hash (tenant_id, statement_hash)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_aging_bucket_summaries (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    admno           VARCHAR(50)     NOT NULL,
    as_of_date      DATE            NOT NULL,
    bucket_current  DECIMAL(15,2)   NOT NULL DEFAULT 0,
    bucket_30       DECIMAL(15,2)   NOT NULL DEFAULT 0,
    bucket_60       DECIMAL(15,2)   NOT NULL DEFAULT 0,
    bucket_90       DECIMAL(15,2)   NOT NULL DEFAULT 0,
    bucket_over_90  DECIMAL(15,2)   NOT NULL DEFAULT 0,
    total_outstanding DECIMAL(15,2) NOT NULL DEFAULT 0,
    computed_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_aging_admno_date (tenant_id, admno, as_of_date)
) ENGINE=InnoDB;
