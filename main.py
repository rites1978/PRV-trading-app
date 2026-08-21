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
LIVE_COMMENTARY = "AI Trading Floor: Precision & Error-Correction Engine Online."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}

BASE_CAPITAL_TARGET = 50000.00
BANKED_PROFITS = 0.00

AI_BUY_COOLDOWN = {}
AI_SELL_COOLDOWN = {}

ALL_UK_TICKERS = []
ALL_US_TICKERS = []

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
            # Clean up error text so logs remain readable
            err_msg = res.json().get("detail", res.text) if res.headers.get("content-type", "").startswith("application/json") else res.text
            log_activity(f"Skipped {exact_ticker}: {err_msg}", "warning")
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
    
    try:
        res = requests.get(f"{T212_BASE_URL}/metadata/instruments", headers=get_t212_auth_headers(), timeout=15)
        if res.status_code == 200:
            for inst in res.json():
                ticker = inst.get("ticker", "")
                if not ticker: continue
                if ticker.endswith("_US_EQ"): ALL_US_TICKERS.append(ticker)
                elif "l_EQ" in ticker or "L_EQ" in ticker or "GB_EQ" in ticker or "UK_EQ" in ticker: ALL_UK_TICKERS.append(ticker)
            log_activity(f"Engine Ready: {len(ALL_UK_TICKERS)} UK & {len(ALL_US_TICKERS)} US Global Targets Loaded.", "success")
    except Exception as e:
        log_activity(f"Instrument load error: {str(e)}", "error")

    await asyncio.sleep(2)
    
    while True:
        try:
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            free_cash = float(CACHED_ACCOUNT.get("free", 0))
            
            # --- PHASE 1: UNRESTRICTED INTELLIGENT EXITS ---
            for t212_ticker, pos in owned_tickers.items():
                # FIX: Extended sell cooldown to 120s to prevent duplicate sell spam while orders are queued
                if t212_ticker in AI_SELL_COOLDOWN and (time.time() - AI_SELL_COOLDOWN[t212_ticker] < 120):
                    continue 

                qty = float(pos.get("quantity", 0))
                avg = float(pos.get("averagePrice", 0))
                cur = float(pos.get("currentPrice", 0))
                
                if avg > 0:
                    ret_pct = ((cur - avg) / avg) * 100
                    
                    if ret_pct >= 0.3:
                        log_activity(f"🎯 SECURING GAIN: Selling {t212_ticker} (+{ret_pct:.2f}%)", "success")
                        execute_live_order(t212_ticker, -qty)
                        AI_SELL_COOLDOWN[t212_ticker] = time.time()
                    elif ret_pct <= -1.5:
                        log_activity(f"✂️ PRUNING POSITION: Cutting {t212_ticker} ({ret_pct:.2f}%)", "warning")
                        execute_live_order(t212_ticker, -qty)
                        AI_SELL_COOLDOWN[t212_ticker] = time.time()
            
            # --- PHASE 2: DYNAMIC CAPITAL DEPLOYMENT ---
            if free_cash > 50.0: # Only buy if we have meaningful cash
                available_pool = []
                if is_market_open("UK"): available_pool.extend(ALL_UK_TICKERS)
                if is_market_open("US"): available_pool.extend(ALL_US_TICKERS)
                
                if available_pool:
                    batch = random.sample(available_pool, min(200, len(available_pool)))
                    
                    for t212_ticker in batch:
                        free_cash = float(CACHED_ACCOUNT.get("free", 0))
                        if free_cash < 50.0: break
                        
                        if t212_ticker in owned_tickers or (time.time() - AI_BUY_COOLDOWN.get(t212_ticker, 0) < 60):
                            continue
                            
                        if "l_EQ" in t212_ticker: yf_ticker = t212_ticker.replace("l_EQ", ".L")
                        elif "L_EQ" in t212_ticker: yf_ticker = t212_ticker.replace("L_EQ", ".L")
                        elif t212_ticker.endswith("_US_EQ"): yf_ticker = t212_ticker.replace("_US_EQ", "")
                        else: continue
                        
                        data = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
                        
                        if not data.empty and len(data) >= 3:
                            closes = [float(x) for x in data['Close'].values.flatten()]
                            current_price = closes[-1]
                            recent_avg = sum(closes[-2:]) / 2.0
                            older_avg = sum(closes[-4:-2]) / 2.0 if len(closes) >= 4 else closes[0]
                            momentum = ((recent_avg - older_avg) / older_avg) * 100.0
                            
                            if momentum > 0.001 and current_price > 0: 
                                # Dynamic position size: use £500 or whatever cash is left if under £500
                                target_spend = min(500.0, free_cash)
                                
                                if "l_EQ" in t212_ticker or "L_EQ" in t212_ticker:
                                    qty = max(1.0, round((target_spend * 100.0) / current_price))
                                else:
                                    # FIX: Strictly round US fractional shares to 2 decimal places to prevent precision errors
                                    qty = round(target_spend / current_price, 2)
                                    if qty <= 0: continue
                                
                                log_activity(f"🚀 AI STRIKE: {yf_ticker} momentum ({momentum:+.3f}%)", "success")
                                execute_live_order(t212_ticker, qty)
                                AI_BUY_COOLDOWN[t212_ticker] = time.time()
                                await asyncio.sleep(0.2)
                        
                        await asyncio.sleep(0.05)
                        
        except Exception as e:
            log_activity(f"Brain Error: {str(e)}", "error")
            
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(autonomous_ai_brain())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    if is_market_open("US"): return execute_live_order("AAPL_US_EQ", round(500.0 / 180.0, 2))
    elif is_market_open("UK"): return execute_live_order("BARCl_EQ", 50000.0 / 220.0)
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
