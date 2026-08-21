from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import yfinance as yf
from db_manager import db
import asyncio
from datetime import datetime
import os
import requests
import base64
from contextlib import asynccontextmanager

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Authenticating with T212 API..."

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 60: SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{timestamp}] {message}"
    print(f"[{level.upper()}] {timestamp} - {message}")

T212_API_KEY = os.getenv("T212_API_KEY", "").strip()
T212_API_SECRET = os.getenv("T212_API_SECRET", "").strip()
T212_BASE_URL = os.getenv("T212_BASE_URL", "https://demo.trading212.com/api/v0/equity")

def execute_t212_order(ticker: str, quantity: float, side: str = "BUY"):
    if not T212_API_KEY or not T212_API_SECRET:
        log_activity("T212 Error: Missing API Key or Secret.", "error")
        return "MISSING CREDS"
    
    clean_ticker = ticker.upper().strip().replace(".", "-")
    if "_" not in clean_ticker:
        clean_ticker = f"{clean_ticker}_US_EQ"

    final_qty = float(abs(quantity)) if side == "BUY" else float(-abs(quantity))

    creds = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(creds.encode('utf-8')).decode('utf-8').strip()
    
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "quantity": final_qty,
        "ticker": clean_ticker,
        "timeValidity": "DAY"
    }
    
    url = f"{T212_BASE_URL}/orders/market"
    log_activity(f"Sending MARKET order to T212 for {clean_ticker} (Qty: {final_qty})", "info")
    
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        log_activity(f"T212 Response [{res.status_code}]: {res.text}", "success" if res.status_code < 300 else "warning")
        return res.status_code
    except Exception as e:
        log_activity(f"Exception: {str(e)}", "error")
        return 0

async def market_scouring_agent():
    await asyncio.sleep(5)
    while True:
        log_activity("Testing live order placement against T212 Practice API...", "info")
        execute_t212_order("AAPL", 1.0, "BUY")
        await asyncio.sleep(300)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(market_scouring_agent())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.api_route("/api/valuation", methods=["GET"])
def get_live_valuation():
    return {"commentary": LIVE_COMMENTARY}

@app.get("/", response_class=HTMLResponse)
def read_root():
    return f"<html><body style='background:#111;color:#fff;font-family:sans-serif;padding:40px;'><h1>T212 Diagnostic Console</h1><pre>{LIVE_COMMENTARY}</pre></body></html>"
