-- Migration 042: Permit one immutable replacement receipt for each cancelled payment.
-- The original payment remains CANCELLED; reposted_payment_id records its linked replacement.

ALTER TABLE fee_payments
  ADD COLUMN IF NOT EXISTS reposted_payment_id INT NULL AFTER cashier_session_id,
  ADD KEY IF NOT EXISTS idx_fee_payments_school_reposted_payment (school_id, reposted_payment_id),
  ADD UNIQUE KEY IF NOT EXISTS uq_fee_payments_school_reposted_payment (school_id, reposted_payment_id);