"""
Closed-Market Execution, Orders Audit, and NAV Delta Bridge
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from datetime import datetime, timezone
from src.brokers.trading212 import broker
from src.database.db import db
from src.portfolio.portfolio_snapshot import portfolio_snapshot

# 1. Fetch open orders and recent order history from broker
open_orders = broker.get_open_orders()

with db.get_connection() as conn:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, trade_id, symbol, action, quantity, price, timestamp, mode, trade_reason
        FROM trades
        ORDER BY timestamp DESC
    """)
    trades = [dict(r) for r in cur.fetchall()]

# 2. Extract snapshot history to analyze the 20:58 vs 20:59 NAV move
with db.get_connection() as conn:
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM portfolio_snapshots
        ORDER BY id DESC LIMIT 10
    """)
    recon_events = [dict(r) for r in cur.fetchall()]

current_snap = portfolio_snapshot.get_authoritative_snapshot(force_refresh=True)

out = {
    "open_orders": open_orders,
    "trades": trades,
    "recon_events": recon_events,
    "current_snap": {
        "snapshot_id": current_snap["snapshot_id"],
        "timestamp": current_snap["timestamp"],
        "account_summary": current_snap["account_summary"],
        "positions": [
            {
                "symbol": p["symbol"],
                "quantity": p["quantity"],
                "current_price_raw": p["current_price_raw"],
                "current_price_gbp": p["current_price_gbp"],
                "average_price_gbp": p["average_price_gbp"],
                "market_value_gbp": p["market_value_gbp"],
                "cost_basis_gbp": p["cost_basis_gbp"],
                "is_uk": p["is_uk"],
                "instrument_currency": p["instrument_currency"]
            }
            for p in current_snap["positions"]
        ]
    }
}

with open("scratch/audit_results.json", "w") as f:
    json.dump(out, f, indent=2)
print("AUDIT_COMPLETE")
