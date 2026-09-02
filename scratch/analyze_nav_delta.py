"""
Reconciliation analysis of the £36.05 NAV delta between 20:58:15 UTC and 20:59:33 UTC
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from src.database.db import db
from src.brokers.trading212 import broker
from src.portfolio.portfolio_snapshot import portfolio_snapshot

# 1. Check all trades executed between 19:50 and 21:10 UTC
with db.get_connection() as conn:
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM trades
        WHERE timestamp >= '2026-09-02 19:50:00'
        ORDER BY timestamp ASC
    """)
    trades_window = [dict(r) for r in cur.fetchall()]

# 2. Check snapshot history in database
with db.get_connection() as conn:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, timestamp, nav, cash, invested, unrealized_pnl, realized_pnl
        FROM portfolio_snapshots
        WHERE timestamp >= '2026-09-02 20:50:00' AND timestamp <= '2026-09-02 21:05:00'
        ORDER BY id ASC
    """)
    snaps = [dict(r) for r in cur.fetchall()]

# 3. Analyze live positions, FX, and after-hours ticks
positions = broker.get_open_positions()
acc = broker.get_account_summary()

report = {
    "trades_in_window": trades_window,
    "snapshots_in_window": snaps,
    "current_broker_summary": acc,
    "positions_count": len(positions)
}

with open("scratch/nav_delta_analysis.json", "w") as f:
    json.dump(report, f, indent=2)
print("NAV_DELTA_ANALYSIS_COMPLETE")
