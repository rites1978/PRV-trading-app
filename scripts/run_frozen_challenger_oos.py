"""
🏛️ PRV CAPITAL | STAGE 3 & 4: CHALLENGER FREEZE & FINAL OOS EVALUATION
1. Freezes the winning Model B (GBP SDRT-Exempt Index ETFs) with cryptographic hashes.
2. Formally unseals the FINAL OOS partition (2025-07-01 to 2026-08-31) with auditor signature.
3. Executes the frozen challenger EXACTLY ONCE on the untouched Final OOS partition.
4. Generates complete performance, distribution, friction, and £100-stop comparison metrics.
5. If OOS net expectancy <= 0, stops immediately with 'NO STRATEGY VALIDATED'.
"""
import os
import json
import hashlib
from datetime import datetime, date, timezone
from typing import Dict, List, Any
import pandas as pd
import numpy as np

from src.research.cost_schedule import CostScheduleRepository, Jurisdiction, InstrumentClass
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType
from src.research.portfolio_ledger import PortfolioLedger, ClosedTrade
from src.research.oos_sealer import OOSSealer, OOSAccessViolationError

OOS_START = "2025-07-01"
OOS_END = "2026-08-31"

# Frozen Challenger Parameters
FROZEN_PARAMETERS = {
    "strategy_name": "PRV_HIT_AND_RUN_ETF_V1",
    "model_family": "MODEL_B_GBP_SDRT_EXEMPT_ETFS",
    "universe": ["CSP1.L", "ISF.L", "VUSA.L", "EQQQ.L"],
    "target_pct": 0.008,                # +0.80% profit target
    "stop_pct": 0.008,                  # -0.80% hard stop loss
    "rvol_threshold": 1.20,             # 1.2x 20-day volume expansion
    "position_size_gbp": 35000.0,       # £35,000 nominal capital deployment
    "max_concurrent_positions": 1,      # Strictly 1 position at a time
    "time_cap_days": 3,                 # Maximum 3-day holding period
    "daily_stop_enabled": True,         # £100 Daily Realised Net Profit -> Watch Mode
    "daily_stop_threshold_gbp": 100.0,
    "jurisdiction": "UK",
    "instrument_class": "ETF"
}


def load_raw_oos_data(symbol: str, is_lse_gbx: bool = True) -> pd.DataFrame:
    clean_sym = symbol.replace("^", "_").replace(".", "_")
    file_path = os.path.join("data", "historical_prices", f"{clean_sym}.csv")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Missing data file: {file_path}")
    
    df = pd.read_csv(file_path, index_col=0, parse_dates=True)
    df = df.sort_index()
    if is_lse_gbx:
        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                df[col] = df[col] / 100.0
    return df


def freeze_challenger_manifest(symbols_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """Generates cryptographic manifest for the frozen challenger."""
    # Hash parameters
    param_str = json.dumps(FROZEN_PARAMETERS, sort_keys=True)
    param_hash = hashlib.sha256(param_str.encode("utf-8")).hexdigest()

    # Hash code file
    with open(__file__, "rb") as f:
        code_hash = hashlib.sha256(f.read()).hexdigest()

    # Hash cost schedule file
    cost_file = os.path.join("src", "research", "cost_schedule.py")
    with open(cost_file, "rb") as f:
        cost_hash = hashlib.sha256(f.read()).hexdigest()

    # Seal OOS data with OOSSealer
    sealer = OOSSealer(oos_start=OOS_START, oos_end=OOS_END)
    data_manifest_hash = sealer.seal_oos_partition(symbols_data)

    manifest = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "strategy_name": FROZEN_PARAMETERS["strategy_name"],
        "parameters": FROZEN_PARAMETERS,
        "parameter_hash": param_hash,
        "code_hash": code_hash,
        "cost_schedule_hash": cost_hash,
        "data_manifest_hash": data_manifest_hash,
        "oos_window": f"{OOS_START} to {OOS_END}"
    }

    manifest_path = "data/frozen_challenger_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"🔒 CHALLENGER FROZEN: Manifest written to {manifest_path}")
    print(f"  Parameter Hash: {param_hash}")
    print(f"  Data Hash:      {data_manifest_hash}")
    return manifest


def run_single_oos_pass(
    symbols_data: Dict[str, pd.DataFrame],
    daily_stop_enabled: bool = True
) -> Dict[str, Any]:
    cost_repo = CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    ledger = PortfolioLedger(initial_capital_gbp=50000.0, start_timestamp=pd.Timestamp(OOS_START))

    # Build timeline
    all_dates = set()
    for df in symbols_data.values():
        sliced = df.loc[(df.index >= OOS_START) & (df.index <= OOS_END)]
        all_dates.update(sliced.index)
    timeline = sorted(list(all_dates))

    enriched = {}
    for sym, df in symbols_data.items():
        sub = df.copy()
        sub["VolMA20"] = sub["Volume"].rolling(20).mean()
        sub["RVOL"] = sub["Volume"] / (sub["VolMA20"] + 1e-6)
        sub["SMA20"] = sub["Close"].rolling(20).mean()
        enriched[sym] = sub

    daily_realised: Dict[str, float] = {}
    daily_navs = []
    capital_deployed_history = []

    target_pct = FROZEN_PARAMETERS["target_pct"]
    stop_pct = FROZEN_PARAMETERS["stop_pct"]
    position_size_gbp = FROZEN_PARAMETERS["position_size_gbp"]
    rvol_thresh = FROZEN_PARAMETERS["rvol_threshold"]

    for current_t in timeline:
        current_date_str = str(current_t)[:10]
        if current_date_str not in daily_realised:
            daily_realised[current_date_str] = 0.0

        # Mark to market
        current_prices = {}
        for sym in ledger.positions.keys():
            df_sym = enriched[sym]
            if current_t in df_sym.index:
                current_prices[sym] = float(df_sym.loc[current_t, "Close"])
        ledger.mark_to_market(current_prices)
        daily_navs.append(ledger.get_portfolio_nav())

        # Check exits
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
            elif (current_t - pos.entry_time).days >= FROZEN_PARAMETERS["time_cap_days"]:
                exit_reason = "TIME_CAP_EXIT"
                exit_price = close_p

            if exit_reason:
                sell_order = Order(
                    order_id=f"OOS_EXIT_{sym}_{len(ledger.closed_trades)+1}",
                    symbol=sym,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=pos.shares,
                    created_at=current_t,
                    jurisdiction=Jurisdiction.UK,
                    instrument_class=InstrumentClass.ETF
                )
                fill_sell = sim.simulate_fill(sell_order, bar, current_t)
                closed = ledger.close_position(
                    timestamp=current_t,
                    symbol=sym,
                    price_gbp=fill_sell.fill_price_gbp,
                    itemized_exit_frictions=fill_sell.itemized_frictions,
                    exit_reason=exit_reason
                )
                daily_realised[current_date_str] += closed.net_pnl_gbp

        # Check new entry
        if len(ledger.positions) == 0:
            if daily_stop_enabled and daily_realised[current_date_str] >= FROZEN_PARAMETERS["daily_stop_threshold_gbp"]:
                continue

            candidates = []
            for sym, df_sym in enriched.items():
                if current_t not in df_sym.index:
                    continue
                loc_idx = df_sym.index.get_loc(current_t)
                if loc_idx < 21:
                    continue
                prev_bar = df_sym.iloc[loc_idx - 1]
                curr_bar = df_sym.iloc[loc_idx]

                rvol = float(curr_bar.get("RVOL", 1.0))
                close_prev = float(prev_bar["Close"])
                close_curr = float(curr_bar["Close"])
                sma20 = float(curr_bar["SMA20"])

                if rvol >= rvol_thresh and close_curr > sma20 and close_curr > close_prev:
                    score = (close_curr - close_prev) / close_prev * rvol
                    candidates.append((sym, score, curr_bar))

            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_sym, best_score, best_bar = candidates[0]
                entry_p = float(best_bar["Open"])
                shares = round(position_size_gbp / entry_p, 4)

                buy_order = Order(
                    order_id=f"OOS_ENTRY_{best_sym}_{len(ledger.closed_trades)+1}",
                    symbol=best_sym,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=shares,
                    created_at=current_t,
                    jurisdiction=Jurisdiction.UK,
                    instrument_class=InstrumentClass.ETF
                )
                fill_buy = sim.simulate_fill(buy_order, best_bar, current_t)
                if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                    ledger.open_position(
                        timestamp=current_t,
                        symbol=best_sym,
                        jurisdiction="UK",
                        instrument_class="ETF",
                        shares=fill_buy.quantity,
                        price_gbp=fill_buy.fill_price_gbp,
                        itemized_entry_frictions=fill_buy.itemized_frictions
                    )
                    capital_deployed_history.append(fill_buy.notional_gbp)

    ledger.reconcile()

    trades = ledger.closed_trades
    wins = [t for t in trades if t.net_pnl_gbp > 0]
    losses = [t for t in trades if t.net_pnl_gbp <= 0]
    gross_pnl = sum(t.gross_pnl_gbp for t in trades)
    total_friction = sum(t.total_friction_gbp for t in trades)
    net_pnl = sum(t.net_pnl_gbp for t in trades)
    final_nav = ledger.get_portfolio_nav()
    total_return_pct = round(((final_nav - 50000.0) / 50000.0) * 100, 2)

    total_active_days = len(daily_realised)
    days_ge_100 = len([v for v in daily_realised.values() if v >= 100.0])
    positive_days = len([v for v in daily_realised.values() if v > 0.0])
    negative_days = len([v for v in daily_realised.values() if v < 0.0])
    largest_daily_loss = min(daily_realised.values()) if daily_realised else 0.0
    largest_daily_gain = max(daily_realised.values()) if daily_realised else 0.0

    nav_series = pd.Series(daily_navs)
    peak = nav_series.cummax()
    dd = (nav_series - peak) / (peak + 1e-8)
    max_dd_pct = round(abs(float(dd.min())) * 100, 2)
    max_dd_gbp = round(abs(float((nav_series - peak).min())), 2)

    returns = nav_series.pct_change().dropna()
    sharpe = round(float(np.sqrt(252) * returns.mean() / (returns.std() + 1e-8)), 2) if len(returns) > 1 else 0.0

    total_gains = sum(t.net_pnl_gbp for t in wins)
    total_losses_abs = abs(sum(t.net_pnl_gbp for t in losses))
    pf = round(total_gains / total_losses_abs, 2) if total_losses_abs > 0 else (99.0 if total_gains > 0 else 0.0)

    avg_win = round(total_gains / len(wins), 2) if wins else 0.0
    avg_loss = round(total_losses_abs / len(losses), 2) if losses else 0.0
    expectancy = round(net_pnl / len(trades), 2) if trades else 0.0
    avg_holding_sec = float(np.mean([t.holding_seconds for t in trades])) if trades else 0.0

    return {
        "variant": "VARIANT_A_STOP_100" if daily_stop_enabled else "VARIANT_B_UNRESTRICTED",
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": round((len(wins) / len(trades)) * 100, 1) if trades else 0.0,
        "gross_pnl_gbp": round(gross_pnl, 2),
        "total_friction_gbp": round(total_friction, 2),
        "net_pnl_gbp": round(net_pnl, 2),
        "final_nav_gbp": final_nav,
        "total_return_pct": total_return_pct,
        "max_drawdown_gbp": max_dd_gbp,
        "max_drawdown_pct": max_dd_pct,
        "sharpe_ratio": sharpe,
        "profit_factor": pf,
        "days_ge_100": days_ge_100,
        "pct_days_ge_100": round((days_ge_100 / total_active_days) * 100, 2),
        "positive_days": positive_days,
        "pct_positive_days": round((positive_days / total_active_days) * 100, 2),
        "negative_days": negative_days,
        "pct_negative_days": round((negative_days / total_active_days) * 100, 2),
        "largest_daily_loss_gbp": round(largest_daily_loss, 2),
        "largest_daily_gain_gbp": round(largest_daily_gain, 2),
        "avg_winner_gbp": avg_win,
        "avg_loser_gbp": avg_loss,
        "expectancy_per_trade_gbp": expectancy,
        "avg_holding_days": round(avg_holding_sec / 86400.0, 1),
        "avg_capital_deployed_gbp": round(float(np.mean(capital_deployed_history)), 2) if capital_deployed_history else 0.0,
        "trades": [t.__dict__ for t in trades]
    }


def execute_stage_3_and_4():
    print("=" * 80)
    print("🏛️ PRV CAPITAL — STAGE 3 & 4: CHALLENGER FREEZE & FINAL OOS EVALUATION")
    print("=" * 80)

    symbols = FROZEN_PARAMETERS["universe"]
    symbols_data = {s: load_raw_oos_data(s, is_lse_gbx=True) for s in symbols}

    # Step 1: Freeze Challenger Manifest
    manifest = freeze_challenger_manifest(symbols_data)

    # Step 2: Formally unseal OOS partition
    sealer = OOSSealer(oos_start=OOS_START, oos_end=OOS_END)
    sealer.seal_oos_partition(symbols_data)
    audit = sealer.unseal_for_final_audit(
        auditor_signature="PRV_AUTONOMOUS_CHIEF_RISK_OFFICER",
        rationale="Authorized execution of Stage 4 Final OOS Evaluation"
    )
    print(f"🔓 FINAL OOS UNSEALED: {audit['auditor_signature']} @ {audit['unsealed_at']}")

    # Step 3: Execute Single Final OOS Pass for Variant A (Stop at £100)
    print("\nExecuting Frozen Challenger on Final OOS (Variant A: Stop at £100)...")
    res_a = run_single_oos_pass(symbols_data, daily_stop_enabled=True)

    # Step 4: Execute Single Final OOS Pass for Variant B (Unrestricted)
    print("Executing Frozen Challenger on Final OOS (Variant B: Unrestricted)...")
    res_b = run_single_oos_pass(symbols_data, daily_stop_enabled=False)

    # Combine results
    oos_summary = {
        "manifest": manifest,
        "unseal_audit": audit,
        "variant_a_stop_100": {k: v for k, v in res_a.items() if k != "trades"},
        "variant_b_unrestricted": {k: v for k, v in res_b.items() if k != "trades"},
        "variant_a_trades_sample": res_a["trades"][:5]
    }

    output_path = "data/stage4_final_oos_results.json"
    with open(output_path, "w") as f:
        json.dump(oos_summary, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print("FINAL OUT-OF-SAMPLE (OOS) OFFICIAL RESULTS")
    print(f"OOS Window: {OOS_START} to {OOS_END} (14 Months)")
    print("=" * 80)
    va = res_a
    print(f"Total Trades:           {va['total_trades']} (Wins: {va['winning_trades']}, Losses: {va['losing_trades']})")
    print(f"Win Rate:               {va['win_rate_pct']}%")
    print(f"Gross P&L:              £{va['gross_pnl_gbp']:+,.2f}")
    print(f"Total Frictions Paid:   £{va['total_friction_gbp']:,.2f}")
    print(f"REALISED NET P&L:       £{va['net_pnl_gbp']:+,.2f}")
    print(f"Final Account NAV:      £{va['final_nav_gbp']:,.2f} ({va['total_return_pct']:+,.2f}%)")
    print(f"Expectancy Per Trade:   £{va['expectancy_per_trade_gbp']:+,.2f}")
    print(f"Profit Factor:          {va['profit_factor']:.2f}")
    print(f"Sharpe Ratio:           {va['sharpe_ratio']:.2f}")
    print(f"Maximum Drawdown:       £{va['max_drawdown_gbp']:,.2f} ({va['max_drawdown_pct']:.2f}%)")
    print(f"Average Winner:         £{va['avg_winner_gbp']:+,.2f}")
    print(f"Average Loser:          £{va['avg_loser_gbp']:+,.2f}")
    print(f"Days >= £100 Net:       {va['days_ge_100']} ({va['pct_days_ge_100']}%)")
    print(f"Profitable Days:        {va['positive_days']} ({va['pct_positive_days']}%)")
    print(f"Negative Days:          {va['negative_days']} ({va['pct_negative_days']}%)")
    print(f"Largest Daily Loss:     £{va['largest_daily_loss_gbp']:,.2f}")
    print(f"Average Capital Size:   £{va['avg_capital_deployed_gbp']:,.2f}")
    print(f"Average Holding Period: {va['avg_holding_days']} days")
    print("=" * 80)

    # Verification Decision
    if va["net_pnl_gbp"] <= 0 or va["expectancy_per_trade_gbp"] <= 0:
        print("\n❌ VERDICT: NO STRATEGY VALIDATED. OOS Net Expectancy is non-positive.")
        exit(1)
    else:
        print("\n✅ VERDICT: OOS PASS. Positive post-cost expectancy certified.")


if __name__ == "__main__":
    execute_stage_3_and_4()
