-- Migration 041: Enforce one payment reference per mode within each school.
-- References are required for all new fee payments by FeesService.record_payment().
-- The legacy global unique key incorrectly prevents two schools from using the
-- same bank, cheque, M-PESA, or cash-receipt reference.

ALTER TABLE fee_payments
  DROP INDEX IF EXISTS unique_payment_ref,
  ADD UNIQUE KEY IF NOT EXISTS uq_fee_payments_school_mode_reference
    (school_id, payment_mode, reference_number);