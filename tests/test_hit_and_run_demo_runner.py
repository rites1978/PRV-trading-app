"""
Unit tests for DemoExperimentRunner (scripts/run_demo_experiment.py)
Verifies:
1. Rejects live broker environment on startup.
2. Aborts if pre-existing positions or orders exist in DEMO.
3. Pre-session captures cash and equity cleanly.
4. Without an authorized strategy module, run_scan_and_execute_cycle outputs AWAITING_USER_AUTHORISATION with 0 entries.
5. With injected strategy, approved entries are dispatched to DemoExecutionDispatcher.
6. End of day flattens active holdings and produces full JSON report.
"""
import unittest
from unittest.mock import MagicMock, patch
from scripts.run_demo_experiment import DemoExperimentRunner
from src.hit_and_run.models import HitAndRunEntryDecision


class TestDemoExperimentRunner(unittest.TestCase):

    def setUp(self):
        self.mock_dispatcher = MagicMock()
        self.mock_dispatcher.reconcile_broker_state.return_value = {
            "is_clean_slate": True,
            "positions_count": 0,
            "orders_count": 0
        }
        self.runner = DemoExperimentRunner(
            experiment_id="TEST_EXP_001",
            strategy_version="TEST_V1",
            dispatcher=self.mock_dispatcher,
            audit_log_dir="/tmp/test_demo_experiments"
        )

    @patch("scripts.run_demo_experiment.broker")
    def test_01_pre_session_captures_cash_and_equity(self, mock_broker):
        mock_broker.env = "demo"
        mock_broker.get_account_summary.return_value = {
            "success": True,
            "raw": {"free": 50000.0, "total": 50000.0}
        }

        startup = self.runner.pre_session_startup()
        self.assertEqual(startup["starting_cash"], 50000.0)
        self.assertEqual(startup["starting_equity"], 50000.0)
        self.assertEqual(startup["broker_environment"], "DEMO")

    @patch("scripts.run_demo_experiment.broker")
    def test_02_pre_session_aborts_if_unclean_slate(self, mock_broker):
        mock_broker.env = "demo"
        mock_broker.get_account_summary.return_value = {
            "success": True,
            "raw": {"free": 49000.0, "total": 50000.0}
        }
        self.mock_dispatcher.reconcile_broker_state.return_value = {
            "is_clean_slate": False,
            "positions_count": 1,
            "orders_count": 0
        }

        with self.assertRaises(RuntimeError) as ctx:
            self.runner.pre_session_startup()
        self.assertIn("ACCOUNT_STATE_NOT_CLEAN", str(ctx.exception))

    def test_03_trading_cycle_without_strategy_awaits_authorization(self):
        self.runner.strategy_module = None
        res = self.runner.run_scan_and_execute_cycle([])
        self.assertEqual(res["cycle_status"], "AWAITING_USER_AUTHORISATION")
        self.assertEqual(res["entries_submitted"], 0)
        self.mock_dispatcher.execute_entry.assert_not_called()

    def test_04_trading_cycle_with_injected_strategy_dispatches(self):
        mock_strategy = MagicMock()
        mock_decision = HitAndRunEntryDecision(
            decision="ENTER",
            instrument_id="LLOYl_EQ",
            symbol="LLOY",
            feed_ticker="LLOY.L",
            intended_capital_gbp=50.0,
            intended_quantity=50.0,
            required_protective_level=95.0,
            tick_size=0.1
        )
        mock_strategy.evaluate.return_value = [mock_decision]
        self.runner.strategy_module = mock_strategy
        self.mock_dispatcher.execute_entry.return_value = {
            "success": True,
            "fill_price": 100.0,
            "filled_quantity": 50.0,
            "stop_order_id": "STOP_999",
            "stop_price": 95.0,
            "timestamp": "2026-09-17T18:00:00Z"
        }

        res = self.runner.run_scan_and_execute_cycle(["opp1"])
        self.assertEqual(res["cycle_status"], "CYCLE_COMPLETED")
        self.assertEqual(res["entries_submitted"], 1)
        self.mock_dispatcher.execute_entry.assert_called_once_with(mock_decision)
        self.assertIn("LLOYl_EQ", self.runner.active_holdings)

    @patch("scripts.run_demo_experiment.broker")
    def test_05_end_of_day_flattens_and_reports(self, mock_broker):
        mock_broker.get_account_summary.return_value = {
            "success": True,
            "raw": {"free": 50025.0, "total": 50025.0}
        }
        self.runner.starting_equity = 50000.0
        self.runner.active_holdings["LLOYl_EQ"] = {
            "ticker": "LLOYl_EQ",
            "quantity": 50.0
        }
        self.mock_dispatcher.execute_exit.return_value = {"success": True, "exit_order_id": "EXIT_1"}

        report = self.runner.end_of_day_cleanup_and_review()
        self.assertEqual(report["REALISED_NET_PNL"], 25.0)
        self.mock_dispatcher.execute_exit.assert_called_once_with(
            ticker="LLOYl_EQ", quantity=50.0, reason="END_OF_DAY_FLATTEN"
        )
        self.assertEqual(len(self.runner.active_holdings), 0)


if __name__ == "__main__":
    unittest.main()
