"""
PRV Capital - Regression Test Suite for Fast Endpoints Latency & Non-Blocking Caching
Verifies:
1. Fast endpoints (/api/portfolio/summary_fast, /api/portfolio/positions, /api/integrity/broker_parity)
   do NOT invoke Yahoo Finance or Trading212 outbound network functions synchronously.
2. Empty or stale cache returns explicit state / last-verified fallback without blocking.
3. Raw index.html contains no hardcoded £50,000 account/portfolio placeholder values.
"""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import re
import os


class TestFastEndpointsLatencyAndCaching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.api.routes import app
        cls.client = TestClient(app)

    def test_fast_endpoints_do_not_invoke_yahoo_or_t212_network(self):
        """
        Enforces that /api/portfolio/summary_fast, /api/portfolio/positions, and
        /api/integrity/broker_parity never invoke outbound HTTP calls to Yahoo Finance or Trading212.
        """
        # Populate safe in-memory cache on broker so endpoints have warm memory
        from src.brokers.trading212 import broker
        broker._cached_summary = {
            "success": True,
            "total_value": 49980.0,
            "available_cash": 27000.0,
            "invested": 22980.0,
            "ppl": 20.0,
            "from_cache": True
        }
        broker._cached_positions = [
            {"ticker": "SLB_US_EQ", "quantity": 47.0, "averagePrice": 58.33, "currentPrice": 58.43, "ppl": 2.82}
        ]
        broker._cached_summary_time = 1e11
        broker._cached_positions_time = 1e11

        with patch("requests.get") as mock_get,              patch("requests.post") as mock_post,              patch("yfinance.Ticker") as mock_yf:

            mock_get.side_effect = AssertionError("Synchronous requests.get invoked inside fast endpoint!")
            mock_post.side_effect = AssertionError("Synchronous requests.post invoked inside fast endpoint!")
            mock_yf.side_effect = AssertionError("Synchronous yfinance.Ticker invoked inside fast endpoint!")

            # 1. /api/portfolio/summary_fast
            res_summary = self.client.get("/api/portfolio/summary_fast")
            self.assertEqual(res_summary.status_code, 200, f"summary_fast failed: {res_summary.text}")

            # 2. /api/portfolio/positions
            res_pos = self.client.get("/api/portfolio/positions")
            self.assertEqual(res_pos.status_code, 200, f"positions failed: {res_pos.text}")

            # 3. /api/integrity/broker_parity
            res_parity = self.client.get("/api/integrity/broker_parity")
            self.assertEqual(res_parity.status_code, 200, f"broker_parity failed: {res_parity.text}")

            self.assertFalse(mock_get.called)
            self.assertFalse(mock_post.called)
            self.assertFalse(mock_yf.called)

    def test_empty_or_stale_cache_returns_fallback_without_network_blocking(self):
        """
        Enforces that when broker caches are uninitialized or cold, fast endpoints
        return the fallback state cleanly rather than blocking on network calls.
        """
        from src.brokers.trading212 import broker
        broker._cached_summary = None
        broker._cached_positions = []
        broker._cached_summary_time = 0.0
        broker._cached_positions_time = 0.0

        with patch("requests.get") as mock_get,              patch("requests.post") as mock_post,              patch("yfinance.Ticker") as mock_yf:

            mock_get.side_effect = AssertionError("Synchronous requests.get invoked during cold cache!")
            mock_post.side_effect = AssertionError("Synchronous requests.post invoked during cold cache!")
            mock_yf.side_effect = AssertionError("Synchronous yfinance.Ticker invoked during cold cache!")

            res_summary = self.client.get("/api/portfolio/summary_fast")
            self.assertEqual(res_summary.status_code, 200)

            res_parity = self.client.get("/api/integrity/broker_parity")
            self.assertEqual(res_parity.status_code, 200)

    def test_raw_html_contains_no_hardcoded_50k_account_values(self):
        """
        Enforces that raw index.html contains no hardcoded £50,000 placeholder values
        in parity or active equity DOM cards.
        """
        html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        forbidden_patterns = [
            r'id="parityBrokerNav"[^>]*>£?50,?000(?:\.00)?<',
            r'id="parityApiNav"[^>]*>£?50,?000(?:\.00)?<',
            r'id="parityDashboardNav"[^>]*>£?50,?000(?:\.00)?<',
            r'id="objActiveEquity"[^>]*>£?50,?000(?:\.00)?<'
        ]

        for pattern in forbidden_patterns:
            matches = re.findall(pattern, content)
            self.assertEqual(len(matches), 0, f"Found forbidden hardcoded £50,000 value matching: {pattern}")


if __name__ == "__main__":
    unittest.main()
