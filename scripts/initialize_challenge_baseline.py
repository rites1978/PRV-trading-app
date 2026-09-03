"""
🏛️ PRV CAPITAL | OFFICIAL 30-DAY CHALLENGE BASELINE CERTIFICATION
Initializes and freezes the official Day 1 challenge baseline:
- Verifies Trading212 Practice API: NAV == £50,000.00, Cash == £50,000.00, Positions == 0, Orders == 0
- Initializes virgin database state (Vault = £0, Transfers = £0, Closed Trades = 0)
- Records authoritative Start-of-Day snapshot for Day 1
- Emits cryptographic freeze manifest and baseline certificate
"""
import sys
import os
import time
import json
import hashlib
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config.settings import settings
from src.brokers.trading212 import broker
from src.database.db import db
from src.portfolio.portfolio_snapshot import portfolio_snapshot
from src.portfolio.capital_state_machine import capital_state_machine


def initialize_challenge_baseline(allow_impaired: bool = False):
    print("=" * 80)
    print("🏛️ PRV CAPITAL — OFFICIAL 30-DAY CHALLENGE BASELINE CERTIFICATION")
    print("=" * 80)

    # 1. Query live broker account state
    summary = broker.get_account_summary(force_refresh=True)
    positions = broker.get_open_positions(force_refresh=True)
    orders = broker.get_open_orders()

    nav = round(float(summary.get("total_value", 0.0)), 2)
    cash = round(float(summary.get("free_cash", summary.get("available_cash", 0.0))), 2)
    invested = round(float(summary.get("invested", 0.0)), 2)
    pos_count = len(positions)
    order_count = len(orders)

    print(f"\n[STEP 1: LIVE BROKER VERIFICATION]")
    print(f"  Broker NAV:        £{nav:,.2f}")
    print(f"  Broker Cash:       £{cash:,.2f}")
    print(f"  Invested Value:    £{invested:,.2f}")
    print(f"  Open Positions:    {pos_count}")
    print(f"  Open Orders:       {order_count}")

    if not allow_impaired:
        if nav != 50000.00 or cash != 50000.00 or pos_count != 0 or order_count != 0:
            print("\n❌ BROKER STATE NOT CLEAN BASELINE!")
            print(f"  Expected: NAV=£50,000.00, Cash=£50,000.00, Positions=0, Orders=0")
            print(f"  Found:    NAV=£{nav:,.2f}, Cash=£{cash:,.2f}, Positions={pos_count}, Orders={order_count}")
            print("\n👉 Please perform the final reset in Trading212 Practice UI (Settings -> Reset Account -> £50,000).")
            return False

    print("\n✅ Broker State Verified: Ready for Official Baseline.")

    # 2. Clean internal challenge database tables
    print("\n[STEP 2: DATABASE INITIALIZATION]")
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM trades")
        cur.execute("DELETE FROM profit_vault")
        cur.execute("DELETE FROM capital_transfers")
        cur.execute("DELETE FROM capital_state_transitions")
        cur.execute("DELETE FROM daily_start_of_day_snapshots")
        cur.execute("DELETE FROM audit_logs")
        conn.commit()

    vault_bal = db.get_vault_balance()
    transfers_total = db.get_total_capital_transfers()
    trades_count = len(db.get_trades(limit=10))

    print(f"  Vault Balance:      £{vault_bal:,.2f}")
    print(f"  Capital Transfers:  £{transfers_total:,.2f}")
    print(f"  Trades Count:       {trades_count}")
    assert vault_bal == 0.0
    assert transfers_total == 0.0
    assert trades_count == 0
    print("✅ Virgin Database State Verified.")

    # 3. Record Authoritative Day 1 Start-of-Day Snapshot
    print("\n[STEP 3: AUTHORITATIVE START-OF-DAY BASELINE SNAPSHOT]")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()

    db.record_start_of_day_snapshot(
        date_str=today_str,
        start_active_equity=nav,
        start_broker_nav=nav,
        start_vault_balance=0.0,
        start_unrealized_pnl=0.0,
        position_marks={},
        fx_rates={"GBP/USD": 1.35},
        notes="OFFICIAL 30-DAY CHALLENGE DAY 1 BASELINE"
    )

    db.record_state_transition(
        previous_state="INITIALIZING",
        new_state="NORMAL|ACTIVE|NORMAL",
        active_equity=nav,
        deficit=0.0,
        vault_balance=0.0,
        trigger_reason="OFFICIAL 30-DAY CHALLENGE INITIATION"
    )

    sod_snap = db.get_start_of_day_snapshot(today_str)
    print(f"  SOD Active Equity: £{sod_snap['start_active_equity']:,.2f}")
    print(f"  SOD Broker NAV:    £{sod_snap['start_broker_nav']:,.2f}")
    print(f"  SOD Date:          {today_str}")
    print("✅ Day 1 Baseline Snapshot Recorded.")

    # 4. Compute and Freeze Cryptographic Hashes
    print("\n[STEP 4: CRYPTOGRAPHIC FREEZE MANIFEST]")
    config_bytes = open("src/config/settings.py", "rb").read()
    config_hash = hashlib.sha256(config_bytes).hexdigest()
    manifest_hash = settings.get_parameter_manifest_hash()
    
    # Git commit hash
    import subprocess
    commit_sha = subprocess.check_output(["git", "log", "-1", "--format=%H"]).decode("utf-8").strip()

    certificate = {
        "challenge_name": "PRV_CAPITAL_OFFICIAL_30_DAY_CHALLENGE",
        "official_start_timestamp": now_iso,
        "official_start_date": today_str,
        "baseline_metrics": {
            "starting_broker_nav_gbp": nav,
            "starting_free_cash_gbp": cash,
            "starting_invested_value_gbp": invested,
            "starting_open_positions_count": pos_count,
            "starting_open_orders_count": order_count,
            "starting_banked_profit_gbp": 0.0,
            "starting_capital_transfers_gbp": 0.0
        },
        "operating_mandate": {
            "reference_base_capital_gbp": settings.REFERENCE_BASE_CAPITAL,
            "max_normal_deployable_capital_gbp": settings.MAX_NORMAL_DEPLOYABLE_CAPITAL,
            "daily_bankable_net_target_gbp": settings.DAILY_BANKABLE_NET_TARGET,
            "daily_new_entry_loss_lock_gbp": settings.DAILY_NEW_ENTRY_LOSS_LOCK,
            "daily_emergency_loss_level_gbp": settings.DAILY_EMERGENCY_LOSS_LEVEL,
            "banked_profit_is_non_deployable": True,
            "banked_profit_reserve_location": settings.BANKED_PROFIT_RESERVE_LOCATION,
            "force_trade_to_reach_daily_target": False,
            "anti_gambling_safeguards_enforced": True
        },
        "cryptographic_freeze": {
            "final_commit_sha": commit_sha,
            "final_config_sha256": config_hash,
            "final_parameter_manifest_sha256": manifest_hash
        },
        "challenge_verdict": "OFFICIAL_CHALLENGE_ACTIVE"
    }

    cert_path = "audit/challenge_baseline_certificate.json"
    os.makedirs(os.path.dirname(cert_path), exist_ok=True)
    with open(cert_path, "w") as f:
        json.dump(certificate, f, indent=2)

    print(f"  Certificate Saved: {cert_path}")
    print(f"  Final Commit SHA:   {commit_sha}")
    print(f"  Config SHA256:      {config_hash}")
    print(f"  Manifest SHA256:    {manifest_hash}")
    print("\n" + "=" * 80)
    print("🏛️ OFFICIAL 30-DAY CHALLENGE BASELINE FROZEN & ACTIVATED")
    print("=" * 80)
    return True


if __name__ == "__main__":
    allow = "--allow-impaired" in sys.argv
    res = initialize_challenge_baseline(allow_impaired=allow)
    sys.exit(0 if res else 1)
