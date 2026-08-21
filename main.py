from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime, timezone
import os
import requests
import base64
import time
import random
from contextlib import asynccontextmanager
from db_manager import db
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: UK/US Top 500 Engine with Strict Profit Vault."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
STARTING_CAPITAL = 50000.00
BANKED_PROFITS = 0.00

PRICE_MEMORY = {}
DYNAMIC_INSTRUMENTS = {"UK": [], "US": []}

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
    """Dynamically fetches all available US and UK instruments to build the true 500 pools."""
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
            
            # Ensure we have broad pools
            DYNAMIC_INSTRUMENTS["UK"] = uk_list if uk_list else ["VUKGl_EQ", "SHELl_EQ", "AZNl_EQ", "HSBA_EQ"]
            DYNAMIC_INSTRUMENTS["US"] = us_list if us_list else ["VOO_US_EQ", "AAPL_US_EQ", "MSFT_US_EQ", "NVDA_US_EQ"]
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
            
            # THE PROFIT VAULT: Strictly lock away any total equity above £50,000
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
    log_activity("UK/US Top 500 Engine Online. Enforcing strict profit vault.", "success")
    
    while True:
        fetch_live_data()
        owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
        
        # Deployable cash NEVER includes banked profits
        raw_free_cash = float(CACHED_ACCOUNT.get("free", 0))
        deployable_cash = max(0.0, raw_free_cash - BANKED_PROFITS)

        # --- PHASE 1: ACTIVE DEPLOYMENT INTO TOP 500 (US & UK) ---
        active_pool = []
        if is_market_open("UK"): active_pool.extend(DYNAMIC_INSTRUMENTS["UK"])
        if is_market_open("US"): active_pool.extend(DYNAMIC_INSTRUMENTS["US"])
        
        if active_pool and deployable_cash > 2000.0:
            target = random.choice(active_pool)
            if target not in owned_tickers:
                execute_live_order(target, 0.1, "MARKET SEED")
                await asyncio.sleep(2)
                fetch_live_data()

        # --- PHASE 2: CALCULATIVE SCALING & PROFIT BANKING ---
        for ticker, pos in owned_tickers.items():
            cur_price = float(pos.get("currentPrice", 0))
            avg_price = float(pos.get("averagePrice", 0))
            qty = float(pos.get("quantity", 0))
            invested = avg_price * qty
            
            if cur_price > 0:
                if ticker not in PRICE_MEMORY: PRICE_MEMORY[ticker] = []
                PRICE_MEMORY[ticker].append(cur_price)
                if len(PRICE_MEMORY[ticker]) > 10: PRICE_MEMORY[ticker].pop(0)
            
            if len(PRICE_MEMORY[ticker]) >= 2:
                # Scale seeds into £1000 blocks if we have deployable cash
                if invested < 15.0 and deployable_cash > 1500.0:
                    target_qty = round(1000.0 / cur_price, 2)
                    if target_qty > 0:
                        log_activity(f"💰 DEPLOYING CAPITAL: Scaling {ticker} to £1000 Core Position.", "success")
                        execute_live_order(ticker, target_qty, "CORE ALLOCATION")
                        PRICE_MEMORY[ticker] = []
                
                # Bank profits or cut losses on Core Positions
                elif invested >= 500.0 and avg_price > 0: 
                    total_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                    
                    if total_ret_pct >= 0.90:
                        log_activity(f"🏦 VAULT DEPOSIT: Selling {ticker} (+{total_ret_pct:.2f}%). Locking profit.", "success")
                        execute_live_order(ticker, -qty, "TAKE PROFIT")
                        PRICE_MEMORY[ticker] = []
                        
                    elif total_ret_pct <= -1.50:
                        log_activity(f"🛡️ CUTTING RISK: {ticker} ({total_ret_pct:.2f}%). Reallocating.", "warning")
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