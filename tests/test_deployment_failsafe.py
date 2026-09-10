"""
PRV CAPITAL | DEPLOYMENT FAIL-SAFE REGRESSION SUITE

Invariant: DEPLOYMENT_NEVER_AUTOSTARTS_TRADING_WITHOUT_EXPLICIT_OPT_IN.

A deploy (Render redeploy, container restart, crash-loop recovery) must never begin
autonomous trading on its own. The autonomous engine starts only on an explicit,
exactly-approved opt-in value; absent, empty or malformed values leave it stopped.

Separately, the entry lock (PRACTICE_NEW_ENTRIES_ALLOWED=False) must prevent every
autonomous new-entry submission even with the engine running, a valid signal, ample
cash and position headroom.

Mock-only. No live broker read or write.
"""
import ast
import inspect
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import settings
from src.core.engine import PRVQuantEngine
from src.core.runtime_guard import (
    autonomous_engine_autostart_allowed,
    AUTORUN_ENGINE_ENV,
)
from src.brokers.trading212 import broker
from src.data.market_data import market_data
from src.database.db import db
from src.strategies.core_compounding_v1 import core_compounding_strategy as CORE
from tests._provenance_mocks import provenance_aware


class TestAutorunFailClosed(unittest.TestCase):
    """The autostart opt-in is fail-closed by construction."""

    def _with_env(self, value):
        env = dict(os.environ)
        env.pop(AUTORUN_ENGINE_ENV, None)
        if value is not None:
            env[AUTORUN_ENGINE_ENV] = value
        return patch.dict(os.environ, env, clear=True)

    def test_AUTORUN_ENV_ABSENT_ENGINE_STAYS_STOPPED(self):
        with self._with_env(None):
            allowed, reason = autonomous_engine_autostart_allowed()
        self.assertFalse(allowed)
        self.assertIn("not set", reason)

    def test_AUTORUN_ENV_FALSE_ENGINE_STAYS_STOPPED(self):
        for value in ("false", "False", "FALSE", " false "):
            with self.subTest(value=value):
                with self._with_env(value):
                    self.assertFalse(autonomous_engine_autostart_allowed()[0])

    def test_AUTORUN_ENV_EMPTY_ENGINE_STAYS_STOPPED(self):
        for value in ("", "   ", "\t"):
            with self.subTest(value=repr(value)):
                with self._with_env(value):
                    self.assertFalse(autonomous_engine_autostart_allowed()[0])

    def test_AUTORUN_ENV_GARBAGE_ENGINE_STAYS_STOPPED(self):
        # Truthy-looking values are deliberately NOT accepted: only the exact opt-in.
        for value in ("1", "yes", "y", "on", "TRUE_", "true!", "maybe", "0", "null",
                      "none", "enabled", "tru"):
            with self.subTest(value=value):
                with self._with_env(value):
                    self.assertFalse(autonomous_engine_autostart_allowed()[0],
                                     f"{value!r} must not start autonomous trading")

    def test_AUTORUN_ENV_TRUE_ENGINE_CAN_START(self):
        for value in ("true", "TRUE", "True", " true "):
            with self.subTest(value=value):
                with self._with_env(value):
                    allowed, _ = autonomous_engine_autostart_allowed()
                    self.assertTrue(allowed, "the explicit opt-in must be honoured")

    def test_DEPLOYMENT_DEFAULT_IS_FAIL_CLOSED(self):
        """No implicit truthy default may exist anywhere in the source."""
        from src.core import runtime_guard
        from src.api import routes

        for mod in (runtime_guard, routes):
            src = inspect.getsource(mod)
            for banned in ('getenv("PRV_AUTORUN_ENGINE", "true")',
                           "getenv('PRV_AUTORUN_ENGINE', 'true')",
                           'getenv(AUTORUN_ENGINE_ENV, "true")'):
                self.assertNotIn(banned, src,
                                 f"implicit autostart default found in {mod.__name__}")

        # The gate must be consulted by the startup hook, and denial must return early.
        routes_src = inspect.getsource(routes)
        self.assertIn("autonomous_engine_autostart_allowed()", routes_src)
        self.assertIn("AUTONOMOUS_ENGINE_NOT_STARTED", routes_src)

        # AST proof: os.getenv on the autorun variable never carries a default.
        tree = ast.parse(inspect.getsource(runtime_guard))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "getenv":
                names = [a.id for a in node.args if isinstance(a, ast.Name)]
                if "AUTORUN_ENGINE_ENV" in names:
                    self.assertEqual(len(node.args), 1,
                                     "autorun getenv must have no default value")

    def test_STARTUP_HOOK_HAS_SINGLE_ENGINE_AUTOSTART_PATH(self):
        """Exactly one startup hook, and it starts the engine only behind the gate."""
        from src.api import routes
        src = inspect.getsource(routes)
        self.assertEqual(src.count('@app.on_event("startup")'), 1)
        # The only other quant_engine.start() is the explicit operator endpoint.
        self.assertEqual(src.count("quant_engine.start()"), 2,
                         "startup autostart + explicit /engine/start endpoint only")


class TestBrokerSyncIsReadOnly(unittest.TestCase):
    """The background snapshot worker must be incapable of mutating broker state."""

    def test_BACKGROUND_SYNC_CANNOT_SUBMIT_OR_CANCEL_ORDERS(self):
        sync_src = inspect.getsource(broker.__class__.start_background_sync)
        refresh_src = inspect.getsource(broker.__class__.refresh_broker_snapshot)
        combined = sync_src + refresh_src
        for banned in ("place_limit_order", "place_market_order", "place_stop_order",
                       "sync_broker_stop_order", "cancel_order", "cancel_stop_orders",
                       "route_entry_order", "route_exit_order",
                       "_run_core_compounding_cycle", '"POST"', '"DELETE"'):
            self.assertNotIn(banned, combined,
                             f"background sync must not be able to {banned}")

    def test_BACKGROUND_SYNC_ONLY_ISSUES_READS(self):
        """It refreshes via account summary + positions, both GET-only."""
        refresh_src = inspect.getsource(broker.__class__.refresh_broker_snapshot)
        self.assertIn("get_account_summary", refresh_src)
        self.assertIn("get_open_positions", refresh_src)
        pos_src = inspect.getsource(broker.__class__.get_open_positions)
        self.assertNotIn('_request_with_retry("POST"', pos_src)
        self.assertNotIn('_request_with_retry("DELETE"', pos_src)


class TestEntryLockHolds(unittest.TestCase):
    """PRACTICE_NEW_ENTRIES_ALLOWED=False blocks every autonomous entry submission."""

    def setUp(self):
        from src.portfolio.portfolio_snapshot import portfolio_snapshot
        from src.execution.order_state_machine import portfolio_reservations
        self.orig_practice = settings.PRACTICE_NEW_ENTRIES_ALLOWED
        self.orig_real = settings.REAL_MONEY_NEW_ENTRIES_ALLOWED
        self.orig_mode = settings.ACCOUNT_MODE
        settings.REAL_MONEY_NEW_ENTRIES_ALLOWED = False
        settings.ACCOUNT_MODE = "PRACTICE"

        self.engine = PRVQuantEngine()
        self.engine._stop_event.set()
        self.engine._executed_signals.clear()
        portfolio_reservations.reset()
        self._wipe()

        self.dates = pd.date_range("2024-01-01", "2026-09-04", freq="B")
        self.patch_account = patch.object(broker, "get_account_summary", return_value={
            "total": 500000.0, "free": 500000.0, "invested": 0.0, "ppl": 0.0, "result": 0.0})
        self.patch_snap = patch.object(portfolio_snapshot, "hydrate_once", return_value={
            "account_summary": {"free_cash": 500000.0, "total_nav": 500000.0}, "positions": []})
        self.patch_cancel = patch.object(broker, "cancel_stop_orders_for_ticker", return_value=[])
        self.patch_account.start(); self.patch_snap.start(); self.patch_cancel.start()

    def tearDown(self):
        from src.execution.order_state_machine import portfolio_reservations
        self.patch_account.stop(); self.patch_snap.stop(); self.patch_cancel.stop()
        self.engine.is_running = False
        portfolio_reservations.reset()
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_practice
        settings.REAL_MONEY_NEW_ENTRIES_ALLOWED = self.orig_real
        settings.ACCOUNT_MODE = self.orig_mode
        self._wipe()

    def _wipe(self):
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                cur.execute("DELETE FROM trades")
                conn.commit()
        except Exception:
            pass

    def _feed(self, top_symbol="EMIM", top_close=41.59):
        feed = {}
        for item in CORE.CERTIFIED_UNIVERSE:
            n = len(self.dates)
            if item["symbol"] == top_symbol:
                base = top_close * 100.0 if item.get("is_uk_pence", True) else top_close
                closes = np.linspace(base * 0.75, base, n)
            else:
                closes = np.linspace(1000.0, 900.0, n)
            feed[item["yf_ticker"]] = pd.DataFrame({
                "Open": closes * 0.999, "High": closes * 1.002, "Low": closes * 0.998,
                "Close": closes, "Volume": [100000] * n}, index=self.dates)
        return feed

    def _run_cycle(self, limit_mock):
        feed = self._feed()
        stack = [
            patch.object(market_data, "fetch_history",
                         side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())),
            patch.object(market_data, "get_current_executable_price", return_value=41.6900),
            patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),
            patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),
            patch.object(broker, "place_limit_order", limit_mock),
            patch.object(broker, "sync_broker_stop_order",
                         MagicMock(return_value={"success": True, "order_id": "S"})),
        ]
        for ctx in stack:
            ctx.start()
        try:
            return self.engine._run_core_compounding_cycle(
                account={"total_value": 500000.0, "available_cash": 500000.0},
                bypass_execution_window=True)
        finally:
            for ctx in reversed(stack):
                ctx.stop()

    def test_RUNNING_ENGINE_WITH_ENTRY_LOCK_CANNOT_SUBMIT_ORDER(self):
        """Engine RUNNING + valid signal + ample cash + free slots -> still no order."""
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        self.engine.is_running = True          # engine is live, as the dashboard shows
        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_LOCKED", "status": "FILLED", "fillPrice": 4169.00,
            "filledQuantity": 956.158}})
        res = self._run_cycle(limit)
        limit.assert_not_called()
        self.assertNotEqual(res.get("decision"), "ENTER")
        self.assertIn("PRACTICE_NEW_ENTRIES_ALLOWED", str(res.get("reason", "")))

    def test_ENTRY_LOCK_SURVIVES_RESTART(self):
        """A rebuilt engine re-reads the lock and still refuses to submit."""
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_LOCKED", "status": "FILLED", "fillPrice": 4169.00,
            "filledQuantity": 956.158}})
        self._run_cycle(limit)

        # Simulate a process restart.
        from src.execution.order_state_machine import portfolio_reservations
        self.engine._executed_signals.clear()
        portfolio_reservations.reset()
        self._wipe()
        self.engine = PRVQuantEngine()
        self.engine._stop_event.set()
        self.engine._executed_signals.clear()
        self.engine.is_running = True

        res = self._run_cycle(limit)
        limit.assert_not_called()
        self.assertNotEqual(res.get("decision"), "ENTER")

    def test_ENTRY_LOCK_IS_DEFENCE_IN_DEPTH(self):
        """The router refuses an entry on its own, without the engine's guard.

        route_entry_order is called directly here, so the engine-level check is
        bypassed entirely. The submission must still be refused, proving the lock does
        not depend on a single call site.
        """
        from src.execution.order_router import order_router
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        limit = MagicMock(return_value={"success": True, "data": {"id": "X"}})
        with patch.object(broker, "place_limit_order", limit):
            ok, _reason, _meta = order_router.route_entry_order(
                symbol="EMIM", t212_ticker="EMIMl_EQ", quantity=100.0, price=41.69,
                target_price=44.0, stop_loss_price=40.8562, sector="ETF",
                confidence_score=0.0, market_regime="CROSS_SECTIONAL_MOMENTUM",
                agent_votes={"CORE_COMPOUNDING": "BUY"}, risk_approved=True,
                is_paper=True, instrument_type="ETF", decision_price=41.59,
                bypass_market_hours=True,
                strategy_id="PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1")
        self.assertFalse(ok, "the router must refuse an entry while the lock is closed")
        limit.assert_not_called()

    def test_ENTRY_LOCK_IS_LOAD_BEARING(self):
        """Control: with the lock OPEN the same scenario does dispatch.

        This is the mutation control for the two tests above -- it proves they fail
        for the right reason rather than because the harness never reaches dispatch.
        """
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = True
        self.engine.is_running = True
        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_OPEN", "status": "FILLED", "fillPrice": 4169.00,
            "filledQuantity": 956.158}})
        self._run_cycle(limit)
        self.assertEqual(limit.call_count, 1,
                         "with the lock open the harness must reach order dispatch")


if __name__ == "__main__":
    unittest.main()
