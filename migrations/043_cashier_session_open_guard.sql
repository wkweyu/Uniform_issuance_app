-- Migration 043: Enforce one active cashier session per school and cashier.
-- NULL markers permit unlimited closed or pending-approval sessions.

ALTER TABLE cashier_sessions
  ADD COLUMN IF NOT EXISTS open_session_marker CHAR(4) NULL AFTER status;

UPDATE cashier_sessions
SET open_session_marker = CASE WHEN status = 'OPEN' THEN 'OPEN' ELSE NULL END
WHERE open_session_marker IS NULL;

ALTER TABLE cashier_sessions
  ADD UNIQUE KEY IF NOT EXISTS uq_cashier_sessions_one_open
    (school_id, cashier_user_id, open_session_marker);