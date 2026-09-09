"""
PRV CAPITAL | F3 REGRESSION SUITE — CORE STRATEGY ROUTING

Defect: monitor_open_positions recognised only ("V2","ETF_V1","PRV_HIT_AND_RUN_ETF_V1")
and sent everything else to the legacy V1 swing branch, which uses
settings.DEFAULT_STOP_LOSS_PCT (2.5%) and time_validity="DAY". Core Compounding
positions therefore had a correct GOOD_TILL_CANCEL stop overwritten with a legacy
2.5% DAY stop by the 15-second watchdog.

These tests are mock-only. No live broker read or write occurs.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import settings
from src.core.engine import PRVQuantEngine
from src.brokers.trading212 import broker
from src.data.market_data import market_data
from src.strategies.core_compounding_v1 import core_compounding_strategy

CORE_ID = "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1"

# Mirrors the live EMIM position shape (broker-native GBX), so the routing test
# exercises the same data that produced the incorrect 4041.38 DAY stop.
CORE_POSITION = [{
    "ticker": "EMIMl_EQ",
    "quantity": 948.967,
    "averagePrice": 4145.00000527,
    "currentPrice": 4157.0,
}]

LEGACY_POSITION = [{
    "ticker": "LLOYl_EQ",
    "quantity": 100.0,
    "averagePrice": 100.0,
    "currentPrice": 101.0,
}]


class F3RoutingHarness(unittest.TestCase):
    """Runs monitor_open_positions under a given strategy id with every broker
    mutation point instrumented, so routing can be proven by call counts."""

    def setUp(self):
        # PRVQuantEngine is a process singleton shared with the module-level
        # quant_engine. Snapshot mutable shared state so these tests cannot leak
        # tickers into other suites' expectations.
        self._orig_instance = PRVQuantEngine._instance
        self.engine = PRVQuantEngine()
        self._orig_peaks = dict(getattr(self.engine, "position_peaks", {}))
        self.engine.paper_mode = False
        self.engine._stop_event.set()
        self.engine.is_running = False
        self.orig_mode = settings.ACCOUNT_MODE
        settings.ACCOUNT_MODE = "PRACTICE"

    def tearDown(self):
        settings.ACCOUNT_MODE = self.orig_mode
        # Restore the shared singleton exactly as found.
        PRVQuantEngine._instance = self._orig_instance
        if self._orig_instance is not None:
            self._orig_instance.position_peaks.clear()
            self._orig_instance.position_peaks.update(self._orig_peaks)

    def run_monitor(self, strategy_id, positions):
        """Returns a dict of observed broker mutations and branch call counts."""
        calls = {"sync_stop": [], "place_stop": [], "place_market": [],
                 "cancel": [], "exit": [], "orphan": []}
        # PRVQuantEngine is a process singleton (__new__ returns a shared instance),
        # so counters persist across tests. Measure deltas, never absolutes.
        before_core = getattr(self.engine, "core_watchdog_observations", 0)
        before_unknown = getattr(self.engine, "unknown_strategy_skips", 0)

        def rec(name, ret=None):
            def _f(*a, **k):
                calls[name].append({"args": a, "kwargs": k})
                return ret
            return _f

        with patch("src.strategies.registry.strategy_registry.get_active_execution_strategy_id",
                   return_value=strategy_id), \
             patch.object(broker, "get_open_positions", return_value=positions), \
             patch.object(broker, "get_open_orders", return_value=[]), \
             patch.object(broker, "reconcile_orphan_stops", side_effect=rec("orphan", [])), \
             patch.object(broker, "sync_broker_stop_order",
                          side_effect=rec("sync_stop", {"success": True, "action": "PLACED_NEW"})), \
             patch.object(broker, "place_stop_order",
                          side_effect=rec("place_stop", {"success": True, "data": {"id": "S1"}})), \
             patch.object(broker, "place_market_order",
                          side_effect=rec("place_market", {"success": True, "data": {"id": "M1"}})), \
             patch.object(broker, "cancel_order", side_effect=rec("cancel", {"success": True})), \
             patch("src.execution.order_router.order_router.route_exit_order",
                   side_effect=rec("exit", (False, "mocked", {}))), \
             patch.object(market_data, "get_market_snapshot",
                          return_value={"success": True, "indicators": {"atr": 0.2}, "recent_returns": []}):
            closed, _ = self.engine.monitor_open_positions(positions)

        calls["closed"] = closed
        calls["core_observations"] = getattr(self.engine, "core_watchdog_observations", 0) - before_core
        calls["unknown_skips"] = getattr(self.engine, "unknown_strategy_skips", 0) - before_unknown
        return calls


class TestF3CoreStrategyRouting(F3RoutingHarness):

    # ---------------- F3_CORE_ID_ROUTES_TO_CORE ----------------
    def test_F3_CORE_ID_ROUTES_TO_CORE(self):
        r = self.run_monitor(CORE_ID, CORE_POSITION)
        self.assertEqual(r["core_observations"], 1,
                         "CORE_POSITION_MANAGER_CALL_COUNT must be 1")

    # ------------- F3_CORE_ID_NEVER_ROUTES_TO_LEGACY -------------
    def test_F3_CORE_ID_NEVER_ROUTES_TO_LEGACY(self):
        r = self.run_monitor(CORE_ID, CORE_POSITION)
        # LEGACY_POSITION_MANAGER_CALL_COUNT = 0: the legacy branch's only observable
        # side effects are stop synchronisation and exit routing.
        self.assertEqual(len(r["sync_stop"]), 0, "Core must never reach legacy stop sync")
        self.assertEqual(len(r["place_stop"]), 0, "Core must never place a stop from the watchdog")
        self.assertEqual(len(r["exit"]), 0, "Core must never exit via the legacy watchdog branch")
        self.assertEqual(len(r["place_market"]), 0, "Core must never market-order from the watchdog")
        self.assertEqual(len(r["cancel"]), 0, "Core must never cancel orders from the watchdog")

    # -------- F3_CORE_POSITION_RESTART_ROUTES_TO_CORE --------
    def test_F3_CORE_POSITION_RESTART_ROUTES_TO_CORE(self):
        """A genuinely restarted engine must still route Core to Core.

        PRVQuantEngine is a singleton, so a real restart is simulated by clearing
        the cached instance and forcing full re-initialisation.
        """
        PRVQuantEngine._instance = None
        self.engine = PRVQuantEngine()          # true re-construction
        self.assertEqual(getattr(self.engine, "core_watchdog_observations", 0), 0,
                         "restarted engine must start with clean watchdog state")
        self.engine.paper_mode = False
        r = self.run_monitor(CORE_ID, CORE_POSITION)
        self.assertEqual(r["core_observations"], 1)
        self.assertEqual(len(r["sync_stop"]), 0)

    # --- F3_CORE_POSITION_WITH_EXISTING_GTC_STOP_NOT_DOWNGRADED_TO_DAY ---
    def test_F3_CORE_POSITION_WITH_EXISTING_GTC_STOP_NOT_DOWNGRADED_TO_DAY(self):
        """The live-shaped GTC stop must survive the watchdog untouched."""
        existing_gtc = [{
            "id": "54700786023", "ticker": "EMIMl_EQ", "type": "STOP",
            "quantity": -948.967, "stopPrice": 4062.10,
            "timeInForce": "GOOD_TILL_CANCEL", "status": "NEW",
        }]
        calls = {"sync": [], "place": [], "cancel": []}
        with patch("src.strategies.registry.strategy_registry.get_active_execution_strategy_id",
                   return_value=CORE_ID), \
             patch.object(broker, "get_open_positions", return_value=CORE_POSITION), \
             patch.object(broker, "get_open_orders", return_value=existing_gtc), \
             patch.object(broker, "reconcile_orphan_stops", return_value=[]), \
             patch.object(broker, "sync_broker_stop_order",
                          side_effect=lambda *a, **k: calls["sync"].append((a, k))), \
             patch.object(broker, "place_stop_order",
                          side_effect=lambda *a, **k: calls["place"].append((a, k))), \
             patch.object(broker, "cancel_order",
                          side_effect=lambda *a, **k: calls["cancel"].append((a, k))), \
             patch.object(market_data, "get_market_snapshot",
                          return_value={"success": True, "indicators": {"atr": 0.2}, "recent_returns": []}):
            self.engine.monitor_open_positions(CORE_POSITION)

        self.assertEqual(calls["sync"], [], "watchdog must not re-sync a Core stop")
        self.assertEqual(calls["place"], [], "watchdog must not place a Core stop")
        self.assertEqual(calls["cancel"], [], "watchdog must not cancel a Core stop")
        # The existing protection is therefore still exactly as supplied.
        self.assertEqual(existing_gtc[0]["timeInForce"], "GOOD_TILL_CANCEL")
        self.assertEqual(existing_gtc[0]["stopPrice"], 4062.10)

    # ---------- F3_LEGACY_STRATEGY_STILL_ROUTES_TO_LEGACY ----------
    def test_F3_LEGACY_STRATEGY_STILL_ROUTES_TO_LEGACY(self):
        r = self.run_monitor("V1", LEGACY_POSITION)
        self.assertEqual(r["core_observations"], 0, "V1 must not reach the Core watchdog")
        self.assertEqual(r["unknown_skips"], 0, "V1 must not be treated as unknown")
        self.assertGreaterEqual(len(r["sync_stop"]), 1,
                                "legacy V1 must still synchronise its broker stop")
        # Legacy behaviour unchanged: 2.5% source and DAY validity preserved for V1.
        kwargs = r["sync_stop"][0]["kwargs"]
        self.assertEqual(kwargs.get("time_validity"), "DAY",
                         "legacy V1 stop validity must remain unchanged")
        expected = round(100.0 * (1.0 - settings.DEFAULT_STOP_LOSS_PCT), 2)
        self.assertEqual(r["sync_stop"][0]["args"][2], expected,
                         "legacy V1 must still use DEFAULT_STOP_LOSS_PCT")

    # ---------------- F3_V2_BEHAVIOUR_UNCHANGED ----------------
    def test_F3_V2_BEHAVIOUR_UNCHANGED(self):
        for sid in ("V2", "ETF_V1", "PRV_HIT_AND_RUN_ETF_V1"):
            with self.subTest(strategy=sid):
                r = self.run_monitor(sid, LEGACY_POSITION)
                self.assertEqual(r["core_observations"], 0,
                                 f"{sid} must not reach the Core watchdog")
                self.assertEqual(r["unknown_skips"], 0,
                                 f"{sid} must not be treated as unknown")
                self.assertGreaterEqual(len(r["sync_stop"]), 1,
                                        f"{sid} must still sync its stop via the V2 branch")
                self.assertEqual(r["sync_stop"][0]["kwargs"].get("time_validity"),
                                 "GOOD_TILL_CANCEL",
                                 f"{sid} must retain GTC persistence")

    # ------------- F3_UNKNOWN_STRATEGY_FAILS_CLOSED -------------
    def test_F3_UNKNOWN_STRATEGY_FAILS_CLOSED(self):
        r = self.run_monitor("SOME_UNRATIFIED_STRATEGY_X", LEGACY_POSITION)
        self.assertEqual(r["unknown_skips"], 1, "unknown id must be counted as fail-closed")
        self.assertEqual(r["core_observations"], 0)
        self.assertEqual(len(r["sync_stop"]), 0, "unknown id must not reach legacy stop sync")
        self.assertEqual(len(r["place_stop"]), 0)
        self.assertEqual(len(r["place_market"]), 0)
        self.assertEqual(len(r["cancel"]), 0)
        self.assertEqual(len(r["exit"]), 0)
        self.assertEqual(r["closed"], [], "unknown id must close no positions")

    # -------------- F3_CORE_IWDA_BLOCK_UNCHANGED --------------
    def test_F3_CORE_IWDA_BLOCK_UNCHANGED(self):
        """The IWDA execution block must be untouched by F3."""
        import inspect
        from src.execution import order_router as orr
        src = inspect.getsource(orr)
        self.assertIn("IWDA_UNIT_MISMATCH_BLOCKED", src,
                      "IWDA order-router block must still exist")
        self.assertIn("IWDA is blocked from execution pending unit-normalisation remediation", src)
        engine_src = inspect.getsource(sys.modules["src.core.engine"])
        self.assertIn("IWDA is blocked from execution pending unit-normalisation remediation",
                      engine_src, "IWDA engine block must still exist")

    # ---------------- Invariant assertions ----------------
    def test_INVARIANT_core_watchdog_never_sources_legacy_stop_pct(self):
        """CORE_STOP_PCT_SOURCE_IS_FROZEN_CORE: the Core watchdog must not apply 2.5%."""
        import ast, inspect, textwrap
        src = textwrap.dedent(inspect.getsource(PRVQuantEngine._monitor_core_position_watchdog))
        fn = ast.parse(src).body[0]
        body = fn.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]                      # strip docstring; assert on real code only
        code = "\n".join(ast.unparse(n) for n in body)
        self.assertNotIn("DEFAULT_STOP_LOSS_PCT", code,
                         "Core watchdog code must never source the legacy 2.5% value")
        self.assertNotIn("sync_broker_stop_order", code,
                         "Core watchdog code must never synchronise a broker stop")
        self.assertNotIn("place_stop_order", code)
        self.assertNotIn("cancel_order", code)
        self.assertNotIn("DAY", code, "Core watchdog code must never emit DAY validity")
        self.assertNotEqual(core_compounding_strategy.STOP_LOSS_PCT,
                            settings.DEFAULT_STOP_LOSS_PCT,
                            "test is only meaningful while Core 2% differs from legacy 2.5%")

    def test_INVARIANT_watchdog_tick_cannot_mutate_core_protection(self):
        """The 15s watchdog at engine.py:2100 calls monitor_open_positions() with no
        arguments; prove that entry point also cannot mutate Core protection."""
        calls = []
        with patch("src.strategies.registry.strategy_registry.get_active_execution_strategy_id",
                   return_value=CORE_ID), \
             patch.object(broker, "get_open_positions", return_value=CORE_POSITION), \
             patch.object(broker, "get_open_orders", return_value=[]), \
             patch.object(broker, "reconcile_orphan_stops", return_value=[]), \
             patch.object(broker, "sync_broker_stop_order",
                          side_effect=lambda *a, **k: calls.append(("sync", a, k))), \
             patch.object(broker, "place_stop_order",
                          side_effect=lambda *a, **k: calls.append(("place", a, k))), \
             patch.object(broker, "cancel_order",
                          side_effect=lambda *a, **k: calls.append(("cancel", a, k))), \
             patch.object(market_data, "get_market_snapshot",
                          return_value={"success": True, "indicators": {"atr": 0.2}, "recent_returns": []}):
            self.engine.monitor_open_positions()      # exact 15s-watchdog call signature
        self.assertEqual(calls, [], "15s watchdog must not mutate Core broker protection")


if __name__ == "__main__":
    unittest.main()
