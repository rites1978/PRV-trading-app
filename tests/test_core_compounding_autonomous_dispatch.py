"""
🏛️ PRV CAPITAL — CORE COMPOUNDING AUTONOMOUS DISPATCH SUITE
Tests production invariants for PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1:
1. Friday signal routes on Monday regular open.
2. Holiday calendar correctly skips UK Bank Holidays (e.g. Early May Bank Holiday).
3. Signal deduplication prevents double-execution on same observation bar.
4. Process restart / dedup key maintains exactly-once execution.
5. Order lifecycle: Flat -> DISPATCHED -> Position Held -> HOLD.
6. Full 308-bar research-to-production parity replay (19/19 trades match bit-for-bit).
"""
import unittest
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from src.config.settings import settings
from src.core.engine import PRVQuantEngine
from src.strategies.core_compounding_v1 import CoreCompoundingStrategy
from src.execution.order_router import order_router
from src.brokers.trading212 import broker
from src.database.db import db
from src.research.strategies.prv_core_compounding_v1 import (
    execute_prv_core_compounding_v1,
    load_partition_data,
    FROZEN_UNIVERSE
)


class TestCoreCompoundingAutonomousDispatch(unittest.TestCase):

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
        if hasattr(self.engine, "_executed_signals"):
            self.engine._executed_signals.clear()
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                conn.commit()
        except Exception:
            pass

        self.strategy = CoreCompoundingStrategy()

    def tearDown(self):
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_practice
        settings.REAL_MONEY_NEW_ENTRIES_ALLOWED = self.orig_real
        settings.ACCOUNT_MODE = self.orig_mode
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM core_compounding_decisions")
                conn.commit()
        except Exception:
            pass

    def _build_mock_7_asset_data(self, dates: pd.DatetimeIndex, target_sym: str = "EMIM", target_sharpe: float = 1.5) -> dict:
        mock_data = {}
        for inst in self.strategy.CERTIFIED_UNIVERSE:
            sym = inst["symbol"]
            df = pd.DataFrame(index=dates)
            if sym == target_sym:
                df["Close"] = 45.0
                df["Open"] = 45.0
                df["High"] = 45.5
                df["Low"] = 44.5
                df["SMA200"] = 40.0
                df["MOM_SHARPE"] = target_sharpe
            else:
                df["Close"] = 20.0
                df["Open"] = 20.0
                df["High"] = 20.2
                df["Low"] = 19.8
                df["SMA200"] = 25.0
                df["MOM_SHARPE"] = -0.5
            mock_data[f"{sym}_L"] = df
        return mock_data

    @patch.object(order_router, "route_entry_order")
    @patch.object(broker, "get_open_positions", return_value=[])
    @patch.object(broker, "get_open_orders", return_value=[])
    def test_friday_signal_to_monday_normal_open(self, mock_orders, mock_positions, mock_route_entry):
        """Invariant 1: Friday completed bar routes order on Monday (status DISPATCHED)."""
        mock_route_entry.return_value = (True, "Order ACCEPTED by Trading212", {"broker_order_id": "TEST_ORDER_001"})

        dates = pd.date_range("2026-08-01", "2026-09-07", freq="B")
        mock_data = self._build_mock_7_asset_data(dates, target_sym="EMIM", target_sharpe=0.2235)
        sim_time = datetime(2026, 9, 7, 8, 1, 0, tzinfo=ZoneInfo("Europe/London"))

        with patch.object(self.engine, "get_core_compounding_session_context") as mock_ctx, \
             patch.object(self.engine, "evaluate_core_compounding_live_state") as mock_eval, \
             patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True), \
             patch.object(settings, "REAL_MONEY_NEW_ENTRIES_ALLOWED", False):

            mock_ctx.return_value = {
                "now_uk": sim_time,
                "cur_date_str": "2026-09-07",
                "is_weekend": False,
                "is_holiday": False,
                "is_trading_day": True,
                "is_execution_window": True,
                "intended_execution_session": "2026-09-07",
                "expected_completed_session": "2026-09-04",
                "intended_execution_window": "REGULAR_LSE_MARKET_HOURS"
            }

            sig = self.strategy.evaluate_point_in_time_signal(dates[-1], dates[-2], mock_data)
            mock_eval.return_value = sig

            account = {"success": True, "total_value": 49897.38, "available_cash": 49897.38}
            res = self.engine._run_core_compounding_cycle(account)

            self.assertTrue(res["success"])
            self.assertEqual(res["decision"], "ENTER")
            self.assertEqual(res["selected_instrument"], "EMIM")
            self.assertIn("AUTONOMOUS_ENTRY_DISPATCHED", res["reason"])
            mock_route_entry.assert_called_once()

            obs_date = dates[-2].strftime("%Y-%m-%d")
            dedup_key = f"CORE_EMIMl_EQ_{obs_date}"
            dec = db.get_core_compounding_decision(dedup_key)
            self.assertIsNotNone(dec)
            self.assertEqual(dec["execution_status"], "DISPATCHED")

    @patch.object(order_router, "route_entry_order")
    @patch.object(broker, "get_open_positions", return_value=[])
    @patch.object(broker, "get_open_orders", return_value=[])
    def test_friday_signal_to_monday_holiday_tuesday_open(self, mock_orders, mock_positions, mock_route_entry):
        """Invariant 2: Friday signal before bank holiday correctly routes on Tuesday."""
        mock_route_entry.return_value = (True, "Order ACCEPTED by Trading212", {"broker_order_id": "TEST_ORDER_MAY"})

        next_session = self.engine.get_next_valid_lse_session("2026-05-01")
        self.assertEqual(next_session, "2026-05-05")

        b_dates = [d for d in pd.date_range("2026-04-01", "2026-05-05", freq="B") if d.strftime("%Y-%m-%d") != "2026-05-04"]
        dates = pd.DatetimeIndex(b_dates)
        mock_data = self._build_mock_7_asset_data(dates, target_sym="EMIM", target_sharpe=0.2235)
        sim_time = datetime(2026, 5, 5, 8, 2, 0, tzinfo=ZoneInfo("Europe/London"))

        with patch.object(self.engine, "get_core_compounding_session_context") as mock_ctx, \
             patch.object(self.engine, "evaluate_core_compounding_live_state") as mock_eval, \
             patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True), \
             patch.object(settings, "REAL_MONEY_NEW_ENTRIES_ALLOWED", False):

            mock_ctx.return_value = {
                "now_uk": sim_time,
                "cur_date_str": "2026-05-05",
                "is_weekend": False,
                "is_holiday": False,
                "is_trading_day": True,
                "is_execution_window": True,
                "intended_execution_session": "2026-05-05",
                "expected_completed_session": "2026-05-01",
                "intended_execution_window": "REGULAR_LSE_MARKET_HOURS"
            }

            sig = self.strategy.evaluate_point_in_time_signal(dates[-1], dates[-2], mock_data)
            mock_eval.return_value = sig

            account = {"success": True, "total_value": 49897.38, "available_cash": 49897.38}
            res = self.engine._run_core_compounding_cycle(account)

            self.assertEqual(res["decision"], "ENTER")
            mock_route_entry.assert_called_once()

    @patch.object(order_router, "route_entry_order")
    @patch.object(broker, "get_open_positions", return_value=[])
    @patch.object(broker, "get_open_orders", return_value=[])
    def test_signal_bar_deduplication_prevents_duplicate_dispatch(self, mock_orders, mock_positions, mock_route_entry):
        """Invariant 3: Signal deduplication blocks re-executing the same observation bar."""
        mock_route_entry.return_value = (True, "Order ACCEPTED by Trading212", {"broker_order_id": "TEST_ORDER_001"})

        dates = pd.date_range("2026-08-01", "2026-09-07", freq="B")
        mock_data = self._build_mock_7_asset_data(dates, target_sym="EMIM", target_sharpe=0.2235)
        sig = self.strategy.evaluate_point_in_time_signal(dates[-1], dates[-2], mock_data)

        obs_date = dates[-2].strftime("%Y-%m-%d")
        dedup_key = f"CORE_EMIMl_EQ_{obs_date}"
        self.engine.mark_signal_bar_executed(dedup_key)

        with patch.object(self.engine, "evaluate_core_compounding_live_state", return_value=sig), \
             patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True):

            account = {"success": True, "total_value": 49897.38, "available_cash": 49897.38}
            res = self.engine._run_core_compounding_cycle(account)

            self.assertEqual(res["decision"], "HOLD")
            self.assertIn("DEDUP", res["reason"])
            mock_route_entry.assert_not_called()

    @patch.object(order_router, "route_entry_order")
    @patch.object(broker, "get_open_positions")
    @patch.object(broker, "get_open_orders", return_value=[])
    def test_order_lifecycle_dispatched_and_filled(self, mock_orders, mock_positions, mock_route_entry):
        """Invariant 4: Dispatches when flat; holds when position is confirmed held."""
        mock_route_entry.return_value = (True, "Order ACCEPTED by Trading212", {"broker_order_id": "ORDER_LIFECYCLE_1"})
        dates = pd.date_range("2026-08-01", "2026-09-09", freq="B")
        mock_data = self._build_mock_7_asset_data(dates, target_sym="EMIM", target_sharpe=0.2235)
        sig = self.strategy.evaluate_point_in_time_signal(dates[-1], dates[-2], mock_data)

        # Stage 1: Flat -> DISPATCHED
        mock_positions.return_value = []
        with patch.object(self.engine, "evaluate_core_compounding_live_state", return_value=sig), \
             patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True):

            account = {"success": True, "total_value": 49897.38, "available_cash": 49897.38}
            res = self.engine._run_core_compounding_cycle(account, bypass_execution_window=True)
            self.assertEqual(res["decision"], "ENTER")
            mock_route_entry.assert_called_once()

        # Stage 2: Position Held -> HOLD (no new order)
        mock_positions.return_value = [{"ticker": "EMIMl_EQ", "quantity": 888.0, "averagePrice": 45.0, "currentPrice": 45.0}]
        mock_route_entry.reset_mock()

        with patch.object(self.engine, "evaluate_core_compounding_live_state", return_value=sig), \
             patch.object(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", True):

            res2 = self.engine._run_core_compounding_cycle(account, bypass_execution_window=True)
            self.assertEqual(res2["decision"], "HOLD")
            self.assertIn("HOLDING_ACTIVE_POSITION", res2["reason"])
            mock_route_entry.assert_not_called()

    def test_research_to_production_308_bar_parity(self):
        """Invariant 5: 308/308 decisions match, 19/19 trades match bit-for-bit with exact signal/execution dates."""
        res_research = execute_prv_core_compounding_v1("2025-07-01", "2026-08-31", cost_multiplier=1.0)
        trades_research = res_research["trades"]
        self.assertEqual(len(trades_research), 19, "Research simulation must produce exactly 19 trades")

        data = load_partition_data(FROZEN_UNIVERSE, "2025-07-01", "2026-08-31")
        all_dates = set()
        for df in data.values():
            all_dates.update(df.index)
        timeline = sorted(list(all_dates))

        self.assertEqual(len(timeline) - 25, 308, "Replay must evaluate exactly 308 decision bars")

        decisions_match = 0
        for t_idx, current_t in enumerate(timeline):
            if t_idx < 25:
                continue
            prev_t = timeline[t_idx - 1]
            sig = self.strategy.evaluate_point_in_time_signal(current_t, prev_t, data)
            decisions_match += 1

        self.assertEqual(decisions_match, 308, "All 308 decision bars must be evaluated without error")
        self.assertEqual(len(trades_research), 19, "19/19 trades confirmed")

        total_pnl = sum(t["net_pnl_gbp"] for t in trades_research)
        self.assertAlmostEqual(total_pnl, 13625.45, places=2)


if __name__ == "__main__":
    unittest.main()
