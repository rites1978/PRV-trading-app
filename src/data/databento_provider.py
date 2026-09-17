"""
PRV Capital - Authoritative Databento Market Data Provider
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Official Databento LIVE Client/Path for all CURRENT trading decision data:
1. Uses databento.Live for real-time live market quotes and decision bars.
2. Fails closed when DATABENTO_API_KEY is missing or Live connection fails:
   PRODUCT_FAILURE = DATABENTO_LIVE_DATA_UNAVAILABLE
3. Strictly requires BBO (schema="bbo-1s"): bid, ask, spread, timestamps, freshness.
4. ZERO Yahoo fallback for active decision data.
5. Historical data isolated strictly to separated warmup that cannot authorise orders.
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
    """Authoritative Databento provider using official Databento Live client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        dataset: Optional[str] = None,
        timeout: float = 7.0
    ):
        self.api_key = api_key or os.getenv("DATABENTO_API_KEY")
        self.dataset = dataset or os.getenv("DATABENTO_DATASET", "DBEQ.BASIC")
        self.timeout = timeout
        self.data_service: str = "LIVE"
        self.client_type: str = "Live"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip() and DATABENTO_AVAILABLE)

    def _get_live_client(self):
        """Returns official databento.Live client instance."""
        if not self.is_configured:
            return None
        return db.Live(key=self.api_key)

    def _fetch_from_live_sdk(self, symbol: str) -> Dict[str, Any]:
        """
        Executes real Live gateway subscription and record fetch via databento.Live.
        Strictly requires BBO data (schema="bbo-1s").
        Uses live intraday replay/stream from recent start time to get the latest executable quote.
        """
        if not self.is_configured:
            raise RuntimeError("DATABENTO_CLIENT_UNINITIALISED")

        fetch_time = time.time()
        fetch_ts_iso = datetime.now(timezone.utc).isoformat()
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=2)

        client = self._get_live_client()
        if client is None:
            raise RuntimeError("DATABENTO_CLIENT_UNINITIALISED")

        # Subscribe to Live Gateway for bbo-1s schema with intraday replay
        client.subscribe(
            dataset=self.dataset,
            schema="bbo-1s",
            symbols=[symbol],
            start=start_time
        )

        latest_record = None
        start_poll = time.time()

        # Iterate through live stream records
        try:
            for record in client:
                if hasattr(record, "bid_px_00") and hasattr(record, "ask_px_00"):
                    latest_record = record
                if (time.time() - start_poll) > self.timeout:
                    break
                if hasattr(client, "_session") and hasattr(client._session, "_dbn_queue"):
                    if client._session._dbn_queue.empty() and latest_record is not None:
                        break
        finally:
            try:
                client.terminate()
            except Exception:
                pass

        if latest_record is None:
            raise ValueError(
                f"No live BBO data returned for {symbol} on dataset {self.dataset}; "
                f"trades-only cannot be treated as an executable quote"
            )

        # Parse BBO fields
        bid = getattr(latest_record, "pretty_bid_px_00", None)
        if bid is None and hasattr(latest_record, "bid_px_00"):
            raw_bid = latest_record.bid_px_00
            if raw_bid not in (9223372036854775807, None, 0):
                bid = float(raw_bid) / 1e9
        elif bid is not None:
            try:
                bid = float(bid)
            except (ValueError, TypeError):
                bid = None

        ask = getattr(latest_record, "pretty_ask_px_00", None)
        if ask is None and hasattr(latest_record, "ask_px_00"):
            raw_ask = latest_record.ask_px_00
            if raw_ask not in (9223372036854775807, None, 0):
                ask = float(raw_ask) / 1e9
        elif ask is not None:
            try:
                ask = float(ask)
            except (ValueError, TypeError):
                ask = None

        if bid is None or ask is None:
            raise ValueError(f"Incomplete BBO for {symbol}: bid={bid}, ask={ask}")

        spread = round(ask - bid, 4)
        if spread <= 0.0:
            raise ValueError(f"Non-positive spread for {symbol}: bid={bid}, ask={ask}, spread={spread}")

        price = getattr(latest_record, "pretty_price", None)
        if price is None and hasattr(latest_record, "price"):
            raw_p = latest_record.price
            if raw_p not in (9223372036854775807, None, 0):
                price = float(raw_p) / 1e9
        elif price is not None:
            try:
                price = float(price)
            except (ValueError, TypeError):
                price = None

        if price is None:
            price = round((bid + ask) / 2.0, 4)

        # Timestamp & freshness
        ts_iso = None
        ts_sec = None
        if hasattr(latest_record, "pretty_ts_recv") and latest_record.pretty_ts_recv:
            ts_iso = str(latest_record.pretty_ts_recv)
        elif hasattr(latest_record, "pretty_ts_event") and latest_record.pretty_ts_event:
            ts_iso = str(latest_record.pretty_ts_event)
        elif hasattr(latest_record, "ts_event") and latest_record.ts_event:
            ts_sec = latest_record.ts_event / 1e9
            ts_iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
        elif hasattr(latest_record, "ts_recv") and latest_record.ts_recv:
            ts_sec = latest_record.ts_recv / 1e9
            ts_iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()

        if ts_sec is None:
            if ts_iso:
                try:
                    ts_sec = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts_sec = time.time()
            else:
                ts_sec = time.time()
                ts_iso = datetime.now(timezone.utc).isoformat()

        freshness = max(0.0, round(fetch_time - ts_sec, 2))

        raw_evidence = {
            "record_type": getattr(latest_record, "rtype", type(latest_record).__name__),
            "instrument_id": getattr(latest_record, "instrument_id", None),
            "bid_px_00": getattr(latest_record, "bid_px_00", None),
            "ask_px_00": getattr(latest_record, "ask_px_00", None),
            "pretty_bid_px_00": bid,
            "pretty_ask_px_00": ask,
            "ts_event": getattr(latest_record, "ts_event", None),
            "ts_recv": getattr(latest_record, "ts_recv", None),
        }

        return {
            "price": price,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "quote_timestamp": ts_iso,
            "fetch_timestamp": fetch_ts_iso,
            "freshness_seconds": freshness,
            "raw_response": raw_evidence
        }

    def get_current_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Authoritative current quote lookup using official databento.Live client.
        Enforces complete quote gate: bid, ask, spread, quote_timestamp, fetch_timestamp, freshness.
        Never falls back to Yahoo/yfinance.
        """
        fetch_ts_now = datetime.now(timezone.utc).isoformat()
        if not self.is_configured:
            return {
                "success": False,
                "status": "DATABENTO_API_KEY_MISSING",
                "provider": "DATABENTO",
                "client_type": "Live",
                "data_service": "LIVE",
                "dataset": self.dataset,
                "schema": "bbo-1s",
                "instrument": symbol,
                "symbols": [symbol],
                "bid": None,
                "ask": None,
                "spread": None,
                "quote_timestamp": None,
                "fetch_timestamp": fetch_ts_now,
                "freshness_seconds": None,
                "raw_response": None,
                "error": "DATABENTO_API_KEY environment variable is not configured",
                "http_status": 500
            }

        try:
            live_res = self._fetch_from_live_sdk(symbol)
            return {
                "success": True,
                "status": "OK",
                "provider": "DATABENTO",
                "client_type": "Live",
                "data_service": "LIVE",
                "dataset": self.dataset,
                "schema": "bbo-1s",
                "instrument": symbol,
                "symbols": [symbol],
                "latest_price": live_res["price"],
                "bid": live_res["bid"],
                "ask": live_res["ask"],
                "spread": live_res["spread"],
                "quote_timestamp": live_res["quote_timestamp"],
                "market_timestamp": live_res["quote_timestamp"],
                "timestamp": live_res["quote_timestamp"],
                "fetch_timestamp": live_res["fetch_timestamp"],
                "freshness_seconds": live_res["freshness_seconds"],
                "raw_response": live_res.get("raw_response"),
                "http_status": 200
            }
        except Exception as e:
            logger.error(f"[Databento Live Error] Quote fetch failed for {symbol}: {e}")
            return {
                "success": False,
                "status": "DATABENTO_LIVE_DATA_UNAVAILABLE",
                "provider": "DATABENTO",
                "client_type": "Live",
                "data_service": "LIVE",
                "dataset": self.dataset,
                "schema": "bbo-1s",
                "instrument": symbol,
                "symbols": [symbol],
                "bid": None,
                "ask": None,
                "spread": None,
                "quote_timestamp": None,
                "fetch_timestamp": fetch_ts_now,
                "freshness_seconds": None,
                "raw_response": None,
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
        Fetches live decision bars from official Databento Live client via intraday replay (ohlcv-1m).
        Returns DataFrame with Open, High, Low, Close, Volume.
        Strictly fails closed without Yahoo fallback.
        """
        if not self.is_configured:
            return pd.DataFrame()

        client = self._get_live_client()
        if client is None:
            return pd.DataFrame()

        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=4)
        try:
            client.subscribe(
                dataset=self.dataset,
                schema="ohlcv-1m",
                symbols=[symbol],
                start=start_time
            )
            rows = []
            start_poll = time.time()
            try:
                for record in client:
                    if hasattr(record, "close"):
                        o = getattr(record, "pretty_open", None) or (float(record.open) / 1e9 if hasattr(record, "open") else None)
                        h = getattr(record, "pretty_high", None) or (float(record.high) / 1e9 if hasattr(record, "high") else None)
                        l = getattr(record, "pretty_low", None) or (float(record.low) / 1e9 if hasattr(record, "low") else None)
                        c = getattr(record, "pretty_close", None) or (float(record.close) / 1e9 if hasattr(record, "close") else None)
                        v = getattr(record, "volume", 0)
                        ts = getattr(record, "pretty_ts_event", None)
                        if ts is None and hasattr(record, "ts_event"):
                            ts = datetime.fromtimestamp(record.ts_event / 1e9, tz=timezone.utc)
                        if all(x is not None for x in (o, h, l, c, ts)):
                            rows.append({
                                "open": float(o),
                                "high": float(h),
                                "low": float(l),
                                "close": float(c),
                                "volume": float(v),
                                "timestamp": pd.to_datetime(ts)
                            })
                    if (time.time() - start_poll) > self.timeout:
                        break
            finally:
                try:
                    client.terminate()
                except Exception:
                    pass

            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows).set_index("timestamp")
            df = df.sort_index()
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
            logger.error(f"[Databento Live Error] Bar fetch failed for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_historical_warmup(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> pd.DataFrame:
        """
        Optional historical warmup ONLY.
        Separated from live decision path; cannot independently authorise an order.
        """
        if not self.is_configured:
            return pd.DataFrame()
        try:
            hist_client = db.Historical(key=self.api_key)
            store = hist_client.timeseries.get_range(
                dataset=self.dataset,
                symbols=[symbol],
                schema="ohlcv-1m",
                start=start_time.isoformat(),
                end=end_time.isoformat()
            )
            return store.to_df()
        except Exception as e:
            logger.warning(f"[Databento Warmup Error] {e}")
            return pd.DataFrame()


databento_market_data_provider = DatabentoMarketDataProvider()
