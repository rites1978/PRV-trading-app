"""
🏛️ PRV CAPITAL — CORE ACCOUNT AUTHORITY & FAIL-CLOSED ENTRY GATES
Test Suite: tests/test_core_account_fallback_fail_closed.py

Mandatory Verifications:
1. account is None => HOLD (FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE)
2. account == {} => HOLD (FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE)
3. account["total_value"] is None => HOLD (FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE)
4. account["available_cash"] is None => HOLD (FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE)
5. account["total_value"] <= 0 => HOLD (FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE)
6. account["available_cash"] < 0 => HOLD (FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE)
7. Corrupt / non-numeric values => HOLD (FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE)
8. account["success"] is False => HOLD (FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE)
9. Risk-reducing exits PRESERVED when account state is invalid/missing => EXIT executed
10. Stop-order reconciliation/expansion PRESERVED when account state is invalid/missing
11. Valid authoritative account state => Sizing uses genuine cash/NAV without fallback constant
12. Part D: IGLT unit scaling is metadata-driven (is_uk_pence=False) without magnitude heuristics
"""
import unittest
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from src.config.settings import settings
from src.core.engine import PRVQuantEngine
from src.execution.order_router import order_router
from src.brokers.trading212 import broker
from src.data.market_data import market_data
from src.database.db import db
from src.strategies.core_compounding_v1 import core_compounding_strategy
from src.core.price_units import _lookup_is_uk_pence, broker_price_to_gbp
from src.research.strategies.prv_core_compounding_v1 import load_partition_data, FROZEN_UNIVERSE
from tests._provenance_mocks import provenance_aware


class TestCoreAccountFallbackFailClosed(unittest.TestCase):

    def setUp(self):
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
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                cur.execute("DELETE FROM trades WHERE trade_id LIKE 'ORDER_%' OR trade_id LIKE 'PATH_%'")
                conn.commit()
        except Exception:
            pass

        self.dates = pd.date_range("2024-01-01", "2026-09-04", freq="B")
        self._patch_exec_price = patch.object(
            market_data, "get_current_executable_price",
            side_effect=self._synthetic_executable_price)
        self._patch_exec_price.start()

    def _synthetic_executable_price(self, yf_ticker, is_uk_pence=True):
        try:
            df = market_data.fetch_history(yf_ticker)
        except Exception:
            return None
        if df is None or getattr(df, "empty", True):
            return None
        last = float(df["Close"].iloc[-1])
        if last <= 0:
            return None
        return round(last / 100.0, 4) if is_uk_pence else round(last, 4)

    def tearDown(self):
        self._patch_exec_price.stop()
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_practice
        settings.REAL_MONEY_NEW_ENTRIES_ALLOWED = self.orig_real
        settings.ACCOUNT_MODE = self.orig_mode
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                cur.execute("DELETE FROM trades WHERE trade_id LIKE 'ORDER_%' OR trade_id LIKE 'PATH_%'")
                conn.commit()
        except Exception:
            pass

    def _create_synthetic_feed(self, emim_qualifies: bool = True):
        feed = {}
        n = len(self.dates)
        for inst in core_compounding_strategy.CERTIFIED_UNIVERSE:
            sym = inst["symbol"]
            yf_t = inst["yf_ticker"]
            df = pd.DataFrame(index=self.dates)
            if sym == "EMIM" and emim_qualifies:
                prices = 3000.0 + np.linspace(0, 1500.0, n) + np.sin(np.arange(n)) * 10
            else:
                prices = 2000.0 - np.linspace(0, 500.0, n)
            df["Open"] = prices
            df["High"] = prices * 1.01
            df["Low"] = prices * 0.99
            df["Close"] = prices
            df["Volume"] = 100000
            feed[yf_t] = df
        return feed

    # ──────────────── 1. account is None ────────────────
    def test_01_account_is_none_fails_closed(self):
        feed = self._create_synthetic_feed(emim_qualifies=True)
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(order_router, "route_entry_order") as mock_route:

            res = self.engine._run_core_compounding_cycle(account=None, bypass_execution_window=True)
            self.assertEqual(res["decision"], "HOLD")
            self.assertEqual(res["reason"], "FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE")
            mock_route.assert_not_called()

    # ──────────────── 2. account is empty dict ────────────────
    def test_02_account_empty_dict_fails_closed(self):
        feed = self._create_synthetic_feed(emim_qualifies=True)
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(order_router, "route_entry_order") as mock_route:

            res = self.engine._run_core_compounding_cycle(account={}, bypass_execution_window=True)
            self.assertEqual(res["decision"], "HOLD")
            self.assertEqual(res["reason"], "FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE")
            mock_route.assert_not_called()

    # ──────────────── 3. account["total_value"] is None ────────────────
    def test_03_account_total_value_none_fails_closed(self):
        feed = self._create_synthetic_feed(emim_qualifies=True)
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(order_router, "route_entry_order") as mock_route:

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": None, "available_cash": 49896.38},
                bypass_execution_window=True
            )
            self.assertEqual(res["decision"], "HOLD")
            self.assertEqual(res["reason"], "FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE")
            mock_route.assert_not_called()

    # ──────────────── 4. account["available_cash"] is None ────────────────
    def test_04_account_available_cash_none_fails_closed(self):
        feed = self._create_synthetic_feed(emim_qualifies=True)
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(order_router, "route_entry_order") as mock_route:

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": None},
                bypass_execution_window=True
            )
            self.assertEqual(res["decision"], "HOLD")
            self.assertEqual(res["reason"], "FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE")
            mock_route.assert_not_called()

    # ──────────────── 5. account["total_value"] <= 0 ────────────────
    def test_05_account_total_value_zero_or_negative_fails_closed(self):
        feed = self._create_synthetic_feed(emim_qualifies=True)
        for invalid_nav in [0.0, -100.0]:
            with self.subTest(invalid_nav=invalid_nav):
                with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
                     patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
                     patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
                     patch.object(order_router, "route_entry_order") as mock_route:

                    res = self.engine._run_core_compounding_cycle(
                        account={"total_value": invalid_nav, "available_cash": 49896.38},
                        bypass_execution_window=True
                    )
                    self.assertEqual(res["decision"], "HOLD")
                    self.assertEqual(res["reason"], "FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE")
                    mock_route.assert_not_called()

    # ──────────────── 6. account["available_cash"] < 0 ────────────────
    def test_06_account_available_cash_negative_fails_closed(self):
        feed = self._create_synthetic_feed(emim_qualifies=True)
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(order_router, "route_entry_order") as mock_route:

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": -50.0},
                bypass_execution_window=True
            )
            self.assertEqual(res["decision"], "HOLD")
            self.assertEqual(res["reason"], "FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE")
            mock_route.assert_not_called()

    # ──────────────── 7. Corrupt / non-numeric values ────────────────
    def test_07_account_corrupt_values_fails_closed(self):
        feed = self._create_synthetic_feed(emim_qualifies=True)
        corrupt_cases = [
            {"total_value": "corrupt", "available_cash": 49896.38},
            {"total_value": 49896.38, "available_cash": "invalid"},
            {"total_value": float("nan"), "available_cash": 49896.38},
            {"total_value": 49896.38, "available_cash": float("nan")},
            {"total_value": {}, "available_cash": []},
        ]
        for c_acc in corrupt_cases:
            with self.subTest(c_acc=c_acc):
                with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
                     patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
                     patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
                     patch.object(order_router, "route_entry_order") as mock_route:

                    res = self.engine._run_core_compounding_cycle(account=c_acc, bypass_execution_window=True)
                    self.assertEqual(res["decision"], "HOLD")
                    self.assertEqual(res["reason"], "FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE")
                    mock_route.assert_not_called()

    # ──────────────── 8. account["success"] is False ────────────────
    def test_08_account_success_false_fails_closed(self):
        feed = self._create_synthetic_feed(emim_qualifies=True)
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(order_router, "route_entry_order") as mock_route:

            res = self.engine._run_core_compounding_cycle(
                account={"success": False, "error": "rate_limit_exceeded", "total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )
            self.assertEqual(res["decision"], "HOLD")
            self.assertEqual(res["reason"], "FAIL_CLOSED: MISSING_AUTHORITATIVE_ACCOUNT_STATE")
            mock_route.assert_not_called()

    # ──────────────── 9. Risk-reducing exits PRESERVED when account state is missing ────────────────
    def test_09_risk_reducing_exit_preserved_when_account_state_invalid(self):
        """When an open position breaches stop loss (-2%), exit MUST execute even if account is None."""
        feed = self._create_synthetic_feed(emim_qualifies=False)
        held_pos = [{
            "ticker": "EMIMl_EQ",
            "quantity": 884.0,
            "averagePrice": 4500.0,   # 4500 GBX = £45.00
            "currentPrice": 4400.0    # 4400 GBX = £44.00 (-2.2% <= -2.0% stop)
        }]
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(held_pos)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(order_router, "route_exit_order", return_value=(True, "STOP_EXECUTED", {})) as mock_exit:

            res = self.engine._run_core_compounding_cycle(account=None, bypass_execution_window=True)
            self.assertEqual(res["decision"], "EXIT")
            self.assertIn("STOP_LOSS_TRIGGERED", res["reason"])
            mock_exit.assert_called_once()
            args, kwargs = mock_exit.call_args
            self.assertEqual(kwargs.get("t212_ticker"), "EMIMl_EQ")
            self.assertEqual(kwargs.get("quantity"), 884.0)

    # ──────────────── 10. Stop expansion PRESERVED when account state is missing ────────────────
    def test_10_stop_expansion_preserved_when_account_state_invalid(self):
        """When holding unprotected shares, stop order MUST sync even if account is None."""
        feed = self._create_synthetic_feed(emim_qualifies=False)
        held_pos = [{
            "ticker": "EMIMl_EQ",
            "quantity": 884.0,
            "averagePrice": 4500.0,
            "currentPrice": 4500.0
        }]
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(held_pos)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "sync_broker_stop_order", return_value={"success": True}) as mock_stop_sync:

            res = self.engine._run_core_compounding_cycle(account=None, bypass_execution_window=True)
            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("HOLDING_ACTIVE_POSITION", res["reason"])
            mock_stop_sync.assert_called_once()
            args, _ = mock_stop_sync.call_args
            self.assertEqual(args[0], "EMIMl_EQ")
            self.assertEqual(args[1], 884.0)

    # ──────────────── 11. Authoritative account state proceeds to sizing and dispatch ────────────────
    def test_11_authoritative_account_proceeds_without_fallback_constant(self):
        """Authoritative account NAV and cash are used directly without inventing capital."""
        self.assertTrue(PRVQuantEngine.NO_NEW_ENTRY_FROM_FALLBACK_NAV_OR_CASH)

        feed = self._create_synthetic_feed(emim_qualifies=True)
        mock_snap = {
            "account_summary": {"free_cash": 49896.38, "total_nav": 49896.38},
            "positions": []
        }
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kw: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", return_value={"success": True, "data": {"id": "ORD_OK", "status": "ACCEPTED"}}), \
             patch.object(broker, "sync_broker_stop_order", return_value={"success": True}), \
             patch("src.execution.order_router.portfolio_snapshot.hydrate_once", return_value=mock_snap), \
             patch.object(order_router, "route_entry_order", wraps=order_router.route_entry_order) as spy_route:

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )
            self.assertEqual(res["decision"], "ENTER")
            self.assertEqual(spy_route.call_count, 1)

    # ──────────────── 12. Part D: IGLT metadata-driven normalisation ────────────────
    def test_12_part_d_iglt_metadata_driven_unit_normalisation(self):
        """IGLT is GBP-quoted (is_uk_pence=False); GBX assets have is_uk_pence=True."""
        # Metadata checks
        self.assertFalse(_lookup_is_uk_pence("IGLT"))
        self.assertFalse(_lookup_is_uk_pence("IGLTl_EQ"))
        self.assertTrue(_lookup_is_uk_pence("CSP1"))
        self.assertTrue(_lookup_is_uk_pence("EQQQ"))
        self.assertTrue(_lookup_is_uk_pence("ISF"))
        self.assertTrue(_lookup_is_uk_pence("EMIM"))
        self.assertTrue(_lookup_is_uk_pence("SGLN"))

        # Load partition data and assert IGLT prices are NOT divided by 100
        data = load_partition_data(FROZEN_UNIVERSE, "2025-07-01", "2025-07-15")
        df_iglt = data["IGLT_L"]
        iglt_close = float(df_iglt["Close"].iloc[0])
        # Raw IGLT close is ~£10.70. If divided by 100 it would be ~£0.107.
        self.assertGreater(iglt_close, 5.0, f"IGLT close £{iglt_close} must not be divided by 100")
        self.assertLess(iglt_close, 20.0, f"IGLT close £{iglt_close} must be reasonable gilt price (~£10-12)")

        # GBX assets: CSP1 raw close is ~60,000p. After dividing by 100 it should be ~£600.
        df_csp1 = data["CSP1_L"]
        csp1_close = float(df_csp1["Close"].iloc[0])
        self.assertGreater(csp1_close, 100.0, f"CSP1 close £{csp1_close} should be in £ hundreds")
        self.assertLess(csp1_close, 1000.0, f"CSP1 close £{csp1_close} should be in £ hundreds")


if __name__ == "__main__":
    unittest.main()
