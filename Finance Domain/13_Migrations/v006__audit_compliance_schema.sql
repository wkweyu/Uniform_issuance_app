-- MIG-FIN-006 | CAP-FIN-011 Audit and Compliance
-- Wave-1 | Additive schema | 2026-07-22
-- Note: app DB role must NOT have UPDATE or DELETE on fin_audit_events.

CREATE TABLE IF NOT EXISTS fin_audit_events (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    event_type      VARCHAR(60)     NOT NULL COMMENT 'payment.received|receipt.reversed|period.locked|...',
    actor_id        BIGINT UNSIGNED NOT NULL,
    actor_role      VARCHAR(50)     NULL,
    target_type     VARCHAR(50)     NOT NULL COMMENT 'payment|invoice|journal|period_lock|...',
    target_id       VARCHAR(100)    NOT NULL,
    before_state    JSON            NULL,
    after_state     JSON            NULL,
    ip_address      VARCHAR(45)     NULL,
    correlation_id  VARCHAR(100)    NULL,
    occurred_at     DATETIME        NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_audit_tenant_type  (tenant_id, event_type),
    INDEX idx_audit_tenant_actor (tenant_id, actor_id),
    INDEX idx_audit_occurred     (tenant_id, occurred_at),
    INDEX idx_audit_target       (tenant_id, target_type, target_id(40))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_evidence_attachments (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    audit_event_id  BIGINT UNSIGNED NOT NULL,
    attachment_type VARCHAR(30)     NOT NULL COMMENT 'approval-screenshot|export-pdf|signature|note',
    storage_key     VARCHAR(500)    NOT NULL,
    file_hash       VARCHAR(64)     NOT NULL,
    uploaded_by     BIGINT UNSIGNED NOT NULL,
    uploaded_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_evidence_audit FOREIGN KEY (audit_event_id) REFERENCES fin_audit_events(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_audit_export_jobs (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    requested_by    BIGINT UNSIGNED NOT NULL,
    from_date       DATE            NOT NULL,
    to_date         DATE            NOT NULL,
    filter_json     JSON            NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                    COMMENT 'pending|running|completed|failed',
    output_key      VARCHAR(500)    NULL,
    watermark_meta  JSON            NULL,
    started_at      DATETIME        NULL,
    completed_at    DATETIME        NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
