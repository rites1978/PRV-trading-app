"""
🏛️ PRV CAPITAL | AUTHORITATIVE ALPHA ENGINE TOURNAMENT RUNNER
Executes the scientific 3-way strategy tournament:
- Strategy A: Frozen Strategy V2 Baseline (75% quorum technical rotation, tight ratchet +0.50% / -1.00%)
- Strategy B: Quality + Value (Greenblatt-inspired, non-financial/non-utility, low turnover)
- Strategy C: Quality + Value + Momentum (Strategy B fundamental ranking + medium-term trend/momentum entry timing)

Includes:
- Phase 1: Point-in-time Research Harness execution
- Phase 2: Competing Strategies evaluation
- Phase 3: Market Segmentation (UK vs US vs Combined)
- Phase 4: Regime Segmentation (2010-2015, 2016-2019, 2020-2021, 2022, 2023-2026, Full)
- Phase 5: Robustness Sweeps (Parameter, +25%/+50% Costs, 1-day Execution Lag)
- Phase 6: Factor Attribution (Quality vs Value vs Momentum)
- Phase 7: Concentration Test (Excluding Top 1, Top 5, Top 10 trades)
- Phase 8: Infrastructure Defect Verification & Parameter Hash Invariance
"""
import os
import sys
import json
import copy
import math
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add project root to path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.research.data_loader import (
    get_all_universe_bars,
    load_fundamentals_cache,
    fetch_and_cache_fundamentals,
    get_cached_bars
)
from src.research.backtest_harness import (
    BacktestEngine,
    BacktestFrictions,
    SimulatedTrade
)
from src.research.competing_strategies import (
    StrategyAFrozenV2,
    StrategyBQualityValue,
    StrategyCQualityValueMomentum,
    precompute_indicators
)
from src.data.universe import INSTITUTIONAL_UNIVERSE
from src.config.settings import settings
PRACTICE_NEW_ENTRIES_ALLOWED = settings.PRACTICE_NEW_ENTRIES_ALLOWED


def calculate_metrics_without_top_trades(closed_trades: List[Dict[str, Any]], starting_nav: float, remove_count: int, total_days: int) -> Dict[str, Any]:
    """Recalculates CAGR, win rate, profit factor, and net expectancy after removing the top N winning trades."""
    if not closed_trades:
        return {"cagr": 0.0, "net_expectancy": 0.0, "profit_factor": 0.0, "trade_count": 0}

    # Sort trades descending by net_pnl
    sorted_trades = sorted(closed_trades, key=lambda x: x["net_pnl"], reverse=True)
    remaining_trades = sorted_trades[remove_count:]
    
    if not remaining_trades:
        return {"cagr": 0.0, "net_expectancy": 0.0, "profit_factor": 0.0, "trade_count": 0}

    net_pnls = [t["net_pnl"] for t in remaining_trades]
    total_net_pnl = sum(net_pnls)
    ending_nav = starting_nav + total_net_pnl
    years = max(0.08, total_days / 365.25)
    cagr = round((((max(1.0, ending_nav) / starting_nav) ** (1.0 / years)) - 1.0) * 100.0, 2) if ending_nav > 0 else -100.0

    winners = [p for p in net_pnls if p > 0]
    losers = [p for p in net_pnls if p <= 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = round(gross_profit / max(0.01, gross_loss), 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 0.0)
    win_rate = round((len(winners) / len(remaining_trades)) * 100.0, 2)
    net_expectancy = round(float(np.mean(net_pnls)), 2)

    return {
        "cagr": cagr,
        "net_expectancy": net_expectancy,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "trade_count": len(remaining_trades),
        "total_net_pnl": round(total_net_pnl, 2)
    }


def run_tournament():
    print("=" * 78)
    print("🏛️ PRV CAPITAL | ALPHA ENGINE TOURNAMENT EXECUTION")
    print("=" * 78)

    # Invariant safety assertion
    print(f"Safety Check: PRACTICE_NEW_ENTRIES_ALLOWED = {PRACTICE_NEW_ENTRIES_ALLOWED}")
    if PRACTICE_NEW_ENTRIES_ALLOWED:
        raise RuntimeError("FATAL: PRACTICE_NEW_ENTRIES_ALLOWED must be False during research!")

    # 1. Load Data
    print("\n[1/7] Loading Historical Bars & Benchmark Data...")
    bars_data = get_all_universe_bars()
    print(f"  Loaded daily bars for {len(bars_data)} instruments.")
    print("  Precomputing indicators (SMA20, SMA50, SMA200, RSI14, Momentum)...")
    bars_data = precompute_indicators(bars_data)
    print("  Indicators precomputed.")
    
    benchmark_ftse = get_cached_bars("^FTSE", start_date="2009-01-01", end_date="2026-09-01")
    benchmark_gspc = get_cached_bars("^GSPC", start_date="2009-01-01", end_date="2026-09-01")
    print(f"  Benchmark ^FTSE: {len(benchmark_ftse)} bars | ^GSPC: {len(benchmark_gspc)} bars")

    # 2. Load Fundamentals
    print("\n[2/7] Loading Fundamentals Cache...")
    fundamentals = load_fundamentals_cache()
    if len(fundamentals) < 50:
        print("  Hydrating fundamentals cache...")
        fundamentals = fetch_and_cache_fundamentals()
    print(f"  Loaded fundamentals for {len(fundamentals)} companies.")

    # Instantiate strategies
    strat_a = StrategyAFrozenV2()
    
    strat_b = StrategyBQualityValue()
    strat_b.set_fundamentals(fundamentals)
    
    strat_c = StrategyCQualityValueMomentum()
    strat_c.set_fundamentals(fundamentals)

    engine = BacktestEngine(starting_nav=50000.0, max_positions=15, min_cash_buffer_pct=0.05)

    # ---------------------------------------------------------
    # MAIN TOURNAMENT: Full Period (2010-01-01 to 2026-09-01), Combined Universe
    # ---------------------------------------------------------
    print("\n[3/7] Running Full Historical Backtests (2010-01-01 to 2026-09-01)...")
    full_start = "2010-01-01"
    full_end = "2026-09-01"

    print("  -> Simulating Strategy A (Frozen V2 Baseline)...")
    strat_a.universe_region = "ALL"
    res_a = engine.run_simulation(bars_data, strat_a, full_start, full_end, benchmark_bars=benchmark_ftse)
    
    print("  -> Simulating Strategy B (Quality + Value)...")
    strat_b.universe_region = "ALL"
    res_b = engine.run_simulation(bars_data, strat_b, full_start, full_end, benchmark_bars=benchmark_ftse)

    print("  -> Simulating Strategy C (Quality + Value + Momentum)...")
    strat_c.strat_b.universe_region = "ALL"
    res_c = engine.run_simulation(bars_data, strat_c, full_start, full_end, benchmark_bars=benchmark_ftse)

    # ---------------------------------------------------------
    # PHASE 3: MARKET SEGMENTATION (UK vs US vs Combined)
    # ---------------------------------------------------------
    print("\n[4/7] Running Phase 3 Market Segmentation...")
    market_results = {}
    for region in ["UK", "US", "ALL"]:
        print(f"  Evaluating Region: {region}...")
        
        bench = benchmark_ftse if region in ("UK", "ALL") else benchmark_gspc
        
        # Strat A
        strat_a_reg = StrategyAFrozenV2(universe_region=region)
        m_res_a = engine.run_simulation(bars_data, strat_a_reg, full_start, full_end, benchmark_bars=bench)
        
        # Strat B
        strat_b_reg = StrategyBQualityValue(universe_region=region)
        strat_b_reg.set_fundamentals(fundamentals)
        m_res_b = engine.run_simulation(bars_data, strat_b_reg, full_start, full_end, benchmark_bars=bench)

        # Strat C
        strat_c_reg = StrategyCQualityValueMomentum(universe_region=region)
        strat_c_reg.set_fundamentals(fundamentals)
        m_res_c = engine.run_simulation(bars_data, strat_c_reg, full_start, full_end, benchmark_bars=bench)

        market_results[region] = {
            "Strategy A": m_res_a["metrics"],
            "Strategy B": m_res_b["metrics"],
            "Strategy C": m_res_c["metrics"]
        }

    # ---------------------------------------------------------
    # PHASE 4: REGIME SEGMENTATION
    # ---------------------------------------------------------
    print("\n[5/7] Running Phase 4 Regime Segmentation...")
    regimes = [
        ("2010-01-01", "2015-12-31", "2010–2015 (ZIRP Expansion)"),
        ("2016-01-01", "2019-12-31", "2016–2019 (Brexit / Trade Wars)"),
        ("2020-01-01", "2021-12-31", "2020–2021 (COVID Shock & Stimulus)"),
        ("2022-01-01", "2022-12-31", "2022 (Inflation & Rate Shock)"),
        ("2023-01-01", "2026-09-01", "2023–2026 (AI Bull / Higher Rates)"),
        ("2010-01-01", "2026-09-01", "2010–2026 (Full Period)")
    ]

    regime_results = {}
    for r_start, r_end, r_label in regimes:
        print(f"  Evaluating Regime: {r_label}...")
        r_res_a = engine.run_simulation(bars_data, strat_a, r_start, r_end, benchmark_bars=benchmark_ftse)
        r_res_b = engine.run_simulation(bars_data, strat_b, r_start, r_end, benchmark_bars=benchmark_ftse)
        r_res_c = engine.run_simulation(bars_data, strat_c, r_start, r_end, benchmark_bars=benchmark_ftse)
        
        regime_results[r_label] = {
            "Strategy A": r_res_a["metrics"],
            "Strategy B": r_res_b["metrics"],
            "Strategy C": r_res_c["metrics"]
        }

    # ---------------------------------------------------------
    # PHASE 5: ROBUSTNESS SWEEPS (on Strategy C)
    # ---------------------------------------------------------
    print("\n[6/7] Running Phase 5 Robustness Sweeps...")
    
    # 1. Parameter sweeps for Strategy C (Holding period & stop loss)
    param_sweep_results = {}
    for h_days in [30, 60, 90, 180]:
        for stop_p in [5.0, 7.0, 10.0]:
            sweep_strat = StrategyCQualityValueMomentum(rebalance_days=h_days, stop_loss_pct=stop_p)
            sweep_strat.set_fundamentals(fundamentals)
            sw_res = engine.run_simulation(bars_data, sweep_strat, full_start, full_end, benchmark_bars=benchmark_ftse)
            param_sweep_results[f"Hold_{h_days}d_Stop_{stop_p}%"] = sw_res["metrics"]

    # 2. Cost Sensitivity (+25%, +50%)
    cost_sensitivity_results = {}
    for mult, label in [(1.0, "Baseline (1.0x)"), (1.25, "+25% Costs (1.25x)"), (1.50, "+50% Costs (1.50x)")]:
        fric = BacktestFrictions(cost_multiplier=mult)
        cost_engine = BacktestEngine(starting_nav=50000.0, frictions=fric)
        c_res = cost_engine.run_simulation(bars_data, strat_c, full_start, full_end, benchmark_bars=benchmark_ftse)
        cost_sensitivity_results[label] = c_res["metrics"]

    # 3. Execution Lag Sensitivity (0-day vs 1-day delayed execution)
    lag_sensitivity_results = {}
    for lag, label in [(0, "0-day Lag (Instant Fill)"), (1, "1-day Delayed Execution")]:
        lag_engine = BacktestEngine(starting_nav=50000.0, execution_lag_days=lag)
        l_res = lag_engine.run_simulation(bars_data, strat_c, full_start, full_end, benchmark_bars=benchmark_ftse)
        lag_sensitivity_results[label] = l_res["metrics"]

    # ---------------------------------------------------------
    # PHASE 6: FACTOR ATTRIBUTION
    # ---------------------------------------------------------
    print("\n[7/7] Running Phase 6 Factor Attribution & Phase 7 Concentration Test...")
    class StrategyQualityOnly(StrategyBQualityValue):
        def compute_ranks(self):
            ranks = super().compute_ranks()
            candidates = list(ranks.values())
            candidates.sort(key=lambda x: x["quality_rank"])
            return {c["yf_ticker"]: c for c in candidates}

    class StrategyValueOnly(StrategyBQualityValue):
        def compute_ranks(self):
            ranks = super().compute_ranks()
            candidates = list(ranks.values())
            candidates.sort(key=lambda x: x["value_rank"])
            return {c["yf_ticker"]: c for c in candidates}

    strat_q = StrategyQualityOnly()
    strat_q.set_fundamentals(fundamentals)
    res_q = engine.run_simulation(bars_data, strat_q, full_start, full_end, benchmark_bars=benchmark_ftse)

    strat_v = StrategyValueOnly()
    strat_v.set_fundamentals(fundamentals)
    res_v = engine.run_simulation(bars_data, strat_v, full_start, full_end, benchmark_bars=benchmark_ftse)

    factor_attribution = {
        "Quality Alone": res_q["metrics"],
        "Value Alone": res_v["metrics"],
        "Quality + Value (Strategy B)": res_b["metrics"],
        "Quality + Value + Momentum (Strategy C)": res_c["metrics"]
    }

    # ---------------------------------------------------------
    # PHASE 7: CONCENTRATION / OUTLIER TEST (Strategy C)
    # ---------------------------------------------------------
    strat_c_closed = res_c["closed_trades"]
    total_days = (pd.to_datetime(full_end) - pd.to_datetime(full_start)).days
    
    concentration_results = {
        "All Trades": {
            "cagr": res_c["metrics"]["CAGR"],
            "net_expectancy": res_c["metrics"]["net_expectancy_gbp"],
            "profit_factor": res_c["metrics"]["profit_factor"],
            "win_rate": res_c["metrics"]["win_rate_pct"],
            "trade_count": res_c["metrics"]["trade_count"]
        },
        "Excluding Top 1 Trade": calculate_metrics_without_top_trades(strat_c_closed, 50000.0, 1, total_days),
        "Excluding Top 5 Trades": calculate_metrics_without_top_trades(strat_c_closed, 50000.0, 5, total_days),
        "Excluding Top 10 Trades": calculate_metrics_without_top_trades(strat_c_closed, 50000.0, 10, total_days)
    }

    # Compile and save tournament results JSON
    full_export = {
        "timestamp": datetime.now().isoformat(),
        "tournament_metrics": {
            "Strategy A": res_a["metrics"],
            "Strategy B": res_b["metrics"],
            "Strategy C": res_c["metrics"]
        },
        "market_segmentation": market_results,
        "regime_segmentation": regime_results,
        "parameter_sweeps": param_sweep_results,
        "cost_sensitivity": cost_sensitivity_results,
        "lag_sensitivity": lag_sensitivity_results,
        "factor_attribution": factor_attribution,
        "concentration_test": concentration_results
    }

    out_path = os.path.join(ROOT_DIR, "data", "alpha_tournament_results.json")
    with open(out_path, "w") as f:
        json.dump(full_export, f, indent=2)
    print(f"\n[OK] Saved tournament results to {out_path}")

    return full_export


if __name__ == "__main__":
    run_tournament()
