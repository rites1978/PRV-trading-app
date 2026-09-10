"""
PRV CAPITAL | F4 REGRESSION SUITE — CANONICAL PRICE-UNIT CONTRACT

Defect: seven Core stop sites read broker `averagePrice` (already broker-native,
GBX for most LSE lines) and then multiplied by 100, emitting a sell-stop ~100x above
market. For the live EMIM position that produced 406210 instead of 4062.10 GBX.

Contract: ONE internal unit (GBP). Broker-native normalised to GBP exactly once at
the adapter boundary; GBP converted to the broker payload unit exactly once at
submission. Unit resolution is metadata-driven, never magnitude-based.

Mock-only. No live broker read or write.
"""
import json
import os
import sys
import unittest

import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.price_units import (
    broker_price_to_gbp,
    gbp_to_broker_price,
    broker_price_unit,
    broker_stop_from_broker_entry,
    UnknownInstrumentUnitError,
)
from src.strategies.core_compounding_v1 import core_compounding_strategy as CORE
from src.core.engine import PRVQuantEngine
from src.brokers.trading212 import broker
from src.data.market_data import market_data
from src.database.db import db
from tests._provenance_mocks import provenance_aware, stale

STOP_PCT = CORE.STOP_LOSS_PCT          # frozen 0.02

# Broker-native reference prices, evidenced from repo data:
#   live broker position (EMIM) and data/historical_prices/*.csv scales.
NATIVE = {
    "CSP1": ("CSP1_EQ", 61718.0, "GBX"),
    "EQQQ": ("EQQQl_EQ", 53574.0, "GBX"),
    "ISF":  ("ISFl_EQ", 1061.0, "GBX"),
    "EMIM": ("EMIMl_EQ", 4145.0, "GBX"),
    "SGLN": ("SGLNl_EQ", 6519.0, "GBX"),
    "IGLT": ("IGLTl_EQ", 9.60, "GBP"),
}

BROKER_INSTRUMENTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "trading212_instruments.json")


def _broker_currency_map():
    """Authoritative broker instrument currencies (no network)."""
    out = {}
    with open(BROKER_INSTRUMENTS) as f:
        for r in json.load(f):
            out[str(r.get("ticker", ""))] = r.get("currencyCode")
    return out


class TestF4CanonicalPriceUnits(unittest.TestCase):

    # ---------------- EMIM: the live case ----------------

    def test_F4_EMIM_GBX_TO_GBP_ONCE(self):
        """4145 GBX normalises to exactly £41.45 — once, not twice."""
        gbp = broker_price_to_gbp(4145.0, "EMIMl_EQ")
        self.assertAlmostEqual(gbp, 41.45, places=6)
        self.assertNotAlmostEqual(gbp, 0.4145, places=6)   # double-divided
        self.assertNotAlmostEqual(gbp, 4145.0, places=6)   # not normalised

    def test_F4_EMIM_STOP_BACK_TO_GBX_ONCE(self):
        """£41.45 -> 2% stop £40.621 -> broker payload 4062.10 GBX."""
        gbp = broker_price_to_gbp(4145.0, "EMIMl_EQ")
        stop_gbp = round(gbp * (1.0 - STOP_PCT), 4)
        self.assertAlmostEqual(stop_gbp, 40.621, places=6)

        payload = gbp_to_broker_price(stop_gbp, "EMIMl_EQ")
        self.assertAlmostEqual(payload, 4062.10, places=2)
        self.assertNotAlmostEqual(payload, 40.621, places=3,
                                  msg="payload must not be left in GBP")
        self.assertNotEqual(payload, 406210.0, "payload must not be scaled twice")

        # And via the single-call helper the Core paths use:
        self.assertAlmostEqual(
            broker_stop_from_broker_entry(4145.0, "EMIMl_EQ", STOP_PCT), 4062.10, places=2)

    def test_F4_NO_DOUBLE_MULTIPLY_BY_100(self):
        """Applying the payload conversion to an already-native price is impossible
        through the contract: conversion consumes a GBP value exactly once."""
        for sym, (ticker, raw, _u) in NATIVE.items():
            with self.subTest(symbol=sym):
                payload = broker_stop_from_broker_entry(raw, ticker, STOP_PCT)
                expected = round(raw * (1.0 - STOP_PCT), 2) if broker_price_unit(ticker) == "GBX" \
                    else round(raw * (1.0 - STOP_PCT), 4)
                self.assertAlmostEqual(payload, expected, places=2)
                self.assertLess(payload, raw * 100.0,
                                f"{sym} payload shows a double x100")

    def test_F4_NO_DOUBLE_DIVIDE_BY_100(self):
        """Normalisation is idempotent per boundary crossing, never applied twice."""
        for sym, (ticker, raw, unit) in NATIVE.items():
            with self.subTest(symbol=sym):
                gbp = broker_price_to_gbp(raw, ticker)
                expected = raw / 100.0 if unit == "GBX" else raw
                self.assertAlmostEqual(gbp, expected, places=6)
                self.assertGreater(gbp, expected / 10.0,
                                   f"{sym} appears divided by 100 twice")

    # ---------------- per-instrument parity ----------------

    def _assert_parity(self, symbol):
        ticker, raw, unit = NATIVE[symbol]
        self.assertEqual(broker_price_unit(ticker), unit,
                         f"{symbol} broker unit must match authoritative metadata")
        gbp = broker_price_to_gbp(raw, ticker)
        expected_gbp = raw / 100.0 if unit == "GBX" else raw
        self.assertAlmostEqual(gbp, expected_gbp, places=6)
        payload = broker_stop_from_broker_entry(raw, ticker, STOP_PCT)
        expected_payload = round(expected_gbp * (1.0 - STOP_PCT) * (100.0 if unit == "GBX" else 1.0),
                                 2 if unit == "GBX" else 4)
        self.assertAlmostEqual(payload, expected_payload, places=2)

    def test_F4_CSP1_UNIT_PARITY(self):
        self._assert_parity("CSP1")

    def test_F4_EQQQ_UNIT_PARITY(self):
        self._assert_parity("EQQQ")

    def test_F4_ISF_UNIT_PARITY(self):
        self._assert_parity("ISF")

    def test_F4_SGLN_UNIT_PARITY(self):
        self._assert_parity("SGLN")

    def test_F4_IGLT_UNIT_SOURCE_CONSISTENT(self):
        """IGLT is GBP-quoted. All three metadata sources must agree with the broker."""
        cur = _broker_currency_map()
        self.assertEqual(cur.get("IGLTl_EQ"), "GBP",
                         "broker metadata is the authority: IGLT is GBP-quoted")

        core = CORE.get_instrument_metadata("IGLT")
        self.assertFalse(core.get("is_uk_pence"),
                         "certified universe must mark IGLT as non-pence")

        from src.data.universe import universe_manager
        um = universe_manager.get_by_t212_ticker("IGLTl_EQ")
        if um and "is_uk_pence" in um:
            self.assertFalse(um["is_uk_pence"], "universe_manager must agree with the broker")

        self.assertEqual(broker_price_unit("IGLTl_EQ"), "GBP")
        # A GBP-quoted price must never be scaled.
        self.assertAlmostEqual(broker_price_to_gbp(9.60, "IGLTl_EQ"), 9.60, places=6)
        self.assertAlmostEqual(broker_stop_from_broker_entry(9.60, "IGLTl_EQ", STOP_PCT),
                               round(9.60 * 0.98, 4), places=4)

    def test_F4_ALL_SEVEN_MATCH_BROKER_METADATA(self):
        """Every certified instrument's pence flag must match broker currencyCode."""
        cur = _broker_currency_map()
        for inst in CORE.CERTIFIED_UNIVERSE:
            t212 = inst["t212_ticker"]
            with self.subTest(instrument=t212):
                broker_ccy = cur.get(t212)
                self.assertIsNotNone(broker_ccy, f"{t212} missing from broker metadata")
                self.assertEqual(bool(inst["is_uk_pence"]), broker_ccy == "GBX",
                                 f"{t212}: metadata says pence={inst['is_uk_pence']} "
                                 f"but broker says {broker_ccy}")

    # ---------------- IWDA stays blocked ----------------

    def test_F4_IWDA_REMAINS_BLOCKED(self):
        """F4 must not unblock IWDA, and the evidence for blocking must remain."""
        import inspect
        from src.execution import order_router as orr
        from src.core import engine as eng
        self.assertIn("IWDA_UNIT_MISMATCH_BLOCKED", inspect.getsource(orr))
        self.assertIn("IWDA is blocked from execution pending unit-normalisation remediation",
                      inspect.getsource(orr))
        self.assertIn("IWDA is blocked from execution pending unit-normalisation remediation",
                      inspect.getsource(eng))

        # Documented mismatch: research used IWDA.L, production maps to SWDAl_EQ.
        cur = _broker_currency_map()
        self.assertEqual(cur.get("IWDAl_EQ"), "USD",
                         "IWDAl_EQ is a USD line - not the production instrument")
        self.assertEqual(cur.get("SWDAl_EQ"), "GBX",
                         "production maps IWDA -> SWDAl_EQ which is GBX")
        self.assertNotEqual(cur.get("IWDAl_EQ"), cur.get("SWDAl_EQ"),
                            "research and production instruments differ in currency")

        # No SWDA research series exists at all.
        hist = os.path.join(os.path.dirname(BROKER_INSTRUMENTS), "historical_prices")
        if os.path.isdir(hist):
            self.assertFalse(os.path.exists(os.path.join(hist, "SWDA_L.csv")),
                             "no validated SWDA research series exists; block must stand")

    # ---------------- boundary behaviour ----------------

    def test_F4_BROKER_FILL_PRICE_NORMALISED(self):
        """The fill price feeding the entry stop is canonical GBP, resolved fail-closed.

        Trading212's live order payload contains NO `fillPrice` field, verified against
        the real filled EMIM order, so `price` (already GBP) is what is normally used.
        Should the broker ever return one it is BROKER-NATIVE -- sibling fields on that
        same payload are GBX -- so it is normalised through instrument metadata exactly
        once. If the unit cannot be resolved the broker value is REFUSED, not guessed.
        """
        import inspect
        from src.execution import order_router as orr
        src = inspect.getsource(orr)

        # Evidence: the real broker order payload has no fillPrice key.
        with open(os.path.join(os.path.dirname(BROKER_INSTRUMENTS),
                               "trading212_raw_orders.json")) as fh:
            raw = json.load(fh)
        emim = [x for x in raw if "EMIM" in str(x.get("order", {}).get("ticker", ""))]
        self.assertTrue(emim, "expected a real EMIM order in the broker ledger")
        self.assertNotIn("fillPrice", emim[0]["order"],
                         "live payload has no fillPrice; do not assume its unit")
        self.assertIn("limitPrice", emim[0]["order"])
        self.assertGreater(emim[0]["order"]["limitPrice"], 1000.0,
                           "sibling price fields on the order payload are GBX-scaled")

        # The raw broker value must never be consumed unnormalised any more.
        self.assertNotIn('float(broker_order_data.get("fillPrice") or price)', src,
                         "raw broker fillPrice must not be used without unit resolution")
        # It is normalised exactly once, from ticker/instrument metadata.
        self.assertIn("broker_price_to_gbp(float(raw_fill_price), t212_ticker)", src,
                      "broker fillPrice must be normalised via instrument metadata")
        # And the unresolved case fails closed rather than guessing.
        self.assertIn("except UnknownInstrumentUnitError", src,
                      "an unresolvable quote unit must be handled, not assumed")
        self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION", src,
                      "a present-but-unresolvable fillPrice must fail closed to reconciliation")

        # The stop still derives from a GBP fill price, exactly once converted.
        self.assertIn("actual_stop_price = round(fill_price * (1.0 - stop_pct), 4)", src)
        self.assertAlmostEqual(broker_price_to_gbp(4145.0, "EMIMl_EQ"), 41.45, places=6)

    def test_F4_FILL_PRICE_NORMALISATION_IS_FAIL_CLOSED(self):
        """A broker-native fillPrice normalises once; an unresolvable one refuses."""
        # GBX-quoted line: broker-native 4145.0 must become £41.45, never £4145.
        self.assertAlmostEqual(broker_price_to_gbp(4145.0, "EMIMl_EQ"), 41.45, places=6)
        # GBP-quoted line: must pass through untouched, never divided by 100.
        self.assertAlmostEqual(broker_price_to_gbp(9.60, "IGLTl_EQ"), 9.60, places=6)
        # Unresolvable instrument: refuse rather than guess a unit.
        with self.assertRaises(UnknownInstrumentUnitError):
            broker_price_to_gbp(4145.0, "TOTALLY_UNKNOWN_EQ")

    def test_F4_UNKNOWN_INSTRUMENT_FAILS_CLOSED(self):
        """Unresolvable units raise instead of guessing."""
        for bad in ["TOTALLY_UNKNOWN_EQ", "", None]:
            with self.subTest(instrument=bad):
                with self.assertRaises(UnknownInstrumentUnitError):
                    broker_price_unit(bad)

    def test_F4_NO_MAGNITUDE_HEURISTIC_IN_CONTRACT(self):
        """The canonical module must not infer units from a price's size."""
        import ast, inspect
        from src.core import price_units
        tree = ast.parse(inspect.getsource(price_units))

        # Strip every docstring so the assertion tests executable code, not prose.
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    # Keep the block syntactically valid if the docstring was its only statement.
                    node.body = body[1:] or [ast.Pass()]
        code = ast.unparse(tree)

        # No numeric comparison may drive a unit decision.
        for cmp_node in [n for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Compare)]:
            for op, comparator in zip(cmp_node.ops, cmp_node.comparators):
                if isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)) and \
                        isinstance(comparator, ast.Constant) and \
                        isinstance(comparator.value, (int, float)):
                    self.fail(f"magnitude heuristic found in contract: compares against "
                              f"{comparator.value}")
        for banned in ["> 50", "> 100.0", "> 500"]:
            self.assertNotIn(banned, code,
                             f"magnitude heuristic '{banned}' must not exist in the contract")

    # ---------------- fillPrice unit contract (F4) ----------------

    def test_F4_FILLPRICE_GBX_NORMALISES_FROM_TICKER_METADATA(self):
        """A GBX broker fill normalises to GBP from ticker metadata, once."""
        self.assertEqual(broker_price_unit("EMIMl_EQ"), "GBX")
        fill_gbp = broker_price_to_gbp(4169.0, "EMIMl_EQ")
        self.assertAlmostEqual(fill_gbp, 41.69, places=6)
        # Frozen 2% rule in canonical GBP, then one payload conversion.
        stop_gbp = round(fill_gbp * (1.0 - STOP_PCT), 4)
        self.assertAlmostEqual(stop_gbp, 40.8562, places=4)
        self.assertAlmostEqual(gbp_to_broker_price(stop_gbp, "EMIMl_EQ"), 4085.62, places=2)

    def test_F4_FILLPRICE_GBP_REMAINS_MAJOR_UNIT(self):
        """A GBP-quoted line's fill must pass through untouched, never divided."""
        self.assertEqual(broker_price_unit("IGLTl_EQ"), "GBP")
        self.assertAlmostEqual(broker_price_to_gbp(9.60, "IGLTl_EQ"), 9.60, places=6)
        self.assertAlmostEqual(gbp_to_broker_price(9.60, "IGLTl_EQ"), 9.60, places=4)

    def test_F4_FILLPRICE_ORDER_CURRENCY_GBP_DOES_NOT_OVERRIDE_GBX_QUOTE(self):
        """order['currency'] is the SETTLEMENT currency and must not set the quote unit."""
        with open(os.path.join(os.path.dirname(BROKER_INSTRUMENTS),
                               "trading212_raw_orders.json")) as fh:
            raw = json.load(fh)
        emim = [x for x in raw if "EMIM" in str(x.get("order", {}).get("ticker", ""))]
        self.assertTrue(emim, "expected a real EMIM order in the broker ledger")
        order = emim[0]["order"]
        # The real payload literally says currency=GBP while quoting in GBX.
        self.assertEqual(order.get("currency"), "GBP")
        self.assertGreater(order.get("limitPrice"), 1000.0)
        # Metadata, not the order envelope, decides the unit.
        self.assertEqual(broker_price_unit("EMIMl_EQ"), "GBX")
        self.assertAlmostEqual(broker_price_to_gbp(4169.0, "EMIMl_EQ"), 41.69, places=6)

    def test_F4_FILLPRICE_UNKNOWN_TICKER_FAILS_CLOSED(self):
        """An unresolvable ticker refuses rather than guessing a unit."""
        for bad in ["TOTALLY_UNKNOWN_EQ", "", None]:
            with self.subTest(instrument=bad):
                with self.assertRaises(UnknownInstrumentUnitError):
                    broker_price_to_gbp(4169.0, bad)
        import inspect
        from src.execution import order_router as orr
        src = inspect.getsource(orr)
        self.assertIn("except UnknownInstrumentUnitError", src)
        self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION", src)

    def test_F4_FILLPRICE_ABSENT_USES_EXPLICIT_GBP_FALLBACK(self):
        """Trading212 sends no fillPrice; the fallback is the explicit GBP arrival price."""
        with open(os.path.join(os.path.dirname(BROKER_INSTRUMENTS),
                               "trading212_raw_orders.json")) as fh:
            raw = json.load(fh)
        emim = [x for x in raw if "EMIM" in str(x.get("order", {}).get("ticker", ""))]
        self.assertNotIn("fillPrice", emim[0]["order"])
        import inspect
        from src.execution import order_router as orr
        src = inspect.getsource(orr)
        self.assertIn("GBP_ARRIVAL_PRICE_NO_BROKER_FILLPRICE", src)
        self.assertIn("fill_price = price", src,
                      "absent fillPrice must fall back to the canonical GBP arrival price")
        # The absent case and the unresolvable case must not share a branch.
        self.assertIn("CASE A", src)
        self.assertIn("CASE B", src)

    def test_F4_FILLPRICE_CANNOT_DOUBLE_NORMALISE(self):
        """Normalisation is applied exactly once on the router's fill path."""
        once = broker_price_to_gbp(4169.0, "EMIMl_EQ")
        self.assertAlmostEqual(once, 41.69, places=6)
        # Applying it twice is the hazard being guarded against.
        twice = broker_price_to_gbp(once, "EMIMl_EQ")
        self.assertAlmostEqual(twice, 0.4169, places=6)
        self.assertNotAlmostEqual(twice, 41.69, places=2)
        import inspect
        from src.execution import order_router as orr
        src = inspect.getsource(orr)
        self.assertEqual(src.count("broker_price_to_gbp("), 1,
                         "exactly one call site; a fill is never normalised twice")

    def test_F4_FILLPRICE_CANNOT_DOUBLE_MULTIPLY_100(self):
        """The GBP -> GBX payload conversion happens exactly once at submission."""
        stop_gbp = round(broker_price_to_gbp(4169.0, "EMIMl_EQ") * (1.0 - STOP_PCT), 4)
        payload = gbp_to_broker_price(stop_gbp, "EMIMl_EQ")
        self.assertAlmostEqual(payload, 4085.62, places=2)
        self.assertNotAlmostEqual(payload, 408562.0, places=2)
        self.assertLess(payload, 10000.0, "EMIM stop payload must stay in GBX scale")
        import inspect
        from src.execution import order_router as orr
        src = inspect.getsource(orr)
        self.assertEqual(src.count("round(actual_stop_price * 100.0, 2)"), 1,
                         "stop payload is scaled to GBX exactly once")

    # ---------------- engine paths emit canonical payloads ----------------

    def _run_window_close_capture(self, ticker, raw_avg):
        """Drive the window-close path and capture the broker stop payload."""
        captured = []
        working = [{"id": "ORD_F4", "ticker": ticker, "type": "LIMIT", "quantity": 100.0}]
        filled = [{"ticker": ticker, "quantity": 100.0,
                   "averagePrice": raw_avg, "currentPrice": raw_avg}]
        from datetime import datetime
        from zoneinfo import ZoneInfo
        t_past = datetime(2026, 9, 7, 8, 30, 0, tzinfo=ZoneInfo("Europe/London"))

        engine = PRVQuantEngine()
        with patch.object(broker, "get_open_orders", side_effect=provenance_aware(working)), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(filled)), \
             patch.object(broker, "cancel_order", return_value={"success": True}), \
             patch.object(broker, "reconcile_orphan_stops", return_value=[]), \
             patch.object(broker, "sync_broker_stop_order",
                          side_effect=lambda t, q, p, **k: captured.append(p) or {"success": True}), \
             patch.object(market_data, "get_market_snapshot",
                          return_value={"success": True, "indicators": {"atr": 0.2},
                                        "recent_returns": []}), \
             patch.object(db, "get_latest_core_compounding_decision", return_value=None), \
             patch.object(db, "update_core_compounding_decision_status", return_value=None):
            engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                current_time=t_past)
        return captured

    def test_F4_WINDOW_CLOSE_STOP_USES_CANONICAL_PRICE(self):
        """Window-close stop sync must submit 4062.10 GBX for EMIM, never 406210."""
        captured = self._run_window_close_capture("EMIMl_EQ", 4145.0)
        self.assertTrue(captured, "window-close path did not synchronise a stop")
        for payload in captured:
            self.assertAlmostEqual(payload, 4062.10, places=2)
            self.assertNotEqual(payload, 406210.0)

    def test_F4_ENGINE_RECONCILIATION_STOP_USES_CANONICAL_PRICE(self):
        """Every engine stop site derives its payload from the canonical helper."""
        import inspect
        from src.core import engine as eng
        src = inspect.getsource(eng)
        self.assertNotIn("round(stop_price * 100.0, 2)", src,
                         "no engine path may multiply an already-native price by 100")
        self.assertGreaterEqual(src.count("broker_stop_from_broker_entry"), 7,
                                "all seven Core stop sites must use the canonical helper")

    def test_F4_ORDER_ROUTER_STOP_USES_CANONICAL_PRICE(self):
        """order_router's entry stop already works in GBP; assert it stays that way."""
        import inspect
        from src.execution import order_router as orr
        src = inspect.getsource(orr)
        self.assertIn("actual_stop_price = round(fill_price * (1.0 - stop_pct), 4)", src,
                      "entry stop must be computed from a GBP fill price")
        self.assertIn("broker_stop_price = round(actual_stop_price * 100.0, 2)", src,
                      "GBP -> GBX payload conversion happens exactly once at submission")
        # End-to-end contract equivalence for EMIM.
        fill_gbp = broker_price_to_gbp(4145.0, "EMIMl_EQ")
        self.assertAlmostEqual(round(round(fill_gbp * (1.0 - STOP_PCT), 4) * 100.0, 2),
                               4062.10, places=2)

    # ---------------- invariants ----------------

    def test_INVARIANT_NO_CORE_PATH_CAN_EMIT_406210_FOR_EMIM(self):
        payload = broker_stop_from_broker_entry(4145.00000527, "EMIMl_EQ", STOP_PCT)
        self.assertAlmostEqual(payload, 4062.10, places=2)
        self.assertNotEqual(payload, 406210.0)
        self.assertLess(payload, 10000.0, "EMIM stop payload must stay in GBX scale")

    def test_INVARIANT_ONE_INTERNAL_PRICE_UNIT(self):
        """Round trip is lossless: native -> GBP -> native."""
        for sym, (ticker, raw, _u) in NATIVE.items():
            with self.subTest(symbol=sym):
                back = gbp_to_broker_price(broker_price_to_gbp(raw, ticker), ticker)
                self.assertAlmostEqual(back, raw, places=2)


if __name__ == "__main__":
    unittest.main()


class TestF4FillPriceContract(unittest.TestCase):
    """End-to-end fillPrice unit contract through the real entry path.

    CASE A (fillPrice absent) is the live Trading212 behaviour and must keep using the
    explicitly-known-GBP arrival price. CASE B (fillPrice present) must be normalised
    from instrument metadata, and when that unit cannot be resolved the router must
    refuse to recognise a fill price at all rather than substitute a different one.
    """

    def setUp(self):
        from src.config.settings import settings
        from src.portfolio.portfolio_snapshot import portfolio_snapshot
        from src.execution.order_state_machine import portfolio_reservations

        self.settings = settings
        self.orig_practice = settings.PRACTICE_NEW_ENTRIES_ALLOWED
        self.orig_real = settings.REAL_MONEY_NEW_ENTRIES_ALLOWED
        self.orig_mode = settings.ACCOUNT_MODE
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = True
        settings.REAL_MONEY_NEW_ENTRIES_ALLOWED = False
        settings.ACCOUNT_MODE = "PRACTICE"

        self.engine = PRVQuantEngine()
        self.engine._stop_event.set()
        self.engine.is_running = False
        self.engine._executed_signals.clear()
        portfolio_reservations.reset()

        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                cur.execute("DELETE FROM trades")
                conn.commit()
        except Exception:
            pass

        self.dates = pd.date_range("2024-01-01", "2026-09-04", freq="B")
        self.dates_next = pd.date_range("2024-01-01", "2026-09-07", freq="B")
        self.patch_account = patch.object(broker, "get_account_summary", return_value={
            "total": 49896.38, "free": 49896.38, "invested": 0.0, "ppl": 0.0, "result": 0.0})
        self.patch_snap = patch.object(portfolio_snapshot, "hydrate_once", return_value={
            "account_summary": {"free_cash": 49896.38, "total_nav": 49896.38}, "positions": []})
        self.patch_cancel = patch.object(broker, "cancel_stop_orders_for_ticker",
                                         return_value=["STOP_MOCK_1"])
        self.patch_account.start(); self.patch_snap.start(); self.patch_cancel.start()

    def tearDown(self):
        from src.execution.order_state_machine import portfolio_reservations
        self.patch_account.stop(); self.patch_snap.stop(); self.patch_cancel.stop()
        portfolio_reservations.reset()
        self.settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_practice
        self.settings.REAL_MONEY_NEW_ENTRIES_ALLOWED = self.orig_real
        self.settings.ACCOUNT_MODE = self.orig_mode
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                cur.execute("DELETE FROM trades")
                conn.commit()
        except Exception:
            pass

    def _feed(self, top_symbol="EMIM", top_close=41.59, dates=None):
        dates = self.dates if dates is None else dates
        feed = {}
        for item in CORE.CERTIFIED_UNIVERSE:
            sym, yf_t = item["symbol"], item["yf_ticker"]
            n = len(dates)
            if sym == top_symbol:
                base = top_close * 100.0 if item.get("is_uk_pence", True) else top_close
                closes = np.linspace(base * 0.75, base, n)
            else:
                closes = np.linspace(1000.0, 900.0, n)
            feed[yf_t] = pd.DataFrame({
                "Open": closes * 0.999, "High": closes * 1.002,
                "Low": closes * 0.998, "Close": closes,
                "Volume": [100000] * n}, index=dates)
        return feed

    def _run_entry(self, broker_data, live_price=41.6900, top_symbol="EMIM",
                   top_close=41.59, break_units=False):
        """Drive one entry cycle; return (result, stop_mock)."""
        feed = self._feed(top_symbol, top_close)
        mock_limit = MagicMock(return_value={"success": True, "data": broker_data})
        mock_stop = MagicMock(return_value={"success": True, "order_id": "STOP_F4"})

        stack = [
            patch.object(market_data, "fetch_history",
                         side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())),
            patch.object(market_data, "get_current_executable_price", return_value=live_price),
            patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),
            patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),
            patch.object(broker, "place_limit_order", mock_limit),
            patch.object(broker, "sync_broker_stop_order", mock_stop),
        ]
        if break_units:
            # Simulate an instrument whose quote unit cannot be resolved at the boundary.
            import src.execution.order_router as orr_mod
            stack.append(patch.object(
                orr_mod, "broker_price_to_gbp",
                side_effect=UnknownInstrumentUnitError("PRICE_UNIT_UNRESOLVED: forced")))
        for ctx in stack:
            ctx.start()
        try:
            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True)
        finally:
            for ctx in reversed(stack):
                ctx.stop()
        return res, mock_stop

    def _cycle(self, limit_mock, stop_mock, dates=None, top_symbol="EMIM",
               top_close=41.59, live_price=41.6900, break_units=False, account=None,
               positions=None, orders=None, fresh=True):
        """One entry cycle reusing caller-owned mocks so call counts accumulate."""
        feed = self._feed(top_symbol, top_close, dates)
        stack = [
            patch.object(market_data, "fetch_history",
                         side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())),
            patch.object(market_data, "get_current_executable_price", return_value=live_price),
            patch.object(broker, "get_open_positions",
                         side_effect=provenance_aware(positions or [], fresh)),
            patch.object(broker, "get_open_orders",
                         side_effect=provenance_aware(orders or [], fresh)),
            patch.object(broker, "place_limit_order", limit_mock),
            patch.object(broker, "sync_broker_stop_order", stop_mock),
        ]
        if break_units:
            import src.execution.order_router as orr_mod
            stack.append(patch.object(
                orr_mod, "broker_price_to_gbp",
                side_effect=UnknownInstrumentUnitError("PRICE_UNIT_UNRESOLVED: forced")))
        for ctx in stack:
            ctx.start()
        try:
            return self.engine._run_core_compounding_cycle(
                account=account or {"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True)
        finally:
            for ctx in reversed(stack):
                ctx.stop()

    def _ambiguous_then_new_signal(self, status="FILLED", filled_qty=956.158,
                                   second_top="SGLN"):
        """Create an ambiguous possibly-filled order, then present a NEW signal.

        The retry uses a later bar (new dedup key) and, by default, a DIFFERENT
        instrument, so neither per-bar dedup nor same-order idempotency alone can
        account for the block.
        """
        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_AMBIG", "status": status, "fillPrice": 4169.00,
            "filledQuantity": filled_qty}})
        stop = MagicMock(return_value={"success": True, "order_id": "STOP_F4"})
        first = self._cycle(limit, stop, break_units=True)
        dispatched_after_first = limit.call_count
        second = self._cycle(limit, stop, dates=self.dates_next, top_symbol=second_top)
        return first, second, limit, stop, dispatched_after_first

    # ---- ambiguous fill must block all further capital deployment ----

    def test_F4_UNRESOLVED_FILL_BLOCKS_NEW_ENTRIES(self):
        """A possibly-FILLED ambiguous order blocks any subsequent new entry."""
        first, second, limit, _stop, after_first = self._ambiguous_then_new_signal("FILLED")
        self.assertIn("PRICE_UNIT_UNRESOLVED", str(first.get("reason")))
        self.assertEqual(after_first, 1, "the ambiguous order itself was dispatched once")
        self.assertNotEqual(second.get("decision"), "ENTER")
        # The invariant: entry dispatch count for the subsequent signal is 0.
        self.assertEqual(limit.call_count - after_first, 0,
                         "no new capital may be deployed while a fill is unreconciled")

    def test_F4_UNRESOLVED_PARTIAL_FILL_BLOCKS_NEW_ENTRIES(self):
        """A possibly-PARTIALLY_FILLED ambiguous order blocks subsequent new entries."""
        first, second, limit, _stop, after_first = self._ambiguous_then_new_signal(
            "PARTIALLY_FILLED", filled_qty=400.0)
        self.assertIn("PRICE_UNIT_UNRESOLVED", str(first.get("reason")))
        self.assertNotEqual(second.get("decision"), "ENTER")
        self.assertEqual(limit.call_count - after_first, 0,
                         "a partial ambiguous fill must not permit further deployment")

    def test_F4_UNRESOLVED_FILL_RESERVATION_NOT_RELEASED(self):
        """Capital stays reserved: the position may genuinely exist at the broker."""
        from src.execution.order_state_machine import portfolio_reservations
        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_AMBIG", "status": "FILLED", "fillPrice": 4169.00,
            "filledQuantity": 956.158}})
        stop = MagicMock(return_value={"success": True, "order_id": "STOP_F4"})
        self._cycle(limit, stop, break_units=True)
        self.assertGreater(portfolio_reservations.get_total_reserved_cash(), 0.0,
                           "an unreconciled possibly-filled order must keep its reservation")

    def test_F4_UNRESOLVED_FILL_CANNOT_BE_RECORDED_REJECTED(self):
        """The decision is recorded as pending reconciliation, never as rejected."""
        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_AMBIG", "status": "FILLED", "fillPrice": 4169.00,
            "filledQuantity": 956.158}})
        stop = MagicMock(return_value={"success": True, "order_id": "STOP_F4"})
        self._cycle(limit, stop, break_units=True)
        dec = db.get_latest_core_compounding_decision()
        self.assertIsNotNone(dec, "the ambiguous order must leave a decision record")
        status = str(dec.get("execution_status", ""))
        self.assertEqual(status, "PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION")
        self.assertNotIn("REJECT", status.upper(),
                         "a possibly-filled order must never be recorded as rejected")

    def test_F4_UNRESOLVED_FILL_CANNOT_PRODUCE_TERMINAL_SUCCESS(self):
        """No terminal success: no ENTER, no stop, no filled/closed status."""
        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_AMBIG", "status": "FILLED", "fillPrice": 4169.00,
            "filledQuantity": 956.158}})
        stop = MagicMock(return_value={"success": True, "order_id": "STOP_F4"})
        res = self._cycle(limit, stop, break_units=True)
        self.assertNotEqual(res.get("decision"), "ENTER")
        stop.assert_not_called()
        dec = db.get_latest_core_compounding_decision()
        terminal_success = {"FILLED", "PARTIALLY_FILLED", "CLOSED", "COMPLETED",
                            "PARTIALLY_FILLED_WINDOW_CLOSED"}
        self.assertNotIn(str(dec.get("execution_status", "")), terminal_success)

    def test_INVARIANT_AMBIGUOUS_POSSIBLY_FILLED_NEVER_ALLOWS_NEW_CAPITAL(self):
        """Neither a full nor a partial ambiguous fill may release new capital."""
        for status, qty in (("FILLED", 956.158), ("PARTIALLY_FILLED", 400.0)):
            with self.subTest(broker_status=status):
                self.engine._executed_signals.clear()
                from src.execution.order_state_machine import portfolio_reservations
                portfolio_reservations.reset()
                _f, second, limit, _s, after_first = self._ambiguous_then_new_signal(status, qty)
                self.assertEqual(limit.call_count - after_first, 0)
                self.assertNotEqual(second.get("decision"), "ENTER")

    def _ambiguous_then_unconstrained_retry(self, status="FILLED", filled_qty=956.158,
                                            second_top="SGLN"):
        """Leave an ambiguous possibly-filled order, then retry with EVERY incidental
        constraint removed.

        The retry runs with:
          * a reset reservation ledger (no held cash from the first order),
          * £500,000 synthetic cash and NAV (ample for another full-sized order),
          * a reservation subsystem stubbed to approve everything, which simultaneously
            disables the MAX_POSITIONS limit, the cash floor and symbol idempotency,
          * a DIFFERENT instrument, and
          * a DIFFERENT bar (a distinct dedup key).

        Anything that still blocks the entry can therefore only be the explicit
        pending-unresolved-fill gate.
        """
        from src.execution.order_state_machine import portfolio_reservations
        from src.portfolio.portfolio_snapshot import portfolio_snapshot

        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_AMBIG", "status": status, "fillPrice": 4169.00,
            "filledQuantity": filled_qty}})
        stop = MagicMock(return_value={"success": True, "order_id": "STOP_F4"})

        first = self._cycle(limit, stop, break_units=True)
        after_first = limit.call_count

        # The ambiguous state must actually be persisted, or the retry proves nothing.
        dec = db.get_unresolved_fill_price_decision()
        self.assertIsNotNone(dec, "expected a persisted unresolved-fill decision")

        portfolio_reservations.reset()
        big = {"total": 500000.0, "free": 500000.0, "invested": 0.0, "ppl": 0.0, "result": 0.0}
        relax = [
            patch.object(broker, "get_account_summary", return_value=big),
            patch.object(portfolio_snapshot, "hydrate_once", return_value={
                "account_summary": {"free_cash": 500000.0, "total_nav": 500000.0},
                "positions": []}),
            patch.object(portfolio_reservations, "reserve", return_value=(True, "")),
        ]
        for ctx in relax:
            ctx.start()
        try:
            second = self._cycle(
                limit, stop, dates=self.dates_next, top_symbol=second_top,
                account={"total_value": 500000.0, "available_cash": 500000.0})
        finally:
            for ctx in reversed(relax):
                ctx.stop()
        return first, second, limit, stop, after_first

    # ---- explicit global entry gate on an unresolved possibly-filled order ----

    def test_F4_UNRESOLVED_FILL_IS_EXPLICIT_GLOBAL_ENTRY_GATE(self):
        """Blocked by the explicit gate, with every incidental constraint removed."""
        _f, second, limit, _s, after_first = self._ambiguous_then_unconstrained_retry("FILLED")
        self.assertEqual(limit.call_count - after_first, 0,
                         "no entry may be dispatched while a fill is unreconciled")
        self.assertNotEqual(second.get("decision"), "ENTER")
        reason = str(second.get("reason", ""))
        self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION", reason,
                      "the block must be the explicit gate, not an incidental refusal")

    def test_F4_UNRESOLVED_PARTIAL_FILL_IS_EXPLICIT_GLOBAL_ENTRY_GATE(self):
        """Same, for a possibly PARTIALLY_FILLED ambiguous order."""
        _f, second, limit, _s, after_first = self._ambiguous_then_unconstrained_retry(
            "PARTIALLY_FILLED", filled_qty=400.0)
        self.assertEqual(limit.call_count - after_first, 0)
        self.assertNotEqual(second.get("decision"), "ENTER")
        self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION",
                      str(second.get("reason", "")))

    def test_F4_BLOCK_DOES_NOT_DEPEND_ON_MAX_POSITIONS(self):
        """The refusal is not the Core MAX_POSITIONS=1 limit."""
        _f, second, _l, _s, _a = self._ambiguous_then_unconstrained_retry("FILLED")
        reason = str(second.get("reason", ""))
        self.assertNotIn("Max positions", reason)
        self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION", reason)

    def test_F4_BLOCK_DOES_NOT_DEPEND_ON_CASH_RESERVATION(self):
        """The refusal is not a cash floor or a held reservation."""
        from src.execution.order_state_machine import portfolio_reservations
        _f, second, _l, _s, _a = self._ambiguous_then_unconstrained_retry("FILLED")
        reason = str(second.get("reason", ""))
        for token in ("Insufficient cash", "HOLD_CASH", "RESERVATION"):
            self.assertNotIn(token, reason)
        self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION", reason)

    def test_F4_BLOCK_DOES_NOT_DEPEND_ON_IDEMPOTENCY(self):
        """The refusal survives a DIFFERENT instrument on a DIFFERENT bar."""
        _f, second, limit, _s, after_first = self._ambiguous_then_unconstrained_retry(
            "FILLED", second_top="SGLN")
        reason = str(second.get("reason", ""))
        self.assertNotIn("IDEMPOTENCY", reason.upper())
        self.assertEqual(limit.call_count - after_first, 0)
        self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION", reason)

    def test_INVARIANT_PENDING_UNRESOLVED_FILL_GATES_ALL_NEW_CAPITAL(self):
        """Across fill states and instruments, no new capital may ever be deployed."""
        for status, qty, top in (("FILLED", 956.158, "SGLN"),
                                 ("PARTIALLY_FILLED", 400.0, "ISF"),
                                 ("FILLED", 956.158, "CSP1")):
            with self.subTest(broker_status=status, retry_instrument=top):
                self.engine._executed_signals.clear()
                self._reset_decisions()
                _f, second, limit, _s, after_first = \
                    self._ambiguous_then_unconstrained_retry(status, qty, second_top=top)
                self.assertEqual(limit.call_count - after_first, 0)
                self.assertNotEqual(second.get("decision"), "ENTER")
                self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION",
                              str(second.get("reason", "")))

    def _reset_decisions(self):
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                cur.execute("DELETE FROM trades")
                conn.commit()
        except Exception:
            pass

    def _arm_unresolved(self):
        """Create a persisted ambiguous unresolved-fill state and assert it is armed."""
        limit = MagicMock(return_value={"success": True, "data": {
            "id": "ORD_AMBIG", "status": "FILLED", "fillPrice": 4169.00,
            "filledQuantity": 956.158}})
        stop = MagicMock(return_value={"success": True, "order_id": "STOP_F4"})
        self._cycle(limit, stop, break_units=True)
        self.assertIsNotNone(db.get_unresolved_fill_price_decision(),
                             "the unresolved-fill gate must be armed")
        return limit, stop

    AUTH_POS = [{"ticker": "EMIMl_EQ", "quantity": 956.158,
                 "averagePrice": 4169.00, "currentPrice": 4169.00}]

    # ---- recoverability of the unresolved-fill state ----

    def test_F4_UNRESOLVED_FILL_NOT_CLEARED_BY_EMPTY_BROKER_STATE(self):
        """An empty (but authoritative) broker view is absence, not evidence."""
        limit, stop = self._arm_unresolved()
        self._cycle(limit, stop, dates=self.dates_next, top_symbol="SGLN",
                    positions=[], orders=[], fresh=True)
        self.assertIsNotNone(db.get_unresolved_fill_price_decision(),
                             "an empty broker response must never clear the gate")

    def test_F4_UNRESOLVED_FILL_NOT_CLEARED_BY_NONAUTHORITATIVE_STATE(self):
        """A stale/cached read must not clear it, even showing the real position."""
        limit, stop = self._arm_unresolved()
        feed_pos = self.AUTH_POS
        self._cycle(limit, stop, dates=self.dates_next,
                    positions=feed_pos, orders=[], fresh=False)
        self.assertIsNotNone(db.get_unresolved_fill_price_decision(),
                             "a non-authoritative refresh must never clear the gate")

    def test_F4_UNRESOLVED_FILL_CLEARS_ONLY_AFTER_AUTHORITATIVE_RESOLUTION(self):
        """Positive authoritative evidence -- and only that -- clears the state."""
        limit, stop = self._arm_unresolved()
        # Same position, but non-authoritative: still armed.
        self._cycle(limit, stop, dates=self.dates_next,
                    positions=self.AUTH_POS, orders=[], fresh=False)
        self.assertIsNotNone(db.get_unresolved_fill_price_decision())
        # Now authoritative: resolved.
        self._cycle(limit, stop, dates=self.dates_next,
                    positions=self.AUTH_POS, orders=[], fresh=True)
        self.assertIsNone(db.get_unresolved_fill_price_decision(),
                          "authoritative position evidence must clear the gate")
        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(str(dec.get("execution_status")), "FILLED")

    def test_F4_UNRESOLVED_FILL_SURVIVES_RESTART(self):
        """The gate is persisted, so a fresh process still refuses new entries."""
        limit, stop = self._arm_unresolved()
        dispatched = limit.call_count

        # Simulate a restart: drop all in-process state and rebuild the engine.
        from src.execution.order_state_machine import portfolio_reservations
        self.engine._executed_signals.clear()
        portfolio_reservations.reset()
        self.engine = PRVQuantEngine()
        self.engine._stop_event.set()
        self.engine.is_running = False
        self.engine._executed_signals.clear()

        self.assertIsNotNone(db.get_unresolved_fill_price_decision(),
                             "the unresolved state must survive a restart")
        res = self._cycle(limit, stop, dates=self.dates_next, top_symbol="SGLN",
                          positions=[], orders=[], fresh=True)
        self.assertEqual(limit.call_count - dispatched, 0,
                         "a restarted engine must still refuse new entries")
        self.assertIn("PRICE_UNIT_UNRESOLVED_PENDING_RECONCILIATION",
                      str(res.get("reason", "")))

    def test_F4_UNRESOLVED_FILL_STATE_CANNOT_BE_SILENTLY_OVERWRITTEN(self):
        """A later save for the same signal must not clobber the armed gate."""
        self._arm_unresolved()
        dec = db.get_unresolved_fill_price_decision()
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dec.get("dedup_key"),
            "signal_bar_date": dec.get("signal_bar_date"),
            "signal_generated_at": "2026-09-07T08:00:00+00:00",
            "target_instrument": dec.get("target_instrument"),
            "target_score": 1.0,
            "intended_execution_session": dec.get("intended_execution_session"),
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "PENDING",
            "notes": "attempted re-save",
        })
        self.assertIsNotNone(db.get_unresolved_fill_price_decision(),
                             "an upsert must not disarm the unresolved-fill gate")

    # ---- CASE A: absent ----

    def test_F4_FILLPRICE_ABSENT_USES_EXPLICIT_GBP_FALLBACK(self):
        """Live Trading212 sends no fillPrice: the GBP arrival price is used."""
        res, stop = self._run_entry(
            {"id": "ORD_ABSENT", "status": "FILLED", "filledQuantity": 956.158})
        self.assertEqual(res["decision"], "ENTER")
        stop.assert_called_once()
        _, _, payload = stop.call_args[0]
        # arrival £41.69 -> stop £40.8562 -> 4085.62 GBX
        self.assertAlmostEqual(payload, 4085.62, places=2)

    # ---- CASE B: present and resolvable ----

    def test_F4_RESOLVED_GBX_FILL(self):
        """4169 GBX -> £41.69 -> £40.8562 -> 4085.62 GBX."""
        res, stop = self._run_entry(
            {"id": "ORD_GBX", "status": "FILLED", "fillPrice": 4169.00,
             "filledQuantity": 956.158})
        self.assertEqual(res["decision"], "ENTER")
        stop.assert_called_once()
        _, _, payload = stop.call_args[0]
        self.assertAlmostEqual(payload, 4085.62, places=2)
        self.assertNotAlmostEqual(payload, 40.86, places=2)
        self.assertNotAlmostEqual(payload, 408562.0, places=2)

    def test_F4_RESOLVED_GBP_FILL(self):
        """9.60 GBP stays £9.60 and yields the correct GBP stop, never /100 or *100."""
        self.assertEqual(broker_price_unit("IGLTl_EQ"), "GBP")
        fill_gbp = broker_price_to_gbp(9.60, "IGLTl_EQ")
        self.assertAlmostEqual(fill_gbp, 9.60, places=6)
        stop_gbp = round(fill_gbp * (1.0 - STOP_PCT), 4)
        self.assertAlmostEqual(stop_gbp, 9.408, places=4)
        payload = gbp_to_broker_price(stop_gbp, "IGLTl_EQ")
        self.assertAlmostEqual(payload, 9.408, places=4)
        self.assertNotAlmostEqual(payload, 940.80, places=2)
        self.assertNotAlmostEqual(payload, 0.09408, places=5)

    # ---- CASE B: present but unresolvable ----

    def test_F4_FILLPRICE_PRESENT_UNKNOWN_UNIT_FAILS_CLOSED(self):
        """A present-but-unresolvable fillPrice returns an explicit unresolved state."""
        res, _ = self._run_entry(
            {"id": "ORD_AMBIG", "status": "FILLED", "fillPrice": 4169.00,
             "filledQuantity": 956.158}, break_units=True)
        blob = json.dumps(res, default=str)
        self.assertIn("PRICE_UNIT_UNRESOLVED", blob,
                      "an unresolvable fill price must surface explicitly")
        self.assertNotEqual(res.get("decision"), "ENTER",
                            "an unrecognised fill price must not report a clean entry")

    def test_F4_FILLPRICE_PRESENT_UNKNOWN_UNIT_NEVER_USES_ARRIVAL_AS_ACTUAL_FILL(self):
        """The arrival price must never be passed off as the actual fill price."""
        res, _ = self._run_entry(
            {"id": "ORD_AMBIG2", "status": "FILLED", "fillPrice": 4169.00,
             "filledQuantity": 956.158}, break_units=True)
        blob = json.dumps(res, default=str)
        self.assertNotIn("41.69", blob,
                         "arrival price must not be reported as a recognised fill price")
        for key in ("fill_price", "stop_price"):
            if key in res:
                self.assertIsNone(res[key], f"{key} must be unset when the unit is unresolved")

    def test_F4_AMBIGUOUS_FILLPRICE_CANNOT_CREATE_ACTUAL_FILL_DERIVED_STOP(self):
        """No protective stop may be derived from an unrecognised fill price."""
        _, stop = self._run_entry(
            {"id": "ORD_AMBIG3", "status": "FILLED", "fillPrice": 4169.00,
             "filledQuantity": 956.158}, break_units=True)
        stop.assert_not_called()

