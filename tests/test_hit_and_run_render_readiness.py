"""
PRV Capital - Hit-and-Run Render Trading Build Readiness Tests
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Validates the four concrete defects required for the Render branch switch:
1. Databento current-data path and zero Yahoo active decision calls at strategy level
2. Enforced Complete Quote Gate (BBO required; trades-only rejected; live spread hurdle)
3. Authoritative FX source wired into real runner and strategy singleton
4. Render application startup autostarts EXP-DEMO-001 runner in persistent loop (not legacy quant_engine)
"""
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.hit_and_run.models import HitAndRunEntryDecision


def _create_mock_databento_provider(bid=225.45, ask=225.55, spread=0.10, is_configured=True, success=True):
    mock_db = MagicMock()
    mock_db.is_configured = is_configured
    if success:
        mock_db.get_current_quote.return_value = {
            "success": True,
            "status": "OK",
            "provider": "DATABENTO",
            "dataset": "DBEQ.BASIC",
            "instrument": "AAPL",
            "latest_price": 225.50,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "quote_timestamp": "2026-09-17T20:00:00Z",
            "fetch_timestamp": "2026-09-17T20:00:01Z",
            "freshness_seconds": 1.0,
            "http_status": 200
        }
        df_bars = pd.DataFrame({
            "Open": [220.0] * 30,
            "High": [226.0] * 30,
            "Low": [219.0] * 30,
            "Close": [225.50] * 30,
            "Volume": [50000] * 30
        }, index=pd.date_range("2026-09-17 09:30", periods=30, freq="5min", tz="America/New_York"))
        mock_db.fetch_live_bars.return_value = df_bars
    else:
        mock_db.get_current_quote.return_value = {
            "success": False,
            "status": "DATABENTO_BBO_UNAVAILABLE",
            "provider": "DATABENTO",
            "dataset": "DBEQ.BASIC",
            "instrument": "AAPL",
            "bid": None,
            "ask": None,
            "spread": None,
            "quote_timestamp": None,
            "fetch_timestamp": "2026-09-17T20:00:01Z",
            "freshness_seconds": None,
            "error": "BBO quote unavailable"
        }
        mock_db.fetch_live_bars.return_value = pd.DataFrame()
    return mock_db


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
                "quote_timestamp": "2026-09-17T20:00:00Z",
                "fetch_timestamp": "2026-09-17T20:00:01Z",
                "freshness_seconds": 1.0
            }
            quote = provider.get_current_quote("AAPL")
            self.assertTrue(quote["success"])
            self.assertEqual(quote["provider"], "DATABENTO")
            self.assertEqual(quote["instrument"], "AAPL")
            self.assertEqual(quote["latest_price"], 225.50)
            self.assertEqual(quote["bid"], 225.45)
            self.assertEqual(quote["ask"], 225.55)
            self.assertEqual(quote["spread"], 0.10)
            self.assertEqual(quote["quote_timestamp"], "2026-09-17T20:00:00Z")
            self.assertEqual(quote["fetch_timestamp"], "2026-09-17T20:00:01Z")

    def test_02_no_yahoo_current_decision_fallback(self):
        """When Databento is unavailable, current-decision path must fail closed and NEVER invoke Yahoo."""
        from src.data.databento_provider import DatabentoMarketDataProvider
        
        # Unconfigured provider (no key)
        provider = DatabentoMarketDataProvider(api_key=None)
        with patch("yfinance.Ticker") as mock_yf:
            quote = provider.get_current_quote("AAPL")
            self.assertFalse(quote["success"])
            self.assertEqual(quote["status"], "DATABENTO_API_KEY_MISSING")
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
        runner.active_holdings["AAPL_US_EQ"] = {
            "ticker": "AAPL_US_EQ",
            "fill_price": 220.0,
            "quantity": 0.19,
            "stop_order_id": "STOP_111",
            "stop_price": 215.60,
            "entry_time": "2026-09-17T19:00:00Z"
        }
        
        cycle1 = runner.run_scan_and_execute_cycle([])
        self.assertEqual(len(runner.active_holdings), 1)
        self.assertEqual(mock_dispatcher.execute_exit.call_count, 1)
        self.assertEqual(mock_dispatcher.execute_entry.call_count, 1)

    def test_05_no_max_daily_entry_halt(self):
        """MAX_DAILY_ENTRIES must be None; strategy must NOT halt after 3 entries."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        mock_databento = _create_mock_databento_provider()
        strategy = DemoStrategyV1(databento_provider=mock_databento)
        
        self.assertIsNone(strategy.MAX_DAILY_ENTRIES)
        
        for _ in range(5):
            strategy.record_entry()
        self.assertEqual(strategy.daily_entries_count, 5)
        
        tz_ny = ZoneInfo("America/New_York")
        midday = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()
        
        dec = strategy.evaluate_entry(now_time=midday, fx_gbpusd=1.33)
        self.assertNotIn("DAILY_LIMIT_REACHED", dec.no_entry_reason or "")

    def test_06_no_hardcoded_fx_fallback(self):
        """demo_strategy_v1 must require authoritative FX rate; fail closed with PRODUCT_FAILURE if missing."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        mock_databento = _create_mock_databento_provider()
        strategy = DemoStrategyV1(databento_provider=mock_databento, fx_provider=None)
        
        tz_ny = ZoneInfo("America/New_York")
        midday = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()
        
        dec = strategy.evaluate_entry(now_time=midday, fx_gbpusd=None)
        self.assertEqual(dec.decision, "NO_ENTRY")
        self.assertIn("PRODUCT_FAILURE: FX_CONVERSION_RATE_UNAVAILABLE", dec.no_entry_reason)
        
        qty = strategy.calculate_quantity(current_price_usd=225.0, fx_gbpusd=None)
        self.assertEqual(qty, 0.0)

    def test_07_strategy_level_no_yahoo_when_databento_unavailable(self):
        """Strategy-level test proving DemoStrategyV1.evaluate_entry() NEVER calls Yahoo when Databento is unavailable."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        mock_market_data = MagicMock()
        mock_databento = MagicMock()
        mock_databento.is_configured = False
        mock_databento.get_current_quote.return_value = {
            "success": False,
            "status": "DATABENTO_API_KEY_MISSING",
            "provider": "DATABENTO",
            "error": "DATABENTO_API_KEY is not configured"
        }
        
        strategy = DemoStrategyV1(
            market_data_provider=mock_market_data,
            databento_provider=mock_databento,
            fx_provider=None
        )
        
        tz_ny = ZoneInfo("America/New_York")
        midday = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()
        
        dec = strategy.evaluate_entry(now_time=midday, fx_gbpusd=1.33)
        self.assertEqual(dec.decision, "NO_ENTRY")
        self.assertIn("PRODUCT_FAILURE: DATABENTO_LIVE_DATA_UNAVAILABLE", dec.no_entry_reason)
        
        # Invariant: Yahoo/market_data.fetch_history was NEVER invoked for active decision
        mock_market_data.fetch_history.assert_not_called()

    def test_08_complete_quote_gate_enforcement(self):
        """Complete Quote Gate: requires bid, ask, spread > 0, timestamps; rejects trades-only responses."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        # Test Case A: Databento falls back to trades only (bid, ask, spread are None)
        mock_databento_trades_only = MagicMock()
        mock_databento_trades_only.is_configured = True
        mock_databento_trades_only.get_current_quote.return_value = {
            "success": False,
            "status": "DATABENTO_BBO_UNAVAILABLE",
            "provider": "DATABENTO",
            "bid": None,
            "ask": None,
            "spread": None,
            "quote_timestamp": None,
            "fetch_timestamp": "2026-09-17T20:00:00Z",
            "freshness_seconds": None,
            "error": "Trades-only cannot be treated as an executable quote"
        }
        
        strategy_trades = DemoStrategyV1(databento_provider=mock_databento_trades_only)
        tz_ny = ZoneInfo("America/New_York")
        midday = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()
        
        dec_trades = strategy_trades.evaluate_entry(now_time=midday, fx_gbpusd=1.33)
        self.assertEqual(dec_trades.decision, "NO_ENTRY")
        self.assertIn("DATABENTO_LIVE_DATA_UNAVAILABLE", dec_trades.no_entry_reason)
        
        # Test Case B: Partial quote (missing ask/spread)
        mock_databento_partial = MagicMock()
        mock_databento_partial.is_configured = True
        mock_databento_partial.get_current_quote.return_value = {
            "success": True,
            "status": "OK",
            "provider": "DATABENTO",
            "latest_price": 225.0,
            "bid": 225.0,
            "ask": None,
            "spread": None,
            "quote_timestamp": "2026-09-17T20:00:00Z",
            "fetch_timestamp": "2026-09-17T20:00:01Z",
            "freshness_seconds": 1.0
        }
        strategy_partial = DemoStrategyV1(databento_provider=mock_databento_partial)
        dec_partial = strategy_partial.evaluate_entry(now_time=midday, fx_gbpusd=1.33)
        self.assertEqual(dec_partial.decision, "NO_ENTRY")
        self.assertIn("DATABENTO_BBO_UNAVAILABLE", dec_partial.no_entry_reason)

    def test_09_authoritative_fx_wired_to_runner_and_singleton(self):
        """Verify fx_provider is wired into singleton demo_strategy_v1 and runner passes resolved FX."""
        from src.hit_and_run.demo_strategy_v1 import demo_strategy_v1
        from scripts.run_demo_experiment import DemoExperimentRunner
        
        # Verify singleton has fx_provider wired
        self.assertIsNotNone(demo_strategy_v1.fx_provider)
        self.assertTrue(hasattr(demo_strategy_v1.fx_provider, "get_gbp_usd_rate") or hasattr(demo_strategy_v1.fx_provider, "get_rate"))
        
        # Verify runner passes resolved FX into strategy evaluate
        mock_strategy = MagicMock()
        mock_strategy.fx_provider = MagicMock()
        mock_strategy.fx_provider.get_gbp_usd_rate.return_value = 1.345
        mock_strategy.evaluate.return_value = []
        mock_strategy.MAX_CONCURRENT_POSITIONS = 1
        
        mock_dispatcher = MagicMock()
        runner = DemoExperimentRunner(
            experiment_id="TEST-FX-WIRE-001",
            strategy_version="1.0-DEMO",
            strategy_module=mock_strategy,
            dispatcher=mock_dispatcher,
            audit_log_dir="/tmp/test_audit"
        )
        runner.run_scan_and_execute_cycle([])
        
        mock_strategy.evaluate.assert_called_once()
        _, kwargs = mock_strategy.evaluate.call_args
        self.assertEqual(kwargs.get("fx_gbpusd"), 1.345)

    def test_10_render_startup_routes_to_exp_demo_001_runner(self):
        """Verify on_startup routes to EXP-DEMO-001 runner on DEMO autorun and leaves legacy quant_engine unstarted."""
        from src.api.routes import on_startup
        from src.core.engine import quant_engine
        
        with patch("src.api.routes.autonomous_engine_autostart_allowed", return_value=(True, "Approved opt-in")), \
             patch("src.api.routes.broker.start_background_sync"), \
             patch("src.api.routes.threading.Thread") as mock_thread, \
             patch.object(quant_engine, "start") as mock_legacy_start, \
             patch.dict("os.environ", {"TRADING_ENV": "demo", "PRV_AUTORUN_HIT_AND_RUN": "true", "PRV_ACTIVE_STRATEGY": "EXP-DEMO-001", "PRV_TESTING": "false"}), \
             patch("sys.modules", {}):
            
            on_startup()
            
            # Verify legacy quant_engine was NOT started
            mock_legacy_start.assert_not_called()
            # Verify background worker thread was launched
            mock_thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()
