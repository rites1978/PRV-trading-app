"""
🏛️ PRV CAPITAL | STAGE 1: BASELINE CONTROL TOURNAMENT (TRAIN ONLY)
Runs predefined simple controls across TRAIN (2020-01-01 to 2023-12-31):
1. Cash Baseline (100% cash, zero trades)
2. Passive Buy-and-Hold ETF (CSP1 S&P 500 & ISF FTSE 100)
3. Simple Opening Range Breakout (ORB) Control
4. Simple 20-period Moving Average Trend Control

All controls evaluate on exact same clock, execution simulator, and versioned cost engine.
Zero optimization beyond predefined rules.
"""
import os
import json
import pandas as pd
import numpy as np
from datetime import date
from typing import Dict, List, Any

from src.research.cost_schedule import CostScheduleRepository, Jurisdiction, InstrumentClass
from src.research.execution_simulator import ExecutionSimulator
from src.research.benchmarks import BenchmarkEvaluator, BenchmarkResult
from src.research.oos_sealer import OOSSealer

TRAIN_START = "2020-01-01"
TRAIN_END = "2023-12-31"


def load_train_data(symbol: str, is_lse_gbx: bool = False) -> pd.DataFrame:
    clean_sym = symbol.replace("^", "_").replace(".", "_")
    file_path = os.path.join("data", "historical_prices", f"{clean_sym}.csv")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Missing data file: {file_path}")
    
    df = pd.read_csv(file_path, index_col=0, parse_dates=True)
    df = df.sort_index()
    
    # Filter strictly to TRAIN partition
    df_train = df.loc[(df.index >= TRAIN_START) & (df.index <= TRAIN_END)].copy()
    
    # Normalize GBX to GBP major unit if applicable
    if is_lse_gbx:
        for col in ["Open", "High", "Low", "Close"]:
            if col in df_train.columns:
                df_train[col] = df_train[col] / 100.0
                
    return df_train


def run_stage_1_baseline_controls() -> Dict[str, Any]:
    print("=" * 70)
    print("🏛️ PRV CAPITAL — STAGE 1: BASELINE CONTROL TOURNAMENT")
    print(f"Partition: TRAIN ONLY [{TRAIN_START} to {TRAIN_END}]")
    print("Initial Capital: £50,000.00 | Cost Engine: Official 2026 Versioned Schedule")
    print("=" * 70)

    cost_repo = CostScheduleRepository()
    sim = ExecutionSimulator(cost_repo)
    evaluator = BenchmarkEvaluator(sim, initial_capital_gbp=50000.0)

    results = []

    # 1. Cash Baseline
    cash_res = evaluator.run_cash_benchmark([])
    results.append(cash_res)
    print(f"1. CASH BASELINE: Return: {cash_res.total_return_pct:.2f}% | Max DD: {cash_res.max_drawdown_pct:.2f}% | Trades: {cash_res.total_trades}")

    # Load ETF & Equity Data
    df_csp1 = load_train_data("CSP1.L", is_lse_gbx=True)
    df_isf = load_train_data("ISF.L", is_lse_gbx=True)
    df_nvda = load_train_data("NVDA", is_lse_gbx=False)
    df_aapl = load_train_data("AAPL", is_lse_gbx=False)

    # 2. Passive Buy & Hold CSP1 (S&P 500 ETF - GBP)
    bh_csp1 = evaluator.run_passive_buy_and_hold(
        symbol="CSP1",
        df=df_csp1,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.ETF
    )
    results.append(bh_csp1)
    print(f"2. PASSIVE BUY & HOLD (CSP1 ETF): Return: {bh_csp1.total_return_pct:+.2f}% | Max DD: {bh_csp1.max_drawdown_pct:.2f}% | Sharpe: {bh_csp1.sharpe_ratio:.2f} | Friction: £{bh_csp1.total_friction_gbp:.2f}")

    # 3. Passive Buy & Hold ISF (FTSE 100 ETF - GBP)
    bh_isf = evaluator.run_passive_buy_and_hold(
        symbol="ISF",
        df=df_isf,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.ETF
    )
    results.append(bh_isf)
    print(f"3. PASSIVE BUY & HOLD (ISF ETF):  Return: {bh_isf.total_return_pct:+.2f}% | Max DD: {bh_isf.max_drawdown_pct:.2f}% | Sharpe: {bh_isf.sharpe_ratio:.2f} | Friction: £{bh_isf.total_friction_gbp:.2f}")

    # 4. Simple Trend Control (MA20) on CSP1 ETF
    trend_csp1 = evaluator.run_simple_trend_control(
        symbol="CSP1",
        df=df_csp1,
        ma_period=20,
        position_size_gbp=25000.0,
        target_pct=0.015,
        stop_pct=0.010,
        jurisdiction=Jurisdiction.UK,
        instrument_class=InstrumentClass.ETF
    )
    results.append(trend_csp1)
    print(f"4. SIMPLE TREND MA20 (CSP1 ETF):  Return: {trend_csp1.total_return_pct:+.2f}% | Net PnL: £{trend_csp1.net_pnl_gbp:+,.2f} | Trades: {trend_csp1.total_trades} (Win: {trend_csp1.win_rate_pct:.1f}%) | Friction: £{trend_csp1.total_friction_gbp:.2f} | Max DD: {trend_csp1.max_drawdown_pct:.2f}%")

    # 5. Simple Trend Control (MA20) on NVDA (US Equity)
    trend_nvda = evaluator.run_simple_trend_control(
        symbol="NVDA",
        df=df_nvda,
        ma_period=20,
        position_size_gbp=25000.0,
        target_pct=0.025,
        stop_pct=0.015,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.EQUITY
    )
    results.append(trend_nvda)
    print(f"5. SIMPLE TREND MA20 (NVDA US):   Return: {trend_nvda.total_return_pct:+.2f}% | Net PnL: £{trend_nvda.net_pnl_gbp:+,.2f} | Trades: {trend_nvda.total_trades} (Win: {trend_nvda.win_rate_pct:.1f}%) | Friction: £{trend_nvda.total_friction_gbp:.2f} | Max DD: {trend_nvda.max_drawdown_pct:.2f}%")

    # 6. Simple Trend Control (MA20) on AAPL (US Equity)
    trend_aapl = evaluator.run_simple_trend_control(
        symbol="AAPL",
        df=df_aapl,
        ma_period=20,
        position_size_gbp=25000.0,
        target_pct=0.020,
        stop_pct=0.012,
        jurisdiction=Jurisdiction.US,
        instrument_class=InstrumentClass.EQUITY
    )
    results.append(trend_aapl)
    print(f"6. SIMPLE TREND MA20 (AAPL US):   Return: {trend_aapl.total_return_pct:+.2f}% | Net PnL: £{trend_aapl.net_pnl_gbp:+,.2f} | Trades: {trend_aapl.total_trades} (Win: {trend_aapl.win_rate_pct:.1f}%) | Friction: £{trend_aapl.total_friction_gbp:.2f} | Max DD: {trend_aapl.max_drawdown_pct:.2f}%")

    # Summary table output
    summary = {
        "partition": "TRAIN",
        "window": f"{TRAIN_START} to {TRAIN_END}",
        "benchmarks": [
            {
                "name": r.benchmark_name,
                "trades": r.total_trades,
                "win_rate_pct": r.win_rate_pct,
                "gross_pnl_gbp": r.gross_pnl_gbp,
                "friction_gbp": r.total_friction_gbp,
                "net_pnl_gbp": r.net_pnl_gbp,
                "final_nav_gbp": r.final_nav_gbp,
                "return_pct": r.total_return_pct,
                "max_drawdown_pct": r.max_drawdown_pct,
                "sharpe": r.sharpe_ratio
            }
            for r in results
        ]
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/stage1_controls_results.json", "w") as f:
        json.dump(summary, f, indent=2)
        
    print("=" * 70)
    print("✅ Stage 1 Control Tournament Completed. Results written to data/stage1_controls_results.json")
    return summary


if __name__ == "__main__":
    run_stage_1_baseline_controls()
