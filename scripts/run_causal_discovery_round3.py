"""
🏛️ PRV CAPITAL | CAUSAL STRATEGY DISCOVERY ROUND 3
Parallel Search Across Causal Architectures on Train and Validation Partitions.
Sealed OOS (2025-07-01 to 2026-08-31) is STRICTLY LOCKED & PROHIBITED.

Tracks Evaluated:
1. Cross-Sectional ETF Relative Strength / Dispersion (Multi-Asset London SDRT-Exempt ETFs)
2. Opening-Range Momentum (LSE Opening Breakout Proxy)
3. Abnormal Dislocation Mean Reversion (Bollinger / RSI Stretch)
4. Gap Continuation vs Gap Fade
5. Event / Catalyst Momentum (Data Integrity Evaluation)
6. Passive Limit-Order / Microstructure Edge (LOB Data Evaluation)
7. Regime-Conditioned Hybrid (Ex-Ante Macro Selector)
"""
import os
import sys
sys.path.insert(0, os.path.abspath("."))
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Tuple

from src.research.cost_schedule import Jurisdiction, InstrumentClass, CostScheduleRepository
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType
from src.research.portfolio_ledger import PortfolioLedger, Position, ClosedTrade
from src.research.causal_engine import CausalPreEntryCostGate, CausalityViolationError
from src.research.causal_auditor import CausalAuditor
from scripts.run_causal_tournament_v2 import load_sanitized_data, compute_rsi, compute_trade_metrics, TRAIN_START, TRAIN_END, VAL_START, VAL_END

SEALED_OOS_START = "2025-07-01"


def run_track1_cross_sectional_etf(start_date: str, end_date: str, params: Dict[str, Any], cost_multiplier: float = 1.0, delay_bars: int = 0) -> Dict[str, Any]:
    """
    Track 1: Cross-Sectional ETF Relative Strength / Dispersion.
    Ranks liquid SDRT-exempt ETFs by trailing point-in-time momentum.
    """
    if pd.Timestamp(end_date) >= pd.Timestamp(SEALED_OOS_START):
        raise CausalityViolationError(f"OOS violation: {end_date}")

    cost_repo = CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    cost_gate = CausalPreEntryCostGate(cost_repo)
    ledger = PortfolioLedger(initial_capital_gbp=50000.0, start_timestamp=pd.Timestamp(start_date))

    universe = ["CSP1_L", "EQQQ_L", "IWDA_L", "ISF_L", "EMIM_L", "SGLN_L", "IGLT_L"]
    data = {}
    mom_lookback = params.get("mom_lookback", 20)
    for s in universe:
        df = load_sanitized_data(s, is_gbx=True)
        df["SMA200"] = df["Close"].rolling(200).mean()
        df["MOM"] = df["Close"].pct_change(mom_lookback)
        df["Vol20"] = df["Close"].pct_change().rolling(20).std() * np.sqrt(252)
        df["MOM_SHARPE"] = df["MOM"] / (df["Vol20"] + 1e-4)
        data[s] = df

    df_bench = load_sanitized_data("_GSPC", is_gbx=False)
    df_bench["SMA200"] = df_bench["Close"].rolling(200).mean()

    all_dates = set()
    for df in data.values():
        all_dates.update(df.loc[(df.index >= start_date) & (df.index <= end_date)].index)
    timeline = sorted(list(all_dates))

    rebalance_days = params.get("rebalance_days", 5) # weekly rebalance
    position_size_gbp = params.get("position_size_gbp", 40000.0)
    use_sharpe = params.get("use_sharpe", False)

    daily_realised = {}
    daily_navs = []
    days_since_rebal = 0

    for t_idx, current_t in enumerate(timeline):
        current_date_str = str(current_t)[:10]
        curr_d = pd.to_datetime(current_t).date()
        if current_date_str not in daily_realised:
            daily_realised[current_date_str] = 0.0

        # Mark to market
        current_prices = {}
        for s in ledger.positions.keys():
            if current_t in data[s].index:
                current_prices[s] = float(data[s].loc[current_t, "Close"])
        ledger.mark_to_market(current_prices)
        daily_navs.append(ledger.get_portfolio_nav())

        days_since_rebal += 1

        if t_idx < 25:
            continue
        prev_t = timeline[t_idx - 1]

        # Check rebalance condition
        should_rebalance = (days_since_rebal >= rebalance_days)

        # Rank assets on Day T-1 Close
        eligible = []
        for s in universe:
            df_s = data[s]
            if prev_t not in df_s.index or current_t not in df_s.index:
                continue
            prev_bar = df_s.loc[prev_t]
            c_prev = float(prev_bar["Close"])
            sma200 = float(prev_bar["SMA200"])
            score = float(prev_bar["MOM_SHARPE"] if use_sharpe else prev_bar["MOM"])

            # Must be in long-term uptrend and positive momentum
            if c_prev > sma200 and score > 0.0:
                eligible.append((s, score))

        target_sym = None
        if eligible:
            eligible.sort(key=lambda x: x[1], reverse=True)
            target_sym = eligible[0][0]

        # If holding a position that is no longer target or no longer eligible, close it
        for s in list(ledger.positions.keys()):
            pos = ledger.positions[s]
            df_s = data[s]
            if current_t not in df_s.index:
                continue
            bar = df_s.loc[current_t]
            need_exit = False
            exit_reason = "REBALANCE"

            # Check stop loss
            low_p = float(bar["Low"])
            stop_pct = params.get("stop_pct", 0.02)
            if low_p <= pos.avg_price_gbp * (1.0 - stop_pct):
                need_exit = True
                exit_reason = "STOP_LOSS"
            elif should_rebalance and s != target_sym:
                need_exit = True
                exit_reason = "REBALANCE_ROTATION"

            if need_exit:
                sell_order = Order(
                    order_id=f"EXIT_{s}_{len(ledger.closed_trades)+1}",
                    symbol=s, side=OrderSide.SELL, order_type=OrderType.MARKET,
                    quantity=pos.shares, created_at=current_t,
                    jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                )
                fill_sell = sim.simulate_fill(sell_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_sell.itemized_frictions.items()}
                closed = ledger.close_position(
                    timestamp=current_t, symbol=s, price_gbp=fill_sell.fill_price_gbp,
                    itemized_exit_frictions=adj_frictions, exit_reason=exit_reason
                )
                daily_realised[current_date_str] += closed.net_pnl_gbp

        # Open target position if flat and target_sym identified
        if should_rebalance:
            days_since_rebal = 0
            if len(ledger.positions) == 0 and target_sym:
                df_tgt = data[target_sym]
                if current_t in df_tgt.index:
                    curr_open = float(df_tgt.loc[current_t, "Open"])
                    shares = round(position_size_gbp / curr_open, 4)
                    bar = df_tgt.loc[current_t]
                    buy_order = Order(
                        order_id=f"ENTRY_{target_sym}_{len(ledger.closed_trades)+1}",
                        symbol=target_sym, side=OrderSide.BUY, order_type=OrderType.MARKET,
                        quantity=shares, created_at=current_t,
                        jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                    )
                    fill_buy = sim.simulate_fill(buy_order, bar, current_t)
                    adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_buy.itemized_frictions.items()}
                    if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                        ledger.open_position(
                            timestamp=current_t, symbol=target_sym, jurisdiction=Jurisdiction.UK.value,
                            instrument_class=InstrumentClass.ETF.value, shares=fill_buy.quantity,
                            price_gbp=fill_buy.fill_price_gbp, itemized_entry_frictions=adj_frictions
                        )

    ledger.reconcile()
    trades = ledger.closed_trades
    metrics = compute_trade_metrics(trades, daily_realised=daily_realised, daily_navs=daily_navs)
    return {"track": "TRACK_1_CROSS_SECTIONAL_ETF", "params": params, "metrics": metrics, "trades": [t.__dict__ for t in trades]}


def run_track4_gap_strategy(start_date: str, end_date: str, mode: str, params: Dict[str, Any], cost_multiplier: float = 1.0) -> Dict[str, Any]:
    """
    Track 4: Gap Continuation vs Gap Fade on liquid SDRT-exempt ETFs.
    mode: "CONTINUATION" or "FADE"
    """
    if pd.Timestamp(end_date) >= pd.Timestamp(SEALED_OOS_START):
        raise CausalityViolationError(f"OOS violation: {end_date}")

    cost_repo = CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    cost_gate = CausalPreEntryCostGate(cost_repo)
    ledger = PortfolioLedger(initial_capital_gbp=50000.0, start_timestamp=pd.Timestamp(start_date))

    universe = ["CSP1_L", "EQQQ_L", "IWDA_L", "ISF_L"]
    data = {}
    for s in universe:
        df = load_sanitized_data(s, is_gbx=True)
        df["SMA200"] = df["Close"].rolling(200).mean()
        df["VolMA20"] = df["Volume"].rolling(20).mean()
        df["RVOL"] = df["Volume"] / (df["VolMA20"] + 1e-6)
        data[s] = df

    df_bench = load_sanitized_data("_GSPC", is_gbx=False)
    df_bench["SMA200"] = df_bench["Close"].rolling(200).mean()

    all_dates = set()
    for df in data.values():
        all_dates.update(df.loc[(df.index >= start_date) & (df.index <= end_date)].index)
    timeline = sorted(list(all_dates))

    target_pct = params.get("target_pct", 0.010)
    stop_pct = params.get("stop_pct", 0.008)
    time_cap_days = params.get("time_cap_days", 1)
    position_size_gbp = params.get("position_size_gbp", 35000.0)

    daily_realised = {}
    daily_navs = []

    for t_idx, current_t in enumerate(timeline):
        current_date_str = str(current_t)[:10]
        curr_d = pd.to_datetime(current_t).date()
        if current_date_str not in daily_realised:
            daily_realised[current_date_str] = 0.0

        current_prices = {s: float(data[s].loc[current_t, "Close"]) for s in ledger.positions.keys() if current_t in data[s].index}
        ledger.mark_to_market(current_prices)
        daily_navs.append(ledger.get_portfolio_nav())

        # Manage positions
        for s in list(ledger.positions.keys()):
            pos = ledger.positions[s]
            if current_t not in data[s].index:
                continue
            bar = data[s].loc[current_t]
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
                    jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                )
                fill_sell = sim.simulate_fill(sell_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_sell.itemized_frictions.items()}
                closed = ledger.close_position(
                    timestamp=current_t, symbol=s, price_gbp=fill_sell.fill_price_gbp,
                    itemized_exit_frictions=adj_frictions, exit_reason=exit_reason
                )
                daily_realised[current_date_str] += closed.net_pnl_gbp

        # Form entry decision
        if len(ledger.positions) == 0 and t_idx >= 25:
            prev_t = timeline[t_idx - 1]
            candidates = []

            for s in universe:
                df_s = data[s]
                if prev_t not in df_s.index or current_t not in df_s.index:
                    continue
                prev_bar = df_s.loc[prev_t]
                curr_open = float(df_s.loc[current_t, "Open"])
                prev_close = float(prev_bar["Close"])
                gap_pct = (curr_open - prev_close) / prev_close
                sma200 = float(prev_bar["SMA200"])

                triggered = False
                score = 0.0

                if mode == "CONTINUATION":
                    # Buy positive gap in bull trend
                    min_gap = params.get("min_gap", 0.004)
                    max_gap = params.get("max_gap", 0.015)
                    if prev_close > sma200 and min_gap <= gap_pct <= max_gap:
                        triggered = True
                        score = gap_pct
                elif mode == "FADE":
                    # Buy oversold gap down in long-term bull market (gap fill expectation)
                    fade_gap = params.get("fade_gap", -0.010)
                    if prev_close > sma200 and gap_pct <= fade_gap:
                        triggered = True
                        score = abs(gap_pct)

                if triggered:
                    target_p = curr_open * (1.0 + target_pct)
                    stop_p = curr_open * (1.0 - stop_pct)
                    assessment = cost_gate.assess_candidate(
                        symbol=s, jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF,
                        entry_price_gbp=curr_open, target_price_gbp=target_p, stop_price_gbp=stop_p,
                        nominal_position_gbp=position_size_gbp, expected_win_rate=0.58, trade_date=curr_d
                    )
                    if assessment.passed_economic_gate:
                        candidates.append((s, score, curr_open))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_s, best_score, best_open = candidates[0]
                shares = round(position_size_gbp / best_open, 4)
                bar = data[best_s].loc[current_t]
                buy_order = Order(
                    order_id=f"ENTRY_{best_s}_{len(ledger.closed_trades)+1}",
                    symbol=best_s, side=OrderSide.BUY, order_type=OrderType.MARKET,
                    quantity=shares, created_at=current_t,
                    jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                )
                fill_buy = sim.simulate_fill(buy_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_buy.itemized_frictions.items()}
                if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                    ledger.open_position(
                        timestamp=current_t, symbol=best_s, jurisdiction=Jurisdiction.UK.value,
                        instrument_class=InstrumentClass.ETF.value, shares=fill_buy.quantity,
                        price_gbp=fill_buy.fill_price_gbp, itemized_entry_frictions=adj_frictions
                    )

    ledger.reconcile()
    trades = ledger.closed_trades
    metrics = compute_trade_metrics(trades, daily_realised=daily_realised, daily_navs=daily_navs)
    return {"track": f"TRACK_4_GAP_{mode}", "params": params, "metrics": metrics, "trades": [t.__dict__ for t in trades]}


def run_track3_abnormal_dislocation(start_date: str, end_date: str, params: Dict[str, Any], cost_multiplier: float = 1.0) -> Dict[str, Any]:
    """
    Track 3: Abnormal Dislocation Mean Reversion (Bollinger Band Stretch in Secular Bull).
    """
    if pd.Timestamp(end_date) >= pd.Timestamp(SEALED_OOS_START):
        raise CausalityViolationError(f"OOS violation: {end_date}")

    cost_repo = CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    cost_gate = CausalPreEntryCostGate(cost_repo)
    ledger = PortfolioLedger(initial_capital_gbp=50000.0, start_timestamp=pd.Timestamp(start_date))

    universe = ["CSP1_L", "EQQQ_L", "IWDA_L"]
    data = {}
    for s in universe:
        df = load_sanitized_data(s, is_gbx=True)
        df["SMA200"] = df["Close"].rolling(200).mean()
        df["SMA20"] = df["Close"].rolling(20).mean()
        df["STD20"] = df["Close"].rolling(20).std()
        df["BB_LOWER"] = df["SMA20"] - 2.0 * df["STD20"]
        df["RSI14"] = compute_rsi(df["Close"], 14)
        data[s] = df

    all_dates = set()
    for df in data.values():
        all_dates.update(df.loc[(df.index >= start_date) & (df.index <= end_date)].index)
    timeline = sorted(list(all_dates))

    target_pct = params.get("target_pct", 0.012)
    stop_pct = params.get("stop_pct", 0.010)
    time_cap_days = params.get("time_cap_days", 3)
    position_size_gbp = params.get("position_size_gbp", 35000.0)

    daily_realised = {}
    daily_navs = []

    for t_idx, current_t in enumerate(timeline):
        current_date_str = str(current_t)[:10]
        curr_d = pd.to_datetime(current_t).date()
        if current_date_str not in daily_realised:
            daily_realised[current_date_str] = 0.0

        current_prices = {s: float(data[s].loc[current_t, "Close"]) for s in ledger.positions.keys() if current_t in data[s].index}
        ledger.mark_to_market(current_prices)
        daily_navs.append(ledger.get_portfolio_nav())

        for s in list(ledger.positions.keys()):
            pos = ledger.positions[s]
            if current_t not in data[s].index:
                continue
            bar = data[s].loc[current_t]
            high_p = float(bar["High"])
            low_p = float(bar["Low"])
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
                    jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                )
                fill_sell = sim.simulate_fill(sell_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_sell.itemized_frictions.items()}
                closed = ledger.close_position(
                    timestamp=current_t, symbol=s, price_gbp=fill_sell.fill_price_gbp,
                    itemized_exit_frictions=adj_frictions, exit_reason=exit_reason
                )
                daily_realised[current_date_str] += closed.net_pnl_gbp

        if len(ledger.positions) == 0 and t_idx >= 25:
            prev_t = timeline[t_idx - 1]
            candidates = []
            for s in universe:
                df_s = data[s]
                if prev_t not in df_s.index or current_t not in df_s.index:
                    continue
                prev_bar = df_s.loc[prev_t]
                c_prev = float(prev_bar["Close"])
                bb_low = float(prev_bar["BB_LOWER"])
                sma200 = float(prev_bar["SMA200"])
                rsi = float(prev_bar["RSI14"])
                curr_open = float(df_s.loc[current_t, "Open"])

                # Dislocation condition: Close pierced below 2-std lower band while long-term trend intact
                if c_prev < bb_low and c_prev > sma200 * 0.98 and rsi < 35.0:
                    disloc_pct = (bb_low - c_prev) / bb_low
                    candidates.append((s, disloc_pct, curr_open))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_s, best_score, best_open = candidates[0]
                shares = round(position_size_gbp / best_open, 4)
                bar = data[best_s].loc[current_t]
                buy_order = Order(
                    order_id=f"ENTRY_{best_s}_{len(ledger.closed_trades)+1}",
                    symbol=best_s, side=OrderSide.BUY, order_type=OrderType.MARKET,
                    quantity=shares, created_at=current_t,
                    jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                )
                fill_buy = sim.simulate_fill(buy_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_buy.itemized_frictions.items()}
                if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                    ledger.open_position(
                        timestamp=current_t, symbol=best_s, jurisdiction=Jurisdiction.UK.value,
                        instrument_class=InstrumentClass.ETF.value, shares=fill_buy.quantity,
                        price_gbp=fill_buy.fill_price_gbp, itemized_entry_frictions=adj_frictions
                    )

    ledger.reconcile()
    trades = ledger.closed_trades
    metrics = compute_trade_metrics(trades, daily_realised=daily_realised, daily_navs=daily_navs)
    return {"track": "TRACK_3_ABNORMAL_DISLOCATION", "params": params, "metrics": metrics, "trades": [t.__dict__ for t in trades]}


def run_track7_regime_hybrid(start_date: str, end_date: str, params: Dict[str, Any], cost_multiplier: float = 1.0) -> Dict[str, Any]:
    """
    Track 7: Regime-Conditioned Hybrid Selector (Ex-Ante Macro Decision):
    - When Benchmark > SMA200 and Vol < 16%: Cross-Sectional Relative Strength in Equities (CSP1, EQQQ, IWDA)
    - When Benchmark > SMA200 and Vol >= 16%: Dislocation Mean Reversion
    - When Benchmark <= SMA200: Safe Haven (SGLN Physical Gold if > SMA200, else 100% Cash)
    """
    if pd.Timestamp(end_date) >= pd.Timestamp(SEALED_OOS_START):
        raise CausalityViolationError(f"OOS violation: {end_date}")

    cost_repo = CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    cost_gate = CausalPreEntryCostGate(cost_repo)
    ledger = PortfolioLedger(initial_capital_gbp=50000.0, start_timestamp=pd.Timestamp(start_date))

    universe = ["CSP1_L", "EQQQ_L", "IWDA_L", "SGLN_L"]
    data = {}
    for s in universe:
        df = load_sanitized_data(s, is_gbx=True)
        df["SMA200"] = df["Close"].rolling(200).mean()
        df["SMA20"] = df["Close"].rolling(20).mean()
        df["STD20"] = df["Close"].rolling(20).std()
        df["BB_LOWER"] = df["SMA20"] - 2.0 * df["STD20"]
        df["Ret20d"] = df["Close"].pct_change(20)
        df["RSI14"] = compute_rsi(df["Close"], 14)
        data[s] = df

    df_bench = load_sanitized_data("_GSPC", is_gbx=False)
    df_bench["SMA200"] = df_bench["Close"].rolling(200).mean()
    df_bench["RealizedVol20"] = df_bench["Close"].pct_change().rolling(20).std() * np.sqrt(252)

    all_dates = set()
    for df in data.values():
        all_dates.update(df.loc[(df.index >= start_date) & (df.index <= end_date)].index)
    timeline = sorted(list(all_dates))

    target_pct = params.get("target_pct", 0.012)
    stop_pct = params.get("stop_pct", 0.008)
    time_cap_days = params.get("time_cap_days", 3)
    position_size_gbp = params.get("position_size_gbp", 35000.0)

    daily_realised = {}
    daily_navs = []

    for t_idx, current_t in enumerate(timeline):
        current_date_str = str(current_t)[:10]
        curr_d = pd.to_datetime(current_t).date()
        if current_date_str not in daily_realised:
            daily_realised[current_date_str] = 0.0

        current_prices = {s: float(data[s].loc[current_t, "Close"]) for s in ledger.positions.keys() if current_t in data[s].index}
        ledger.mark_to_market(current_prices)
        daily_navs.append(ledger.get_portfolio_nav())

        # Manage positions
        for s in list(ledger.positions.keys()):
            pos = ledger.positions[s]
            if current_t not in data[s].index:
                continue
            bar = data[s].loc[current_t]
            high_p = float(bar["High"])
            low_p = float(bar["Low"])
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
                    jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                )
                fill_sell = sim.simulate_fill(sell_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_sell.itemized_frictions.items()}
                closed = ledger.close_position(
                    timestamp=current_t, symbol=s, price_gbp=fill_sell.fill_price_gbp,
                    itemized_exit_frictions=adj_frictions, exit_reason=exit_reason
                )
                daily_realised[current_date_str] += closed.net_pnl_gbp

        # Form entry decision
        if len(ledger.positions) == 0 and t_idx >= 25:
            prev_t = timeline[t_idx - 1]
            prev_bench_rows = df_bench.loc[df_bench.index <= prev_t]
            if len(prev_bench_rows) == 0:
                continue
            bench_close = float(prev_bench_rows.iloc[-1]["Close"])
            bench_sma = float(prev_bench_rows.iloc[-1]["SMA200"])
            bench_vol = float(prev_bench_rows.iloc[-1]["RealizedVol20"])

            candidates = []

            if bench_close > bench_sma:
                if bench_vol < 0.16:
                    # Low vol: Relative Strength momentum among equities
                    for s in ["CSP1_L", "EQQQ_L", "IWDA_L"]:
                        df_s = data[s]
                        if prev_t in df_s.index and current_t in df_s.index:
                            pb = df_s.loc[prev_t]
                            c_p = float(pb["Close"])
                            sma200 = float(pb["SMA200"])
                            ret20 = float(pb["Ret20d"])
                            if c_p > sma200 and ret20 > 0.01:
                                candidates.append((s, ret20, float(df_s.loc[current_t, "Open"])))
                else:
                    # Elevated vol: Mean Reversion dislocation
                    for s in ["CSP1_L", "EQQQ_L", "IWDA_L"]:
                        df_s = data[s]
                        if prev_t in df_s.index and current_t in df_s.index:
                            pb = df_s.loc[prev_t]
                            c_p = float(pb["Close"])
                            bb_low = float(pb["BB_LOWER"])
                            sma200 = float(pb["SMA200"])
                            if c_p < bb_low and c_p > sma200 * 0.98:
                                disloc = (bb_low - c_p) / bb_low
                                candidates.append((s, disloc, float(df_s.loc[current_t, "Open"])))
            else:
                # Bear market: Safe Haven Gold
                s = "SGLN_L"
                df_s = data[s]
                if prev_t in df_s.index and current_t in df_s.index:
                    pb = df_s.loc[prev_t]
                    c_p = float(pb["Close"])
                    sma200 = float(pb["SMA200"])
                    ret20 = float(pb["Ret20d"])
                    if c_p > sma200 and ret20 > 0.005:
                        candidates.append((s, ret20, float(df_s.loc[current_t, "Open"])))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_s, best_score, best_open = candidates[0]
                shares = round(position_size_gbp / best_open, 4)
                bar = data[best_s].loc[current_t]
                buy_order = Order(
                    order_id=f"ENTRY_{best_s}_{len(ledger.closed_trades)+1}",
                    symbol=best_s, side=OrderSide.BUY, order_type=OrderType.MARKET,
                    quantity=shares, created_at=current_t,
                    jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                )
                fill_buy = sim.simulate_fill(buy_order, bar, current_t)
                adj_frictions = {k: round(v * cost_multiplier, 4) for k, v in fill_buy.itemized_frictions.items()}
                if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                    ledger.open_position(
                        timestamp=current_t, symbol=best_s, jurisdiction=Jurisdiction.UK.value,
                        instrument_class=InstrumentClass.ETF.value, shares=fill_buy.quantity,
                        price_gbp=fill_buy.fill_price_gbp, itemized_entry_frictions=adj_frictions
                    )

    ledger.reconcile()
    trades = ledger.closed_trades
    metrics = compute_trade_metrics(trades, daily_realised=daily_realised, daily_navs=daily_navs)
    return {"track": "TRACK_7_REGIME_HYBRID", "params": params, "metrics": metrics, "trades": [t.__dict__ for t in trades]}


def main():
    print("=" * 90)
    print("🏛️ PRV CAPITAL | CAUSAL STRATEGY DISCOVERY ROUND 3")
    print("Partitioning: TRAIN (2021-01-01 to 2024-06-30) | VALIDATION (2024-07-01 to 2025-06-30)")
    print("SEALED OOS (2025-07-01 to 2026-08-31) IS STRICTLY LOCKED & PROHIBITED")
    print("=" * 90)

    # 1. Track 1: Cross-Sectional ETF Relative Strength
    print("\n--- EVALUATING TRACK 1: CROSS-SECTIONAL ETF RELATIVE STRENGTH ---")
    p1 = {"mom_lookback": 20, "rebalance_days": 5, "position_size_gbp": 40000.0, "stop_pct": 0.02, "use_sharpe": False}
    t1_train = run_track1_cross_sectional_etf(TRAIN_START, TRAIN_END, p1)
    t1_val = run_track1_cross_sectional_etf(VAL_START, VAL_END, p1)
    t1_cost15 = run_track1_cross_sectional_etf(VAL_START, VAL_END, p1, cost_multiplier=1.5)

    # 2. Track 4A: Gap Continuation
    print("\n--- EVALUATING TRACK 4A: GAP CONTINUATION ---")
    p4a = {"min_gap": 0.003, "max_gap": 0.015, "target_pct": 0.010, "stop_pct": 0.008, "time_cap_days": 1, "position_size_gbp": 35000.0}
    t4a_train = run_track4_gap_strategy(TRAIN_START, TRAIN_END, "CONTINUATION", p4a)
    t4a_val = run_track4_gap_strategy(VAL_START, VAL_END, "CONTINUATION", p4a)
    t4a_cost15 = run_track4_gap_strategy(VAL_START, VAL_END, "CONTINUATION", p4a, cost_multiplier=1.5)

    # 3. Track 4B: Gap Fade
    print("\n--- EVALUATING TRACK 4B: GAP FADE ---")
    p4b = {"fade_gap": -0.008, "target_pct": 0.010, "stop_pct": 0.008, "time_cap_days": 2, "position_size_gbp": 35000.0}
    t4b_train = run_track4_gap_strategy(TRAIN_START, TRAIN_END, "FADE", p4b)
    t4b_val = run_track4_gap_strategy(VAL_START, VAL_END, "FADE", p4b)
    t4b_cost15 = run_track4_gap_strategy(VAL_START, VAL_END, "FADE", p4b, cost_multiplier=1.5)

    # 4. Track 3: Abnormal Dislocation Mean Reversion
    print("\n--- EVALUATING TRACK 3: ABNORMAL DISLOCATION MEAN REVERSION ---")
    p3 = {"target_pct": 0.012, "stop_pct": 0.010, "time_cap_days": 3, "position_size_gbp": 35000.0}
    t3_train = run_track3_abnormal_dislocation(TRAIN_START, TRAIN_END, p3)
    t3_val = run_track3_abnormal_dislocation(VAL_START, VAL_END, p3)
    t3_cost15 = run_track3_abnormal_dislocation(VAL_START, VAL_END, p3, cost_multiplier=1.5)

    # 5. Track 7: Regime-Conditioned Hybrid Selector
    print("\n--- EVALUATING TRACK 7: REGIME-CONDITIONED HYBRID SELECTOR ---")
    p7 = {"target_pct": 0.012, "stop_pct": 0.008, "time_cap_days": 3, "position_size_gbp": 35000.0}
    t7_train = run_track7_regime_hybrid(TRAIN_START, TRAIN_END, p7)
    t7_val = run_track7_regime_hybrid(VAL_START, VAL_END, p7)
    t7_cost15 = run_track7_regime_hybrid(VAL_START, VAL_END, p7, cost_multiplier=1.5)

    all_tracks = [
        ("Track 1: Cross-Sectional ETF Relative Strength", t1_train, t1_val, t1_cost15),
        ("Track 4A: Gap Continuation", t4a_train, t4a_val, t4a_cost15),
        ("Track 4B: Gap Fade", t4b_train, t4b_val, t4b_cost15),
        ("Track 3: Abnormal Dislocation Mean Reversion", t3_train, t3_val, t3_cost15),
        ("Track 7: Regime-Conditioned Hybrid", t7_train, t7_val, t7_cost15),
    ]

    results = {}
    print("\n==========================================================================")
    print("🏛️ PRV CAPITAL | ROUND 3 EARLY KILL SCORECARD")
    print("==========================================================================")

    for name, tr, va, c15 in all_tracks:
        tm = tr["metrics"]
        vm = va["metrics"]
        cm = c15["metrics"]

        trades_val = vm["total_trades"]
        net_val = vm["net_pnl_gbp"]
        pf_val = vm["profit_factor"]
        exp_val = vm["expectancy_per_trade_gbp"]
        exp_c15 = cm["expectancy_per_trade_gbp"]
        top5_share = vm.get("top_5pct_pnl_share", 0.0)

        # Early Kill Rules
        k1 = exp_val <= 0.0
        k2 = pf_val < 1.20
        k3 = exp_c15 < 0.0
        k4 = top5_share > 50.0 and net_val > 0.0
        k5 = trades_val < 12 # less than 1 trade per month

        killed = k1 or k2 or k3 or k4 or k5
        kill_reasons = []
        if k1: kill_reasons.append(f"Val Expectancy <= £0 (£{exp_val:.2f})")
        if k2: kill_reasons.append(f"Val PF < 1.20 ({pf_val:.2f})")
        if k3: kill_reasons.append(f"1.5x Cost Expectancy < £0 (£{exp_c15:.2f})")
        if k4: kill_reasons.append(f"Top 5% Outlier Share > 50% ({top5_share:.1f}%)")
        if k5: kill_reasons.append(f"Trade frequency too low ({trades_val} trades / 12m)")

        status = "KILLED" if killed else "SURVIVED"
        print(f"\n{name}:")
        print(f"  Train: Trades={tm['total_trades']}, Net=£{tm['net_pnl_gbp']:.2f}, PF={tm['profit_factor']:.2f}, Exp=£{tm['expectancy_per_trade_gbp']:.2f}, MaxDD={tm['max_drawdown_pct']:.2f}%")
        print(f"  Val:   Trades={vm['total_trades']}, Net=£{vm['net_pnl_gbp']:.2f}, PF={vm['profit_factor']:.2f}, Exp=£{vm['expectancy_per_trade_gbp']:.2f}, MaxDD={vm['max_drawdown_pct']:.2f}%")
        print(f"  1.5x:  Net=£{cm['net_pnl_gbp']:.2f}, Exp=£{cm['expectancy_per_trade_gbp']:.2f}, PF={cm['profit_factor']:.2f}")
        print(f"  Verdict: [{status}] -> {kill_reasons if killed else 'PASSED ALL EARLY KILL GATES'}")

        results[name] = {
            "train": tm,
            "validation": vm,
            "cost_15x": cm,
            "status": status,
            "kill_reasons": kill_reasons
        }

    # Track 5 and Track 6 Disqualifications
    results["Track 5: Event / Catalyst Momentum"] = {
        "status": "DISQUALIFIED",
        "kill_reasons": ["Missing point-in-time catalyst feed; cannot evaluate causally without hindsight data"]
    }
    results["Track 6: Passive Limit-Order / Microstructure Edge"] = {
        "status": "DISQUALIFIED",
        "kill_reasons": ["Missing Level 2 / LOB tick data; bid/ask imbalance modeling unsupported by OHLCV dataset"]
    }

    with open("data/causal_discovery_round3_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved Round 3 results to data/causal_discovery_round3_results.json")


if __name__ == "__main__":
    main()
