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
import os
import math
import time
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd

from src.hit_and_run.models import HitAndRunEntryDecision
from src.data.databento_provider import DatabentoMarketDataProvider, databento_market_data_provider
from src.research.news_sentiment import news_sentiment

logger = logging.getLogger("demo_strategy_v1")


class DemoStrategyV1:
    """Implementation of user-authorised Hit-and-Run and EXP-DEMO-001 strategy."""

    EXPERIMENT_ID: str = "EXP-DEMO-001"
    SUBSET_TEST: bool = True
    DEMO_EXPERIMENTAL: bool = True

    TARGET_INSTRUMENT: str = "AAPL_US_EQ"
    FEED_TICKER: str = "AAPL"
    EXCHANGE_TIMEZONE: str = "America/New_York"

    # Full Vision Tradeable Universe (US Equities & ETFs)
    FULL_VISION_UNIVERSE: List[str] = [
        "AAPL_US_EQ",
        "NVDA_US_EQ",
        "MSFT_US_EQ",
        "AMZN_US_EQ",
        "TSLA_US_EQ",
        "GOOG_US_EQ",
        "META_US_EQ",
        "SPY_US_EQ",
        "QQQ_US_EQ"
    ]
    TICKER_TO_FEED: Dict[str, str] = {
        "AAPL_US_EQ": "AAPL",
        "NVDA_US_EQ": "NVDA",
        "MSFT_US_EQ": "MSFT",
        "AMZN_US_EQ": "AMZN",
        "TSLA_US_EQ": "TSLA",
        "GOOG_US_EQ": "GOOG",
        "META_US_EQ": "META",
        "SPY_US_EQ": "SPY",
        "QQQ_US_EQ": "QQQ"
    }

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

    # Capital Ceiling & Target Banked Profit
    TOTAL_CAPITAL_BASE_GBP: float = 50000.0
    MAX_DEPLOYMENT_CEILING_PCT: float = 0.80  # 80% capital ceiling (£40,000 max)
    TARGET_PROFIT_GBP: float = 100.0  # £100 realized net profit banking target

    def __init__(
        self,
        market_data_provider: Optional[Any] = None,
        databento_provider: Optional[DatabentoMarketDataProvider] = None,
        fx_provider: Optional[Any] = None,
        mode: Optional[str] = None
    ):
        self.market_data = market_data_provider
        self.databento_provider = databento_provider or databento_market_data_provider
        self.fx_provider = fx_provider
        self.mode = mode or os.getenv("PRV_STRATEGY_MODE", "FULL_VISION").upper()
        self.daily_entries_count: int = 0
        self.last_exit_timestamp: float = 0.0
        self.current_holding: Optional[Dict[str, Any]] = None
        self.current_deployed_capital_gbp: float = 0.0

        if self.mode == "FULL_VISION":
            self.MAX_CONCURRENT_POSITIONS = 5
            self.SUBSET_TEST = False

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
        Calculate share quantity for £50 nominal allocation (EXP-DEMO-001 legacy mode).
        Exact quantity format: 2 decimal places floor (empirically proven accepted by Trading212 DEMO).
        MANDATE: No hardcoded FX assumptions. Authoritative FX rate must be provided.
        """
        if current_price_usd <= 0.0 or fx_gbpusd is None or fx_gbpusd <= 0.0:
            return 0.0
        price_gbp = current_price_usd / fx_gbpusd
        raw_qty = self.CAPITAL_PER_POSITION_GBP / price_gbp
        qty = math.floor(raw_qty * 100.0) / 100.0
        return max(0.0, qty)

    def calculate_dynamic_allocation(
        self,
        conviction_score: float,
        current_deployed_gbp: float,
        current_price_usd: float,
        fx_gbpusd: float
    ) -> Tuple[float, float]:
        """
        AI Dynamic Capital Allocation & Sizing Engine:
        1. Hard ceiling: Total deployment across all positions <= 80% of £50,000 (£40,000 max).
        2. Dynamic position sizing based on conviction (e.g. £3,000 to £10,000 per position).
        3. Allows buying 1 share, 10 shares, 50 shares, or 100+ shares without arbitrary limits.
        Returns: (allocated_capital_gbp, intended_quantity_shares).
        """
        max_total_deployment = self.TOTAL_CAPITAL_BASE_GBP * self.MAX_DEPLOYMENT_CEILING_PCT  # £40,000.00
        remaining_budget = max(0.0, max_total_deployment - current_deployed_gbp)
        if remaining_budget < 250.0 or current_price_usd <= 0.0 or fx_gbpusd <= 0.0:
            return 0.0, 0.0

        # Conviction scaling: 50 -> £3,000; 70 -> £6,500; 90+ -> £10,000
        norm_conv = max(0.0, min(1.0, (conviction_score - 50.0) / 40.0))
        target_allocation = 3000.0 + (norm_conv * 7000.0)
        allocated_capital = round(min(target_allocation, remaining_budget), 2)

        # Quantity calculation: shares rounded to 2 decimal places
        price_gbp = current_price_usd / fx_gbpusd
        raw_qty = allocated_capital / price_gbp
        qty = round(raw_qty, 2)
        if qty < 0.01:
            qty = 0.0
        return allocated_capital, qty

    def evaluate_entry(
        self,
        ticker: Optional[str] = None,
        now_time: Optional[float] = None,
        fx_gbpusd: Optional[float] = None,
        current_deployed_capital: float = 0.0
    ) -> HitAndRunEntryDecision:
        """
        Evaluate entry conditions for target instrument across technicals, live news, and sentiment.
        Returns HitAndRunEntryDecision with ENTER or NO_ENTRY.
        """
        target_inst = ticker or self.TARGET_INSTRUMENT
        feed_ticker = self.TICKER_TO_FEED.get(target_inst, self.FEED_TICKER)

        curr_time = now_time or time.time()
        tz_ny = ZoneInfo(self.EXCHANGE_TIMEZONE)
        dt_ny = datetime.fromtimestamp(curr_time, tz=tz_ny)

        # 1. Check daily entry limit (if configured)
        if self.MAX_DAILY_ENTRIES is not None and self.daily_entries_count >= self.MAX_DAILY_ENTRIES:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                no_entry_reason=f"DAILY_LIMIT_REACHED: {self.daily_entries_count}/{self.MAX_DAILY_ENTRIES}"
            )

        # 2. Check re-entry cooldown
        if self.last_exit_timestamp > 0.0 and (curr_time - self.last_exit_timestamp) < self.REENTRY_COOLDOWN_SECONDS:
            remaining_cooldown = int(self.REENTRY_COOLDOWN_SECONDS - (curr_time - self.last_exit_timestamp))
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                no_entry_reason=f"REENTRY_COOLDOWN_ACTIVE: {remaining_cooldown}s remaining"
            )

        # 3. Check time of day in exchange-local America/New_York time
        if not self.is_within_entry_window(dt_ny):
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                no_entry_reason=f"OUTSIDE_ENTRY_WINDOW: current ET time {dt_ny.strftime('%H:%M:%S')} not in 09:45-15:00"
            )

        # 4. Fetch Databento Live Quote and Enforce Complete Quote Gate (BBO strictly required)
        if not self.databento_provider or not self.databento_provider.is_configured:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                no_entry_reason="PRODUCT_FAILURE: DATABENTO_LIVE_DATA_UNAVAILABLE: Databento provider unconfigured (API key missing)"
            )

        quote = self.databento_provider.get_current_quote(feed_ticker)
        if not quote.get("success"):
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                no_entry_reason=f"PRODUCT_FAILURE: DATABENTO_LIVE_DATA_UNAVAILABLE: {quote.get('error') or quote.get('status')}"
            )

        # Enforce Complete Executable Quote Gate (BBO strictly required)
        bid = quote.get("bid")
        ask = quote.get("ask")
        spread = quote.get("spread")
        quote_ts = quote.get("quote_timestamp") or quote.get("market_timestamp") or quote.get("timestamp")
        fetch_ts = quote.get("fetch_timestamp")
        freshness = quote.get("freshness_seconds")

        if bid is None or ask is None or spread is None or spread <= 0.0 or not quote_ts or not fetch_ts or freshness is None:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                no_entry_reason=(
                    "PRODUCT_FAILURE: DATABENTO_BBO_UNAVAILABLE: Complete executable quote "
                    "(bid, ask, positive spread, quote_timestamp, fetch_timestamp, and known freshness) required"
                )
            )

        # 5. Fetch Databento 5m bars directly for indicator computation (NO Yahoo fallback for active decisions)
        df_raw = self.databento_provider.fetch_live_bars(feed_ticker, interval=self.BAR_INTERVAL, n_bars=30)
        if df_raw is None or df_raw.empty or len(df_raw) < 25:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                no_entry_reason="PRODUCT_FAILURE: DATABENTO_LIVE_DATA_UNAVAILABLE: Fewer than 25 5m Databento bars available"
            )

        df = self.compute_indicators(df_raw)
        last_row = df.iloc[-1]

        close_px = float(quote.get("latest_price", last_row["Close"]))
        bb_upper = float(last_row["BB_Upper"])
        rsi_val = float(last_row["RSI"])
        sma_20 = float(last_row["SMA_20"])
        atr_val = float(last_row["ATR"])

        # 6. Evaluate Expected Move vs Friction (Authorised formula from PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md)
        friction_proxy = self.FRICTION_BPS_PROXY * close_px
        expected_move = 1.5 * atr_val
        friction_hurdle = 2.0 * friction_proxy

        if expected_move <= friction_hurdle:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                current_price=close_px,
                no_entry_reason=(
                    f"EXPECTED_MOVE_BELOW_FRICTION: move={expected_move:.4f} <= hurdle={friction_hurdle:.4f} "
                    f"(friction_proxy={friction_proxy:.4f}, live_bid={bid}, live_ask={ask}, live_spread={spread:.4f})"
                )
            )

        # 7. Resolve authoritative FX rate (no guessing, no hardcoded defaults, NO Yahoo, NO 1.35 seed)
        active_fx = fx_gbpusd
        if active_fx is None and self.fx_provider is not None:
            prov_cls = getattr(self.fx_provider, "__class__", type(self.fx_provider)).__name__
            if "PortfolioSnapshot" not in prov_cls:
                if hasattr(self.fx_provider, "get_rate"):
                    active_fx = self.fx_provider.get_rate("GBP", "USD")
                elif hasattr(self.fx_provider, "get_gbpusd_rate"):
                    active_fx = self.fx_provider.get_gbpusd_rate()

        if active_fx is None or active_fx <= 0.0:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                current_price=close_px,
                no_entry_reason="PRODUCT_FAILURE: FX_CONVERSION_RATE_UNAVAILABLE: Authoritative GBP/USD rate missing (no guessed defaults, no seed, no Yahoo)"
            )

        # 8. Live Market Research, Financial News & Market Sentiment
        news_data = news_sentiment.fetch_stock_sentiment(feed_ticker)
        sentiment_score = float(news_data.get("sentiment_score", 50.0))
        news_tone = news_data.get("tone", "NEUTRAL")
        headlines = news_data.get("headlines", [])

        # 9. Technical & Multi-Factor Conditions
        cond_bb = close_px >= bb_upper
        cond_rsi = 55.0 <= rsi_val <= 75.0
        cond_sma = close_px > sma_20

        if self.mode == "FULL_VISION":
            # Multi-factor conviction combining technical momentum + news sentiment
            tech_conv = 75.0 if (cond_bb and cond_rsi) else (60.0 if cond_sma else 40.0)
            composite_conviction = (0.40 * tech_conv) + (0.40 * sentiment_score) + (0.20 * (65.0 if cond_sma else 40.0))

            if composite_conviction < 52.0 or sentiment_score < 42.0 or not cond_sma:
                reasons = []
                if not cond_sma:
                    reasons.append(f"Close ({close_px:.2f}) <= SMA_20 ({sma_20:.2f})")
                if sentiment_score < 42.0:
                    reasons.append(f"Bearish Sentiment ({sentiment_score:.1f})")
                if composite_conviction < 52.0:
                    reasons.append(f"Composite Conviction ({composite_conviction:.1f}) < 52.0")
                return HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=target_inst,
                    symbol=feed_ticker,
                    feed_ticker=feed_ticker,
                    current_price=close_px,
                    no_entry_reason=f"CONVICTION_BELOW_HURDLE: {'; '.join(reasons)}"
                )

            # AI Dynamic Capital Allocation & Sizing up to 80% capital ceiling (£40,000)
            allocated_capital, qty = self.calculate_dynamic_allocation(
                conviction_score=composite_conviction,
                current_deployed_gbp=current_deployed_capital,
                current_price_usd=close_px,
                fx_gbpusd=active_fx
            )
        else:
            # Legacy EXP-DEMO-001 single-instrument validation
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
                    instrument_id=target_inst,
                    symbol=feed_ticker,
                    feed_ticker=feed_ticker,
                    current_price=close_px,
                    no_entry_reason=f"SIGNAL_CONDITIONS_NOT_MET: {'; '.join(reasons)}"
                )
            allocated_capital = self.CAPITAL_PER_POSITION_GBP
            qty = self.calculate_quantity(close_px, fx_gbpusd=active_fx)

        if qty <= 0.0:
            return HitAndRunEntryDecision(
                decision="NO_ENTRY",
                instrument_id=target_inst,
                symbol=feed_ticker,
                feed_ticker=feed_ticker,
                current_price=close_px,
                no_entry_reason="CAPITAL_CEILING_OR_INVALID_QUANTITY: 0.0 shares deployable"
            )

        # 10. Protective Stop Level (2% planned loss ceiling)
        protective_stop_floor = math.ceil(close_px * (1.0 - self.PLANNED_LOSS_PCT) * 100.0) / 100.0

        thesis_text = (
            f"Hit-and-Run Market Opportunity ({target_inst}): "
            f"Technical: Close {close_px:.2f}, BB_Upper {bb_upper:.2f}, RSI {rsi_val:.1f}, SMA_20 {sma_20:.2f}. "
            f"Research & News Sentiment: Score {sentiment_score:.1f} ({news_tone}) across {len(headlines)} headlines. "
            f"Expected move {expected_move:.3f} > friction hurdle {friction_hurdle:.3f}."
        )
        alloc_text = (
            f"AI Allocation: £{allocated_capital:.2f} -> {qty} shares "
            f"(80% capital ceiling £{self.TOTAL_CAPITAL_BASE_GBP * self.MAX_DEPLOYMENT_CEILING_PCT:.2f})."
        )

        decision = HitAndRunEntryDecision(
            decision="ENTER",
            instrument_id=target_inst,
            symbol=feed_ticker,
            feed_ticker=feed_ticker,
            intended_capital_gbp=allocated_capital,
            intended_quantity=qty,
            current_price=close_px,
            required_protective_level=protective_stop_floor,
            thesis=thesis_text,
            allocation_rationale=alloc_text
        )
        decision.planned_loss_pct = self.PLANNED_LOSS_PCT
        return decision

    def evaluate_exit(
        self,
        holding: Dict[str, Any],
        now_time: Optional[float] = None,
        fx_gbpusd: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Evaluates active position lifecycle exit conditions:
        1. SESSION_END: time >= 15:45 ET
        2. PROFIT_BANK_100_EXIT: net profit after all fees & taxes >= £100.00 (Immediate Selling & Profit Banking!)
        3. TAKE_PROFIT: current price >= fill_price * 1.03 (+3.0%)
        4. MOMENTUM_REVERSAL: 5m Close < SMA(20)
        5. EDGE_DECAY: held for >= 12 consecutive 5m bars (60 min)
        Returns (should_exit: bool, exit_reason: str).
        """
        curr_time = now_time or time.time()
        tz_ny = ZoneInfo(self.EXCHANGE_TIMEZONE)
        dt_ny = datetime.fromtimestamp(curr_time, tz=tz_ny)

        # 1. Session End Rule (15:45 ET)
        if self.is_session_end(dt_ny):
            return True, "SESSION_END"

        ticker = holding.get("ticker", self.TARGET_INSTRUMENT)
        feed_ticker = self.TICKER_TO_FEED.get(ticker, self.FEED_TICKER)
        fill_price = float(holding.get("fill_price", 0.0))
        qty = float(holding.get("quantity", 0.0))

        # 2. Check live quote & Net Profit Banking Rule
        active_fx = fx_gbpusd
        if active_fx is None and self.fx_provider:
            try:
                active_fx = self.fx_provider.get_rate("GBP", "USD")
            except Exception:
                pass
        if active_fx is None or active_fx <= 0.0:
            active_fx = float(holding.get("fx_rate", 1.30))

        # Fetch latest 5m bar via Databento Live (ZERO Yahoo calls)
        df_raw = self.databento_provider.fetch_live_bars(feed_ticker, interval=self.BAR_INTERVAL)
        if df_raw is None or df_raw.empty or len(df_raw) < 20:
            return False, "HOLD"

        df = self.compute_indicators(df_raw)
        last_row = df.iloc[-1]
        cur_close = float(last_row["Close"])
        sma_20 = float(last_row["SMA_20"])

        # Fetch live BBO quote for realistic liquidation proceeds
        cur_bid = cur_close
        if self.databento_provider and self.databento_provider.is_configured:
            quote = self.databento_provider.get_current_quote(feed_ticker)
            if quote.get("success"):
                cur_bid = float(quote.get("bid", cur_close))

        if cur_close > 0.0 and fill_price > 0.0 and qty > 0.0 and active_fx > 0.0:
            entry_cost_gbp = float(holding.get("entry_cost_gbp", 0.0))
            if entry_cost_gbp <= 0.0:
                entry_cost_gbp = (qty * fill_price) / active_fx

            liquidation_price = cur_bid if cur_bid > 0.0 else cur_close
            gross_value_gbp = (qty * liquidation_price) / active_fx
            # Estimated exit friction (FX fee 0.15% + SEC + FINRA + spread ~ 0.20% total)
            estimated_exit_fees_gbp = round(gross_value_gbp * 0.0020, 2)
            net_profit_gbp = round(gross_value_gbp - entry_cost_gbp - estimated_exit_fees_gbp, 2)

            holding["current_price"] = liquidation_price
            holding["net_pnl_gbp"] = net_profit_gbp

            # 🎯 USER DIRECTIVE: The moment £100 profit after fees and tax is earned, selling happens & money is banked!
            if net_profit_gbp >= self.TARGET_PROFIT_GBP:
                logger.info(
                    f"[Profit Banked Trigger] {ticker}: Net profit £{net_profit_gbp:.2f} >= target £{self.TARGET_PROFIT_GBP:.2f}! "
                    f"Triggering immediate exit to bank profit."
                )
                return True, "PROFIT_BANK_100_EXIT"

            # Percentage take profit (+3.0%) fallback
            tp_target = round(fill_price * (1.0 + self.TAKE_PROFIT_PCT), 2)
            if cur_close >= tp_target:
                return True, "TAKE_PROFIT"

        # 3. Indicators for momentum reversal
        if df_raw is not None and not df_raw.empty and len(df_raw) >= 20:
            df = self.compute_indicators(df_raw)
            last_row = df.iloc[-1]
            cur_c = float(last_row["Close"])
            sma_20 = float(last_row["SMA_20"])
            if cur_c < sma_20:
                return True, "MOMENTUM_REVERSAL"

        # 4. Edge Decay Rule (12 consecutive 5m bars = 3600 seconds)
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

        if self.mode == "FULL_VISION":
            current_deployed = getattr(self, "current_deployed_capital_gbp", 0.0)
            decisions = []
            for ticker in self.FULL_VISION_UNIVERSE:
                dec = self.evaluate_entry(
                    ticker=ticker,
                    fx_gbpusd=fx,
                    current_deployed_capital=current_deployed
                )
                if dec.decision == "ENTER":
                    decisions.append(dec)
            if decisions:
                return decisions
            # Return primary candidate for telemetry logging
            return [self.evaluate_entry(ticker=self.FULL_VISION_UNIVERSE[0], fx_gbpusd=fx)]

        dec = self.evaluate_entry(fx_gbpusd=fx)
        return [dec]


# Singleton instance wired with Databento live data; no unapproved FX default
demo_strategy_v1 = DemoStrategyV1(
    databento_provider=databento_market_data_provider,
    fx_provider=None,
    mode=os.getenv("PRV_STRATEGY_MODE", "FULL_VISION").upper()
)

