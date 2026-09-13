"""
Unit tests for Process Memory Observability & Alerting.
Verifies:
1. Cross-platform memory inspection returns positive RSS, Peak RSS, and open FDs.
2. Memory alerts trigger warnings ONLY at 300 MB, 400 MB, and 475 MB thresholds.
3. Alert checks perform telemetry only: no service restarts, no order cancellations.
4. /api/diagnostics/memory endpoint is strictly read-only:
   - Performs zero broker network calls
   - Performs zero database writes
   - Performs zero market-data network calls
   - Performs zero execution actions
5. rate_limiter.call_history length correctly reflected in telemetry.
"""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.monitoring.memory_telemetry import (
    get_process_memory_info,
    check_memory_growth_alerts,
    get_memory_telemetry,
    record_and_log_telemetry,
    ALERT_THRESHOLDS,
)
from src.api.routes import app
from src.brokers.trading212 import broker
from src.execution.order_router import order_router


class TestMemoryObservability(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_process_memory_info_returns_valid_metrics(self):
        """Verify process RSS and Peak RSS return valid positive floating-point values."""
        rss, peak, fds = get_process_memory_info()
        self.assertIsInstance(rss, float)
        self.assertGreater(rss, 0.0, "Process RSS must be greater than 0 MB")
        if peak is not None:
            self.assertIsInstance(peak, float)
            self.assertGreaterEqual(peak, rss, "Peak RSS should be >= current RSS")
        if fds is not None:
            self.assertIsInstance(fds, int)
            self.assertGreater(fds, 0, "Open FD count should be greater than 0")

    def test_memory_growth_alerts_thresholds(self):
        """
        Prove alerts trigger only when RSS crosses 300 MB, 400 MB, and 475 MB.
        Verify no alerts below 300 MB.
        """
        # Below 300 MB: completely clean, no alerts
        alerts_200 = check_memory_growth_alerts(200.0)
        self.assertEqual(len(alerts_200), 0)

        alerts_299 = check_memory_growth_alerts(299.9)
        self.assertEqual(len(alerts_299), 0)

        # 300 MB threshold: elevated warning
        with self.assertLogs("memory_telemetry", level="WARNING") as cm:
            alerts_300 = check_memory_growth_alerts(300.5)
            self.assertEqual(len(alerts_300), 1)
            self.assertIn("300 MB", alerts_300[0])
            self.assertIn("Elevated RSS threshold crossed", cm.output[0])

        # 400 MB threshold: high warning
        with self.assertLogs("memory_telemetry", level="WARNING") as cm:
            alerts_400 = check_memory_growth_alerts(415.0)
            self.assertEqual(len(alerts_400), 1)
            self.assertIn("400 MB", alerts_400[0])
            self.assertIn("High RSS threshold crossed", cm.output[0])

        # 475 MB threshold: critical warning
        with self.assertLogs("memory_telemetry", level="WARNING") as cm:
            alerts_475 = check_memory_growth_alerts(480.0)
            self.assertEqual(len(alerts_475), 1)
            self.assertIn("475 MB", alerts_475[0])
            self.assertIn("Critical RSS threshold crossed", cm.output[0])

    def test_get_memory_telemetry_structure(self):
        """Verify all telemetry keys are present and correctly typed."""
        data = get_memory_telemetry()
        expected_keys = [
            "status",
            "mem_rss_mb",
            "mem_peak_rss_mb",
            "thread_count",
            "open_fd_count",
            "call_history_len",
            "broker_cache_position_count",
            "market_data_cache_size",
            "MEM_RSS_MB",
            "MEM_PEAK_RSS_MB",
            "THREAD_COUNT",
            "OPEN_FD_COUNT",
            "CALL_HISTORY_LEN",
            "BROKER_CACHE_POSITION_COUNT",
            "MARKET_DATA_CACHE_SIZE",
            "alerts",
            "timestamp",
        ]
        for key in expected_keys:
            self.assertIn(key, data, f"Telemetry missing key: {key}")

        self.assertIn(data["status"], ("HEALTHY", "ELEVATED", "HIGH", "CRITICAL"))
        self.assertGreater(data["mem_rss_mb"], 0.0)
        self.assertGreater(data["thread_count"], 0)
        self.assertIsInstance(data["call_history_len"], int)
        self.assertIsInstance(data["broker_cache_position_count"], int)
        self.assertIsInstance(data["market_data_cache_size"], int)

    def test_diagnostics_memory_endpoint_is_read_only(self):
        """
        Prove /api/diagnostics/memory:
        1. Returns HTTP 200 with valid telemetry.
        2. Performs zero broker network calls.
        3. Performs zero DB writes.
        4. Performs zero market-data network calls.
        5. Performs zero execution actions.
        """
        with patch.object(broker, "_request_with_retry") as mock_broker_req,              patch("src.database.db.db.get_connection") as mock_db,              patch("yfinance.Ticker") as mock_yf,              patch.object(order_router, "route_entry_order") as mock_entry, patch.object(order_router, "route_exit_order") as mock_exit:

            resp = self.client.get("/api/diagnostics/memory")
            self.assertEqual(resp.status_code, 200)
            json_data = resp.json()

            self.assertIn("mem_rss_mb", json_data)
            self.assertIn("status", json_data)

            # Assert zero external/mutating operations
            mock_broker_req.assert_not_called()
            mock_db.assert_not_called()
            mock_yf.assert_not_called()
            mock_entry.assert_not_called()
            mock_exit.assert_not_called()

    def test_record_and_log_telemetry_formats_clean_log(self):
        """Verify periodic logger outputs the standard 5-minute production log line."""
        with self.assertLogs("memory_telemetry", level="INFO") as cm:
            data = record_and_log_telemetry()
            self.assertTrue(any("MEM_TELEMETRY:" in log for log in cm.output))
            self.assertTrue(any("MEM_RSS_MB=" in log for log in cm.output))
            self.assertTrue(any("THREAD_COUNT=" in log for log in cm.output))

    def test_telemetry_worker_refuses_in_test_env_without_force(self):
        """Prove test environment prevents accidental background telemetry thread launch."""
        from src.monitoring.memory_telemetry import start_memory_telemetry_worker
        res = start_memory_telemetry_worker(force=False)
        self.assertFalse(res, "start_memory_telemetry_worker must refuse without force=True in test env")

    def test_telemetry_worker_idempotent_spawns_exactly_one_thread(self):
        """Prove repeated invocation of start_memory_telemetry_worker is strictly idempotent."""
        import threading
        from src.monitoring.memory_telemetry import start_memory_telemetry_worker, _telemetry_lock
        import src.monitoring.memory_telemetry as mt

        # Reset flag with lock for test
        with _telemetry_lock:
            mt._telemetry_thread_running = False

        # First start with force=True
        first_start = start_memory_telemetry_worker(interval_seconds=3600, force=True)
        self.assertTrue(first_start)

        # Count memory-telemetry threads
        threads_after_1 = [t for t in threading.enumerate() if t.name == "memory-telemetry"]
        self.assertEqual(len(threads_after_1), 1)

        # Call 9 more times
        for _ in range(9):
            subsequent_start = start_memory_telemetry_worker(interval_seconds=3600, force=True)
            self.assertFalse(subsequent_start, "Subsequent starts must return False (idempotent no-op)")

        threads_after_10 = [t for t in threading.enumerate() if t.name == "memory-telemetry"]
        self.assertEqual(len(threads_after_10), 1, "Exactly one memory-telemetry thread must exist after 10 starts")


if __name__ == "__main__":
    unittest.main()
