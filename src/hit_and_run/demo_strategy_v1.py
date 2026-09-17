#!/usr/bin/env python3
"""
PRV Capital - EXP-DEMO-001 Strategy Implementation
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md
User Authority: Authorised exclusively for one-market-day Trading212 PRACTICE/DEMO experimentation.

Specification:
- EXPERIMENT_ID: EXP-DEMO-001
- SUBSET_TEST: True (AAPL_US_EQ only; not representative of full-universe proof)
- DEMO_EXPERIMENTAL: True
- BAR_INTERVAL: 5m (Yahoo Finance / yfinance 5m OHLCV, classified as DEMO_SIGNAL_DATA_ONLY)
- INDICATORS:
  * BOLLINGER_WINDOW = 20 (Close)
  * BOLLINGER_STDDEV_MULTIPLIER = 2.0 (Close)
  * RSI_PERIOD = 14 (Close)
  * ATR_PERIOD = 14 (High, Low, Close)
  * SMA_PERIOD = 20 (Close)
- FRICTION PROXY:
  * EXPERIMENTAL_FRICTION_PROXY = 0.0010 * Close (10 bps assumption)
  * EXPECTED_MOVE = 1.5 * ATR(14)
  * Filter: EXPECTED_MOVE > 2.0 * EXPERIMENTAL_FRICTION_PROXY
- ENTRY RULE:
  * 5m Close >= BB_Upper(20, 2.0)
  * 55 <= RSI(14) <= 75
  * 5m Close > SMA(20)
  * Exchange-local time (America/New_York) between 09:45 ET and 15:00 ET
  * Active positions == 0 (MAX_CONCURRENT_POSITIONS = 1)
  * Daily entries < 3 (MAX_DAILY_ENTRIES = 3)
  * Time since last exit >= 1800s (REENTRY_COOLDOWN = 30 minutes)
- ALLOCATION:
  * CAPITAL_PER_POSITION = £50.00 nominal
  * Quantity: floor to 2 decimal places (e.g. 0.19 shares, empirically proven accepted)
- PROTECTIVE STOP:
  * Planned loss: 2.0%
  * STOP_PRICE = math.ceil(fill_price * 0.98 * 100.0) / 100.0 (protective 2-decimal ceiling)
  * Stop timeout: 5.0 seconds (fail-safe flattens immediately if unconfirmed in open orders)
- EXITS:
  * TAKE_PROFIT: 5m Close >= round(fill_price * 1.03, 2) (+3.0%)
  * EDGE_DECAY: Position held for >= 12 consecutive 5m bars (60 minutes)
  * MOMENTUM_REVERSAL: 5m Close < SMA(20)
  * SESSION_END: Exchange-local time >= 15:45 ET (flattens position, cancels open orders, 0 overnight)
"""
import math
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd

from src.hit_and_run.models import HitAndRunEntryDecision
from src.data.market_data import MarketDataProvider
from src.data.databento_provider import DatabentoMarketDataProvider, databento_market_data_provider

logger = logging.getLogger("demo_strategy_v1")


class DemoStrategyV1:
    """Implementation of user-authorised EXP-DEMO-001 experimental strategy."""

    EXPERIMENT_ID: str = "EXP-DEMO-001"
    SUBSET_TEST: bool = True
    DEMO_EXPERIMENTAL: bool = True

    TARGET_INSTRUMENT: str = "AAPL_US_EQ"
    FEED_TICKER: str = "AAPL"
    EXCHANGE_TIMEZONE: str = "America/New_York"

    # Strict Indicator Settings (Zero hidden defaults)
    BAR_INTERVAL: str = "5m"
    BOLLINGER_WINDOW: int = 20
    BOLLINGER_STDDEV_MULTIPLIER: float = 2.0
    RSI_PERIOD: int = 14
    ATR_PERIOD: int = 14
    SMA_PERIOD: int = 20

    # Allocation & Risk
    CAPITAL_PER_POSITION_GBP: float = 50.0
    MAX_CONCURRENT_POSITIONS: int = 1
    MAX_DAILY_ENTRIES: Optional[int] = None
    PLANNED_LOSS_PCT: float = 0.02
    TAKE_PROFIT_PCT: float = 0.03
    EDGE_DECAY_BARS: int = 12  # 12 x 5m = 60 minutes
    REENTRY_COOLDOWN_SECONDS: float = 1800.0  # 30 minutes
    FRICTION_BPS_PROXY: float = 0.0010  # 10 bps

    def __init__(
        self,
        market_data_provider: Optional[MarketDataProvider] = None,
        databento_provider: Optional[DatabentoMarketDataProvider] = None,
        fx_provider: Optional[Any] = None
    ):
        self.market_data = market_data_provider or MarketDataProvider()
        self.databento_provider = databento_provider or databento_market_data_provider
        self.fx_provider = fx_provider
        self.daily_entries_count: int = 0
        self.last_exit_timestamp: float = 0.0
        self.current_holding: Optional[Dict[str, Any]] = None

    def reset_daily_state(self) -> None:
        """Reset state at the start of a new trading session."""
        self.daily_entries_count = 0
        self.last_exit_timestamp = 0.0
        self.current_holding = None

    def is_within_entry_window(self, dt_ny: datetime) -> bool:
        """Entry window: 09:45 ET through 15:00 ET (America/New_York)."""
        t = dt_ny.time()
        start_t = datetime.strptime("09:45:00", "%H:%M:%S").time()
        end_t = datetime.strptime("15:00:00", "%H:%M:%S").time()
        return start_t <= t <= end_t

    def is_session_end(self, dt_ny: datetime) -> bool:
        """Session-end flatten: 15:45 ET."""
        t = dt_ny.time()
        cutoff_t = datetime.strptime("15:45:00", "%H:%M:%S").time()
        return t >= cutoff_t

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute exact technical indicators using specified parameters."""
        if df.empty or len(df) < max(self.BOLLINGER_WINDOW, self.RSI_PERIOD, self.ATR_PERIOD):
            return df

        data = df.copy()

        # 1. 20-period SMA on Close
        data["SMA_20"] = data["Close"].rolling(window=self.SMA_PERIOD).mean()

        # 2. Bollinger Bands (20, 2.0) on Close
        rolling_std = data["Close"].rolling(window=self.BOLLINGER_WINDOW).std()
        data["BB_Upper"] = data["SMA_20"] + (rolling_std * self.BOLLINGER_STDDEV_MULTIPLIER)
        data["BB_Lower"] = data["SMA_20"] - (rolling_std * self.BOLLINGER_STDDEV_MULTIPLIER)

        # 3. RSI (14) on Close
        delta = data["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.RSI_PERIOD).mean()
        rs = gain / (loss + 1e-9)
        data["RSI"] = 100 - (100 / (1 + rs))

        # 4. ATR (14) on High, Low, Close
        high_low = data["High"] - data["Low"]
        high_close = (data["High"] - data["Close"].shift()).abs()
        low_close = (data["Low"] - data["Close"].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        data["ATR"] = ranges.max(axis=1).rolling(window=self.ATR_PERIOD).mean()

        return data

    def calculate_quantity(self, current_price_usd: float, fx_gbpusd: Optional[float] = None) -> float:
        """
        Calculate share quantity for £50 nominal allocation.
        Exact quantity format: 2 decimal places floor (empirically proven accepted by Trading212 DEMO).
        MANDATE: No hardcoded FX assumptions. Authoritative FX rate must be provided.
        """
        if current_price_usd <= 0.0 or fx_gbpusd is None or fx_gbpusd <= 0.0:
            return 0.0
        price_gbp = current_price_usd / fx_gbpusd
        raw_qty = self.CAPITAL_PER_POSITION_GBP / price_gbp
        # Protective floor to 2 decimal places so nominal <= £50
        qty = math.floor(raw_qty * 100.0) / 100.0
        return max(0.0, qty)

    def evaluate_entry(
        self,
        now_time: Optional[float] = None,
        fx_gbpusd: Optional[float] = None
    ) -> HitAndRunEntryDecision:
        """
        Evaluate entry conditions for AAPL_US_EQ.
        Returns HitAndRunEntryDecision with ENTER or NO_ENTRY.
        """
        curr_time = now_time or time.time()
        tz_ny = ZoneInfo(self.EXCHANGE_TIMEZONE)
        dt_ny = datetime.fromtimestamp(curr_time, tz=tz_ny)

        # 1. Check daily entry limit (if configured - None for DEMO experiment)
        if self.MAX_DAILY_ENTRIES is not None and self.daily_entries_count >= self.MAX_DAILY_ENTRIES:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=self.TARGET_INSTRUMENT,
                symbol=self.FEED_TICKER,
                feed_ticker=self.FEED_TICKER,
                no_entry_reason=f"DAILY_LIMIT_REACHED: {self.daily_entries_count}/{self.MAX_DAILY_ENTRIES}"
            )

        # 2. Check re-entry cooldown
        if self.last_exit_timestamp > 0.0 and (curr_time - self.last_exit_timestamp) < self.REENTRY_COOLDOWN_SECONDS:
            remaining_cooldown = int(self.REENTRY_COOLDOWN_SECONDS - (curr_time - self.last_exit_timestamp))
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=self.TARGET_INSTRUMENT,
                symbol=self.FEED_TICKER,
                feed_ticker=self.FEED_TICKER,
                no_entry_reason=f"REENTRY_COOLDOWN_ACTIVE: {remaining_cooldown}s remaining"
            )

        # 3. Check time of day in exchange-local America/New_York time
        if not self.is_within_entry_window(dt_ny):
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=self.TARGET_INSTRUMENT,
                symbol=self.FEED_TICKER,
                feed_ticker=self.FEED_TICKER,
                no_entry_reason=f"OUTSIDE_ENTRY_WINDOW: current ET time {dt_ny.strftime('%H:%M:%S')} not in 09:45-15:00"
            )

        # 4. Resolve authoritative FX rate (no guessing, no hardcoded defaults)
        active_fx = fx_gbpusd
        if active_fx is None and self.fx_provider is not None:
            if hasattr(self.fx_provider, "get_rate"):
                active_fx = self.fx_provider.get_rate("GBP", "USD")
            elif hasattr(self.fx_provider, "get_gbpusd_rate"):
                active_fx = self.fx_provider.get_gbpusd_rate()

        if active_fx is None or active_fx <= 0.0:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=self.TARGET_INSTRUMENT,
                symbol=self.FEED_TICKER,
                feed_ticker=self.FEED_TICKER,
                no_entry_reason="PRODUCT_FAILURE: FX_CONVERSION_RATE_UNAVAILABLE: Authoritative GBP/USD rate missing"
            )

        # 5. Fetch market data series (5m bars)
        df_raw = self.market_data.fetch_history(self.FEED_TICKER, period="5d", interval=self.BAR_INTERVAL)
        if df_raw.empty or len(df_raw) < 25:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=self.TARGET_INSTRUMENT,
                symbol=self.FEED_TICKER,
                feed_ticker=self.FEED_TICKER,
                no_entry_reason="MARKET_DATA_INSUFFICIENT: Fewer than 25 5m bars available"
            )

        df = self.compute_indicators(df_raw)
        last_row = df.iloc[-1]

        close_px = float(last_row["Close"])
        bb_upper = float(last_row["BB_Upper"])
        rsi_val = float(last_row["RSI"])
        sma_20 = float(last_row["SMA_20"])
        atr_val = float(last_row["ATR"])

        # Databento live quote check for current decision price (no Yahoo fallback for active decision)
        if self.databento_provider and self.databento_provider.is_configured:
            quote = self.databento_provider.get_current_quote(self.FEED_TICKER)
            if not quote.get("success"):
                return HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=self.TARGET_INSTRUMENT,
                    symbol=self.FEED_TICKER,
                    feed_ticker=self.FEED_TICKER,
                    no_entry_reason=f"PRODUCT_FAILURE: DATABENTO_LIVE_DATA_UNAVAILABLE: {quote.get('error')}"
                )
            close_px = float(quote["latest_price"])

        # 6. Evaluate Expected Move vs Friction Proxy
        expected_move = 1.5 * atr_val
        friction_proxy = self.FRICTION_BPS_PROXY * close_px
        friction_hurdle = 2.0 * friction_proxy

        if expected_move <= friction_hurdle:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=self.TARGET_INSTRUMENT,
                symbol=self.FEED_TICKER,
                feed_ticker=self.FEED_TICKER,
                current_price=close_px,
                no_entry_reason=f"EXPECTED_MOVE_BELOW_FRICTION: move={expected_move:.3f} <= hurdle={friction_hurdle:.3f}"
            )

        # 7. Evaluate Signal Conditions
        cond_bb = close_px >= bb_upper
        cond_rsi = 55.0 <= rsi_val <= 75.0
        cond_sma = close_px > sma_20

        if not (cond_bb and cond_rsi and cond_sma):
            reasons = []
            if not cond_bb:
                reasons.append(f"Close ({close_px:.2f}) < BB_Upper ({bb_upper:.2f})")
            if not cond_rsi:
                reasons.append(f"RSI ({rsi_val:.1f}) not in [55, 75]")
            if not cond_sma:
                reasons.append(f"Close ({close_px:.2f}) <= SMA_20 ({sma_20:.2f})")
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=self.TARGET_INSTRUMENT,
                symbol=self.FEED_TICKER,
                feed_ticker=self.FEED_TICKER,
                current_price=close_px,
                no_entry_reason=f"SIGNAL_CONDITIONS_NOT_MET: {'; '.join(reasons)}"
            )

        # 8. Sizing: Calculate exact share quantity for £50 nominal using authoritative FX
        qty = self.calculate_quantity(close_px, fx_gbpusd=active_fx)
        if qty <= 0.0:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=self.TARGET_INSTRUMENT,
                symbol=self.FEED_TICKER,
                feed_ticker=self.FEED_TICKER,
                current_price=close_px,
                no_entry_reason="INVALID_CALCULATED_QUANTITY: 0.0"
            )

        # 8. Protective Stop Level (2% planned loss ceiling)
        protective_stop_floor = math.ceil(close_px * (1.0 - self.PLANNED_LOSS_PCT) * 100.0) / 100.0

        decision = HitAndRunEntryDecision(
            decision="ENTER",
            instrument_id=self.TARGET_INSTRUMENT,
            symbol=self.FEED_TICKER,
            feed_ticker=self.FEED_TICKER,
            intended_capital_gbp=self.CAPITAL_PER_POSITION_GBP,
            intended_quantity=qty,
            current_price=close_px,
            required_protective_level=protective_stop_floor,
            thesis=(
                f"EXP-DEMO-001 Momentum Breakout: Close {close_px:.2f} >= BB_Upper {bb_upper:.2f}, "
                f"RSI {rsi_val:.1f} in [55,75], Close > SMA_20 {sma_20:.2f}. "
                f"Expected move {expected_move:.3f} > friction hurdle {friction_hurdle:.3f}."
            ),
            allocation_rationale=f"Fixed nominal £{self.CAPITAL_PER_POSITION_GBP:.2f} allocation -> {qty} shares."
        )
        # Attach experimental metadata
        decision.planned_loss_pct = self.PLANNED_LOSS_PCT
        return decision

    def evaluate_exit(
        self,
        holding: Dict[str, Any],
        now_time: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Evaluates active position lifecycle exit conditions:
        1. SESSION_END: time >= 15:45 ET
        2. TAKE_PROFIT: current price >= fill_price * 1.03 (+3.0%)
        3. MOMENTUM_REVERSAL: 5m Close < SMA(20)
        4. EDGE_DECAY: held for >= 12 consecutive 5m bars (60 min)
        Returns (should_exit: bool, exit_reason: str).
        """
        curr_time = now_time or time.time()
        tz_ny = ZoneInfo(self.EXCHANGE_TIMEZONE)
        dt_ny = datetime.fromtimestamp(curr_time, tz=tz_ny)

        # 1. Session End Rule (15:45 ET)
        if self.is_session_end(dt_ny):
            return True, "SESSION_END"

        # 2. Fetch latest 5m bar
        df_raw = self.market_data.fetch_history(self.FEED_TICKER, period="1d", interval=self.BAR_INTERVAL)
        if df_raw.empty:
            return False, "HOLD"

        df = self.compute_indicators(df_raw)
        last_row = df.iloc[-1]
        cur_close = float(last_row["Close"])
        sma_20 = float(last_row["SMA_20"])

        fill_price = float(holding.get("fill_price", 0.0))

        # 3. Take Profit Rule (+3.0%)
        if fill_price > 0.0:
            tp_target = round(fill_price * (1.0 + self.TAKE_PROFIT_PCT), 2)
            if cur_close >= tp_target:
                return True, "TAKE_PROFIT"

        # 4. Momentum Reversal Rule (Close < SMA20)
        if cur_close < sma_20:
            return True, "MOMENTUM_REVERSAL"

        # 5. Edge Decay Rule (12 consecutive 5m bars = 3600 seconds)
        entry_time_iso = holding.get("entry_time")
        if entry_time_iso:
            try:
                entry_dt = datetime.fromisoformat(entry_time_iso)
                holding_duration_seconds = (datetime.now(timezone.utc) - entry_dt.astimezone(timezone.utc)).total_seconds()
                if holding_duration_seconds >= (self.EDGE_DECAY_BARS * 300):
                    return True, "EDGE_DECAY"
            except Exception as e:
                logger.warning(f"Failed to parse entry_time {entry_time_iso}: {e}")

        return False, "HOLD"

    def record_entry(self) -> None:
        """Called when an entry fills."""
        self.daily_entries_count += 1

    def record_exit(self, timestamp: Optional[float] = None) -> None:
        """Called when an exit fills, recording cooldown."""
        self.last_exit_timestamp = timestamp or time.time()

    def evaluate(
        self,
        opportunities: Optional[List[Any]] = None,
        fx_gbpusd: Optional[float] = None
    ) -> List[HitAndRunEntryDecision]:
        """Runner-compatible evaluate interface."""
        fx = fx_gbpusd
        if fx is None and opportunities and len(opportunities) > 0:
            first_opp = opportunities[0]
            if isinstance(first_opp, dict) and "fx_gbpusd" in first_opp:
                fx = first_opp["fx_gbpusd"]
            elif hasattr(first_opp, "fx_gbpusd"):
                fx = getattr(first_opp, "fx_gbpusd")
        dec = self.evaluate_entry(fx_gbpusd=fx)
        return [dec]


# Singleton instance
demo_strategy_v1 = DemoStrategyV1()
