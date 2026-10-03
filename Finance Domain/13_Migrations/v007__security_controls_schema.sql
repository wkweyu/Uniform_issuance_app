-- MIG-FIN-007 | CAP-FIN-012 Security Controls
-- Wave-1 | Additive schema | 2026-07-22

CREATE TABLE IF NOT EXISTS fin_control_policies (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    action_type     VARCHAR(60)     NOT NULL COMMENT 'refund|reversal|manual-payment|period-unlock|...',
    control_type    VARCHAR(30)     NOT NULL COMMENT 'step-up|dual-approval|threshold',
    threshold_amount DECIMAL(15,2)  NULL COMMENT 'NULL = always triggers',
    step_up_ttl_secs INT UNSIGNED   NULL DEFAULT 300,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    effective_from  DATE            NOT NULL,
    created_by      BIGINT UNSIGNED NOT NULL,
    updated_by      BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_control_action (tenant_id, action_type, control_type)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_step_up_challenges (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    actor_id        BIGINT UNSIGNED NOT NULL,
    action_type     VARCHAR(60)     NOT NULL,
    source_ref      VARCHAR(100)    NULL COMMENT 'ID of the object requiring step-up',
    challenge_token VARCHAR(200)    NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                    COMMENT 'pending|passed|failed|expired',
    issued_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME        NOT NULL,
    resolved_at     DATETIME        NULL,
    UNIQUE KEY uq_challenge_token (tenant_id, challenge_token),
    INDEX idx_stepup_actor (tenant_id, actor_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fin_sod_violation_log (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    actor_id        BIGINT UNSIGNED NOT NULL,
    action_type     VARCHAR(60)     NOT NULL,
    conflicting_roles JSON          NOT NULL,
    detection_mode  VARCHAR(20)     NOT NULL DEFAULT 'warn'
                    COMMENT 'warn|block',
    source_ref      VARCHAR(100)    NULL,
    detected_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_by     BIGINT UNSIGNED NULL,
    reviewed_at     DATETIME        NULL,
    resolution      VARCHAR(30)     NULL COMMENT 'accepted|mitigated|false-positive',
    INDEX idx_sod_actor  (tenant_id, actor_id),
    INDEX idx_sod_action (tenant_id, action_type)
) ENGINE=InnoDB;
