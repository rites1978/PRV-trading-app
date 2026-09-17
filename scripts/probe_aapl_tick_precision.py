#!/usr/bin/env python3
"""
PRV Capital - Empirical AAPL Price Precision & Tick Validation Script
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Tests various price precisions on AAPL_US_EQ in Trading212 DEMO:
- 250.00 (standard whole)
- 250.01 (2 decimal places / 1 cent)
- 250.005 (3 decimal places / sub-cent)
- 250.001 (3 decimal places / milli-dollar)
- 250.0001 (4 decimal places / deci-cent)

Records exact broker response, cancels accepted orders, and verifies clean slate.
"""
import os
import sys
import time
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brokers.trading212 import broker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aapl_tick_probe")


def run_aapl_tick_probes():
    if str(broker.env).lower() != "demo":
        raise RuntimeError(f"Refusing to run on non-demo env: {broker.env}")

    ticker = "AAPL_US_EQ"
    test_prices = [
        250.00,
        250.01,
        250.005,
        250.001,
        250.0001
    ]

    results = []

    logger.info("Starting AAPL price precision probes...")

    for px in test_prices:
        time.sleep(2.0)
        logger.info(f"Submitting test order for {ticker} qty=1.0 @ {px}")
        res = broker.place_limit_order(ticker=ticker, quantity=1.0, limit_price=px)
        logger.info(f"Response for px={px}: {res}")

        order_id = None
        status = "REJECTED"
        if res.get("success"):
            status = "ACCEPTED"
            order_id = str(res.get("data", {}).get("id"))
            # Cancel immediately
            time.sleep(1.5)
            c_res = broker.cancel_order(order_id)
            logger.info(f"Cancelled order {order_id}: {c_res}")
            cancel_result = "CANCEL_SUCCESS" if c_res.get("success") else f"CANCEL_FAIL: {c_res}"
        else:
            cancel_result = "N/A"

        # Check position
        time.sleep(1.0)
        pos = broker.get_position(ticker)
        pos_result = "ZERO_POSITION" if not pos or float(pos.get("quantity", 0.0)) == 0.0 else f"HELD: {pos.get('quantity')}"

        results.append({
            "test_price": px,
            "status": status,
            "broker_response": res,
            "order_id": order_id,
            "cancel_result": cancel_result,
            "position_result": pos_result
        })

    # Final clean slate verification
    time.sleep(2.0)
    positions, _ = broker.get_open_positions_authoritative()
    time.sleep(2.0)
    orders, _ = broker.get_open_orders_authoritative()

    output = {
        "ticker": ticker,
        "probes": results,
        "final_positions": len(positions),
        "final_orders": len(orders)
    }

    with open("data/aapl_tick_probe_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("\n=== AAPL TICK PROBE RESULTS ===")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    run_aapl_tick_probes()
