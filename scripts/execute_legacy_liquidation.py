"""
PRV Capital — Safe Legacy Position Liquidation Script
Safely liquidates the 5 legacy UK equity positions:
STANl_EQ, ULVRl_EQ, RELl_EQ, HSBAl_EQ, VODl_EQ

Protocol per ticker:
1. Confirm position quantity and active protective stop ID.
2. Cancel the specific stop order ID immediately before sell.
3. Submit market SELL order (-qty).
4. If SELL fails, immediately reinstate protective stop and HALT.
5. Verify position returns to zero.
6. Clean any residual/orphan stops.
7. Record execution details.
"""
import os
import sys
import time
import json
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brokers.trading212 import broker
from src.brokers.broker_ledger import broker_ledger

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("liquidation")

TARGET_TICKERS = ["STANl_EQ", "ULVRl_EQ", "RELl_EQ", "HSBAl_EQ", "VODl_EQ"]

def liquidate_all():
    logger.info("=" * 80)
    logger.info("🏛️ PRV CAPITAL — LEGACY POSITION SAFE LIQUIDATION")
    logger.info("=" * 80)

    # 1. Pre-liquidation snapshot
    pre_summary = broker.get_account_summary(force_refresh=True)
    logger.info(f"Pre-Liquidation NAV:  £{pre_summary.get('total_value', 0.0):.2f}")
    logger.info(f"Pre-Liquidation Cash: £{pre_summary.get('available_cash', 0.0):.2f}")
    logger.info(f"Pre-Liquidation PPL:  £{pre_summary.get('ppl', 0.0):.2f}")

    positions = broker.get_open_positions(force_refresh=True) or []
    open_orders = broker.get_open_orders(force_refresh=True) or []
    pos_map = {p["ticker"]: p for p in positions}
    order_map = {o["ticker"]: o for o in open_orders if o.get("type") == "STOP"}

    logger.info(f"Found {len(positions)} open positions and {len(open_orders)} working orders.")

    liquidation_records = []

    for ticker in TARGET_TICKERS:
        if ticker not in pos_map:
            logger.warning(f"Ticker {ticker} not found in open positions. Skipping.")
            continue

        pos = pos_map[ticker]
        qty = abs(float(pos["quantity"]))
        avg_price = float(pos["averagePrice"])
        cur_price = float(pos["currentPrice"])
        stop_order = order_map.get(ticker)
        stop_id = str(stop_order["id"]) if stop_order else None
        stop_price = float(stop_order["stopPrice"]) if stop_order else round(avg_price * 0.975, 2)

        logger.info("-" * 60)
        logger.info(f"Processing {ticker}: Qty={qty}, AvgPrice={avg_price}p, CurPrice={cur_price}p, ActiveStopID={stop_id}")

        # Step 2: Cancel protective stop
        if stop_id:
            logger.info(f"Cancelling active protective stop {stop_id} for {ticker}...")
            cancel_res = broker.cancel_order(stop_id)
            if not cancel_res.get("success"):
                logger.error(f"Failed to cancel stop order {stop_id}: {cancel_res.get('error')}")
            time.sleep(0.5)

        # Step 3: Submit market SELL (-qty)
        logger.info(f"Submitting market SELL for {ticker}: -{qty} shares...")
        sell_res = broker.place_market_order(ticker, -qty)

        if not sell_res.get("success"):
            logger.critical(f"FATAL: Market SELL for {ticker} failed: {sell_res.get('error')}!")
            logger.info(f"Attempting to immediately reinstate protective stop for {ticker} at {stop_price}p...")
            broker.place_stop_order(ticker, qty, stop_price)
            raise RuntimeError(f"Market SELL failed for {ticker}: {sell_res.get('error')}. Stop reinstated.")

        sell_order_id = str(sell_res.get("data", {}).get("id"))
        logger.info(f"SELL order accepted by broker. Order ID: {sell_order_id}")

        # Step 4: Verify fill & zero position
        filled = False
        final_pos_qty = 0.0
        for attempt in range(15):
            time.sleep(1.0)
            cur_p = broker.get_position(ticker)
            if not cur_p or float(cur_p.get("quantity", 0.0)) == 0.0:
                filled = True
                final_pos_qty = 0.0
                break
            final_pos_qty = float(cur_p.get("quantity", 0.0))

        if not filled:
            logger.error(f"Position {ticker} did not reach 0 within 15s (remaining: {final_pos_qty})")
        else:
            logger.info(f"Position {ticker} successfully verified as 0.")

        # Step 5: Clean any residual/orphan stops
        orphans = broker.cancel_stop_orders_for_ticker(ticker)
        if orphans:
            logger.info(f"Cleaned orphan stop orders for {ticker}: {orphans}")

        record = {
            "ticker": ticker,
            "quantity": qty,
            "entry_avg_price": avg_price,
            "cancelled_stop_id": stop_id,
            "sell_order_id": sell_order_id,
            "verified_zero_position": filled,
            "cleaned_orphan_stops": orphans,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        liquidation_records.append(record)

    # 6. Post-liquidation verification
    logger.info("=" * 80)
    logger.info("🏛️ POST-LIQUIDATION VERIFICATION")
    logger.info("=" * 80)

    time.sleep(2.0)
    post_pos = broker.get_open_positions(force_refresh=True) or []
    post_orders = broker.get_open_orders(force_refresh=True) or []
    orphan_stops = broker.reconcile_orphan_stops()
    post_summary = broker.get_account_summary(force_refresh=True)
    post_nav = float(post_summary.get("total_value", 0.0))
    post_cash = float(post_summary.get("available_cash", 0.0))
    post_invested = float(post_summary.get("invested", 0.0))

    logger.info(f"Post-Liquidation NAV:      £{post_nav:.2f}")
    logger.info(f"Post-Liquidation Cash:     £{post_cash:.2f}")
    logger.info(f"Post-Liquidation Invested: £{post_invested:.2f}")
    logger.info(f"Remaining Open Positions:  {len(post_pos)}")
    logger.info(f"Remaining Open Orders:     {len(post_orders)}")
    logger.info(f"Reconciled Orphan Stops:   {len(orphan_stops)}")

    # Ground truth ledger
    ledger = broker_ledger.fetch_ground_truth_ledger(force_refresh=True)
    variance = float(ledger.get("prv_ledger_variance_gbp", 0.0))
    sdrt = float(ledger.get("sdrt_paid_gbp", 0.0))
    realised_pnl = float(ledger.get("broker_derived_realized_pnl_gbp", 0.0))
    total_loss = round(50000.0 - post_nav, 2)

    logger.info(f"Total Incident Loss:       £{total_loss:.2f}")
    logger.info(f"SDRT Paid:                 £{sdrt:.2f}")
    logger.info(f"Realised Market PnL:       £{realised_pnl:.2f}")
    logger.info(f"Ledger Variance:           £{variance:.4f}")

    results = {
        "liquidation_records": liquidation_records,
        "pre_nav": pre_summary.get("total_value", 0.0),
        "post_nav": post_nav,
        "post_cash": post_cash,
        "post_invested": post_invested,
        "open_positions_count": len(post_pos),
        "open_orders_count": len(post_orders),
        "orphan_stops_count": len(orphan_stops),
        "ledger_variance_gbp": variance,
        "legacy_incident_start_nav": 50000.0,
        "legacy_incident_final_nav": post_nav,
        "legacy_incident_total_loss": total_loss,
        "legacy_incident_sdrt": sdrt,
        "legacy_incident_realised_market_pnl": realised_pnl,
        "is_clean_slate": len(post_pos) == 0 and len(post_orders) == 0 and abs(post_nav - post_cash) < 0.05
    }

    os.makedirs("audit", exist_ok=True)
    with open("audit/legacy_liquidation_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nFINAL_JSON_RESULT=" + json.dumps(results))
    return results

if __name__ == "__main__":
    liquidate_all()
