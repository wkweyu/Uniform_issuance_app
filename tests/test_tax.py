"""Unit tests for core.tax — Kenyan statutory computation functions."""

import pytest
from decimal import Decimal
from core.tax import (
    compute_paye,
    compute_shif,
    compute_nssf_separate,
    compute_housing_levy,
    compute_taxable_income,
)

D = Decimal

# ── 2025 Kenyan PAYE bands (monthly) ──────────────────────────────
PAYE_BANDS = [
    {'band_from': D('0'),       'band_to': D('24000'),  'rate': D('10')},
    {'band_from': D('24000'),   'band_to': D('32333'),  'rate': D('25')},
    {'band_from': D('32333'),   'band_to': D('500000'), 'rate': D('30')},
    {'band_from': D('500000'),  'band_to': D('800000'), 'rate': D('32.5')},
    {'band_from': D('800000'),  'band_to': D('99999999'), 'rate': D('35')},
]
PERSONAL_RELIEF = D('2400')

NSSF_EE = [
    {'band_from': D('0'), 'band_to': D('7000'),  'rate': D('6')},
    {'band_from': D('7000'), 'band_to': D('36000'), 'rate': D('6')},
]
NSSF_ER = [
    {'band_from': D('0'), 'band_to': D('7000'),  'rate': D('6')},
    {'band_from': D('7000'), 'band_to': D('36000'), 'rate': D('6')},
]


class TestPAYE:
    def test_below_first_band(self):
        """Someone earning 20,000 taxable: 10% of 20000 = 2000 - 2400 relief = 0"""
        result = compute_paye(D('20000'), PAYE_BANDS, PERSONAL_RELIEF)
        assert result == D('0.00')

    def test_first_band_exactly(self):
        """24000 taxable: 10% of 24000 = 2400 - 2400 = 0"""
        result = compute_paye(D('24000'), PAYE_BANDS, PERSONAL_RELIEF)
        assert result == D('0.00')

    def test_second_band(self):
        """30000 taxable: 2400 (first band) + 25% of 6000 = 1500 = 3900 - 2400 = 1500"""
        result = compute_paye(D('30000'), PAYE_BANDS, PERSONAL_RELIEF)
        assert result == D('1500.00')

    def test_zero_income(self):
        result = compute_paye(D('0'), PAYE_BANDS, PERSONAL_RELIEF)
        assert result == D('0.00')

    def test_high_income(self):
        """100,000 taxable:
        10% of 24000 = 2400
        25% of 8333 = 2083.25
        30% of 67667 = 20300.10 (100000-32333)
        Total = 24783.35 - 2400 = 22383.35
        """
        result = compute_paye(D('100000'), PAYE_BANDS, PERSONAL_RELIEF)
        assert result == D('22383.35')

    def test_never_negative(self):
        result = compute_paye(D('5000'), PAYE_BANDS, D('999999'))
        assert result == D('0.00')


class TestSHIF:
    def test_basic(self):
        """2.75% of 50000 = 1375"""
        result = compute_shif(D('50000'), D('2.75'))
        assert result == D('1375.00')

    def test_zero(self):
        result = compute_shif(D('0'), D('2.75'))
        assert result == D('0.00')


class TestNSSF:
    def test_below_tier1(self):
        """Gross 5000: 6% of 5000 = 300 each"""
        ee, er = compute_nssf_separate(D('5000'), NSSF_EE, NSSF_ER)
        assert ee == D('300.00')
        assert er == D('300.00')

    def test_above_tier2_cap(self):
        """Gross 100000: 6% of 7000 (tier1) + 6% of 29000 (tier2 7000-36000) = 420 + 1740 = 2160"""
        ee, er = compute_nssf_separate(D('100000'), NSSF_EE, NSSF_ER)
        assert ee == D('2160.00')
        assert er == D('2160.00')

    def test_between_tiers(self):
        """Gross 20000: 6% of 7000 + 6% of 13000 = 420 + 780 = 1200"""
        ee, er = compute_nssf_separate(D('20000'), NSSF_EE, NSSF_ER)
        assert ee == D('1200.00')
        assert er == D('1200.00')


class TestHousingLevy:
    def test_standard(self):
        """1.5% ee + 1.5% er of 50000 = 750 each"""
        ee, er = compute_housing_levy(D('50000'), D('1.5'), D('1.5'))
        assert ee == D('750.00')
        assert er == D('750.00')


class TestTaxableIncome:
    def test_standard(self):
        """gross - shif - nssf - housing_levy"""
        result = compute_taxable_income(D('100000'), D('2750'), D('2160'), D('1500'))
        expected = D('100000') - D('2750') - D('2160') - D('1500')
        assert result == expected

    def test_with_pension_cap(self):
        """Pension capped at 30000"""
        result = compute_taxable_income(D('100000'), D('0'), D('0'), D('0'),
                                        pension=D('50000'))
        expected = D('100000') - D('30000')  # capped
        assert result == expected

    def test_never_negative(self):
        result = compute_taxable_income(D('5000'), D('3000'), D('2000'), D('1000'))
        assert result == D('0.00')
