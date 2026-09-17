"""
Unit Tests for Hit-and-Run DEMO Execution Dispatcher (src/hit_and_run/demo_execution.py)
Verifies:
1. Strict fail-closed on LIVE broker environment.
2. Refuses non-ENTER decision payloads.
3. Submits entry order and places protective stop with SUBMITTED_STOP >= RAW_STOP_FLOOR.
4. Fail-safe trigger: If stop order fails/rejected, immediately flattens position via Market SELL.
5. Exit execution: Cancels active stop orders, flattens position, reconciles zero residual.
6. Clean broker state reconciliation.
"""
import unittest
from unittest.mock import MagicMock, patch
from src.hit_and_run.models import HitAndRunEntryDecision
from src.hit_and_run.demo_execution import DemoExecutionDispatcher


class TestDemoExecutionDispatcher(unittest.TestCase):

    def setUp(self):
        self.mock_broker = MagicMock()
        self.mock_broker.env = "demo"
        self.mock_broker.base_url = "https://demo.trading212.com/api/v0"
        self.mock_risk = MagicMock()
        self.dispatcher = DemoExecutionDispatcher(
            broker_client=self.mock_broker,
            risk_manager=self.mock_risk
        )

    def test_01_fails_closed_on_live_environment(self):
        """Must raise RuntimeError immediately if broker environment is LIVE."""
        live_broker = MagicMock()
        live_broker.env = "live"
        with self.assertRaises(RuntimeError) as ctx:
            DemoExecutionDispatcher(broker_client=live_broker)
        self.assertIn("CRITICAL_SAFETY_VIOLATION", str(ctx.exception))

    def test_02_refuses_non_enter_decisions(self):
        """Dispatcher must reject decisions where decision != 'ENTER'."""
        decision = HitAndRunEntryDecision(
            decision="NO_ENTRY",
            instrument_id="LLOYl_EQ",
            symbol="LLOY",
            feed_ticker="LLOY.L",
            no_entry_reason="Testing rejection"
        )
        res = self.dispatcher.execute_entry(decision)
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "REJECTED_NOT_ENTER")
        self.mock_broker.place_market_order.assert_not_called()

    def test_03_successful_entry_and_protective_stop_sequence(self):
        """
        Nominal path:
        1. Place market buy.
        2. Poll confirms fill @ 100.0.
        3. Raw stop floor is 95.0. Stop calculated >= 95.0.
        4. Place native stop.
        5. Verify stop exists in open orders.
        """
        decision = HitAndRunEntryDecision(
            decision="ENTER",
            instrument_id="LLOYl_EQ",
            symbol="LLOY",
            feed_ticker="LLOY.L",
            intended_capital_gbp=50.0,
            intended_quantity=50.0,
            required_protective_level=95.0,
            tick_size=0.1
        )
        self.mock_broker.place_market_order.return_value = {
            "success": True,
            "data": {"id": "ORDER_ENTRY_123"}
        }
        self.mock_broker.get_open_positions.return_value = [
            {"ticker": "LLOYl_EQ", "averagePrice": 100.0, "quantity": 50.0}
        ]
        self.mock_risk.calculate_protective_stop.return_value = 95.0
        self.mock_broker.place_stop_order.return_value = {
            "success": True,
            "data": {"id": "ORDER_STOP_456"}
        }
        self.mock_broker.get_open_orders.return_value = [
            {"id": "ORDER_STOP_456", "ticker": "LLOYl_EQ", "type": "STOP"}
        ]

        res = self.dispatcher.execute_entry(decision, timeout_seconds=1.0, poll_interval=0.01)

        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PROTECTED_POSITION_ACTIVE")
        self.assertEqual(res["fill_price"], 100.0)
        self.assertEqual(res["stop_order_id"], "ORDER_STOP_456")
        self.assertGreaterEqual(res["stop_price"], 95.0)

    def test_04_fail_safe_flattens_when_stop_fails(self):
        """
        Fail-safe invariant: If entry fills but protective stop fails,
        dispatcher must immediately issue Market SELL to flatten position.
        """
        decision = HitAndRunEntryDecision(
            decision="ENTER",
            instrument_id="AAPL_US_EQ",
            symbol="AAPL",
            feed_ticker="AAPL",
            intended_capital_gbp=200.0,
            intended_quantity=1.0,
            required_protective_level=190.0,
            tick_size=0.01
        )
        self.mock_broker.place_market_order.side_effect = [
            {"success": True, "data": {"id": "ORDER_ENTRY_999"}},  # Entry BUY
            {"success": True, "data": {"id": "ORDER_FLATTEN_000"}}  # Fail-safe SELL
        ]
        self.mock_broker.get_open_positions.return_value = [
            {"ticker": "AAPL_US_EQ", "averagePrice": 200.0, "quantity": 1.0}
        ]
        self.mock_risk.calculate_protective_stop.return_value = 190.0
        # Stop order fails / rejected by broker
        self.mock_broker.place_stop_order.return_value = {
            "success": False,
            "error": "HTTP 400: Stop order rejected"
        }

        res = self.dispatcher.execute_entry(decision, timeout_seconds=1.0, poll_interval=0.01)

        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "STOP_FAILED_EMERGENCY_FLATTENED")
        # Verify flatten sell was called with negative quantity
        self.mock_broker.place_market_order.assert_called_with(ticker="AAPL_US_EQ", quantity=-1.0)

    def test_05_execute_exit_cancels_stops_and_flattens(self):
        """Exit execution must cancel active stop orders, submit market SELL, and confirm flat state."""
        self.mock_broker.cancel_stop_orders_for_ticker.return_value = ["STOP_123"]
        self.mock_broker.place_market_order.return_value = {
            "success": True,
            "data": {"id": "EXIT_ORDER_789"}
        }
        self.mock_broker.get_open_positions.return_value = []

        res = self.dispatcher.execute_exit("VUSAl_EQ", quantity=1.0, reason="TAKE_PROFIT")

        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "FLATTENED")
        self.assertEqual(res["exit_order_id"], "EXIT_ORDER_789")
        self.assertEqual(res["cancelled_stops"], ["STOP_123"])
        self.mock_broker.cancel_stop_orders_for_ticker.assert_called_once_with("VUSAl_EQ")
        self.mock_broker.place_market_order.assert_called_once_with(ticker="VUSAl_EQ", quantity=-1.0)

    def test_06_reconcile_broker_state(self):
        """Reconciliation must report whether account is clean slate."""
        self.mock_broker.get_open_positions_authoritative.return_value = ([], True)
        self.mock_broker.get_open_orders_authoritative.return_value = ([], True)

        reconcile = self.dispatcher.reconcile_broker_state()
        self.assertTrue(reconcile["is_clean_slate"])
        self.assertEqual(reconcile["positions_count"], 0)
        self.assertEqual(reconcile["orders_count"], 0)


if __name__ == "__main__":
    unittest.main()
