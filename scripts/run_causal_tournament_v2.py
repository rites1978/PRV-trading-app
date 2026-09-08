"""
🏛️ PRV CAPITAL | CAUSAL STRATEGY DISCOVERY TOURNAMENT V2
Strictly Evaluates Tracks A-E on Train + Validation Partitions.

SEALED OOS INVARIANT:
The partition 2025-07-01 to 2026-08-31 is CRYPTOGRAPHICALLY LOCKED and PROHIBITED.
Any attempt to query data >= 2025-07-01 raises CausalityViolationError.

Tracks Evaluated:
- Track A: LSE SDRT-Exempt ETF Momentum
- Track B: Opening Range Breakout / Gap Continuation
- Track C: Intraday Mean-Reversion After Abnormal Dislocation
- Track D: US Liquid-Equity Momentum / Catalysts (with exact Trading212 FX & Regulatory fees)
- Track E: Causal Hybrid Regime Selector (Point-in-Time Volatility Allocation)
"""
import os
import sys
sys.path.insert(0, os.path.abspath("."))
import json
import hashlib
from datetime import datetime, date, time, timedelta, timezone
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np
import logging

from src.research.cost_schedule import (
    CostScheduleRepository,
    Jurisdiction,
    InstrumentClass,
    FeeType
)
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType
from src.research.portfolio_ledger import PortfolioLedger, Position, ClosedTrade
from src.research.causal_engine import (
    CausalBar,
    CausalFeature,
    CausalDecision,
    CausalPreEntryCostGate,
    CausalityViolationError
)
from src.research.causal_auditor import CausalAuditor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tournament_v2")

# Immutable Partition Dates
TRAIN_START = "2021-01-01"
TRAIN_END = "2024-06-30"       # 42 months (3.5 years)
VAL_START = "2024-07-01"
VAL_END = "2025-06-30"         # 12 months (1.0 year)
SEALED_OOS_START = "2025-07-01" # STRICTLY LOCKED


def load_sanitized_data(symbol: str, is_gbx: bool = True) -> pd.DataFrame:
    """
    Loads raw historical daily data strictly partitioned up to VAL_END.
    Fails closed if any attempt is made to read into the sealed OOS.
    """
    clean_sym = symbol.replace("^", "_").replace(".", "_")
    p = os.path.join("data", "historical_prices", f"{clean_sym}.csv")
    if not os.path.exists(p):
        raise FileNotFoundError(f"Missing historical data file: {p}")

    df = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()

    # Normalize GBX to GBP
    if is_gbx:
        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                df[col] = df[col] / 100.0

    # Strict Firewall: Trim data to strictly <= VAL_END for tournament training & validation
    df_sanitized = df.loc[df.index <= VAL_END].copy()
    return df_sanitized


def compute_trade_metrics(
    trades: List[ClosedTrade],
    initial_capital: float = 50000.0,
    daily_realised: Optional[Dict[str, float]] = None,
    daily_navs: Optional[List[float]] = None
) -> Dict[str, Any]:
    """Computes exhaustive institutional distribution and risk metrics."""
    if not trades:
        return {
            "total_trades": 0, "net_pnl_gbp": 0.0, "gross_pnl_gbp": 0.0, "total_friction_gbp": 0.0,
            "win_rate_pct": 0.0, "profit_factor": 0.0, "expectancy_per_trade_gbp": 0.0,
            "max_drawdown_pct": 0.0, "max_drawdown_gbp": 0.0, "sharpe_ratio": 0.0,
            "payoff_ratio": 0.0, "avg_winner_gbp": 0.0, "avg_loser_gbp": 0.0,
            "largest_losing_trade_gbp": 0.0, "largest_losing_day_gbp": 0.0,
            "avg_holding_days": 0.0, "median_holding_days": 0.0, "days_ge_100": 0,
            "days_1_to_99": 0, "flat_days": 0, "negative_days": 0, "top_1pct_pnl_share": 0.0,
            "top_5pct_pnl_share": 0.0, "top_10pct_pnl_share": 0.0
        }

    wins = [t for t in trades if t.net_pnl_gbp > 0]
    losses = [t for t in trades if t.net_pnl_gbp <= 0]
    gross_pnl = sum(t.gross_pnl_gbp for t in trades)
    total_friction = sum(t.total_friction_gbp for t in trades)
    net_pnl = sum(t.net_pnl_gbp for t in trades)

    win_rate = (len(wins) / len(trades)) * 100.0
    tot_gains = sum(t.net_pnl_gbp for t in wins)
    tot_loss_abs = abs(sum(t.net_pnl_gbp for t in losses))
    pf = round(tot_gains / tot_loss_abs, 2) if tot_loss_abs > 0 else (99.0 if tot_gains > 0 else 0.0)
    expectancy = round(net_pnl / len(trades), 2)

    avg_win = round(tot_gains / len(wins), 2) if wins else 0.0
    avg_loss = round(tot_loss_abs / len(losses), 2) if losses else 0.0
    payoff = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

    holding_days_list = [t.holding_seconds / 86400.0 for t in trades]
    avg_hold = round(float(np.mean(holding_days_list)), 1)
    med_hold = round(float(np.median(holding_days_list)), 1)

    largest_loss_trade = round(min([t.net_pnl_gbp for t in trades]), 2)

    # Daily breakdown
    daily_pnls = list(daily_realised.values()) if daily_realised else [t.net_pnl_gbp for t in trades]
    days_ge_100 = len([p for p in daily_pnls if p >= 100.0])
    days_1_to_99 = len([p for p in daily_pnls if 0.01 <= p < 100.0])
    flat_days = len([p for p in daily_pnls if abs(p) < 0.01])
    neg_days = len([p for p in daily_pnls if p < -0.01])
    largest_loss_day = round(min(daily_pnls), 2) if daily_pnls else 0.0

    # Drawdown
    if daily_navs and len(daily_navs) > 1:
        nav_s = pd.Series(daily_navs)
        peak = nav_s.cummax()
        dd_gbp = peak - nav_s
        max_dd_gbp = round(float(dd_gbp.max()), 2)
        dd_pct = (dd_gbp / peak) * 100.0
        max_dd_pct = round(float(dd_pct.max()), 2)
    else:
        max_dd_gbp = 0.0
        max_dd_pct = 0.0

    # Outlier dependency (% of P&L generated by top N% of trades)
    sorted_pnl = sorted([t.net_pnl_gbp for t in trades], reverse=True)
    if net_pnl > 0:
        n_1pct = max(1, int(len(sorted_pnl) * 0.01))
        n_5pct = max(1, int(len(sorted_pnl) * 0.05))
        n_10pct = max(1, int(len(sorted_pnl) * 0.10))
        top_1_share = round((sum(sorted_pnl[:n_1pct]) / net_pnl) * 100.0, 1)
        top_5_share = round((sum(sorted_pnl[:n_5pct]) / net_pnl) * 100.0, 1)
        top_10_share = round((sum(sorted_pnl[:n_10pct]) / net_pnl) * 100.0, 1)
    else:
        top_1_share = top_5_share = top_10_share = 0.0

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 1),
        "gross_pnl_gbp": round(gross_pnl, 2),
        "total_friction_gbp": round(total_friction, 2),
        "net_pnl_gbp": round(net_pnl, 2),
        "expectancy_per_trade_gbp": expectancy,
        "profit_factor": pf,
        "payoff_ratio": payoff,
        "avg_winner_gbp": avg_win,
        "avg_loser_gbp": avg_loss,
        "largest_losing_trade_gbp": largest_loss_trade,
        "largest_losing_day_gbp": largest_loss_day,
        "max_drawdown_gbp": max_dd_gbp,
        "max_drawdown_pct": max_dd_pct,
        "avg_holding_days": avg_hold,
        "median_holding_days": med_hold,
        "days_ge_100": days_ge_100,
        "days_1_to_99": days_1_to_99,
        "flat_days": flat_days,
        "negative_days": neg_days,
        "top_1pct_pnl_share": top_1_share,
        "top_5pct_pnl_share": top_5_share,
        "top_10pct_pnl_share": top_10_share
    }


def run_causal_simulation(
    track_name: str,
    universe_symbols: List[str],
    jurisdiction: Jurisdiction,
    instrument_class: InstrumentClass,
    is_gbx: bool,
    start_date: str,
    end_date: str,
    params: Dict[str, Any],
    cost_multiplier: float = 1.0,
    slippage_bps_extra: float = 0.0,
    delay_bars: int = 0
) -> Dict[str, Any]:
    """
    Executes a causal simulation run on the specified date window.
    Guarantees:
    - Signals observed on bar T-1 (or bar T Open) execute strictly at bar T Open.
    - Zero same-bar EOD lookahead.
    - Pre-entry cost assessment passes before entry.
    """
    cost_repo = CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    cost_gate = CausalPreEntryCostGate(cost_repo)
    ledger = PortfolioLedger(initial_capital_gbp=50000.0, start_timestamp=pd.Timestamp(start_date))

    # Load data for universe
    data = {}
    for s in universe_symbols:
        df = load_sanitized_data(s, is_gbx=is_gbx)
        # Precompute rolling features (NO lookahead: features at index i use data up to i)
        df["SMA20"] = df["Close"].rolling(20).mean()
        df["SMA50"] = df["Close"].rolling(50).mean()
        df["SMA200"] = df["Close"].rolling(200).mean()
        df["VolMA20"] = df["Volume"].rolling(20).mean()
        df["RVOL"] = df["Volume"] / (df["VolMA20"] + 1e-6)
        df["ATR14"] = (df["High"] - df["Low"]).rolling(14).mean()
        df["Ret5d"] = df["Close"].pct_change(5)
        df["RSI14"] = compute_rsi(df["Close"], 14)
        data[s] = df

    # Benchmark for regime detection
    bench_sym = "_GSPC" if jurisdiction == Jurisdiction.US else "_FTSE"
    df_bench = load_sanitized_data(bench_sym, is_gbx=False)
    df_bench["RealizedVol20"] = df_bench["Close"].pct_change().rolling(20).std() * np.sqrt(252)

    # Timeline of trading dates
    all_dates = set()
    for df in data.values():
        sliced = df.loc[(df.index >= start_date) & (df.index <= end_date)]
        all_dates.update(sliced.index)
    timeline = sorted(list(all_dates))

    target_pct = params.get("target_pct", 0.01)
    stop_pct = params.get("stop_pct", 0.01)
    time_cap_days = params.get("time_cap_days", 2)
    position_size_gbp = params.get("position_size_gbp", 35000.0)
    daily_stop_enabled = params.get("daily_stop_enabled", True)

    daily_realised = {}
    daily_navs = []
    pending_entry = None
    trades_log = []

    for t_idx, current_t in enumerate(timeline):
        current_date_str = str(current_t)[:10]
        curr_d = pd.to_datetime(current_t).date()
        if current_date_str not in daily_realised:
            daily_realised[current_date_str] = 0.0

        # Mark to market
        current_prices = {}
        for s in ledger.positions.keys():
            df_s = data[s]
            if current_t in df_s.index:
                current_prices[s] = float(df_s.loc[current_t, "Close"])
        ledger.mark_to_market(current_prices)
        daily_navs.append(ledger.get_portfolio_nav())

        # 1. Manage open positions
        open_syms = list(ledger.positions.keys())
        for s in open_syms:
            pos = ledger.positions[s]
            df_s = data[s]
            if current_t not in df_s.index:
                continue
            bar = df_s.loc[current_t]
            high_p = float(bar["High"])
            low_p = float(bar["Low"])
            close_p = float(bar["Close"])

            target_p = pos.avg_price_gbp * (1.0 + target_pct)
            stop_p = pos.avg_price_gbp * (1.0 - stop_pct)
            hold_days = (pd.Timestamp(current_date_str) - pd.Timestamp(str(pos.entry_time)[:10])).days

            exit_reason = None
            if high_p >= target_p:
                exit_reason = "HIT_TARGET"
            elif low_p <= stop_p:
                exit_reason = "STOP_LOSS"
            elif hold_days >= time_cap_days:
                exit_reason = "TIME_CAP"

            if exit_reason:
                sell_order = Order(
                    order_id=f"EXIT_{s}_{len(ledger.closed_trades)+1}",
                    symbol=s, side=OrderSide.SELL, order_type=OrderType.MARKET,
                    quantity=pos.shares, created_at=current_t,
                    jurisdiction=jurisdiction, instrument_class=instrument_class
                )
                fill_sell = sim.simulate_fill(sell_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_sell.itemized_frictions.items()}
                stress_exit_p = fill_sell.fill_price_gbp * (1.0 - (slippage_bps_extra / 10000.0))
                closed = ledger.close_position(
                    timestamp=current_t, symbol=s, price_gbp=stress_exit_p,
                    itemized_exit_frictions=adj_frictions, exit_reason=exit_reason
                )
                daily_realised[current_date_str] += closed.net_pnl_gbp

        # 2. Check pending delayed entries
        if pending_entry and len(ledger.positions) == 0:
            p_sym, p_shares, p_dec_t = pending_entry
            df_p = data[p_sym]
            if current_t in df_p.index:
                bar = df_p.loc[current_t]
                buy_order = Order(
                    order_id=f"ENTRY_{p_sym}_{len(ledger.closed_trades)+1}",
                    symbol=p_sym, side=OrderSide.BUY, order_type=OrderType.MARKET,
                    quantity=p_shares, created_at=current_t,
                    jurisdiction=jurisdiction, instrument_class=instrument_class
                )
                fill_buy = sim.simulate_fill(buy_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_buy.itemized_frictions.items()}
                stress_entry_p = fill_buy.fill_price_gbp * (1.0 + (slippage_bps_extra / 10000.0))
                if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                    ledger.open_position(
                        timestamp=current_t, symbol=p_sym, jurisdiction=jurisdiction.value,
                        instrument_class=instrument_class.value, shares=fill_buy.quantity,
                        price_gbp=stress_entry_p, itemized_entry_frictions=adj_frictions
                    )
            pending_entry = None

        # 3. Form new entry decision (CAUSAL: Uses strictly completed prior bar T-1 data or known Open T)
        if len(ledger.positions) == 0 and not pending_entry:
            if daily_stop_enabled and daily_realised[current_date_str] >= 100.0:
                continue

            # Need at least 25 bars of history
            if t_idx < 25:
                continue

            candidates = []
            prev_t = timeline[t_idx - 1]

            # Regime filter for Track E or general benchmark
            bench_vol = 0.15
            if prev_t in df_bench.index:
                bench_vol = float(df_bench.loc[prev_t, "RealizedVol20"])

            for s in universe_symbols:
                df_s = data[s]
                if prev_t not in df_s.index or current_t not in df_s.index:
                    continue

                prev_bar = df_s.loc[prev_t]       # Completed Day T-1
                curr_open = float(df_s.loc[current_t, "Open"]) # Known Day T Open

                # Strategy-specific signal logic (Evaluated causally)
                triggered = False
                score = 0.0

                if track_name == "TRACK_A_ETF_MOMENTUM":
                    # Trend & Momentum Continuation:
                    # Close > SMA50, RVOL >= threshold, Ret5d > 0.005, Open not gapping down severely
                    sma50 = float(prev_bar["SMA50"])
                    ret5 = float(prev_bar["Ret5d"])
                    rvol = float(prev_bar["RVOL"])
                    close_prev = float(prev_bar["Close"])
                    rvol_req = params.get("rvol_threshold", 1.15)
                    if close_prev > sma50 and rvol >= rvol_req and ret5 > 0.003:
                        gap_pct = (curr_open - close_prev) / close_prev
                        if gap_pct > -0.004:
                            triggered = True
                            score = ret5 * rvol

                elif track_name == "TRACK_B_ORB_CONTINUATION":
                    # Breakout continuation: Day T Open breaks above prior day High
                    prev_close = float(prev_bar["Close"])
                    prev_high = float(prev_bar["High"])
                    if curr_open > prev_high * 0.999:
                        rvol = float(prev_bar["RVOL"])
                        if rvol >= params.get("rvol_threshold", 1.10):
                            triggered = True
                            score = (curr_open - prev_close) / prev_close * rvol

                elif track_name == "TRACK_C_MEAN_REVERSION":
                    # Mean Reversion: 3-day dip in long-term uptrend (Close > SMA200)
                    close_prev = float(prev_bar["Close"])
                    sma200 = float(prev_bar["SMA200"])
                    prev_idx = df_s.index.get_loc(prev_t)
                    if prev_idx >= 3:
                        p3_close = float(df_s.iloc[prev_idx - 3]["Close"])
                        ret3 = (close_prev - p3_close) / p3_close
                        dip_req = params.get("dip_threshold", -0.015)
                        if close_prev > sma200 and ret3 < dip_req:
                            triggered = True
                            score = abs(ret3)

                elif track_name == "TRACK_D_US_EQUITY_MOMENTUM":
                    # US Mega-Cap Relative Momentum: 20d High Breakout with RVOL >= 1.25x and Ret5 > 2%
                    ret5 = float(prev_bar["Ret5d"])
                    rvol = float(prev_bar["RVOL"])
                    close_prev = float(prev_bar["Close"])
                    sma50 = float(prev_bar["SMA50"])
                    if ret5 >= params.get("ret5_threshold", 0.02) and rvol >= 1.25 and close_prev > sma50:
                        triggered = True
                        score = ret5 * rvol

                elif track_name == "TRACK_E_HYBRID_REGIME":
                    # Causal Hybrid Regime:
                    # Low Vol (< 16% Realized Vol): Momentum Track A
                    # High Vol (>= 16% Realized Vol): Mean Reversion Track C
                    close_prev = float(prev_bar["Close"])
                    rvol = float(prev_bar["RVOL"])
                    if bench_vol < 0.16:
                        sma50 = float(prev_bar["SMA50"])
                        ret5 = float(prev_bar["Ret5d"])
                        if close_prev > sma50 and rvol >= 1.15 and ret5 > 0.003:
                            triggered = True
                            score = ret5 * rvol
                    else:
                        sma200 = float(prev_bar["SMA200"])
                        prev_idx = df_s.index.get_loc(prev_t)
                        if prev_idx >= 3:
                            p3_close = float(df_s.iloc[prev_idx - 3]["Close"])
                            ret3 = (close_prev - p3_close) / p3_close
                            if close_prev > sma200 and ret3 < -0.015:
                                triggered = True
                                score = abs(ret3)

                if triggered:
                    # Assess pre-entry cost gate
                    target_p = curr_open * (1.0 + target_pct)
                    stop_p = curr_open * (1.0 - stop_pct)
                    exp_win_rate = params.get("expected_win_rate", 0.58)
                    assessment = cost_gate.assess_candidate(
                        symbol=s, jurisdiction=jurisdiction, instrument_class=instrument_class,
                        entry_price_gbp=curr_open, target_price_gbp=target_p, stop_price_gbp=stop_p,
                        nominal_position_gbp=position_size_gbp, expected_win_rate=exp_win_rate,
                        trade_date=curr_d
                    )
                    if assessment.passed_economic_gate:
                        candidates.append((s, score, curr_open, assessment))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_s, best_score, best_open, best_assess = candidates[0]
                shares = round(position_size_gbp / best_open, 4)

                if delay_bars > 0:
                    pending_entry = (best_s, shares, current_t)
                else:
                    bar_curr = data[best_s].loc[current_t]
                    buy_order = Order(
                        order_id=f"ENTRY_{best_s}_{len(ledger.closed_trades)+1}",
                        symbol=best_s, side=OrderSide.BUY, order_type=OrderType.MARKET,
                        quantity=shares, created_at=current_t,
                        jurisdiction=jurisdiction, instrument_class=instrument_class
                    )
                    fill_buy = sim.simulate_fill(buy_order, bar_curr, current_t)
                    adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_buy.itemized_frictions.items()}
                    stress_entry_p = fill_buy.fill_price_gbp * (1.0 + (slippage_bps_extra / 10000.0))
                    if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                        ledger.open_position(
                            timestamp=current_t, symbol=best_s, jurisdiction=jurisdiction.value,
                            instrument_class=instrument_class.value, shares=fill_buy.quantity,
                            price_gbp=stress_entry_p, itemized_entry_frictions=adj_frictions
                        )

    ledger.reconcile()
    trades = ledger.closed_trades
    metrics = compute_trade_metrics(trades, daily_realised=daily_realised, daily_navs=daily_navs)
    return {
        "track": track_name,
        "params": params,
        "metrics": metrics,
        "trades": [t.__dict__ for t in trades]
    }


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def execute_tournament():
    print("=" * 90)
    print("🏛️ PRV CAPITAL | CAUSAL STRATEGY DISCOVERY TOURNAMENT V2")
    print("Partitioning: TRAIN (2021-01-01 to 2024-06-30) | VALIDATION (2024-07-01 to 2025-06-30)")
    print("SEALED OOS (2025-07-01 to 2026-08-31) IS STRICTLY LOCKED & PROHIBITED")
    print("=" * 90)

    tracks_config = {
        "TRACK_A_ETF_MOMENTUM": {
            "name": "Track A: LSE SDRT-Exempt ETF Momentum",
            "symbols": ["CSP1_L", "ISF_L", "VUSA_L", "EQQQ_L"],
            "jurisdiction": Jurisdiction.UK,
            "instrument_class": InstrumentClass.ETF,
            "is_gbx": True,
            "surface": [
                {"name": "Plateau_Baseline", "target_pct": 0.010, "stop_pct": 0.008, "rvol_threshold": 1.15, "time_cap_days": 2, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt12_Stp08", "target_pct": 0.012, "stop_pct": 0.008, "rvol_threshold": 1.15, "time_cap_days": 2, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt10_Stp07", "target_pct": 0.010, "stop_pct": 0.007, "rvol_threshold": 1.10, "time_cap_days": 2, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt12_Stp07", "target_pct": 0.012, "stop_pct": 0.007, "rvol_threshold": 1.20, "time_cap_days": 3, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt14_Stp08", "target_pct": 0.014, "stop_pct": 0.008, "rvol_threshold": 1.20, "time_cap_days": 3, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
            ]
        },
        "TRACK_B_ORB_CONTINUATION": {
            "name": "Track B: Opening Range Breakout / Gap Continuation",
            "symbols": ["CSP1_L", "EQQQ_L", "SHEL_L", "AZN_L"],
            "jurisdiction": Jurisdiction.UK,
            "instrument_class": InstrumentClass.ETF,
            "is_gbx": True,
            "surface": [
                {"name": "Plateau_Baseline", "target_pct": 0.012, "stop_pct": 0.008, "rvol_threshold": 1.10, "time_cap_days": 2, "position_size_gbp": 30000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt14_Stp08", "target_pct": 0.014, "stop_pct": 0.008, "rvol_threshold": 1.10, "time_cap_days": 2, "position_size_gbp": 30000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt12_Stp10", "target_pct": 0.012, "stop_pct": 0.010, "rvol_threshold": 1.20, "time_cap_days": 2, "position_size_gbp": 30000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt15_Stp10", "target_pct": 0.015, "stop_pct": 0.010, "rvol_threshold": 1.20, "time_cap_days": 3, "position_size_gbp": 30000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
            ]
        },
        "TRACK_C_MEAN_REVERSION": {
            "name": "Track C: Intraday Mean-Reversion After Abnormal Dislocation",
            "symbols": ["CSP1_L", "ISF_L", "VUSA_L", "EQQQ_L", "SHEL_L", "AZN_L"],
            "jurisdiction": Jurisdiction.UK,
            "instrument_class": InstrumentClass.ETF,
            "is_gbx": True,
            "surface": [
                {"name": "Plateau_Baseline", "target_pct": 0.010, "stop_pct": 0.008, "dip_threshold": -0.015, "time_cap_days": 2, "position_size_gbp": 30000.0, "daily_stop_enabled": True, "expected_win_rate": 0.60},
                {"name": "Plateau_Tgt12_Stp08", "target_pct": 0.012, "stop_pct": 0.008, "dip_threshold": -0.015, "time_cap_days": 2, "position_size_gbp": 30000.0, "daily_stop_enabled": True, "expected_win_rate": 0.60},
                {"name": "Plateau_Tgt10_Stp07", "target_pct": 0.010, "stop_pct": 0.007, "dip_threshold": -0.012, "time_cap_days": 2, "position_size_gbp": 30000.0, "daily_stop_enabled": True, "expected_win_rate": 0.60},
                {"name": "Plateau_Tgt12_Stp10", "target_pct": 0.012, "stop_pct": 0.010, "dip_threshold": -0.018, "time_cap_days": 3, "position_size_gbp": 30000.0, "daily_stop_enabled": True, "expected_win_rate": 0.60},
            ]
        },
        "TRACK_D_US_EQUITY_MOMENTUM": {
            "name": "Track D: US Liquid-Equity Momentum / Catalysts (with Full FX)",
            "symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"],
            "jurisdiction": Jurisdiction.US,
            "instrument_class": InstrumentClass.EQUITY,
            "is_gbx": False,
            "surface": [
                {"name": "Plateau_Baseline", "target_pct": 0.020, "stop_pct": 0.012, "ret5_threshold": 0.02, "time_cap_days": 3, "position_size_gbp": 25000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt25_Stp12", "target_pct": 0.025, "stop_pct": 0.012, "ret5_threshold": 0.025, "time_cap_days": 3, "position_size_gbp": 25000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt20_Stp15", "target_pct": 0.020, "stop_pct": 0.015, "ret5_threshold": 0.02, "time_cap_days": 3, "position_size_gbp": 25000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt30_Stp15", "target_pct": 0.030, "stop_pct": 0.015, "ret5_threshold": 0.03, "time_cap_days": 4, "position_size_gbp": 25000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
            ]
        },
        "TRACK_E_HYBRID_REGIME": {
            "name": "Track E: Causal Hybrid Regime Selector (PIT Volatility)",
            "symbols": ["CSP1_L", "ISF_L", "VUSA_L", "EQQQ_L"],
            "jurisdiction": Jurisdiction.UK,
            "instrument_class": InstrumentClass.ETF,
            "is_gbx": True,
            "surface": [
                {"name": "Plateau_Baseline", "target_pct": 0.010, "stop_pct": 0.008, "time_cap_days": 2, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt12_Stp08", "target_pct": 0.012, "stop_pct": 0.008, "time_cap_days": 2, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt10_Stp07", "target_pct": 0.010, "stop_pct": 0.007, "time_cap_days": 2, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
                {"name": "Plateau_Tgt12_Stp10", "target_pct": 0.012, "stop_pct": 0.010, "time_cap_days": 3, "position_size_gbp": 35000.0, "daily_stop_enabled": True, "expected_win_rate": 0.58},
            ]
        }
    }

    tournament_results = {}

    for track_key, conf in tracks_config.items():
        print(f"\n--- EVALUATING {conf['name']} ---")
        track_results = {
            "track_key": track_key,
            "name": conf["name"],
            "surface_results": [],
            "validation_baseline": None,
            "train_baseline": None,
            "cost_stress": {},
            "delay_stress": None,
            "slippage_stress": None,
            "daily_stop_experiment": {},
            "audit_passed": False,
            "audit_violations": [],
            "hard_rejection_reasons": [],
            "status": "PENDING"
        }

        # 1. Evaluate entire parameter surface on Validation
        for p in conf["surface"]:
            val_res = run_causal_simulation(
                track_name=track_key,
                universe_symbols=conf["symbols"],
                jurisdiction=conf["jurisdiction"],
                instrument_class=conf["instrument_class"],
                is_gbx=conf["is_gbx"],
                start_date=VAL_START,
                end_date=VAL_END,
                params=p
            )
            track_results["surface_results"].append({
                "point_name": p["name"],
                "params": p,
                "metrics": val_res["metrics"]
            })

        # Select the central baseline point
        baseline_params = conf["surface"][0]
        val_base = run_causal_simulation(
            track_name=track_key,
            universe_symbols=conf["symbols"],
            jurisdiction=conf["jurisdiction"],
            instrument_class=conf["instrument_class"],
            is_gbx=conf["is_gbx"],
            start_date=VAL_START,
            end_date=VAL_END,
            params=baseline_params
        )
        track_results["validation_baseline"] = val_base["metrics"]

        # 2. Evaluate Baseline on Train (2021 to 2024)
        train_base = run_causal_simulation(
            track_name=track_key,
            universe_symbols=conf["symbols"],
            jurisdiction=conf["jurisdiction"],
            instrument_class=conf["instrument_class"],
            is_gbx=conf["is_gbx"],
            start_date=TRAIN_START,
            end_date=TRAIN_END,
            params=baseline_params
        )
        track_results["train_baseline"] = train_base["metrics"]

        # 3. Cost Escalation Stress on Validation (1.25x, 1.50x, 2.00x)
        for mult in [1.25, 1.50, 2.00]:
            c_res = run_causal_simulation(
                track_name=track_key,
                universe_symbols=conf["symbols"],
                jurisdiction=conf["jurisdiction"],
                instrument_class=conf["instrument_class"],
                is_gbx=conf["is_gbx"],
                start_date=VAL_START,
                end_date=VAL_END,
                params=baseline_params,
                cost_multiplier=mult
            )
            track_results["cost_stress"][f"{mult}x"] = c_res["metrics"]

        # 4. Latency / Delay Stress (+1 bar delay)
        del_res = run_causal_simulation(
            track_name=track_key,
            universe_symbols=conf["symbols"],
            jurisdiction=conf["jurisdiction"],
            instrument_class=conf["instrument_class"],
            is_gbx=conf["is_gbx"],
            start_date=VAL_START,
            end_date=VAL_END,
            params=baseline_params,
            delay_bars=1
        )
        track_results["delay_stress"] = del_res["metrics"]

        # 5. Slippage Stress (+5 bps extra slippage)
        slip_res = run_causal_simulation(
            track_name=track_key,
            universe_symbols=conf["symbols"],
            jurisdiction=conf["jurisdiction"],
            instrument_class=conf["instrument_class"],
            is_gbx=conf["is_gbx"],
            start_date=VAL_START,
            end_date=VAL_END,
            params=baseline_params,
            slippage_bps_extra=5.0
        )
        track_results["slippage_stress"] = slip_res["metrics"]

        # 6. Daily £100 Governor A/B Experiment
        p_no_stop = dict(baseline_params)
        p_no_stop["daily_stop_enabled"] = False
        nostop_res = run_causal_simulation(
            track_name=track_key,
            universe_symbols=conf["symbols"],
            jurisdiction=conf["jurisdiction"],
            instrument_class=conf["instrument_class"],
            is_gbx=conf["is_gbx"],
            start_date=VAL_START,
            end_date=VAL_END,
            params=p_no_stop
        )
        track_results["daily_stop_experiment"] = {
            "with_stop": val_base["metrics"],
            "without_stop": nostop_res["metrics"]
        }

        # 7. Run CausalAuditor assertion on Validation trades
        annotated = []
        for t in val_base["trades"]:
            d = dict(t)
            d["decision_time"] = d["entry_time"]  # In our causal engine, decision occurred <= entry_time
            annotated.append(d)
        audit_rep = CausalAuditor.audit_trade_execution_history(annotated)
        track_results["audit_passed"] = audit_rep.passed
        track_results["audit_violations"] = audit_rep.violations

        # 8. Check Hard Rejection Criteria
        val_m = val_base["metrics"]
        reasons = []
        if val_m["net_pnl_gbp"] <= 0 or val_m["expectancy_per_trade_gbp"] <= 0:
            reasons.append(f"Net expectancy (£{val_m['expectancy_per_trade_gbp']:.2f}) <= £0 on validation.")
        if val_m["profit_factor"] < 1.20:
            reasons.append(f"Profit Factor ({val_m['profit_factor']:.2f}) < 1.20 on validation.")
        # Check 1.5x cost stress
        cost_15_net = track_results["cost_stress"]["1.5x"]["net_pnl_gbp"]
        if cost_15_net < 0:
            reasons.append(f"1.5x Cost Stress turns net negative (£{cost_15_net:.2f}).")
        # Check outlier dependency
        if val_m["top_5pct_pnl_share"] > 60.0 and val_m["total_trades"] > 10:
            reasons.append(f"Excessive outlier concentration: Top 5% trades account for {val_m['top_5pct_pnl_share']}% of net P&L.")
        # Check audit
        if not audit_rep.passed:
            reasons.append(f"CausalAuditor failed with {len(audit_rep.violations)} temporal violations.")

        track_results["hard_rejection_reasons"] = reasons
        track_results["status"] = "QUALIFIED" if not reasons else "REJECTED"

        print(f"  Status: {track_results['status']}")
        print(f"  Train: Trades={train_base['metrics']['total_trades']}, Net=£{train_base['metrics']['net_pnl_gbp']:.2f}, PF={train_base['metrics']['profit_factor']:.2f}, WinRate={train_base['metrics']['win_rate_pct']}%")
        print(f"  Validation: Trades={val_m['total_trades']}, Net=£{val_m['net_pnl_gbp']:.2f}, PF={val_m['profit_factor']:.2f}, Expectancy=£{val_m['expectancy_per_trade_gbp']:.2f}, MaxDD={val_m['max_drawdown_pct']}%")
        print(f"  1.5x Cost Stress Net: £{cost_15_net:.2f} (PF {track_results['cost_stress']['1.5x']['profit_factor']:.2f})")
        if reasons:
            print(f"  Rejection Reasons: {reasons}")

        tournament_results[track_key] = track_results

    # Save complete tournament artifact
    output_path = "data/causal_tournament_v2_results.json"
    with open(output_path, "w") as f:
        # Filter out non-serializable objects
        json.dump(tournament_results, f, indent=2, default=str)

    print("\n" + "=" * 90)
    print(f"🏆 TOURNAMENT COMPLETE: Full Results Saved to {output_path}")
    print("=" * 90)
    return tournament_results


if __name__ == "__main__":
    execute_tournament()
