import sys
from src.config.settings import settings
from src.brokers.broker_ledger import broker_ledger
from src.brokers.trading212 import broker
from src.portfolio.daily_objective_service import daily_objective_service
from src.strategies.registry import strategy_registry

def main():
    print("================ PRV SYSTEM VERIFICATION ================")
    
    # 1. V1 Parameter Manifest
    v1_hash = settings.get_parameter_manifest_hash()
    expected_v1_hash = "7c512be5bc26910c1c4ed81a3e650480a676cd750faa49bc8dbd8901360bc708"
    v1_match = (v1_hash == expected_v1_hash)
    print(f"V1 Manifest SHA-256: {v1_hash}")
    print(f"V1 Manifest Match: {v1_match}")
    
    v1_meta = strategy_registry.get_strategy("V1")
    v2_meta = strategy_registry.get_strategy("V2")
    print(f"V1 Status: {v1_meta.get('status')}, Mode: {v1_meta.get('execution_mode')}, Can Route: {v1_meta.get('can_route_orders', False)}")
    print(f"V2 Status: {v2_meta.get('status')}, Mode: {v2_meta.get('execution_mode')}, Can Route: {v2_meta.get('can_route_orders', True)}")
    
    # 2. Broker Ground Truth Ledger
    ledger = broker_ledger.fetch_ground_truth_ledger(force_refresh=True)
    print("\n--- BROKER LEDGER ---")
    print(f"Broker NAV: £{ledger['broker_nav_gbp']:.2f}")
    print(f"Cash: £{ledger['cash_gbp']:.2f}")
    print(f"Invested: £{ledger['invested_value_gbp']:.2f}")
    print(f"Ledger Variance: £{ledger['prv_ledger_variance_gbp']:.2f}")
    print(f"Reconciled: {ledger['is_reconciled']}")
    print(f"Open Positions: {ledger['open_positions_count']}")
    
    # 3. Live Positions & Working Protective Stops
    open_positions = broker.get_open_positions()
    open_tickers = {p['ticker'] for p in open_positions}
    all_orders = broker.get_open_orders()
    stop_orders = [
        o for o in all_orders
        if o.get('type') in ('STOP', 'STOP_LIMIT')
        and o.get('status') in ('UNCONFIRMED', 'NEW', 'SUBMITTED', 'LOCAL')
    ]
    orphan_stops = [o for o in stop_orders if o['ticker'] not in open_tickers]
    
    print(f"\nLive Positions ({len(open_positions)}):")
    for p in open_positions:
        print(f"  - {p['ticker']}: qty={p['quantity']}, avgPrice={p['averagePrice']}, curPrice={p['currentPrice']}")
        
    print(f"\nWorking Stops ({len(stop_orders)}):")
    for s in stop_orders:
        print(f"  - Order {s.get('id')}: {s.get('ticker')}, stopPrice={s.get('stopPrice')}, qty={s.get('quantity')}")
        
    print(f"\nOrphan Stops: {len(orphan_stops)}")
    
    # 4. Daily Objective & Anti-Overtrading Mandate
    daily = daily_objective_service.get_daily_status(force_refresh=True)
    print("\n--- DAILY OBJECTIVE MANDATE ---")
    print(f"Daily State: {daily.get('daily_state')}")
    print(f"Emergency Risk Mode: {daily.get('emergency_risk_mode')}")
    print(f"New Discretionary Entries Allowed: {daily.get('new_discretionary_entries_allowed')}")
    print(f"Daily Gross Realized PnL: £{daily.get('daily_gross_realized_pnl_gbp'):.2f}")
    print(f"Daily MTM PnL: £{daily.get('daily_mtm_pnl_gbp'):.2f}")
    print(f"Account Mode: {settings.ACCOUNT_MODE}")
    print(f"Real Money Trading Enabled: {settings.REAL_MONEY_TRADING_ENABLED}")
    print(f"Practice New Entries Allowed: {getattr(settings, 'PRACTICE_NEW_ENTRIES_ALLOWED', True)}")
    print("==========================================================")

if __name__ == '__main__':
    main()
