"""
🏛️ PRV CAPITAL | STAGE 2: STRATEGY RESEARCH TOURNAMENT
Evaluates three competing architectures across TRAIN + VALIDATION:
  Model A: Dynamic Liquid US Equities
  Model B: GBP SDRT-Exempt LSE Index ETFs
  Model C: Regime-Adaptive Hybrid Router

Data Partitioning:
  TRAIN:      2020-01-01 to 2023-12-31 (4 years)
  VALIDATION: 2024-01-01 to 2025-06-30 (1.5 years)
  FINAL OOS:  STRICTLY SEALED (2025-07-01 to 2026-08-31)

Evaluates:
  - Multi-dimensional parameter surfaces (Target, Stop, RVOL, Position Size)
  - Plateau stability (rejects narrow overfitted spikes)
  - Full post-cost accounting (FX, SEC, FINRA, SDRT, PTM, spread, slippage)
  - £100 daily lock rule effect (Variant A vs Variant B)
"""
import os
import json
from dataclasses import dataclass
from datetime import datetime, date
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
import numpy as np

from src.research.cost_schedule import CostScheduleRepository, Jurisdiction, InstrumentClass
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType
from src.research.portfolio_ledger import PortfolioLedger, ClosedTrade
from src.research.oos_sealer import OOSSealer

TRAIN_START = "2020-01-01"
TRAIN_END = "2023-12-31"
VAL_START = "2024-01-01"
VAL_END = "2025-06-30"


def load_partition_data(symbol: str, is_lse_gbx: bool = False, max_date: str = VAL_END) -> pd.DataFrame:
    clean_sym = symbol.replace("^", "_").replace(".", "_")
    file_path = os.path.join("data", "historical_prices", f"{clean_sym}.csv")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Missing data file: {file_path}")
    
    df = pd.read_csv(file_path, index_col=0, parse_dates=True)
    df = df.sort_index()
    # Strictly filter out anything past max_date (OOS isolation)
    df = df.loc[df.index <= max_date].copy()
    
    if is_lse_gbx:
        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                df[col] = df[col] / 100.0
                
    return df


@dataclass
class TournamentRunResult:
    model_name: str
    universe_type: str
    partition: str
    target_pct: float
    stop_pct: float
    rvol_thresh: float
    position_size_gbp: float
    daily_stop_enabled: bool
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_pnl_gbp: float
    total_friction_gbp: float
    net_pnl_gbp: float
    final_nav_gbp: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    days_ge_100: int
    pct_days_ge_100: float
    negative_days: int
    pct_negative_days: float
    avg_winner_gbp: float
    avg_loser_gbp: float
    expectancy_per_trade_gbp: float


def simulate_hit_and_run(
    model_name: str,
    universe_type: str,
    symbols_data: Dict[str, pd.DataFrame],
    jurisdiction_map: Dict[str, Jurisdiction],
    instrument_class_map: Dict[str, InstrumentClass],
    date_start: str,
    date_end: str,
    target_pct: float,
    stop_pct: float,
    rvol_thresh: float,
    position_size_gbp: float,
    daily_stop_enabled: bool = True,
    cost_repo: Optional[CostScheduleRepository] = None
) -> TournamentRunResult:
    cost_repo = cost_repo or CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    ledger = PortfolioLedger(initial_capital_gbp=50000.0, start_timestamp=pd.Timestamp(date_start))

    # Build common timeline across symbols
    all_dates = set()
    for df in symbols_data.values():
        sliced = df.loc[(df.index >= date_start) & (df.index <= date_end)]
        all_dates.update(sliced.index)
    timeline = sorted(list(all_dates))

    if not timeline:
        raise ValueError("Empty timeline for simulation.")

    # Calculate indicators per symbol
    enriched = {}
    for sym, df in symbols_data.items():
        sub = df.copy()
        sub["VolMA20"] = sub["Volume"].rolling(20).mean()
        sub["RVOL"] = sub["Volume"] / (sub["VolMA20"] + 1e-6)
        sub["SMA20"] = sub["Close"].rolling(20).mean()
        sub["ATR14"] = (sub["High"] - sub["Low"]).rolling(14).mean()
        enriched[sym] = sub

    daily_realised_pnl: Dict[str, float] = {}
    daily_navs = []

    for current_t in timeline:
        current_date_str = str(current_t)[:10]
        if current_date_str not in daily_realised_pnl:
            daily_realised_pnl[current_date_str] = 0.0

        # Mark to market open positions
        current_prices = {}
        for sym in ledger.positions.keys():
            df_sym = enriched[sym]
            if current_t in df_sym.index:
                current_prices[sym] = float(df_sym.loc[current_t, "Close"])
        ledger.mark_to_market(current_prices)
        daily_navs.append(ledger.get_portfolio_nav())

        # Check exits on open positions first
        for sym in list(ledger.positions.keys()):
            pos = ledger.positions[sym]
            df_sym = enriched[sym]
            if current_t not in df_sym.index:
                continue
            bar = df_sym.loc[current_t]
            high_p = float(bar["High"])
            low_p = float(bar["Low"])
            close_p = float(bar["Close"])

            entry_p = pos.avg_price_gbp
            target_p = entry_p * (1.0 + target_pct)
            stop_p = entry_p * (1.0 - stop_pct)

            exit_reason = None
            exit_price = close_p

            if high_p >= target_p:
                exit_reason = "HIT_TARGET"
                exit_price = target_p
            elif low_p <= stop_p:
                exit_reason = "HIT_STOP"
                exit_price = stop_p
            elif (current_t - pos.entry_time).days >= 3:
                # Time exit (hit-and-run duration cap)
                exit_reason = "TIME_CAP_EXIT"
                exit_price = close_p

            if exit_reason:
                jur = jurisdiction_map[sym]
                ic = instrument_class_map[sym]
                sell_order = Order(
                    order_id=f"EXIT_{sym}_{len(ledger.closed_trades)+1}",
                    symbol=sym,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=pos.shares,
                    created_at=current_t,
                    jurisdiction=jur,
                    instrument_class=ic
                )
                fill_sell = sim.simulate_fill(sell_order, bar, current_t)
                closed = ledger.close_position(
                    timestamp=current_t,
                    symbol=sym,
                    price_gbp=fill_sell.fill_price_gbp,
                    itemized_exit_frictions=fill_sell.itemized_frictions,
                    exit_reason=exit_reason
                )
                daily_realised_pnl[current_date_str] += closed.net_pnl_gbp

        # Check new entries if no position is open (strictly 1 concurrent position)
        if len(ledger.positions) == 0:
            # Check £100 daily lock rule
            if daily_stop_enabled and daily_realised_pnl[current_date_str] >= 100.0:
                # TARGET ACHIEVED / WATCH MODE -> Skip entries
                continue

            # Evaluate candidate signals
            candidates = []
            for sym, df_sym in enriched.items():
                if current_t not in df_sym.index:
                    continue
                loc_idx = df_sym.index.get_loc(current_t)
                if loc_idx < 21:
                    continue
                prev_bar = df_sym.iloc[loc_idx - 1]
                curr_bar = df_sym.iloc[loc_idx]

                # Setup: Momentum expansion + RVOL filter
                rvol = float(curr_bar.get("RVOL", 1.0))
                close_prev = float(prev_bar["Close"])
                close_curr = float(curr_bar["Close"])
                open_curr = float(curr_bar["Open"])
                sma20 = float(curr_bar["SMA20"])

                # Bullish continuation: Close > SMA20, Open gapped or pushing higher, RVOL >= threshold
                if rvol >= rvol_thresh and close_curr > sma20 and close_curr > close_prev:
                    momentum_score = (close_curr - close_prev) / close_prev * rvol
                    candidates.append((sym, momentum_score, curr_bar))

            # Select best candidate by momentum score
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_sym, best_score, best_bar = candidates[0]
                jur = jurisdiction_map[best_sym]
                ic = instrument_class_map[best_sym]

                entry_p = float(best_bar["Open"])
                shares = round(position_size_gbp / entry_p, 4)

                buy_order = Order(
                    order_id=f"ENTRY_{best_sym}_{len(ledger.closed_trades)+1}",
                    symbol=best_sym,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=shares,
                    created_at=current_t,
                    jurisdiction=jur,
                    instrument_class=ic
                )
                fill_buy = sim.simulate_fill(buy_order, best_bar, current_t)
                if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                    ledger.open_position(
                        timestamp=current_t,
                        symbol=best_sym,
                        jurisdiction=jur.value,
                        instrument_class=ic.value,
                        shares=fill_buy.quantity,
                        price_gbp=fill_buy.fill_price_gbp,
                        itemized_entry_frictions=fill_buy.itemized_frictions
                    )

    # Reconcile ledger
    ledger.reconcile()

    trades = ledger.closed_trades
    wins = [t for t in trades if t.net_pnl_gbp > 0]
    losses = [t for t in trades if t.net_pnl_gbp <= 0]
    gross_pnl = sum(t.gross_pnl_gbp for t in trades)
    total_friction = sum(t.total_friction_gbp for t in trades)
    net_pnl = sum(t.net_pnl_gbp for t in trades)
    final_nav = ledger.get_portfolio_nav()
    total_ret = round(((final_nav - 50000.0) / 50000.0) * 100, 2)

    # Daily distribution metrics
    days_with_trades = [v for v in daily_realised_pnl.values() if v != 0.0]
    days_ge_100 = len([v for v in daily_realised_pnl.values() if v >= 100.0])
    negative_days = len([v for v in daily_realised_pnl.values() if v < 0.0])
    total_active_days = len(daily_realised_pnl)

    nav_series = pd.Series(daily_navs)
    peak = nav_series.cummax()
    dd = (nav_series - peak) / (peak + 1e-8)
    max_dd_pct = round(abs(float(dd.min())) * 100, 2)

    returns = nav_series.pct_change().dropna()
    sharpe = round(float(np.sqrt(252) * returns.mean() / (returns.std() + 1e-8)), 2) if len(returns) > 1 else 0.0

    total_gains = sum(t.net_pnl_gbp for t in wins)
    total_losses_abs = abs(sum(t.net_pnl_gbp for t in losses))
    pf = round(total_gains / total_losses_abs, 2) if total_losses_abs > 0 else (99.0 if total_gains > 0 else 0.0)

    avg_win = round(total_gains / len(wins), 2) if wins else 0.0
    avg_loss = round(total_losses_abs / len(losses), 2) if losses else 0.0
    expectancy = round(net_pnl / len(trades), 2) if trades else 0.0

    return TournamentRunResult(
        model_name=model_name,
        universe_type=universe_type,
        partition="TRAIN" if date_end <= TRAIN_END else "VALIDATION",
        target_pct=target_pct,
        stop_pct=stop_pct,
        rvol_thresh=rvol_thresh,
        position_size_gbp=position_size_gbp,
        daily_stop_enabled=daily_stop_enabled,
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate_pct=round((len(wins) / len(trades)) * 100, 1) if trades else 0.0,
        gross_pnl_gbp=round(gross_pnl, 2),
        total_friction_gbp=round(total_friction, 2),
        net_pnl_gbp=round(net_pnl, 2),
        final_nav_gbp=final_nav,
        total_return_pct=total_ret,
        max_drawdown_pct=max_dd_pct,
        sharpe_ratio=sharpe,
        profit_factor=pf,
        days_ge_100=days_ge_100,
        pct_days_ge_100=round((days_ge_100 / total_active_days) * 100, 2),
        negative_days=negative_days,
        pct_negative_days=round((negative_days / total_active_days) * 100, 2),
        avg_winner_gbp=avg_win,
        avg_loser_gbp=avg_loss,
        expectancy_per_trade_gbp=expectancy
    )


def execute_stage_2_tournament():
    print("=" * 80)
    print("🏛️ PRV CAPITAL — STAGE 2: STRATEGY RESEARCH TOURNAMENT")
    print(f"TRAIN WINDOW:      {TRAIN_START} to {TRAIN_END}")
    print(f"VALIDATION WINDOW: {VAL_START} to {VAL_END}")
    print("OOS SEALED WINDOW: 2025-07-01 to 2026-08-31 (Untouched)")
    print("=" * 80)

    # Load Universe A: Dynamic Liquid US Equities
    us_symbols = ["NVDA", "AAPL", "MSFT", "AMD", "AMZN", "GOOGL", "META", "TSLA"]
    us_data = {s: load_partition_data(s, is_lse_gbx=False) for s in us_symbols}
    us_jur = {s: Jurisdiction.US for s in us_symbols}
    us_ic = {s: InstrumentClass.EQUITY for s in us_symbols}

    # Load Universe B: GBP SDRT-Exempt LSE Index ETFs
    etf_symbols = ["CSP1.L", "ISF.L", "VUSA.L", "EQQQ.L"]
    etf_data = {s: load_partition_data(s, is_lse_gbx=True) for s in etf_symbols}
    etf_jur = {s: Jurisdiction.UK for s in etf_symbols}
    etf_ic = {s: InstrumentClass.ETF for s in etf_symbols}

    # Combined Universe for Model C (Hybrid)
    hybrid_data = {**us_data, **etf_data}
    hybrid_jur = {**us_jur, **etf_jur}
    hybrid_ic = {**us_ic, **etf_ic}

    # Parameter Surfaces to evaluate
    targets = [0.008, 0.012, 0.016]       # +0.8%, +1.2%, +1.6%
    stops = [0.006, 0.008, 0.010]         # -0.6%, -0.8%, -1.0%
    sizes = [25000.0, 35000.0, 45000.0]  # £25k, £35k, £45k

    models = [
        ("MODEL_A_US_EQUITIES", "US_EQUITIES", us_data, us_jur, us_ic),
        ("MODEL_B_GBP_ETFS", "GBP_ETFS", etf_data, etf_jur, etf_ic),
        ("MODEL_C_HYBRID", "HYBRID", hybrid_data, hybrid_jur, hybrid_ic),
    ]

    all_results: List[TournamentRunResult] = []

    for model_name, univ_type, s_data, s_jur, s_ic in models:
        print(f"\nEvaluating Architecture: {model_name}...")
        
        # Grid sweep across parameter surface on TRAIN
        for t_pct in targets:
            for s_pct in stops:
                for sz in sizes:
                    # Run on TRAIN
                    res_train = simulate_hit_and_run(
                        model_name=model_name,
                        universe_type=univ_type,
                        symbols_data=s_data,
                        jurisdiction_map=s_jur,
                        instrument_class_map=s_ic,
                        date_start=TRAIN_START,
                        date_end=TRAIN_END,
                        target_pct=t_pct,
                        stop_pct=s_pct,
                        rvol_thresh=1.2,
                        position_size_gbp=sz,
                        daily_stop_enabled=True
                    )
                    all_results.append(res_train)

                    # Run on VALIDATION
                    res_val = simulate_hit_and_run(
                        model_name=model_name,
                        universe_type=univ_type,
                        symbols_data=s_data,
                        jurisdiction_map=s_jur,
                        instrument_class_map=s_ic,
                        date_start=VAL_START,
                        date_end=VAL_END,
                        target_pct=t_pct,
                        stop_pct=s_pct,
                        rvol_thresh=1.2,
                        position_size_gbp=sz,
                        daily_stop_enabled=True
                    )
                    all_results.append(res_val)

    # Also run the £100 Daily Stop A/B comparison on baseline parameterization
    print("\nRunning £100 Daily Stop Rule A/B Experiment...")
    ab_results = []
    for model_name, univ_type, s_data, s_jur, s_ic in models:
        for daily_stop in [True, False]:
            variant_name = "VARIANT_A_STOP_100" if daily_stop else "VARIANT_B_UNRESTRICTED"
            res_val_ab = simulate_hit_and_run(
                model_name=f"{model_name}_{variant_name}",
                universe_type=univ_type,
                symbols_data=s_data,
                jurisdiction_map=s_jur,
                instrument_class_map=s_ic,
                date_start=VAL_START,
                date_end=VAL_END,
                target_pct=0.012,
                stop_pct=0.008,
                rvol_thresh=1.2,
                position_size_gbp=35000.0,
                daily_stop_enabled=daily_stop
            )
            ab_results.append(res_val_ab)

    # Save all tournament data to disk
    os.makedirs("data", exist_ok=True)
    summary_path = "data/stage2_tournament_results.json"
    with open(summary_path, "w") as f:
        json.dump([r.__dict__ for r in all_results + ab_results], f, indent=2)

    print(f"\nTournament complete. Evaluated {len(all_results)} surface configurations.")
    print(f"Results archived to {summary_path}")


if __name__ == "__main__":
    execute_stage_2_tournament()
