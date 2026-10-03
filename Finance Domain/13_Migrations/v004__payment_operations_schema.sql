-- MIG-FIN-004 | CAP-FIN-004 Payment Operations
-- Wave-1 | Additive schema + Dual-write | 2026-07-22

CREATE TABLE IF NOT EXISTS fin_payment_transactions (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    admno           VARCHAR(50)     NOT NULL,
    payment_method_id BIGINT UNSIGNED NOT NULL,
    rail            VARCHAR(30)     NOT NULL COMMENT 'CASH|BANK|MPESA|CARD|EFT',
    reference       VARCHAR(100)    NOT NULL,
    amount          DECIMAL(15,2)   NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                    COMMENT 'pending|accepted|rejected|reversed',
    received_at     DATETIME        NOT NULL,
    posted_by       BIGINT UNSIGNED NOT NULL,
    idempotency_key VARCHAR(200)    NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_idempotency (tenant_id, idempotency_key),
    INDEX idx_pmt_admno      (tenant_id, admno),
    INDEX idx_pmt_rail_ref   (tenant_id, rail, reference),
    CONSTRAINT fk_pmt_method FOREIGN KEY (payment_method_id) REFERENCES fin_payment_methods(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_payment_rail_references (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    payment_id      BIGINT UNSIGNED NOT NULL,
    provider        VARCHAR(50)     NOT NULL,
    provider_ref    VARCHAR(100)    NOT NULL,
    raw_payload     JSON            NULL,
    signature_valid TINYINT(1)      NULL,
    validated_at    DATETIME        NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_rail_provider_ref (tenant_id, provider, provider_ref),
    CONSTRAINT fk_rail_payment FOREIGN KEY (payment_id) REFERENCES fin_payment_transactions(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_reconciliation_cases (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    payment_id      BIGINT UNSIGNED NOT NULL,
    mismatch_type   VARCHAR(50)     NOT NULL COMMENT 'amount|reference|duplicate|unknown',
    mismatch_reason TEXT            NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'open'
                    COMMENT 'open|under-review|resolved|dismissed',
    assigned_to     BIGINT UNSIGNED NULL,
    resolved_by     BIGINT UNSIGNED NULL,
    resolved_at     DATETIME        NULL,
    resolution_note TEXT            NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_recon_status (tenant_id, status),
    CONSTRAINT fk_recon_payment FOREIGN KEY (payment_id) REFERENCES fin_payment_transactions(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_settlement_batches (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    bank_account_id BIGINT UNSIGNED NOT NULL,
    rail            VARCHAR(30)     NOT NULL,
    settlement_date DATE            NOT NULL,
    expected_amount DECIMAL(15,2)   NOT NULL,
    actual_amount   DECIMAL(15,2)   NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                    COMMENT 'pending|matched|mismatched|closed',
    closed_by       BIGINT UNSIGNED NULL,
    closed_at       DATETIME        NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_batch_bank FOREIGN KEY (bank_account_id) REFERENCES fin_bank_accounts(id)
) ENGINE=InnoDB;
