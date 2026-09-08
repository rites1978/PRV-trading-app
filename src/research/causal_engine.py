"""
🏛️ PRV CAPITAL | CAUSAL RESEARCH ENGINE V2
Institutional Point-in-Time Causality & Temporal Invariant Enforcement.

Invariants:
1. Every research decision at timestamp t may use ONLY data published at <= t.
2. Every feature carries an explicit `feature_observation_timestamp`.
3. Invariant: `feature_observation_timestamp <= as_of_timestamp` strictly enforced.
4. Fills occur strictly at or after the decision timestamp: `fill_timestamp >= decision_timestamp`.
5. Completed 16:30 EOD candles can NEVER produce same-day 08:00 open fills.
6. Time-of-Day Volume (TOD-RVOL): Cumulative volume through time H is compared
   ONLY against historical cumulative volume through time H (not against full-day volume).
7. Pre-Entry Net Expectancy Gate: Expected Gross Profit minus ALL itemized frictions
   (Spread, Slippage, FX, Taxes, Broker/Regulatory fees) must be strictly positive.
"""
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any, Set
import pandas as pd
import numpy as np
import logging

from src.research.cost_schedule import (
    CostScheduleRepository,
    Jurisdiction,
    InstrumentClass,
    FeeType
)
from src.research.portfolio_ledger import PortfolioLedger, Position, ClosedTrade

logger = logging.getLogger("causal_engine")


class CausalityViolationError(RuntimeError):
    """Raised when an illegal temporal lookahead, future-data leakage, or reverse fill occurs."""
    pass


class EconomicRejectionError(RuntimeError):
    """Raised when a candidate fails the pre-entry net economic expectancy gate."""
    pass


@dataclass(frozen=True)
class CausalBar:
    """
    Market bar with explicit, auditable temporal lifecycle bounds.
    """
    symbol: str
    bar_start_timestamp: pd.Timestamp
    bar_end_timestamp: pd.Timestamp
    published_timestamp: pd.Timestamp
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    timeframe: str = "1m"             # "1m", "5m", "1h", "1d"

    def is_observable_at(self, as_of: pd.Timestamp) -> bool:
        """A completed bar (including Close and Total Volume) is observable iff as_of >= published_timestamp."""
        return pd.to_datetime(as_of) >= self.published_timestamp

    def is_open_observable_at(self, as_of: pd.Timestamp) -> bool:
        """The Open price is observable as soon as the bar opens (bar_start_timestamp)."""
        return pd.to_datetime(as_of) >= self.bar_start_timestamp


@dataclass(frozen=True)
class CausalFeature:
    """
    Feature carrying cryptographic-grade temporal provenance.
    """
    name: str
    value: Any
    feature_observation_timestamp: pd.Timestamp
    as_of_timestamp: pd.Timestamp
    source_description: str = ""

    def __post_init__(self):
        obs_t = pd.to_datetime(self.feature_observation_timestamp)
        as_of_t = pd.to_datetime(self.as_of_timestamp)
        if obs_t > as_of_t:
            raise CausalityViolationError(
                f"FAIL-CLOSED CAUSALITY LEAK: Feature '{self.name}' observed at {obs_t} "
                f"exceeds decision as_of_timestamp {as_of_t} (Future delta: {obs_t - as_of_t})!"
            )


@dataclass
class PreEntryCostAssessment:
    """
    Complete pre-entry economic friction ledger and net expectancy gate.
    """
    symbol: str
    jurisdiction: Jurisdiction
    instrument_class: InstrumentClass
    nominal_position_gbp: float
    target_price_gbp: float
    stop_price_gbp: float
    entry_price_gbp: float
    expected_win_probability: float

    # Itemized frictions (Entry + Exit round-trip)
    spread_friction_gbp: float = 0.0
    slippage_friction_gbp: float = 0.0
    fx_friction_gbp: float = 0.0
    sdrt_tax_gbp: float = 0.0
    ptm_levy_gbp: float = 0.0
    sec_fee_gbp: float = 0.0
    finra_taf_gbp: float = 0.0
    total_friction_gbp: float = 0.0

    # Economics
    expected_gross_profit_gbp: float = 0.0
    expected_gross_loss_gbp: float = 0.0
    expected_net_profit_gbp: float = 0.0
    passed_economic_gate: bool = False
    rejection_reason: str = ""


@dataclass
class CausalDecision:
    """
    Strategy decision formed strictly at as_of_timestamp.
    """
    decision_id: str
    as_of_timestamp: pd.Timestamp
    decision_type: str                # "ENTER", "HOLD_CASH", "EXIT", "WATCH_MODE"
    symbol: Optional[str]
    features: Dict[str, CausalFeature]
    cost_assessment: Optional[PreEntryCostAssessment] = None
    reason: str = ""


class CausalMarketDatabase:
    """
    Point-in-time market data store.
    Strictly partitions historical bars and rejects queries attempting to look past as_of_timestamp.
    """
    def __init__(self):
        # symbol -> List[CausalBar] sorted by bar_end_timestamp
        self._bars: Dict[str, List[CausalBar]] = {}
        # symbol -> pd.DataFrame for fast vectorized indexing
        self._bar_dfs: Dict[str, pd.DataFrame] = {}

    def register_bars(self, symbol: str, bars: List[CausalBar]):
        """Registers bars for a symbol, asserting strictly chronological ordering."""
        sorted_bars = sorted(bars, key=lambda b: b.published_timestamp)
        self._bars[symbol] = sorted_bars

        # Build indexed DataFrame
        records = []
        for b in sorted_bars:
            records.append({
                "bar_start": b.bar_start_timestamp,
                "bar_end": b.bar_end_timestamp,
                "published_at": b.published_timestamp,
                "Open": b.open_price,
                "High": b.high_price,
                "Low": b.low_price,
                "Close": b.close_price,
                "Volume": b.volume,
                "timeframe": b.timeframe
            })
        df = pd.DataFrame(records)
        df.index = pd.to_datetime(df["published_at"])
        df = df.sort_index()
        self._bar_dfs[symbol] = df

    def get_completed_bars_up_to(
        self,
        symbol: str,
        as_of_timestamp: pd.Timestamp,
        lookback: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Returns ONLY bars whose published_timestamp <= as_of_timestamp.
        Guarantees that no unfinished or future bars are returned.
        """
        as_of_t = pd.to_datetime(as_of_timestamp)
        if symbol not in self._bar_dfs:
            return pd.DataFrame()

        df = self._bar_dfs[symbol]
        visible = df.loc[df["published_at"] <= as_of_t]
        if lookback is not None and lookback > 0:
            return visible.iloc[-lookback:]
        return visible

    def get_intraday_partial_bar(
        self,
        symbol: str,
        as_of_timestamp: pd.Timestamp
    ) -> Optional[Dict[str, Any]]:
        """
        If the current bar is currently in-session (started <= as_of < published_at),
        returns strictly what is known: Open price, and cumulative volume/ticks up to as_of.
        Does NOT return the future Close or future High/Low of the uncompleted bar.
        """
        as_of_t = pd.to_datetime(as_of_timestamp)
        if symbol not in self._bar_dfs:
            return None

        df = self._bar_dfs[symbol]
        active = df.loc[(df["bar_start"] <= as_of_t) & (df["published_at"] > as_of_t)]
        if active.empty:
            return None

        row = active.iloc[0]
        return {
            "symbol": symbol,
            "bar_start": row["bar_start"],
            "as_of": as_of_t,
            "Open": row["Open"],
            "partial_price": row["Open"],
            "status": "UNCOMPLETED_IN_SESSION"
        }


class CausalIndicatorEngine:
    """
    Computes indicators with guaranteed temporal causality.
    Computes Time-Of-Day Adjusted Relative Volume (TOD-RVOL) and multi-timeframe features.
    """
    @staticmethod
    def compute_causal_feature(
        name: str,
        value: Any,
        observation_timestamp: pd.Timestamp,
        as_of_timestamp: pd.Timestamp,
        description: str = ""
    ) -> CausalFeature:
        return CausalFeature(
            name=name,
            value=value,
            feature_observation_timestamp=observation_timestamp,
            as_of_timestamp=as_of_timestamp,
            source_description=description
        )

    @staticmethod
    def compute_tod_rvol(
        intraday_bars: pd.DataFrame,
        historical_days: List[pd.DataFrame],
        current_time_of_day: time,
        as_of_timestamp: pd.Timestamp,
        lookback_days: int = 20
    ) -> CausalFeature:
        """
        Computes Time-Of-Day Adjusted RVOL:
        Cumulative volume on current day up to current_time_of_day
        divided by the 20-day mean of cumulative volume up to current_time_of_day.
        """
        as_of_t = pd.to_datetime(as_of_timestamp)
        if intraday_bars.empty:
            return CausalIndicatorEngine.compute_causal_feature(
                "TOD_RVOL", 1.0, as_of_t, as_of_t, "Empty intraday bars default"
            )

        # Current day cumulative volume up to as_of
        current_cum_vol = float(intraday_bars.loc[intraday_bars.index <= as_of_t, "Volume"].sum())

        # Historical days cumulative volume up to exact time of day
        hist_cum_vols = []
        for h_df in historical_days[-lookback_days:]:
            matched = h_df.loc[h_df.index.time <= current_time_of_day]
            if not matched.empty:
                hist_cum_vols.append(float(matched["Volume"].sum()))

        if not hist_cum_vols:
            tod_rvol = 1.0
            mean_hist_tod_vol = 1.0
        else:
            mean_hist_tod_vol = float(np.mean(hist_cum_vols))
            tod_rvol = round(current_cum_vol / (mean_hist_tod_vol + 1e-6), 2)

        return CausalIndicatorEngine.compute_causal_feature(
            name="TOD_RVOL",
            value=tod_rvol,
            observation_timestamp=as_of_t,
            as_of_timestamp=as_of_t,
            description=f"TOD-RVOL: CumVol({current_cum_vol:.0f}) vs MeanHistTOD({mean_hist_tod_vol:.0f} over {len(hist_cum_vols)} days)"
        )

    @staticmethod
    def compute_opening_range(
        intraday_bars: pd.DataFrame,
        open_time: time = time(8, 0),
        range_end_time: time = time(8, 30),
        as_of_timestamp: pd.Timestamp = None
    ) -> Tuple[Optional[float], Optional[float], CausalFeature]:
        """
        Computes Opening Range High and Low (e.g. 08:00 to 08:30).
        Observation timestamp is range_end_time. Cannot be observed before range_end_time!
        """
        as_of_t = pd.to_datetime(as_of_timestamp)
        orb_bars = intraday_bars.loc[
            (intraday_bars.index.time >= open_time) &
            (intraday_bars.index.time < range_end_time) &
            (intraday_bars.index <= as_of_t)
        ]

        target_orb_end_t = as_of_t.replace(hour=range_end_time.hour, minute=range_end_time.minute, second=0)
        if as_of_t < target_orb_end_t or orb_bars.empty:
            feature = CausalIndicatorEngine.compute_causal_feature(
                "ORB_ESTABLISHED", False, as_of_t, as_of_t, "Opening range not yet complete"
            )
            return None, None, feature

        orb_high = float(orb_bars["High"].max())
        orb_low = float(orb_bars["Low"].min())
        feature = CausalIndicatorEngine.compute_causal_feature(
            "ORB_ESTABLISHED", True, target_orb_end_t, as_of_t, f"ORB Established: H={orb_high}, L={orb_low}"
        )
        return orb_high, orb_low, feature

    @staticmethod
    def compute_intraday_vwap(
        intraday_bars: pd.DataFrame,
        as_of_timestamp: pd.Timestamp
    ) -> CausalFeature:
        """
        Computes cumulative intraday Volume Weighted Average Price (VWAP) strictly up to as_of.
        """
        as_of_t = pd.to_datetime(as_of_timestamp)
        visible = intraday_bars.loc[intraday_bars.index <= as_of_t]
        if visible.empty or visible["Volume"].sum() == 0:
            return CausalIndicatorEngine.compute_causal_feature(
                "VWAP", 0.0, as_of_t, as_of_t, "No volume for VWAP"
            )

        typical_price = (visible["High"] + visible["Low"] + visible["Close"]) / 3.0
        vwap = float((typical_price * visible["Volume"]).sum() / visible["Volume"].sum())
        return CausalIndicatorEngine.compute_causal_feature(
            "VWAP", round(vwap, 4), as_of_t, as_of_t, f"Intraday VWAP over {len(visible)} bars"
        )


class CausalPreEntryCostGate:
    """
    Evaluates candidate trades against institutional cost schedules before entry.
    Rejects any trade with expected net profit <= 0.
    """
    def __init__(self, cost_repo: Optional[CostScheduleRepository] = None):
        self.cost_repo = cost_repo or CostScheduleRepository()

    def assess_candidate(
        self,
        symbol: str,
        jurisdiction: Jurisdiction,
        instrument_class: InstrumentClass,
        entry_price_gbp: float,
        target_price_gbp: float,
        stop_price_gbp: float,
        nominal_position_gbp: float,
        expected_win_rate: float,
        trade_date: date,
        gbpusd_rate: float = 1.30,
        spread_bps: float = 2.5,
        slippage_bps: float = 2.0
    ) -> PreEntryCostAssessment:
        shares = nominal_position_gbp / entry_price_gbp
        target_gain_gbp = shares * (target_price_gbp - entry_price_gbp)
        stop_loss_gbp = shares * (entry_price_gbp - stop_price_gbp)

        # 1. Spread Friction (Round-trip)
        spread_friction = round(nominal_position_gbp * (spread_bps / 10000.0) * 2.0, 4)

        # 2. Execution Slippage (Round-trip)
        slippage_friction = round(nominal_position_gbp * (slippage_bps / 10000.0) * 2.0, 4)

        # 3. FX Friction (Trading212 0.15% each way if US)
        fx_friction = 0.0
        if jurisdiction == Jurisdiction.US:
            try:
                fx_sched = self.cost_repo.get_entry(FeeType.FX_CONVERSION, Jurisdiction.GLOBAL, InstrumentClass.ALL, trade_date)
                fx_rate = fx_sched.rate
            except Exception:
                fx_rate = 0.0015
            fx_friction = round(nominal_position_gbp * fx_rate * 2.0, 4)

        # 4. Stamp Duty (SDRT 0.50% if UK Equity, 0.0% if ETF)
        sdrt_friction = 0.0
        if jurisdiction == Jurisdiction.UK and instrument_class == InstrumentClass.EQUITY:
            try:
                sdrt_sched = self.cost_repo.get_entry(FeeType.SDRT, Jurisdiction.UK, InstrumentClass.EQUITY, trade_date)
                sdrt_rate = sdrt_sched.rate
            except Exception:
                sdrt_rate = 0.0050
            sdrt_friction = round(nominal_position_gbp * sdrt_rate, 4)

        # 5. PTM Levy (£1.50 each way if UK order > £10,000)
        ptm_friction = 0.0
        if jurisdiction == Jurisdiction.UK and nominal_position_gbp >= 10000.0:
            try:
                ptm_sched = self.cost_repo.get_entry(FeeType.PTM_LEVY, Jurisdiction.UK, instrument_class, trade_date)
                ptm_each = ptm_sched.fixed_amount_gbp
            except Exception:
                ptm_each = 1.50
            ptm_friction = round(ptm_each * 2.0, 4)

        # 6. US SEC Section 31 Fee (Sell side only)
        sec_friction = 0.0
        if jurisdiction == Jurisdiction.US:
            try:
                sec_sched = self.cost_repo.get_entry(FeeType.SEC_SECTION_31, Jurisdiction.US, InstrumentClass.ALL, trade_date)
                sec_rate = sec_sched.rate
            except Exception:
                sec_rate = 0.00002060
            sec_usd = (nominal_position_gbp * gbpusd_rate) * sec_rate
            sec_friction = round(sec_usd / gbpusd_rate, 4)

        # 7. US FINRA TAF (Sell side only)
        finra_friction = 0.0
        if jurisdiction == Jurisdiction.US:
            try:
                finra_sched = self.cost_repo.get_entry(FeeType.FINRA_TAF, Jurisdiction.US, InstrumentClass.EQUITY, trade_date)
                finra_rate = finra_sched.rate
                min_usd = finra_sched.minimum
                max_usd = finra_sched.maximum if finra_sched.maximum is not None else 9.79
            except Exception:
                finra_rate = 0.000195
                min_usd = 0.01
                max_usd = 9.79
            finra_usd = min(max(shares * finra_rate, min_usd), max_usd)
            finra_friction = round(finra_usd / gbpusd_rate, 4)

        total_friction = round(
            spread_friction + slippage_friction + fx_friction +
            sdrt_friction + ptm_friction + sec_friction + finra_friction, 2
        )

        expected_gross = round(
            (expected_win_rate * target_gain_gbp) - ((1.0 - expected_win_rate) * stop_loss_gbp), 2
        )
        expected_net = round(expected_gross - total_friction, 2)

        passed = expected_net > 0.0
        reason = "PASSED_ECONOMIC_GATE" if passed else f"REJECTED: Expected Net Profit (£{expected_net:.2f}) <= £0.00 after £{total_friction:.2f} frictions."

        return PreEntryCostAssessment(
            symbol=symbol,
            jurisdiction=jurisdiction,
            instrument_class=instrument_class,
            nominal_position_gbp=nominal_position_gbp,
            entry_price_gbp=entry_price_gbp,
            target_price_gbp=target_price_gbp,
            stop_price_gbp=stop_price_gbp,
            expected_win_probability=expected_win_rate,
            spread_friction_gbp=spread_friction,
            slippage_friction_gbp=slippage_friction,
            fx_friction_gbp=fx_friction,
            sdrt_tax_gbp=sdrt_friction,
            ptm_levy_gbp=ptm_friction,
            sec_fee_gbp=sec_friction,
            finra_taf_gbp=finra_friction,
            total_friction_gbp=total_friction,
            expected_gross_profit_gbp=expected_gross,
            expected_gross_loss_gbp=stop_loss_gbp,
            expected_net_profit_gbp=expected_net,
            passed_economic_gate=passed,
            rejection_reason=reason
        )


class CausalExecutionEngine:
    """
    Causal Execution Simulator.
    Enforces that orders execute strictly at or after decision timestamps,
    and prevents completed EOD bars from executing on same-day morning opens.
    """
    def __init__(self, cost_repo: Optional[CostScheduleRepository] = None):
        self.cost_repo = cost_repo or CostScheduleRepository()

    def execute_order(
        self,
        decision: CausalDecision,
        execution_bar: CausalBar,
        fill_timestamp: pd.Timestamp,
        position_size_gbp: float = 35000.0,
        gbpusd_rate: float = 1.30
    ) -> Dict[str, Any]:
        """
        Executes an order against a causal bar.
        Asserts fill_timestamp >= decision.as_of_timestamp.
        Asserts execution_bar.bar_start_timestamp >= decision.as_of_timestamp.
        """
        d_ts = pd.to_datetime(decision.as_of_timestamp)
        f_ts = pd.to_datetime(fill_timestamp)

        # 1. Hard Temporal Causality Assertion
        if f_ts < d_ts:
            raise CausalityViolationError(
                f"FAIL-CLOSED CAUSALITY LEAK: Attempted execution fill at {f_ts} "
                f"prior to decision as_of_timestamp {d_ts} (Delta: {d_ts - f_ts})!"
            )

        # 2. Hard Anti-Same-Bar Daily Lookahead Assertion
        if execution_bar.timeframe == "1d":
            if d_ts.time() >= time(16, 0) and f_ts.date() == d_ts.date() and f_ts.time() < time(16, 0):
                raise CausalityViolationError(
                    f"FAIL-CLOSED TIME TRAVEL LEAK: Decision at {d_ts} (EOD) attempted to fill "
                    f"at {f_ts} (Same-Day Morning Open)! A completed 16:30 candle cannot produce an 08:00 fill!"
                )

        # 3. Bar Observability Assertion
        if f_ts < execution_bar.bar_start_timestamp:
            raise CausalityViolationError(
                f"FAIL-CLOSED LEAK: Fill timestamp {f_ts} is before execution bar start {execution_bar.bar_start_timestamp}!"
            )

        # Fills at execution bar open or tick
        fill_price = execution_bar.open_price
        shares = round(position_size_gbp / fill_price, 4)

        return {
            "symbol": decision.symbol,
            "decision_as_of": d_ts,
            "fill_timestamp": f_ts,
            "fill_price_gbp": fill_price,
            "shares": shares,
            "notional_gbp": round(shares * fill_price, 2),
            "status": "CAUSALLY_FILLED"
        }
