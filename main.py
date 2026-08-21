from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
import time
import random
from contextlib import asynccontextmanager
from db_manager import db
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: UK & US 500 Index Alpha Engine Active."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}

BASE_CAPITAL_TARGET = 50000.00
BANKED_PROFITS = 0.00

AI_BUY_COOLDOWN = {}
AI_SELL_COOLDOWN = {}

# 1. UK FTSE Top 500 / Index Pool
UK_TOP_POOL = [
    "VUKGl_EQ",  # Vanguard FTSE 100 Index Acc
    "ISFl_EQ",   # iShares FTSE 100 UCITS ETF
    "SHELl_EQ",  # Shell plc
    "AZNl_EQ",   # AstraZeneca
    "HSBA_EQ",   # HSBC Holdings
    "ULVRl_EQ",  # Unilever
    "BP.l_EQ",   # BP plc
    "GSKl_EQ",   # GSK
    "RIO_EQ",    # Rio Tinto
    "LLOYl_EQ",  # Lloyds Banking Group
    "BARCl_EQ",  # Barclays
    "RR.l_EQ"    # Rolls-Royce Holdings
]

# 2. US 500 Index & Mega-Cap Pool (Strictly S&P 500 Trackers & Market Giants)
US_TOP_POOL = [
    "VUSA_US_EQ",  # Vanguard S&P 500 ETF (LSE/US cross-listing or US equivalent)
    "VOO_US_EQ",   # Vanguard S&P 500 ETF
    "SPY_US_EQ",   # SPDR S&P 500 ETF Trust
    "IVV_US_EQ",   # iShares Core S&P 500 ETF
    "AAPL_US_EQ",  # Apple (Top S&P 500 Component)
    "MSFT_US_EQ",  # Microsoft (Top S&P 500 Component)
    "NVDA_US_EQ",  # NVIDIA (Top S&P 500 Component)
    "AMZN_US_EQ",  # Amazon (Top S&P 500 Component)
    "GOOGL_US_EQ"  # Alphabet (Top S&P 500 Component)
]

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
            err_msg = res.json().get("detail", res.text) if res.headers.get("content-type", "").startswith("application/json") else res.text
            log_activity(f"Order skipped {exact_ticker}: {err_msg}", "warning")
            return False
    except Exception as e:
        log_activity(f"Exception on {exact_ticker}: {str(e)}", "error")
        return False

def fetch_live_data():
    global CACHED_PORTFOLIO, CACHED_ACCOUNT, BANKED_PROFITS
    if not T212_API_KEY: return
    headers = get_t212_auth_headers()
    try:
        res_cash = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res_cash.status_code == 200: 
            CACHED_ACCOUNT = res_cash.json()
            total_eq = float(CACHED_ACCOUNT.get("total", 50000.00))
            if total_eq > BASE_CAPITAL_TARGET:
                excess = total_eq - BASE_CAPITAL_TARGET
                BANKED_PROFITS += excess
                log_activity(f"💰 PROFIT SWEEP: Banked £{excess:.2f} excess earnings!", "success")
    except Exception: pass
    
    try:
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200: CACHED_PORTFOLIO = res_port.json()
    except Exception: pass

async def autonomous_ai_brain():
    await asyncio.sleep(2)
    log_activity("Cross-Continental US 500 & UK Index Engine Online.", "success")
    
    while True:
        try:
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            free_cash = float(CACHED_ACCOUNT.get("free", 0))
            
            # --- PHASE 1: DISCIPLINED EXITS (1.5% Stop Loss & Daily Profit Target) ---
            for t212_ticker, pos in owned_tickers.items():
                if t212_ticker in AI_SELL_COOLDOWN and (time.time() - AI_SELL_COOLDOWN[t212_ticker] < 180):
                    continue 

                qty = float(pos.get("quantity", 0))
                avg = float(pos.get("averagePrice", 0))
                cur = float(pos.get("currentPrice", 0))
                
                if avg > 0:
                    ret_pct = ((cur - avg) / avg) * 100
                    
                    if ret_pct >= 0.8:
                        log_activity(f"🎯 DAILY PROFIT SECURED: Selling {t212_ticker} (+{ret_pct:.2f}%)", "success")
                        execute_live_order(t212_ticker, -qty)
                        AI_SELL_COOLDOWN[t212_ticker] = time.time()
                    elif ret_pct <= -1.5:
                        log_activity(f"🛡️ 1.5% STOP LOSS ACTIVATED: Protecting capital on {t212_ticker} ({ret_pct:.2f}%)", "warning")
                        execute_live_order(t212_ticker, -qty)
                        AI_SELL_COOLDOWN[t212_ticker] = time.time()
            
            # --- PHASE 2: ACTIVE DUAL-MARKET US 500 & UK SELECTION ---
            active_pool = []
            if is_market_open("UK"): active_pool.extend([(t, "UK") for t in UK_TOP_POOL])
            if is_market_open("US"): active_pool.extend([(t, "US") for t in US_TOP_POOL])
            
            if free_cash > 200.0 and active_pool:
                target_ticker, market_type = random.choice(active_pool)
                
                if target_ticker not in owned_tickers and (time.time() - AI_BUY_COOLDOWN.get(target_ticker, 0) < 120):
                    
                    if market_type == "UK":
                        clean_sym = target_ticker.replace("l_EQ", "").replace("_EQ", "")
                        if "SHEL" in clean_sym: yf_sym = "SHEL.L"
                        elif "RR" in clean_sym: yf_sym = "RR.L"
                        elif "BP" in clean_sym: yf_sym = "BP.L"
                        elif "VUKG" in clean_sym: yf_sym = "VUAG.L"
                        else: yf_sym = clean_sym + ".L"
                    else:
                        yf_sym = target_ticker.replace("_US_EQ", "").replace(".", "-")
                    
                    data = yf.download(yf_sym, period="5d", interval="15m", progress=False)
                    
                    if not data.empty and len(data) >= 10:
                        closes = [float(x) for x in data['Close'].values.flatten()]
                        volumes = [float(x) for x in data['Volume'].values.flatten()]
                        
                        current_price = closes[-1]
                        recent_avg = sum(closes[-3:]) / 3.0
                        baseline_avg = sum(closes[-10:]) / 10.0
                        
                        avg_vol = sum(volumes[-10:]) / 10.0
                        latest_vol = volumes[-1]
                        
                        momentum = ((recent_avg - baseline_avg) / baseline_avg) * 100.0
                        
                        if momentum > 0.08 and latest_vol >= (avg_vol * 0.8) and current_price > 0:
                            target_spend = min(1000.0, free_cash)
                            
                            if market_type == "UK":
                                qty = max(1.0, round((target_spend * 100.0) / current_price))
                            else:
                                qty = round(target_spend / current_price, 2)
                                if qty <= 0: continue
                            
                            log_activity(f"🧠 {market_type} US/UK 500 ENTRY: {yf_sym} (Score: +{momentum:.3f}%, Vol Confirmed)", "success")
                            execute_live_order(target_ticker, qty)
                            AI_BUY_COOLDOWN[target_ticker] = time.time()
                            await asyncio.sleep(2.0)
                        
        except Exception as e:
            log_activity(f"Brain Error: {str(e)}", "error")
            
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(autonomous_ai_brain())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    if is_market_open("US"): return execute_live_order("VOO_US_EQ", round(500.0 / 450.0, 2))
    elif is_market_open("UK"): return execute_live_order("VUKGl_EQ", 500.0)
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