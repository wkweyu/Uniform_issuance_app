-- MIG-FIN-002 | CAP-FIN-002 Billing Engine
-- Wave-1 | Additive schema + Dual-write | 2026-07-22

CREATE TABLE IF NOT EXISTS fin_invoice_headers (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    invoice_no      VARCHAR(50)     NOT NULL,
    admno           VARCHAR(50)     NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    term_id         BIGINT UNSIGNED NOT NULL,
    total_amount    DECIMAL(15,2)   NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'draft'
                    COMMENT 'draft|posted|cancelled|superseded',
    superseded_by   BIGINT UNSIGNED NULL,
    version         INT UNSIGNED    NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_invoice_no (tenant_id, invoice_no),
    CONSTRAINT fk_inv_year FOREIGN KEY (academic_year_id) REFERENCES fin_academic_years(id),
    CONSTRAINT fk_inv_term FOREIGN KEY (term_id)          REFERENCES fin_terms(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_invoice_lines (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    invoice_id      BIGINT UNSIGNED NOT NULL,
    votehead_id     BIGINT UNSIGNED NOT NULL,
    description     VARCHAR(255)    NOT NULL,
    amount          DECIMAL(15,2)   NOT NULL,
    line_order      SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_invline_header  FOREIGN KEY (invoice_id)  REFERENCES fin_invoice_headers(id),
    CONSTRAINT fk_invline_votehead FOREIGN KEY (votehead_id) REFERENCES fin_voteheads(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_billing_plans (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    name            VARCHAR(100)    NOT NULL,
    academic_year_id BIGINT UNSIGNED NOT NULL,
    billing_scope   VARCHAR(30)     NOT NULL COMMENT 'class-group|individual|programme',
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_plan_year FOREIGN KEY (academic_year_id) REFERENCES fin_academic_years(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_recurring_schedules (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    billing_plan_id BIGINT UNSIGNED NOT NULL,
    frequency       VARCHAR(20)     NOT NULL COMMENT 'term|monthly|once',
    next_run_date   DATE            NOT NULL,
    last_run_date   DATE            NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_schedule_plan FOREIGN KEY (billing_plan_id) REFERENCES fin_billing_plans(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_debit_notes (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    note_no         VARCHAR(50)     NOT NULL,
    invoice_id      BIGINT UNSIGNED NOT NULL,
    admno           VARCHAR(50)     NOT NULL,
    amount          DECIMAL(15,2)   NOT NULL,
    reason          TEXT            NOT NULL,
    approved_by     BIGINT UNSIGNED NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                    COMMENT 'pending|approved|rejected',
    created_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_debitnote_no (tenant_id, note_no),
    CONSTRAINT fk_debitnote_inv FOREIGN KEY (invoice_id) REFERENCES fin_invoice_headers(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_credit_notes (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    note_no         VARCHAR(50)     NOT NULL,
    invoice_id      BIGINT UNSIGNED NOT NULL,
    admno           VARCHAR(50)     NOT NULL,
    amount          DECIMAL(15,2)   NOT NULL,
    reason          TEXT            NOT NULL,
    approved_by     BIGINT UNSIGNED NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                    COMMENT 'pending|approved|rejected',
    created_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_creditnote_no (tenant_id, note_no),
    CONSTRAINT fk_creditnote_inv FOREIGN KEY (invoice_id) REFERENCES fin_invoice_headers(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_installment_plans (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    invoice_id      BIGINT UNSIGNED NOT NULL,
    admno           VARCHAR(50)     NOT NULL,
    installment_no  TINYINT UNSIGNED NOT NULL,
    due_date        DATE            NOT NULL,
    amount          DECIMAL(15,2)   NOT NULL,
    paid_amount     DECIMAL(15,2)   NOT NULL DEFAULT 0,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                    COMMENT 'pending|partial|paid|overdue',
    created_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_installment_inv FOREIGN KEY (invoice_id) REFERENCES fin_invoice_headers(id)
) ENGINE=InnoDB;
