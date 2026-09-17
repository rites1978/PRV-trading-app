"""
PRV Capital - Hit-and-Run Render Trading Build Readiness Tests
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Validates the four concrete defects required for the Render branch switch:
1. Databento current-data path
2. No Yahoo current-decision fallback
3. Persistent runner loop
4. Continued scanning after an exit
5. No max-daily-entry halt
6. No hard-coded FX fallback
"""
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.hit_and_run.models import HitAndRunEntryDecision


class TestRenderTradingBuildReadiness(unittest.TestCase):

    def test_01_databento_current_data_path(self):
        """Databento provider must parse live quote: price, bid, ask, spread, timestamp, freshness."""
        from src.data.databento_provider import DatabentoMarketDataProvider
        
        provider = DatabentoMarketDataProvider(api_key="mock-key-for-test")
        with patch.object(provider, "_fetch_from_sdk") as mock_fetch:
            mock_fetch.return_value = {
                "price": 225.50,
                "bid": 225.45,
                "ask": 225.55,
                "spread": 0.10,
                "timestamp": "2026-09-17T20:00:00Z",
                "freshness_seconds": 1.2
            }
            quote = provider.get_current_quote("AAPL")
            self.assertTrue(quote["success"])
            self.assertEqual(quote["provider"], "DATABENTO")
            self.assertEqual(quote["instrument"], "AAPL")
            self.assertEqual(quote["latest_price"], 225.50)
            self.assertEqual(quote["bid"], 225.45)
            self.assertEqual(quote["ask"], 225.55)
            self.assertEqual(quote["spread"], 0.10)

    def test_02_no_yahoo_current_decision_fallback(self):
        """When Databento is unavailable, current-decision path must fail closed and NEVER invoke Yahoo."""
        from src.data.databento_provider import DatabentoMarketDataProvider
        
        # Unconfigured provider (no key)
        provider = DatabentoMarketDataProvider(api_key=None)
        with patch("yfinance.Ticker") as mock_yf:
            quote = provider.get_current_quote("AAPL")
            self.assertFalse(quote["success"])
            self.assertEqual(quote["status"], "DATABENTO_API_KEY_MISSING")
            # Invariant: yfinance must NEVER be called as fallback for current decision
            mock_yf.assert_not_called()
            
            price = provider.get_current_executable_price("AAPL")
            self.assertIsNone(price)
            mock_yf.assert_not_called()

    def test_03_persistent_runner_loop(self):
        """Runner must not exit after 1 empty cycle; must loop continuously across iterations."""
        from scripts.run_demo_experiment import DemoExperimentRunner
        
        mock_dispatcher = MagicMock()
        mock_dispatcher.reconcile_broker_state.return_value = {
            "is_clean_slate": True,
            "positions_count": 0,
            "orders_count": 0
        }
        mock_strategy = MagicMock()
        mock_strategy.evaluate.return_value = []
        mock_strategy.MAX_CONCURRENT_POSITIONS = 1

        runner = DemoExperimentRunner(
            experiment_id="TEST-PERSISTENT-001",
            strategy_version="1.0-DEMO",
            strategy_module=mock_strategy,
            dispatcher=mock_dispatcher,
            audit_log_dir="/tmp/test_audit"
        )
        runner.pre_session_startup = MagicMock(return_value={"starting_cash": 50000.0, "starting_equity": 50000.0})

        with patch.object(runner, "is_session_ended", return_value=False):
            result = runner.run_continuous_session(max_iterations=3, poll_interval=0.01)

        self.assertEqual(result["cycles_completed"], 3)
        self.assertEqual(mock_strategy.evaluate.call_count, 3)

    def test_04_continued_scanning_after_exit(self):
        """After a holding exits, the runner must continue scanning in subsequent cycles."""
        from scripts.run_demo_experiment import DemoExperimentRunner
        
        mock_dispatcher = MagicMock()
        mock_dispatcher.execute_exit.return_value = {"success": True}
        
        mock_strategy = MagicMock()
        mock_strategy.MAX_CONCURRENT_POSITIONS = 1
        # Cycle 1: holding exits. Cycle 2: new entry evaluated and approved
        mock_strategy.evaluate_exit.return_value = (True, "TAKE_PROFIT")
        
        entry_decision = HitAndRunEntryDecision(
            decision="ENTER",
            instrument_id="AAPL_US_EQ",
            symbol="AAPL",
            feed_ticker="AAPL",
            intended_capital_gbp=50.0,
            intended_quantity=0.19,
            required_protective_level=220.0
        )
        mock_strategy.evaluate.return_value = [entry_decision]
        mock_dispatcher.execute_entry.return_value = {
            "success": True,
            "fill_price": 225.0,
            "filled_quantity": 0.19,
            "stop_order_id": "STOP_999",
            "stop_price": 220.50,
            "timestamp": "2026-09-17T20:00:00Z"
        }
        
        runner = DemoExperimentRunner(
            experiment_id="TEST-EXIT-SCAN-001",
            strategy_version="1.0-DEMO",
            strategy_module=mock_strategy,
            dispatcher=mock_dispatcher,
            audit_log_dir="/tmp/test_audit"
        )
        # Pre-seed active holding
        runner.active_holdings["AAPL_US_EQ"] = {
            "ticker": "AAPL_US_EQ",
            "fill_price": 220.0,
            "quantity": 0.19,
            "stop_order_id": "STOP_111",
            "stop_price": 215.60,
            "entry_time": "2026-09-17T19:00:00Z"
        }
        
        # Run cycle: should exit holding, then subsequent evaluation should allow new entries
        cycle1 = runner.run_scan_and_execute_cycle([])
        self.assertEqual(len(runner.active_holdings), 1)  # holding was entered after exit!
        self.assertEqual(mock_dispatcher.execute_exit.call_count, 1)
        self.assertEqual(mock_dispatcher.execute_entry.call_count, 1)

    def test_05_no_max_daily_entry_halt(self):
        """MAX_DAILY_ENTRIES must be None; strategy must NOT halt after 3 entries."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        mock_market_data = MagicMock()
        strategy = DemoStrategyV1(market_data_provider=mock_market_data)
        
        # Verify MAX_DAILY_ENTRIES is None
        self.assertIsNone(strategy.MAX_DAILY_ENTRIES)
        
        # Record 3 entries
        strategy.record_entry()
        strategy.record_entry()
        strategy.record_entry()
        self.assertEqual(strategy.daily_entries_count, 3)
        
        # Record 4th and 5th entries
        strategy.record_entry()
        strategy.record_entry()
        self.assertEqual(strategy.daily_entries_count, 5)
        
        # In-window check: must NOT block with DAILY_LIMIT_REACHED
        tz_ny = ZoneInfo("America/New_York")
        midday = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()
        
        # Setup valid market data and FX
        df = pd.DataFrame({
            "Open": [300.0] * 30,
            "High": [305.0] * 30,
            "Low": [299.0] * 30,
            "Close": [304.0] * 30,
            "Volume": [10000] * 30
        }, index=pd.date_range("2026-09-17 09:30", periods=30, freq="5min", tz="America/New_York"))
        mock_market_data.fetch_history.return_value = df
        
        # Even with 5 entries today, evaluate_entry does not fail with DAILY_LIMIT_REACHED
        dec = strategy.evaluate_entry(now_time=midday, fx_gbpusd=1.33)
        self.assertNotIn("DAILY_LIMIT_REACHED", dec.no_entry_reason or "")

    def test_06_no_hardcoded_fx_fallback(self):
        """demo_strategy_v1 must require authoritative FX rate; fail closed with PRODUCT_FAILURE if missing."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        strategy = DemoStrategyV1(market_data_provider=MagicMock())
        
        # When FX is missing or None
        tz_ny = ZoneInfo("America/New_York")
        midday = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()
        
        df = pd.DataFrame({
            "Open": [300.0] * 30,
            "High": [305.0] * 30,
            "Low": [299.0] * 30,
            "Close": [304.0] * 30,
            "Volume": [10000] * 30
        }, index=pd.date_range("2026-09-17 09:30", periods=30, freq="5min", tz="America/New_York"))
        strategy.market_data.fetch_history.return_value = df
        
        # Call with fx_gbpusd = None and no fx_provider configured
        strategy.fx_provider = None
        dec = strategy.evaluate_entry(now_time=midday, fx_gbpusd=None)
        self.assertEqual(dec.decision, "NO_ENTRY")
        self.assertIn("PRODUCT_FAILURE: FX_CONVERSION_RATE_UNAVAILABLE", dec.no_entry_reason)
        
        # Call calculate_quantity directly with None: must raise ValueError or return 0.0 with product failure
        qty = strategy.calculate_quantity(current_price_usd=225.0, fx_gbpusd=None)
        self.assertEqual(qty, 0.0)


if __name__ == "__main__":
    unittest.main()
