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
LIVE_COMMENTARY = "AI Trading Floor: Active Capital Deployment Engine (US Session)."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
BANKED_PROFITS = 0.00

PRICE_MEMORY = {}

# Expanded Top 25 US 500 Giants & Trackers to ensure broad market capture
TARGET_POOL = [
    "VOO_US_EQ",   # Vanguard S&P 500
    "SPY_US_EQ",   # SPDR S&P 500
    "QQQ_US_EQ",   # Nasdaq 100 Tracker
    "AAPL_US_EQ",  # Apple
    "MSFT_US_EQ",  # Microsoft
    "NVDA_US_EQ",  # NVIDIA
    "AMZN_US_EQ",  # Amazon
    "META_US_EQ",  # Meta Platforms
    "GOOGL_US_EQ", # Alphabet
    "TSLA_US_EQ",  # Tesla
    "AMD_US_EQ",   # Advanced Micro Devices
    "AVGO_US_EQ",  # Broadcom
    "JPM_US_EQ",   # JPMorgan Chase
    "V_US_EQ",     # Visa
    "WMT_US_EQ",   # Walmart
    "MA_US_EQ",    # Mastercard
    "PG_US_EQ",    # Procter & Gamble
    "JNJ_US_EQ",   # Johnson & Johnson
    "HD_US_EQ",    # Home Depot
    "COST_US_EQ",  # Costco
    "NFLX_US_EQ",  # Netflix
    "PEP_US_EQ",   # PepsiCo
    "KO_US_EQ",    # Coca-Cola
    "DIS_US_EQ",   # Disney
    "CSCO_US_EQ"   # Cisco
]

def is_market_open() -> bool:
    # Clock Override: Forcing the US market OPEN to capture the current bull session
    return True

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    raw_time = datetime.now().strftime("%H:%M:%S")
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
    log_activity("Active Capital Deployment Engine Online. Getting idle cash to work...", "success")
    
    while True:
        if is_market_open():
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            free_cash = float(CACHED_ACCOUNT.get("free", 0))

            # --- PHASE 1: AGGRESSIVE IDLE CASH DEPLOYMENT ---
            # If we have a lot of cash doing nothing, start taking £1,000 blocks in the top 25 companies
            if free_cash > 5000.0:
                for target in TARGET_POOL:
                    if target not in owned_tickers and free_cash > 1500.0:
                        # We don't know the exact price until we own it, so we buy a £1.00 seed first,
                        # OR if we know the market is open, we can just estimate a fractional amount.
                        # To be perfectly safe with the API, we buy a small 0.1 qty to unlock the price feed immediately.
                        execute_live_order(target, 0.1, "MARKET SEED")
                        await asyncio.sleep(2)
                        fetch_live_data() # Refresh to get the price of the seed we just bought
                        free_cash = float(CACHED_ACCOUNT.get("free", 0))

            # --- PHASE 2: PORTFOLIO MANAGEMENT & INTELLIGENT SCALING ---
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
                
                if len(PRICE_MEMORY[ticker]) >= 2:
                    oldest_price = PRICE_MEMORY[ticker][0]
                    momentum_pct = ((cur_price - oldest_price) / oldest_price) * 100.0
                    
                    # If this is just a seed (invested < £10) and we have idle cash, scale it up to a £1000 Core Position!
                    if invested < 10.0 and free_cash > 1500.0:
                        target_qty = round(1000.0 / cur_price, 2)
                        if target_qty > 0:
                            log_activity(f"💰 DEPLOYING CAPITAL: Scaling {ticker} to £1000 Core Position.", "success")
                            execute_live_order(ticker, target_qty, "CORE ALLOCATION")
                            PRICE_MEMORY[ticker] = [] # Reset memory to track the new average
                    
                    # If it is a full Core Position, manage it for profit/loss
                    elif invested >= 500.0 and avg_price > 0: 
                        total_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                        
                        # Bank clean daily profits
                        if total_ret_pct >= 0.90:
                            log_activity(f"🎯 SECURING PROFIT: {ticker} (+{total_ret_pct:.2f}%). Banking gains.", "success")
                            execute_live_order(ticker, -(qty - 0.05), "TAKE PROFIT")
                            PRICE_MEMORY[ticker] = []
                            
                        # Cut losers so they don't drag down the portfolio
                        elif total_ret_pct <= -1.50:
                            log_activity(f"🛡️ CUTTING RISK: {ticker} ({total_ret_pct:.2f}%). Reallocating capital.", "warning")
                            execute_live_order(ticker, -(qty - 0.05), "STOP LOSS")
                            PRICE_MEMORY[ticker] = []

        await asyncio.sleep(15)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(continuous_intelligence_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    return {"status": "LOCKED", "detail": "AI is actively deploying idle capital across the Top 25 US pool."}

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", 50000.00)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", 50000.00)),
        "banked_profits": BANKED_PROFITS,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {"UK": False, "US": True}
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")