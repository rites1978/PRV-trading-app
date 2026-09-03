"""
Unit and Property Tests for PRV Strong Type Money and Currency Model.
Proves currency isolation, unit normalization, and market value calculations across:
- UK Equities (quoted in GBX / pence)
- UK ETFs (quoted in GBP / pounds)
- US Equities (quoted in USD / dollars)
"""
import unittest
from datetime import datetime, timezone
from src.core.money import Money, Currency, CurrencyUnit, CurrencyMismatchError


class TestMoneyModel(unittest.TestCase):
    def test_gbp_creation_and_formatting(self):
        m = Money(1500.50, Currency.GBP)
        self.assertEqual(m.amount, 1500.50)
        self.assertEqual(m.currency, Currency.GBP)
        self.assertEqual(m.unit, CurrencyUnit.MAJOR)
        self.assertEqual(m.format(), "£1,500.50")
        self.assertEqual(str(m), "£1,500.50")

    def test_gbx_creation_and_normalization(self):
        # LSE Equity (e.g. HSBC @ 1545.20 GBX)
        quote = Money(1545.20, Currency.GBX)
        self.assertEqual(quote.currency, Currency.GBX)
        self.assertEqual(quote.unit, CurrencyUnit.MINOR)
        self.assertEqual(quote.format(), "1,545.20 GBX")

        major = quote.to_major()
        self.assertEqual(major.currency, Currency.GBP)
        self.assertEqual(major.unit, CurrencyUnit.MAJOR)
        self.assertAlmostEqual(major.amount, 15.452, places=4)
        self.assertEqual(major.format(), "£15.45")

    def test_usd_creation_and_conversion(self):
        # US Equity (e.g. Apple @ $225.50)
        quote = Money(225.50, Currency.USD)
        self.assertEqual(quote.currency, Currency.USD)
        self.assertEqual(quote.unit, CurrencyUnit.MAJOR)
        self.assertEqual(quote.format(), "$225.50")

        # Assume GBP/USD = 1.3500 => USD/GBP = 1 / 1.3500 = 0.7407407
        fx_usd_to_gbp = 1.0 / 1.3500
        gbp_val = quote.to_gbp(fx_rate_usd_to_gbp=fx_usd_to_gbp)
        self.assertEqual(gbp_val.currency, Currency.GBP)
        self.assertEqual(gbp_val.unit, CurrencyUnit.MAJOR)
        self.assertAlmostEqual(gbp_val.amount, 225.50 / 1.35, places=3)

    def test_mismatched_currency_addition_prohibited(self):
        gbp = Money(100.0, Currency.GBP)
        usd = Money(100.0, Currency.USD)
        with self.assertRaises(CurrencyMismatchError):
            _ = gbp + usd

        with self.assertRaises(CurrencyMismatchError):
            _ = gbp - usd

    def test_gbx_and_gbp_addition_prohibited_without_normalization(self):
        gbp = Money(10.0, Currency.GBP)
        gbx = Money(500.0, Currency.GBX)  # 500 pence = £5.00
        with self.assertRaises(CurrencyMismatchError):
            _ = gbp + gbx

        # Adding after normalization must succeed
        combined = gbp + gbx.to_major()
        self.assertEqual(combined.currency, Currency.GBP)
        self.assertAlmostEqual(combined.amount, 15.0, places=4)

    def test_market_value_gbp_calculation_uk_equity_gbx(self):
        # 183.02 shares of HSBC @ 1545.20 GBX
        quantity = 183.02
        price_gbx = Money(1545.20, Currency.GBX)
        mv = Money.calculate_market_value_gbp(quantity, price_gbx)
        self.assertEqual(mv.currency, Currency.GBP)
        # Expected: 183.02 * 15.4520 = 2828.025
        self.assertAlmostEqual(mv.amount, 183.02 * 15.4520, places=2)

    def test_market_value_gbp_calculation_us_equity_usd(self):
        # 9.05 shares of Visa @ $377.93 with GBP/USD = 1.3500
        quantity = 9.05
        price_usd = Money(377.93, Currency.USD)
        fx_usd_to_gbp = 1.0 / 1.3500
        mv = Money.calculate_market_value_gbp(quantity, price_usd, fx_rate_usd_to_gbp=fx_usd_to_gbp)
        self.assertEqual(mv.currency, Currency.GBP)
        expected = (9.05 * 377.93) / 1.3500
        self.assertAlmostEqual(mv.amount, expected, places=2)

    def test_serialization_roundtrip(self):
        orig = Money(4200.75, Currency.GBP, source="TEST_FIXTURE")
        data = orig.to_dict()
        rebuilt = Money.from_dict(data)
        self.assertEqual(orig, rebuilt)
        self.assertEqual(rebuilt.source, "TEST_FIXTURE")


if __name__ == "__main__":
    unittest.main()
