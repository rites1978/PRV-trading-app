from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime, timezone
import os
import requests
import base64
from contextlib import asynccontextmanager
from db_manager import db
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Planned Execution Architecture Active (Zero Churn)."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}

# The Core Index Anchors
UK_ANCHOR = "VUKGl_EQ"  # Vanguard FTSE 100
US_ANCHOR = "VUSA_US_EQ" # Vanguard S&P 500

# Track if daily executions have run to prevent duplicates
DAILY_RUN_STATE = {
    "date": None,
    "uk_executed": False,
    "us_executed": False
}

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 50: SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{timestamp}] {message}"
    print(f"[{level.upper()}] {timestamp} - {message}")

T212_API_KEY = os.getenv("T212_API_KEY", "").strip()
T212_API_SECRET = os.getenv("T212_API_SECRET", "").strip()
T212_BASE_URL = "https://demo.trading212.com/api/v0/equity"

def get_t212_auth_headers():
    raw_credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

def execute_live_order(exact_ticker: str, quantity: float):
    payload = {"ticker": exact_ticker, "quantity": quantity}
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_t212_auth_headers(), timeout=10)
        if res.status_code in [200, 201]:
            log_activity(f"✅ PLANNED EXECUTION: Bought {exact_ticker} (Qty: {quantity})", "success")
            return True
        else:
            err = res.json().get("detail", res.text) if res.headers.get("content-type", "").startswith("application/json") else res.text
            log_activity(f"Order failed for {exact_ticker}: {err}", "warning")
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
    except Exception: pass
    
    try:
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200: CACHED_PORTFOLIO = res_port.json()
    except Exception: pass

def get_estimated_price(ticker: str) -> float:
    """Gets the current price from the portfolio if we own it, otherwise uses a safe default to initiate the first position."""
    for pos in CACHED_PORTFOLIO:
        if pos.get("ticker") == ticker:
            return float(pos.get("currentPrice", 1.0))
    # Safe historical fallback to calculate initial fractional quantity if not currently owned
    return 35.0 if "VUKG" in ticker else 75.0 

async def planned_execution_brain():
    """Wakes up periodically, checks the time, and executes planned DCA index buys without spamming APIs."""
    await asyncio.sleep(2)
    log_activity("Planned Execution Engine Online. Awaiting scheduled market windows.", "success")
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            today_str = now.strftime("%Y-%m-%d")
            
            # Reset execution state at the start of a new day
            if DAILY_RUN_STATE["date"] != today_str:
                DAILY_RUN_STATE["date"] = today_str
                DAILY_RUN_STATE["uk_executed"] = False
                DAILY_RUN_STATE["us_executed"] = False
            
            # Skip weekends (Saturday=5, Sunday=6)
            if now.weekday() < 5:
                fetch_live_data()
                free_cash = float(CACHED_ACCOUNT.get("free", 0))
                time_decimal = now.hour + (now.minute / 60.0)

                # 1. UK Market Execution Window (Activates at 08:30 UTC / 09:30 BST)
                if 8.5 <= time_decimal < 15.0 and not DAILY_RUN_STATE["uk_executed"]:
                    if free_cash > 100.0:
                        target_spend = min(free_cash * 0.10, 500.0)  # Deploy 10% of cash or max £500
                        est_price = get_estimated_price(UK_ANCHOR)
                        qty = round(target_spend / est_price, 2)
                        
                        if qty > 0 and execute_live_order(UK_ANCHOR, qty):
                            DAILY_RUN_STATE["uk_executed"] = True
                            log_activity("UK Daily DCA Complete. Returning to sleep.", "info")

                # 2. US Market Execution Window (Activates at 14:30 UTC / 15:30 BST / 10:30 EST)
                if 14.5 <= time_decimal < 20.0 and not DAILY_RUN_STATE["us_executed"]:
                    if free_cash > 100.0:
                        target_spend = min(free_cash * 0.10, 500.0)  # Deploy 10% of cash or max £500
                        est_price = get_estimated_price(US_ANCHOR)
                        qty = round(target_spend / est_price, 2)
                        
                        if qty > 0 and execute_live_order(US_ANCHOR, qty):
                            DAILY_RUN_STATE["us_executed"] = True
                            log_activity("US Daily DCA Complete. Returning to sleep.", "info")

        except Exception as e:
            log_activity(f"System Error: {str(e)}", "error")
            
        # Sleep for a full 60 seconds (no high-frequency polling)
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(planned_execution_brain())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    """Manual override for testing outside of the scheduled cron windows."""
    fetch_live_data()
    free_cash = float(CACHED_ACCOUNT.get("free", 0))
    if free_cash > 100:
        est_price = get_estimated_price(US_ANCHOR)
        qty = round(150.0 / est_price, 2)
        success = execute_live_order(US_ANCHOR, qty)
        return {"status": "SUCCESS" if success else "FAILED"}
    return {"status": "INSUFFICIENT_FUNDS"}

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", 50000.00)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", 50000.00)),
        "banked_profits": 0.00,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {
            "UK": DAILY_RUN_STATE["uk_executed"], 
            "US": DAILY_RUN_STATE["us_executed"]
        }
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")