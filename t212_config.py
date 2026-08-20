import os
from dotenv import load_dotenv

load_dotenv()

# TRADING_ENV should be either 'demo' or 'live' in your .env file
TRADING_ENV = os.getenv("TRADING_ENV", "demo").lower()

if TRADING_ENV == "live":
    BASE_URL = "https://live.trading212.com/api/v0/equity"
    print("⚠️ WARNING: SYSTEM RUNNING IN LIVE REAL-MONEY ENVIRONMENT")
else:
    BASE_URL = "https://demo.trading212.com/api/v0/equity"
    print("ℹ️ System running in PAPER TRADING (Demo) environment")

# Trading 212 Fee Structure (Real-Money Protection)
T212_FX_FEE_PCT = 0.0015  # 0.15% Currency conversion fee
UK_STAMP_DUTY_PCT = 0.005  # 0.5% for UK LSE Stocks (Buying only)

def calculate_net_alpha(expected_return_pct, is_us_stock=True):
    """
    Calculates if a trade is actually profitable after Trading 212 fees.
    If expected return is 0.2%, but FX fees (in+out) are 0.3%, the trade is a net loss.
    """
    total_fee_drag = 0.0
    
    if is_us_stock:
        # FX fee applies on buy AND sell (0.15% x 2 = 0.30% total drag)
        total_fee_drag += (T212_FX_FEE_PCT * 2)
    else:
        # UK stock: No FX fee (if account is GBP), but 0.5% Stamp Duty on buy
        total_fee_drag += UK_STAMP_DUTY_PCT
        
    net_alpha = expected_return_pct - total_fee_drag
    return net_alpha