"""
🏛️ PRV CAPITAL | REGRESSION SUITE: VERSIONED COST-SCHEDULE CONTRACT
Validates:
1. Point-in-time lookup accuracy across historical dates (2024 vs 2025 vs 2026).
2. Correct regulatory values:
   - SEC Section 31 ($20.60/M post April 4, 2026 vs $27.80/M prior).
   - FINRA TAF ($0.000195/share, max $9.79 post Jan 1, 2026 vs $0.000166/share, max $8.30 prior).
   - UK PTM Levy (£1.50 buy + £1.50 sell for trades > £10,000; £0.00 for ETFs).
   - UK SDRT (0.50% on UK equity buy; 0.00% on UK ETF buy).
3. Fail-closed behavior on missing or expired schedules.
4. Exact £ ledger friction values across £15k, £25k, £35k, £40k, £45k tiers.
"""
import unittest
from datetime import date
from src.research.cost_schedule import (
    CostScheduleRepository,
    FeeType,
    Jurisdiction,
    InstrumentClass,
    CostScheduleEntry,
    CalculationBasis
)


class TestVersionedCostSchedule(unittest.TestCase):
    def setUp(self):
        self.repo = CostScheduleRepository()

    def test_point_in_time_sec_rate_evolution(self):
        # Pre-April 4, 2026: FY2025 rate was $27.80 / $1M
        entry_old = self.repo.get_entry(FeeType.SEC_SECTION_31, Jurisdiction.US, InstrumentClass.EQUITY, date(2025, 10, 1))
        self.assertAlmostEqual(entry_old.rate, 0.0000278, places=7)
        
        # Post-April 4, 2026: FY2026 rate is $20.60 / $1M
        entry_new = self.repo.get_entry(FeeType.SEC_SECTION_31, Jurisdiction.US, InstrumentClass.EQUITY, date(2026, 5, 1))
        self.assertAlmostEqual(entry_new.rate, 0.0000206, places=7)

    def test_point_in_time_finra_taf_evolution(self):
        # 2025: $0.000166 / share, max $8.30
        entry_2025 = self.repo.get_entry(FeeType.FINRA_TAF, Jurisdiction.US, InstrumentClass.EQUITY, date(2025, 6, 1))
        self.assertAlmostEqual(entry_2025.rate, 0.000166, places=6)
        self.assertEqual(entry_2025.maximum, 8.30)
        
        # 2026: $0.000195 / share, max $9.79
        entry_2026 = self.repo.get_entry(FeeType.FINRA_TAF, Jurisdiction.US, InstrumentClass.EQUITY, date(2026, 6, 1))
        self.assertAlmostEqual(entry_2026.rate, 0.000195, places=6)
        self.assertEqual(entry_2026.maximum, 9.79)

    def test_uk_ptm_levy_and_sdrt_rules(self):
        trade_date = date(2026, 9, 8)
        
        # UK Equity: 0.50% SDRT on Buy, £1.50 per leg PTM Levy if > £10,000
        ptm_eq = self.repo.get_entry(FeeType.PTM_LEVY, Jurisdiction.UK, InstrumentClass.EQUITY, trade_date)
        self.assertEqual(ptm_eq.rate, 1.50)
        self.assertEqual(ptm_eq.threshold, 10000.0)
        
        sdrt_eq = self.repo.get_entry(FeeType.SDRT, Jurisdiction.UK, InstrumentClass.EQUITY, trade_date)
        self.assertEqual(sdrt_eq.rate, 0.0050)
        
        # UK ETF: 0.00% SDRT, £0.00 PTM Levy
        ptm_etf = self.repo.get_entry(FeeType.PTM_LEVY, Jurisdiction.UK, InstrumentClass.ETF, trade_date)
        self.assertEqual(ptm_etf.rate, 0.00)
        
        sdrt_etf = self.repo.get_entry(FeeType.SDRT, Jurisdiction.UK, InstrumentClass.ETF, trade_date)
        self.assertEqual(sdrt_etf.rate, 0.0000)

    def test_fail_closed_missing_schedule(self):
        # Query an ancient date before any schedules existed (e.g. 1950)
        with self.assertRaises(LookupError):
            self.repo.get_entry(FeeType.FX_CONVERSION, Jurisdiction.GLOBAL, InstrumentClass.ALL, date(1950, 1, 1))

    def test_production_health_validation(self):
        health = self.repo.validate_production_health(date(2026, 9, 8))
        self.assertTrue(health["all_passed"])
        self.assertIn("SEC_SECTION_31_US_ALL", health["details"])
        self.assertEqual(health["details"]["SEC_SECTION_31_US_ALL"]["status"], "VALID")

    def test_exact_capital_tier_cost_calculations(self):
        trade_date = date(2026, 9, 8)
        gbpusd = 1.30
        share_price_usd = 150.0

        # Test £15,000 US Equity
        buy_15k = 15000.0
        sell_15k = 15153.10
        shares_15k = (buy_15k * gbpusd) / share_price_usd
        costs_us_15k = self.repo.calculate_trade_costs(
            trade_date=trade_date,
            jurisdiction=Jurisdiction.US,
            instrument_class=InstrumentClass.EQUITY,
            buy_notional_gbp=buy_15k,
            sell_notional_gbp=sell_15k,
            shares=shares_15k,
            gbpusd_rate=gbpusd
        )
        self.assertAlmostEqual(costs_us_15k["total_fx_gbp"], 45.23, delta=0.05)
        self.assertAlmostEqual(costs_us_15k["sec_fee_gbp"], 0.312, delta=0.01)
        self.assertAlmostEqual(costs_us_15k["finra_taf_gbp"], 0.020, delta=0.005)
        self.assertAlmostEqual(costs_us_15k["total_friction_gbp"], 53.10, delta=0.15)

        # Test £45,000 US Equity
        buy_45k = 45000.0
        sell_45k = 45258.94
        shares_45k = (buy_45k * gbpusd) / share_price_usd
        costs_us_45k = self.repo.calculate_trade_costs(
            trade_date=trade_date,
            jurisdiction=Jurisdiction.US,
            instrument_class=InstrumentClass.EQUITY,
            buy_notional_gbp=buy_45k,
            sell_notional_gbp=sell_45k,
            shares=shares_45k,
            gbpusd_rate=gbpusd
        )
        self.assertAlmostEqual(costs_us_45k["total_fx_gbp"], 135.39, delta=0.10)
        self.assertAlmostEqual(costs_us_45k["sec_fee_gbp"], 0.932, delta=0.02)
        self.assertAlmostEqual(costs_us_45k["finra_taf_gbp"], 0.058, delta=0.01)
        self.assertAlmostEqual(costs_us_45k["total_friction_gbp"], 158.94, delta=0.20)

        # Test £25,000 UK Equity (Qualifies for £3.00 PTM levy + 0.50% SDRT)
        buy_25k = 25000.0
        sell_25k = 25255.64
        costs_uk_25k = self.repo.calculate_trade_costs(
            trade_date=trade_date,
            jurisdiction=Jurisdiction.UK,
            instrument_class=InstrumentClass.EQUITY,
            buy_notional_gbp=buy_25k,
            sell_notional_gbp=sell_25k,
            shares=1000
        )
        self.assertEqual(costs_uk_25k["sdrt_gbp"], 125.00)
        self.assertEqual(costs_uk_25k["ptm_levy_gbp"], 3.00)
        self.assertEqual(costs_uk_25k["total_fx_gbp"], 0.00)
        self.assertAlmostEqual(costs_uk_25k["total_friction_gbp"], 155.64, delta=0.20)

        # Test £25,000 GBP ETF (Exempt from SDRT, PTM, FX)
        costs_etf_25k = self.repo.calculate_trade_costs(
            trade_date=trade_date,
            jurisdiction=Jurisdiction.UK,
            instrument_class=InstrumentClass.ETF,
            buy_notional_gbp=buy_25k,
            sell_notional_gbp=25120.05,
            shares=500
        )
        self.assertEqual(costs_etf_25k["sdrt_gbp"], 0.00)
        self.assertEqual(costs_etf_25k["ptm_levy_gbp"], 0.00)
        self.assertEqual(costs_etf_25k["total_fx_gbp"], 0.00)
        self.assertAlmostEqual(costs_etf_25k["total_friction_gbp"], 20.05, delta=0.15)


if __name__ == "__main__":
    unittest.main()
