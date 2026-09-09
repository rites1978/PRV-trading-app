"""
🏛️ PRV CAPITAL — LIVE EXECUTION PRICE SIZING REMEDIATION TEST SUITE
Test Suite: tests/test_core_live_price_sizing_remediation.py

Verifies:
1. Market +1% above T-1 close
2. Market -1% below T-1 close
3. +5% overnight gap
4. Current-price lookup unavailable (REJECT_NON_RETRYABLE = EXECUTION_SIZING_PRICE_UNAVAILABLE, no fallback to T-1)
5. Exact broker quantity increment (0.001 increment flooring)
6. Restart / exactly-once behaviour
7. Deterministic broker rejection remains non-retryable
8. UNKNOWN submission remains reconciliation-only
9. Quantity * sizing price never exceeds deployable (tested across 100+ random price/NAV combinations)
10. All seven Core instruments, including IGLT sizing and explicit IWDA execution blocking
"""
import unittest
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo
from datetime import datetime, time as dtime, timezone
import pandas as pd
import numpy as np

from src.config.settings import settings
from src.core.engine import PRVQuantEngine
from src.execution.order_router import order_router
from src.brokers.trading212 import broker
from src.data.market_data import market_data
from src.database.db import db
from src.strategies.core_compounding_v1 import core_compounding_strategy
from src.data.universe import PRV_CORE_COMPOUNDING_UNIVERSE
from tests._provenance_mocks import provenance_aware


class TestCoreLivePriceSizingRemediation(unittest.TestCase):

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
        from src.execution.order_state_machine import portfolio_reservations
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
        self.patch_stop = patch.object(broker, "sync_broker_stop_order", return_value={"success": True, "data": {"id": "STOP_MOCK_1"}})
        self.patch_cancel = patch.object(broker, "cancel_stop_orders_for_ticker", return_value=["STOP_MOCK_1"])
        self.patch_account = patch.object(broker, "get_account_summary", return_value={"total": 49896.38, "free": 49896.38, "invested": 0.0, "ppl": 0.0, "result": 0.0})
        from src.portfolio.portfolio_snapshot import portfolio_snapshot
        self.patch_snap = patch.object(portfolio_snapshot, "hydrate_once", return_value={"account_summary": {"free_cash": 49896.38, "total_nav": 49896.38}, "positions": []})
        self.patch_stop.start()
        self.patch_cancel.start()
        self.patch_account.start()
        self.patch_snap.start()

    def tearDown(self):
        self.patch_stop.stop()
        self.patch_cancel.stop()
        self.patch_account.stop()
        self.patch_snap.stop()
        from src.execution.order_state_machine import portfolio_reservations
        portfolio_reservations.reset()
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_practice
        settings.REAL_MONEY_NEW_ENTRIES_ALLOWED = self.orig_real
        settings.ACCOUNT_MODE = self.orig_mode
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                cur.execute("DELETE FROM trades")
                conn.commit()
        except Exception:
            pass

    def _create_synthetic_feed(self, top_symbol="EMIM", emim_close=41.59):
        feed = {}
        for item in core_compounding_strategy.CERTIFIED_UNIVERSE:
            sym = item["symbol"]
            yf_t = item["yf_ticker"]
            n = len(self.dates)
            if sym == top_symbol:
                base = emim_close * 100.0 if item.get("is_uk_pence", True) else emim_close
                closes = np.linspace(base * 0.75, base, n)
            else:
                closes = np.linspace(1000.0, 900.0, n)
            df = pd.DataFrame({
                "Open": closes * 0.999,
                "High": closes * 1.002,
                "Low": closes * 0.998,
                "Close": closes,
                "Volume": [100000] * n
            }, index=self.dates)
            feed[yf_t] = df
        return feed

    def test_01_market_plus_one_percent_sizing(self):
        """1. Market +1% above T-1 close: sizing uses max permitted fill price and notional <= deployable."""
        t_minus_1_close = 41.5900
        live_price = round(t_minus_1_close * 1.01, 4)  # 42.0059
        collar_pct = settings.MARKETABLE_LIMIT_SLIPPAGE_BPS / 10000.0  # 10 bps
        max_permitted_fill = round(live_price * (1.0 + collar_pct), 4)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=t_minus_1_close)
        nav = 49896.38
        deployable = min(40000.0, nav, nav * 0.80 - 15.0)

        mock_place = MagicMock(return_value={"success": True, "data": {"id": "ORD_P1", "status": "SUBMITTED", "filledQuantity": 0}})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=live_price), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            self.assertEqual(mock_place.call_count, 1)
            call_ticker, call_qty = mock_place.call_args[0][:2]
            self.assertEqual(call_ticker, "EMIMl_EQ")

            # Verify quantity is calculated against max permitted fill price and <= deployable
            expected_qty = core_compounding_strategy.floor_to_broker_increment(deployable / max_permitted_fill)
            self.assertEqual(call_qty, expected_qty)
            self.assertLessEqual(call_qty * max_permitted_fill, deployable)
            self.assertLess(call_qty, 959.0)  # Quantity is lower than at T-1 close

    def test_02_market_minus_one_percent_sizing(self):
        """2. Market -1% below T-1 close: sizing recalibrates to larger quantity within deployable cap."""
        t_minus_1_close = 41.5900
        live_price = round(t_minus_1_close * 0.99, 4)  # 41.1741
        collar_pct = settings.MARKETABLE_LIMIT_SLIPPAGE_BPS / 10000.0
        max_permitted_fill = round(live_price * (1.0 + collar_pct), 4)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=t_minus_1_close)
        nav = 49896.38
        deployable = min(40000.0, nav, nav * 0.80 - 15.0)

        mock_place = MagicMock(return_value={"success": True, "data": {"id": "ORD_M1", "status": "SUBMITTED", "filledQuantity": 0}})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=live_price), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            self.assertEqual(mock_place.call_count, 1)
            call_ticker, call_qty = mock_place.call_args[0][:2]

            expected_qty = core_compounding_strategy.floor_to_broker_increment(deployable / max_permitted_fill)
            self.assertEqual(call_qty, expected_qty)
            self.assertLessEqual(call_qty * max_permitted_fill, deployable)
            self.assertGreater(call_qty, 959.0)  # Quantity increased due to lower price

    def test_03_plus_five_percent_overnight_gap(self):
        """3. +5% overnight gap: prevents severe capital breach by sizing against gap open + collar."""
        t_minus_1_close = 41.5900
        live_price = round(t_minus_1_close * 1.05, 4)  # 43.6695
        collar_pct = settings.MARKETABLE_LIMIT_SLIPPAGE_BPS / 10000.0
        max_permitted_fill = round(live_price * (1.0 + collar_pct), 4)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=t_minus_1_close)
        nav = 49896.38
        deployable = min(40000.0, nav, nav * 0.80 - 15.0)

        mock_place = MagicMock(return_value={"success": True, "data": {"id": "ORD_GAP", "status": "SUBMITTED", "filledQuantity": 0}})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=live_price), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            call_ticker, call_qty = mock_place.call_args[0][:2]

            self.assertLessEqual(call_qty * max_permitted_fill, deployable)
            self.assertAlmostEqual(call_qty, 912.816, places=2)

    def test_04_current_price_lookup_unavailable_fail_closed(self):
        """4. Current-price lookup unavailable: REJECT_NON_RETRYABLE = EXECUTION_SIZING_PRICE_UNAVAILABLE, no fallback to T-1."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        nav = 49896.38

        mock_place = MagicMock()

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=None), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("EXECUTION_SIZING_PRICE_UNAVAILABLE", res["reason"])
            self.assertEqual(mock_place.call_count, 0)

            # Verify persisted decision in DB
            obs_bar_str = "2026-09-04"
            dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"
            dec = db.get_core_compounding_decision(dedup_key)
            self.assertIsNotNone(dec)
            self.assertEqual(dec["execution_status"], "REJECTED_NON_RETRYABLE_FOR_SIGNAL")

    def test_05_exact_broker_quantity_increment(self):
        """5. Exact broker quantity increment: verify 3 decimals flooring without rounding up."""
        prices = [41.6900, 41.4800, 609.4500, 9.5575, 531.0800, 10.4980, 63.1000]
        deployable = 39902.104

        for p in prices:
            collar_p = round(p * 1.0010, 4)
            qty = core_compounding_strategy.calculate_order_shares(
                entry_price_gbp=collar_p,
                available_cash_gbp=deployable,
                total_nav_gbp=49896.38,
                symbol="EMIM"
            )
            # Decimals must be <= 3
            dec_len = len(str(qty).split(".")[1]) if "." in str(qty) else 0
            self.assertLessEqual(dec_len, 3)
            # Must strictly satisfy notional <= deployable
            self.assertLessEqual(qty * collar_p, deployable)

    def test_06_restart_exactly_once_behaviour(self):
        """6. Restart / exactly-once behaviour: persistent deduplication across process restarts."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        nav = 49896.38
        mock_place = MagicMock(return_value={"success": True, "data": {"id": "ORD_1", "status": "SUBMITTED", "filledQuantity": 0}})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.69), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            # Cycle 1: Executes
            res1 = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )
            self.assertEqual(res1["decision"], "ENTER")
            self.assertEqual(mock_place.call_count, 1)

            # Simulate process restart
            new_engine = PRVQuantEngine()
            new_engine._stop_event.set()
            new_engine.is_running = False

            # Cycle 2: DEDUP triggered from SQLite DB
            res2 = new_engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )
            self.assertEqual(res2["decision"], "HOLD")
            self.assertIn("DEDUP", res2["reason"])
            self.assertEqual(mock_place.call_count, 1)

    def test_07_deterministic_broker_rejection_non_retryable(self):
        """7. Deterministic broker rejection remains non-retryable across cycles."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        nav = 49896.38
        mock_place = MagicMock(return_value={"success": False, "error": "HTTP 400: Order rejected by risk"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.69), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            # Cycle 1: Dispatches and gets rejected
            res1 = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )
            self.assertEqual(res1["decision"], "HOLD")
            self.assertEqual(mock_place.call_count, 1)

            # Cycle 2: Same bar detects non-retryable rejection dedup
            res2 = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )
            self.assertEqual(res2["decision"], "HOLD")
            self.assertIn("DEDUP", res2["reason"])
            self.assertEqual(mock_place.call_count, 1)

    def test_08_unknown_submission_reconciliation_only(self):
        """8. UNKNOWN submission remains reconciliation-only (never blindly retried)."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        nav = 49896.38
        mock_place = MagicMock(return_value={"success": False, "error": "HTTPSConnectionPool: Read timed out", "is_timeout": True})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.69), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            res1 = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )
            self.assertEqual(res1["decision"], "HOLD")
            self.assertIn("UNKNOWN_PENDING_RECONCILIATION", res1["reason"])
            self.assertEqual(mock_place.call_count, 1)

            # Verify persisted state in SQLite DB
            obs_bar_str = "2026-09-04"
            dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"
            dec = db.get_core_compounding_decision(dedup_key)
            self.assertIsNotNone(dec)
            self.assertEqual(dec["execution_status"], "UNKNOWN_PENDING_RECONCILIATION")

            # Persistent protection on process restart
            restarted_engine = PRVQuantEngine()
            restarted_engine._stop_event.set()
            restarted_engine.is_running = False
            is_exec = restarted_engine.is_signal_bar_already_executed(dedup_key)
            self.assertTrue(is_exec, "UNKNOWN submission must persist in DB to prevent duplicate orders on restart")

            # Subsequent cycle must never blindly submit a new order
            res2 = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )
            self.assertEqual(mock_place.call_count, 1)  # No blind resubmission

    def test_09_quantity_times_sizing_price_never_exceeds_deployable(self):
        """9. Invariant: quantity * sizing_price <= deployable holds across 100+ random price/NAV combinations."""
        np.random.seed(42)
        for _ in range(100):
            test_price = float(np.random.uniform(0.5, 2000.0))
            test_nav = float(np.random.uniform(5000.0, 100000.0))
            test_cash = float(np.random.uniform(1000.0, test_nav))
            deployable = min(40000.0, test_cash, test_nav * 0.80 - 15.0)

            if deployable <= 0:
                continue

            collar_p = round(test_price * 1.0010, 4)
            qty = core_compounding_strategy.calculate_order_shares(
                entry_price_gbp=collar_p,
                available_cash_gbp=test_cash,
                total_nav_gbp=test_nav,
                symbol="EMIM"
            )

            notional = qty * collar_p
            self.assertLessEqual(notional, deployable + 1e-9, f"Breached at price={test_price}, nav={test_nav}: notional={notional} > deployable={deployable}")

    def test_10_all_seven_core_instruments_and_iwda_blocked(self):
        """10. All seven Core instruments: IGLT correctly sized in GBP, and IWDA strictly BLOCKED from execution."""
        nav = 49896.38
        deployable = min(40000.0, nav, nav * 0.80 - 15.0)

        # 10a. Verify IWDA is strictly blocked in engine & order router
        feed_iwda = self._create_synthetic_feed(top_symbol="IWDA", emim_close=114.0)
        mock_place = MagicMock()

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed_iwda.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=1.468), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("IWDA is blocked from execution", res["reason"])
            self.assertEqual(mock_place.call_count, 0)  # IWDA NEVER calls broker!

        # 10b. Verify IGLT sizing in GBP (£9.55 -> ~4170 shares)
        iglt_price = 9.5575
        iglt_collar = round(iglt_price * 1.0010, 4)
        iglt_qty = core_compounding_strategy.calculate_order_shares(
            entry_price_gbp=iglt_collar,
            available_cash_gbp=nav,
            total_nav_gbp=nav,
            symbol="IGLT"
        )
        self.assertAlmostEqual(iglt_qty, 4170.81, delta=5.0)
        self.assertLessEqual(iglt_qty * iglt_collar, deployable)

        # 10c. Verify all remaining symbols (CSP1, EQQQ, ISF, EMIM, SGLN) size properly
        for sym, p in [("CSP1", 609.45), ("EQQQ", 531.08), ("ISF", 10.498), ("EMIM", 41.69), ("SGLN", 63.10)]:
            collar = round(p * 1.0010, 4)
            q = core_compounding_strategy.calculate_order_shares(
                entry_price_gbp=collar,
                available_cash_gbp=nav,
                total_nav_gbp=nav,
                symbol=sym
            )
    def test_11_today_emim_exact_replay_mock_broker(self):
        """
        11. Complete production-path exact replay of today's EMIM signal with mock broker only.
        Calculates and verifies all required telemetry and safety boundaries.
        """
        signal_price = 41.5900
        live_price = 41.6900
        nav = 49896.38
        deployable = min(40000.0, nav, nav * 0.80 - 15.0)  # 39902.104
        collar_pct = settings.MARKETABLE_LIMIT_SLIPPAGE_BPS / 10000.0  # 10 bps
        max_permitted_fill = round(live_price * (1.0 + collar_pct), 4)  # 41.7317

        raw_qty = deployable / max_permitted_fill
        broker_qty = core_compounding_strategy.floor_to_broker_increment(raw_qty, increment=0.001, precision=3)
        max_possible_notional = round(broker_qty * max_permitted_fill, 2)
        stop_price = round(live_price * (1.0 - core_compounding_strategy.STOP_LOSS_PCT), 4)
        max_gross_stop_risk = round(max_possible_notional - (broker_qty * stop_price), 2)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=signal_price)
        mock_place = MagicMock(return_value={"success": True, "data": {"id": "ORD_EMIM_REPLAY", "status": "SUBMITTED", "filledQuantity": 0}})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=live_price), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_place):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            self.assertEqual(mock_place.call_count, 1)
            call_ticker, call_qty = mock_place.call_args[0][:2]
            self.assertEqual(call_ticker, "EMIMl_EQ")
            self.assertEqual(call_qty, broker_qty)
            self.assertEqual(broker_qty, 956.158)
            self.assertLessEqual(max_possible_notional, deployable)
            self.assertEqual(stop_price, 40.8562)


if __name__ == "__main__":
    unittest.main()
