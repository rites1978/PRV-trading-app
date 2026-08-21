from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime, timezone
import os
import requests
import base64
import warnings
from contextlib import asynccontextmanager
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: £10k HEAVY STRIKE ENGINE (API Compliant)."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
STARTING_CAPITAL = 50000.00
BANKED_PROFITS = 0.00
PRICE_MEMORY = {}

# FIXED POOL: UK-compliant ETFs and legacy T212 API tickers applied
HEAVY_STRIKE_POOL = [
    "NVDA_US_EQ",  # NVIDIA
    "TSLA_US_EQ",  # Tesla
    "MSTR_US_EQ",  # MicroStrategy (Extreme Beta)
    "COIN_US_EQ",  # Coinbase
    "FB_US_EQ",    # Meta Platforms (T212 API strictly requires the legacy 'FB' ticker)
    "AMD_US_EQ",   # AMD
    "EQQQl_EQ",    # Invesco EQQQ Nasdaq-100 (UK/EU Compliant UCITS version)
    "AAPL_US_EQ"   # Apple
]

FX_ROUNDTRIP_FEE_PCT = 0.30 

def is_market_open() -> bool:
    return True # US Market Forced Open for final session hours

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
            if "Max position" not in err and "insufficient" not in err.lower():
                log_activity(f"Order skipped {exact_ticker}: {err}", "warning")
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
            
            if total_eq > STARTING_CAPITAL:
                BANKED_PROFITS = total_eq - STARTING_CAPITAL
            else:
                BANKED_PROFITS = 0.00
                
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200: CACHED_PORTFOLIO = res_port.json()
    except Exception: pass

async def heavy_strike_engine():
    await asyncio.sleep(2)
    log_activity("£10,000 Heavy Strike Engine Online. Deploying Maximum Capital.", "success")
    
    while True:
        fetch_live_data()
        owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
        
        raw_free_cash = float(CACHED_ACCOUNT.get("free", 0))
        deployable_cash = max(0.0, raw_free_cash - BANKED_PROFITS)

        # --- PHASE 1: DATA SEEDING ---
        if deployable_cash > 5000.0:
            for target in HEAVY_STRIKE_POOL:
                if target not in owned_tickers:
                    execute_live_order(target, 0.05, "DATA SEED")
                    await asyncio.sleep(0.5)

        # --- PHASE 2: £10,000 STRIKES & NET PROFIT HARVESTING ---
        for ticker, pos in owned_tickers.items():
            if ticker not in HEAVY_STRIKE_POOL: continue
            
            cur_price = float(pos.get("currentPrice", 0))
            avg_price = float(pos.get("averagePrice", 0))
            qty = float(pos.get("quantity", 0))
            invested = avg_price * qty
            
            if cur_price > 0 and avg_price > 0:
                if ticker not in PRICE_MEMORY: PRICE_MEMORY[ticker] = []
                PRICE_MEMORY[ticker].append(cur_price)
                if len(PRICE_MEMORY[ticker]) > 5: PRICE_MEMORY[ticker].pop(0)
                
                spread_pct = max(0.05, ((avg_price - cur_price) / avg_price) * 100.0)
                total_friction_pct = spread_pct + FX_ROUNDTRIP_FEE_PCT
                
                # SCALING: £10,000 BLOCK DEPLOYMENT
                if invested < 20.0 and deployable_cash > 9500.0 and len(PRICE_MEMORY[ticker]) >= 3:
                    oldest_price = PRICE_MEMORY[ticker][0]
                    momentum_pct = ((cur_price - oldest_price) / oldest_price) * 100.0
                    
                    if momentum_pct >= (total_friction_pct + 0.10):
                        target_spend = min(10000.0, deployable_cash)
                        target_qty = round(target_spend / cur_price, 2)
                        if target_qty > 0:
                            log_activity(f"💰 HEAVY STRIKE: Slamming £{target_spend:,.2f} into {ticker} (Mom: +{momentum_pct:.2f}%).", "success")
                            execute_live_order(ticker, target_qty, "HEAVY BLOCK")
                            deployable_cash -= target_spend
                            PRICE_MEMORY[ticker] = []

                # PROFIT / RISK MANAGEMENT FOR £10k BLOCKS
                elif invested >= 5000.0:
                    gross_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                    net_ret_pct = gross_ret_pct - total_friction_pct
                    
                    if net_ret_pct >= 0.40:
                        log_activity(f"🏦 MASSIVE PROFIT SECURED: {ticker} (Gross: +{gross_ret_pct:.2f}%, Net: +{net_ret_pct:.2f}%).", "success")
                        execute_live_order(ticker, -qty, "TAKE PROFIT")
                        PRICE_MEMORY[ticker] = []
                        
                    elif gross_ret_pct <= -1.25:
                        log_activity(f"🛡️ CUTTING BLEED: Closing {ticker} ({gross_ret_pct:.2f}%).", "warning")
                        execute_live_order(ticker, -qty, "STOP LOSS")
                        PRICE_MEMORY[ticker] = []

        await asyncio.sleep(4)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(heavy_strike_engine())
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