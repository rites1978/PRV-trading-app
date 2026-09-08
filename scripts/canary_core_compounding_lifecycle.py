"""
🏛️ PRV CAPITAL | PHASE 7: CONTROLLED PRACTICE CANARY VERIFICATION
Executes an end-to-end live canary on Trading212 Practice API for Core Compounding Engine:
1. Live Market Session & Connection Validation
2. Routing Permission Gate Validation (Asserts PRACTICE_NEW_ENTRIES_ALLOWED=False blocks live autonomous orders)
3. Controlled 1-Share Practice Broker Order Placement (IGLTl_EQ - SDRT-exempt UK Gilts ETF)
4. Live Order Acceptance & Order ID Confirmation from Trading212
5. Controlled Clean Exit / Cancellation
6. Broker Balance Sheet Reconciliation:
   - 0 Open Orders
   - 0 Open Positions
   - Free Cash == £49,897.38 to the exact penny
"""
import sys
import os
import time
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config.settings import settings
from src.brokers.trading212 import broker
from src.strategies.core_compounding_v1 import CoreCompoundingStrategy, core_compounding_strategy
from src.strategies.registry import strategy_registry
from src.execution.order_router import order_router
from src.portfolio.portfolio_snapshot import portfolio_snapshot


def run_core_compounding_canary():
    print("=" * 85)
    print("🏛️ PRV CAPITAL — PHASE 7: CORE COMPOUNDING PRACTICE CANARY")
    print("Strategy: PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1")
    print("Target Canary Instrument: IGLTl_EQ (IE00B1FZSB30 - UK Gilts UCITS ETF)")
    print("=" * 85)

    # 1. Verify Broker Connectivity & Pre-Flight State
    print("\n[STAGE 1/5] Pre-Flight Broker State Verification...")
    if not broker.is_authenticated():
        raise RuntimeError("Trading212 broker is not authenticated.")

    summary = broker.get_account_summary(force_refresh=True)
    initial_cash = summary.get("available_cash", 0.0)
    initial_nav = summary.get("total_value", 0.0)
    initial_orders = broker.get_open_orders(force_refresh=True)
    initial_positions = broker.get_open_positions(force_refresh=True)

    print(f"  Broker Environment: {broker.env.upper()}")
    print(f"  Available Cash:     £{initial_cash:,.2f}")
    print(f"  Total NAV:          £{initial_nav:,.2f}")
    print(f"  Open Orders:        {len(initial_orders)}")
    print(f"  Open Positions:     {len(initial_positions)}")

    assert abs(initial_cash - 49897.38) < 0.01, f"Initial cash £{initial_cash} != £49,897.38"
    assert len(initial_orders) == 0, "Expected 0 open orders before canary"
    assert len(initial_positions) == 0, "Expected 0 open positions before canary"
    print("✅ Pre-Flight State Verified: £49,897.38 Free Cash, 0 Orders, 0 Positions.")

    # 2. Assert Strict Gate Authority (Autonomous routing blocked)
    print("\n[STAGE 2/5] Production Gate Authority Verification...")
    can_route_autonomous = strategy_registry.can_strategy_route_orders("PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1")
    print(f"  PRACTICE_NEW_ENTRIES_ALLOWED: {settings.PRACTICE_NEW_ENTRIES_ALLOWED}")
    print(f"  REAL_MONEY_NEW_ENTRIES_ALLOWED: {settings.REAL_MONEY_NEW_ENTRIES_ALLOWED}")
    print(f"  Autonomous Order Routing Permitted: {can_route_autonomous}")
    assert not can_route_autonomous, "Autonomous order routing must be BLOCKED (PRACTICE_NEW_ENTRIES_ALLOWED=False)"
    print("✅ Gate Authority Confirmed: Autonomous entry is strictly locked.")

    # 3. Controlled Practice Canary Order Placement
    print("\n[STAGE 3/5] Routing Controlled 1-Share Practice Canary Order to Trading212...")
    ticker = "IGLTl_EQ"
    qty = 1.0
    limit_price = 5.0 # Low-bound limit ensures placement validation without accidental spread drag

    res = broker.place_limit_order(ticker, qty, limit_price)
    if not res.get("success"):
        raise RuntimeError(f"Canary order rejected by Trading212: {res.get('error')}")

    order_data = res.get("data", {})
    order_id = order_data.get("id")
    order_status = order_data.get("status")
    print(f"✅ Real Trading212 Practice Order Accepted & Confirmed!")
    print(f"  Broker Order ID: {order_id}")
    print(f"  Instrument:      {order_data.get('instrument', {}).get('name')} ({ticker})")
    print(f"  Quantity:        {qty} share")
    print(f"  Status:          {order_status}")
    print(f"  Created At:      {order_data.get('createdAt')}")

    time.sleep(1.5)

    # 4. In-Flight Order Verification
    print("\n[STAGE 4/5] Verifying In-Flight Order in Trading212 Order Book...")
    in_flight_orders = broker.get_open_orders(force_refresh=True)
    matching = [o for o in in_flight_orders if str(o.get("id")) == str(order_id)]
    print(f"  Open Orders in Broker Book: {len(in_flight_orders)}")
    print(f"  Matching Canary Order Found: {len(matching) == 1}")
    assert len(matching) == 1, f"Canary order {order_id} not visible in broker order book!"

    # 5. Clean Market Exit / Order Cancellation
    print("\n[STAGE 5/5] Executing Clean Order Cancellation & Balance Sheet Reconciliation...")
    cancel_res = broker.cancel_order(str(order_id))
    print(f"  Cancellation Result: {cancel_res.get('success')}")
    assert cancel_res.get("success"), f"Failed to cancel canary order {order_id}: {cancel_res.get('error')}"

    time.sleep(1.5)

    final_orders = broker.get_open_orders(force_refresh=True)
    final_positions = broker.get_open_positions(force_refresh=True)
    final_acc = broker.get_account_summary(force_refresh=True)
    final_cash = final_acc.get("available_cash", 0.0)
    final_nav = final_acc.get("total_value", 0.0)

    print(f"\n  Final Open Orders:    {len(final_orders)}")
    print(f"  Final Open Positions: {len(final_positions)}")
    print(f"  Final Available Cash: £{final_cash:,.2f}")
    print(f"  Final Total NAV:      £{final_nav:,.2f}")

    assert len(final_orders) == 0, f"Expected 0 open orders after cancel, found {len(final_orders)}"
    assert len(final_positions) == 0, f"Expected 0 positions, found {len(final_positions)}"
    assert abs(final_cash - 49897.38) < 0.01, f"Cash invariant breached! Final cash £{final_cash} != £49,897.38"
    assert abs(final_nav - 49897.38) < 0.01, f"NAV invariant breached! Final NAV £{final_nav} != £49,897.38"

    print("\n" + "=" * 85)
    print("🏛️ PRV CAPITAL | CONTROLLED PRACTICE CANARY VERIFICATION — 100% PASS")
    print("=" * 85)

    canary_result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "canary_passed": True,
        "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
        "ticker": ticker,
        "isin": "IE00B1FZSB30",
        "shares": qty,
        "broker_order_id": order_id,
        "order_status_confirmed": order_status,
        "cancellation_confirmed": True,
        "pre_flight_cash_gbp": initial_cash,
        "post_flight_cash_gbp": final_cash,
        "post_flight_nav_gbp": final_nav,
        "orphan_orders_count": len(final_orders),
        "orphan_positions_count": len(final_positions),
        "cash_invariant_preserved": True,
        "autonomous_entries_locked": not can_route_autonomous
    }

    out_file = "audit/real_trading212_core_compounding_canary_result.json"
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(canary_result, f, indent=2)
    print(f"Canary audit result saved to: {out_file}")

    return canary_result


if __name__ == "__main__":
    run_core_compounding_canary()
