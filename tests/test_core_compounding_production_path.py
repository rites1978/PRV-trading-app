"""
🏛️ PRV CAPITAL — DETERMINISTIC PRODUCTION-PATH INTEGRATION TEST
Test Suite: tests/test_core_compounding_production_path.py

Verifies the real end-to-end production path:
  engine._run_core_compounding_cycle()
    -> evaluate_core_compounding_live_state()
    -> Net Edge Gate & Capital Reservation
    -> order_router.route_entry_order()
    -> broker.place_market_order() (final API boundary)

Acceptance Criteria:
1. Given a qualifying frozen signal during a valid execution condition:
   ROUTE_ENTRY_ORDER_CALL_COUNT = 1
2. Given no qualifying signal:
   ROUTE_ENTRY_ORDER_CALL_COUNT = 0
3. Given an existing position:
   ROUTE_ENTRY_ORDER_CALL_COUNT = 0
"""
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from src.config.settings import settings
from src.core.engine import PRVQuantEngine
from src.execution.order_router import order_router
from src.brokers.trading212 import broker
from src.data.market_data import market_data
from src.strategies.core_compounding_v1 import core_compounding_strategy


class TestCoreCompoundingProductionPath(unittest.TestCase):

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

        # Build synthetic 2-year daily history for all 7 ETFs
        self.dates = pd.date_range("2024-01-01", "2026-09-04", freq="B")

    def tearDown(self):
        settings.PRACTICE_NEW_ENTRIES_ALLOWED = self.orig_practice
        settings.REAL_MONEY_NEW_ENTRIES_ALLOWED = self.orig_real
        settings.ACCOUNT_MODE = self.orig_mode

    def _create_synthetic_feed(self, emim_qualifies: bool = True):
        feed = {}
        for inst in core_compounding_strategy.CERTIFIED_UNIVERSE:
            sym = inst["symbol"]
            yf_t = inst["yf_ticker"]
            n = len(self.dates)
            df = pd.DataFrame(index=self.dates)

            if sym == "EMIM" and emim_qualifies:
                # Upward trend: Close > SMA200, positive Sharpe momentum
                prices = 3000.0 + np.linspace(0, 1500.0, n) + np.sin(np.arange(n)) * 10
            elif sym == "EMIM" and not emim_qualifies:
                # Downward trend: Close < SMA200
                prices = 4500.0 - np.linspace(0, 2000.0, n)
            else:
                # Subdued or downward trend for other 6 instruments
                prices = 2000.0 - np.linspace(0, 500.0, n)

            df["Open"] = prices
            df["High"] = prices * 1.01
            df["Low"] = prices * 0.99
            df["Close"] = prices
            df["Volume"] = 100000
            feed[yf_t] = df
        return feed

    def test_1_qualifying_signal_routes_entry_order_exactly_once(self):
        """
        1. Given a qualifying frozen signal during a valid execution condition:
           ROUTE_ENTRY_ORDER_CALL_COUNT = 1
        """
        feed = self._create_synthetic_feed(emim_qualifies=True)

        mock_snap = {
            "account_summary": {"free_cash": 49896.38, "total_nav": 49896.38},
            "positions": []
        }

        import uuid
        test_order_id = f"PATH_TEST_{uuid.uuid4().hex[:8]}"

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", return_value=[]), \
             patch.object(broker, "get_open_orders", return_value=[]), \
             patch.object(broker, "place_market_order", return_value={"success": True, "data": {"id": test_order_id, "status": "FILLED", "fillPrice": 45.0}}) as mock_place_order, \
             patch.object(broker, "sync_broker_stop_order", return_value={"success": True, "action": "PLACED_NEW"}), \
             patch("src.execution.order_router.portfolio_snapshot.hydrate_once", return_value=mock_snap), \
             patch("src.execution.order_router.market_hours.is_asset_market_open", return_value=True), \
             patch.object(order_router, "route_entry_order", wraps=order_router.route_entry_order) as spy_route_order:

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38}
            )

            # Assert route_entry_order was called EXACTLY 1 time
            self.assertEqual(spy_route_order.call_count, 1, f"Expected route_entry_order call count 1, got {spy_route_order.call_count}")

            # Assert the engine decision is ENTER
            self.assertEqual(self.engine.last_decision, "ENTER")
            self.assertIn("AUTONOMOUS_ENTRY_DISPATCHED", self.engine.last_no_trade_reason)

            # Assert broker API boundary was called
            mock_place_order.assert_called_once()
            args, _ = mock_place_order.call_args
            self.assertEqual(args[0], "EMIMl_EQ")
            self.assertGreater(args[1], 0)

    def test_2_no_qualifying_signal_does_not_route_order(self):
        """
        2. Given no qualifying signal:
           ROUTE_ENTRY_ORDER_CALL_COUNT = 0
        """
        # All 7 ETFs in downtrend below 200 SMA
        feed = self._create_synthetic_feed(emim_qualifies=False)

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", return_value=[]), \
             patch.object(broker, "get_open_orders", return_value=[]), \
             patch.object(broker, "place_market_order") as mock_place_order, \
             patch.object(order_router, "route_entry_order", wraps=order_router.route_entry_order) as spy_route_order:

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 49896.38}
            )

            # Assert route_entry_order was called 0 times
            self.assertEqual(spy_route_order.call_count, 0, f"Expected route_entry_order call count 0, got {spy_route_order.call_count}")

            # Assert the engine decision is HOLD
            self.assertEqual(self.engine.last_decision, "HOLD")
            mock_place_order.assert_not_called()

    def test_3_existing_position_does_not_route_new_order(self):
        """
        3. Given an existing position:
           ROUTE_ENTRY_ORDER_CALL_COUNT = 0
        """
        feed = self._create_synthetic_feed(emim_qualifies=True)

        existing_pos = [{
            "ticker": "EMIMl_EQ",
            "quantity": 888.0,
            "averagePrice": 45.0,
            "currentPrice": 45.5
        }]

        with patch.object(market_data, "fetch_history", side_effect=lambda t, **kwargs: feed.get(t, pd.DataFrame())), \
             patch.object(broker, "get_open_positions", return_value=existing_pos), \
             patch.object(broker, "get_open_orders", return_value=[]), \
             patch.object(broker, "place_market_order") as mock_place_order, \
             patch.object(order_router, "route_entry_order", wraps=order_router.route_entry_order) as spy_route_order:

            res = self.engine._run_core_compounding_cycle(
                account={"total_value": 49896.38, "available_cash": 9896.38}
            )

            # Assert route_entry_order was called 0 times
            self.assertEqual(spy_route_order.call_count, 0, f"Expected route_entry_order call count 0, got {spy_route_order.call_count}")

            # Assert engine decision is HOLD (holding active position)
            self.assertEqual(self.engine.last_decision, "HOLD")
            self.assertIn("HOLDING_ACTIVE_POSITION", self.engine.last_no_trade_reason)
            mock_place_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
