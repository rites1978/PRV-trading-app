"""
PRV Capital - Production Bulk Market Data Layer
Provides high-throughput, bounded bulk market data acquisition for dynamic broker universes.

Features:
- Bounded batch chunking (e.g. 50 tickers per batch)
- Bounded ThreadPoolExecutor with strict context-manager lifecycle (zero thread leaks)
- Explicit network connect/read timeouts passed directly to requests
- In-memory rolling LRU cache with configurable TTL (default: 30 minutes)
- Immediate memory release: raw MultiIndex OHLCV DataFrames are dropped after scalar reduction
- Zero broker writes: pure analytical data feed
- Graceful degradation: individual ticker or batch network failures fail closed without crashing the scanner
"""
import time
import threading
import logging
from typing import Dict, List, Any, Optional, Union, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger("BulkMarketData")


class BulkMarketDataProvider:
    """Production bulk market data provider supporting multi-thousand instrument universes."""

    def __init__(
        self,
        batch_size: int = 50,
        max_workers: int = 5,
        request_timeout: float = 8.0,
        cache_ttl_seconds: float = 1800.0,
        max_cache_size: int = 2500,
    ):
        self.batch_size = max(1, batch_size)
        self.max_workers = max(1, max_workers)
        self.request_timeout = request_timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_size = max_cache_size

        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def clear_cache(self) -> None:
        """Clears all cached market snapshots."""
        with self._lock:
            self._cache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Returns cache telemetry."""
        with self._lock:
            return {
                "cache_entries": len(self._cache),
                "max_cache_size": self.max_cache_size,
                "ttl_seconds": self.cache_ttl_seconds,
            }

    @staticmethod
    def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Compute full quantitative technical indicators suite on a single OHLCV DataFrame."""
        if df.empty or len(df) < 15:
            return df

        data = df.copy()

        # 1. Moving Averages & Trend
        data["SMA_20"] = data["Close"].rolling(window=min(20, len(data))).mean()
        data["SMA_50"] = data["Close"].rolling(window=min(50, len(data))).mean()
        data["SMA_200"] = data["Close"].rolling(window=min(200, len(data))).mean()
        data["EMA_12"] = data["Close"].ewm(span=12, adjust=False).mean()
        data["EMA_26"] = data["Close"].ewm(span=26, adjust=False).mean()

        # 2. MACD (12, 26, 9)
        data["MACD"] = data["EMA_12"] - data["EMA_26"]
        data["MACD_Signal"] = data["MACD"].ewm(span=9, adjust=False).mean()
        data["MACD_Hist"] = data["MACD"] - data["MACD_Signal"]

        # 3. Relative Strength Index (RSI - 14)
        delta = data["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=min(14, len(data))).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=min(14, len(data))).mean()
        rs = gain / (loss + 1e-9)
        data["RSI"] = 100 - (100 / (1 + rs))

        # 4. Bollinger Bands (20 periods, 2 std dev)
        rolling_std = data["Close"].rolling(window=min(20, len(data))).std()
        data["BB_Middle"] = data["SMA_20"]
        data["BB_Upper"] = data["BB_Middle"] + (rolling_std * 2)
        data["BB_Lower"] = data["BB_Middle"] - (rolling_std * 2)
        data["BB_Width"] = (data["BB_Upper"] - data["BB_Lower"]) / data["BB_Middle"]

        # 5. Average True Range (ATR - 14) & Volatility
        high_low = data["High"] - data["Low"]
        high_close = (data["High"] - data["Close"].shift()).abs()
        low_close = (data["Low"] - data["Close"].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        data["ATR"] = ranges.max(axis=1).rolling(min(14, len(data))).mean()
        data["ATR_Pct"] = data["ATR"] / data["Close"]

        # 6. Volume Confirmation
        if "Volume" in data.columns:
            data["Vol_SMA_20"] = data["Volume"].rolling(window=min(20, len(data))).mean()
            data["Vol_Ratio"] = data["Volume"] / (data["Vol_SMA_20"] + 1e-9)

            # 7. On-Balance Volume (OBV)
            obv = [0]
            for i in range(1, len(data)):
                if data["Close"].iloc[i] > data["Close"].iloc[i - 1]:
                    obv.append(obv[-1] + data["Volume"].iloc[i])
                elif data["Close"].iloc[i] < data["Close"].iloc[i - 1]:
                    obv.append(obv[-1] - data["Volume"].iloc[i])
                else:
                    obv.append(obv[-1])
            data["OBV"] = obv
            data["OBV_SMA_20"] = (
                pd.Series(obv, index=data.index)
                .rolling(window=min(20, len(data)))
                .mean()
            )
        else:
            data["Vol_Ratio"] = 1.0
            data["OBV"] = 0
            data["OBV_SMA_20"] = 0

        return data

    @classmethod
    def _build_snapshot_from_df(
        cls,
        df: pd.DataFrame,
        t212_ticker: str,
        feed_ticker: str,
        is_uk_pence: bool = False,
    ) -> Dict[str, Any]:
        """Calculates scalar metrics and indicators, strictly releasing the raw DataFrame."""
        if df.empty or len(df) < 15:
            return {
                "success": False,
                "error": f"Insufficient historical data ({len(df)} bars found, 15 required)",
                "ticker": t212_ticker,
                "feed_ticker": feed_ticker,
                "current_price": 0.0,
                "raw_price": 0.0,
                "dataframe": pd.DataFrame(),
            }

        df_calc = cls.compute_technical_indicators(df)
        last = df_calc.iloc[-1]
        prev = df_calc.iloc[-2]

        current_price = float(last["Close"])
        if np.isnan(current_price) or current_price <= 0.0:
            return {
                "success": False,
                "error": f"Invalid market price ({current_price})",
                "ticker": t212_ticker,
                "feed_ticker": feed_ticker,
                "current_price": 0.0,
                "raw_price": 0.0,
                "dataframe": pd.DataFrame(),
            }

        unit_price = (current_price / 100.0) if is_uk_pence else current_price

        # 30-day return
        idx_30d = max(0, len(df_calc) - 21)
        base_30d = float(df_calc["Close"].iloc[idx_30d])
        return_30d = float((current_price - base_30d) / max(0.001, base_30d))

        # Volatility
        ret_series = df_calc["Close"].pct_change().dropna()
        daily_std = float(ret_series.std()) if len(ret_series) > 1 else 0.01
        annualized_vol = (
            float(daily_std * np.sqrt(252)) if not np.isnan(daily_std) else 0.20
        )
        recent_returns = [round(float(r), 5) for r in ret_series.tail(30).tolist()]

        last_bar_date = (
            df_calc.index[-1].strftime("%Y-%m-%d")
            if hasattr(df_calc.index[-1], "strftime")
            else str(df_calc.index[-1])[:10]
        )

        return {
            "success": True,
            "ticker": t212_ticker,
            "feed_ticker": feed_ticker,
            "current_price": unit_price,
            "raw_price": current_price,
            "daily_return": (current_price - float(prev["Close"]))
            / max(0.001, float(prev["Close"])),
            "last_bar_date": last_bar_date,
            "indicators": {
                "rsi": float(last["RSI"]) if not pd.isna(last["RSI"]) else 50.0,
                "sma_20": (float(last["SMA_20"]) / 100.0)
                if is_uk_pence
                else float(last["SMA_20"]),
                "sma_50": (float(last["SMA_50"]) / 100.0)
                if is_uk_pence
                else float(last["SMA_50"]),
                "sma_200": (float(last["SMA_200"]) / 100.0)
                if is_uk_pence
                else float(last["SMA_200"]),
                "macd": float(last["MACD"]) if not pd.isna(last["MACD"]) else 0.0,
                "macd_signal": float(last["MACD_Signal"])
                if not pd.isna(last["MACD_Signal"])
                else 0.0,
                "macd_hist": float(last["MACD_Hist"])
                if not pd.isna(last["MACD_Hist"])
                else 0.0,
                "bb_upper": (float(last["BB_Upper"]) / 100.0)
                if is_uk_pence
                else float(last["BB_Upper"]),
                "bb_lower": (float(last["BB_Lower"]) / 100.0)
                if is_uk_pence
                else float(last["BB_Lower"]),
                "bb_width": float(last["BB_Width"])
                if not pd.isna(last["BB_Width"])
                else 0.04,
                "atr": (float(last["ATR"]) / 100.0)
                if is_uk_pence
                else float(last["ATR"]),
                "atr_pct": float(last["ATR_Pct"])
                if not pd.isna(last["ATR_Pct"])
                else 0.02,
                "vol_ratio": float(last["Vol_Ratio"])
                if not pd.isna(last["Vol_Ratio"])
                else 1.0,
                "obv_trending_up": bool(last["OBV"] > last["OBV_SMA_20"])
                if ("OBV" in last and "OBV_SMA_20" in last)
                else True,
                "return_30d": return_30d,
                "annualized_vol": annualized_vol,
            },
            "recent_returns": recent_returns,
            "dataframe": pd.DataFrame(),  # Strictly discard raw DataFrame memory
        }

    def _extract_ticker_df_from_batch(
        self, batch_df: pd.DataFrame, feed_ticker: str
    ) -> pd.DataFrame:
        """Robustly extracts single-ticker OHLCV from yf.download result."""
        if batch_df.empty:
            return pd.DataFrame()

        if isinstance(batch_df.columns, pd.MultiIndex):
            levels = batch_df.columns.levels
            if len(levels) >= 2:
                if feed_ticker in levels[0]:
                    sub = batch_df[feed_ticker]
                    return sub.dropna(subset=["Close"]) if "Close" in sub.columns else pd.DataFrame()
                elif feed_ticker in levels[1]:
                    sub = batch_df.xs(feed_ticker, axis=1, level=1)
                    return sub.dropna(subset=["Close"]) if "Close" in sub.columns else pd.DataFrame()

            for val in batch_df.columns.get_level_values(0).unique():
                if str(val).upper() == feed_ticker.upper():
                    sub = batch_df[val]
                    return sub.dropna(subset=["Close"]) if "Close" in sub.columns else pd.DataFrame()
            return pd.DataFrame()
        else:
            return batch_df.dropna(subset=["Close"]) if "Close" in batch_df.columns else pd.DataFrame()

    def _process_chunk(
        self,
        chunk_items: List[Dict[str, Any]],
        timeout: float,
    ) -> Dict[str, Dict[str, Any]]:
        """Downloads and processes a single batch of tickers."""
        chunk_results = {}
        feed_to_item = {item["feed_ticker"]: item for item in chunk_items}
        feed_tickers = list(feed_to_item.keys())

        try:
            batch_df = yf.download(
                feed_tickers,
                period="6mo",
                interval="1d",
                group_by="ticker",
                timeout=timeout,
                progress=False,
                threads=False,
            )

            now = time.time()
            for feed_ticker, item in feed_to_item.items():
                t212_ticker = item.get("ticker", feed_ticker)
                is_uk_pence = bool(item.get("is_uk_pence", False))

                try:
                    sub_df = self._extract_ticker_df_from_batch(batch_df, feed_ticker)
                    snap = self._build_snapshot_from_df(
                        sub_df, t212_ticker, feed_ticker, is_uk_pence
                    )
                except Exception as ex:
                    snap = {
                        "success": False,
                        "error": f"Processing exception for {feed_ticker}: {ex}",
                        "ticker": t212_ticker,
                        "feed_ticker": feed_ticker,
                        "current_price": 0.0,
                        "raw_price": 0.0,
                        "dataframe": pd.DataFrame(),
                    }

                chunk_results[t212_ticker] = snap

                if snap.get("success"):
                    cache_key = f"{t212_ticker}_{is_uk_pence}"
                    with self._lock:
                        if len(self._cache) >= self.max_cache_size:
                            oldest = min(self._cache, key=lambda k: self._cache[k][0])
                            del self._cache[oldest]
                        self._cache[cache_key] = (now, snap)

        except Exception as e:
            logger.warning(f"Batch download failed for chunk of {len(feed_tickers)} tickers: {e}")
            for feed_ticker, item in feed_to_item.items():
                t212_ticker = item.get("ticker", feed_ticker)
                chunk_results[t212_ticker] = {
                    "success": False,
                    "error": f"Batch download error: {e}",
                    "ticker": t212_ticker,
                    "feed_ticker": feed_ticker,
                    "current_price": 0.0,
                    "raw_price": 0.0,
                    "dataframe": pd.DataFrame(),
                }

        return chunk_results

    def fetch_bulk_snapshots(
        self,
        instruments: List[Union[Dict[str, Any], str]],
        batch_size: Optional[int] = None,
        max_workers: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetches snapshots for a collection of instruments with bounded concurrency,
        strict thread cleanup, and rolling caching.
        """
        effective_batch_size = batch_size or self.batch_size
        effective_max_workers = max_workers or self.max_workers
        effective_timeout = timeout or self.request_timeout

        now = time.time()
        results: Dict[str, Dict[str, Any]] = {}
        items_to_fetch: List[Dict[str, Any]] = []

        with self._lock:
            for item in instruments:
                if isinstance(item, str):
                    t212_ticker = item
                    feed_ticker = item
                    is_uk_pence = False
                    normalized = {
                        "ticker": t212_ticker,
                        "feed_ticker": feed_ticker,
                        "is_uk_pence": is_uk_pence,
                    }
                elif isinstance(item, dict):
                    t212_ticker = item.get("ticker") or item.get("feed_ticker")
                    feed_ticker = item.get("feed_ticker") or item.get("shortName") or t212_ticker
                    is_uk_pence = bool(item.get("is_uk_pence", False))
                    normalized = {
                        "ticker": t212_ticker,
                        "feed_ticker": feed_ticker,
                        "is_uk_pence": is_uk_pence,
                    }
                else:
                    continue

                cache_key = f"{t212_ticker}_{is_uk_pence}"
                if cache_key in self._cache:
                    ts, cached_snap = self._cache[cache_key]
                    if (now - ts) < self.cache_ttl_seconds:
                        results[t212_ticker] = cached_snap
                        continue

                items_to_fetch.append(normalized)

        if not items_to_fetch:
            return results

        chunks = [
            items_to_fetch[i : i + effective_batch_size]
            for i in range(0, len(items_to_fetch), effective_batch_size)
        ]

        pool_size = min(effective_max_workers, len(chunks))
        with ThreadPoolExecutor(max_workers=pool_size) as executor:
            future_to_chunk = {
                executor.submit(self._process_chunk, chunk, effective_timeout): chunk
                for chunk in chunks
            }

            for future in as_completed(future_to_chunk):
                try:
                    chunk_res = future.result()
                    results.update(chunk_res)
                except Exception as ex:
                    chunk = future_to_chunk[future]
                    for item in chunk:
                        t212_t = item.get("ticker")
                        results[t212_t] = {
                            "success": False,
                            "error": f"Executor failure: {ex}",
                            "ticker": t212_t,
                            "feed_ticker": item.get("feed_ticker"),
                            "current_price": 0.0,
                            "raw_price": 0.0,
                            "dataframe": pd.DataFrame(),
                        }

        return results

    def get_market_snapshot(
        self,
        ticker_or_item: Union[str, Dict[str, Any]],
        is_uk_pence: bool = False,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Single-instrument interface delegating to bulk caching and fetcher."""
        res = self.fetch_bulk_snapshots([ticker_or_item], timeout=timeout)
        if isinstance(ticker_or_item, str):
            return res.get(ticker_or_item, {"success": False, "error": "Not found"})
        elif isinstance(ticker_or_item, dict):
            key = ticker_or_item.get("ticker") or ticker_or_item.get("feed_ticker")
            return res.get(key, {"success": False, "error": "Not found"})
        return {"success": False, "error": "Invalid instrument identifier"}


bulk_market_data = BulkMarketDataProvider()
