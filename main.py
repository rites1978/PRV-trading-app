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
LIVE_COMMENTARY = "PRV Capital: Core Engine Active."

STARTING_CAPITAL = 50000.00
MAX_DAILY_LOSS_PCT = 0.05
FX_ROUNDTRIP_FEE_PCT = 0.30

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": STARTING_CAPITAL, "free": STARTING_CAPITAL}
BANKED_PROFITS = 0.00
TRADING_HALTED = False

# Core liquid blue-chip pool
CORE_POOL = [
    "AAPL_US_EQ", "MSFT_US_EQ", "NVDA_US_EQ", "AMZN_US_EQ", "GOOGL_US_EQ",
    "TSLA_US_EQ", "VUKGl_EQ", "SHELl_EQ", "AZNl_EQ", "HSBA_EQ"
]

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
T212_BASE_URL = os.getenv("T212_BASE_URL", "https://demo.trading212.com/api/v0/equity")

def get_auth_headers():
    raw_creds = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(raw_creds.encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

def execute_order(ticker: str, quantity: float) -> bool:
    payload = {"ticker": ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_auth_headers(), timeout=10)
        if res.status_code in [200, 201]:
            log_activity(f"ORDER FILLED: {side} {ticker} (Qty: {abs(quantity):.2f})", "success")
            return True
        else:
            err_text = res.text
            if "Max position" not in err_text and "insufficient" not in err_text.lower():
                log_activity(f"ORDER REJECTED ({ticker}): {err_text}", "warning")
    except Exception as e:
        log_activity(f"API EXCEPTION ({ticker}): {str(e)}", "error")
    return False

def sync_state():
    global CACHED_PORTFOLIO, CACHED_ACCOUNT, BANKED_PROFITS, TRADING_HALTED
    if not T212_API_KEY: return
    headers = get_auth_headers()
    try:
        res_cash = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res_cash.status_code == 200:
            CACHED_ACCOUNT = res_cash.json()
            total_eq = float(CACHED_ACCOUNT.get("total", STARTING_CAPITAL))
            
            # 5% Daily Loss Kill Switch
            if (STARTING_CAPITAL - total_eq) >= (STARTING_CAPITAL * MAX_DAILY_LOSS_PCT):
                if not TRADING_HALTED:
                    log_activity("CRITICAL: 5% Daily Loss Limit Reached. Trading HALTED.", "error")
                TRADING_HALTED = True
            
            # Profit Vaulting
            if total_eq > STARTING_CAPITAL:
                BANKED_PROFITS = total_eq - STARTING_CAPITAL
            else:
                BANKED_PROFITS = 0.00

        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200:
            CACHED_PORTFOLIO = res_port.json()
    except Exception as e:
        log_activity(f"State sync error: {str(e)}", "error")

async def trading_loop():
    await asyncio.sleep(2)
    log_activity("PRV Capital Engine Online.", "success")
    
    while True:
        sync_state()
        
        if TRADING_HALTED:
            await asyncio.sleep(30)
            continue

        owned = {p.get("ticker"): p for p in CACHED_PORTFOLIO}
        free_cash = float(CACHED_ACCOUNT.get("free", STARTING_CAPITAL))
        deployable_cash = max(0.0, free_cash - BANKED_PROFITS)

        # Capital Deployment: If cash is sitting idle, methodically scale into the core pool
        if deployable_cash > 2000.0:
            for target in CORE_POOL:
                if target not in owned:
                    log_activity(f"Deploying capital into {target}...", "info")
                    success = execute_order(target, 1.0)
                    if success:
                        break
                    await asyncio.sleep(1)

        # Position Management (Take Profit & Stop Loss)
        for pos in CACHED_PORTFOLIO:
            ticker = pos.get("ticker")
            cur = float(pos.get("currentPrice", 0))
            avg = float(pos.get("averagePrice", 0))
            qty = float(pos.get("quantity", 0))
            
            if cur > 0 and avg > 0:
                gross_ret = ((cur - avg) / avg) * 100.0
                net_ret = gross_ret - FX_ROUNDTRIP_FEE_PCT
                
                if net_ret >= 0.50:
                    log_activity(f"TAKE PROFIT: {ticker} (+{net_ret:.2f}% net). Vaulting gains.", "success")
                    execute_order(ticker, -qty)
                elif gross_ret <= -1.50:
                    log_activity(f"STOP LOSS: {ticker} ({gross_ret:.2f}%).", "warning")
                    execute_order(ticker, -qty)

        await asyncio.sleep(15)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(trading_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    sync_state()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", STARTING_CAPITAL)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", STARTING_CAPITAL)),
        "banked_profits": BANKED_PROFITS,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "trading_halted": TRADING_HALTED
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")