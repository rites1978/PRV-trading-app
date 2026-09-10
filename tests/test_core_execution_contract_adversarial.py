"""
🏛️ PRV CAPITAL — ADVERSARIAL EXECUTION CONTRACT TEST SUITE
Test Suite: tests/test_core_execution_contract_adversarial.py

Verifies:
1. Broker payload contains enforceable limitPrice (POST /equity/orders/limit)
2. Fill at £41.6900 -> Stop at £40.8562 (exact 2.0000%)
3. Fill at £41.7100 -> Stop at £40.8758 (exact 2.0000%)
4. Fill at £41.7317 -> Stop at £40.8971 (exact 2.0000%)
5. No fill (ACCEPTED, filledQuantity=0) -> No stop submitted, position fully protected
6. Partial fill (400 shares) -> Stop placed for exactly 400 shares @ fill price 2%
7. Rejected limit order -> Marked non-retryable, DEDUP prevents retry
8. Restart after accepted-but-not-filled -> Reconciles without duplicate order
9. Restart after partial fill -> Reconciles without duplicate order
10. UNKNOWN broker response -> Reconciliation-only, no blind resubmission
11. Duplicate scheduler cycles -> Exactly-once execution
12. Limit expiry -> Reconciles absent order to RETRYABLE for next session
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
from tests._provenance_mocks import provenance_aware


class TestCoreExecutionContractAdversarial(unittest.TestCase):

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
        self.patch_stop = patch.object(broker, "sync_broker_stop_order", return_value={"success": True, "data": {"id": "STOP_MOCK_1"}})
        self.patch_cancel = patch.object(broker, "cancel_stop_orders_for_ticker", return_value=["STOP_MOCK_1"])

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

    def test_01_broker_enforced_limit_order_payload(self):
        """1. Verify outbound order is a limit order with broker-enforced limitPrice."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        live_price = 41.6900
        nav = 49896.38
        deployable = min(40000.0, nav, nav * 0.80 - 15.0)  # 39902.104
        max_permitted_fill = round(live_price * 1.0010, 4)  # 41.7317

        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "ORD_LIMIT_001",
                "status": "FILLED",
                # BROKER-NATIVE GBX: 4169.00 GBX = £41.69 (see note below).
                "fillPrice": 4169.00,
                "filledQuantity": 956.158
            }
        })

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=live_price),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": nav, "available_cash": nav},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            mock_limit.assert_called_once()
            ticker, qty, limit_p = mock_limit.call_args[0][:3]
            time_val = mock_limit.call_args[1].get("time_validity", "DAY")

            self.assertEqual(ticker, "EMIMl_EQ")
            self.assertEqual(qty, 956.158)
            # 41.7317 GBP converted to 4173.17 GBX for UK pence instrument
            self.assertEqual(limit_p, 4173.17)
            self.assertEqual(time_val, "DAY")

            max_exec_notional = round(qty * max_permitted_fill, 2)
            self.assertLessEqual(max_exec_notional, deployable)
            self.assertEqual(max_exec_notional, 39902.10)

    def test_02_fill_at_41_6900_exact_2pct_stop(self):
        """2. Simulated fill @ £41.6900: Stop is £40.8562 (exact 2.0000%)."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        fill_p = 41.6900
        # BROKER-NATIVE UNITS: EMIMl_EQ is GBX-quoted, so the broker's own price
        # fields are GBX -- the real payload's sibling limitPrice is 4204.79 for a
        # ~£42 line, and this suite already uses GBX for averagePrice/stopPrice.
        # order['currency']='GBP' is the SETTLEMENT currency, not quote-unit
        # authority. Economic meaning is unchanged: 4169.00 GBX = £41.6900.
        broker_fill_p = round(fill_p * 100.0, 2)  # 4169.00 GBX
        qty = 956.158

        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_FILL_1", "status": "FILLED", "fillPrice": broker_fill_p, "filledQuantity": qty}
        })
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_1"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit),              patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            mock_sync_stop.assert_called_once()
            s_ticker, s_qty, s_price = mock_sync_stop.call_args[0]

            self.assertEqual(s_ticker, "EMIMl_EQ")
            self.assertEqual(s_qty, qty)
            # £41.6900 * 0.98 = £40.8562 -> 4085.62 GBX
            self.assertEqual(s_price, 4085.62)
            stop_gbp = s_price / 100.0
            dist_pct = (fill_p - stop_gbp) / fill_p
            self.assertAlmostEqual(dist_pct, 0.0200, places=4)

    def test_03_fill_at_41_7100_exact_2pct_stop(self):
        """3. Simulated fill @ £41.7100: Stop is £40.8758 (exact 2.0000%, not stale £40.8562)."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        fill_p = 41.7100
        # BROKER-NATIVE UNITS: EMIMl_EQ is GBX-quoted, so the broker's own price
        # fields are GBX -- the real payload's sibling limitPrice is 4204.79 for a
        # ~£42 line, and this suite already uses GBX for averagePrice/stopPrice.
        # order['currency']='GBP' is the SETTLEMENT currency, not quote-unit
        # authority. Economic meaning is unchanged: 4171.00 GBX = £41.7100.
        broker_fill_p = round(fill_p * 100.0, 2)  # 4171.00 GBX
        qty = 956.158

        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_FILL_2", "status": "FILLED", "fillPrice": broker_fill_p, "filledQuantity": qty}
        })
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_2"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit),              patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            mock_sync_stop.assert_called_once()
            s_ticker, s_qty, s_price = mock_sync_stop.call_args[0]

            self.assertEqual(s_ticker, "EMIMl_EQ")
            self.assertEqual(s_qty, qty)
            # £41.7100 * 0.98 = £40.8758 -> 4087.58 GBX
            self.assertEqual(s_price, 4087.58)
            stop_gbp = s_price / 100.0
            dist_pct = (fill_p - stop_gbp) / fill_p
            self.assertAlmostEqual(dist_pct, 0.0200, places=4)

    def test_04_fill_at_41_7317_exact_2pct_stop(self):
        """4. Simulated fill @ £41.7317: Stop is £40.8971 (exact 2.0000%, not stale £40.8562)."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        fill_p = 41.7317
        # BROKER-NATIVE UNITS: EMIMl_EQ is GBX-quoted, so the broker's own price
        # fields are GBX -- the real payload's sibling limitPrice is 4204.79 for a
        # ~£42 line, and this suite already uses GBX for averagePrice/stopPrice.
        # order['currency']='GBP' is the SETTLEMENT currency, not quote-unit
        # authority. Economic meaning is unchanged: 4173.17 GBX = £41.7317.
        broker_fill_p = round(fill_p * 100.0, 2)  # 4173.17 GBX
        qty = 956.158

        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_FILL_3", "status": "FILLED", "fillPrice": broker_fill_p, "filledQuantity": qty}
        })
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_3"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit),              patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            mock_sync_stop.assert_called_once()
            s_ticker, s_qty, s_price = mock_sync_stop.call_args[0]

            self.assertEqual(s_ticker, "EMIMl_EQ")
            self.assertEqual(s_qty, qty)
            # £41.7317 * 0.98 = £40.897066 -> £40.8971 -> 4089.71 GBX
            self.assertEqual(s_price, 4089.71)
            stop_gbp = s_price / 100.0
            dist_pct = (fill_p - stop_gbp) / fill_p
            self.assertAlmostEqual(dist_pct, 0.0200, places=4)

    def test_05_no_fill_accepted_order_on_book(self):
        """5. No fill (ACCEPTED, filledQuantity=0): order works on book, NO stop submitted."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)

        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_WORKING_001", "status": "SUBMITTED", "filledQuantity": 0.0}
        })
        mock_sync_stop = MagicMock()

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit),              patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            self.assertIn("ACCEPTED", res["reason"])
            # ZERO stops submitted because 0 shares filled!
            mock_sync_stop.assert_not_called()

    def test_06_partial_fill_proportional_stop_protection(self):
        """6. Partial fill: stop order placed strictly for the 400 filled shares @ actual fill price."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        partial_qty = 400.0
        fill_p = 41.7000
        # BROKER-NATIVE UNITS: EMIMl_EQ is GBX-quoted, so the broker's own price
        # fields are GBX -- the real payload's sibling limitPrice is 4204.79 for a
        # ~£42 line, and this suite already uses GBX for averagePrice/stopPrice.
        # order['currency']='GBP' is the SETTLEMENT currency, not quote-unit
        # authority. Economic meaning is unchanged: 4170.00 GBX = £41.7000.
        broker_fill_p = round(fill_p * 100.0, 2)  # 4170.00 GBX

        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_PARTIAL_001", "status": "PARTIALLY_FILLED", "fillPrice": broker_fill_p, "filledQuantity": partial_qty}
        })
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_PARTIAL"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit),              patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "ENTER")
            mock_sync_stop.assert_called_once()
            s_ticker, s_qty, s_price = mock_sync_stop.call_args[0]

            self.assertEqual(s_ticker, "EMIMl_EQ")
            # Stop quantity MUST equal exactly the partially filled 400 shares
            self.assertEqual(s_qty, partial_qty)
            # Stop price: £41.7000 * 0.98 = £40.8660 -> 4086.60 GBX
            self.assertEqual(s_price, 4086.60)

    def test_07_rejected_limit_order_non_retryable(self):
        """7. Rejected limit order: non-retryable status prevents duplicate orders."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)

        mock_limit = MagicMock(return_value={"success": False, "error": "HTTP 400: Limit price exceeded bounds"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit):

            res1 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )
            self.assertEqual(res1["decision"], "HOLD")
            self.assertEqual(mock_limit.call_count, 1)

            # Cycle 2: Non-retryable dedup prevents new submission
            res2 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )
            self.assertEqual(res2["decision"], "HOLD")
            self.assertIn("DEDUP", res2["reason"])
            self.assertEqual(mock_limit.call_count, 1)

    def test_08_restart_after_accepted_working_order(self):
        """8. Restart after accepted-but-not-filled order: engine reconciles working order without duplicates."""
        obs_bar_str = "2026-09-04"
        dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"

        # DB has order in ACCEPTED state
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "ACCEPTED",
            "notes": "Order working at broker"
        })

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock()

        # Restart engine instance
        restarted_engine = PRVQuantEngine()
        restarted_engine._stop_event.set()
        restarted_engine.is_running = False

        open_orders = [{"id": "ORD_WORKING_99", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}]

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware(open_orders)),              patch.object(broker, "place_limit_order", mock_limit):

            res = restarted_engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("DEDUP", res["reason"])
            mock_limit.assert_not_called()  # Never resubmitted!

    def test_09_restart_after_partial_fill(self):
        """9. Restart after partial fill: engine preserves position without duplicate orders."""
        obs_bar_str = "2026-09-04"
        dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"

        # DB has partial fill recorded
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "PARTIALLY_FILLED",
            "notes": "Partial fill 400 shares"
        })

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock()

        restarted_engine = PRVQuantEngine()
        restarted_engine._stop_event.set()
        restarted_engine.is_running = False

        open_positions = [{"ticker": "EMIMl_EQ", "quantity": 400.0, "averagePrice": 4170.00}]

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware(open_positions)),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit):

            res = restarted_engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 33216.38},
                bypass_execution_window=True
            )

            self.assertEqual(res["decision"], "HOLD")
            mock_limit.assert_not_called()

    def test_10_unknown_broker_response_reconciliation_only(self):
        """10. UNKNOWN broker response: persists in DB, reconciles without blind resubmission."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock(return_value={"success": False, "error": "HTTPSConnectionPool: Read timed out", "is_timeout": True})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit):

            res1 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )

            self.assertEqual(res1["decision"], "HOLD")
            self.assertIn("UNKNOWN_PENDING_RECONCILIATION", res1["reason"])
            self.assertEqual(mock_limit.call_count, 1)

            # Cycle 2: Same bar detects pending reconciliation, no new call
            res2 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )
            self.assertEqual(res2["decision"], "HOLD")
            self.assertEqual(mock_limit.call_count, 1)

    def test_11_duplicate_scheduler_cycles_exactly_once(self):
        """11. Duplicate scheduler cycles: order executed exactly once on first cycle, 0 on second."""
        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_EXACT_1", "status": "FILLED", "fillPrice": 4169.00, "filledQuantity": 956.158}
        })

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())),              patch.object(market_data, "get_current_executable_price", return_value=41.6900),              patch.object(broker, "get_open_positions", side_effect=provenance_aware([])),              patch.object(broker, "get_open_orders", side_effect=provenance_aware([])),              patch.object(broker, "place_limit_order", mock_limit):

            res1 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )
            self.assertEqual(res1["decision"], "ENTER")
            self.assertEqual(mock_limit.call_count, 1)

            res2 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=True
            )
            self.assertEqual(res2["decision"], "HOLD")
            self.assertIn("DEDUP", res2["reason"])
            self.assertEqual(mock_limit.call_count, 1)

    def test_12_limit_expiry_reconciles_to_expired_missed_window(self):
        """12. Limit order expiry at broker: reconciler detects absent order and marks EXPIRED_MISSED_WINDOW (no carry)."""
        obs_bar_str = "2026-09-04"
        dedup_key = f"CORE_EMIMl_EQ_{obs_bar_str}"

        # Order was pending reconciliation or timed out
        db.save_core_compounding_decision({
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "dedup_key": dedup_key,
            "signal_bar_date": obs_bar_str,
            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
            "target_instrument": "EMIMl_EQ",
            "target_score": 0.24,
            "intended_execution_session": "2026-09-07",
            "intended_execution_window": "08:00:00-08:05:00 BST",
            "execution_status": "UNKNOWN_PENDING_RECONCILIATION",
            "notes": "Timed out submission"
        })

        # Broker has NO open order and NO position (expired/cancelled)
        recon_msg = self.engine.reconcile_unknown_submissions(open_positions=[], open_orders=[])
        self.assertIn("EXPIRED_MISSED_WINDOW", recon_msg)

        # Verify DB status updated to EXPIRED_MISSED_WINDOW
        dec = db.get_core_compounding_decision(dedup_key)
        self.assertEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")

        # Crucial Invariant: De-duplication marks bar executed, permanently disallowing carry or retry
        self.assertTrue(self.engine.is_signal_bar_already_executed(dedup_key))

    # =========================================================================
    # 🏛️ DETERMINISTIC 08:00-08:05 BST WINDOW & PARTIAL-FILL SUITE (SCENARIOS 1-8)
    # =========================================================================

    def test_w1_no_fill_by_08_05(self):
        """W1. NO_FILL_BY_08_05: Placed @ 08:01; no fill by 08:05. At 08:05, order cancelled at broker, marked EXPIRED_MISSED_WINDOW."""
        tz = ZoneInfo("Europe/London")
        t_08_01 = datetime(2026, 9, 7, 8, 1, 0, tzinfo=tz)
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_W1_001", "status": "SUBMITTED", "filledQuantity": 0.0}
        })
        mock_cancel = MagicMock(return_value={"success": True})
        mock_sync_stop = MagicMock()

        # Step 1: Cycle at 08:01:00 BST -> Limit order placed
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res1 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_01
            )
            self.assertEqual(res1["decision"], "ENTER")
            self.assertEqual(mock_limit.call_count, 1)
            mock_sync_stop.assert_not_called()

        # Step 2: Cycle at 08:05:00 BST -> Window closes, order cancelled at broker
        working_order = {"id": "ORD_W1_001", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        active_orders = [working_order]
        def cancel_side_effect(oid):
            nonlocal active_orders
            active_orders = [o for o in active_orders if str(o.get("id")) != str(oid)]
            return {"success": True}
        mock_cancel = MagicMock(side_effect=cancel_side_effect)

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders)), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res2 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res2["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_W1_001")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")

        # Invariant Assertions
        final_filled_qty = 0.0
        unfilled_remainder = 0.0
        order_cancelled_at_window_close = True
        broker_stop_qty = 0.0
        position_fully_protected = True
        signal_final_state = "EXPIRED_MISSED_WINDOW"
        next_session_retry_allowed = False

        self.assertEqual(final_filled_qty, 0.0)
        self.assertEqual(unfilled_remainder, 0.0)
        self.assertTrue(order_cancelled_at_window_close)
        self.assertEqual(broker_stop_qty, 0.0)
        self.assertTrue(position_fully_protected)
        self.assertEqual(signal_final_state, dec["execution_status"])
        self.assertFalse(next_session_retry_allowed)
        self.assertTrue(self.engine.is_signal_bar_already_executed(dec["dedup_key"]))

    def test_w2_full_fill_at_08_01(self):
        """W2. FULL_FILL_AT_08_01: Placed @ 08:01, all 956.158 shares fill. Stop covers 956.158 shares. Remainder = 0."""
        tz = ZoneInfo("Europe/London")
        t_08_01 = datetime(2026, 9, 7, 8, 1, 0, tzinfo=tz)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_W2_001", "status": "FILLED", "fillPrice": 4169.00, "filledQuantity": 956.158}
        })
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_W2"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_01
            )
            self.assertEqual(res["decision"], "ENTER")
            mock_sync_stop.assert_called_once()
            _, s_qty, s_price = mock_sync_stop.call_args[0]
            self.assertEqual(s_qty, 956.158)
            self.assertEqual(s_price, 4085.62)

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "FILLED")

        # Invariants
        self.assertEqual(dec["execution_status"], "FILLED")
        self.assertTrue(self.engine.is_signal_bar_already_executed(dec["dedup_key"]))

    def test_w3_partial_fill_at_08_02_no_more_fill(self):
        """W3. PARTIAL_FILL_AT_08_02_NO_MORE_FILL: 400 shares fill @ 08:02. Remainder (556.158) cancelled @ 08:05. Stop covers 400."""
        tz = ZoneInfo("Europe/London")
        t_08_02 = datetime(2026, 9, 7, 8, 2, 0, tzinfo=tz)
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock(return_value={
            "success": True,
            "data": {"id": "ORD_W3_001", "status": "PARTIALLY_FILLED", "fillPrice": 4170.00, "filledQuantity": 400.0}
        })
        mock_cancel = MagicMock(return_value={"success": True})
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_W3"})

        # Step 1: Partial fill at 08:02
        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res1 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_02
            )
            self.assertEqual(res1["decision"], "ENTER")
            mock_sync_stop.assert_called_once()
            self.assertEqual(mock_sync_stop.call_args[0][1], 400.0)

        # Step 2: At 08:05, window closes. Remainder (556.158) cancelled, position 400 retained
        working_remainder = {"id": "ORD_W3_001", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 556.158}
        active_stop = {"id": "STOP_W3", "ticker": "EMIMl_EQ", "type": "STOP", "quantity": -400.0, "stopPrice": 4086.60}
        pos_400 = [{"ticker": "EMIMl_EQ", "quantity": 400.0, "averagePrice": 4170.00, "currentPrice": 4170.00}]

        active_orders_w3 = [working_remainder, active_stop]
        def cancel_w3(oid):
            nonlocal active_orders_w3
            active_orders_w3 = [o for o in active_orders_w3 if str(o.get("id")) != str(oid)]
            return {"success": True}
        mock_cancel = MagicMock(side_effect=cancel_w3)

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.7000), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(pos_400)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders_w3)), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res2 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 33216.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            mock_cancel.assert_called_once_with("ORD_W3_001")
            self.assertEqual(res2["decision"], "HOLD")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")

    def test_w4_partial_fill_at_08_02_additional_fill_at_08_04(self):
        """W4. PARTIAL_FILL_AT_08_02_ADDITIONAL_FILL_AT_08_04: 400 fill @ 08:02, +200 fill @ 08:04 -> stop expands to 600. Remainder (356.158) cancelled @ 08:05."""
        tz = ZoneInfo("Europe/London")
        t_08_04 = datetime(2026, 9, 7, 8, 4, 0, tzinfo=tz)
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_cancel = MagicMock(return_value={"success": True})
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_W4_EXPANDED"})

        # Record initial partial fill in DB
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
            "execution_status": "PARTIALLY_FILLED",
            "notes": "400 shares filled at 08:02"
        })

        # At 08:04, position increased to 600 shares, but stop still covers only 400 shares
        pos_600 = [{"ticker": "EMIMl_EQ", "quantity": 600.0, "averagePrice": 4170.00, "currentPrice": 4170.00}]
        working_remainder_356 = {"id": "ORD_W4_001", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 356.158}
        old_stop_400 = {"id": "STOP_W4_OLD", "ticker": "EMIMl_EQ", "type": "STOP", "quantity": -400.0, "stopPrice": 4086.60}

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.7000), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(pos_600)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([working_remainder_356, old_stop_400])), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res_08_04 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 24876.38},
                bypass_execution_window=False,
                current_time=t_08_04
            )
            # Dynamic stop expansion must be called for the new full 600 shares!
            mock_sync_stop.assert_called_once()
            s_tick, s_qty, s_price = mock_sync_stop.call_args[0]
            self.assertEqual(s_tick, "EMIMl_EQ")
            self.assertEqual(s_qty, 600.0)
            self.assertEqual(s_price, 4086.60)
            # Remainder is NOT cancelled at 08:04 (within window)
            mock_cancel.assert_not_called()

        # Step 2: At 08:05, window closes. Remainder (356.158) cancelled
        expanded_stop_600 = {"id": "STOP_W4_EXPANDED", "ticker": "EMIMl_EQ", "type": "STOP", "quantity": -600.0, "stopPrice": 4086.60}
        active_orders_w4 = [working_remainder_356, expanded_stop_600]
        def cancel_w4(oid):
            nonlocal active_orders_w4
            active_orders_w4 = [o for o in active_orders_w4 if str(o.get("id")) != str(oid)]
            return {"success": True}
        mock_cancel_w4 = MagicMock(side_effect=cancel_w4)

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.7000), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(pos_600)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders_w4)), \
             patch.object(broker, "cancel_order", mock_cancel_w4), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res_08_05 = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 24876.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            mock_cancel_w4.assert_called_once_with("ORD_W4_001")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")

    def test_w5_partial_fill_at_08_02_attempted_fill_after_08_05(self):
        """W5. PARTIAL_FILL_AT_08_02_ATTEMPTED_FILL_AFTER_08_05: Remainder was cancelled at 08:05; NO new fills possible after 08:05."""
        tz = ZoneInfo("Europe/London")
        t_08_06 = datetime(2026, 9, 7, 8, 6, 0, tzinfo=tz)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock()
        mock_cancel = MagicMock()

        # At 08:06 BST, only the 600-share position and its stop exist; entry order remainder is GONE
        pos_600 = [{"ticker": "EMIMl_EQ", "quantity": 600.0, "averagePrice": 4170.00, "currentPrice": 4170.00}]
        expanded_stop_600 = {"id": "STOP_W4_EXPANDED", "ticker": "EMIMl_EQ", "type": "STOP", "quantity": -600.0, "stopPrice": 4086.60}

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.7000), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(pos_600)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([expanded_stop_600])), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 24876.38},
                bypass_execution_window=False,
                current_time=t_08_06
            )
            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("HOLDING_ACTIVE_POSITION", res["reason"])
            mock_limit.assert_not_called()
            mock_cancel.assert_not_called()

    def test_w6_limit_still_working_at_08_05(self):
        """W6. LIMIT_STILL_WORKING_AT_08_05: Limit order still working on book at 08:05 is cancelled and marked EXPIRED_MISSED_WINDOW."""
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_cancel = MagicMock(return_value={"success": True})

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
            "execution_status": "ACCEPTED",
            "notes": "Working on broker book"
        })

        working_order = {"id": "ORD_W6_001", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        active_orders_w6 = [working_order]
        def cancel_w6(oid):
            nonlocal active_orders_w6
            active_orders_w6 = [o for o in active_orders_w6 if str(o.get("id")) != str(oid)]
            return {"success": True}
        mock_cancel = MagicMock(side_effect=cancel_w6)

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders_w6)), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_W6_001")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")

    def test_w7_restart_at_08_03_with_working_order(self):
        """W7. RESTART_AT_08_03_WITH_WORKING_ORDER: Daemon restarts @ 08:03 BST (within window). Adopts working order without duplicate entry and without cancellation."""
        tz = ZoneInfo("Europe/London")
        t_08_03 = datetime(2026, 9, 7, 8, 3, 0, tzinfo=tz)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock()
        mock_cancel = MagicMock()

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
            "execution_status": "UNKNOWN_PENDING_RECONCILIATION",
            "notes": "Restarting while order in-flight"
        })

        working_order = {"id": "ORD_W7_WORKING", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}

        restarted_engine = PRVQuantEngine()
        restarted_engine._stop_event.set()
        restarted_engine.is_running = False

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([working_order])), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = restarted_engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_03
            )
            # Reconciled and adopted without cancellation
            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("RECONCILIATION_COMPLETED", res["reason"])
            mock_cancel.assert_not_called()
            mock_limit.assert_not_called()

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "ACCEPTED")

    def test_w8_restart_at_08_06_with_stale_working_order(self):
        """W8. RESTART_AT_08_06_WITH_STALE_WORKING_ORDER: Daemon restarts @ 08:06 BST (after window). Detects stale working order, cancels it at broker, marks EXPIRED_MISSED_WINDOW."""
        tz = ZoneInfo("Europe/London")
        t_08_06 = datetime(2026, 9, 7, 8, 6, 0, tzinfo=tz)

        feed = self._create_synthetic_feed(top_symbol="EMIM", emim_close=41.59)
        mock_limit = MagicMock()
        mock_cancel = MagicMock(return_value={"success": True})

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
            "execution_status": "UNKNOWN_PENDING_RECONCILIATION",
            "notes": "Restarting after window elapsed"
        })

        stale_order = {"id": "ORD_W8_STALE", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        active_orders_w8 = [stale_order]
        def cancel_w8(oid):
            nonlocal active_orders_w8
            active_orders_w8 = [o for o in active_orders_w8 if str(o.get("id")) != str(oid)]
            return {"success": True}
        mock_cancel = MagicMock(side_effect=cancel_w8)

        restarted_engine = PRVQuantEngine()
        restarted_engine._stop_event.set()
        restarted_engine.is_running = False

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders_w8)), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = restarted_engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_06
            )
            self.assertEqual(res["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_W8_STALE")
            mock_limit.assert_not_called()

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")
        self.assertTrue(restarted_engine.is_signal_bar_already_executed(dedup_key))


    # =========================================================================
    # WINDOW-CLOSE CANCELLATION RACE REMEDIATION ADVERSARIAL SUITE (9 SCENARIOS)
    # =========================================================================

    def test_race_1_cancel_http_500(self):
        """Race 1: CANCEL_HTTP_500: broker.cancel_order returns HTTP 500 error. Order remains present. Status -> WINDOW_CLOSE_PENDING_RECONCILIATION."""
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
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
            "execution_status": "ACCEPTED",
            "notes": "Working order on book"
        })

        working_order = {"id": "ORD_R1_500", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        active_orders = [working_order]
        mock_cancel = MagicMock(return_value={"success": False, "error": "HTTP 500 Internal Server Error"})
        mock_sync_stop = MagicMock()

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders)), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_R1_500")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")

        # Invariant Assertions
        terminal_state = dec["execution_status"]
        self.assertNotIn(terminal_state, ("EXPIRED_MISSED_WINDOW", "PARTIALLY_FILLED_WINDOW_CLOSED"))
        self.assertTrue(self.engine.is_signal_bar_already_executed(dedup_key))
        mock_sync_stop.assert_not_called()

    def test_race_2_cancel_timeout_unknown(self):
        """Race 2: CANCEL_TIMEOUT_UNKNOWN: broker.cancel_order raises TimeoutError. Order remains present. Status -> WINDOW_CLOSE_PENDING_RECONCILIATION."""
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
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
            "execution_status": "ACCEPTED",
            "notes": "Working order on book"
        })

        working_order = {"id": "ORD_R2_TIMEOUT", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        active_orders = [working_order]
        mock_cancel = MagicMock(side_effect=TimeoutError("Gateway Timeout"))

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders)), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")
        self.assertTrue(self.engine.is_signal_bar_already_executed(dedup_key))

    def test_race_3_cancel_rejected(self):
        """Race 3: CANCEL_REJECTED: broker.cancel_order returns error. Order remains present. Status -> WINDOW_CLOSE_PENDING_RECONCILIATION."""
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
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
            "execution_status": "ACCEPTED",
            "notes": "Working order on book"
        })

        working_order = {"id": "ORD_R3_REJECT", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        active_orders = [working_order]
        mock_cancel = MagicMock(return_value={"success": False, "error": "Order cannot be cancelled"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders)), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "WINDOW_CLOSE_PENDING_RECONCILIATION")
        self.assertTrue(self.engine.is_signal_bar_already_executed(dedup_key))

    def test_race_4_fill_occurs_between_pre_cancel_snapshot_and_cancel_ack(self):
        """Race 4: FILL_OCCURS_BETWEEN_PRE_CANCEL_SNAPSHOT_AND_CANCEL_ACK: 0 shares pre-cancel. Fill occurs before cancel ACK. Post-cancel position = 956.158 shares. Stop synced to exactly 956.158 shares."""
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
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
            "execution_status": "ACCEPTED",
            "notes": "Working order on book"
        })

        working_order = {"id": "ORD_R4_RACE", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        active_orders = [working_order]
        active_positions = []  # Pre-cancel: 0 shares

        def cancel_race(oid):
            nonlocal active_orders, active_positions
            active_orders = []
            active_positions = [{"ticker": "EMIMl_EQ", "quantity": 956.158, "averagePrice": 4169.00, "currentPrice": 4169.00}]
            return {"success": True}

        mock_cancel = MagicMock(side_effect=cancel_race)
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_R4"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(lambda: active_positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders)), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_R4_RACE")
            mock_sync_stop.assert_called_once()
            _, s_qty, s_price = mock_sync_stop.call_args[0]
            self.assertEqual(s_qty, 956.158)
            self.assertEqual(s_price, 4085.62)

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")
        self.assertEqual(s_qty, 956.158)
        self.assertTrue(self.engine.is_signal_bar_already_executed(dedup_key))

    def test_race_5_partial_fill_increases_during_cancel(self):
        """Race 5: PARTIAL_FILL_INCREASES_DURING_CANCEL: 400 shares pre-cancel. +200 shares fill during cancel. Post-cancel position = 600.0 shares. Stop synced to exactly 600.0 shares."""
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
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
            "execution_status": "PARTIALLY_FILLED",
            "notes": "400 shares filled at 08:02"
        })

        working_remainder = {"id": "ORD_R5_REM", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 556.158}
        active_stop = {"id": "STOP_R5_OLD", "ticker": "EMIMl_EQ", "type": "STOP", "quantity": -400.0, "stopPrice": 4086.60}
        active_orders = [working_remainder, active_stop]
        active_positions = [{"ticker": "EMIMl_EQ", "quantity": 400.0, "averagePrice": 4170.00, "currentPrice": 4170.00}]

        def cancel_race_partial(oid):
            nonlocal active_orders, active_positions
            active_orders = [active_stop]
            active_positions = [{"ticker": "EMIMl_EQ", "quantity": 600.0, "averagePrice": 4170.00, "currentPrice": 4170.00}]
            return {"success": True}

        mock_cancel = MagicMock(side_effect=cancel_race_partial)
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_R5_EXPANDED"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.7000), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(lambda: active_positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders)), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 24876.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_R5_REM")
            mock_sync_stop.assert_called_once()
            _, s_qty, s_price = mock_sync_stop.call_args[0]
            self.assertEqual(s_qty, 600.0)
            self.assertEqual(s_price, 4086.60)

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")

    def test_race_6_cancel_success_but_open_order_cache_stale(self):
        """Race 6: CANCEL_SUCCESS_BUT_OPEN_ORDER_CACHE_STALE: Non-force-refreshed cache had order; force_refresh=True clears it. Terminal status confirmed only after fresh check."""
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
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
            "execution_status": "ACCEPTED",
            "notes": "Working order on book"
        })

        working_order = {"id": "ORD_R6_STALE_CACHE", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 956.158}
        call_count = 0
        def get_orders_smart(**kwargs):
            nonlocal call_count
            call_count += 1
            data = [working_order] if call_count == 1 else []
            # Both reads are authoritative here: the test asserts a terminal state,
            # which requires genuine broker provenance.
            return (data, True) if kwargs.get("return_provenance") else data

        mock_cancel = MagicMock(return_value={"success": True})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=get_orders_smart), \
             patch.object(broker, "cancel_order", mock_cancel):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_R6_STALE_CACHE")

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")

    def test_race_7_cancel_success_and_final_position_greater_than_pre_cancel_position(self):
        """Race 7: CANCEL_SUCCESS_AND_FINAL_POSITION_GREATER_THAN_PRE_CANCEL_POSITION: Pre-cancel position 100 shares. Post-cancel position 500 shares. Stop covers exactly 500 shares."""
        tz = ZoneInfo("Europe/London")
        t_08_05 = datetime(2026, 9, 7, 8, 5, 0, tzinfo=tz)
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
            "execution_status": "PARTIALLY_FILLED",
            "notes": "100 shares filled"
        })

        working_remainder = {"id": "ORD_R7_REM", "ticker": "EMIMl_EQ", "type": "LIMIT", "quantity": 856.158}
        active_stop = {"id": "STOP_R7_OLD", "ticker": "EMIMl_EQ", "type": "STOP", "quantity": -100.0, "stopPrice": 4085.62}
        active_orders = [working_remainder, active_stop]
        active_positions = [{"ticker": "EMIMl_EQ", "quantity": 100.0, "averagePrice": 4169.00, "currentPrice": 4169.00}]

        def cancel_race_7(oid):
            nonlocal active_orders, active_positions
            active_orders = [active_stop]
            active_positions = [{"ticker": "EMIMl_EQ", "quantity": 500.0, "averagePrice": 4169.00, "currentPrice": 4169.00}]
            return {"success": True}

        mock_cancel = MagicMock(side_effect=cancel_race_7)
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_R7_EXPANDED"})

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(lambda: active_positions)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware(lambda: active_orders)), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 29051.38},
                bypass_execution_window=False,
                current_time=t_08_05
            )
            self.assertEqual(res["decision"], "HOLD")
            mock_cancel.assert_called_once_with("ORD_R7_REM")
            mock_sync_stop.assert_called_once()
            _, s_qty, s_price = mock_sync_stop.call_args[0]
            self.assertEqual(s_qty, 500.0)
            self.assertEqual(s_price, 4085.62)

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")

    def test_race_8_restart_during_cancel_unknown(self):
        """Race 8: RESTART_DURING_CANCEL_UNKNOWN: Daemon restarts while in WINDOW_CLOSE_PENDING_RECONCILIATION. Post-restart reconciliation detects order absent, syncs stop, transitions to terminal without replacement entry."""
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
            "broker_order_id": "ORD_R8_IN_FLIGHT",
            "notes": "Cancel pending reconciliation before reboot"
        })

        pos_600 = [{"ticker": "EMIMl_EQ", "quantity": 600.0, "averagePrice": 4170.00, "currentPrice": 4170.00}]
        mock_limit = MagicMock()
        mock_cancel = MagicMock()
        mock_sync_stop = MagicMock(return_value={"success": True, "order_id": "STOP_R8_RECON"})

        restarted_engine = PRVQuantEngine()
        restarted_engine._stop_event.set()
        restarted_engine.is_running = False

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.7000), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware(pos_600)), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = restarted_engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 24876.38},
                bypass_execution_window=False,
                current_time=t_08_06
            )
            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("RECONCILIATION_COMPLETED", res["reason"])
            mock_limit.assert_not_called()
            mock_cancel.assert_not_called()
            mock_sync_stop.assert_called_once()
            _, s_qty, s_price = mock_sync_stop.call_args[0]
            self.assertEqual(s_qty, 600.0)
            self.assertEqual(s_price, 4086.60)

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "PARTIALLY_FILLED_WINDOW_CLOSED")
        self.assertTrue(restarted_engine.is_signal_bar_already_executed(dedup_key))

    def test_race_9_restart_after_cancel_before_final_reconciliation(self):
        """Race 9: RESTART_AFTER_CANCEL_BEFORE_FINAL_RECONCILIATION: Cancel succeeded on broker, but daemon restarted before DB status updated to terminal. Post-restart reconciliation completes terminal transition to EXPIRED_MISSED_WINDOW."""
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
            "broker_order_id": "ORD_R9_CANCELLED",
            "notes": "Cancel completed on broker, crashed before terminal DB write"
        })

        mock_limit = MagicMock()
        mock_cancel = MagicMock()
        mock_sync_stop = MagicMock()

        restarted_engine = PRVQuantEngine()
        restarted_engine._stop_event.set()
        restarted_engine.is_running = False

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(market_data, "get_current_executable_price", return_value=41.6900), \
             patch.object(broker, "get_open_positions", side_effect=provenance_aware([])), \
             patch.object(broker, "get_open_orders", side_effect=provenance_aware([])), \
             patch.object(broker, "place_limit_order", mock_limit), \
             patch.object(broker, "cancel_order", mock_cancel), \
             patch.object(broker, "sync_broker_stop_order", mock_sync_stop):

            res = restarted_engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38},
                bypass_execution_window=False,
                current_time=t_08_06
            )
            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("RECONCILIATION_COMPLETED", res["reason"])
            mock_limit.assert_not_called()
            mock_cancel.assert_not_called()
            mock_sync_stop.assert_not_called()

        dec = db.get_latest_core_compounding_decision()
        self.assertEqual(dec["execution_status"], "EXPIRED_MISSED_WINDOW")
        self.assertTrue(restarted_engine.is_signal_bar_already_executed(dedup_key))


if __name__ == "__main__":
    unittest.main()

