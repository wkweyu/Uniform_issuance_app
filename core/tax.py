"""
Kenyan statutory tax/deduction computation engine.
Pure functions — no database access, fully unit-testable.

Rates are passed in as arguments (loaded from payroll_statutory_rates by the service layer).
All monetary values use Decimal for precision.
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal('0.00')
TWO_PLACES = Decimal('0.01')


def _round(value: Decimal) -> Decimal:
    """Round to 2 decimal places using banker's rounding."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_paye(taxable_monthly: Decimal, bands: list, personal_relief: Decimal = Decimal('2400.00')) -> Decimal:
    """
    Compute PAYE using progressive tax bands.

    Args:
        taxable_monthly: Monthly taxable income after allowable deductions.
        bands: List of dicts sorted by band_from ascending:
               [{'band_from': Decimal, 'band_to': Decimal, 'rate': Decimal}, ...]
               where rate is a percentage (e.g. 10.0 for 10%).
        personal_relief: Monthly personal relief amount (default KSh 2,400).

    Returns:
        PAYE amount (never negative).
    """
    if taxable_monthly <= ZERO:
        return ZERO

    tax = ZERO
    remaining = taxable_monthly

    for band in bands:
        band_from = Decimal(str(band['band_from']))
        band_to = Decimal(str(band['band_to']))
        rate = Decimal(str(band['rate'])) / Decimal('100')

        band_width = band_to - band_from
        if band_width <= ZERO:
            continue

        # How much income falls in this band
        if remaining <= ZERO:
            break

        # Income in this band = min(remaining, band_width)
        # But we need to handle the offset: tax starts from 0, bands define absolute ranges
        if taxable_monthly <= band_from:
            break

        taxable_in_band = min(taxable_monthly, band_to) - band_from
        if taxable_in_band <= ZERO:
            continue

        tax += _round(taxable_in_band * rate)

    # Apply personal relief
    tax = tax - personal_relief
    return _round(max(tax, ZERO))


def compute_shif(gross_pay: Decimal, rate: Decimal = Decimal('2.75')) -> Decimal:
    """
    Compute SHIF (Social Health Insurance Fund) contribution.

    Args:
        gross_pay: Monthly gross pay.
        rate: Percentage rate (default 2.75%).

    Returns:
        SHIF contribution amount.
    """
    if gross_pay <= ZERO:
        return ZERO
    return _round(gross_pay * rate / Decimal('100'))


def compute_nssf(gross_pay: Decimal, tiers: list) -> tuple:
    """
    Compute NSSF contributions (employee and employer) using tiered rates.

    Args:
        gross_pay: Monthly gross pay.
        tiers: List of dicts sorted by band_from:
               [{'band_from': Decimal, 'band_to': Decimal, 'rate': Decimal}, ...]
               Separate tier lists for employee vs employer.

    Returns:
        Tuple of (employee_contribution, employer_contribution).
        Note: For Kenya, employer matches employee, so caller passes both tier lists.
    """
    if gross_pay <= ZERO:
        return (ZERO, ZERO)

    def _calc_tiered(pay, tier_bands):
        total = ZERO
        for tier in tier_bands:
            band_from = Decimal(str(tier['band_from']))
            band_to = Decimal(str(tier['band_to']))
            rate = Decimal(str(tier['rate'])) / Decimal('100')

            if pay <= band_from:
                break

            applicable = min(pay, band_to) - band_from
            if applicable > ZERO:
                total += _round(applicable * rate)
        return total

    # In Kenya, employer matches employee. Caller provides separate tier lists.
    # For simplicity, we compute from the employee tiers and return same for both.
    employee = _calc_tiered(gross_pay, tiers)
    employer = employee  # Kenya: employer matches
    return (employee, employer)


def compute_nssf_separate(gross_pay: Decimal, employee_tiers: list, employer_tiers: list) -> tuple:
    """
    Compute NSSF with separate employee/employer tier schedules.

    Returns:
        Tuple of (employee_contribution, employer_contribution).
    """
    if gross_pay <= ZERO:
        return (ZERO, ZERO)

    def _calc(pay, tiers):
        total = ZERO
        for tier in tiers:
            band_from = Decimal(str(tier['band_from']))
            band_to = Decimal(str(tier['band_to']))
            rate = Decimal(str(tier['rate'])) / Decimal('100')
            if pay <= band_from:
                break
            applicable = min(pay, band_to) - band_from
            if applicable > ZERO:
                total += _round(applicable * rate)
        return total

    return (_calc(gross_pay, employee_tiers), _calc(gross_pay, employer_tiers))


def compute_housing_levy(gross_pay: Decimal, employee_rate: Decimal = Decimal('1.5'),
                         employer_rate: Decimal = Decimal('1.5')) -> tuple:
    """
    Compute Affordable Housing Levy.

    Args:
        gross_pay: Monthly gross pay.
        employee_rate: Employee percentage (default 1.5%).
        employer_rate: Employer percentage (default 1.5%).

    Returns:
        Tuple of (employee_amount, employer_amount).
    """
    if gross_pay <= ZERO:
        return (ZERO, ZERO)
    ee = _round(gross_pay * employee_rate / Decimal('100'))
    er = _round(gross_pay * employer_rate / Decimal('100'))
    return (ee, er)


def compute_taxable_income(gross_pay: Decimal, shif: Decimal, nssf_employee: Decimal,
                           housing_levy_employee: Decimal, pension: Decimal = ZERO,
                           mortgage_interest: Decimal = ZERO) -> Decimal:
    """
    Compute taxable income by deducting allowable items from gross pay.

    Allowable deductions before PAYE (per KRA):
    - SHIF contributions
    - NSSF employee contributions
    - Housing Levy (employee portion)
    - Registered pension contributions (up to KSh 30,000/month)
    - Mortgage interest (up to KSh 30,000/month)

    Returns:
        Taxable income (never negative).
    """
    pension_cap = min(pension, Decimal('30000.00'))
    mortgage_cap = min(mortgage_interest, Decimal('30000.00'))

    taxable = gross_pay - shif - nssf_employee - housing_levy_employee - pension_cap - mortgage_cap
    return _round(max(taxable, ZERO))
