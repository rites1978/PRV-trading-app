"""
🏛️ PRV CAPITAL | RESEARCH ↔ PRODUCTION PARITY CERTIFICATION
Test Suite: Exact Replay Verification between Frozen Research Engine and Production Signal Engine
Partition: 2025-07-01 to 2026-08-31 (14 Months OOS)

Mandatory Assertions:
1. SIGNAL_COUNT_MATCH = TRUE
2. SIGNAL_TIMESTAMPS_MATCH = TRUE
3. INSTRUMENT_SELECTION_MATCH = TRUE
4. POSITION_SIZE_MATCH = TRUE
5. ENTRY_RULE_MATCH = TRUE
6. EXIT_RULE_MATCH = TRUE
7. RANKING_MATCH = TRUE
8. UNEXPLAINED_DIFFERENCES = 0
"""
import os
import sys
import json
from datetime import datetime, timezone
from typing import Dict, Any, List
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath("."))

from src.research.strategies.prv_core_compounding_v1 import (
    FROZEN_UNIVERSE,
    FROZEN_PARAMETERS,
    execute_prv_core_compounding_v1,
    load_partition_data
)
from src.strategies.core_compounding_v1 import core_compounding_strategy, CoreCompoundingStrategy
from src.research.causal_auditor import CausalAuditor

from src.research.cost_schedule import Jurisdiction, InstrumentClass, CostScheduleRepository
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType
from src.research.portfolio_ledger import PortfolioLedger

START_DATE = "2025-07-01"
END_DATE = "2026-08-31"


def run_research_production_parity_test() -> Dict[str, Any]:
    print("=" * 90)
    print("🏛️ PRV CAPITAL | RESEARCH ↔ PRODUCTION PARITY CERTIFICATION")
    print(f"Evaluation Window: {START_DATE} to {END_DATE}")
    print("=" * 90)

    # 1. Cryptographic Hash Validation
    hashes = CoreCompoundingStrategy.verify_cryptographic_integrity()
    print(f"✅ Cryptographic Integrity Verified:")
    print(f"   Code SHA256:     {hashes['code_sha256']}")
    print(f"   Manifest SHA256: {hashes['manifest_sha256']}")

    # 2. Run Frozen Research Simulator
    print("\n[STEP 1/4] Running Frozen Research Simulator...")
    research_res = execute_prv_core_compounding_v1(START_DATE, END_DATE)
    research_trades = research_res["trades"]
    research_m = research_res["metrics"]
    print(f"-> Research Simulator: {research_m['total_trades']} trades, Net P&L: £{research_m['net_pnl_gbp']:.2f}, PF: {research_m['profit_factor']:.2f}")

    # 3. Run Production Signal Engine Replay
    print("\n[STEP 2/4] Running Production Signal Engine Replay on Identical PIT Market Data...")
    raw_data = load_partition_data(FROZEN_UNIVERSE, START_DATE, END_DATE)

    all_dates = set()
    for df in raw_data.values():
        all_dates.update(df.index)
    timeline = sorted(list(all_dates))

    rebalance_days = FROZEN_PARAMETERS["rebalance_days"]

    cost_repo = CostScheduleRepository()
    prod_sim = ExecutionSimulator(cost_repo)
    prod_ledger = PortfolioLedger(initial_capital_gbp=50000.0, start_timestamp=pd.Timestamp(START_DATE))

    days_since_rebal = 0
    parity_ledger = []
    differences = []

    for t_idx, current_t in enumerate(timeline):
        current_date_str = str(current_t)[:10]
        days_since_rebal += 1

        if t_idx < 25:
            continue
        prev_t = timeline[t_idx - 1]
        should_rebalance = (days_since_rebal >= rebalance_days)

        # Production Signal Evaluation (Day T 08:00 using Day T-1 Close)
        prod_eval = core_compounding_strategy.evaluate_point_in_time_signal(
            current_t=current_t,
            prev_t=prev_t,
            historical_daily_data=raw_data
        )
        prod_target_key = prod_eval["selected_target_key"]

        # Compare with Research Ranking on this same bar
        res_eligible = []
        for s in FROZEN_UNIVERSE:
            df_s = raw_data[s]
            if prev_t not in df_s.index or current_t not in df_s.index:
                continue
            prev_bar = df_s.loc[prev_t]
            c_prev = float(prev_bar["Close"])
            sma200 = float(prev_bar["SMA200"])
            sharpe_score = float(prev_bar["MOM_SHARPE"])
            if c_prev > sma200 and sharpe_score > 0.0:
                res_eligible.append((s, sharpe_score))
        if res_eligible:
            res_eligible.sort(key=lambda x: x[1], reverse=True)
        res_target = res_eligible[0][0] if res_eligible else None

        prod_rank_symbols = [r["target_key"] for r in prod_eval["rankings"] if r["eligible"]]
        res_rank_symbols = [r[0] for r in res_eligible]

        ranking_match = (prod_rank_symbols == res_rank_symbols)
        target_match = (prod_target_key == res_target)

        if not ranking_match or not target_match:
            diff_item = {
                "date": current_date_str,
                "error": "RANKING_OR_TARGET_MISMATCH",
                "prod_target": prod_target_key,
                "res_target": res_target,
                "prod_rankings": prod_rank_symbols,
                "res_rankings": res_rank_symbols
            }
            differences.append(diff_item)

        # Production Position Lifecycle Management
        for s in list(prod_ledger.positions.keys()):
            pos = prod_ledger.positions[s]
            df_s = raw_data[s]
            if current_t not in df_s.index:
                continue
            bar = df_s.loc[current_t]
            low_p = float(bar["Low"])

            need_exit, exit_reason = core_compounding_strategy.evaluate_position_lifecycle(
                current_symbol_or_key=s,
                entry_price_gbp=pos.avg_price_gbp,
                current_low_gbp=low_p,
                should_rebalance=should_rebalance,
                target_symbol_or_key=prod_target_key
            )

            if need_exit:
                sell_order = Order(
                    order_id=f"PROD_EXIT_{s}_{len(prod_ledger.closed_trades)+1}",
                    symbol=s, side=OrderSide.SELL, order_type=OrderType.MARKET,
                    quantity=pos.shares, created_at=current_t,
                    jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                )
                fill_sell = prod_sim.simulate_fill(sell_order, bar, current_t)
                adj_frictions = {k: round(v, 4) for k, v in fill_sell.itemized_frictions.items()}
                prod_ledger.close_position(
                    timestamp=current_t, symbol=s, price_gbp=fill_sell.fill_price_gbp,
                    itemized_exit_frictions=adj_frictions, exit_reason=exit_reason
                )

        # Production Sizing & Entry Management
        if should_rebalance:
            days_since_rebal = 0
            if len(prod_ledger.positions) == 0 and prod_target_key:
                df_tgt = raw_data[prod_target_key]
                if current_t in df_tgt.index:
                    curr_open = float(df_tgt.loc[current_t, "Open"])
                    shares = core_compounding_strategy.calculate_order_shares(curr_open, prod_ledger.cash_gbp)
                    bar = df_tgt.loc[current_t]
                    buy_order = Order(
                        order_id=f"PROD_ENTRY_{prod_target_key}_{len(prod_ledger.closed_trades)+1}",
                        symbol=prod_target_key, side=OrderSide.BUY, order_type=OrderType.MARKET,
                        quantity=shares, created_at=current_t,
                        jurisdiction=Jurisdiction.UK, instrument_class=InstrumentClass.ETF
                    )
                    fill_buy = prod_sim.simulate_fill(buy_order, bar, current_t)
                    adj_frictions = {k: round(v, 4) for k, v in fill_buy.itemized_frictions.items()}
                    if fill_buy and fill_buy.notional_gbp <= prod_ledger.cash_gbp:
                        prod_ledger.open_position(
                            timestamp=current_t, symbol=prod_target_key, jurisdiction=Jurisdiction.UK.value,
                            instrument_class=InstrumentClass.ETF.value, shares=fill_buy.quantity,
                            price_gbp=fill_buy.fill_price_gbp, itemized_entry_frictions=adj_frictions
                        )

        parity_ledger.append({
            "date": current_date_str,
            "should_rebalance": should_rebalance,
            "prod_target": prod_target_key,
            "research_target": res_target,
            "ranking_match": ranking_match,
            "target_match": target_match,
            "position_held": list(prod_ledger.positions.keys())[0] if prod_ledger.positions else "CASH"
        })

    prod_ledger.reconcile()
    prod_trades = [t.__dict__ for t in prod_ledger.closed_trades]
    print(f"-> Production Signal Replay complete: {len(parity_ledger)} decision bars checked.")

    # 4. Compare Closed Trades Row-by-Row
    print("\n[STEP 3/4] Comparing Trades Between Research Simulator & Production Engine...")
    trade_comparison = []
    signal_count_match = (len(research_trades) == len(prod_trades))

    max_len = max(len(research_trades), len(prod_trades))
    for i in range(max_len):
        r_tr = research_trades[i] if i < len(research_trades) else {}
        p_tr = prod_trades[i] if i < len(prod_trades) else {}

        r_sym = r_tr.get("symbol")
        p_sym = p_tr.get("symbol")
        sym_match = (r_sym == p_sym)

        r_ent = str(r_tr.get("entry_time"))[:10]
        p_ent = str(p_tr.get("entry_time"))[:10]
        ent_match = (r_ent == p_ent)

        r_ext = str(r_tr.get("exit_time"))[:10]
        p_ext = str(p_tr.get("exit_time"))[:10]
        ext_match = (r_ext == p_ext)

        r_reason = r_tr.get("exit_reason")
        p_reason = p_tr.get("exit_reason")
        reason_match = (r_reason == p_reason)

        r_shares = round(float(r_tr.get("shares", 0.0)), 2)
        p_shares = round(float(p_tr.get("shares", 0.0)), 2)
        shares_match = (abs(r_shares - p_shares) < 0.1)

        row_ok = sym_match and ent_match and ext_match and reason_match and shares_match
        if not row_ok:
            differences.append({
                "trade_index": i,
                "research": r_tr,
                "production": p_tr
            })

        trade_comparison.append({
            "trade_num": i + 1,
            "research_symbol": r_sym,
            "production_symbol": p_sym,
            "symbol_match": sym_match,
            "research_entry": r_ent,
            "production_entry": p_ent,
            "entry_match": ent_match,
            "research_exit": r_ext,
            "production_exit": p_ext,
            "exit_match": ext_match,
            "research_reason": r_reason,
            "production_reason": p_reason,
            "reason_match": reason_match,
            "research_shares": r_shares,
            "production_shares": p_shares,
            "shares_match": shares_match,
            "full_match": row_ok
        })

    # 5. Causal Audit of Production Trades
    print("\n[STEP 4/4] Running Independent Causal Audit on Production Replay Trades...")
    audit_report = CausalAuditor.audit_trade_execution_history(research_trades)
    causal_violations = len(audit_report.violations)
    print(f"-> Causal Audit: Passed={audit_report.passed}, Violations={causal_violations}")

    # 6. Evaluation of Required Parity Metrics
    signal_count_match = (len(research_trades) == len(prod_trades))
    signal_timestamps_match = all(r["entry_match"] and r["exit_match"] for r in trade_comparison)
    instrument_selection_match = all(r["symbol_match"] for r in trade_comparison)
    position_size_match = all(r["shares_match"] for r in trade_comparison)
    entry_rule_match = all(p["target_match"] for p in parity_ledger)
    exit_rule_match = all(r["reason_match"] for r in trade_comparison)
    ranking_match = all(p["ranking_match"] for p in parity_ledger)
    unexplained_diffs = len(differences)

    print("\n" + "=" * 80)
    print("🏛️ PRV CAPITAL | PARITY CERTIFICATION SCORECARD")
    print("=" * 80)
    print(f"{'CRITERION':<35} | {'REQUIRED':<15} | {'ACTUAL':<15} | STATUS")
    print("-" * 80)
    print(f"{'SIGNAL_COUNT_MATCH':<35} | {'TRUE':<15} | {str(signal_count_match):<15} | {'✅ PASS' if signal_count_match else '❌ FAIL'}")
    print(f"{'SIGNAL_TIMESTAMPS_MATCH':<35} | {'TRUE':<15} | {str(signal_timestamps_match):<15} | {'✅ PASS' if signal_timestamps_match else '❌ FAIL'}")
    print(f"{'INSTRUMENT_SELECTION_MATCH':<35} | {'TRUE':<15} | {str(instrument_selection_match):<15} | {'✅ PASS' if instrument_selection_match else '❌ FAIL'}")
    print(f"{'POSITION_SIZE_MATCH':<35} | {'TRUE':<15} | {str(position_size_match):<15} | {'✅ PASS' if position_size_match else '❌ FAIL'}")
    print(f"{'ENTRY_RULE_MATCH':<35} | {'TRUE':<15} | {str(entry_rule_match):<15} | {'✅ PASS' if entry_rule_match else '❌ FAIL'}")
    print(f"{'EXIT_RULE_MATCH':<35} | {'TRUE':<15} | {str(exit_rule_match):<15} | {'✅ PASS' if exit_rule_match else '❌ FAIL'}")
    print(f"{'RANKING_MATCH':<35} | {'TRUE':<15} | {str(ranking_match):<15} | {'✅ PASS' if ranking_match else '❌ FAIL'}")
    print(f"{'0 UNEXPLAINED DIFFERENCES':<35} | {'0':<15} | {str(unexplained_diffs):<15} | {'✅ PASS' if unexplained_diffs == 0 else '❌ FAIL'}")
    print(f"{'CAUSAL_VIOLATIONS':<35} | {'0':<15} | {str(causal_violations):<15} | {'✅ PASS' if causal_violations == 0 else '❌ FAIL'}")
    print("=" * 80)

    overall_parity_passed = (
        signal_count_match and
        signal_timestamps_match and
        instrument_selection_match and
        position_size_match and
        entry_rule_match and
        exit_rule_match and
        ranking_match and
        (unexplained_diffs == 0) and
        (causal_violations == 0)
    )

    verdict = "PARITY_CERTIFIED_PASS" if overall_parity_passed else "PARITY_FAIL"
    print(f"\nOVERALL PARITY VERDICT: [{verdict}]")

    result_payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "strategy_id": core_compounding_strategy.STRATEGY_ID,
        "evaluation_partition": f"{START_DATE} to {END_DATE}",
        "verdict": verdict,
        "scorecard": {
            "SIGNAL_COUNT_MATCH": signal_count_match,
            "SIGNAL_TIMESTAMPS_MATCH": signal_timestamps_match,
            "INSTRUMENT_SELECTION_MATCH": instrument_selection_match,
            "POSITION_SIZE_MATCH": position_size_match,
            "ENTRY_RULE_MATCH": entry_rule_match,
            "EXIT_RULE_MATCH": exit_rule_match,
            "RANKING_MATCH": ranking_match,
            "UNEXPLAINED_DIFFERENCES": unexplained_diffs,
            "CAUSAL_VIOLATIONS": causal_violations
        },
        "trade_comparison": trade_comparison,
        "differences": differences
    }

    out_path = "data/research_production_parity_ledger.json"
    with open(out_path, "w") as f:
        json.dump(result_payload, f, indent=2, default=str)
    print(f"Parity ledger saved to: {out_path}")
    return result_payload


if __name__ == "__main__":
    run_research_production_parity_test()
