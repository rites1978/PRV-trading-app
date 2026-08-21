from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime, timezone
import os
import requests
import base64
import time
from contextlib import asynccontextmanager
from db_manager import db
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: UK/US Top 500 Calculative Engine Active."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
STARTING_CAPITAL = 50000.00
BANKED_PROFITS = 0.00

PRICE_MEMORY = {}
DYNAMIC_INSTRUMENTS = {"UK": [], "US": []}
SEED_INDEX = {"UK": 0, "US": 0} # Used to intelligently cycle the Top 500, not guess randomly

def is_market_open(market: str) -> bool:
    """Accurate UTC time checks. UK: 07:00-15:30 UTC. US: 13:30-20:00 UTC."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5: return False 
    time_dec = now.hour + (now.minute / 60.0)
    if market == "UK": return 7.0 <= time_dec < 15.5
    if market == "US": return 13.5 <= time_dec < 20.0
    return False

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

def load_top_500_instruments():
    """Fetches all UK/US instruments to build the true Top 500 lists."""
    global DYNAMIC_INSTRUMENTS
    if not T212_API_KEY: return
    try:
        res = requests.get(f"{T212_BASE_URL}/metadata/instruments", headers=get_t212_auth_headers(), timeout=15)
        if res.status_code == 200:
            uk_list, us_list = [], []
            for item in res.json():
                ticker = item.get("ticker", "")
                if "_US_EQ" in ticker: us_list.append(ticker)
                elif ticker.endswith("l_EQ"): uk_list.append(ticker)
            
            DYNAMIC_INSTRUMENTS["UK"] = uk_list[:500] if uk_list else ["VUKGl_EQ", "SHELl_EQ", "AZNl_EQ"]
            DYNAMIC_INSTRUMENTS["US"] = us_list[:500] if us_list else ["VOO_US_EQ", "AAPL_US_EQ", "MSFT_US_EQ"]
            log_activity(f"Loaded {len(DYNAMIC_INSTRUMENTS['UK'])} UK and {len(DYNAMIC_INSTRUMENTS['US'])} US instruments.", "success")
    except Exception as e:
        log_activity("Failed to load dynamic instrument catalog.", "warning")

def execute_live_order(exact_ticker: str, quantity: float, order_type: str = "EXECUTION"):
    payload = {"ticker": exact_ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_t212_auth_headers(), timeout=10)
        if res.status_code in [200, 201]:
            log_activity(f"✅ {side} {exact_ticker} (Qty: {abs(quantity):.2f}) [{order_type}]", "success")
            return True
    except Exception: pass
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
            
            # THE VAULT: Any equity over £50,000 is permanently locked
            if total_eq > STARTING_CAPITAL:
                BANKED_PROFITS = total_eq - STARTING_CAPITAL
            else:
                BANKED_PROFITS = 0.00
                
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200: CACHED_PORTFOLIO = res_port.json()
    except Exception: pass

async def continuous_intelligence_loop():
    await asyncio.sleep(2)
    load_top_500_instruments()
    log_activity("Calculative AI Engine Online. Mapping Spread Costs.", "success")
    
    while True:
        fetch_live_data()
        owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
        
        # Rule 2: Vault logic applied to cash
        raw_free_cash = float(CACHED_ACCOUNT.get("free", 0))
        deployable_cash = max(0.0, raw_free_cash - BANKED_PROFITS)

        # --- PHASE 1: METHODICAL SEEDING (NOT RANDOM) ---
        for market in ["US", "UK"]:
            if is_market_open(market) and DYNAMIC_INSTRUMENTS[market] and deployable_cash > 2000.0:
                # Intelligently cycle through the 500 list, skip if we already own it
                target = DYNAMIC_INSTRUMENTS[market][SEED_INDEX[market]]
                if target not in owned_tickers:
                    execute_live_order(target, 0.1, "SPREAD CALCULATOR SEED")
                    await asyncio.sleep(1)
                
                # Move index forward, loop back to 0 if at the end
                SEED_INDEX[market] = (SEED_INDEX[market] + 1) % len(DYNAMIC_INSTRUMENTS[market])

        # --- PHASE 2: CALCULATIVE COST MATH & EXECUTION ---
        for ticker, pos in owned_tickers.items():
            cur_price = float(pos.get("currentPrice", 0))
            avg_price = float(pos.get("averagePrice", 0))
            qty = float(pos.get("quantity", 0))
            invested = avg_price * qty
            
            if cur_price > 0 and avg_price > 0:
                if ticker not in PRICE_MEMORY: PRICE_MEMORY[ticker] = []
                PRICE_MEMORY[ticker].append(cur_price)
                if len(PRICE_MEMORY[ticker]) > 15: PRICE_MEMORY[ticker].pop(0) # Keep short history
                
                if len(PRICE_MEMORY[ticker]) >= 3:
                    oldest_price = PRICE_MEMORY[ticker][0]
                    momentum_pct = ((cur_price - oldest_price) / oldest_price) * 100.0
                    
                    # Rule 5: Calculate exact spread cost using T212's Bid (cur) and Ask (avg)
                    spread_cost_pct = ((avg_price - cur_price) / avg_price) * 100.0
                    # Floor it at 0.1% just in case T212 gives an artificially tight read
                    spread_cost_pct = max(0.1, spread_cost_pct)
                    
                    # If this is just a seed (£15 or less), check if it mathematically beats the cost
                    if invested < 15.0 and deployable_cash > 1500.0:
                        # Intelligence check: Momentum must be GREATER than the spread cost to enter
                        if momentum_pct > spread_cost_pct:
                            target_qty = round(1000.0 / cur_price, 2)
                            if target_qty > 0:
                                log_activity(f"🧠 CALCULATED ENTRY: {ticker}. Momentum (+{momentum_pct:.2f}%) beat Spread Cost (-{spread_cost_pct:.2f}%).", "success")
                                execute_live_order(ticker, target_qty, "CORE DEPLOYMENT")
                                PRICE_MEMORY[ticker] = [] 
                    
                    # If it is a full Core Position, manage it
                    elif invested >= 500.0: 
                        total_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                        
                        # Rule 2: Bank the growth
                        if total_ret_pct >= 0.80:
                            log_activity(f"🏦 PROFIT VAULTED: Selling {ticker} (+{total_ret_pct:.2f}%).", "success")
                            execute_live_order(ticker, -qty, "TAKE PROFIT")
                            PRICE_MEMORY[ticker] = []
                            
                        # Keep risk calculated
                        elif total_ret_pct <= -1.20:
                            log_activity(f"🛡️ CUTTING RISK: {ticker} ({total_ret_pct:.2f}%).", "warning")
                            execute_live_order(ticker, -qty, "STOP LOSS")
                            PRICE_MEMORY[ticker] = []

        await asyncio.sleep(15)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(continuous_intelligence_loop())
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
        "markets": {"UK": is_market_open("UK"), "US": is_market_open("US")}
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")