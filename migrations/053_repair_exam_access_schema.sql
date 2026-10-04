CREATE TABLE IF NOT EXISTS `exam_user_roles` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `role_key` VARCHAR(48) NOT NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `granted_by` INT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_exam_user_role` (`school_id`, `user_id`, `role_key`),
  KEY `idx_exam_user_roles_lookup` (`school_id`, `user_id`, `is_active`),
  CONSTRAINT `fk_exam_user_roles_school`
    FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_user_roles_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`userNo`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_user_roles_grantor`
    FOREIGN KEY (`granted_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `exam_access_grants` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `exam_id` INT NOT NULL,
  `class_id` INT NOT NULL,
  `subject_id` INT NOT NULL,
  `permission_key` VARCHAR(48) NOT NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'requested',
  `requested_by` INT NOT NULL,
  `reviewed_by` INT NULL,
  `request_reason` VARCHAR(500) NOT NULL,
  `review_reason` VARCHAR(500) NULL,
  `expires_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `reviewed_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `idx_exam_access_grant_user` (`school_id`, `user_id`, `status`, `expires_at`),
  KEY `idx_exam_access_grant_scope` (`school_id`, `exam_id`, `class_id`, `subject_id`),
  CONSTRAINT `fk_exam_access_grants_school`
    FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_access_grants_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`userNo`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_access_grants_requester`
    FOREIGN KEY (`requested_by`) REFERENCES `users` (`userNo`) ON DELETE RESTRICT,
  CONSTRAINT `fk_exam_access_grants_reviewer`
    FOREIGN KEY (`reviewed_by`) REFERENCES `users` (`userNo`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `exam_audit_events` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `school_id` INT NOT NULL,
  `actor_user_id` INT NULL,
  `event_key` VARCHAR(80) NOT NULL,
  `entity_type` VARCHAR(48) NOT NULL,
  `entity_id` VARCHAR(80) NULL,
  `old_values` JSON NULL,
  `new_values` JSON NULL,
  `reason` VARCHAR(500) NULL,
  `request_id` VARCHAR(80) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_exam_audit_school_time` (`school_id`, `created_at`),
  KEY `idx_exam_audit_entity` (`school_id`, `entity_type`, `entity_id`, `created_at`),
  KEY `idx_exam_audit_actor` (`school_id`, `actor_user_id`, `created_at`),
  CONSTRAINT `fk_exam_audit_school`
    FOREIGN KEY (`school_id`) REFERENCES `schools` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_exam_audit_actor`
    FOREIGN KEY (`actor_user_id`) REFERENCES `users` (`userNo`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
