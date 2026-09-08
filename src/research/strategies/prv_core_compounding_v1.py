"""
🏛️ PRV CAPITAL | CORE COMPOUNDING ENGINE V1
Candidate ID: PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1
Status: FROZEN FOR ONE-SHOT OOS EVALUATION

Specification:
- Universe: CSP1_L, EQQQ_L, IWDA_L, ISF_L, EMIM_L, SGLN_L, IGLT_L (London SDRT-Exempt ETFs)
- Benchmark: _GSPC (S&P 500)
- Ranking Metric: 20-Day Annualized Sharpe Ratio = Ret20d / Vol20d
- Trend Gate: Asset Close > 200-day SMA AND Sharpe > 0.0
- Rebalance Horizon: 10 trading days (bi-weekly rotation)
- Position Sizing: £40,000 nominal (1 concurrent position max)
- Stop Loss: -2.0% protective stop from entry price
- Execution: Day-T 08:00 LSE Market Open
- Cost Model: Trading212 UK ETF schedule (0% SDRT, 0% FX, realistic bid-ask spread and slippage)
"""
import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Tuple

from src.research.cost_schedule import Jurisdiction, InstrumentClass, CostScheduleRepository
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType
from src.research.portfolio_ledger import PortfolioLedger, Position, ClosedTrade
from src.research.causal_engine import CausalPreEntryCostGate, CausalityViolationError
from src.research.causal_auditor import CausalAuditor
from scripts.run_causal_tournament_v2 import load_sanitized_data, compute_trade_metrics


FROZEN_UNIVERSE = [
    "CSP1_L",  # iShares Core S&P 500 UCITS ETF GBP
    "EQQQ_L",  # Invesco EQQQ Nasdaq 100 UCITS ETF GBP
    "IWDA_L",  # iShares Core MSCI World UCITS ETF GBP
    "ISF_L",   # iShares Core FTSE 100 UCITS ETF GBP
    "EMIM_L",  # iShares Core MSCI EM IMI UCITS ETF GBP
    "SGLN_L",  # iShares Physical Gold ETC GBP
    "IGLT_L"   # iShares Core UK Gilts UCITS ETF GBP
]

FROZEN_PARAMETERS = {
    "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
    "architecture_class": "PRV_CORE_COMPOUNDING_ENGINE",
    "mom_lookback_bars": 20,
    "vol_lookback_bars": 20,
    "rebalance_days": 10,
    "position_size_gbp": 40000.0,
    "max_concurrent_positions": 1,
    "stop_loss_pct": 0.02,
    "use_sharpe_metric": True,
    "regime_sma_lookback": 200,
    "execution_time_bst": "08:00:00",
    "cost_model": "TRADING212_UK_ETF_ZERO_SDRT_ZERO_FX",
    "slippage_model": "SQUARE_ROOT_IMPACT_2BPS_BASE"
}


def load_partition_data(symbols: List[str], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    """
    Loads daily historical price series strictly within [start_date, end_date].
    Computes all features rolling with ZERO future data leakage.
    """
    data = {}
    mom_lookback = FROZEN_PARAMETERS["mom_lookback_bars"]
    vol_lookback = FROZEN_PARAMETERS["vol_lookback_bars"]
    sma_len = FROZEN_PARAMETERS["regime_sma_lookback"]

    for s in symbols:
        clean_sym = s.replace("^", "_").replace(".", "_")
        p = os.path.join("data", "historical_prices", f"{clean_sym}.csv")
        if not os.path.exists(p):
            raise FileNotFoundError(f"Missing historical price data for {s}: {p}")

        df = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()

        # Normalize GBX to GBP
        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                df[col] = df[col] / 100.0

        # Features strictly calculated on historical rolling window
        df["SMA200"] = df["Close"].rolling(sma_len).mean()
        df["MOM"] = df["Close"].pct_change(mom_lookback)
        df["Vol20"] = df["Close"].pct_change().rolling(vol_lookback).std() * np.sqrt(252)
        df["MOM_SHARPE"] = df["MOM"] / (df["Vol20"] + 1e-4)

        # Slice strictly to bounds
        df_sliced = df.loc[(df.index >= start_date) & (df.index <= end_date)].copy()
        data[s] = df_sliced

    return data


def execute_prv_core_compounding_v1(
    start_date: str,
    end_date: str,
    cost_multiplier: float = 1.0,
    delay_bars: int = 0,
    initial_capital_gbp: float = 50000.0
) -> Dict[str, Any]:
    """
    Authoritative causal simulator for PRV Core Compounding Engine V1.
    Evaluates exact frozen rules on any designated chronological window.
    """
    cost_repo = CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    ledger = PortfolioLedger(initial_capital_gbp=initial_capital_gbp, start_timestamp=pd.Timestamp(start_date))

    data = load_partition_data(FROZEN_UNIVERSE, start_date, end_date)

    all_dates = set()
    for df in data.values():
        all_dates.update(df.index)
    timeline = sorted(list(all_dates))

    rebalance_days = FROZEN_PARAMETERS["rebalance_days"]
    position_size_gbp = FROZEN_PARAMETERS["position_size_gbp"]
    stop_pct = FROZEN_PARAMETERS["stop_loss_pct"]

    daily_realised = {}
    daily_navs = []
    days_since_rebal = 0
    pending_delayed_order = None

    for t_idx, current_t in enumerate(timeline):
        current_date_str = str(current_t)[:10]
        curr_d = pd.to_datetime(current_t).date()
        if current_date_str not in daily_realised:
            daily_realised[current_date_str] = 0.0

        # 1. Mark-to-market existing positions
        current_prices = {}
        for s in ledger.positions.keys():
            if current_t in data[s].index:
                current_prices[s] = float(data[s].loc[current_t, "Close"])
        ledger.mark_to_market(current_prices)
        daily_navs.append(ledger.get_portfolio_nav())

        days_since_rebal += 1

        # 2. Check pending delayed order from previous bar if delay_bars > 0
        if pending_delayed_order and len(ledger.positions) == 0:
            target_sym, p_shares = pending_delayed_order
            df_tgt = data[target_sym]
            if current_t in df_tgt.index:
                bar = df_tgt.loc[current_t]
                buy_order = Order(
                    order_id=f"ENTRY_DELAYED_{target_sym}_{len(ledger.closed_trades)+1}",
                    symbol=target_sym, side=OrderSide.BUY, order_type=OrderType.MARKET,
                    quantity=p_shares, created_at=current_t,
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
            pending_delayed_order = None

        if t_idx < 25:
            continue
        prev_t = timeline[t_idx - 1]

        should_rebalance = (days_since_rebal >= rebalance_days)

        # 3. Rank assets on Day T-1 Close (Point-in-time causality guaranteed)
        eligible = []
        for s in FROZEN_UNIVERSE:
            df_s = data[s]
            if prev_t not in df_s.index or current_t not in df_s.index:
                continue
            prev_bar = df_s.loc[prev_t]
            c_prev = float(prev_bar["Close"])
            sma200 = float(prev_bar["SMA200"])
            sharpe_score = float(prev_bar["MOM_SHARPE"])

            # Absolute trend gate: must be above 200d SMA and have positive Sharpe momentum
            if c_prev > sma200 and sharpe_score > 0.0:
                eligible.append((s, sharpe_score))

        target_sym = None
        if eligible:
            eligible.sort(key=lambda x: x[1], reverse=True)
            target_sym = eligible[0][0]

        # 4. Position management: check stop loss or rebalance rotation exit
        for s in list(ledger.positions.keys()):
            pos = ledger.positions[s]
            df_s = data[s]
            if current_t not in df_s.index:
                continue
            bar = df_s.loc[current_t]
            need_exit = False
            exit_reason = "REBALANCE_ROTATION"

            low_p = float(bar["Low"])
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

        # 5. Open target position at Day T Open if flat and target identified
        if should_rebalance:
            days_since_rebal = 0
            if len(ledger.positions) == 0 and target_sym:
                df_tgt = data[target_sym]
                if current_t in df_tgt.index:
                    curr_open = float(df_tgt.loc[current_t, "Open"])
                    shares = round(position_size_gbp / curr_open, 4)

                    if delay_bars > 0:
                        pending_delayed_order = (target_sym, shares)
                    else:
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
    return {
        "strategy_id": FROZEN_PARAMETERS["strategy_id"],
        "parameters": FROZEN_PARAMETERS,
        "metrics": metrics,
        "trades": [t.__dict__ for t in trades],
        "daily_realised": daily_realised,
        "daily_navs": daily_navs
    }
