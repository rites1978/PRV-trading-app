"""
PRV CAPITAL | ORPHAN-STOP RECONCILIATION SAFETY

Defect: reconcile_orphan_stops read positions and orders with force_refresh=True but
never checked provenance. A failed positions read degrades to cached/empty data, so
with a healthy orders read every live protective stop looked orphaned and was
cancelled. Demonstrated against the live-shaped Core stop 54700786023.

Contract under test: a stop may be cancelled ONLY when the positions read AND the
orders read are authoritative and the ticker definitively holds zero quantity.
Cached, empty-fallback, timeout, HTTP 500, malformed or unknown state must never
cancel anything.

Mock-only. No live broker read or write.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brokers.trading212 import Trading212Broker

# Mirrors the real live Core protective stop.
LIVE_CORE_STOP = {
    "id": "54700786023", "ticker": "EMIMl_EQ", "type": "STOP",
    "quantity": -948.967, "stopPrice": 4062.10,
    "timeInForce": "GOOD_TILL_CANCEL", "status": "NEW",
}
HELD_POSITION = {"ticker": "EMIMl_EQ", "quantity": 948.967, "averagePrice": 4145.0, "currentPrice": 4157.0}
CLOSED_POSITION_SET = []          # genuinely flat
TRUE_ORPHAN_STOP = {
    "id": "STOP_ORPHAN_1", "ticker": "LLOYl_EQ", "type": "STOP",
    "quantity": -100.0, "stopPrice": 100.0, "timeInForce": "GOOD_TILL_CANCEL", "status": "NEW",
}


class OrphanHarness(unittest.TestCase):
    def setUp(self):
        self.broker = Trading212Broker()
        self.cancelled = []

    def run_reconcile(self, positions_result, orders_result, cancel_result=None,
                      post_cancel_orders=None):
        """positions_result / orders_result are either (data, fresh) tuples or an
        Exception instance to raise. Returns (cancelled_ids, cancel_calls, report)."""
        pos_calls = {"n": 0}
        ord_calls = {"n": 0}

        def fake_positions():
            pos_calls["n"] += 1
            if isinstance(positions_result, Exception):
                raise positions_result
            return positions_result

        def fake_orders():
            ord_calls["n"] += 1
            if isinstance(orders_result, Exception):
                raise orders_result
            # after a cancel, allow a distinct post-cancel view
            if post_cancel_orders is not None and ord_calls["n"] > 1:
                return post_cancel_orders
            return orders_result

        def fake_cancel(order_id):
            self.cancelled.append(order_id)
            if isinstance(cancel_result, Exception):
                raise cancel_result
            return cancel_result if cancel_result is not None else {"success": True}

        with patch.object(self.broker, "get_open_positions_authoritative", side_effect=fake_positions), \
             patch.object(self.broker, "get_open_orders_authoritative", side_effect=fake_orders), \
             patch.object(self.broker, "cancel_order", side_effect=fake_cancel):
            result = self.broker.reconcile_orphan_stops()
        return result, list(self.cancelled), getattr(self.broker, "last_orphan_reconciliation", {})


class TestOrphanStopReconciliationSafety(OrphanHarness):

    # ---- NONAUTHORITATIVE POSITIONS MUST NEVER CANCEL ----

    def test_ORPHAN_POSITIONS_TIMEOUT_ORDERS_FRESH(self):
        r, cancels, rep = self.run_reconcile(
            positions_result=TimeoutError("read timed out"),
            orders_result=([LIVE_CORE_STOP], True))
        self.assertEqual(cancels, [], "timeout on positions must cancel nothing")
        self.assertEqual(r, [])
        self.assertEqual(rep["status"], "ORPHAN_RECONCILIATION_DEFERRED")

    def test_ORPHAN_POSITIONS_500_ORDERS_FRESH(self):
        # An HTTP 500 surfaces as a non-authoritative read via provenance.
        r, cancels, rep = self.run_reconcile(
            positions_result=([], False),
            orders_result=([LIVE_CORE_STOP], True))
        self.assertEqual(cancels, [], "HTTP 500 positions read must cancel nothing")
        self.assertEqual(rep["status"], "ORPHAN_RECONCILIATION_DEFERRED")
        self.assertIn("NOT authoritative", rep["deferred_reason"])

    def test_ORPHAN_POSITIONS_STALE_CACHE_ORDERS_FRESH(self):
        """The exact live-hazard case: stale cache showing no positions."""
        r, cancels, rep = self.run_reconcile(
            positions_result=([], False),                 # stale cache, degraded
            orders_result=([LIVE_CORE_STOP], True))
        self.assertNotIn("54700786023", cancels,
                         "live Core protective stop must never be cancelled from stale state")
        self.assertEqual(cancels, [])

    def test_ORPHAN_POSITIONS_EMPTY_NONAUTHORITATIVE(self):
        """CACHED_EMPTY_POSITION_NEVER_COUNTS_AS_ZERO_HOLDING."""
        r, cancels, rep = self.run_reconcile(
            positions_result=([], False),
            orders_result=([LIVE_CORE_STOP, TRUE_ORPHAN_STOP], True))
        self.assertEqual(cancels, [], "empty non-authoritative positions is not proof of zero holding")

    # ---- NONAUTHORITATIVE ORDERS MUST NEVER CANCEL ----

    def test_ORPHAN_ORDERS_TIMEOUT_POSITIONS_FRESH(self):
        r, cancels, rep = self.run_reconcile(
            positions_result=(CLOSED_POSITION_SET, True),
            orders_result=TimeoutError("orders read timed out"))
        self.assertEqual(cancels, [], "timeout on orders must cancel nothing")
        self.assertEqual(rep["status"], "ORPHAN_RECONCILIATION_DEFERRED")

    def test_ORPHAN_ORDERS_NONAUTHORITATIVE_POSITIONS_FRESH(self):
        r, cancels, rep = self.run_reconcile(
            positions_result=(CLOSED_POSITION_SET, True),
            orders_result=([TRUE_ORPHAN_STOP], False))
        self.assertEqual(cancels, [], "non-authoritative orders must cancel nothing")

    def test_ORPHAN_BOTH_NONAUTHORITATIVE(self):
        r, cancels, rep = self.run_reconcile(
            positions_result=([], False),
            orders_result=([LIVE_CORE_STOP], False))
        self.assertEqual(cancels, [])
        self.assertEqual(rep["status"], "ORPHAN_RECONCILIATION_DEFERRED")

    # ---- LEGITIMATE BEHAVIOUR MUST BE PRESERVED ----

    def test_ORPHAN_TRUE_ZERO_POSITION_BOTH_AUTHORITATIVE(self):
        """A genuine orphan, proven by two authoritative reads, is still cancelled."""
        r, cancels, rep = self.run_reconcile(
            positions_result=(CLOSED_POSITION_SET, True),
            orders_result=([TRUE_ORPHAN_STOP], True),
            cancel_result={"success": True},
            post_cancel_orders=([], True))
        self.assertEqual(cancels, ["STOP_ORPHAN_1"], "a proven orphan must still be reconciled")
        self.assertEqual(r, ["STOP_ORPHAN_1"])
        self.assertEqual(rep["status"], "ORPHAN_RECONCILIATION_COMPLETED")

    def test_ORPHAN_HELD_POSITION_BOTH_AUTHORITATIVE(self):
        """A stop protecting a genuinely held position is never touched."""
        r, cancels, rep = self.run_reconcile(
            positions_result=([HELD_POSITION], True),
            orders_result=([LIVE_CORE_STOP], True))
        self.assertEqual(cancels, [], "stop for a held position must never be cancelled")
        self.assertEqual(rep["status"], "ORPHAN_RECONCILIATION_CLEAN")

    # ---- CANCEL RESULT MUST BE INSPECTED ----

    def test_ORPHAN_CANCEL_HTTP_500(self):
        r, cancels, rep = self.run_reconcile(
            positions_result=(CLOSED_POSITION_SET, True),
            orders_result=([TRUE_ORPHAN_STOP], True),
            cancel_result={"success": False, "error": "HTTP 500: server error"})
        self.assertEqual(cancels, ["STOP_ORPHAN_1"], "cancel was attempted")
        self.assertEqual(r, [], "a failed cancel must NOT be reported as reconciled")
        self.assertIn("STOP_ORPHAN_1", rep["unconfirmed"])

    def test_ORPHAN_CANCEL_TIMEOUT(self):
        r, cancels, rep = self.run_reconcile(
            positions_result=(CLOSED_POSITION_SET, True),
            orders_result=([TRUE_ORPHAN_STOP], True),
            cancel_result=TimeoutError("cancel timed out"))
        self.assertEqual(r, [], "a timed-out cancel must NOT be reported as reconciled")
        self.assertIn("STOP_ORPHAN_1", rep["unconfirmed"])

    def test_ORPHAN_CANCEL_SUCCESS_BUT_ORDER_STILL_PRESENT(self):
        """A success response contradicted by broker truth is not a confirmation."""
        r, cancels, rep = self.run_reconcile(
            positions_result=(CLOSED_POSITION_SET, True),
            orders_result=([TRUE_ORPHAN_STOP], True),
            cancel_result={"success": True},
            post_cancel_orders=([TRUE_ORPHAN_STOP], True))
        self.assertEqual(r, [], "order still present means cancellation is unconfirmed")
        self.assertIn("STOP_ORPHAN_1", rep["unconfirmed"])

    def test_ORPHAN_CANCEL_SUCCESS_POST_READ_NONAUTHORITATIVE(self):
        r, cancels, rep = self.run_reconcile(
            positions_result=(CLOSED_POSITION_SET, True),
            orders_result=([TRUE_ORPHAN_STOP], True),
            cancel_result={"success": True},
            post_cancel_orders=([], False))
        self.assertEqual(r, [], "cancellation cannot be confirmed from a stale post-read")
        self.assertIn("STOP_ORPHAN_1", rep["unconfirmed"])

    # ---- RESTART / DISK CACHE ----

    def test_ORPHAN_RESTART_WITH_DISK_CACHE_ONLY(self):
        """After a restart the broker may hold only disk-cache state. That is not
        authoritative and must never drive a cancellation."""
        fresh_broker = Trading212Broker()
        cancels = []
        with patch.object(fresh_broker, "get_open_positions_authoritative", return_value=([], False)), \
             patch.object(fresh_broker, "get_open_orders_authoritative", return_value=([LIVE_CORE_STOP], True)), \
             patch.object(fresh_broker, "cancel_order", side_effect=lambda oid: cancels.append(oid)):
            result = fresh_broker.reconcile_orphan_stops()
        self.assertEqual(cancels, [], "disk-cache-only state must never cancel a stop")
        self.assertEqual(result, [])

    # ---- MALFORMED PAYLOADS ----

    def test_ORPHAN_MALFORMED_POSITION_PAYLOAD_DEFERS(self):
        r, cancels, rep = self.run_reconcile(
            positions_result=([{"ticker": "EMIMl_EQ", "quantity": "not-a-number"}], True),
            orders_result=([LIVE_CORE_STOP], True))
        self.assertEqual(cancels, [], "malformed positions must never be read as zero holdings")
        self.assertEqual(rep["status"], "ORPHAN_RECONCILIATION_DEFERRED")

    # ---- RACE: position appears between first read and cancel ----

    def test_ORPHAN_POSITION_REAPPEARS_ON_RECONFIRMATION(self):
        """If re-confirmation shows the position present, the stop is retained."""
        seq = [(CLOSED_POSITION_SET, True), ([HELD_POSITION], True)]
        calls = {"n": 0}
        cancels = []

        def positions():
            r = seq[min(calls["n"], len(seq) - 1)]
            calls["n"] += 1
            return r

        with patch.object(self.broker, "get_open_positions_authoritative", side_effect=positions), \
             patch.object(self.broker, "get_open_orders_authoritative", return_value=([LIVE_CORE_STOP], True)), \
             patch.object(self.broker, "cancel_order", side_effect=lambda oid: cancels.append(oid)):
            result = self.broker.reconcile_orphan_stops()
        self.assertEqual(cancels, [], "re-confirmed holding must abort the cancellation")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
