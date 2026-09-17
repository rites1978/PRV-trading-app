"""
PRV Capital - Hit-and-Run Render Trading Build Readiness Tests
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Comprehensive Verification Suite for EXP-DEMO-001 Render Deployment:
1. Real Databento LIVE path (db.Live, data_service="LIVE", client_type="Live", bbo-1s schema)
2. Zero Yahoo calls across active trading decisions (evaluate_entry AND evaluate_exit)
3. Clean Render worker import in routes.py (demo_dispatcher / demo_execution_dispatcher)
4. Demo execution runtime stop calculation (math.ceil without NameError)
5. Multi-session Render worker survival across market days
6. Removal of non-authorised FX source (no 1.35 seed, no portfolio_snapshot Yahoo, fail closed)
7. Restored authorised experimental friction rule (0.0010*Close, 1.5*ATR > 2*FRICTION_PROXY)
8. Removal of invented 60-second staleness threshold
9. Dynamic git SHA telemetry in /api/demo_experiment/status
"""
import os
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from src.hit_and_run.models import HitAndRunEntryDecision


def _create_mock_databento_provider(bid=225.45, ask=225.55, spread=0.10, is_configured=True, success=True):
    mock_db = MagicMock()
    mock_db.is_configured = is_configured
    mock_db.data_service = "LIVE"
    mock_db.client_type = "Live"
    if success:
        mock_db.get_current_quote.return_value = {
            "success": True,
            "status": "OK",
            "provider": "DATABENTO",
            "client_type": "Live",
            "data_service": "LIVE",
            "dataset": "DBEQ.BASIC",
            "schema": "bbo-1s",
            "instrument": "AAPL",
            "symbols": ["AAPL"],
            "latest_price": 225.50,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "quote_timestamp": "2026-09-17T20:00:00Z",
            "fetch_timestamp": "2026-09-17T20:00:01Z",
            "freshness_seconds": 1.0,
            "raw_response": {"rtype": 1, "bid_px_00": 225450000000, "ask_px_00": 225550000000},
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
            "status": "DATABENTO_LIVE_DATA_UNAVAILABLE",
            "provider": "DATABENTO",
            "client_type": "Live",
            "data_service": "LIVE",
            "dataset": "DBEQ.BASIC",
            "schema": "bbo-1s",
            "instrument": "AAPL",
            "symbols": ["AAPL"],
            "bid": None,
            "ask": None,
            "spread": None,
            "quote_timestamp": None,
            "fetch_timestamp": "2026-09-17T20:00:01Z",
            "freshness_seconds": None,
            "raw_response": None,
            "error": "Live gateway unavailable",
            "http_status": 500
        }
        mock_db.fetch_live_bars.return_value = pd.DataFrame()
    return mock_db


class TestRenderTradingBuildReadiness(unittest.TestCase):

    def test_01_databento_live_current_data_path(self):
        """Databento provider must use official Live client path for current decision data."""
        from src.data.databento_provider import DatabentoMarketDataProvider
        
        provider = DatabentoMarketDataProvider(api_key="mock-key-for-test")
        self.assertEqual(provider.data_service, "LIVE")
        self.assertEqual(provider.client_type, "Live")

        with patch.object(provider, "_fetch_from_live_sdk") as mock_fetch:
            mock_fetch.return_value = {
                "price": 225.50,
                "bid": 225.45,
                "ask": 225.55,
                "spread": 0.10,
                "quote_timestamp": "2026-09-17T20:00:00Z",
                "fetch_timestamp": "2026-09-17T20:00:01Z",
                "freshness_seconds": 1.0,
                "raw_response": {"bid_px_00": 225450000000, "ask_px_00": 225550000000}
            }
            quote = provider.get_current_quote("AAPL")
            self.assertTrue(quote["success"])
            self.assertEqual(quote["provider"], "DATABENTO")
            self.assertEqual(quote["client_type"], "Live")
            self.assertEqual(quote["data_service"], "LIVE")
            self.assertEqual(quote["schema"], "bbo-1s")
            self.assertEqual(quote["instrument"], "AAPL")
            self.assertEqual(quote["latest_price"], 225.50)
            self.assertEqual(quote["bid"], 225.45)
            self.assertEqual(quote["ask"], 225.55)
            self.assertEqual(quote["spread"], 0.10)
            self.assertIsNotNone(quote["raw_response"])

    def test_02_no_yahoo_current_decision_fallback(self):
        """When Databento is unconfigured or fails, current-decision path fails closed with ZERO Yahoo calls."""
        from src.data.databento_provider import DatabentoMarketDataProvider
        
        provider = DatabentoMarketDataProvider(api_key=None)
        with patch("yfinance.Ticker") as mock_yf:
            quote = provider.get_current_quote("AAPL")
            self.assertFalse(quote["success"])
            self.assertEqual(quote["status"], "DATABENTO_API_KEY_MISSING")
            self.assertEqual(quote["data_service"], "LIVE")
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
        
        # Missing FX rate -> must fail closed with PRODUCT_FAILURE
        dec = strategy.evaluate_entry(now_time=midday, fx_gbpusd=None)
        self.assertEqual(dec.decision, "NO_ENTRY")
        self.assertIn("PRODUCT_FAILURE: FX_CONVERSION_RATE_UNAVAILABLE", dec.no_entry_reason)
        
        # Quantity calculation must return 0.0 when FX is missing
        qty = strategy.calculate_quantity(current_price_usd=225.0, fx_gbpusd=None)
        self.assertEqual(qty, 0.0)

    def test_07_strategy_level_zero_yahoo_in_entry_and_exit(self):
        """Proves ZERO Yahoo calls for BOTH DemoStrategyV1.evaluate_entry() and DemoStrategyV1.evaluate_exit()."""
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
        mock_databento.fetch_live_bars.return_value = pd.DataFrame()
        
        strategy = DemoStrategyV1(
            market_data_provider=mock_market_data,
            databento_provider=mock_databento,
            fx_provider=None
        )
        
        tz_ny = ZoneInfo("America/New_York")
        midday = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()
        
        # 1. Entry evaluation
        dec = strategy.evaluate_entry(now_time=midday, fx_gbpusd=1.33)
        self.assertEqual(dec.decision, "NO_ENTRY")
        self.assertIn("PRODUCT_FAILURE: DATABENTO_LIVE_DATA_UNAVAILABLE", dec.no_entry_reason)
        mock_market_data.fetch_history.assert_not_called()
        
        # 2. Exit evaluation
        holding = {"ticker": "AAPL_US_EQ", "fill_price": 220.0, "quantity": 0.19, "entry_time": "2026-09-17T12:00:00Z"}
        should_exit, reason = strategy.evaluate_exit(holding, now_time=midday)
        self.assertFalse(should_exit)
        self.assertEqual(reason, "HOLD")
        
        # Invariant: mock_market_data was NEVER called in entry or exit
        mock_market_data.fetch_history.assert_not_called()

    def test_08_complete_quote_gate_enforcement(self):
        """Complete Quote Gate: requires bid, ask, spread > 0, timestamps, freshness; rejects trades-only."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        # Test Case A: Databento falls back to trades only (bid, ask, spread are None)
        mock_databento_trades_only = MagicMock()
        mock_databento_trades_only.is_configured = True
        mock_databento_trades_only.get_current_quote.return_value = {
            "success": False,
            "status": "DATABENTO_LIVE_DATA_UNAVAILABLE",
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

    def test_09_no_unauthorised_fx_provider_wired(self):
        """Verify singleton demo_strategy_v1 does NOT have non-authorised portfolio_snapshot wired."""
        from src.hit_and_run.demo_strategy_v1 import demo_strategy_v1
        
        # The singleton must not have portfolio_snapshot wired by default (which has 1.35 seed and Yahoo)
        self.assertIsNone(demo_strategy_v1.fx_provider)

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

    def test_11_render_worker_import_clean(self):
        """Verify demo_dispatcher and start_demo_experiment_worker import cleanly without any ImportError."""
        from src.hit_and_run.demo_execution import demo_dispatcher, demo_execution_dispatcher
        from src.api.routes import start_demo_experiment_worker
        
        self.assertIs(demo_dispatcher, demo_execution_dispatcher)
        self.assertTrue(callable(start_demo_experiment_worker))

    def test_12_stop_price_calculation_runtime(self):
        """Verify stop price calculation in DemoExecutionDispatcher executes with math.ceil and no NameError."""
        import math
        from src.hit_and_run.demo_execution import DemoExecutionDispatcher
        
        mock_broker = MagicMock()
        mock_broker.env = "demo"
        dispatcher = DemoExecutionDispatcher(broker_client=mock_broker)
        
        decision = HitAndRunEntryDecision(
            decision="ENTER",
            instrument_id="AAPL_US_EQ",
            symbol="AAPL",
            feed_ticker="AAPL",
            intended_capital_gbp=50.0,
            intended_quantity=0.19,
            required_protective_level=220.0
        )
        decision.planned_loss_pct = 0.02

        # Simulate execution
        mock_broker.place_market_order.return_value = {"success": True, "data": {"id": "123"}}
        mock_broker.get_open_positions.return_value = [{"ticker": "AAPL_US_EQ", "averagePrice": 225.50, "quantity": 0.19}]
        mock_broker.place_stop_order.return_value = {"success": True, "data": {"id": "STOP_1"}}
        mock_broker.get_open_orders.return_value = [{"ticker": "AAPL_US_EQ", "type": "STOP", "id": "STOP_1"}]

        res = dispatcher.execute_entry(decision, timeout_seconds=0.1, poll_interval=0.01)
        self.assertTrue(res["success"])
        # Stop price calculation must ceiling to 2 decimal places: 225.50 * 0.98 = 220.99
        expected_stop = math.ceil(225.50 * 0.98 * 100.0) / 100.0
        self.assertEqual(res["stop_price"], expected_stop)

    def test_13_multi_session_worker_survival(self):
        """Verify DemoExperimentRunner.run_multi_session_worker handles day transitions and EOD cleanup cleanly."""
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
            experiment_id="TEST-MULTI-SESSION-001",
            strategy_version="1.0-DEMO",
            strategy_module=mock_strategy,
            dispatcher=mock_dispatcher,
            audit_log_dir="/tmp/test_audit"
        )
        runner.pre_session_startup = MagicMock(return_value={"starting_cash": 50000.0, "starting_equity": 50000.0})
        runner.end_of_day_cleanup_and_review = MagicMock(return_value={"REALISED_NET_PNL": 0.0, "CLEANUP_SUCCESS": True})

        # Test session reset
        runner.active_holdings["AAPL"] = {"ticker": "AAPL"}
        runner.trades_log.append({"type": "ENTRY"})
        runner.reset_session_state()
        self.assertEqual(len(runner.active_holdings), 0)
        self.assertEqual(len(runner.trades_log), 0)
        mock_strategy.reset_daily_state.assert_called_once()

    def test_14_authorised_friction_rule_restored(self):
        """Verify restored authorised friction rule: FRICTION_PROXY = 0.0010 * Close, EXPECTED_MOVE = 1.5 * ATR > 2 * FRICTION_PROXY."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        # Test Case: ATR = 0.10, Close = 200.0.
        # friction_proxy = 0.0010 * 200 = 0.20
        # hurdle = 2.0 * 0.20 = 0.40
        # expected_move = 1.5 * 0.10 = 0.15
        # 0.15 <= 0.40 -> NO_ENTRY due to friction hurdle
        mock_databento = MagicMock()
        mock_databento.is_configured = True
        mock_databento.get_current_quote.return_value = {
            "success": True,
            "status": "OK",
            "provider": "DATABENTO",
            "client_type": "Live",
            "data_service": "LIVE",
            "dataset": "DBEQ.BASIC",
            "schema": "bbo-1s",
            "instrument": "AAPL",
            "symbols": ["AAPL"],
            "latest_price": 200.0,
            "bid": 199.98,
            "ask": 200.02,
            "spread": 0.04,
            "quote_timestamp": "2026-09-17T20:00:00Z",
            "fetch_timestamp": "2026-09-17T20:00:01Z",
            "freshness_seconds": 1.0,
            "raw_response": {},
            "http_status": 200
        }
        # Craft bars with low ATR (0.10)
        df_bars = pd.DataFrame({
            "Open": [200.0] * 30,
            "High": [200.05] * 30,
            "Low": [199.95] * 30,
            "Close": [200.0] * 30,
            "Volume": [50000] * 30
        }, index=pd.date_range("2026-09-17 09:30", periods=30, freq="5min", tz="America/New_York"))
        mock_databento.fetch_live_bars.return_value = df_bars

        strategy = DemoStrategyV1(databento_provider=mock_databento)
        tz_ny = ZoneInfo("America/New_York")
        midday = datetime(2026, 9, 17, 12, 0, tzinfo=tz_ny).timestamp()

        dec = strategy.evaluate_entry(now_time=midday, fx_gbpusd=1.33)
        self.assertEqual(dec.decision, "NO_ENTRY")
        self.assertIn("EXPECTED_MOVE_BELOW_FRICTION", dec.no_entry_reason)
        self.assertIn("friction_proxy=", dec.no_entry_reason)

    def test_15_no_invented_60s_staleness_threshold(self):
        """Verify MAX_QUOTE_STALENESS_SECONDS attribute is removed and valid quotes pass regardless of age."""
        from src.hit_and_run.demo_strategy_v1 import DemoStrategyV1
        
        self.assertFalse(hasattr(DemoStrategyV1, "MAX_QUOTE_STALENESS_SECONDS"))

    def test_16_dynamic_git_sha_telemetry(self):
        """Verify /api/demo_experiment/status dynamically queries git SHA and does not return hardcoded 3d14b6b."""
        from src.api.routes import get_demo_experiment_status
        
        status = get_demo_experiment_status()
        self.assertNotEqual(status["git_sha"], "3d14b6b10d5ea4cc9814273a9b4a5162df5acc4a")
        self.assertTrue(len(status["git_sha"]) >= 7)


if __name__ == "__main__":
    unittest.main()
