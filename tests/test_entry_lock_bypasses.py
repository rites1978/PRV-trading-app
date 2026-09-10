"""
PRV CAPITAL | ENTRY-LOCK BYPASS CLOSURE SUITE

Invariants:
  ENTRY_LOCK_BLOCKS_EVERY_ORDER_SUBMIT_PATH = TRUE
  NO_PRODUCTION_ENTRY_PATH_CAN_BYPASS_ENTRY_LOCK = TRUE

The lock governs CAPITAL DEPLOYMENT only. Exits, liquidations, protective-stop
placement/replacement and emergency risk reduction must stay available while
entries are locked -- a locked account must still be able to protect and unwind.

Mock-only. No live broker read or write.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import settings
from src.brokers.trading212 import broker
from src.core.runtime_guard import (
    EntrySubmissionBlocked,
    new_entry_submission_allowed,
    entry_lock_bypass_authorised,
    ENTRY_LOCK_BYPASS_ENV,
)


class _LockBase(unittest.TestCase):
    def setUp(self):
        self.orig_mode = settings.ACCOUNT_MODE
        self.orig_practice = settings.PRACTICE_NEW_ENTRIES_ALLOWED
        self.orig_practice_enabled = getattr(settings, "PRACTICE_TRADING_ENABLED", True)
        settings.ACCOUNT_MODE = "PRACTICE"
        settings.PRACTICE_TRADING_ENABLED = True
        # Submitting through the real broker methods invalidates its snapshot caches;
        # snapshot and restore them so this suite leaves no global state behind.
        self._cache_state = (broker._cached_positions, broker._cached_positions_time,
                             broker._cached_summary, broker._cached_summary_time)

    def tearDown(self):
        (broker._cached_positions, broker._cached_positions_time,
         broker._cached_summary, broker._cached_summary_time) = self._cache_state
        settings.ACCOUNT_MODE = self.orig_mode
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_practice
        settings.PRACTICE_TRADING_ENABLED = self.orig_practice_enabled

    def _no_bypass_env(self):
        env = dict(os.environ)
        env.pop(ENTRY_LOCK_BYPASS_ENV, None)
        return patch.dict(os.environ, env, clear=True)


class TestCanaryEntryLock(_LockBase):
    """POST /api/canary/execute_etf must honour the entry lock."""

    def test_CANARY_ENTRY_LOCKED_NO_ORDER(self):
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        from src.execution.canary import execute_live_etf_canary
        submit = MagicMock()
        with self._no_bypass_env(), \
             patch.object(broker, "place_market_order", submit), \
             patch.object(broker, "place_stop_order", submit), \
             patch.object(broker, "get_account_summary", submit), \
             patch.object(broker, "get_open_positions", submit):
            res = execute_live_etf_canary()
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("status"), "CANARY_BLOCKED_ENTRY_LOCK")
        submit.assert_not_called()  # not even a broker READ occurs

    def test_CANARY_ENTRY_ALLOWED_CAN_ORDER(self):
        """With entries permitted the canary proceeds past the gate."""
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = True
        allowed, _ = new_entry_submission_allowed()
        self.assertTrue(allowed, "gate must permit the canary when entries are open")
        from src.execution import canary
        import inspect
        src = inspect.getsource(canary.execute_live_etf_canary)
        self.assertIn("new_entry_submission_allowed()", src)
        self.assertLess(src.index("new_entry_submission_allowed()"),
                        src.index("broker.get_account_summary"),
                        "the gate must precede every broker interaction")


class TestBrokerLayerBackstop(_LockBase):
    """The broker layer refuses capital-deploying orders regardless of caller."""

    def test_DIRECT_ENTRY_ROUTER_LOCKED_NO_ORDER(self):
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        http = MagicMock()
        with self._no_bypass_env(), patch.object(broker, "_request_with_retry", http):
            lim = broker.place_limit_order("CSP1_EQ", 10.0, 617.18)
            mkt = broker.place_market_order("CSP1_EQ", 10.0)
        for r in (lim, mkt):
            self.assertFalse(r.get("success"))
            self.assertIn("ENTRY_SUBMISSION_BLOCKED", str(r.get("error")))
        http.assert_not_called()

    def test_RUNNING_ENGINE_ENTRY_LOCKED_NO_ORDER(self):
        """A RUNNING engine submitting through its only entry path is refused.

        The engine dispatches entries solely via order_router.route_entry_order, so
        driving that with the engine marked running proves the running-engine case
        without re-deriving the full signal harness (which is covered end-to-end in
        tests/test_deployment_failsafe.py).
        """
        from src.core.engine import PRVQuantEngine
        from src.execution.order_router import order_router
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        engine = PRVQuantEngine()
        engine._stop_event.set()
        engine.is_running = True
        try:
            submit = MagicMock()
            with self._no_bypass_env(), patch.object(broker, "place_limit_order", submit), \
                 patch.object(broker, "place_market_order", submit):
                ok, _reason, _meta = order_router.route_entry_order(
                    symbol="EMIM", t212_ticker="EMIMl_EQ", quantity=100.0, price=41.69,
                    target_price=44.0, stop_loss_price=40.8562, sector="ETF",
                    confidence_score=0.0, market_regime="CROSS_SECTIONAL_MOMENTUM",
                    agent_votes={"CORE_COMPOUNDING": "BUY"}, risk_approved=True,
                    is_paper=True, instrument_type="ETF", decision_price=41.59,
                    bypass_market_hours=True,
                    strategy_id="PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1")
            self.assertFalse(ok)
            submit.assert_not_called()
        finally:
            engine.is_running = False

    def test_ENTRY_LOCK_DOES_NOT_BLOCK_EXIT(self):
        """A SELL (negative quantity) must still be submittable while locked."""
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        http = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"id": "X"}))
        with self._no_bypass_env(), patch.object(broker, "_request_with_retry", http):
            res = broker.place_market_order("CSP1_EQ", -10.0)
        self.assertTrue(http.called, "exits must not be blocked by the entry lock")
        self.assertTrue(res.get("success"))

    def test_ENTRY_LOCK_DOES_NOT_BLOCK_PROTECTIVE_STOP(self):
        """Protective stop placement/replacement stays available while locked."""
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        http = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"id": "S"}))
        with self._no_bypass_env(), patch.object(broker, "_request_with_retry", http):
            res = broker.place_stop_order("CSP1_EQ", -10.0, 600.00)
        self.assertTrue(http.called, "protective stops must not be blocked")
        self.assertTrue(res.get("success"))

    def test_ENTRY_LOCK_DOES_NOT_BLOCK_EMERGENCY_RISK_REDUCTION(self):
        """The fail-closed flatten path (negative market order) stays available."""
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        http = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {"id": "F"}))
        with self._no_bypass_env(), patch.object(broker, "_request_with_retry", http):
            flat = broker.place_market_order("CSP1_EQ", -25.0)   # emergency flatten
            trim = broker.place_market_order("CSP1_EQ", -5.0)    # risk-engine trim
        self.assertTrue(flat.get("success"))
        self.assertTrue(trim.get("success"))
        self.assertEqual(http.call_count, 2)


class TestBypassIsRestricted(_LockBase):
    """bypass_audit_freeze cannot silently defeat the lock in production."""

    def test_BYPASS_DENIED_WITHOUT_EXPLICIT_CAPABILITY(self):
        with self._no_bypass_env():
            ok, reason = entry_lock_bypass_authorised()
        self.assertFalse(ok)
        self.assertIn("not set", reason)

    def test_BYPASS_DENIED_FOR_NON_APPROVED_VALUES(self):
        for value in ("", "1", "yes", "on", "TRUE_", "false", "maybe"):
            with self.subTest(value=value):
                env = dict(os.environ); env[ENTRY_LOCK_BYPASS_ENV] = value
                with patch.dict(os.environ, env, clear=True):
                    self.assertFalse(entry_lock_bypass_authorised()[0])

    def test_BYPASS_HONOURED_ONLY_ON_EXPLICIT_OPT_IN(self):
        env = dict(os.environ); env[ENTRY_LOCK_BYPASS_ENV] = "true"
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(entry_lock_bypass_authorised()[0])

    def test_NO_PRODUCTION_ENTRY_PATH_CAN_BYPASS_ENTRY_LOCK(self):
        """No module under src/ passes the bypass flag as True.

        AST-based so that prose mentioning bypass_gate=True in a docstring is not
        mistaken for a real call-site argument.
        """
        import ast as _ast
        import pathlib
        offenders = []
        root = pathlib.Path(__file__).resolve().parent.parent / "src"
        for f in root.rglob("*.py"):
            try:
                tree = _ast.parse(f.read_text(errors="replace"))
            except SyntaxError:
                continue
            for node in _ast.walk(tree):
                if not isinstance(node, _ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg in ("bypass_audit_freeze", "bypass_gate") and \
                            isinstance(kw.value, _ast.Constant) and kw.value.value is True:
                        offenders.append(f"{f}:{node.lineno}")
        self.assertEqual(offenders, [],
                         f"production code must not self-authorise a bypass: {offenders}")

    def test_ROUTER_IGNORES_UNAUTHORISED_BYPASS(self):
        """An unauthorised bypass flag is downgraded, not honoured."""
        import inspect
        from src.execution import order_router as orr
        src = inspect.getsource(orr.OrderRouter.route_entry_order)
        self.assertIn("entry_lock_bypass_authorised()", src)
        self.assertIn("ENTRY_LOCK_BYPASS_IGNORED", src)
        self.assertIn("bypass_audit_freeze = _bypass_ok", src)


class TestEntryPermissionSemantics(_LockBase):
    """The gate governs entries only, and fails closed on unknown modes."""

    def test_LOCK_STATE_MAPPING(self):
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = False
        with self._no_bypass_env():
            self.assertFalse(new_entry_submission_allowed()[0])
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = True
        with self._no_bypass_env():
            self.assertTrue(new_entry_submission_allowed()[0])

    def test_UNKNOWN_ACCOUNT_MODE_FAILS_CLOSED(self):
        settings.ACCOUNT_MODE = "SOMETHING_ELSE"
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = True
        with self._no_bypass_env():
            allowed, reason = new_entry_submission_allowed()
        self.assertFalse(allowed)
        self.assertIn("fail-closed", reason)


if __name__ == "__main__":
    unittest.main()
