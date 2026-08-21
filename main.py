from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime, timezone
import os
import requests
import base64
import time
from contextlib import asynccontextmanager
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Friction-Aware Net Profit Engine Active."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
STARTING_CAPITAL = 50000.00
BANKED_PROFITS = 0.00

PRICE_MEMORY = {}

# Top-Tier US Market Leaders & Index Trackers
APEX_POOL = [
    "VOO_US_EQ",   # Vanguard S&P 500
    "SPY_US_EQ",   # SPDR S&P 500
    "QQQ_US_EQ",   # Invesco QQQ
    "NVDA_US_EQ",  # NVIDIA
    "AAPL_US_EQ",  # Apple
    "MSFT_US_EQ",  # Microsoft
    "AMZN_US_EQ",  # Amazon
    "META_US_EQ",  # Meta
    "GOOGL_US_EQ", # Alphabet
    "TSLA_US_EQ",  # Tesla
    "AMD_US_EQ",   # AMD
    "AVGO_US_EQ",  # Broadcom
    "NFLX_US_EQ",  # Netflix
    "COST_US_EQ",  # Costco
    "JPM_US_EQ"    # JPMorgan Chase
]

# Trading 212 standard round-trip FX fee (0.15% buy + 0.15% sell)
FX_ROUNDTRIP_FEE_PCT = 0.30 

def is_market_open() -> bool:
    return True

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    raw_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    entry = {"time": raw_time, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 100: SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{raw_time}] {message}"
    print(f"[{level.upper()}] {raw_time} - {message}")

T212_API_KEY = os.getenv("T212_API_KEY", "").strip()
T212_API_SECRET = os.getenv("T212_API_SECRET", "").strip()
T212_BASE_URL = "https://demo.trading212.com/api/v0/equity"

def get_t212_auth_headers():
    raw_credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

def execute_live_order(exact_ticker: str, quantity: float, order_type: str = "EXECUTION"):
    payload = {"ticker": exact_ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_t212_auth_headers(), timeout=10)
        if res.status_code in [200, 201]:
            log_activity(f"⚡ {side} {exact_ticker} (Qty: {abs(quantity):.2f}) [{order_type}]", "success")
            return True
        else:
            err = res.json().get("detail", res.text) if "application/json" in res.headers.get("content-type", "") else res.text
            if "Max position" not in err:
                log_activity(f"Order skipped {exact_ticker}: {err}", "warning")
    except Exception as e:
        log_activity(f"API Error on {exact_ticker}: {str(e)}", "error")
    return False

def fetch_live_data():
    global CACHED_PORTFOLIO, CACHED_ACCOUNT, BANKED_PROFITS
    if not T212_API_KEY: return
    headers = get_t212_auth_headers()
    try:
        res_cash = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res_cash.status_code == 200: 
            CACHED_ACCOUNT = res_cash.json()
            total_eq = float(CACHED_ACCOUNT.get("total", STARTING_CAPITAL))
            
            # STRICT PROFIT VAULT: Lock away any total equity exceeding starting capital
            if total_eq > STARTING_CAPITAL:
                BANKED_PROFITS = total_eq - STARTING_CAPITAL
            else:
                BANKED_PROFITS = 0.00
                
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200: CACHED_PORTFOLIO = res_port.json()
    except Exception: pass

async def friction_aware_trading_loop():
    await asyncio.sleep(2)
    log_activity("Friction-Aware Engine Online. Accounting for 0.30% FX fee and live spreads.", "success")
    
    while True:
        fetch_live_data()
        owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
        
        raw_free_cash = float(CACHED_ACCOUNT.get("free", 0))
        deployable_cash = max(0.0, raw_free_cash - BANKED_PROFITS)

        # --- PHASE 1: SEEDING TARGET POOL TO READ LIVE BID/ASK ---
        if deployable_cash > 3000.0:
            for target in APEX_POOL:
                if target not in owned_tickers:
                    execute_live_order(target, 0.05, "DATA SEED")
                    await asyncio.sleep(0.5)

        # --- PHASE 2: CALCULATIVE COST-AWARE EXECUTION ---
        for ticker, pos in owned_tickers.items():
            if ticker not in APEX_POOL: continue
            
            cur_price = float(pos.get("currentPrice", 0))
            avg_price = float(pos.get("averagePrice", 0))
            qty = float(pos.get("quantity", 0))
            invested = avg_price * qty
            
            if cur_price > 0 and avg_price > 0:
                if ticker not in PRICE_MEMORY: PRICE_MEMORY[ticker] = []
                PRICE_MEMORY[ticker].append(cur_price)
                if len(PRICE_MEMORY[ticker]) > 12: PRICE_MEMORY[ticker].pop(0)
                
                # Calculate live entry spread
                spread_pct = max(0.05, ((avg_price - cur_price) / avg_price) * 100.0)
                # Total round-trip trading cost: Spread + 0.30% FX Fee
                total_friction_pct = spread_pct + FX_ROUNDTRIP_FEE_PCT
                
                # 1. CORE ALLOCATION (Only enter if momentum exceeds total friction + safety buffer)
                if invested < 15.0 and deployable_cash > 2500.0 and len(PRICE_MEMORY[ticker]) >= 3:
                    oldest_price = PRICE_MEMORY[ticker][0]
                    momentum_pct = ((cur_price - oldest_price) / oldest_price) * 100.0
                    
                    required_hurdle = total_friction_pct + 0.15 # Must beat all costs + 0.15% edge
                    
                    if momentum_pct >= required_hurdle:
                        target_qty = round(2500.0 / cur_price, 2)
                        if target_qty > 0:
                            log_activity(f"🧠 CALCULATED ENTRY: {ticker} (Mom: +{momentum_pct:.2f}% > Cost: {total_friction_pct:.2f}%).", "success")
                            execute_live_order(ticker, target_qty, "CORE POSITION")
                            deployable_cash -= 2500.0
                            PRICE_MEMORY[ticker] = []

                # 2. NET PROFIT HARVESTING & RISK MITIGATION
                elif invested >= 500.0:
                    gross_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                    net_ret_pct = gross_ret_pct - total_friction_pct
                    
                    # Take-Profit: Must clear all friction + minimum 0.50% true net gain
                    if net_ret_pct >= 0.50:
                        log_activity(f"🏦 NET PROFIT HARVEST: {ticker} (Gross: +{gross_ret_pct:.2f}%, Net: +{net_ret_pct:.2f}%). Vaulting gains.", "success")
                        execute_live_order(ticker, -qty, "TAKE PROFIT")
                        PRICE_MEMORY[ticker] = []
                        
                    # Stop-Loss: Cut if gross drop hits -1.50%
                    elif gross_ret_pct <= -1.50:
                        log_activity(f"🛡️ CAPITAL PROTECTION: Closing {ticker} ({gross_ret_pct:.2f}%).", "warning")
                        execute_live_order(ticker, -qty, "STOP LOSS")
                        PRICE_MEMORY[ticker] = []

        await asyncio.sleep(6)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(friction_aware_trading_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", STARTING_CAPITAL)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", STARTING_CAPITAL)),
        "banked_profits": BANKED_PROFITS,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {"UK": False, "US": True}
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")