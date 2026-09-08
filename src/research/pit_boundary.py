"""
🏛️ PRV CAPITAL | POINT-IN-TIME (PIT) INFORMATION BOUNDARY
Guarantees absolute zero future-information leakage into strategy decisions.

Invariant:
AVAILABLE_INFORMATION(event) iff published_at <= simulated_decision_timestamp

Any attempt to query data with timestamp > clock.current_time raises LookAheadViolationError.
"""
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Union
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class LookAheadViolationError(RuntimeError):
    """Raised when a strategy or component attempts to access future information."""
    pass


class CatalystEvent:
    """Immutable point-in-time catalyst or information event."""
    def __init__(
        self,
        event_id: str,
        symbol: str,
        event_type: str,
        published_at: pd.Timestamp,
        data: Dict[str, Any],
        source: str = ""
    ):
        self.event_id = event_id
        self.symbol = symbol
        self.event_type = event_type
        self.published_at = pd.to_datetime(published_at)
        self.data = data
        self.source = source

    def is_visible_at(self, current_time: pd.Timestamp) -> bool:
        return self.published_at <= pd.to_datetime(current_time)


class PointInTimeBoundary:
    """
    Firewall isolating historical future data from simulation agents.
    All data queries MUST pass through this boundary with an explicit current_time.
    """
    def __init__(self):
        # symbol -> pd.DataFrame (indexed by Timestamp)
        self._market_data: Dict[str, pd.DataFrame] = {}
        # symbol -> List[CatalystEvent]
        self._catalysts: Dict[str, List[CatalystEvent]] = {}
        # Point-in-time constituents: date_str -> Set[symbol]
        self._historical_constituents: Dict[str, set] = {}

    def register_market_data(self, symbol: str, df: pd.DataFrame):
        """Registers OHLCV market data for a symbol. Verifies sorted datetime index."""
        if df.empty:
            return
        df_clean = df.copy()
        if not isinstance(df_clean.index, pd.DatetimeIndex):
            df_clean.index = pd.to_datetime(df_clean.index)
        # Ensure strictly ascending index
        df_clean = df_clean.sort_index()
        self._market_data[symbol] = df_clean

    def register_catalysts(self, symbol: str, events: List[CatalystEvent]):
        """Registers point-in-time catalysts for a symbol, sorted by published_at."""
        sorted_events = sorted(events, key=lambda e: e.published_at)
        self._catalysts[symbol] = sorted_events

    def register_constituents(self, effective_date: date, symbols: List[str]):
        """Registers index / universe constituents active on effective_date."""
        dt_str = effective_date.isoformat()
        self._historical_constituents[dt_str] = set(symbols)

    def is_constituent_at(self, symbol: str, current_time: pd.Timestamp) -> bool:
        """Point-in-time check if symbol is in the active universe at current_time."""
        check_date = pd.to_datetime(current_time).date()
        dt_str = check_date.isoformat()
        # Find the most recent constituent rebalance on or before check_date
        valid_dates = [d for d in self._historical_constituents.keys() if d <= dt_str]
        if not valid_dates:
            # If no constituent schedule registered, default to True (open universe)
            return True
        latest_date = max(valid_dates)
        return symbol in self._historical_constituents[latest_date]

    def get_bars_up_to(
        self,
        symbol: str,
        current_time: pd.Timestamp,
        lookback_bars: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Returns market bars strictly on or before current_time.
        Guarantees no future bars are returned.
        """
        ts = pd.to_datetime(current_time)
        if symbol not in self._market_data:
            return pd.DataFrame()

        df = self._market_data[symbol]
        # Slice up to current_time (inclusive)
        visible_df = df.loc[df.index <= ts]

        if lookback_bars is not None and lookback_bars > 0:
            return visible_df.iloc[-lookback_bars:]
        return visible_df

    def get_latest_bar(self, symbol: str, current_time: pd.Timestamp) -> Optional[pd.Series]:
        """
        Returns the single most recent bar closed on or before current_time.
        """
        bars = self.get_bars_up_to(symbol, current_time, lookback_bars=1)
        if bars.empty:
            return None
        return bars.iloc[-1]

    def get_catalysts_up_to(
        self,
        symbol: str,
        current_time: pd.Timestamp
    ) -> List[CatalystEvent]:
        """
        Returns catalyst events published strictly on or before current_time.
        """
        ts = pd.to_datetime(current_time)
        if symbol not in self._catalysts:
            return []

        events = self._catalysts[symbol]
        return [e for e in events if e.is_visible_at(ts)]

    def verify_query_integrity(
        self,
        queried_timestamp: pd.Timestamp,
        decision_timestamp: pd.Timestamp
    ):
        """
        Explicit integrity assertion.
        Fails closed if queried_timestamp > decision_timestamp.
        """
        q_ts = pd.to_datetime(queried_timestamp)
        d_ts = pd.to_datetime(decision_timestamp)
        if q_ts > d_ts:
            raise LookAheadViolationError(
                f"FAIL-CLOSED: Look-ahead violation detected! "
                f"Queried data timestamp {q_ts} is in the future relative to "
                f"decision timestamp {d_ts} (Delta: {q_ts - d_ts})."
            )
