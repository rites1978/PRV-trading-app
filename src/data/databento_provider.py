"""
PRV Capital - Authoritative Databento Market Data Provider
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Replaces yfinance for all CURRENT trading decision data:
1. Pure Databento SDK integration for live market quotes and decision-grade data.
2. Fails closed when DATABENTO_API_KEY is missing (no semantic fabrication, no Yahoo fallback).
3. Provides exact live quote fields: provider, instrument, timestamp, latest price, bid, ask, spread, freshness.
"""
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import pandas as pd

logger = logging.getLogger("databento_provider")

try:
    import databento as db
    DATABENTO_AVAILABLE = True
except ImportError:
    DATABENTO_AVAILABLE = False


class DatabentoMarketDataProvider:
    """Authoritative Databento provider for real-time market data."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        dataset: Optional[str] = None,
        timeout: float = 7.0
    ):
        self.api_key = api_key or os.getenv("DATABENTO_API_KEY")
        self.dataset = dataset or os.getenv("DATABENTO_DATASET", "DBEQ.BASIC")
        self.timeout = timeout
        self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip() and DATABENTO_AVAILABLE)

    def _get_client(self):
        if self._client is None and self.is_configured:
            self._client = db.Historical(key=self.api_key)
        return self._client

    def _fetch_from_sdk(self, symbol: str) -> Dict[str, Any]:
        """
        Executes real SDK timeseries call to Databento for latest quote.
        Uses recent historical window (e.g. last 30 minutes) on DBEQ.BASIC or XNAS.ITCH.
        """
        client = self._get_client()
        if client is None:
            raise RuntimeError("DATABENTO_CLIENT_UNINITIALISED")

        now = datetime.now(timezone.utc)
        # Fetch recent BBO or trades
        start_time = now - timedelta(hours=2)
        
        try:
            # First attempt BBO_1S schema for bid/ask/spread
            store = client.timeseries.get_range(
                dataset=self.dataset,
                symbols=[symbol],
                schema="bbo-1s",
                start=start_time.isoformat(),
                end=now.isoformat()
            )
            df = store.to_df()
        except Exception as e:
            logger.warning(f"[Databento] bbo-1s fetch failed for {symbol}: {e}. Retrying with trades schema.")
            store = client.timeseries.get_range(
                dataset=self.dataset,
                symbols=[symbol],
                schema="trades",
                start=start_time.isoformat(),
                end=now.isoformat()
            )
            df = store.to_df()

        if df.empty:
            raise ValueError(f"No recent data returned for {symbol} on dataset {self.dataset}")

        last_row = df.iloc[-1]
        ts_index = df.index[-1]
        
        if hasattr(ts_index, "isoformat"):
            ts_iso = ts_index.isoformat()
            ts_sec = ts_index.timestamp()
        else:
            ts_iso = now.isoformat()
            ts_sec = time.time()

        freshness = max(0.0, round(time.time() - ts_sec, 2))
        
        bid = float(last_row.get("bid_px_00")) if "bid_px_00" in last_row and not pd.isna(last_row["bid_px_00"]) else None
        ask = float(last_row.get("ask_px_00")) if "ask_px_00" in last_row and not pd.isna(last_row["ask_px_00"]) else None
        spread = round(ask - bid, 4) if (bid is not None and ask is not None) else None
        
        # Price: mid if bid/ask available, else trade price
        if "price" in last_row and not pd.isna(last_row["price"]):
            price = float(last_row["price"])
        elif bid and ask:
            price = round((bid + ask) / 2.0, 4)
        else:
            price = float(last_row.get("close", 0.0))

        return {
            "price": price,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "timestamp": ts_iso,
            "freshness_seconds": freshness
        }

    def get_current_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Authoritative current quote lookup.
        Never falls back to Yahoo/yfinance.
        """
        if not self.is_configured:
            return {
                "success": False,
                "status": "DATABENTO_API_KEY_MISSING",
                "provider": "DATABENTO",
                "instrument": symbol,
                "error": "DATABENTO_API_KEY environment variable is not configured"
            }

        try:
            sdk_res = self._fetch_from_sdk(symbol)
            return {
                "success": True,
                "status": "OK",
                "provider": "DATABENTO",
                "instrument": symbol,
                "latest_price": sdk_res["price"],
                "bid": sdk_res["bid"],
                "ask": sdk_res["ask"],
                "spread": sdk_res["spread"],
                "timestamp": sdk_res["timestamp"],
                "freshness_seconds": sdk_res["freshness_seconds"],
                "http_status": 200
            }
        except Exception as e:
            logger.error(f"[Databento Error] Quote fetch failed for {symbol}: {e}")
            return {
                "success": False,
                "status": "DATABENTO_FETCH_ERROR",
                "provider": "DATABENTO",
                "instrument": symbol,
                "error": str(e),
                "http_status": 500
            }

    def get_current_executable_price(self, symbol: str) -> Optional[float]:
        """
        Authoritative current executable price immediately before broker submission.
        Returns float price or None if unavailable.
        NEVER falls back to Yahoo for active decisions.
        """
        res = self.get_current_quote(symbol)
        if res.get("success") and res.get("latest_price", 0.0) > 0.0:
            return float(res["latest_price"])
        return None

    def fetch_live_bars(
        self,
        symbol: str,
        interval: str = "5m",
        n_bars: int = 30
    ) -> pd.DataFrame:
        """
        Fetches live bars from Databento OHLCV schema.
        Returns DataFrame with Open, High, Low, Close, Volume.
        """
        if not self.is_configured:
            return pd.DataFrame()

        client = self._get_client()
        if client is None:
            return pd.DataFrame()

        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=4)
        try:
            store = client.timeseries.get_range(
                dataset=self.dataset,
                symbols=[symbol],
                schema="ohlcv-1m",
                start=start_time.isoformat(),
                end=now.isoformat()
            )
            df = store.to_df()
            if df.empty:
                return pd.DataFrame()
            # Resample 1m to requested interval if needed
            if interval == "5m":
                resampled = df.resample("5min").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum"
                }).dropna()
                resampled.columns = ["Open", "High", "Low", "Close", "Volume"]
                return resampled.tail(n_bars)
            df.columns = [c.capitalize() for c in df.columns]
            return df.tail(n_bars)
        except Exception as e:
            logger.error(f"[Databento Error] Bar fetch failed for {symbol}: {e}")
            return pd.DataFrame()


databento_market_data_provider = DatabentoMarketDataProvider()
