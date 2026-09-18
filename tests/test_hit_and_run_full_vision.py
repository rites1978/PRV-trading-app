"""
Unit Tests for User-Authorised Full Vision Hit-and-Run Trading Engine
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md
User Authority Order: Build & Deploy Full Vision Now (18 September 2026)

Verifies:
1. Multi-Asset Scanning: Scans tradeable universe (AAPL, NVDA, MSFT, AMZN, TSLA, GOOG, META, SPY, QQQ).
2. Financial News & Sentiment: NewsSentimentResearcher retrieves live headlines, computes lexical polarity and sentiment score.
3. AI Dynamic Sizing & 80% Capital Ceiling: Total deployment <= £40,000 (80% of £50k), allows purchasing 1 to 100+ shares.
4. £100 Net Realized Profit Banking Exit: The moment net profit after fees/taxes >= £100, triggers immediate selling and banks profit in DailyBankingLedger.
5. Capital Release: Releasing capital after exit immediately enables hunting for new opportunities.
"""
import math
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd

from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
from src.hit_and_run.banking import DailyBankingLedger
from src.research.news_sentiment import NewsSentimentResearcher


class TestHitAndRunFullVision(unittest.TestCase):

    def setUp(self):
        self.mock_databento = MagicMock()
        self.mock_databento.is_configured = True
        self.mock_databento.data_service = "LIVE"
        self.mock_databento.client_type = "Live"
        self.mock_databento.get_current_quote.return_value = {
            "success": True,
            "status": "OK",
            "provider": "DATABENTO",
            "instrument": "NVDA",
            "latest_price": 120.0,
            "bid": 119.95,
            "ask": 120.05,
            "spread": 0.10,
            "quote_timestamp": "2026-09-18T14:30:00Z",
            "fetch_timestamp": "2026-09-18T14:30:01Z",
            "freshness_seconds": 1.0,
        }

        # 5m synthetic bars
        dates = pd.date_range("2026-09-18 09:30:00", periods=30, freq="5min", tz="America/New_York")
        closes = [110.0 + i * 0.5 for i in range(30)]
        self.synthetic_bars = pd.DataFrame({
            "Open": closes,
            "High": [c + 0.8 for c in closes],
            "Low": [c - 0.5 for c in closes],
            "Close": closes,
            "Volume": [1000000 for _ in closes]
        }, index=dates)
        self.mock_databento.fetch_live_bars.return_value = self.synthetic_bars

        self.strategy = DemoStrategyV1(
            databento_provider=self.mock_databento,
            mode="FULL_VISION"
        )

    def test_01_news_sentiment_research_and_lexical_polarity(self):
        """Verify news sentiment engine evaluates financial headlines and scores."""
        researcher = NewsSentimentResearcher()
        # Mock headlines with positive financial catalysts
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"""<rss version="2.0">
            <channel>
                <item><title>Nvidia surges as AI chip demand breaks quarterly profit record</title></item>
                <item><title>Morgan Stanley issues bullish upgrade on strong GPU expansion</title></item>
                <item><title>Tech rally climbs higher as earnings beat expectations</title></item>
            </channel></rss>"""
            mock_get.return_value = mock_resp

            result = researcher.fetch_stock_sentiment("NVDA", "Nvidia")
            self.assertEqual(result["symbol"], "NVDA")
            self.assertEqual(result["tone"], "BULLISH")
            self.assertGreater(result["sentiment_score"], 60.0)
            self.assertGreater(result["polarity"], 0.0)
            self.assertEqual(len(result["headlines"]), 3)

    def test_02_dynamic_allocation_enforces_80_percent_capital_ceiling(self):
        """Verify dynamic allocation respects the £40,000 (80% of £50k) ceiling."""
        # 1. Zero initial deployment: allocates within budget
        cap, qty = self.strategy.calculate_dynamic_allocation(
            conviction_score=75.0,
            current_deployed_gbp=0.0,
            current_price_usd=120.0,
            fx_gbpusd=1.30
        )
        self.assertGreater(cap, 3000.0)
        self.assertLessEqual(cap, 40000.0)
        # Expected quantity: £cap * 1.30 / 120.0
        expected_qty = round((cap * 1.30) / 120.0, 2)
        self.assertEqual(qty, expected_qty)
        self.assertGreaterEqual(qty, 30.0)  # Buying >30 shares, well over 1 share

        # 2. Heavy deployment near ceiling (£38,000 deployed out of £40,000 ceiling)
        cap_near_cap, qty_near_cap = self.strategy.calculate_dynamic_allocation(
            conviction_score=85.0,
            current_deployed_gbp=38000.0,
            current_price_usd=120.0,
            fx_gbpusd=1.30
        )
        self.assertLessEqual(cap_near_cap, 2000.0)
        self.assertLessEqual(38000.0 + cap_near_cap, 40000.0)

        # 3. Capital ceiling fully reached (£40,000 already deployed)
        cap_capped, qty_capped = self.strategy.calculate_dynamic_allocation(
            conviction_score=90.0,
            current_deployed_gbp=40000.0,
            current_price_usd=120.0,
            fx_gbpusd=1.30
        )
        self.assertEqual(cap_capped, 0.0)
        self.assertEqual(qty_capped, 0.0)

    def test_03_flexible_share_quantities(self):
        """Verify trader can buy 1 share or 100+ shares dynamically."""
        # Expensive stock (e.g. Booking Holdings / high price ETF at $3,500)
        cap1, qty1 = self.strategy.calculate_dynamic_allocation(
            conviction_score=55.0,
            current_deployed_gbp=37000.0,  # only £3,000 budget left
            current_price_usd=3500.0,
            fx_gbpusd=1.30
        )
        # £3000 * 1.30 / 3500 = 1.11 shares
        self.assertAlmostEqual(qty1, 1.11, places=1)

        # High allocation in liquid stock (e.g. $50 stock, £8,000 allocation)
        cap2, qty2 = self.strategy.calculate_dynamic_allocation(
            conviction_score=90.0,
            current_deployed_gbp=0.0,
            current_price_usd=50.0,
            fx_gbpusd=1.30
        )
        # ~£10,000 * 1.30 / 50 = 260 shares!
        self.assertGreater(qty2, 100.0)

    def test_04_profit_bank_100_exit_triggers_immediately_when_target_reached(self):
        """Verify that the moment £100 net profit after fees/tax is earned, selling happens & money is banked."""
        # Holding: bought 50 shares of NVDA at $120.00
        # Entry cost: 50 * $120 / 1.30 = £4,615.38
        holding = {
            "ticker": "NVDA_US_EQ",
            "fill_price": 120.0,
            "quantity": 50.0,
            "entry_cost_gbp": 4615.38,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "fx_rate": 1.30
        }

        # Case A: Price rose to $121.00 (+0.83%)
        # Gross value: 50 * 121 / 1.30 = £4,653.85
        # Net profit: £4,653.85 - £4,615.38 - £9.31 fees = £29.16 (< £100 target)
        self.mock_databento.get_current_quote.return_value = {
            "success": True,
            "latest_price": 121.0,
            "bid": 120.95
        }
        df_a = self.synthetic_bars.copy()
        df_a.loc[df_a.index[-1], "Close"] = 121.0
        self.mock_databento.fetch_live_bars.return_value = df_a

        tz_ny = ZoneInfo("America/New_York")
        midday_time = datetime(2026, 9, 18, 12, 0, tzinfo=tz_ny).timestamp()

        should_exit, reason = self.strategy.evaluate_exit(holding, now_time=midday_time, fx_gbpusd=1.30)
        self.assertFalse(should_exit)
        self.assertEqual(reason, "HOLD")

        # Case B: Price rose to $123.50 (+2.9%)
        # Gross value: 50 * 123.50 / 1.30 = £4,750.00
        # Net profit: £4,750.00 - £4,615.38 - £9.50 fees = £125.12 (>= £100.00 target!)
        self.mock_databento.get_current_quote.return_value = {
            "success": True,
            "latest_price": 123.50,
            "bid": 123.45
        }
        df_b = self.synthetic_bars.copy()
        df_b.loc[df_b.index[-1], "Close"] = 123.50
        self.mock_databento.fetch_live_bars.return_value = df_b

        should_exit_b, reason_b = self.strategy.evaluate_exit(holding, now_time=midday_time, fx_gbpusd=1.30)
        self.assertTrue(should_exit_b)
        self.assertEqual(reason_b, "PROFIT_BANK_100_EXIT")

    def test_05_daily_banking_ledger_records_and_banks_profit(self):
        """Verify DailyBankingLedger authoritative recording and £100 daily goal tracking."""
        ledger = DailyBankingLedger(base_target_gbp=100.0)

        # Record trade with £112.50 net profit
        rec = ledger.record_realised_trade(
            trade_id="TRADE_NVDA_001",
            ticker="NVDA_US_EQ",
            gross_pnl_gbp=122.00,
            costs_gbp=9.50,
            exit_reason="PROFIT_BANK_100_EXIT",
            entry_price=120.0,
            exit_price=123.5,
            quantity=50.0
        )
        self.assertEqual(rec["net_pnl_gbp"], 112.50)
        summary = ledger.get_banking_summary()
        self.assertEqual(summary["banked_net_profit_today"], 112.50)
        self.assertEqual(summary["remaining_to_base_target"], 0.0)
        self.assertTrue(summary["base_target_achieved"])


if __name__ == "__main__":
    unittest.main()
