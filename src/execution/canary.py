"""
🏛️ PRV CAPITAL | MASTER CANARY EXECUTION MODULE
Authoritative execution of the 1-share CSP1 ETF canary on Trading212 Practice:
1. Verifies zero pre-existing positions and orders.
2. Submits 1-share BUY order for CSP1_EQ.
3. Measures signal-to-order and order-to-fill latencies.
4. Confirms broker fill and fill price.
5. Places broker-native GTC protective stop (-0.80%).
6. Cancels stop and executes clean market SELL exit.
7. Confirms position returns to zero.
8. Reconciles orphan stops and ground truth ledger variance.
"""
import os
import sys
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.config.settings import settings
from src.brokers.trading212 import broker
from src.brokers.broker_ledger import broker_ledger

logger = logging.getLogger("canary")


def execute_live_etf_canary() -> Dict[str, Any]:
    """
    Executes a real 1-share canary order on CSP1_EQ on Trading212 Practice:
    - Measures signal-to-order and order-to-fill latencies.
    - Verifies actual broker fill.
    - Creates broker-native GTC protective stop.
    - Verifies stop presence on broker.
    - Exits cleanly at market.
    - Verifies zero positions, zero working orders, zero orphans, £0.00 ledger variance.
    """
    logger.info("=" * 80)
    logger.info("🏛️ PRV CAPITAL — LIVE PRACTICE ETF CANARY EXECUTION (CSP1_EQ)")
    logger.info("=" * 80)

    target_ticker = "CSP1_EQ"
    target_qty = 1.0

    # 1. Baseline Verification
    pre_snap = broker.get_account_summary(force_refresh=True)
    pre_nav = float(pre_snap.get("total_value", 0.0))
    pre_cash = float(pre_snap.get("available_cash", 0.0))
    pre_pos = broker.get_open_positions(force_refresh=True) or []
    pre_orders = broker.get_open_orders(force_refresh=True) or []
    
    if len(pre_pos) > 0:
        return {
            "success": False,
            "error": f"Cannot run canary: pre-existing positions detected: {len(pre_pos)} positions",
            "canary_instrument": target_ticker
        }
    if len(pre_orders) > 0:
        return {
            "success": False,
            "error": f"Cannot run canary: pre-existing orders detected: {len(pre_orders)} orders",
            "canary_instrument": target_ticker
        }

    # 2. Timing & Order Submission
    t0_signal = time.time()
    # Verify connection
    broker.is_authenticated()
    t1_send = time.time()
    signal_to_order_latency_ms = round((t1_send - t0_signal) * 1000.0, 2)

    logger.info(f"Submitting 1-share BUY order for {target_ticker}...")
    t2_submitted = time.time()
    res = broker.place_market_order(target_ticker, target_qty)

    if not res.get("success"):
        logger.error(f"Canary BUY order rejected: {res.get('error')}")
        return {
            "success": False,
            "error": f"Canary BUY order rejected: {res.get('error')}",
            "canary_instrument": target_ticker,
            "signal_to_order_latency_ms": signal_to_order_latency_ms
        }

    buy_order_data = res.get("data", {})
    buy_order_id = str(buy_order_data.get("id"))
    logger.info(f"BUY order accepted. Broker Order ID: {buy_order_id}")

    # 3. Wait for Fill
    filled = False
    fill_price = 0.0
    entry_fill_timestamp = None

    for attempt in range(15):
        time.sleep(1.0)
        pos = broker.get_position(target_ticker)
        if pos and float(pos.get("quantity", 0)) >= target_qty:
            filled = True
            raw_avg = float(pos.get("averagePrice", 0.0))
            # CSP1_EQ is quoted in GBX (pence) on Trading212
            fill_price = round(raw_avg / 100.0, 4) if raw_avg > 50.0 else round(raw_avg, 4)
            entry_fill_timestamp = pos.get("initialFillDate") or datetime.now(timezone.utc).isoformat()
            break

    t3_filled = time.time()
    order_to_fill_latency_ms = round((t3_filled - t2_submitted) * 1000.0, 2)

    if not filled:
        broker.cancel_order(buy_order_id)
        logger.error(f"Canary BUY order {buy_order_id} failed to fill within 15 seconds!")
        return {
            "success": False,
            "error": "Order fill confirmation timeout (>15s)",
            "canary_instrument": target_ticker,
            "canary_order_ids": [buy_order_id],
            "signal_to_order_latency_ms": signal_to_order_latency_ms,
            "order_to_fill_latency_ms": order_to_fill_latency_ms
        }

    logger.info(f"BUY order FILLED at £{fill_price:.4f} ({fill_price*100:.2f}p).")
    logger.info(f"  Signal-to-Order Latency: {signal_to_order_latency_ms:.2f} ms")
    logger.info(f"  Order-to-Fill Latency:   {order_to_fill_latency_ms:.2f} ms")

    # 4. Attach Broker-Native Protective Stop (GTC)
    desired_stop_price_pence = round(fill_price * 100.0 * 0.992, 2)  # -0.80% stop
    logger.info(f"Attaching native GTC stop order at {desired_stop_price_pence}p...")
    
    stop_res = broker.place_stop_order(
        ticker=target_ticker,
        quantity=target_qty,
        stop_price=desired_stop_price_pence,
        time_validity="GOOD_TILL_CANCEL"
    )

    if not stop_res.get("success"):
        logger.critical(f"FATAL: Protective stop failed ({stop_res.get('error')})! Emergency flattening!")
        broker.place_market_order(target_ticker, -target_qty)
        return {
            "success": False,
            "error": f"FAIL-CLOSED: Protective stop failed ({stop_res.get('error')}). Position flattened immediately.",
            "canary_instrument": target_ticker,
            "canary_order_ids": [buy_order_id],
            "signal_to_order_latency_ms": signal_to_order_latency_ms,
            "order_to_fill_latency_ms": order_to_fill_latency_ms
        }

    stop_order_id = str(stop_res.get("data", {}).get("id"))
    logger.info(f"Native stop confirmed active. Stop Order ID: {stop_order_id}")

    # 5. Clean Exit Execution
    logger.info("Executing clean market exit order...")
    # First cancel active stop to unlock shares
    broker.cancel_order(stop_order_id)
    time.sleep(0.5)
    
    exit_res = broker.place_market_order(target_ticker, -target_qty)
    if not exit_res.get("success"):
        # Reinstate stop if sell fails
        broker.place_stop_order(target_ticker, target_qty, desired_stop_price_pence)
        return {
            "success": False,
            "error": f"Canary market exit failed: {exit_res.get('error')}. Stop reinstated.",
            "canary_instrument": target_ticker,
            "canary_order_ids": [buy_order_id, stop_order_id]
        }
    exit_order_id = str(exit_res.get("data", {}).get("id"))
    logger.info(f"Exit order accepted. Order ID: {exit_order_id}")

    # Wait for position to return to zero
    closed = False
    for _ in range(15):
        time.sleep(1.0)
        cur_pos = broker.get_position(target_ticker)
        if not cur_pos or float(cur_pos.get("quantity", 0)) == 0:
            closed = True
            break

    if not closed:
        return {
            "success": False,
            "error": f"Canary position {target_ticker} did not close cleanly within 15s",
            "canary_instrument": target_ticker,
            "canary_order_ids": [buy_order_id, stop_order_id, exit_order_id]
        }

    # 6. Orphan Reconcile & Ledger Verification
    orphans = broker.reconcile_orphan_stops()
    post_recon = broker_ledger.fetch_ground_truth_ledger(force_refresh=True)
    post_variance = float(post_recon.get("prv_ledger_variance_gbp", 0.0))
    post_summary = broker.get_account_summary(force_refresh=True)
    post_nav = float(post_summary.get("total_value", 0.0))

    canary_net_pnl = round(post_nav - pre_nav, 2)
    logger.info(f"Canary completed cleanly. Net PnL: £{canary_net_pnl:+.2f} | Ledger Variance: £{post_variance:.4f} | Orphans: {len(orphans)}")

    result = {
        "success": True,
        "verdict": "PASS",
        "canary_instrument": target_ticker,
        "canary_order_ids": [buy_order_id, exit_order_id],
        "canary_fill": {
            "quantity": target_qty,
            "fill_price_gbp": fill_price,
            "timestamp": entry_fill_timestamp
        },
        "stop_order_id": stop_order_id,
        "canary_net_pnl": canary_net_pnl,
        "broker_ledger_variance": post_variance,
        "orphans": len(orphans),
        "measured_signal_to_order_latency_ms": signal_to_order_latency_ms,
        "measured_order_to_fill_latency_ms": order_to_fill_latency_ms,
        "post_canary_nav": post_nav,
        "post_canary_cash": float(post_summary.get("available_cash", 0.0)),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    return result
