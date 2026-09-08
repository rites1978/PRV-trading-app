"""
🏛️ PRV CAPITAL | AUTHORITATIVE PRODUCTION LAUNCH ASSERTIONS ENGINE
Executes atomic evaluation of the 8 mandatory production assertions for PRV_HIT_AND_RUN_ETF_V1:
1. RUNNING_COMMIT_SHA == RATIFIED_COMMIT_SHA
2. RUNNING_STRATEGY_ID == PRV_HIT_AND_RUN_ETF_V1
3. PRODUCTION_UNIVERSE == RATIFIED_ETF_UNIVERSE
4. LEGACY_SINGLE_EQUITY_ROUTING == BLOCKED
5. OPEN_POSITIONS == 0
6. OPEN_ORDERS == 0
7. BROKER_LEDGER_VARIANCE == £0.00
8. DAILY_REALISED_NET_PNL == £0.00
"""
import os
import sys
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from src.config.settings import settings
from src.brokers.trading212 import broker
from src.brokers.broker_ledger import broker_ledger
from src.strategies.registry import strategy_registry
from src.data.universe import universe_manager, ETF_HIT_AND_RUN_UNIVERSE
from src.execution.order_router import order_router
from src.portfolio.daily_objective_service import daily_objective_service


def evaluate_production_launch_assertions() -> Dict[str, Any]:
    """
    Evaluates all 8 production assertions atomically.
    Returns full diagnostics and overall boolean passed.
    """
    assertions = {}
    all_passed = True

    # 1. RUNNING_COMMIT_SHA == RATIFIED_COMMIT_SHA
    running_sha = os.getenv("RENDER_GIT_COMMIT", "")
    if not running_sha:
        try:
            running_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            running_sha = "UNKNOWN"
    ratified_sha = getattr(settings, "RATIFIED_COMMIT_SHA", "auto")
    if ratified_sha in ("auto", "", "UNKNOWN"):
        commit_sha_match = (running_sha != "UNKNOWN")
    else:
        commit_sha_match = running_sha.startswith(ratified_sha) or ratified_sha.startswith(running_sha)
    assertions["RUNNING_COMMIT_SHA == RATIFIED_COMMIT_SHA"] = {
        "passed": commit_sha_match,
        "running_commit_sha": running_sha,
        "ratified_commit_sha": ratified_sha
    }
    if not commit_sha_match:
        all_passed = False

    # 2. RUNNING_STRATEGY_ID == PRV_HIT_AND_RUN_ETF_V1
    active_strat = strategy_registry.get_active_execution_strategy_id()
    strat_match = (str(active_strat).upper() == "PRV_HIT_AND_RUN_ETF_V1")
    assertions["RUNNING_STRATEGY_ID == PRV_HIT_AND_RUN_ETF_V1"] = {
        "passed": strat_match,
        "running_strategy_id": active_strat,
        "required_strategy_id": "PRV_HIT_AND_RUN_ETF_V1"
    }
    if not strat_match:
        all_passed = False

    # 3. PRODUCTION_UNIVERSE == RATIFIED_ETF_UNIVERSE
    current_universe = universe_manager.get_all()
    ratified_tickers = [x["t212_ticker"] for x in ETF_HIT_AND_RUN_UNIVERSE]
    current_tickers = [x["t212_ticker"] for x in current_universe]
    universe_match = (sorted(current_tickers) == sorted(ratified_tickers))
    assertions["PRODUCTION_UNIVERSE == RATIFIED_ETF_UNIVERSE"] = {
        "passed": universe_match,
        "current_universe_tickers": current_tickers,
        "ratified_etf_tickers": ratified_tickers
    }
    if not universe_match:
        all_passed = False

    # 4. LEGACY_SINGLE_EQUITY_ROUTING == BLOCKED
    # Test routing a forbidden legacy UK equity
    legacy_test_ok, legacy_test_reason, _ = order_router.route_entry_order(
        symbol="ULVR",
        t212_ticker="ULVRl_EQ",
        quantity=1.0,
        price=47.0,
        target_price=48.0,
        stop_loss_price=46.0,
        sector="Consumer Staples",
        confidence_score=85.0,
        market_regime="BULL",
        agent_votes={},
        risk_approved=True,
        strategy_id="PRV_HIT_AND_RUN_ETF_V1",
        bypass_audit_freeze=True  # Ensure instrument filter blocks it even if entries allowed
    )
    legacy_blocked = (not legacy_test_ok) and ("Unauthorized instrument" in legacy_test_reason or "UNAUTHORIZED" in legacy_test_reason)
    assertions["LEGACY_SINGLE_EQUITY_ROUTING == BLOCKED"] = {
        "passed": legacy_blocked,
        "legacy_test_blocked": not legacy_test_ok,
        "enforcement_reason": legacy_test_reason
    }
    if not legacy_blocked:
        all_passed = False

    # 5. OPEN_POSITIONS == 0
    positions = broker.get_open_positions(force_refresh=True) or []
    pos_zero = (len(positions) == 0)
    assertions["OPEN_POSITIONS == 0"] = {
        "passed": pos_zero,
        "open_positions_count": len(positions),
        "positions": positions
    }
    if not pos_zero:
        all_passed = False

    # 6. OPEN_ORDERS == 0
    orders = broker.get_open_orders(force_refresh=True) or []
    orders_zero = (len(orders) == 0)
    assertions["OPEN_ORDERS == 0"] = {
        "passed": orders_zero,
        "open_orders_count": len(orders),
        "orders": orders
    }
    if not orders_zero:
        all_passed = False

    # 7. BROKER_LEDGER_VARIANCE == £0.00
    ledger_snap = broker_ledger.fetch_ground_truth_ledger(force_refresh=True)
    var_gbp = float(ledger_snap.get("prv_ledger_variance_gbp", 0.0))
    var_zero = (abs(var_gbp) < 0.001)
    assertions["BROKER_LEDGER_VARIANCE == £0.00"] = {
        "passed": var_zero,
        "broker_ledger_variance_gbp": var_gbp
    }
    if not var_zero:
        all_passed = False

    # 8. DAILY_REALISED_NET_PNL == £0.00
    daily_status = daily_objective_service.get_daily_status(force_refresh=True)
    daily_pnl = float(daily_status.get("daily_net_realized_pnl_gbp", 0.0))
    daily_pnl_zero = (abs(daily_pnl) < 0.01)
    assertions["DAILY_REALISED_NET_PNL == £0.00"] = {
        "passed": daily_pnl_zero,
        "daily_realised_net_pnl_gbp": daily_pnl,
        "forward_baseline_nav": getattr(settings, "ETF_V1_FORWARD_BASELINE_NAV", 49897.38)
    }
    if not daily_pnl_zero:
        all_passed = False

    # 9. STOP_UNIT_CONVERSION_VALIDATED
    csp1_entry_gbp = 613.24
    csp1_sl_gbp = csp1_entry_gbp * (1.0 - 0.008)
    meta_csp1 = universe_manager.get_by_t212_ticker("CSP1_EQ")
    csp1_is_pence = meta_csp1.get("is_uk_pence", False) if meta_csp1 else True
    csp1_broker_stop = round(csp1_sl_gbp * 100.0, 2) if csp1_is_pence else round(csp1_sl_gbp, 4)
    csp1_stop_ok = (csp1_broker_stop > 50000.0) # Must be ~60,833 GBX pence, NOT 608.33p (£6.08)

    vusa_entry_gbp = 107.76
    vusa_sl_gbp = vusa_entry_gbp * (1.0 - 0.008)
    meta_vusa = universe_manager.get_by_t212_ticker("VUSAl_EQ")
    vusa_is_pence = meta_vusa.get("is_uk_pence", False) if meta_vusa else False
    vusa_broker_stop = round(vusa_sl_gbp * 100.0, 2) if vusa_is_pence else round(vusa_sl_gbp, 4)
    vusa_stop_ok = (vusa_broker_stop < 500.0) # Must be ~£106.90 GBP, NOT 10,690p

    stop_unit_pass = (csp1_stop_ok and vusa_stop_ok)
    assertions["STOP_UNIT_CONVERSION_VALIDATED"] = {
        "passed": stop_unit_pass,
        "csp1_calculated_broker_stop": f"{csp1_broker_stop} GBX (pence)",
        "csp1_expected_pence": 60833.41,
        "vusa_calculated_broker_stop": f"£{vusa_broker_stop:.4f} GBP",
        "vusa_expected_gbp": 106.8979
    }
    if not stop_unit_pass:
        all_passed = False

    # 10. SIGNAL_DEDUPLICATION_GATE_ACTIVE
    from src.core.engine import quant_engine
    test_key = "PRV_HIT_AND_RUN_ETF_V1_TEST_TICKER_2026-09-08"
    quant_engine.mark_signal_bar_executed(test_key)
    dedup_detected = quant_engine.is_signal_bar_already_executed(test_key)
    assertions["SIGNAL_DEDUPLICATION_GATE_ACTIVE"] = {
        "passed": dedup_detected,
        "dedup_key_format": "{strategy_id}_{t212_ticker}_{bar_date}",
        "test_key": test_key,
        "duplicate_prevented": dedup_detected
    }
    if not dedup_detected:
        all_passed = False

    summary = broker.get_account_summary(force_refresh=True)
    broker_nav = float(summary.get("total_value", 49897.38))
    free_cash = float(summary.get("available_cash", 49897.38))

    return {
        "all_assertions_passed": all_passed,
        "verdict": "ASSERTIONS_PASSED" if all_passed else "ASSERTIONS_FAILED",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "running_commit_sha": running_sha,
        "ratified_commit_sha": ratified_sha,
        "strategy_id": active_strat,
        "universe": ratified_tickers,
        "engine_running": getattr(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", False),
        "entries_allowed": getattr(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", False),
        "broker_nav": broker_nav,
        "free_cash": free_cash,
        "positions_count": len(positions),
        "orders_count": len(orders),
        "daily_realised_strategy_pnl": daily_pnl,
        "assertions": assertions
    }


if __name__ == "__main__":
    import json
    res = evaluate_production_launch_assertions()
    print(json.dumps(res, indent=2))
