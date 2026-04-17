-- Migration 028: Add formula_expression column to payroll_components
-- Allows storing formula expressions (e.g. "basic_salary * 0.10", "gross * 0.05")

ALTER TABLE payroll_components
    ADD COLUMN formula_expression VARCHAR(500) DEFAULT NULL
    AFTER calculation_type;
