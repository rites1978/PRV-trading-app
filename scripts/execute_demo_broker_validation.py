#!/usr/bin/env python3
"""
PRV Capital - Empirical Trading212 DEMO Broker Validation Script
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Executes controlled empirical validation probes in Trading212 PRACTICE/DEMO.
Strictly isolated:
- LLOY_EVIDENCE = LLOY-specific
- AAPL_EVIDENCE = AAPL-specific
- VUSA_EVIDENCE = VUSA-specific
No asset-class generalization.
Zero real-money risk (£0).
Every probe reconciles position = 0 and open orders = 0.
"""
import os
import sys
import time
import json
import logging
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brokers.trading212 import broker
from src.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("demo_validation")


def verify_clean_slate() -> bool:
    """Verifies that no open positions or open orders exist in the DEMO account."""
    time.sleep(2.0)
    positions, _ = broker.get_open_positions_authoritative()
    time.sleep(2.0)
    orders, _ = broker.get_open_orders_authoritative()
    is_clean = len(positions) == 0 and len(orders) == 0
    if not is_clean:
        logger.error(f"UNRESOLVED_STATE: Positions={len(positions)}, Orders={len(orders)}")
    return is_clean


def cleanup_order_and_position(ticker: str, order_id: str = None) -> bool:
    """Cancels known order_id if provided, cancels any open orders for ticker, and ensures position is flattened."""
    if order_id:
        time.sleep(1.5)
        c_res = broker.cancel_order(order_id)
        logger.info(f"Cleanup: Cancelled order {order_id} for {ticker}: {c_res}")

    # Cancel any open orders for this ticker (limit, stop, etc.)
    time.sleep(1.5)
    orders, _ = broker.get_open_orders_authoritative()
    for o in orders:
        if str(o.get("ticker", "")).upper() == ticker.upper():
            oid = str(o.get("id"))
            time.sleep(1.5)
            c_res = broker.cancel_order(oid)
            logger.info(f"Cleanup: Cancelled remaining order {oid} ({o.get('type')}) for {ticker}: {c_res}")

    time.sleep(2.0)
    positions, _ = broker.get_open_positions_authoritative()
    for p in positions:
        if str(p.get("ticker", "")).upper() == ticker.upper():
            qty = float(p.get("quantity", 0.0))
            if qty != 0.0:
                time.sleep(1.5)
                sell_res = broker.place_market_order(ticker=ticker, quantity=-qty)
                logger.info(f"Cleanup: Flattened position {qty} for {ticker}: {sell_res}")

    return verify_clean_slate()


def cleanup_instrument(ticker: str) -> bool:
    return cleanup_order_and_position(ticker)


def run_probes():
    logger.info("=== PRV CAPITAL — CONTROLLED TRADING212 DEMO VALIDATION ===")

    # 1. Verify Environment is DEMO
    if str(broker.env).lower() != "demo":
        raise RuntimeError(f"CRITICAL: Refusing to run in non-demo environment: {broker.env}")

    # 2. Capture Initial Account State
    acc = broker.get_account_summary(force_refresh=True)
    logger.info(f"DEMO Account Summary: {acc.get('raw')}")

    if not verify_clean_slate():
        raise RuntimeError("DEMO account is not in a clean slate state. Aborting validation.")

    probes_results: List[Dict[str, Any]] = []

    # Target test specifications
    test_specs = [
        {
            "instrument": "LLOYl_EQ",
            "indicative_price": 111.95,  # GBX
            "limit_price": 90.0,
            "currency": "GBX",
            "fractional_qty": 0.5
        },
        {
            "instrument": "AAPL_US_EQ",
            "indicative_price": 333.83,  # USD
            "limit_price": 280.00,
            "currency": "USD",
            "fractional_qty": 0.1
        },
        {
            "instrument": "VUSAl_EQ",
            "indicative_price": 108.21,  # GBP
            "limit_price": 90.00,
            "currency": "GBP",
            "fractional_qty": 0.1
        }
    ]

    for spec in test_specs:
        ticker = spec["instrument"]
        logger.info(f"\n=======================================================")
        logger.info(f"STARTING PROBES FOR {ticker}")
        logger.info(f"=======================================================")

        # -------------------------------------------------------------
        # PROBE 1: Exact Price Payload Probe (Limit BUY, Qty=1.0)
        # -------------------------------------------------------------
        probe1_id = f"DEMO-{ticker[:4]}-01"
        limit_px = spec["limit_price"]
        logger.info(f"[{probe1_id}] Testing Exact Limit Price Payload: {ticker} qty=1.0 @ {limit_px}")

        p1_res = broker.place_limit_order(ticker=ticker, quantity=1.0, limit_price=limit_px)
        p1_record = {
            "test_id": probe1_id,
            "instrument": ticker,
            "order_type": "LIMIT_BUY",
            "quantity": 1.0,
            "limit_price": limit_px,
            "response": p1_res,
            "classification": "EXACT_PRICE_PAYLOAD_ACCEPTED" if p1_res.get("success") else "EXACT_PRICE_PAYLOAD_REJECTED"
        }
        probes_results.append(p1_record)
        logger.info(f"[{probe1_id}] Result: {p1_record['classification']}")

        # Cleanup probe 1
        order_id_1 = str(p1_res.get("data", {}).get("id") or "") if p1_res.get("success") else None
        if not cleanup_order_and_position(ticker, order_id=order_id_1):
            logger.critical(f"Cleanup failed after {probe1_id}. ABORTING ENTIRE RUN.")
            break

        # -------------------------------------------------------------
        # PROBE 2: Exact Fractional Quantity Payload Probe (Limit BUY)
        # -------------------------------------------------------------
        probe2_id = f"DEMO-{ticker[:4]}-02"
        frac_qty = spec["fractional_qty"]
        logger.info(f"[{probe2_id}] Testing Fractional Quantity Payload: {ticker} qty={frac_qty} @ {limit_px}")

        p2_res = broker.place_limit_order(ticker=ticker, quantity=frac_qty, limit_price=limit_px)
        p2_record = {
            "test_id": probe2_id,
            "instrument": ticker,
            "order_type": "LIMIT_BUY",
            "quantity": frac_qty,
            "limit_price": limit_px,
            "response": p2_res,
            "classification": "EXACT_QUANTITY_PAYLOAD_ACCEPTED" if p2_res.get("success") else "EXACT_QUANTITY_PAYLOAD_REJECTED"
        }
        probes_results.append(p2_record)
        logger.info(f"[{probe2_id}] Result: {p2_record['classification']}")

        # Cleanup probe 2
        order_id_2 = str(p2_res.get("data", {}).get("id") or "") if p2_res.get("success") else None
        if not cleanup_order_and_position(ticker, order_id=order_id_2):
            logger.critical(f"Cleanup failed after {probe2_id}. ABORTING ENTIRE RUN.")
            break

        # -------------------------------------------------------------
        # PROBE 3: Native Protective Stop Execution Sequence (Active Position)
        # -------------------------------------------------------------
        probe3_id = f"DEMO-{ticker[:4]}-03"
        logger.info(f"[{probe3_id}] Testing Native Protective Stop Sequence on Active Position for {ticker}")

        # Step 3a: Submit Entry Market Order
        entry_res = broker.place_market_order(ticker=ticker, quantity=1.0)
        logger.info(f"[{probe3_id}] Entry Order Response: {entry_res}")

        if not entry_res.get("success"):
            p3_record = {
                "test_id": probe3_id,
                "instrument": ticker,
                "status": "ENTRY_REJECTED",
                "entry_response": entry_res,
                "classification": "INCONCLUSIVE"
            }
            probes_results.append(p3_record)
            cleanup_instrument(ticker)
            continue

        # Step 3b: Poll for fill confirmation & authoritative fill price
        time.sleep(2.0)
        positions, _ = broker.get_open_positions_authoritative()
        target_pos = next((p for p in positions if str(p.get("ticker", "")).upper() == ticker.upper()), None)

        if not target_pos:
            logger.warning(f"[{probe3_id}] Position not immediately found; waiting 3s...")
            time.sleep(3.0)
            positions, _ = broker.get_open_positions_authoritative()
            target_pos = next((p for p in positions if str(p.get("ticker", "")).upper() == ticker.upper()), None)

        if not target_pos:
            logger.error(f"[{probe3_id}] Entry did not produce open position within timeout.")
            p3_record = {
                "test_id": probe3_id,
                "instrument": ticker,
                "status": "FILL_NOT_CONFIRMED",
                "classification": "INCONCLUSIVE"
            }
            probes_results.append(p3_record)
            cleanup_instrument(ticker)
            continue

        fill_price = float(target_pos.get("averagePrice") or target_pos.get("price") or 0.0)
        logger.info(f"[{probe3_id}] Authoritative Fill Price: {fill_price}")

        # Step 3c: Calculate contract-compliant protective stop (5% max loss, rounded UP)
        raw_stop_floor = fill_price * 0.95
        stop_price = round(raw_stop_floor + 0.01, 2)  # Ceil towards entry
        logger.info(f"[{probe3_id}] Submitting Native Protective Stop @ {stop_price} (floor={raw_stop_floor})")

        stop_res = broker.place_stop_order(ticker=ticker, quantity=-1.0, stop_price=stop_price)
        if not stop_res.get("success"):
            # Try positive quantity format
            stop_res = broker.place_stop_order(ticker=ticker, quantity=1.0, stop_price=stop_price)

        logger.info(f"[{probe3_id}] Stop Order Response: {stop_res}")

        # Step 3d: Verify stop exists in broker open orders
        time.sleep(1.0)
        orders, _ = broker.get_open_orders_authoritative()
        matching_stop = next(
            (o for o in orders if str(o.get("ticker", "")).upper() == ticker.upper() and o.get("type") == "STOP"),
            None
        )

        stop_proven = matching_stop is not None
        p3_record = {
            "test_id": probe3_id,
            "instrument": ticker,
            "fill_price": fill_price,
            "stop_price": stop_price,
            "stop_response": stop_res,
            "stop_verified_in_open_orders": stop_proven,
            "classification": "NATIVE_STOP_SUPPORT_EMPIRICALLY_PROVEN" if stop_proven else "INCONCLUSIVE"
        }
        probes_results.append(p3_record)
        logger.info(f"[{probe3_id}] Stop Verification: {p3_record['classification']}")

        # Step 3e: Cleanup and flatten
        if not cleanup_instrument(ticker):
            logger.critical(f"Cleanup failed after {probe3_id}. ABORTING ENTIRE RUN.")
            break

    # Final Account Reconciliation
    final_acc = broker.get_account_summary(force_refresh=True)
    is_final_clean = verify_clean_slate()

    output_summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "probes": probes_results,
        "clean_slate_final": is_final_clean,
        "final_account_equity": final_acc.get("raw", {}).get("total")
    }

    results_file = "data/demo_broker_validation_results.json"
    os.makedirs(os.path.dirname(results_file), exist_ok=True)
    with open(results_file, "w") as f:
        json.dump(output_summary, f, indent=2)

    logger.info(f"Validation complete. Results saved to {results_file}.")
    print("\n=== SUMMARY OUTPUT ===")
    print(json.dumps(output_summary, indent=2))


if __name__ == "__main__":
    run_probes()
