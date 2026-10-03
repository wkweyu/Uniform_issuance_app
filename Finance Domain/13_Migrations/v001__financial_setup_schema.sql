-- MIG-FIN-001 | CAP-FIN-001 Financial Setup
-- Wave-1 | Additive schema | 2026-07-22

CREATE TABLE IF NOT EXISTS fin_academic_years (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    year_label      VARCHAR(20)     NOT NULL,
    start_date      DATE            NOT NULL,
    end_date        DATE            NOT NULL,
    is_current      TINYINT(1)      NOT NULL DEFAULT 0,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ay_tenant_label (tenant_id, year_label)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_terms (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    term_number     TINYINT UNSIGNED NOT NULL,
    start_date      DATE            NOT NULL,
    end_date        DATE            NOT NULL,
    is_current      TINYINT(1)      NOT NULL DEFAULT 0,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_term_year_num (tenant_id, academic_year_id, term_number),
    CONSTRAINT fk_term_year FOREIGN KEY (academic_year_id) REFERENCES fin_academic_years(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_fee_categories (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    code            VARCHAR(50)     NOT NULL,
    name            VARCHAR(100)    NOT NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_feecategory_code (tenant_id, code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_voteheads (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    code            VARCHAR(50)     NOT NULL,
    name            VARCHAR(100)    NOT NULL,
    fee_category_id BIGINT UNSIGNED NOT NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_votehead_code (tenant_id, code),
    CONSTRAINT fk_votehead_category FOREIGN KEY (fee_category_id) REFERENCES fin_fee_categories(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_bank_accounts (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    account_name    VARCHAR(100)    NOT NULL,
    account_number  VARCHAR(50)     NOT NULL,
    bank_name       VARCHAR(100)    NOT NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_payment_methods (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    code            VARCHAR(30)     NOT NULL,
    name            VARCHAR(100)    NOT NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_paymethod_code (tenant_id, code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_receipt_series (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    prefix          VARCHAR(20)     NOT NULL,
    year            SMALLINT UNSIGNED NOT NULL,
    next_counter    INT UNSIGNED    NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_receipt_series (tenant_id, prefix, year)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_allocation_policies (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    name            VARCHAR(100)    NOT NULL,
    strategy        VARCHAR(50)     NOT NULL COMMENT 'oldest-first|votehead-priority|manual',
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    effective_from  DATE            NOT NULL,
    effective_to    DATE            NULL,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_penalty_policies (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    name            VARCHAR(100)    NOT NULL,
    penalty_type    VARCHAR(30)     NOT NULL COMMENT 'fixed|percentage',
    value           DECIMAL(15,4)   NOT NULL,
    grace_days      SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    effective_from  DATE            NOT NULL,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_financial_policies (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    policy_key      VARCHAR(100)    NOT NULL,
    policy_value    TEXT            NOT NULL,
    version         INT UNSIGNED    NOT NULL DEFAULT 1,
    effective_from  DATE            NOT NULL,
    changed_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_policy_key_version (tenant_id, policy_key, version)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_period_locks (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    term_id         BIGINT UNSIGNED NULL,
    lock_scope      VARCHAR(30)     NOT NULL COMMENT 'term|year|full',
    locked_by       BIGINT UNSIGNED NOT NULL,
    locked_at       DATETIME        NOT NULL,
    unlocked_by     BIGINT UNSIGNED NULL,
    unlocked_at     DATETIME        NULL,
    reason          TEXT            NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_lock_year FOREIGN KEY (academic_year_id) REFERENCES fin_academic_years(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_exchange_rates (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    from_currency   CHAR(3)         NOT NULL,
    to_currency     CHAR(3)         NOT NULL,
    rate            DECIMAL(20,8)   NOT NULL,
    effective_date  DATE            NOT NULL,
    created_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_rate_pair_date (tenant_id, from_currency, to_currency, effective_date)
) ENGINE=InnoDB;
