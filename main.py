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
LIVE_COMMENTARY = "AI Trading Floor: Live Probe & Memory Engine Active."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
BANKED_PROFITS = 0.00

# The AI's internal short-term memory (stores prices every 30s)
PRICE_MEMORY = {}

# Focused US 500 / Mega-Cap Target List
TARGET_POOL = [
    "VOO_US_EQ",   # Vanguard S&P 500
    "SPY_US_EQ",   # SPDR S&P 500
    "AAPL_US_EQ",  # Apple
    "MSFT_US_EQ",  # Microsoft
    "NVDA_US_EQ",  # NVIDIA
    "AMZN_US_EQ",  # Amazon
    "META_US_EQ"   # Meta
]

def is_market_open() -> bool:
    """Checks if US market is open (13:30 to 20:00 UTC / 9:30 AM to 4:00 PM EST)"""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5: return False 
    time_dec = now.hour + (now.minute / 60.0)
    return 13.5 <= time_dec < 20.0

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 100: SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{timestamp}] {message}"
    print(f"[{level.upper()}] {timestamp} - {message}")

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
    """Runs continuously, building an internal price map and calculating clean entries."""
    await asyncio.sleep(2)
    log_activity("Live Probe & Memory Engine Online. Establishing data streams...", "success")
    
    while True:
        if is_market_open():
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            free_cash = float(CACHED_ACCOUNT.get("free", 0))

            # --- PHASE 1: SEEDING THE DATA PROBES ---
            # We buy ~£2 of target stocks so T212 starts feeding us their live prices in the portfolio
            for target in TARGET_POOL:
                if target not in owned_tickers and free_cash > 50.0:
                    # Send a micro-order to establish the live data feed
                    execute_live_order(target, 0.05, "DATA PROBE")
                    await asyncio.sleep(1)

            # --- PHASE 2: MEMORY BUFFER & INTELLIGENT STRIKES ---
            for ticker, pos in owned_tickers.items():
                if ticker not in TARGET_POOL: continue
                
                cur_price = float(pos.get("currentPrice", 0))
                avg_price = float(pos.get("averagePrice", 0))
                qty = float(pos.get("quantity", 0))
                invested = avg_price * qty
                
                if cur_price > 0:
                    if ticker not in PRICE_MEMORY:
                        PRICE_MEMORY[ticker] = []
                    
                    # Store current price, keep last 20 data points (~10 mins of history)
                    PRICE_MEMORY[ticker].append(cur_price)
                    if len(PRICE_MEMORY[ticker]) > 20:
                        PRICE_MEMORY[ticker].pop(0)
                
                # --- INTELLIGENT DECISION MATH ---
                if len(PRICE_MEMORY[ticker]) >= 10:
                    oldest_price = PRICE_MEMORY[ticker][0]
                    momentum_pct = ((cur_price - oldest_price) / oldest_price) * 100.0
                    
                    # If invested amount is tiny (it's just a probe), look for a breakout
                    if invested < 10.0:
                        # Calculation: Spread cost is ~0.15%. We need momentum > 0.35% to confirm a real bull run.
                        if momentum_pct >= 0.35 and free_cash > 500.0:
                            strike_qty = round(500.0 / cur_price, 2)
                            log_activity(f"🧠 CALCULATED STRIKE: {ticker} surging (+{momentum_pct:.2f}%). Beating spread cost.", "success")
                            execute_live_order(ticker, strike_qty, "ALPHA ENTRY")
                            # Reset memory so we don't buy twice in a row
                            PRICE_MEMORY[ticker] = []
                    
                    # If invested amount is large (we took a position), manage risk
                    elif invested >= 10.0 and avg_price > 0:
                        total_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                        
                        if total_ret_pct >= 0.80:
                            log_activity(f"🎯 PROFIT SECURED: {ticker} (+{total_ret_pct:.2f}%)", "success")
                            # Sell everything EXCEPT a tiny fraction so we keep the live data feed alive!
                            execute_live_order(ticker, -(qty - 0.05), "TAKE PROFIT")
                            PRICE_MEMORY[ticker] = []
                            
                        elif total_ret_pct <= -1.25:
                            log_activity(f"🛡️ RISK CUT: {ticker} dropping ({total_ret_pct:.2f}%)", "warning")
                            execute_live_order(ticker, -(qty - 0.05), "STOP LOSS")
                            PRICE_MEMORY[ticker] = []

        else:
            log_activity("US Markets are currently closed. Waiting for session open.", "info")

        # Constant active loop, analyzing every 30 seconds
        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(continuous_intelligence_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    return {"status": "LOCKED", "detail": "Manual disabled. AI is actively mapping internal price buffers."}

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", 50000.00)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", 50000.00)),
        "banked_profits": BANKED_PROFITS,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {"UK": False, "US": is_market_open()}
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")