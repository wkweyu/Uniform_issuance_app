-- MIG-FIN-005 | CAP-FIN-007 General Ledger
-- Wave-1 | Additive schema + Dual-write | 2026-07-22

CREATE TABLE IF NOT EXISTS fin_account_master (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    account_code    VARCHAR(20)     NOT NULL,
    account_name    VARCHAR(100)    NOT NULL,
    account_type    VARCHAR(20)     NOT NULL COMMENT 'asset|liability|equity|income|expense',
    parent_id       BIGINT UNSIGNED NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_account_code (tenant_id, account_code),
    CONSTRAINT fk_account_parent FOREIGN KEY (parent_id) REFERENCES fin_account_master(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_journal_headers (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    journal_no      VARCHAR(50)     NOT NULL,
    source_type     VARCHAR(30)     NOT NULL COMMENT 'payment|reversal|billing|adjustment|manual',
    source_event_id VARCHAR(100)    NOT NULL COMMENT 'idempotency key of originating event',
    academic_year_id BIGINT UNSIGNED NOT NULL,
    term_id         BIGINT UNSIGNED NOT NULL,
    posting_date    DATE            NOT NULL,
    debit_total     DECIMAL(15,2)   NOT NULL,
    credit_total    DECIMAL(15,2)   NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'posted'
                    COMMENT 'posted|reversed',
    reversed_by     BIGINT UNSIGNED NULL COMMENT 'FK to reversal journal',
    posted_by       BIGINT UNSIGNED NOT NULL,
    posted_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_journal_no      (tenant_id, journal_no),
    UNIQUE KEY uq_source_event    (tenant_id, source_type, source_event_id),
    INDEX idx_journal_date        (tenant_id, posting_date),
    CONSTRAINT fk_jh_year FOREIGN KEY (academic_year_id) REFERENCES fin_academic_years(id),
    CONSTRAINT fk_jh_term FOREIGN KEY (term_id)          REFERENCES fin_terms(id),
    -- Enforce double-entry balance
    CONSTRAINT chk_journal_balance CHECK (debit_total = credit_total)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_journal_lines (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    journal_id      BIGINT UNSIGNED NOT NULL,
    account_id      BIGINT UNSIGNED NOT NULL,
    entry_type      CHAR(2)         NOT NULL COMMENT 'DR|CR',
    amount          DECIMAL(15,2)   NOT NULL,
    description     VARCHAR(255)    NULL,
    admno           VARCHAR(50)     NULL COMMENT 'optional student reference',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_jl_header  FOREIGN KEY (journal_id) REFERENCES fin_journal_headers(id),
    CONSTRAINT fk_jl_account FOREIGN KEY (account_id) REFERENCES fin_account_master(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_trial_balance_snapshots (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    term_id         BIGINT UNSIGNED NULL,
    from_date       DATE            NOT NULL,
    to_date         DATE            NOT NULL,
    account_id      BIGINT UNSIGNED NOT NULL,
    total_debit     DECIMAL(15,2)   NOT NULL DEFAULT 0,
    total_credit    DECIMAL(15,2)   NOT NULL DEFAULT 0,
    closing_balance DECIMAL(15,2)   NOT NULL DEFAULT 0,
    generated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tb_year_account (tenant_id, academic_year_id, account_id),
    CONSTRAINT fk_tb_account FOREIGN KEY (account_id) REFERENCES fin_account_master(id),
    CONSTRAINT fk_tb_year    FOREIGN KEY (academic_year_id) REFERENCES fin_academic_years(id)
) ENGINE=InnoDB;
