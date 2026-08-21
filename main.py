from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
from contextlib import asynccontextmanager
from db_manager import db
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Pure Index Anchor Mode (Zero Churn)."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
BANKED_PROFITS = 0.00

# Target Core Index ETF on Trading 212 (Vanguard S&P 500 Acc)
ANCHOR_ETF_TICKER = "VUAGl_EQ" 

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S")
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

def execute_live_order(exact_ticker: str, quantity: float):
    payload = {"ticker": exact_ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_t212_auth_headers(), timeout=10)
        if res.status_code in [200, 201]:
            status = res.json().get("status", "FILLED")
            log_activity(f"✅ ANCHOR {side} {exact_ticker} (Qty: {abs(quantity)})", "success")
            try:
                db.client.table("trades").insert({
                    "ticker": exact_ticker, "side": side, "quantity": abs(quantity), "status": status
                }).execute()
            except Exception: pass
            return True
        else:
            err_msg = res.json().get("detail", res.text) if res.headers.get("content-type", "").startswith("application/json") else res.text
            log_activity(f"Anchor Order Skipped: {err_msg}", "warning")
            return False
    except Exception as e:
        log_activity(f"Exception on anchor order: {str(e)}", "error")
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

async def index_anchor_brain():
    """Waits for account sync, then deploys idle cash into the core S&P 500 ETF once and holds indefinitely."""
    await asyncio.sleep(5)
    log_activity("Initializing Pure Index Anchor Strategy...", "info")
    
    initial_deployment_done = False
    
    while True:
        try:
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            free_cash = float(CACHED_ACCOUNT.get("free", 0))
            
            # If we have significant cash sitting idle and haven't bought our core anchor yet
            if free_cash > 200.0 and ANCHOR_ETF_TICKER not in owned_tickers and not initial_deployment_done:
                # Find current price of anchor ETF from portfolio or fetch instruments
                current_price = 100.0
                for pos in CACHED_PORTFOLIO:
                    if pos.get("ticker") == ANCHOR_ETF_TICKER:
                        current_price = float(pos.get("currentPrice", 100.0))
                
                # Deploy 95% of available free cash into the S&P 500 index fund one time
                target_spend = free_cash * 0.95
                qty = max(1.0, round((target_spend * 100.0) / current_price))
                
                log_activity(f"⚓ ANCHOR DEPLOYMENT: Purchasing S&P 500 ETF ({ANCHOR_ETF_TICKER}) to secure long-term index growth.", "success")
                success = execute_live_order(ANCHOR_ETF_TICKER, qty)
                if success:
                    initial_deployment_done = True
            
            # Once anchored, the AI goes completely dormant to prevent any further trading friction or spread loss.
            if initial_deployment_done:
                log_activity("💤 Index Anchor locked. Zero churn mode active. Portfolio safely tracking market baseline.", "info")
                
        except Exception as e:
            log_activity(f"Anchor Loop Error: {str(e)}", "error")
            
        # Sleep for a long interval (1 hour) since no active trading is needed
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(index_anchor_brain())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    return {"status": "LOCKED", "detail": "Active trading disabled. Pure Index Anchor mode is engaged to protect capital."}

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", 50000.00)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", 50000.00)),
        "banked_profits": BANKED_PROFITS,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {"UK": True, "US": True}
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")