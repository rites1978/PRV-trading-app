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
LIVE_COMMENTARY = "AI Trading Floor: Live Probe Engine Active (Clock Override)."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
BANKED_PROFITS = 0.00

PRICE_MEMORY = {}

TARGET_POOL = [
    "VOO_US_EQ",   # Vanguard S&P 500
    "SPY_US_EQ",   # SPDR S&P 500
    "AAPL_US_EQ",  # Apple
    "MSFT_US_EQ",  # Microsoft
    "NVDA_US_EQ",  # NVIDIA
    "AMZN_US_EQ",  # Amazon
    "META_US_EQ"   # Meta Platforms
]

def is_market_open() -> bool:
    # SERVER CLOCK OVERRIDE: Bypassing the broken Render time check. 
    # Forcing the AI to recognize the US market is OPEN right now.
    return True

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    # Grabbing raw server time just so we can see how badly Render's clock is off in the logs
    raw_time = datetime.now().strftime("%H:%M:%S (Server)")
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

def execute_live_order(exact_ticker: str, quantity: float, order_type: str = "PROBE"):
    payload = {"ticker": exact_ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_t212_auth_headers(), timeout=10)
        if res.status_code in [200, 201]:
            log_activity(f"✅ {side} {exact_ticker} (Qty: {abs(quantity):.2f}) [{order_type}]", "success")
            return True
        else:
            err = res.json().get("detail", res.text) if res.headers.get("content-type", "").startswith("application/json") else res.text
            log_activity(f"Order skipped for {exact_ticker}: {err}", "warning")
            return False
    except Exception as e:
        log_activity(f"API Error on {exact_ticker}: {str(e)}", "error")
        return False

def fetch_live_data():
    global CACHED_PORTFOLIO, CACHED_ACCOUNT
    if not T212_API_KEY: return
    headers = get_t212_auth_headers()
    try:
        res_cash = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res_cash.status_code == 200: CACHED_ACCOUNT = res_cash.json()
        
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200: CACHED_PORTFOLIO = res_port.json()
    except Exception: pass

async def continuous_intelligence_loop():
    await asyncio.sleep(2)
    log_activity("Live Probe Engine Online (Clock Override Active). Deploying market seeds...", "success")
    
    while True:
        if is_market_open():
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            free_cash = float(CACHED_ACCOUNT.get("free", 0))

            # --- PHASE 1: SEEDING PROBES TO FORCE LIVE DATA STREAM ---
            for target in TARGET_POOL:
                if target not in owned_tickers and free_cash > 50.0:
                    execute_live_order(target, 0.05, "DATA PROBE")
                    await asyncio.sleep(2)

            # --- PHASE 2: CALCULATING SPREAD VS MOMENTUM ---
            for ticker, pos in owned_tickers.items():
                if ticker not in TARGET_POOL: continue
                
                cur_price = float(pos.get("currentPrice", 0))
                avg_price = float(pos.get("averagePrice", 0))
                qty = float(pos.get("quantity", 0))
                invested = avg_price * qty
                
                if cur_price > 0:
                    if ticker not in PRICE_MEMORY:
                        PRICE_MEMORY[ticker] = []
                    
                    PRICE_MEMORY[ticker].append(cur_price)
                    if len(PRICE_MEMORY[ticker]) > 20:
                        PRICE_MEMORY[ticker].pop(0)
                
                if len(PRICE_MEMORY[ticker]) >= 8:
                    oldest_price = PRICE_MEMORY[ticker][0]
                    momentum_pct = ((cur_price - oldest_price) / oldest_price) * 100.0
                    
                    if invested < 15.0: # It's just a probe
                        if momentum_pct >= 0.35 and free_cash > 500.0:
                            strike_qty = round(500.0 / cur_price, 2)
                            log_activity(f"🧠 STRIKE: {ticker} (+{momentum_pct:.2f}%). Momentum beats spread cost.", "success")
                            execute_live_order(ticker, strike_qty, "ALPHA ENTRY")
                            PRICE_MEMORY[ticker] = []
                    
                    elif invested >= 15.0 and avg_price > 0: # Full position
                        total_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                        if total_ret_pct >= 0.80:
                            log_activity(f"🎯 SECURING PROFIT: {ticker} (+{total_ret_pct:.2f}%)", "success")
                            execute_live_order(ticker, -(qty - 0.05), "TAKE PROFIT")
                            PRICE_MEMORY[ticker] = []
                        elif total_ret_pct <= -1.25:
                            log_activity(f"🛡️ CUTTING RISK: {ticker} ({total_ret_pct:.2f}%)", "warning")
                            execute_live_order(ticker, -(qty - 0.05), "STOP LOSS")
                            PRICE_MEMORY[ticker] = []

        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(continuous_intelligence_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    return {"status": "LOCKED", "detail": "Manual disabled. AI is deploying live probes."}

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", 50000.00)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", 50000.00)),
        "banked_profits": BANKED_PROFITS,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {"UK": False, "US": True} # Forced open for the dashboard
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")