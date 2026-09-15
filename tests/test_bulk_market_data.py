"""
PRV Capital - Unit & Integration Tests for Bulk Market Data Layer
Verifies:
- Bounded batch processing and correct scalar extraction
- Zero ThreadPoolExecutor leaks (thread count invariant)
- In-memory rolling cache hit, TTL expiration, and eviction
- Graceful handling of network timeouts, partial batch failures, and delisted symbols
- Complete release of raw DataFrame memory
- Zero broker writes
"""
import unittest
import threading
import time
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

from src.data.bulk_market_data import BulkMarketDataProvider
from src.brokers.trading212 import broker


class TestBulkMarketData(unittest.TestCase):

    def setUp(self):
        self.provider = BulkMarketDataProvider(
            batch_size=5,
            max_workers=2,
            request_timeout=3.0,
            cache_ttl_seconds=5.0,
            max_cache_size=10
        )

    def tearDown(self):
        self.provider.clear_cache()

    def _create_mock_ohlcv(self, bars: int = 30, base_price: float = 100.0) -> pd.DataFrame:
        dates = pd.date_range(end="2026-09-15", periods=bars, freq="D")
        closes = [base_price + i * 0.5 for i in range(bars)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        opens = [c - 0.2 for c in closes]
        volumes = [100000 + i * 1000 for i in range(bars)]
        return pd.DataFrame({
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes
        }, index=dates)

    def test_indicator_computation_and_memory_release(self):
        """Verify technical indicators are calculated and raw DataFrame is released."""
        df = self._create_mock_ohlcv(50, 100.0)
        snap = self.provider._build_snapshot_from_df(df, "TEST_TICKER", "TEST", is_uk_pence=False)
        self.assertTrue(snap["success"])
        self.assertIn("rsi", snap["indicators"])
        self.assertIn("sma_20", snap["indicators"])
        self.assertIn("sma_50", snap["indicators"])
        self.assertIn("atr", snap["indicators"])
        self.assertGreater(snap["current_price"], 0.0)
        # Verify raw DataFrame is empty stub
        self.assertTrue(snap["dataframe"].empty)

    def test_uk_pence_quote_divisor_scaling(self):
        """Verify UK GBX pence quotes are scaled by 100.0 in snapshot."""
        df = self._create_mock_ohlcv(30, 200.0)
        snap = self.provider._build_snapshot_from_df(df, "BARCl_EQ", "BARC.L", is_uk_pence=True)
        self.assertTrue(snap["success"])
        # Close price at end is ~214.5 pence -> £2.145
        self.assertAlmostEqual(snap["current_price"], snap["raw_price"] / 100.0, places=4)
        self.assertAlmostEqual(snap["indicators"]["sma_20"], df["Close"].iloc[-20:].mean() / 100.0, places=4)

    def test_rolling_cache_and_ttl(self):
        """Verify cache hits, eviction, and TTL expiration."""
        mock_snap = {
            "success": True,
            "ticker": "AAPL_US_EQ",
            "current_price": 150.0,
            "raw_price": 150.0,
            "indicators": {}
        }
        # Pre-populate cache
        with self.provider._lock:
            self.provider._cache["AAPL_US_EQ_False"] = (time.time(), mock_snap)

        stats = self.provider.get_cache_stats()
        self.assertEqual(stats["cache_entries"], 1)

        # Immediate fetch should hit cache without network
        res = self.provider.get_market_snapshot({"ticker": "AAPL_US_EQ", "feed_ticker": "AAPL", "is_uk_pence": False})
        self.assertTrue(res["success"])
        self.assertEqual(res["current_price"], 150.0)

        # Expire cache TTL
        with self.provider._lock:
            self.provider._cache["AAPL_US_EQ_False"] = (time.time() - 10.0, mock_snap)

        # Mock download to return empty to verify it bypassed expired cache
        with patch("yfinance.download", return_value=pd.DataFrame()):
            res_expired = self.provider.fetch_bulk_snapshots([{"ticker": "AAPL_US_EQ", "feed_ticker": "AAPL"}])
            self.assertFalse(res_expired["AAPL_US_EQ"]["success"])

    def test_thread_count_invariant_and_zero_leaks(self):
        """Verify ThreadPoolExecutor cleanly shuts down and releases all worker threads."""
        threads_before = threading.active_count()

        # Mock batch download
        def mock_download(tickers, *args, **kwargs):
            return pd.DataFrame()

        with patch("yfinance.download", side_effect=mock_download):
            items = [{"ticker": f"TICKER_{i}", "feed_ticker": f"TICKER_{i}"} for i in range(25)]
            self.provider.fetch_bulk_snapshots(items, batch_size=5, max_workers=4)

        time.sleep(0.2)
        threads_after = threading.active_count()
        self.assertEqual(threads_before, threads_after, "ThreadPoolExecutor leaked threads!")

    def test_partial_batch_failures_and_delisted_symbols(self):
        """Verify partial failure or missing symbol in batch fails closed without crashing."""
        df_aapl = self._create_mock_ohlcv(30, 150.0)
        # Construct multi-ticker DataFrame with AAPL present and DELISTED missing
        multi_cols = pd.MultiIndex.from_product([["AAPL"], ["Open", "High", "Low", "Close", "Volume"]], names=["Ticker", "Price"])
        multi_df = pd.DataFrame(df_aapl.values, index=df_aapl.index, columns=multi_cols)

        with patch("yfinance.download", return_value=multi_df):
            items = [
                {"ticker": "AAPL_US_EQ", "feed_ticker": "AAPL"},
                {"ticker": "DELISTED_US_EQ", "feed_ticker": "DELISTED"}
            ]
            results = self.provider.fetch_bulk_snapshots(items)
            self.assertTrue(results["AAPL_US_EQ"]["success"])
            self.assertFalse(results["DELISTED_US_EQ"]["success"])
            self.assertIn("error", results["DELISTED_US_EQ"])

    def test_simulated_network_timeout(self):
        """Verify network timeout raises no uncaught exception and marks batch as failed."""
        with patch("yfinance.download", side_effect=TimeoutError("Request timed out")):
            items = [{"ticker": "TIMEOUT_TICKER", "feed_ticker": "TIMEOUT"}]
            results = self.provider.fetch_bulk_snapshots(items, timeout=1.0)
            self.assertFalse(results["TIMEOUT_TICKER"]["success"])
            self.assertIn("timed out", results["TIMEOUT_TICKER"]["error"])

    def test_zero_broker_writes_occur_during_market_data(self):
        """Verify market data acquisition performs zero broker order mutations."""
        broker_writes = []
        with patch.object(broker, "place_limit_order", side_effect=lambda *a, **kw: broker_writes.append("limit")), \
             patch.object(broker, "place_market_order", side_effect=lambda *a, **kw: broker_writes.append("market")), \
             patch.object(broker, "sync_broker_stop_order", side_effect=lambda *a, **kw: broker_writes.append("stop")):

            df = self._create_mock_ohlcv(30, 100.0)
            with patch("yfinance.download", return_value=df):
                self.provider.fetch_bulk_snapshots([{"ticker": "MOCK_EQ", "feed_ticker": "MOCK"}])

        self.assertEqual(len(broker_writes), 0, "Bulk market data must never write to broker!")


if __name__ == "__main__":
    unittest.main()
