"""
PRV CAPITAL | AUTHORITATIVE-READ PROVENANCE CONTRACT

Defect: the authoritative wrappers inferred freshness from data SHAPE. A bare list
returned (data, True), and the engine wrappers used getattr(broker, "_*_last_fresh",
True), so a missing provenance attribute defaulted to authoritative.

Contract: absence of provenance is NEVER freshness. Every ambiguous, malformed or
missing-provenance result must yield authoritative_fresh = False.

Mock-only. No live broker read or write.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brokers.trading212 import Trading212Broker
from src.core.engine import PRVQuantEngine

LIVE_CORE_STOP = {
    "id": "54700786023", "ticker": "EMIMl_EQ", "type": "STOP",
    "quantity": -948.967, "stopPrice": 4062.10,
    "timeInForce": "GOOD_TILL_CANCEL", "status": "NEW",
}
POSITION = {"ticker": "EMIMl_EQ", "quantity": 948.967, "averagePrice": 4145.0}


class BareBroker:
    """A broker-like object with NO provenance attributes at all."""
    def get_open_positions_authoritative(self):
        return [POSITION]                      # bare list, no freshness

    def get_open_orders_authoritative(self):
        return [LIVE_CORE_STOP]                # bare list, no freshness

    def get_open_positions(self, **kw):
        return [POSITION]

    def get_open_orders(self, **kw):
        return [LIVE_CORE_STOP]


class TestAuthoritativeProvenanceContract(unittest.TestCase):

    def setUp(self):
        self.broker = Trading212Broker()
        self._orig_instance = PRVQuantEngine._instance
        self.engine = PRVQuantEngine()

    def tearDown(self):
        PRVQuantEngine._instance = self._orig_instance

    # ---- bare list must never be upgraded to authoritative ----

    def test_AUTHORITATIVE_POSITIONS_PLAIN_LIST_IS_NOT_FRESH(self):
        with patch.object(self.broker, "get_open_positions", return_value=[POSITION]):
            data, fresh = self.broker.get_open_positions_authoritative()
        self.assertFalse(fresh, "a bare list carries no provenance and must not be fresh")
        self.assertEqual(data, [POSITION], "data must still be returned")

    def test_AUTHORITATIVE_ORDERS_PLAIN_LIST_IS_NOT_FRESH(self):
        with patch.object(self.broker, "get_open_orders", return_value=[LIVE_CORE_STOP]):
            data, fresh = self.broker.get_open_orders_authoritative()
        self.assertFalse(fresh, "a bare list carries no provenance and must not be fresh")
        self.assertEqual(data, [LIVE_CORE_STOP])

    # ---- malformed tuples must never be authoritative ----

    def test_AUTHORITATIVE_POSITIONS_MALFORMED_TUPLE_IS_NOT_FRESH(self):
        for bad in [([POSITION],), ([POSITION], True, "extra"), tuple(), ("nonsense",)]:
            with self.subTest(shape=bad):
                with patch.object(self.broker, "get_open_positions", return_value=bad):
                    data, fresh = self.broker.get_open_positions_authoritative()
                self.assertFalse(fresh, f"malformed tuple {bad!r} must not be authoritative")

    def test_AUTHORITATIVE_ORDERS_MALFORMED_TUPLE_IS_NOT_FRESH(self):
        for bad in [([LIVE_CORE_STOP],), ([LIVE_CORE_STOP], True, "extra"), tuple(), (None,)]:
            with self.subTest(shape=bad):
                with patch.object(self.broker, "get_open_orders", return_value=bad):
                    data, fresh = self.broker.get_open_orders_authoritative()
                self.assertFalse(fresh, f"malformed tuple {bad!r} must not be authoritative")

    # ---- missing freshness attribute defaults FALSE ----

    def test_MISSING_FRESHNESS_ATTRIBUTE_DEFAULTS_FALSE(self):
        bare = BareBroker()
        self.assertFalse(hasattr(bare, "_positions_last_fresh"))
        self.assertFalse(hasattr(bare, "_orders_last_fresh"))

        pos, pos_fresh = self.engine.fetch_positions_authoritative(bare)
        ords, ords_fresh = self.engine.fetch_orders_authoritative(bare)

        self.assertFalse(pos_fresh, "missing _positions_last_fresh must default to False")
        self.assertFalse(ords_fresh, "missing _orders_last_fresh must default to False")

    def test_engine_wrappers_honour_explicit_false_provenance(self):
        """A genuine (data, False) must survive the engine wrapper unchanged."""
        with patch.object(self.broker, "get_open_positions_authoritative",
                          return_value=([POSITION], False)), \
             patch.object(self.broker, "get_open_orders_authoritative",
                          return_value=([LIVE_CORE_STOP], False)):
            _, pf = self.engine.fetch_positions_authoritative(self.broker)
            _, of = self.engine.fetch_orders_authoritative(self.broker)
        self.assertFalse(pf)
        self.assertFalse(of)

    def test_engine_wrappers_preserve_genuine_true_provenance(self):
        """Hardening must not break legitimate authoritative reads."""
        with patch.object(self.broker, "get_open_positions_authoritative",
                          return_value=([POSITION], True)), \
             patch.object(self.broker, "get_open_orders_authoritative",
                          return_value=([LIVE_CORE_STOP], True)):
            pos, pf = self.engine.fetch_positions_authoritative(self.broker)
            ords, of = self.engine.fetch_orders_authoritative(self.broker)
        self.assertTrue(pf)
        self.assertTrue(of)
        self.assertEqual(pos, [POSITION])
        self.assertEqual(ords, [LIVE_CORE_STOP])

    # ---- end-to-end: the hardening protects the live stop ----

    def test_ORPHAN_RECONCILIATION_PLAIN_LIST_NEVER_CANCELS_STOP(self):
        """With provenance absent, reconciliation must defer, not cancel."""
        cancelled = []
        with patch.object(self.broker, "get_open_positions", return_value=[]), \
             patch.object(self.broker, "get_open_orders", return_value=[LIVE_CORE_STOP]), \
             patch.object(self.broker, "cancel_order",
                          side_effect=lambda oid: cancelled.append(oid)):
            result = self.broker.reconcile_orphan_stops()

        self.assertEqual(cancelled, [],
                         "no-provenance reads must never cancel a protective stop")
        self.assertEqual(result, [])
        self.assertEqual(
            self.broker.last_orphan_reconciliation["status"],
            "ORPHAN_RECONCILIATION_DEFERRED")
        self.assertNotIn("54700786023", cancelled)

    def test_INVARIANT_missing_provenance_never_counts_as_authoritative(self):
        """MISSING_PROVENANCE_NEVER_COUNTS_AS_AUTHORITATIVE across every wrapper."""
        cases = []
        for ret in ([POSITION], ([POSITION],), tuple(), None, "garbage"):
            with patch.object(self.broker, "get_open_positions", return_value=ret):
                cases.append(self.broker.get_open_positions_authoritative()[1])
        for ret in ([LIVE_CORE_STOP], ([LIVE_CORE_STOP],), tuple(), None, "garbage"):
            with patch.object(self.broker, "get_open_orders", return_value=ret):
                cases.append(self.broker.get_open_orders_authoritative()[1])
        bare = BareBroker()
        cases.append(self.engine.fetch_positions_authoritative(bare)[1])
        cases.append(self.engine.fetch_orders_authoritative(bare)[1])
        self.assertTrue(all(c is False for c in cases),
                        f"every ambiguous provenance case must be False, got {cases}")

    def test_no_true_default_remains_in_source(self):
        """Guard against reintroducing a True provenance default."""
        import inspect
        from src.core import engine as engine_mod
        from src.brokers import trading212 as t212_mod
        for mod in (engine_mod, t212_mod):
            src = inspect.getsource(mod)
            self.assertNotIn('_last_fresh", True', src,
                             f"{mod.__name__} must not default provenance to True")


if __name__ == "__main__":
    unittest.main()
