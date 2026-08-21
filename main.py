from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import yfinance as yf
from db_manager import db
import asyncio
from datetime import datetime
import os
import requests
import base64

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Verbose diagnostic mode active..."

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 60:
        SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{timestamp}] {message}"

T212_API_KEY = os.getenv("T212_API_KEY", "")
T212_API_SECRET = os.getenv("T212_API_SECRET", "")
T212_BASE_URL = os.getenv("T212_BASE_URL", "https://demo.trading212.com/api/v0/equity")

def execute_t212_order(ticker: str, quantity: float, side: str = "BUY"):
    if not T212_API_KEY or not T212_API_SECRET:
        log_activity("T212 Error: API Key or Secret environment variable is missing.", "error")
        return "MISSING CREDS"
    
    clean_ticker = ticker.upper().strip().replace(".", "-")
    if "_" not in clean_ticker:
        clean_ticker = f"{clean_ticker}_US_EQ"

    final_qty = abs(quantity) if side == "BUY" else -abs(quantity)

    credentials_string = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded_creds = base64.b64encode(credentials_string.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {encoded_creds}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "quantity": float(final_qty),
        "ticker": clean_ticker,
        "timeValidity": "DAY",
        "extendedHours": True
    }
    
    url = f"{T212_BASE_URL}/orders/market"
    log_activity(f"Sending POST to {url} for {clean_ticker} (Qty: {final_qty})", "info")
    
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        log_activity(f"T212 Raw Response [{res.status_code}]: {res.text}", "warning" if res.status_code != 200 else "success")
        if res.status_code in [200, 201]:
            return "LIVE EXECUTED"
        else:
            return f"REJECTED {res.status_code}"
    except Exception as e:
        log_activity(f"T212 Exception: native error -> {str(e)}", "error")
        return "API ERROR"

def get_broad_market_universe():
    return ["AAPL", "NVDA", "TSLA", "MSFT"]

async def market_scouring_agent():
    await asyncio.sleep(5) # Wait for startup
    while True:
        log_activity("Diagnostic Scan: Testing live order placement against T212...", "info")
        # Test with a single liquid ticker to inspect the exact gateway response
        execution_status = execute_t212_order("AAPL", 1.0, "BUY")
        log_activity(f"Diagnostic Test Result: {execution_status}", "info")
        await asyncio.sleep(300)

@app.on_event("startup")
async def startup_event():
    log_activity("Diagnostic Trading Desk online.", "success")
    asyncio.create_task(market_scouring_agent())

def get_trades_from_db():
    try:
        response = db.client.table("trades").select("*").order("created_at", desc=True).execute()
        return response.data if response.data else []
    except Exception:
        return []

@app.api_route("/api/valuation", methods=["GET", "HEAD"])
def get_live_valuation():
    return {
        "valuation": 40000.00,
        "change_24h": 0.00,
        "return_pct": 0.00,
        "allocations": [],
        "commentary": LIVE_COMMENTARY
    }

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Diagnostic Trading Desk</title>
    <style>
        body { background: #000; color: #fff; font-family: sans-serif; padding: 40px; }
        .log { background: #111; padding: 20px; border-radius: 8px; font-family: monospace; font-size: 13px; max-height: 500px; overflow-y: auto; border: 1px solid #333; }
        .success { color: #30d158; }
        .error { color: #ff453a; }
        .warning { color: #f59e0b; }
    </style>
</head>
<body>
    <h1>Diagnostic Log Stream</h1>
    <p>Watching real-time interaction with Trading 212 API...</p>
    <div class="log" id="logStream">Loading logs...</div>
    <script>
        async function fetchLogs() {
            try {
                const res = await fetch('/api/valuation');
                const data = await res.json();
                document.getElementById('logStream').innerHTML = data.commentary;
            } catch(e) {}
        }
        setInterval(fetchLogs, 2000);
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def read_root():
    return HTML_TEMPLATE
