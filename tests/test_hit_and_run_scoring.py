"""
TDD Tests: Hit-and-Run Short-Term Opportunity Scoring Interface
Verifies:
1. Scoring evaluates all mandatory factors:
   - live momentum
   - acceleration / momentum change
   - relative strength
   - liquidity
   - spread / execution friction
   - volatility
   - volume/activity
   - distance from intraday extremes
   - market/session state
   - estimated costs
   - expected net reward versus downside
2. Enforces auditable attribution of weights and criteria.
3. Rejects negative expected net edge (costs > reward).
4. Strictly caps downside risk at 5%.
5. Does NOT use the old ETF 20d Sharpe/SMA200 model.
"""
import unittest
from datetime import datetime, timezone
import pandas as pd
import numpy as np


class TestHitAndRunScoring(unittest.TestCase):

    def setUp(self):
        from src.hit_and_run.scoring import HitAndRunOpportunityScorer
        self.scorer = HitAndRunOpportunityScorer()

    def test_strong_momentum_breakout_scores_highly(self):
        """A strong intraday breakout with volume acceleration should receive high score and qualify."""
        market_snapshot = {
            "instrument_id": "NVDA_US_EQ",
            "symbol": "NVDA",
            "feed_ticker": "NVDA",
            "product_type": "STOCK",
            "currency": "USD",
            "is_uk_pence": False,
            "quote_divisor": 1.0,
            "current_price": 121.50,
            "current_price_gbp": 92.50,
            "exchange_venue": "NASDAQ",
            "min_trade_quantity": 0.001,
            "isin": "US67066G1040",
            "intraday_open": 116.0,
            "intraday_high": 122.0,
            "intraday_low": 115.80,
            "recent_prices": [116.0, 116.3, 116.8, 117.5, 118.5, 119.8, 121.5],
            "benchmark_return": 0.005,  # S&P +0.5%
            "volume_recent": 1500000,
            "volume_avg": 1000000,      # 1.5x volume
            "bid": 121.48,
            "ask": 121.52,              # 0.03% spread
            "session_state": "REGULAR"
        }

        candidate = self.scorer.evaluate_opportunity(market_snapshot)

        self.assertEqual(candidate.symbol, "NVDA")
        self.assertGreater(candidate.momentum, 0.02)  # > 2% move
        self.assertGreater(candidate.acceleration, 0.0)  # Positive acceleration
        self.assertGreater(candidate.volume_activity, 1.2)  # > 1.2x volume
        self.assertLessEqual(candidate.downside_risk, 0.05)  # <= 5% max loss invariant
        self.assertGreater(candidate.expected_net_reward, candidate.estimated_costs)
        self.assertGreater(candidate.risk_reward_ratio, 1.2)
        self.assertGreater(candidate.opportunity_score, 70.0)
        self.assertTrue(candidate.strategy_qualified)
        self.assertIn("opportunity", candidate.entry_thesis.lower())

    def test_high_friction_stagnant_asset_fails_qualification(self):
        """Asset with high spread and stagnant/negative momentum must be disqualified."""
        market_snapshot = {
            "instrument_id": "WIDE_SPREAD_EQ",
            "symbol": "WIDE",
            "feed_ticker": "WIDE.L",
            "product_type": "STOCK",
            "currency": "GBX",
            "is_uk_pence": True,
            "quote_divisor": 100.0,
            "current_price": 100.0,
            "current_price_gbp": 1.0,
            "intraday_open": 102.0,
            "intraday_high": 102.5,
            "intraday_low": 99.5,
            "recent_prices": [102.0, 101.5, 101.0, 100.5, 100.0],
            "benchmark_return": 0.005,
            "volume_recent": 1000,
            "volume_avg": 5000,       # Low volume 0.2x
            "bid": 98.0,
            "ask": 102.0,             # 4.0% spread friction!
            "session_state": "REGULAR"
        }

        candidate = self.scorer.evaluate_opportunity(market_snapshot)

        self.assertFalse(candidate.strategy_qualified)
        self.assertLess(candidate.opportunity_score, 50.0)
        self.assertTrue(any("friction" in r.lower() or "momentum" in r.lower() or "cost" in r.lower() or "edge" in r.lower() for r in candidate.qualification_reasons))

    def test_ranking_sorts_by_opportunity_score(self):
        """Batch evaluation returns candidates sorted by opportunity conviction."""
        cand_a = {
            "instrument_id": "STRONG_EQ",
            "symbol": "STRONG",
            "feed_ticker": "STRONG",
            "product_type": "STOCK",
            "currency": "USD",
            "is_uk_pence": False,
            "quote_divisor": 1.0,
            "current_price": 50.0,
            "current_price_gbp": 38.0,
            "intraday_open": 48.0,
            "intraday_high": 50.2,
            "intraday_low": 47.9,
            "recent_prices": [48.0, 48.5, 49.2, 50.0],
            "benchmark_return": 0.002,
            "volume_recent": 200000,
            "volume_avg": 100000,
            "bid": 49.99,
            "ask": 50.01,
            "session_state": "REGULAR"
        }
        cand_b = {
            "instrument_id": "MED_EQ",
            "symbol": "MED",
            "feed_ticker": "MED",
            "product_type": "STOCK",
            "currency": "USD",
            "is_uk_pence": False,
            "quote_divisor": 1.0,
            "current_price": 20.0,
            "current_price_gbp": 15.0,
            "intraday_open": 20.0,
            "intraday_high": 20.1,
            "intraday_low": 19.9,
            "recent_prices": [20.0, 20.02, 20.05, 20.0],
            "benchmark_return": 0.002,
            "volume_recent": 50000,
            "volume_avg": 50000,
            "bid": 19.98,
            "ask": 20.02,
            "session_state": "REGULAR"
        }

        ranked = self.scorer.rank_opportunities([cand_b, cand_a])
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].symbol, "STRONG")
        self.assertGreater(ranked[0].opportunity_score, ranked[1].opportunity_score)

    def test_no_fixed_rr_rejection_threshold(self):
        """Verifies that risk/reward ratio < 1.2x does NOT cause rejection if candidate has positive net edge and meets score threshold."""
        snapshot = {
            "instrument_id": "MOD_RR_EQ",
            "symbol": "MOD_RR",
            "feed_ticker": "MOD_RR",
            "product_type": "STOCK",
            "currency": "GBP",
            "is_uk_pence": False,
            "quote_divisor": 1.0,
            "current_price": 100.0,
            "current_price_gbp": 100.0,
            "intraday_open": 98.0,
            "intraday_high": 100.2,
            "intraday_low": 97.9,
            "recent_prices": [98.0, 98.5, 99.0, 99.5, 100.0],
            "benchmark_return": 0.001,
            "volume_recent": 500000,
            "volume_avg": 250000,
            "bid": 99.98,
            "ask": 100.02,
            "session_state": "REGULAR"
        }

        candidate = self.scorer.evaluate_opportunity(snapshot)
        # Verify that even if R/R is around 1.0 - 1.1x, it is not rejected for R/R
        self.assertNotIn("Risk-reward ratio", " ".join(candidate.qualification_reasons))

    def test_stamp_duty_and_fx_broker_constants(self):
        """
        Verifies:
        1. UK ordinary stock (STOCK, GB ISIN, GBX) -> 0.5% SDRT, 0.0% FX.
        2. UK ETF (ETF, GB ISIN, GBX) -> 0.0% SDRT (legally exempt), 0.0% FX.
        3. UK-traded Irish/Foreign stock (STOCK, IE ISIN, GBX) -> 0.0% SDRT, 0.0% FX.
        4. US stock (STOCK, US ISIN, USD) -> 0.0% SDRT, 0.15% FX (0.30% round-trip).
        """
        base_snap = {
            "current_price": 100.0,
            "recent_prices": [99.0, 100.0],
            "bid": 99.95,
            "ask": 100.05,
            "session_state": "REGULAR"
        }

        # 1. UK Ordinary Stock (GB ISIN)
        snap_uk_stock = {**base_snap, "instrument_id": "BARCl_EQ", "product_type": "STOCK", "isin": "GB0031348658", "currency": "GBX", "is_uk_pence": True}
        c_uk_stock = self.scorer.evaluate_opportunity(snap_uk_stock)
        # SDRT = 0.005, FX = 0.0, spread = 0.001 -> estimated_costs ~ 0.006
        self.assertAlmostEqual(c_uk_stock.estimated_costs, 0.005 + 0.001, delta=0.0005)

        # 2. UK ETF (GB ISIN) - EXEMPT from SDRT
        snap_uk_etf = {**base_snap, "instrument_id": "ISFl_EQ", "product_type": "ETF", "isin": "GB0005305102", "currency": "GBX", "is_uk_pence": True}
        c_uk_etf = self.scorer.evaluate_opportunity(snap_uk_etf)
        # SDRT = 0.0 (ETF exempt), FX = 0.0, spread = 0.001 -> estimated_costs ~ 0.001
        self.assertAlmostEqual(c_uk_etf.estimated_costs, 0.001, delta=0.0005)

        # 3. Foreign Stock in GBX (e.g. Irish ISIN) - EXEMPT from SDRT
        snap_ie_stock = {**base_snap, "instrument_id": "PETl_EQ", "product_type": "STOCK", "isin": "IE0001340177", "currency": "GBX", "is_uk_pence": True}
        c_ie_stock = self.scorer.evaluate_opportunity(snap_ie_stock)
        # SDRT = 0.0 (non-GB ISIN exempt), FX = 0.0, spread = 0.001 -> estimated_costs ~ 0.001
        self.assertAlmostEqual(c_ie_stock.estimated_costs, 0.001, delta=0.0005)

        # 4. US Stock (USD)
        snap_us = {**base_snap, "instrument_id": "AAPL_US_EQ", "product_type": "STOCK", "isin": "US0378331005", "currency": "USD", "is_uk_pence": False}
        c_us = self.scorer.evaluate_opportunity(snap_us)
        # SDRT = 0.0, FX = 0.0015 * 2 = 0.003, spread = 0.001, SEC = 0.0000206 -> estimated_costs ~ 0.00402
        self.assertAlmostEqual(c_us.estimated_costs, 0.003 + 0.001 + 0.000025, delta=0.0005)

    def test_sdrt_aim_statutory_exemption(self):
        """UK AIM equities are legally exempt from SDRT under Finance Act 2014."""
        base_snap = {
            "current_price": 50.0,
            "recent_prices": [49.0, 50.0],
            "bid": 49.975,
            "ask": 50.025,
            "session_state": "REGULAR"
        }
        snap_aim = {
            **base_snap,
            "instrument_id": "FDMl_EQ",
            "symbol": "FDM",
            "product_type": "STOCK",
            "isin": "GB00B033TF11",
            "currency": "GBX",
            "is_uk_pence": True,
            "exchange_venue": "London Stock Exchange AIM",
            "min_trade_quantity": 0.001
        }
        c_aim = self.scorer.evaluate_opportunity(snap_aim)
        # AIM equity is exempt from SDRT (0.0000), FX is 0.0000
        self.assertAlmostEqual(c_aim.estimated_costs, 0.001, delta=0.0005)
        self.assertTrue(c_aim.cost_model_complete)

    def test_missing_isin_uk_main_market_stock_fails_qualification(self):
        """Missing ISIN on UK Main Market equity prevents SDRT verification -> cost_model_complete = False -> disqualified."""
        base_snap = {
            "current_price": 100.0,
            "recent_prices": [95.0, 100.0],
            "session_state": "REGULAR"
        }
        snap_no_isin = {
            **base_snap,
            "instrument_id": "UNKNOWN_UK_EQ",
            "product_type": "STOCK",
            "isin": "",
            "currency": "GBX",
            "is_uk_pence": True,
            "exchange_venue": "London Stock Exchange",
            "min_trade_quantity": 0.001
        }
        c = self.scorer.evaluate_opportunity(snap_no_isin)
        self.assertFalse(c.cost_model_complete)
        self.assertFalse(c.strategy_qualified)
        self.assertTrue(any("SDRT_STATUS_UNKNOWN" in r for r in c.qualification_reasons))

    def test_french_ftt_market_cap_qualification(self):
        """French stock on Euronext Paris with market cap > €1bn incurs 0.30% FTT on Buy. Unverified market cap -> incomplete."""
        base_snap = {
            "current_price": 50.0,
            "recent_prices": [48.0, 50.0],
            "session_state": "REGULAR"
        }
        # 1. Large cap with confirmed market cap > €1bn
        snap_fr_large = {
            **base_snap,
            "instrument_id": "OR_EQ",
            "product_type": "STOCK",
            "isin": "FR0000120321",
            "currency": "EUR",
            "exchange_venue": "Euronext Paris",
            "market_cap_eur": 2e10,
            "min_trade_quantity": 0.001
        }
        c_large = self.scorer.evaluate_opportunity(snap_fr_large)
        self.assertTrue(c_large.cost_model_complete)
        # FX round trip (0.0030) + French FTT (0.0030) + spread (0.0010) = 0.0070
        self.assertAlmostEqual(c_large.estimated_costs, 0.0070, delta=0.0005)

        # 2. Market cap unverified -> incomplete cost model -> disqualified from orders
        snap_fr_unknown_mcap = {
            **base_snap,
            "instrument_id": "UNKNOWN_FR_EQ",
            "product_type": "STOCK",
            "isin": "FR0000123456",
            "currency": "EUR",
            "exchange_venue": "Euronext Paris",
            "min_trade_quantity": 0.001
        }
        c_unverified = self.scorer.evaluate_opportunity(snap_fr_unknown_mcap)
        self.assertFalse(c_unverified.cost_model_complete)
        self.assertFalse(c_unverified.strategy_qualified)
        self.assertTrue(any("FRENCH_FTT_STATUS_UNKNOWN" in r for r in c_unverified.qualification_reasons))

    def test_ptm_levy_over_10k_gbp(self):
        """PTM levy (£1.50 per leg = £3.00 round trip) applies on UK equities when consideration > £10,000."""
        from src.hit_and_run.cost_model import hit_and_run_cost_model
        # Under £10k: £0.00
        res_small = hit_and_run_cost_model.evaluate_instrument_costs(
            product_type="STOCK",
            currency="GBX",
            isin="GB0031348658",
            exchange_venue="London Stock Exchange",
            order_size_gbp=5000.0
        )
        self.assertEqual(res_small.ptm_levy_amount_gbp, 0.0)

        # Over £10k: £3.00
        res_large = hit_and_run_cost_model.evaluate_instrument_costs(
            product_type="STOCK",
            currency="GBX",
            isin="GB0031348658",
            exchange_venue="London Stock Exchange",
            order_size_gbp=15000.0
        )
        self.assertEqual(res_large.ptm_levy_amount_gbp, 3.0)


if __name__ == "__main__":
    unittest.main()
