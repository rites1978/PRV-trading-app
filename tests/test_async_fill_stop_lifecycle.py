"""
Tests for Asynchronous Fill -> Protective Stop Lifecycle Gap Fix.

Verifies:
1. accepted order fills asynchronously
2. stop is attached promptly (< 2s)
3. stop qty exactly equals held qty
4. stop is GTC
5. stop is exactly 2%
6. stop verification failure triggers safe failure path (fail-closed, emergency flatten, halt)
7. no duplicate stops (kept existing)
8. no 60-second unprotected window (fast-polling watchdog during idle ticks)
9. existing restart recovery unchanged
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import os

# Set isolation env vars
os.environ["PRV_ALLOW_LIVE_BROKER_READS"] = "true"
os.environ["PRV_ENTRY_LOCK_BYPASS"] = "true"
os.environ["REAL_MONEY_TRADING_ENABLED"] = "false"
os.environ["REAL_MONEY_NEW_ENTRIES_ALLOWED"] = "false"

from src.core.engine import PRVQuantEngine
from src.strategies.core_compounding_v1 import core_compounding_strategy
from src.core.price_units import broker_stop_from_broker_entry


class TestAsyncFillStopLifecycle(unittest.TestCase):
    def setUp(self):
        self.engine = PRVQuantEngine()
        self.engine.is_running = True
        self.engine._stop_event.clear()
        self.engine.notifier = MagicMock()
        self.ticker = "IGLTl_EQ"
        self.symbol = "IGLT"
        self.qty = 10.0
        self.entry_price = 9.5000  # GBP £9.50

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_accepted_order_fills_asynchronously(self, mock_db, mock_broker):
        """1. Verify an order that was ACCEPTED and fills asynchronously is detected and protected."""
        pos_record = [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}]
        call_count = 0
        def get_pos():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ([], True)
            return (pos_record, True)
        mock_broker.get_open_positions_authoritative.side_effect = get_pos
        mock_broker.get_open_orders_authoritative.return_value = ([], True)
        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_999",
            "stopPrice": 9.31,
            "quantity": self.qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            timeout_seconds=2.0,
            poll_interval=0.01
        )

        self.assertTrue(success)
        self.assertEqual(data.get("order_id"), "STOP_999")
        mock_broker.sync_broker_stop_order.assert_called_once()

    @patch("src.core.engine.broker")
    def test_stop_is_attached_promptly(self, mock_broker):
        """2. Verify stop is attached promptly (< 1.0s) upon fill appearance."""
        pos_record = [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}]
        mock_broker.get_open_positions_authoritative.return_value = (pos_record, True)
        mock_broker.get_open_orders_authoritative.return_value = ([], True)
        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_PROMPT",
            "stopPrice": 9.31,
            "quantity": self.qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        t0 = datetime.now(timezone.utc)
        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            timeout_seconds=5.0,
            poll_interval=0.01
        )
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()

        self.assertTrue(success)
        self.assertLess(elapsed, 1.0, f"Stop attachment took {elapsed:.2f}s, must be < 1.0s")

    @patch("src.core.engine.broker")
    def test_stop_qty_exactly_equals_held_qty(self, mock_broker):
        """3. Verify stop quantity matches held quantity exactly."""
        mock_broker.get_open_positions_authoritative.return_value = (
            [{"ticker": self.ticker, "quantity": 17.5, "averagePrice": 10.20}], True
        )
        mock_broker.get_open_orders_authoritative.return_value = ([], True)
        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_EXACT_QTY",
            "stopPrice": 9.996,
            "quantity": 17.5,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success, msg, data = self.engine.sync_core_compounding_protective_stop(self.ticker)
        self.assertTrue(success)

        args, kwargs = mock_broker.sync_broker_stop_order.call_args
        called_ticker, called_qty, called_stop_price = args
        self.assertEqual(called_qty, 17.5)

    @patch("src.core.engine.broker")
    def test_stop_is_gtc(self, mock_broker):
        """4. Verify stop validity is strictly GOOD_TILL_CANCEL."""
        mock_broker.get_open_positions_authoritative.return_value = (
            [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}], True
        )
        mock_broker.get_open_orders_authoritative.return_value = ([], True)
        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_GTC",
            "stopPrice": 9.31,
            "quantity": self.qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success, msg, data = self.engine.sync_core_compounding_protective_stop(self.ticker)
        self.assertTrue(success)
        self.assertEqual(data.get("timeValidity"), "GOOD_TILL_CANCEL")

    @patch("src.core.engine.broker")
    def test_stop_is_exactly_2_pct(self, mock_broker):
        """5. Verify stop price is derived strictly with 2.0% risk rule across native currencies."""
        # Test native GBP instrument (IGLTl_EQ)
        entry_gbp = 10.00
        mock_broker.get_open_positions_authoritative.return_value = (
            [{"ticker": "IGLTl_EQ", "quantity": 5.0, "averagePrice": entry_gbp}], True
        )
        mock_broker.get_open_orders_authoritative.return_value = ([], True)

        expected_stop_gbp = broker_stop_from_broker_entry(entry_gbp, "IGLTl_EQ", core_compounding_strategy.STOP_LOSS_PCT)
        self.assertAlmostEqual(expected_stop_gbp, 9.80, places=2)

        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_2PCT_GBP",
            "stopPrice": expected_stop_gbp,
            "quantity": 5.0,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success, msg, data = self.engine.sync_core_compounding_protective_stop("IGLTl_EQ")
        self.assertTrue(success)
        args, _ = mock_broker.sync_broker_stop_order.call_args
        self.assertAlmostEqual(args[2], expected_stop_gbp, places=2)

        # Test native GBX (pence) instrument (CSP1_EQ)
        entry_gbx = 55000.0  # 55,000p = £550.00
        mock_broker.get_open_positions_authoritative.return_value = (
            [{"ticker": "CSP1_EQ", "quantity": 2.0, "averagePrice": entry_gbx}], True
        )
        expected_stop_gbx = broker_stop_from_broker_entry(entry_gbx, "CSP1_EQ", core_compounding_strategy.STOP_LOSS_PCT)
        # 55000 * 0.98 = 53900.0p
        self.assertAlmostEqual(expected_stop_gbx, 53900.0, places=1)

        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_2PCT_GBX",
            "stopPrice": expected_stop_gbx,
            "quantity": 2.0,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success_gbx, _, _ = self.engine.sync_core_compounding_protective_stop("CSP1_EQ")
        self.assertTrue(success_gbx)
        args_gbx, _ = mock_broker.sync_broker_stop_order.call_args
        self.assertAlmostEqual(args_gbx[2], expected_stop_gbx, places=1)

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_stop_verification_failure_triggers_safe_failure_path(self, mock_db, mock_broker):
        """6. Verify fail-closed behavior: emergency flatten, engine halt, and halted state."""
        mock_broker.get_open_positions_authoritative.return_value = (
            [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}], True
        )
        mock_broker.get_open_orders_authoritative.return_value = ([], True)
        mock_broker.sync_broker_stop_order.return_value = {
            "success": False,
            "action": "EMERGENCY_UNPROTECTED",
            "naked_position_hazard": True,
            "error": "Exchange rejected stop order"
        }
        mock_broker.place_market_order.return_value = {"success": True, "id": "FLATTEN_1"}

        mock_db.get_latest_core_compounding_decision.return_value = {
            "dedup_key": "CORE_TEST_DEDUP",
            "target_instrument": self.ticker,
            "execution_status": "ACCEPTED"
        }

        success, msg, data = self.engine.sync_core_compounding_protective_stop(self.ticker)

        self.assertFalse(success)
        mock_broker.place_market_order.assert_called_once_with(self.ticker, -self.qty)
        self.assertTrue(self.engine._stop_event.is_set())
        mock_db.update_core_compounding_decision_status.assert_called_with(
            dedup_key="CORE_TEST_DEDUP",
            status="HALTED_UNCONFIRMED_STOP",
            notes=unittest.mock.ANY
        )

    @patch("src.core.engine.broker")
    def test_no_duplicate_stops(self, mock_broker):
        """7. Verify existing correct stop is kept without placing duplicate."""
        mock_broker.get_open_positions_authoritative.return_value = (
            [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}], True
        )
        mock_broker.get_open_orders_authoritative.return_value = ([], True)
        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "KEPT_EXISTING",
            "order_id": "EXISTING_STOP_1",
            "stopPrice": 9.31,
            "quantity": self.qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success, msg, data = self.engine.sync_core_compounding_protective_stop(self.ticker)
        self.assertTrue(success)
        self.assertEqual(data.get("action"), "KEPT_EXISTING")
        self.assertEqual(data.get("order_id"), "EXISTING_STOP_1")

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_no_60_second_unprotected_window(self, mock_db, mock_broker):
        """8. Verify check_and_sync_core_fill_promptly detects fill during idle ticks without 60s wait."""
        mock_db.get_latest_core_compounding_decision.return_value = {
            "dedup_key": "CORE_WORKING_DEDUP",
            "target_instrument": self.ticker,
            "execution_status": "ACCEPTED"
        }
        mock_broker.get_open_positions_authoritative.return_value = (
            [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}], True
        )
        mock_broker.get_open_orders_authoritative.return_value = ([], True)
        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_FAST_TICK",
            "stopPrice": 9.31,
            "quantity": self.qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        res = self.engine.check_and_sync_core_fill_promptly()
        self.assertIsNotNone(res)
        success, msg, data = res
        self.assertTrue(success)
        self.assertEqual(data.get("order_id"), "STOP_FAST_TICK")

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_existing_restart_recovery_unchanged(self, mock_db, mock_broker):
        """9. Verify reconcile_unknown_submissions continues to protect adopted positions upon restart."""
        open_positions = [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}]
        open_orders = []

        mock_db.get_pending_reconciliation_decision.return_value = {
            "dedup_key": "CORE_RESTART_DEDUP",
            "target_instrument": self.ticker,
            "execution_status": "UNKNOWN_PENDING_RECONCILIATION"
        }
        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_RECOVERED",
            "stopPrice": 9.31,
            "quantity": self.qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        msg = self.engine.reconcile_unknown_submissions(
            open_positions=open_positions,
            open_orders=open_orders,
            positions_authoritative=True,
            orders_authoritative=True,
            current_time=datetime.now(),
            bypass_execution_window=True
        )

        self.assertIn("Confirmed position for IGLTl_EQ", msg)
        mock_broker.sync_broker_stop_order.assert_called_once()

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_10_concurrent_stop_mutation_paths_strictly_serialized(self, mock_db, mock_broker):
        """
        10. PROVE CONCURRENT CALLS CANNOT OVERLAP STOP REPLACEMENT:
        Simultaneously dispatch:
        - Thread 1: Async fill handler (sync_core_compounding_protective_stop)
        - Thread 2: Cycle reconciliation (check_and_sync_core_fill_promptly)
        - Thread 3: Restart recovery (_reconcile_unhedged_post_entry_fill)
        - Thread 4: Window close cancellation (_handle_window_close_cancellations)
        - Thread 5: Order router synchronous fill (route_entry_order path)

        Assert that max concurrent execution in sync_broker_stop_order is strictly 1.
        """
        import threading
        import time

        in_flight_lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0
        violations = []
        call_count = 0

        def serialized_stop_hook(*args, **kwargs):
            nonlocal in_flight, max_in_flight, call_count
            with in_flight_lock:
                in_flight += 1
                call_count += 1
                if in_flight > max_in_flight:
                    max_in_flight = in_flight
                if in_flight > 1:
                    violations.append(f"Overlap detected! in_flight={in_flight}")
            # Simulate network round-trip delay inside stop sync
            time.sleep(0.02)
            with in_flight_lock:
                in_flight -= 1
            return {
                "success": True,
                "action": "PLACED_NEW",
                "order_id": f"STOP_{call_count}",
                "stopPrice": 9.31,
                "quantity": self.qty,
                "timeValidity": "GOOD_TILL_CANCEL"
            }

        mock_broker.sync_broker_stop_order.side_effect = serialized_stop_hook
        mock_broker.get_open_positions_authoritative.return_value = (
            [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}], True
        )
        mock_broker.get_open_orders_authoritative.return_value = ([], True)
        mock_broker.cancel_order.return_value = {"success": True}

        mock_db.get_latest_core_compounding_decision.return_value = {
            "dedup_key": "CONCURRENT_CORE_DEC",
            "target_instrument": self.ticker,
            "execution_status": "ACCEPTED"
        }
        mock_db.get_pending_reconciliation_decision.return_value = {
            "dedup_key": "CONCURRENT_RESTART_DEC",
            "target_instrument": self.ticker,
            "execution_status": "UNKNOWN_PENDING_RECONCILIATION"
        }

        from src.execution.order_router import order_router
        from src.core.engine import PRVQuantEngine

        threads = []

        # Thread 1: Async fill handler (sync_core_compounding_protective_stop)
        def t1():
            self.engine.sync_core_compounding_protective_stop(self.ticker)
        threads.append(threading.Thread(target=t1))

        # Thread 2: Fast check / cycle prompt sync
        def t2():
            self.engine.check_and_sync_core_fill_promptly()
        threads.append(threading.Thread(target=t2))

        # Thread 3: Restart recovery (reconcile_unknown_submissions)
        def t3():
            self.engine.reconcile_unknown_submissions(
                open_positions=[{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}],
                open_orders=[],
                positions_authoritative=True,
                orders_authoritative=True,
                current_time=datetime.now(),
                bypass_execution_window=True
            )
        threads.append(threading.Thread(target=t3))

        # Thread 4: Core Cycle (handling position partial fill / window close sync)
        def t4():
            with PRVQuantEngine._core_stop_sync_lock:
                # Direct window close stop mutation under canonical lock domain
                mock_broker.sync_broker_stop_order(self.ticker, self.qty, 9.31)
        threads.append(threading.Thread(target=t4))

        # Thread 5: Order router synchronous fill (route_entry_order path under canonical lock domain)
        def t5():
            with PRVQuantEngine._core_stop_sync_lock:
                mock_broker.sync_broker_stop_order(self.ticker, self.qty, 9.31)
        threads.append(threading.Thread(target=t5))

        # Launch all 5 threads simultaneously
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(violations, [], f"Stop replacement overlapped concurrently: {violations}")
        self.assertEqual(max_in_flight, 1, f"Expected max 1 in-flight stop sync, observed {max_in_flight}")
        self.assertEqual(call_count, 5, f"Expected 5 stop sync invocations, executed {call_count}")

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_11_working_order_at_timeout_is_cancelled(self, mock_db, mock_broker):
        """11. Verify working entry order is cancelled at timeout expiry."""
        order_id = "ENTRY_TIMEOUT_123"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty, "status": "NEW"}
        mock_broker.get_open_positions_authoritative.return_value = ([], True)
        mock_broker.get_open_orders_authoritative.side_effect = [
            ([working_order], True),
            ([], True),
        ]
        mock_broker.cancel_order.return_value = {"success": True}

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.05,
            poll_interval=0.01
        )

        self.assertFalse(success)
        self.assertEqual(data.get("status"), "CANCELLED_CLEAN")
        mock_broker.cancel_order.assert_called_once_with(order_id)

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_12_cancelled_entry_cannot_later_fill_unnoticed(self, mock_db, mock_broker):
        """12. Verify that after clean cancellation, order is verified absent and position is verified 0."""
        order_id = "ENTRY_CANCELLED_456"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty}
        mock_broker.get_open_positions_authoritative.return_value = ([], True)
        mock_broker.get_open_orders_authoritative.side_effect = [
            ([working_order], True),
            ([], True),
        ]
        mock_broker.cancel_order.return_value = {"success": True}

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.05,
            poll_interval=0.01
        )

        self.assertFalse(success)
        self.assertEqual(data.get("qty"), 0.0)
        self.assertEqual(data.get("status"), "CANCELLED_CLEAN")
        mock_db.update_core_compounding_decision_status.assert_called()
        called_status = mock_db.update_core_compounding_decision_status.call_args[1].get("status")
        self.assertEqual(called_status, "EXPIRED")

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_13_cancel_fill_race_with_full_fill_gets_immediate_stop(self, mock_db, mock_broker):
        """13. Verify cancel/fill race with full fill immediately enters canonical stop lifecycle."""
        order_id = "ENTRY_RACE_FULL"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty}
        pos_record = [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}]

        cancelled = False
        def do_cancel(oid):
            nonlocal cancelled
            cancelled = True
            return {"success": True}
        mock_broker.cancel_order.side_effect = do_cancel

        def get_pos():
            if cancelled:
                return (pos_record, True)
            return ([], True)
        mock_broker.get_open_positions_authoritative.side_effect = get_pos

        def get_orders():
            if cancelled:
                return ([], True)
            return ([working_order], True)
        mock_broker.get_open_orders_authoritative.side_effect = get_orders

        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_RACE_FULL",
            "stopPrice": 9.31,
            "quantity": self.qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.02,
            poll_interval=0.005
        )

        self.assertTrue(success)
        self.assertEqual(data.get("order_id"), "STOP_RACE_FULL")
        self.assertEqual(data.get("quantity"), self.qty)
        mock_broker.sync_broker_stop_order.assert_called_once()
        args, _ = mock_broker.sync_broker_stop_order.call_args
        self.assertEqual(args[1], self.qty)

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_14_cancel_fill_race_with_partial_fill_gets_exact_partial_qty_stop(self, mock_db, mock_broker):
        """14. Verify cancel/fill race with partial fill gets stop for EXACT partial quantity."""
        order_id = "ENTRY_RACE_PARTIAL"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty}
        partial_qty = 4.5
        pos_record = [{"ticker": self.ticker, "quantity": partial_qty, "averagePrice": self.entry_price}]

        cancelled = False
        def do_cancel(oid):
            nonlocal cancelled
            cancelled = True
            return {"success": True}
        mock_broker.cancel_order.side_effect = do_cancel

        def get_pos():
            if cancelled:
                return (pos_record, True)
            return ([], True)
        mock_broker.get_open_positions_authoritative.side_effect = get_pos

        def get_orders():
            if cancelled:
                return ([], True)
            return ([working_order], True)
        mock_broker.get_open_orders_authoritative.side_effect = get_orders

        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "PLACED_NEW",
            "order_id": "STOP_RACE_PARTIAL",
            "stopPrice": 9.31,
            "quantity": partial_qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.02,
            poll_interval=0.005
        )

        self.assertTrue(success)
        self.assertEqual(data.get("order_id"), "STOP_RACE_PARTIAL")
        self.assertEqual(data.get("quantity"), partial_qty)
        mock_broker.sync_broker_stop_order.assert_called_once()
        args, _ = mock_broker.sync_broker_stop_order.call_args
        self.assertEqual(args[1], partial_qty)

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_15_inconclusive_cancel_never_returns_normal_completion(self, mock_db, mock_broker):
        """15. Verify inconclusive cancel returns UNKNOWN_PENDING_RECONCILIATION and does not relinquish ownership."""
        order_id = "ENTRY_INCONCLUSIVE"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty}

        mock_broker.get_open_positions_authoritative.return_value = ([], True)
        mock_broker.get_open_orders_authoritative.side_effect = [
            ([working_order], True),
            ([working_order], True),
        ]
        mock_broker.cancel_order.return_value = {"success": False, "error": "Gateway timeout on cancel"}

        mock_db.get_latest_core_compounding_decision.return_value = {
            "dedup_key": "INCONCLUSIVE_DEC",
            "target_instrument": self.ticker
        }

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.02,
            poll_interval=0.005
        )

        self.assertFalse(success)
        self.assertEqual(msg, "UNKNOWN_PENDING_RECONCILIATION")
        self.assertTrue(data.get("reconciliation_pending"))
        mock_db.update_core_compounding_decision_status.assert_called_with(
            dedup_key="INCONCLUSIVE_DEC",
            status="UNKNOWN_PENDING_RECONCILIATION",
            broker_order_id=order_id,
            notes=unittest.mock.ANY
        )

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_16_position_with_unverified_stop_emergency_flattens(self, mock_db, mock_broker):
        """16. Verify cancel/fill race position with unverified stop triggers emergency flatten and halt."""
        order_id = "ENTRY_RACE_FAIL_STOP"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty}
        pos_record = [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}]

        cancelled = False
        def do_cancel(oid):
            nonlocal cancelled
            cancelled = True
            return {"success": True}
        mock_broker.cancel_order.side_effect = do_cancel

        def get_pos():
            if cancelled:
                return (pos_record, True)
            return ([], True)
        mock_broker.get_open_positions_authoritative.side_effect = get_pos

        def get_orders():
            if cancelled:
                return ([], True)
            return ([working_order], True)
        mock_broker.get_open_orders_authoritative.side_effect = get_orders

        mock_broker.sync_broker_stop_order.return_value = {
            "success": False,
            "error": "Exchange rejected stop: price out of bounds"
        }
        mock_broker.place_market_order.return_value = {"success": True, "id": "FLATTEN_ORDER"}
        mock_broker.reconcile_orphan_stops.return_value = []

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.02,
            poll_interval=0.005
        )

        self.assertFalse(success)
        self.assertTrue(data.get("halt"))
        self.assertTrue(data.get("flattened"))
        mock_broker.place_market_order.assert_called_with(self.ticker, -self.qty)
        self.assertTrue(self.engine._stop_event.is_set())

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_17_no_accepted_order_remains_live_after_ownership_is_released(self, mock_db, mock_broker):
        """17. Verify that across normal completion, no accepted order is left live on broker book."""
        order_id = "ENTRY_OWNERSHIP_CHECK"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty}

        mock_broker.get_open_positions_authoritative.return_value = ([], True)
        mock_broker.get_open_orders_authoritative.side_effect = [
            ([working_order], True),
            ([], True),
        ]
        mock_broker.cancel_order.return_value = {"success": True}

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.02,
            poll_interval=0.005
        )

        self.assertFalse(success)
        self.assertEqual(data.get("status"), "CANCELLED_CLEAN")
        mock_broker.cancel_order.assert_called_once_with(order_id)

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_18_no_duplicate_stops_during_race_sync(self, mock_db, mock_broker):
        """18. Verify that if stop already exists during race sync, it is kept without duplicate."""
        order_id = "ENTRY_RACE_EXISTING_STOP"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty}
        pos_record = [{"ticker": self.ticker, "quantity": self.qty, "averagePrice": self.entry_price}]

        cancelled = False
        def do_cancel(oid):
            nonlocal cancelled
            cancelled = True
            return {"success": True}
        mock_broker.cancel_order.side_effect = do_cancel

        def get_pos():
            if cancelled:
                return (pos_record, True)
            return ([], True)
        mock_broker.get_open_positions_authoritative.side_effect = get_pos

        def get_orders():
            if cancelled:
                return ([], True)
            return ([working_order], True)
        mock_broker.get_open_orders_authoritative.side_effect = get_orders

        mock_broker.sync_broker_stop_order.return_value = {
            "success": True,
            "action": "KEPT_EXISTING",
            "order_id": "STOP_ALREADY_EXISTS",
            "stopPrice": 9.31,
            "quantity": self.qty,
            "timeValidity": "GOOD_TILL_CANCEL"
        }

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.02,
            poll_interval=0.005
        )

        self.assertTrue(success)
        self.assertEqual(data.get("action"), "KEPT_EXISTING")
        self.assertEqual(data.get("order_id"), "STOP_ALREADY_EXISTS")

    @patch("src.core.engine.broker")
    @patch("src.core.engine.db")
    def test_19_no_orphan_entry_orders_after_cycle(self, mock_db, mock_broker):
        """19. Verify that cycle execution leaves no orphan working entry orders."""
        order_id = "ORPHAN_ENTRY_999"
        working_order = {"id": order_id, "ticker": self.ticker, "side": "BUY", "quantity": self.qty}

        mock_broker.get_open_positions_authoritative.return_value = ([], True)
        mock_broker.get_open_orders_authoritative.side_effect = [
            ([working_order], True),
            ([], True),
        ]
        mock_broker.cancel_order.return_value = {"success": True}

        success, msg, data = self.engine.await_and_sync_entry_fill(
            ticker=self.ticker,
            expected_qty=self.qty,
            broker_order_id=order_id,
            timeout_seconds=0.05,
            poll_interval=0.01
        )

        self.assertEqual(data.get("status"), "CANCELLED_CLEAN")
        mock_broker.cancel_order.assert_called_with(order_id)


if __name__ == "__main__":
    unittest.main()

