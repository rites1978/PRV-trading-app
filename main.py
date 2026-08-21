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
LIVE_COMMENTARY = "AI Trading Floor: Testing minimalist payload..."

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 60: SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{timestamp}] {message}"
    print(f"[{level.upper()}] {timestamp} - {message}")

T212_API_KEY = os.getenv("T212_API_KEY", "")
T212_API_SECRET = os.getenv("T212_API_SECRET", "")
T212_BASE_URL = os.getenv("T212_BASE_URL", "https://demo.trading212.com/api/v0/equity")

def execute_t212_order(ticker: str, quantity: int, side: str = "BUY"):
    clean_ticker = ticker.upper().strip().replace(".", "-")
    
    # Authenticate
    credentials_string = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded_creds = base64.b64encode(credentials_string.encode('utf-8')).decode('utf-8')
    headers = {"Authorization": f"Basic {encoded_creds}", "Content-Type": "application/json"}
    
    # Strict Minimalist Payload
    payload = {
        "ticker": clean_ticker,
        "quantity": int(quantity),
        "timeValidity": "DAY"
    }
    
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=headers, timeout=10)
        log_activity(f"T212 Response [{res.status_code}]: {res.text}", "success" if res.status_code < 300 else "error")
        return res.status_code
    except Exception as e:
        log_activity(f"Exception: {str(e)}", "error")
        return 0

async def market_scouring_agent():
    await asyncio.sleep(10)
    while True:
        log_activity("Executing test order for AAPL...", "info")
        execute_t212_order("AAPL", 1) 
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
    return f"<html><body><h1>Log:</h1><pre>{LIVE_COMMENTARY}</pre></body></html>"
