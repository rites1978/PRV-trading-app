"""
PRV CAPITAL | F7 REGRESSION SUITE — TEST / VERIFICATION ISOLATION

Locks in two fail-closed properties:
  1. Ordinary regression tests can never mutate live Trading212 broker state.
  2. Ordinary regression tests can never open the production SQLite database.

Live broker writes require an explicit double opt-in inside a test runtime.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.runtime_guard import (
    LiveBrokerWriteBlocked,
    LiveBrokerReadBlocked,
    assert_live_broker_read_allowed,
    assert_live_broker_write_allowed,
    live_broker_reads_allowed,
    live_caches_may_hydrate_from_disk,
    ENV_ALLOW_LIVE_READS,
    is_test_runtime,
    live_broker_writes_allowed,
    resolve_db_path,
    ENV_ALLOW_LIVE_WRITES,
    ENV_ALLOW_LIVE_WRITES_IN_TESTS,
)
from src.brokers.trading212 import broker
from src.database.db import db


class TestF7RuntimeIsolationGuard(unittest.TestCase):

    def test_test_runtime_is_detected(self):
        """Running under unittest must be recognised as a test runtime."""
        self.assertTrue(is_test_runtime(), "unittest runtime must be detected")

    def test_default_test_mode_blocks_live_writes(self):
        """DEFAULT_TEST_MODE: live broker writes denied with no opt-in."""
        allowed, reason = live_broker_writes_allowed()
        self.assertFalse(allowed, "live writes must be denied by default in tests")
        self.assertIn("BLOCKED_TEST_RUNTIME", reason)

    def test_every_mutating_http_method_is_gated(self):
        """POST/PUT/PATCH/DELETE must all raise; GET must pass through."""
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.assertRaises(LiveBrokerWriteBlocked, msg=f"{method} must be blocked"):
                assert_live_broker_write_allowed(method, "equity/orders/stop")
        assert_live_broker_write_allowed("GET", "equity/orders")  # must not raise

    def test_broker_write_methods_never_reach_network(self):
        """LIVE_BROKER_WRITE_GUARD: no mutating call may reach the HTTP layer."""
        calls = []
        with patch("requests.post", side_effect=lambda *a, **k: calls.append("POST")), \
             patch("requests.delete", side_effect=lambda *a, **k: calls.append("DELETE")):
            results = [
                broker.place_stop_order("EMIMl_EQ", -1.0, 4062.10),
                broker.place_market_order("EMIMl_EQ", -1.0),
                broker.place_limit_order("EMIMl_EQ", 1.0, 4200.0),
                broker.place_stop_limit_order("EMIMl_EQ", -1.0, 4062.10, 4000.0),
                broker.cancel_order("54700786023"),
            ]
        self.assertEqual(len(calls), 0, "no mutating HTTP request may reach the network")
        for r in results:
            self.assertFalse(r.get("success"), "blocked write must not report success")
            # Two independent fail-closed guards stand in front of the HTTP layer: the
            # runtime write guard, and the entry lock (which refuses capital-deploying
            # BUYs earlier still). Either refusal satisfies this invariant -- what must
            # never happen is a mutating request reaching the network.
            self.assertRegex(
                str(r.get("error")),
                r"LIVE_BROKER_WRITE_BLOCKED|ENTRY_SUBMISSION_BLOCKED",
                "a blocked write must name the guard that refused it")

    def test_sync_broker_stop_order_cannot_mutate(self):
        """The stop-sync helper must not be able to place orders under test."""
        calls = []
        with patch("requests.post", side_effect=lambda *a, **k: calls.append("POST")), \
             patch("requests.delete", side_effect=lambda *a, **k: calls.append("DELETE")), \
             patch.object(broker, "get_open_orders", return_value=[]):
            res = broker.sync_broker_stop_order("EMIMl_EQ", 948.967, 4062.10)
        self.assertEqual(len(calls), 0, "stop sync must not reach the network in tests")
        self.assertFalse(res.get("success"))

    def test_production_database_is_never_opened(self):
        """TEST_DB_ISOLATION: the live DB file must not be the active connection."""
        prod = os.path.abspath("prv_capital.db")
        self.assertNotEqual(
            os.path.abspath(db.db_path), prod,
            "tests must never bind to the production database"
        )

    def test_db_path_redirected_under_test_runtime(self):
        """resolve_db_path must divert the production path while under test."""
        self.assertNotEqual(resolve_db_path("prv_capital.db"), "prv_capital.db")

    def test_explicit_test_db_path_is_honoured(self):
        """An operator-specified test DB path must win over the temp default."""
        with patch.dict(os.environ, {"PRV_TEST_DB_PATH": "/tmp/prv_explicit_test.db"}):
            self.assertEqual(resolve_db_path("prv_capital.db"), "/tmp/prv_explicit_test.db")

    def test_live_write_requires_double_opt_in_under_test(self):
        """LIVE_WRITE_REQUIRES_EXPLICIT_OPT_IN: one flag is not enough."""
        with patch.dict(os.environ, {ENV_ALLOW_LIVE_WRITES: "true"}, clear=False):
            allowed, _ = live_broker_writes_allowed()
            self.assertFalse(allowed, "a single flag must not unlock live writes in tests")

        # Write flags alone are still insufficient: live reads must also be authorised.
        with patch.dict(os.environ, {ENV_ALLOW_LIVE_WRITES: "true",
                                     ENV_ALLOW_LIVE_WRITES_IN_TESTS: "true"}, clear=False):
            allowed, _ = live_broker_writes_allowed()
            self.assertFalse(allowed, "write flags without the read flag must not unlock writes")

        with patch.dict(os.environ, {ENV_ALLOW_LIVE_READS: "true",
                                     ENV_ALLOW_LIVE_WRITES: "true",
                                     ENV_ALLOW_LIVE_WRITES_IN_TESTS: "true"}, clear=False):
            allowed, reason = live_broker_writes_allowed()
            self.assertTrue(allowed, "explicit read + double write opt-in must unlock live writes")
            self.assertEqual(reason, "ALLOWED_TEST_RUNTIME_DOUBLE_OPT_IN")

    # ------------------------------------------------------------------
    # READ ISOLATION
    # ------------------------------------------------------------------

    def test_default_test_mode_blocks_live_reads(self):
        """LIVE_BROKER_READ_GUARD: reads denied by default under test."""
        allowed, reason = live_broker_reads_allowed()
        self.assertFalse(allowed, "live reads must be denied by default in tests")
        self.assertIn("BLOCKED_TEST_RUNTIME", reason)

    def test_broker_reads_never_reach_network(self):
        """No GET may reach Trading212 from a default test runtime."""
        calls = []
        with patch("requests.get", side_effect=lambda *a, **k: calls.append("GET")):
            broker.get_open_orders(force_refresh=True)
            broker.get_open_positions(force_refresh=True)
            broker.get_account_summary(force_refresh=True)
        self.assertEqual(len(calls), 0, "no live read may reach the network in tests")

    def test_read_gate_raises_for_get(self):
        with self.assertRaises(LiveBrokerReadBlocked):
            assert_live_broker_read_allowed("GET", "equity/orders")

    def test_disk_snapshot_caches_withheld_from_tests(self):
        """Live account state must not leak into tests via disk snapshot caches."""
        self.assertFalse(live_caches_may_hydrate_from_disk())
        self.assertEqual(broker._cached_positions, [],
                         "broker must not hydrate live positions from disk under test")

    def test_required_read_write_matrix(self):
        """Exact matrix required by the F7 specification."""
        def state():
            return live_broker_reads_allowed()[0], live_broker_writes_allowed()[0]

        base = {ENV_ALLOW_LIVE_READS: "", ENV_ALLOW_LIVE_WRITES: "",
                ENV_ALLOW_LIVE_WRITES_IN_TESTS: ""}

        with patch.dict(os.environ, base, clear=False):
            self.assertEqual(state(), (False, False), "no flags -> reads DENIED, writes DENIED")

        with patch.dict(os.environ, {**base, ENV_ALLOW_LIVE_READS: "true"}, clear=False):
            self.assertEqual(state(), (True, False), "read flag only -> reads ALLOWED, writes DENIED")

        with patch.dict(os.environ, {**base, ENV_ALLOW_LIVE_WRITES: "true"}, clear=False):
            self.assertEqual(state(), (False, False), "write flag only -> reads DENIED, writes DENIED")

        with patch.dict(os.environ, {**base, ENV_ALLOW_LIVE_WRITES: "true",
                                     ENV_ALLOW_LIVE_WRITES_IN_TESTS: "true"}, clear=False):
            self.assertEqual(state(), (False, False),
                             "write flags without read flag must never unlock writes")

        with patch.dict(os.environ, {ENV_ALLOW_LIVE_READS: "true", ENV_ALLOW_LIVE_WRITES: "true",
                                     ENV_ALLOW_LIVE_WRITES_IN_TESTS: "true"}, clear=False):
            self.assertEqual(state(), (True, True), "explicit read+write flags -> both ALLOWED")

    def test_enabling_reads_never_enables_writes(self):
        with patch.dict(os.environ, {ENV_ALLOW_LIVE_READS: "true"}, clear=False):
            self.assertTrue(live_broker_reads_allowed()[0])
            self.assertFalse(live_broker_writes_allowed()[0],
                             "read opt-in must never grant write permission")

    def test_module_import_cannot_trigger_broker_write(self):
        """buy_stock.py must not execute a broker write at import time."""
        calls = []
        with patch("requests.post", side_effect=lambda *a, **k: calls.append("POST")):
            import importlib
            import buy_stock
            importlib.reload(buy_stock)
        self.assertEqual(len(calls), 0, "importing buy_stock must not place an order")
        self.assertTrue(hasattr(buy_stock, "main"), "executable behaviour must live under main()")

    def test_practice_new_entries_remain_disabled(self):
        """New entries must remain OFF."""
        from src.config.settings import settings
        self.assertFalse(settings.PRACTICE_NEW_ENTRIES_ALLOWED,
                         "PRACTICE_NEW_ENTRIES_ALLOWED must remain False")


if __name__ == "__main__":
    unittest.main()
