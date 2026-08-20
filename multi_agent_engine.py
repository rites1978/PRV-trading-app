# Add this import at the top
from risk_engine import RiskEngine

# Replace the execution block inside run_boardroom_cycle()
if best_candidate and risk["approved"]:
    # Initialize Risk Engine with current NAV
    risk_calc = RiskEngine(total_nav).calculate_position(best_candidate['yf_ticker'])
    
    qty = risk_calc['quantity']
    sl = risk_calc['stop_loss_price']
    
    print(f"✅ Executing Position Sizing: {qty} shares | Stop-Loss: ${sl}")
    
    # Update Trading 212 order payload
    payload = {"ticker": best_candidate['t212_ticker'], "quantity": qty}
    
    # [Execute Order logic...]
    # Log the risk-adjusted trade to Postgres
    db.log_trade(
        ticker=best_candidate['yf_ticker'],
        action="BUY",
        price=best_candidate['price'],
        quantity=qty,
        stop_loss=sl,
        debate_id=best_candidate['debate_id']
    )