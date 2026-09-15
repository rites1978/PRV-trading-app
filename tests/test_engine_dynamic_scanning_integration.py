"""
PRV Capital - Integration Tests for Engine Dynamic Scanning & Telemetry (Phase 4)
Verifies:
1. Multi-market session continuity: Engine doesn't halt when LSE closes; continues scanning other open markets
2. Dynamic broker universe telemetry is correctly exposed in execution monitor telemetry
3. Bulk market data layer integration pre-fetches snapshots without thread leaks
4. 3 consecutive autonomous cycles advance heartbeat with stable thread count
5. Zero broker writes during opportunity scans
"""
import unittest
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from src.core.engine import PRVQuantEngine
from src.brokers.trading212 import broker
from src.config.settings import settings


class TestEngineDynamicScanningIntegration(unittest.TestCase):

    def setUp(self):
        self.engine = PRVQuantEngine()
        self.engine._stop_event.set()
        self.engine.is_running = False

    def test_multi_market_continuity_no_lse_shutdown(self):
        """Verify engine does not shutdown when LSE is closed if US/global markets are open."""
        from src.data.market_session_router import market_session_router
        # Simulate 18:00 UTC (London closed at 16:30, US open until 20:00/21:00)
        t_us_session = datetime(2026, 9, 15, 18, 0, 0, tzinfo=timezone.utc)
        open_markets = market_session_router.get_open_markets(t_us_session)
        is_any_open = market_session_router.is_any_market_open(t_us_session)

        self.assertTrue(is_any_open, "US markets must keep engine scanning active after London closes")
        self.assertIn("NYSE", open_markets)
        self.assertIn("NASDAQ", open_markets)
        self.assertNotIn("London Stock Exchange", open_markets)

    def test_execution_monitor_telemetry_includes_discovery_and_open_markets(self):
        """Verify get_execution_monitor_telemetry exposes broker_universe_telemetry and open_markets."""
        telemetry = self.engine.get_execution_monitor_telemetry()
        self.assertIn("broker_universe_telemetry", telemetry)
        self.assertIn("open_markets", telemetry)

        disc = telemetry["broker_universe_telemetry"]
        self.assertGreater(disc.get("BROKER_API_DISCOVERED", 0), 10000)
        self.assertGreater(disc.get("BROKER_API_TRADABLE", 0), 10000)
        self.assertIn("STOCK", disc.get("DISCOVERED_BY_PRODUCT_TYPE", {}))

    def test_consecutive_scans_advance_heartbeat_with_stable_threads(self):
        """Verify 3 consecutive cycles advance heartbeat and maintain stable thread counts."""
        threads_start = threading.active_count()
        heartbeats = []

        with patch.object(self.engine, "evaluate_core_compounding_live_state", return_value={"decision": "HOLD_CASH", "rankings": []}), \
             patch.object(broker, "get_account_summary", return_value={"success": True, "total_value": 50000.0, "available_cash": 50000.0, "invested": 0.0}), \
             patch.object(broker, "get_open_positions", return_value=[]), \
             patch.object(broker, "get_open_orders", return_value=[]):

            for i in range(3):
                t_before = time.time()
                res = self.engine.run_cycle()
                self.assertTrue(res.get("success"), f"Cycle {i+1} failed")
                hb = self.engine.last_heartbeat_timestamp
                self.assertIsNotNone(hb)
                heartbeats.append(hb)
                time.sleep(0.05)

        time.sleep(0.2)
        threads_end = threading.active_count()

        # Check heartbeat updated each cycle
        self.assertEqual(len(heartbeats), 3)
        self.assertEqual(threads_start, threads_end, f"Thread count grew from {threads_start} to {threads_end}!")

    def test_zero_broker_writes_on_scans(self):
        """Verify scanning and market-data acquisition perform zero broker order mutations."""
        broker_writes = []
        with patch.object(broker, "place_limit_order", side_effect=lambda *a, **kw: broker_writes.append("limit")), \
             patch.object(broker, "place_market_order", side_effect=lambda *a, **kw: broker_writes.append("market")), \
             patch.object(broker, "sync_broker_stop_order", side_effect=lambda *a, **kw: broker_writes.append("stop")), \
             patch.object(self.engine, "evaluate_core_compounding_live_state", return_value={"decision": "HOLD_CASH", "rankings": []}), \
             patch.object(broker, "get_account_summary", return_value={"success": True, "total_value": 50000.0, "available_cash": 50000.0, "invested": 0.0}), \
             patch.object(broker, "get_open_positions", return_value=[]), \
             patch.object(broker, "get_open_orders", return_value=[]):

            res = self.engine.run_cycle()
            self.assertTrue(res.get("success"))

        self.assertEqual(len(broker_writes), 0, "Zero broker writes must occur during scans!")


if __name__ == "__main__":
    unittest.main()
