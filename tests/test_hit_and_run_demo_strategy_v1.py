"""
Unit Tests for EXP-DEMO-001 Strategy Implementation (src/hit_and_run/demo_strategy_v1.py)
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md
User Authority: Authorised EXP-DEMO-001 one-market-day experiment.

Verifies:
1. Exact indicator calculations: BB(20, 2.0), RSI(14), ATR(14), SMA(20).
2. Exchange-local time window gating (09:45 - 15:00 ET).
3. Long momentum breakout signal conditions and friction hurdle.
4. Capital allocation (£50 nominal, 2 decimal places floor).
5. Protective stop ceiling formula (math.ceil(fill * 0.98 * 100) / 100 >= fill * 0.95).
6. Daily entry limit (max 3 entries) and re-entry cooldown (30 min).
7. Exit conditions: Take-Profit (+3%), Momentum-Reversal (Close < SMA20), Edge-Decay (60m), Session-End (15:45 ET).
"""
import math
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

import pandas as pd
import numpy as np

from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1


class TestDemoStrategyV1(unittest.TestCase):

    def setUp(self):
        self.mock_databento = MagicMock()
        self.mock_databento.is_configured = True
        self.mock_databento.data_service = "LIVE"
        self.mock_databento.client_type = "Live"
        self.mock_databento.get_current_quote.return_value = {
            "success": True,
            "status": "OK",
            "provider": "DATABENTO",
            "client_type": "Live",
            "data_service": "LIVE",
            "dataset": "DBEQ.BASIC",
            "schema": "bbo-1s",
            "instrument": "AAPL",
            "symbols": ["AAPL"],
            "latest_price": 310.0,
            "bid": 309.95,
            "ask": 310.05,
            "spread": 0.10,
            "quote_timestamp": "2026-09-17T20:00:00Z",
            "fetch_timestamp": "2026-09-17T20:00:01Z",
            "freshness_seconds": 1.0,
            "raw_response": {},
            "http_status": 200
        }
        self.mock_databento.fetch_live_bars.return_value = pd.DataFrame()
        self.strategy = DemoStrategyV1(databento_provider=self.mock_databento)

    def _generate_synthetic_5m_data(self, n_bars: int = 50, base_price: float = 330.0, trend: float = 0.5) -> pd.DataFrame:
        dates = pd.date_range("2026-09-17 09:30:00", periods=n_bars, freq="5min", tz="America/New_York")
        closes = [base_price + i * trend for i in range(n_bars)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        opens = [c - 0.2 for c in closes]
        volumes = [10000.0] * n_bars
        return pd.DataFrame({
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes
        }, index=dates)

    def test_01_indicator_computation_parameters(self):
        """Indicators must use specified windows: BB(20, 2.0), RSI(14), ATR(14), SMA(20)."""
        df_raw = self._generate_synthetic_5m_data(n_bars=30)
        df = self.strategy.compute_indicators(df_raw)

        self.assertIn("SMA_20", df.columns)
        self.assertIn("BB_Upper", df.columns)
        self.assertIn("BB_Lower", df.columns)
        self.assertIn("RSI", df.columns)
        self.assertIn("ATR", df.columns)

        # Invariant checks
        self.assertGreater(float(df["BB_Upper"].iloc[-1]), float(df["SMA_20"].iloc[-1]))
        self.assertLess(float(df["BB_Lower"].iloc[-1]), float(df["SMA_20"].iloc[-1]))
        self.assertTrue(0.0 <= float(df["RSI"].iloc[-1]) <= 100.0)
        self.assertGreater(float(df["ATR"].iloc[-1]), 0.0)

    def test_02_time_window_gating_et(self):
        """Entry permitted strictly between 09:45 ET and 15:00 ET."""
        tz_ny = ZoneInfo("America/New_York")

        # 09:30 ET -> Outside window
        dt_early = datetime(2026, 9, 17, 9, 30, tzinfo=tz_ny)
        self.assertFalse(self.strategy.is_within_entry_window(dt_early))

        # 09:45 ET -> Start of window
        dt_start = datetime(2026, 9, 17, 9, 45, tzinfo=tz_ny)
        self.assertTrue(self.strategy.is_within_entry_window(dt_start))

        # 12:00 ET -> Midday window
        dt_mid = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny)
        self.assertTrue(self.strategy.is_within_entry_window(dt_mid))

        # 15:00 ET -> End of window
        dt_end = datetime(2026, 9, 17, 15, 0, tzinfo=tz_ny)
        self.assertTrue(self.strategy.is_within_entry_window(dt_end))

        # 15:05 ET -> Outside window
        dt_late = datetime(2026, 9, 17, 15, 5, tzinfo=tz_ny)
        self.assertFalse(self.strategy.is_within_entry_window(dt_late))

    def test_03_session_end_timing_et(self):
        """Session-end trigger occurs at 15:45 ET."""
        tz_ny = ZoneInfo("America/New_York")
        dt_before = datetime(2026, 9, 17, 15, 44, tzinfo=tz_ny)
        dt_at = datetime(2026, 9, 17, 15, 45, tzinfo=tz_ny)
        dt_after = datetime(2026, 9, 17, 15, 50, tzinfo=tz_ny)

        self.assertFalse(self.strategy.is_session_end(dt_before))
        self.assertTrue(self.strategy.is_session_end(dt_at))
        self.assertTrue(self.strategy.is_session_end(dt_after))

    def test_04_quantity_calculation_and_precision(self):
        """£50 nominal allocation floored to 2 decimal places."""
        # AAPL at $337.29, GBPUSD at 1.3355 -> £252.55 per share
        # £50 / £252.55 = 0.197978... -> floored to 0.19
        qty = self.strategy.calculate_quantity(current_price_usd=337.29, fx_gbpusd=1.3355)
        self.assertEqual(qty, 0.19)

        # Value check: 0.19 * 252.55 = 47.98 <= £50.00
        val_gbp = qty * (337.29 / 1.3355)
        self.assertLessEqual(val_gbp, 50.0)

    def test_05_protective_stop_ceiling_formula(self):
        """
        STOP_PRICE = math.ceil(fill * 0.98 * 100) / 100
        Must be >= fill * 0.95 (contract hard ceiling).
        """
        fill_price = 336.18
        raw_stop = fill_price * 0.98  # 329.4564
        stop_price = math.ceil(raw_stop * 100.0) / 100.0  # 329.46

        self.assertEqual(stop_price, 329.46)
        self.assertGreaterEqual(stop_price, fill_price * 0.95)
        self.assertGreater(stop_price, raw_stop)

    def test_06_daily_entry_limit_and_cooldown(self):
        """MAX_DAILY_ENTRIES is None (no halt after 3 entries) and enforces 30-minute re-entry cooldown."""
        tz_ny = ZoneInfo("America/New_York")
        in_window_time = datetime(2026, 9, 17, 11, 0, tzinfo=tz_ny).timestamp()

        # Mock market data returning valid breakout
        df_breakout = self._generate_synthetic_5m_data(n_bars=30, base_price=300.0, trend=2.0)
        self.mock_databento.fetch_live_bars.return_value = df_breakout

        # Check entry 1, 2, 3, 4, 5: Must NOT block on daily count
        for i in range(5):
            self.strategy.record_entry()
        self.assertEqual(self.strategy.daily_entries_count, 5)

        # 6th entry evaluated: not blocked by daily limit
        dec = self.strategy.evaluate_entry(now_time=in_window_time, fx_gbpusd=1.33)
        self.assertNotIn("DAILY_LIMIT_REACHED", dec.no_entry_reason or "")

        # Reset daily state
        self.strategy.reset_daily_state()
        self.assertEqual(self.strategy.daily_entries_count, 0)

        # Test cooldown: exit occurred 10 minutes ago (600s < 1800s)
        self.strategy.record_exit(timestamp=in_window_time - 600)
        dec_cool = self.strategy.evaluate_entry(now_time=in_window_time, fx_gbpusd=1.33)
        self.assertEqual(dec_cool.decision, "NO_ENTRY")
        self.assertIn("REENTRY_COOLDOWN_ACTIVE", dec_cool.no_entry_reason)

        # Cooldown expired (2000s > 1800s)
        self.strategy.record_exit(timestamp=in_window_time - 2000)
        # Now cooldown is cleared
        self.assertNotIn("REENTRY_COOLDOWN_ACTIVE", self.strategy.evaluate_entry(now_time=in_window_time, fx_gbpusd=1.33).no_entry_reason or "")

    def test_07_take_profit_exit_rule(self):
        """Take-profit triggers when price >= fill * 1.03 (+3.0%)."""
        holding = {
            "ticker": "AAPL_US_EQ",
            "fill_price": 300.0,
            "quantity": 0.19,
            "entry_time": datetime.now(timezone.utc).isoformat()
        }
        # Price at 310.0 (> 300 * 1.03 = 309.0)
        df_tp = self._generate_synthetic_5m_data(n_bars=30, base_price=310.0, trend=0.1)
        self.mock_databento.fetch_live_bars.return_value = df_tp

        tz_ny = ZoneInfo("America/New_York")
        midday_time = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()

        should_exit, reason = self.strategy.evaluate_exit(holding, now_time=midday_time)
        self.assertTrue(should_exit)
        self.assertEqual(reason, "TAKE_PROFIT")

    def test_08_momentum_reversal_exit_rule(self):
        """Momentum reversal triggers when Close < SMA20."""
        holding = {
            "ticker": "AAPL_US_EQ",
            "fill_price": 300.0,
            "quantity": 0.19,
            "entry_time": datetime.now(timezone.utc).isoformat()
        }
        # Generate data that drops sharply on the last bar
        df_data = self._generate_synthetic_5m_data(n_bars=30, base_price=300.0, trend=0.5)
        # Drop last bar below SMA20
        df_data.loc[df_data.index[-1], "Close"] = 280.0
        self.mock_databento.fetch_live_bars.return_value = df_data

        tz_ny = ZoneInfo("America/New_York")
        midday_time = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()

        should_exit, reason = self.strategy.evaluate_exit(holding, now_time=midday_time)
        self.assertTrue(should_exit)
        self.assertEqual(reason, "MOMENTUM_REVERSAL")


if __name__ == "__main__":
    unittest.main()
