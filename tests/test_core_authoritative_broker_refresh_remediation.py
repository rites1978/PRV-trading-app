"""
🏛️ PRV CAPITAL — AUTHORITATIVE BROKER REFRESH & CACHE-PROVENANCE TEST SUITE
File: tests/test_core_authoritative_broker_refresh_remediation.py

Verifies the 9 required execution-reconciliation scenarios:
1. CANCEL_SUCCESS_ORDERS_REFRESH_TIMEOUT_CACHE_EMPTY
2. CANCEL_SUCCESS_ORDERS_REFRESH_500_CACHE_STALE
3. CANCEL_SUCCESS_POSITIONS_REFRESH_TIMEOUT_CACHE_EMPTY
4. CANCEL_SUCCESS_POSITIONS_REFRESH_500_CACHE_STALE
5. ORDERS_FRESH_POSITIONS_STALE
6. ORDERS_STALE_POSITIONS_FRESH
7. BOTH_REFRESHES_STALE
8. BOTH_REFRESHES_AUTHORITATIVE
9. RESTART_WITH_ONLY_CACHED_BROKER_STATE

And certifies the 4 execution invariants:
- CACHED_DATA_NEVER_COUNTS_AS_BROKER_CONFIRMATION = TRUE
- TERMINAL_STATE_REQUIRES_AUTHORITATIVE_ORDERS_REFRESH = TRUE
- TERMINAL_STATE_REQUIRES_AUTHORITATIVE_POSITIONS_REFRESH = TRUE
- UNKNOWN_BROKER_STATE_REMAINS_NON_TERMINAL = TRUE
"""
import unittest
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from src.config.settings import settings
from src.core.engine import PRVQuantEngine
from src.brokers.trading212 import broker
from src.data.market_data import market_data
from src.database.db import db
from src.strategies.core_compounding_v1 import core_compounding_strategy


class TestCoreAuthoritativeBrokerRefreshRemediation(unittest.TestCase):

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

        self.patch_account = patch.object(broker, "get_account_summary", return_value={"total": 49896.38, "free": 49896.38, "invested": 0.0, "ppl": 0.0, "result": 0.0})
        from src.portfolio.portfolio_snapshot import portfolio_snapshot
        self.patch_snap = patch.object(portfolio_snapshot, "hydrate_once", return_value={"account_summary": {"free_cash": 49896.38, "total_nav": 49896.38}, "positions": []})
        self.patch_stop = patch.object(broker, "sync_broker_stop_order", return_value={"success": True, "data": {"id": "STOP_MOCK_AUTH"}})
        self.patch_cancel = patch.object(broker, "cancel_stop_orders_for_ticker", return_value=["STOP_MOCK_AUTH"])

        self.patch_account.start()
        self.patch_snap.start()
        self.patch_stop.start()
        self.patch_cancel.start()

    def tearDown(self):
        self.patch_account.stop()
        self.patch_snap.stop()
        self.patch_stop.stop()
        self.patch_cancel.stop()

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

    # =========================================================================
    # SCENARIO 1: CANCEL_SUCCESS_ORDERS_REFRESH_TIMEOUT_CACHE_EMPTY
    # =========================================================================
    def test_01_cancel_success_orders_refresh_timeout_cache_empty(self):
        """
        1. CANCEL_SUCCESS_ORDERS_REFRESH_TIMEOUT_CACHE_EMPTY:
        Cancel succeeds on broker, but post-cancel get_open_orders times out.
        Cache was empty. Authoritative freshness is False.
        Engine MUST NOT assume order is absent.
        Status MUST remain WINDOW_CLOSE_PENDING_RECONCILIATION.
        """
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)

        w_ord = {"id": "ORD_SC1", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        mock_cancel = MagicMock(return_value={"success": True})

        call_count_orders = 0
        def smart_orders(**kw):
            nonlocal call_count_orders
            call_count_orders += 1
            if call_count_orders == 1:
                return [w_ord]
            if kw.get("return_provenance", False):
                return ([], False)
            return []

        def smart_positions(**kw):
            if kw.get("return_provenance", False):
                return ([], True)
            return []

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=smart_positions), \
             patch.object(broker, "get_open_orders", side_effect=smart_orders), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_SC1")

        dec = db.get_latest_core_compounding_decision()
        self.assertIsNotNone(dec)
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")
        self.assertIn("not authoritative", dec["notes"])
        self.assertNotEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")

    # =========================================================================
    # SCENARIO 2: CANCEL_SUCCESS_ORDERS_REFRESH_500_CACHE_STALE
    # =========================================================================
    def test_02_cancel_success_orders_refresh_500_cache_stale(self):
        """
        2. CANCEL_SUCCESS_ORDERS_REFRESH_500_CACHE_STALE:
        Cancel succeeds, but orders refresh returns HTTP 500 with stale cache.
        orders_fresh == False. Remains WINDOW_CLOSE_PENDING_RECONCILIATION.
        """
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)

        w_ord = {"id": "ORD_SC2", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        mock_cancel = MagicMock(return_value={"success": True})

        call_count_orders = 0
        def smart_orders(**kw):
            nonlocal call_count_orders
            call_count_orders += 1
            if call_count_orders == 1:
                return [w_ord]
            if kw.get("return_provenance", False):
                return ([w_ord], False)
            return [w_ord]

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=lambda **kw: ([], True) if kw.get("return_provenance") else []), \
             patch.object(broker, "get_open_orders", side_effect=smart_orders), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")
        self.assertNotEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")

    # =========================================================================
    # SCENARIO 3: CANCEL_SUCCESS_POSITIONS_REFRESH_TIMEOUT_CACHE_EMPTY
    # =========================================================================
    def test_03_cancel_success_positions_refresh_timeout_cache_empty(self):
        """
        3. CANCEL_SUCCESS_POSITIONS_REFRESH_TIMEOUT_CACHE_EMPTY:
        Cancel succeeds, orders refresh is fresh and confirms order absent.
        However, positions refresh times out (positions_fresh == False).
        Engine CANNOT claim final filled quantity or transition to terminal state.
        Status MUST remain WINDOW_CLOSE_PENDING_RECONCILIATION.
        """
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)

        w_ord = {"id": "ORD_SC3", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        mock_cancel = MagicMock(return_value={"success": True})

        call_count_orders = 0
        def smart_orders(**kw):
            nonlocal call_count_orders
            call_count_orders += 1
            if call_count_orders == 1:
                return [w_ord]
            if kw.get("return_provenance", False):
                return ([], True)
            return []

        call_count_pos = 0
        def smart_positions(**kw):
            nonlocal call_count_pos
            call_count_pos += 1
            if call_count_pos == 1:
                return []
            if kw.get("return_provenance", False):
                return ([], False)
            return []

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=smart_positions), \
             patch.object(broker, "get_open_orders", side_effect=smart_orders), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")
        self.assertIn("positions_fresh=False", dec["notes"])
        self.assertNotEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")
        self.assertNotEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")

    # =========================================================================
    # SCENARIO 4: CANCEL_SUCCESS_POSITIONS_REFRESH_500_CACHE_STALE
    # =========================================================================
    def test_04_cancel_success_positions_refresh_500_cache_stale(self):
        """
        4. CANCEL_SUCCESS_POSITIONS_REFRESH_500_CACHE_STALE:
        Cancel succeeds, orders fresh, but positions refresh returns 500 with stale cache.
        Cached data never counts as broker confirmation.
        Status MUST remain WINDOW_CLOSE_PENDING_RECONCILIATION.
        """
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)

        w_ord = {"id": "ORD_SC4", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        stale_pos = [{"ticker": "EMIMl_EQ", "quantity": 200.0, "averagePrice": 41.69}]
        mock_cancel = MagicMock(return_value={"success": True})

        call_count_orders = 0
        def smart_orders(**kw):
            nonlocal call_count_orders
            call_count_orders += 1
            if call_count_orders == 1:
                return [w_ord]
            if kw.get("return_provenance", False):
                return ([], True)
            return []

        def smart_positions(**kw):
            if kw.get("return_provenance", False):
                return (stale_pos, False)
            return stale_pos

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=smart_positions), \
             patch.object(broker, "get_open_orders", side_effect=smart_orders), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 41558.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")
        self.assertNotEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")

    # =========================================================================
    # SCENARIO 5: ORDERS_FRESH_POSITIONS_STALE
    # =========================================================================
    def test_05_orders_fresh_positions_stale(self):
        """
        5. ORDERS_FRESH_POSITIONS_STALE:
        orders_authoritative == True, positions_authoritative == False.
        reconcile_unknown_submissions must refuse terminal transition and return WINDOW_CLOSE_PENDING_RECONCILIATION.
        """
        obs_bar_str = "2026-09-04"
        dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "WINDOW_CLOSE_PENDING_RECONCILIATION",
            "broker_order_id": "ORD_SC5",
            "notes": "Cancel pending"
        })

        recon_msg = self.engine.reconcile_unknown_submissions(
            open_positions=[],
            open_orders=[],
            positions_authoritative=False,
            orders_authoritative=True
        )
        self.assertIn("WINDOW_CLOSE_PENDING_RECONCILIATION", recon_msg)
        self.assertIn("refresh not authoritative", recon_msg.lower())

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")

    # =========================================================================
    # SCENARIO 6: ORDERS_STALE_POSITIONS_FRESH
    # =========================================================================
    def test_06_orders_stale_positions_fresh(self):
        """
        6. ORDERS_STALE_POSITIONS_FRESH:
        orders_authoritative == False, positions_authoritative == True.
        reconcile_unknown_submissions must refuse terminal transition and return WINDOW_CLOSE_PENDING_RECONCILIATION.
        """
        obs_bar_str = "2026-09-04"
        dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "WINDOW_CLOSE_PENDING_RECONCILIATION",
            "broker_order_id": "ORD_SC6",
            "notes": "Cancel pending"
        })

        recon_msg = self.engine.reconcile_unknown_submissions(
            open_positions=[],
            open_orders=[],
            positions_authoritative=True,
            orders_authoritative=False
        )
        self.assertIn("WINDOW_CLOSE_PENDING_RECONCILIATION", recon_msg)
        self.assertIn("refresh not authoritative", recon_msg.lower())

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")

    # =========================================================================
    # SCENARIO 7: BOTH_REFRESHES_STALE
    # =========================================================================
    def test_07_both_refreshes_stale(self):
        """
        7. BOTH_REFRESHES_STALE:
        Both orders and positions refreshes fail / are stale.
        Must remain WINDOW_CLOSE_PENDING_RECONCILIATION.
        """
        obs_bar_str = "2026-09-04"
        dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "WINDOW_CLOSE_PENDING_RECONCILIATION",
            "broker_order_id": "ORD_SC7",
            "notes": "Cancel pending"
        })

        recon_msg = self.engine.reconcile_unknown_submissions(
            open_positions=[],
            open_orders=[],
            positions_authoritative=False,
            orders_authoritative=False
        )
        self.assertIn("WINDOW_CLOSE_PENDING_RECONCILIATION", recon_msg)

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")

    # =========================================================================
    # SCENARIO 8: BOTH_REFRESHES_AUTHORITATIVE
    # =========================================================================
    def test_08_both_refreshes_authoritative_clean_expiration_and_partial_fill(self):
        """
        8. BOTH_REFRESHES_AUTHORITATIVE:
        Both orders and positions are authoritative fresh (HTTP 200).
        Case 8a: Order absent, position 0 -> Cleanly transitions to EXPIRED_MISSED_WINDOW.
        Case 8b: Order absent, position 400 -> Syncs stop, cleanly transitions to PARTIALLY_FILLED_WINDOW_CLOSED.
        """
        tz = ZoneInfo("Europe/London")
        t_08_06 = datetime(2026, 9, 7, 8, 6, 0, tzinfo=tz)

        # Case 8a: Unfilled expiration
        obs_bar_str = "2026-09-04"
        dedup_key_a = f"CORE_EMIMl_EQ_{obs_bar_str}_A"
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key_a,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "WINDOW_CLOSE_PENDING_RECONCILIATION",
            "broker_order_id": "ORD_SC8_A",
            "notes": "Cancel completed on broker"
        })

        recon_msg_a = self.engine.reconcile_unknown_submissions(
            open_positions=[],
            open_orders=[],
            positions_authoritative=True,
            orders_authoritative=True,
            current_time=t_08_06
        )
        self.assertIn("EXPIRED_MISSED_WINDOW", recon_msg_a)
        dec_a = db.get_core_compounding_decision(dedup_key_a)
        self.assertEqual(dec_a["execution_status"], "EXPIRED_MISSED_WINDOW")

        # Case 8b: Partial fill
        dedup_key_b = f"CORE_EMIMl_EQ_{obs_bar_str}_B"
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key_b,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "WINDOW_CLOSE_PENDING_RECONCILIATION",
            "broker_order_id": "ORD_SC8_B",
            "notes": "Partial fill confirmed on broker"
        })

        pos_400 = [{"ticker": "EMIMl_EQ", "quantity": 400.0, "averagePrice": 41.7000, "currentPrice": 41.7000}]
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_SC8_B"})

        with patch.object(broker, "sync_broker_stop_order", mock_sync_stop):
            recon_msg_b = self.engine.reconcile_unknown_submissions(
                open_positions=pos_400,
                open_orders=[],
                positions_authoritative=True,
                orders_authoritative=True,
                current_time=t_08_06
            )
            self.assertIn("PARTIALLY_FILLED_WINDOW_CLOSED", recon_msg_b)
            mock_sync_stop.assert_called_once()
            _, s_qty, s_price = mock_sync_stop.call_args[0]
            self.assertEqual(s_qty, 400.0)
            self.assertEqual(s_price, 4086.60)

        dec_b = db.get_core_compounding_decision(dedup_key_b)
        self.assertEqual(dec_b["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")

    # =========================================================================
    # SCENARIO 9: RESTART_WITH_ONLY_CACHED_BROKER_STATE
    # =========================================================================
    def test_09_restart_with_only_cached_broker_state(self):
        """
        9. RESTART_WITH_ONLY_CACHED_BROKER_STATE:
        Daemon restarts. DB has a decision in WINDOW_CLOSE_PENDING_RECONCILIATION.
        Broker network call fails (e.g. timeout / connection refused / 500).
        Broker only returns cached data from disk.
        Authoritative provenance returns False.
        Reconciliation MUST refuse to mark terminal state and remain in WINDOW_CLOSE_PENDING_RECONCILIATION.
        Dedup key remains protected so no replacement entry is placed.
        """
        tz = ZoneInfo("Europe/London")
        t_08_06 = datetime(2026, 9, 7, 8, 6, 0, tzinfo=tz)
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)

        obs_bar_str = "2026-09-04"
        dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "WINDOW_CLOSE_PENDING_RECONCILIATION",
            "broker_order_id": "ORD_SC9_REBOOT",
            "notes": "Decision in pending state prior to daemon restart"
        })

        restarted_engine = PRVQuantEngine()
        restarted_engine._stop_event.set()
        restarted_engine.is_running = False

        mock_limit = MagicMock()
        mock_cancel = MagicMock()

        # Simulate broker failing on HTTP GET with cached disk fallback
        def get_orders_cached(**kw):
            if kw.get("return_provenance", False):
                return ([], False)
            return []

        def get_positions_cached(**kw):
            if kw.get("return_provenance", False):
                return ([], False)
            return []

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=get_positions_cached), \
             patch.object(broker, "get_open_orders", side_effect=get_orders_cached), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = restarted_engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_06
            )
            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("RECONCILIATION_COMPLETED", res["reason"])
            self.assertIn("WINDOW_CLOSE_PENDING_RECONCILIATION", res["reason"])
            mock_limit.assert_not_called()
            mock_cancel.assert_not_called()

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")
        self.assertNotEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")
        self.assertNotEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")
        self.assertTrue(restarted_engine.is_signal_bar_already_executed(dedup_key))


if __name__ == "__main__":
    unittest.main()
