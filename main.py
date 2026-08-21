from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
import time
from contextlib import asynccontextmanager
from db_manager import db
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Multi-Market Engine Online. Tracking Global Hours."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
AI_COOLDOWN_MEMORY = {} 
VALID_T212_TICKERS = set()

MARKET_UNIVERSE = {
    "BARC.L": {"t212": "BARC_l_EQ", "market": "UK", "qty": 25.0},
    "LLOY.L": {"t212": "LLOY_l_EQ", "market": "UK", "qty": 50.0},
    "BP.L": {"t212": "BP_l_EQ", "market": "UK", "qty": 10.0},
    "VOD.L": {"t212": "VOD_l_EQ", "market": "UK", "qty": 50.0},
    "TSCO.L": {"t212": "TSCO_l_EQ", "market": "UK", "qty": 15.0},
    "SHEL.L": {"t212": "SHEL_l_EQ", "market": "UK", "qty": 5.0},
    "AAPL": {"t212": "AAPL_US_EQ", "market": "US", "qty": 1.0},
    "NVDA": {"t212": "NVDA_US_EQ", "market": "US", "qty": 1.0},
    "TSLA": {"t212": "TSLA_US_EQ", "market": "US", "qty": 1.0},
    "MSFT": {"t212": "MSFT_US_EQ", "market": "US", "qty": 1.0},
    "AMZN": {"t212": "AMZN_US_EQ", "market": "US", "qty": 1.0},
    "META": {"t212": "META_US_EQ", "market": "US", "qty": 1.0}
}

def is_market_open(market_code: str) -> bool:
    now = datetime.utcnow()
    if now.weekday() >= 5: return False 
    time_decimal = now.hour + (now.minute / 60.0)
    if market_code == "UK": return 7.0 <= time_decimal < 15.5
    elif market_code == "US": return 13.5 <= time_decimal < 20.0
    return False

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 60: SYSTEM_LOGS.pop()
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
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_t212_auth_headers(), timeout=15)
        if res.status_code in [200, 201]:
            status = res.json().get("status", "FILLED")
            log_activity(f"✅ {side} Executed! {exact_ticker} is {status}.", "success")
            try:
                db.client.table("trades").insert({
                    "ticker": exact_ticker, "side": side, "quantity": abs(quantity), "status": status
                }).execute()
            except Exception: pass
            return {"status": "SUCCESS", "detail": status}
        else:
            log_activity(f"Order Rejected [{res.status_code}]: {res.text}", "error")
            return {"status": "REJECTED"}
    except Exception as e:
        log_activity(f"Order Exception: {str(e)}", "error")
        return {"status": "EXCEPTION"}

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

async def autonomous_ai_brain():
    await asyncio.sleep(2)
    try:
        res = requests.get(f"{T212_BASE_URL}/metadata/instruments", headers=get_t212_auth_headers(), timeout=15)
        if res.status_code == 200:
            for inst in res.json():
                if inst.get("ticker"): VALID_T212_TICKERS.add(inst["ticker"])
            log_activity(f"Synced {len(VALID_T212_TICKERS)} official instrument codes.", "success")
    except Exception: pass

    await asyncio.sleep(3)
    log_activity("HFT Global Brain Online: Scanning actively open markets...", "success")
    
    while True:
        try:
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            action_taken = False
            
            for t212_ticker, pos in owned_tickers.items():
                qty = float(pos.get("quantity", 0))
                avg = float(pos.get("averagePrice", 0))
                cur = float(pos.get("currentPrice", 0))
                if avg > 0:
                    ret_pct = ((cur - avg) / avg) * 100
                    if ret_pct >= 0.05 or ret_pct <= -0.05:
                        log_activity(f"⚡ HFT TRIGGER: Auto-Selling {t212_ticker} (P/L: {ret_pct:+.2f}%)", "warning" if ret_pct < 0 else "success")
                        execute_live_order(t212_ticker, -qty)
                        action_taken = True
                        break 
            
            if action_taken:
                await asyncio.sleep(5)
                continue 
                
            for yf_ticker, info in MARKET_UNIVERSE.items():
                market_code = info["market"]
                t212_ticker = info["t212"]
                
                if not is_market_open(market_code) or t212_ticker not in VALID_T212_TICKERS: continue
                if t212_ticker in owned_tickers or (time.time() - AI_COOLDOWN_MEMORY.get(t212_ticker, 0) < 60): continue 
                
                data = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
                if not data.empty and len(data) >= 3:
                    closes = [float(x) for x in data['Close'].values.flatten()]
                    recent_avg = sum(closes[-2:]) / 2.0
                    older_avg = sum(closes[-4:-2]) / 2.0 if len(closes) >= 4 else closes[0]
                    momentum = ((recent_avg - older_avg) / older_avg) * 100.0
                    
                    if momentum > 0.005: 
                        log_activity(f"🚀 RAPID MOMENTUM on {yf_ticker} ({momentum:+.3f}%). Executing BUY...", "success")
                        execute_live_order(t212_ticker, info["qty"])
                        AI_COOLDOWN_MEMORY[t212_ticker] = time.time()
                        action_taken = True
                        break 
                
                await asyncio.sleep(1) 
        except Exception as e:
            log_activity(f"AI Brain error: {str(e)}", "error")
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(autonomous_ai_brain())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    if is_market_open("UK"): return execute_live_order("BARC_l_EQ", 10.0)
    elif is_market_open("US"): return execute_live_order("AAPL_US_EQ", 1.0)
    return {"status": "ERROR", "detail": "Both UK and US markets are closed."}

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", 50000.00)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", 50000.00)),
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {"UK": is_market_open("UK"), "US": is_market_open("US")}
    }

@app.get("/", response_class=HTMLResponse)
def read_root():
    return FileResponse("index.html")