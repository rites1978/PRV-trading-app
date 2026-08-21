from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from db_manager import db
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Parallel Alpha Engine Active."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
BASE_CAPITAL_TARGET = 50000.00
BANKED_PROFITS = 0.00

AI_COOLDOWN = {}
EXECUTOR = ThreadPoolExecutor(max_workers=8)

# Core High-Liquidity US 500 & UK Large-Cap Watchlist
UNIVERSE = [
    # US S&P 500 Trackers & Market Titans
    {"t212": "VOO_US_EQ", "yf": "VOO", "market": "US"},
    {"t212": "SPY_US_EQ", "yf": "SPY", "market": "US"},
    {"t212": "AAPL_US_EQ", "yf": "AAPL", "market": "US"},
    {"t212": "MSFT_US_EQ", "yf": "MSFT", "market": "US"},
    {"t212": "NVDA_US_EQ", "yf": "NVDA", "market": "US"},
    {"t212": "AMZN_US_EQ", "yf": "AMZN", "market": "US"},
    {"t212": "GOOGL_US_EQ", "yf": "GOOGL", "market": "US"},
    {"t212": "META_US_EQ", "yf": "META", "market": "US"},
    {"t212": "TSLA_US_EQ", "yf": "TSLA", "market": "US"},
    # UK FTSE 100 Trackers & Blue Chips
    {"t212": "VUKGl_EQ", "yf": "VUAG.L", "market": "UK"},
    {"t212": "ISFl_EQ", "yf": "ISF.L", "market": "UK"},
    {"t212": "SHELl_EQ", "yf": "SHEL.L", "market": "UK"},
    {"t212": "AZNl_EQ", "yf": "AZN.L", "market": "UK"},
    {"t212": "HSBA_EQ", "yf": "HSBA.L", "market": "UK"},
    {"t212": "RR.l_EQ", "yf": "RR.L", "market": "UK"}
]

def is_market_open(market: str) -> bool:
    now = datetime.utcnow()
    if now.weekday() >= 5: return False 
    time_dec = now.hour + (now.minute / 60.0)
    if market == "UK": return 7.0 <= time_dec < 15.5
    if market == "US": return 13.5 <= time_dec < 20.0
    return False

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S")
    SYSTEM_LOGS.insert(0, {"time": timestamp, "msg": message, "level": level})
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
            log_activity(f"✅ {side} {exact_ticker} (Qty: {abs(quantity)})", "success")
            try:
                db.client.table("trades").insert({
                    "ticker": exact_ticker, "side": side, "quantity": abs(quantity), "status": status
                }).execute()
            except Exception: pass
            return True
        else:
            err = res.json().get("detail", res.text) if res.headers.get("content-type", "").startswith("application/json") else res.text
            log_activity(f"Order skipped for {exact_ticker}: {err}", "warning")
            return False
    except Exception as e:
        log_activity(f"Order execution error on {exact_ticker}: {str(e)}", "error")
        return False

def fetch_live_data():
    global CACHED_PORTFOLIO, CACHED_ACCOUNT, BANKED_PROFITS
    if not T212_API_KEY: return
    headers = get_t212_auth_headers()
    try:
        res = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res.status_code == 200: 
            CACHED_ACCOUNT = res.json()
            total_eq = float(CACHED_ACCOUNT.get("total", 50000.00))
            if total_eq > BASE_CAPITAL_TARGET:
                excess = total_eq - BASE_CAPITAL_TARGET
                BANKED_PROFITS += excess
                log_activity(f"💰 PROFIT SWEEP: Banked £{excess:.2f}", "success")
    except Exception: pass
    
    try:
        res = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res.status_code == 200: CACHED_PORTFOLIO = res.json()
    except Exception: pass

def evaluate_ticker_sync(item):
    """Evaluates short-term price trend and returns an actionable alpha score."""
    try:
        df = yf.download(item["yf"], period="1d", interval="5m", progress=False)
        if df.empty or len(df) < 3: return None
        closes = [float(x) for x in df['Close'].values.flatten()]
        momentum = ((closes[-1] - closes[-3]) / closes[-3]) * 100.0
        return {
            "t212": item["t212"],
            "yf": item["yf"],
            "market": item["market"],
            "price": closes[-1],
            "momentum": momentum
        }
    except Exception:
        return None

async def parallel_alpha_scan():
    """Scans all eligible open market instruments concurrently."""
    eligible = [item for item in UNIVERSE if is_market_open(item["market"])]
    if not eligible: return []
    
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(EXECUTOR, evaluate_ticker_sync, item) for item in eligible]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def autonomous_ai_brain():
    await asyncio.sleep(2)
    log_activity("Parallel Alpha Engine Online. Real-time batch scanning engaged.", "success")
    
    while True:
        try:
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            free_cash = float(CACHED_ACCOUNT.get("free", 0))
            
            # 1. RISK & PROFIT MANAGEMENT (1.5% Stop-Loss / +0.8% Profit Target)
            for t212_ticker, pos in owned_tickers.items():
                if t212_ticker in AI_COOLDOWN and (time.time() - AI_COOLDOWN[t212_ticker] < 120):
                    continue
                qty = float(pos.get("quantity", 0))
                avg = float(pos.get("averagePrice", 0))
                cur = float(pos.get("currentPrice", 0))
                if avg > 0:
                    ret_pct = ((cur - avg) / avg) * 100
                    if ret_pct >= 0.8:
                        log_activity(f"🎯 PROFIT TARGET REACHED: Selling {t212_ticker} (+{ret_pct:.2f}%)", "success")
                        execute_live_order(t212_ticker, -qty)
                        AI_COOLDOWN[t212_ticker] = time.time()
                    elif ret_pct <= -1.5:
                        log_activity(f"🛡️ 1.5% STOP-LOSS TRIGGERED: Closing {t212_ticker} ({ret_pct:.2f}%)", "warning")
                        execute_live_order(t212_ticker, -qty)
                        AI_COOLDOWN[t212_ticker] = time.time()

            # 2. PARALLEL BATCH ENTRY
            if free_cash > 500.0:
                candidates = await parallel_alpha_scan()
                # Sort all open market stocks by highest positive momentum
                ranked = sorted([c for c in candidates if c["t212"] not in owned_tickers], key=lambda x: x["momentum"], reverse=True)
                
                for top in ranked:
                    # Enter if momentum is positive and cooldown has expired
                    if top["momentum"] > 0.0 and (time.time() - AI_COOLDOWN.get(top["t212"], 0) > 60):
                        target_spend = min(1000.0, free_cash)
                        if top["market"] == "UK":
                            qty = max(1.0, round((target_spend * 100.0) / top["price"]))
                        else:
                            qty = round(target_spend / top["price"], 2)
                        
                        if qty > 0:
                            log_activity(f"🚀 ALPHA ENTRY: {top['t212']} (Score: +{top['momentum']:.3f}%)", "success")
                            execute_live_order(top["t212"], qty)
                            AI_COOLDOWN[top["t212"]] = time.time()
                            break # Open highest conviction trade first

        except Exception as e:
            log_activity(f"Engine Loop Warning: {str(e)}", "error")
            
        await asyncio.sleep(15)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(autonomous_ai_brain())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    if is_market_open("US"): return execute_live_order("SPY_US_EQ", round(500.0 / 500.0, 2))
    if is_market_open("UK"): return execute_live_order("VUKGl_EQ", 500.0)
    return {"status": "ERROR", "detail": "Markets are closed."}

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", 50000.00)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", 50000.00)),
        "banked_profits": BANKED_PROFITS,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {"UK": is_market_open("UK"), "US": is_market_open("US")}
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")