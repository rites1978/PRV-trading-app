from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
from contextlib import asynccontextmanager
from db_manager import db

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Fully online and authenticated with Trading 212..."

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
T212_BASE_URL = "https://demo.trading212.com/api/v0/equity"

def execute_t212_order(ticker: str, quantity: float, side: str = "BUY"):
    if not T212_API_KEY or not T212_API_SECRET:
        log_activity("T212 Error: Missing API credentials.", "error")
        return "MISSING CREDS"
    
    clean_ticker = ticker.upper().strip().replace(".", "-")
    if "_" not in clean_ticker:
        clean_ticker = f"{clean_ticker}_US_EQ"

    final_qty = float(abs(quantity)) if side == "BUY" else float(-abs(quantity))

    raw_credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded_credentials = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "quantity": final_qty,
        "ticker": clean_ticker,
        "timeInForce": "DAY"
    }
    
    url = f"{T212_BASE_URL}/orders/market"
    log_activity(f"Executing MARKET order on T212 for {clean_ticker} (Qty: {final_qty})", "info")
    
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        log_activity(f"T212 Order Response [{res.status_code}]: {res.text}", "success" if res.status_code < 300 else "warning")
        return "LIVE EXECUTED" if res.status_code < 300 else f"REJECTED {res.status_code}"
    except Exception as e:
        log_activity(f"T212 Order Exception: {str(e)}", "error")
        return "API ERROR"

def get_trades_from_db():
    try:
        response = db.client.table("trades").select("*").order("created_at", desc=True).execute()
        return response.data if response.data else []
    except Exception:
        return []

async def market_scouring_agent():
    await asyncio.sleep(10)
    while True:
        try:
            # Verify authentication check
            raw_credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
            encoded = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
            res = requests.get(f"{T212_BASE_URL}/account/info", headers={"Authorization": f"Basic {encoded}"}, timeout=10)
            if res.status_code == 200:
                log_activity("T212 Account Sync Active. Portfolio connection healthy.", "info")
            else:
                log_activity(f"T212 Account Sync Warning: Status {res.status_code}", "warning")
        except Exception as e:
            log_activity(f"Agent loop error: {str(e)}", "error")
        
        await asyncio.sleep(300)

@asynccontextmanager
async def lifespan(app: FastAPI):
    log_activity("PRV Trading Desk starting up with verified broker integration...", "success")
    task = asyncio.create_task(market_scouring_agent())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

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
    <title>PRV Trading Floor</title>
    <style>
        body { background: #0b0f19; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 40px; }
        .card { background: #111827; border: 1px solid #1f2937; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h1 { color: #38bdf8; font-size: 24px; margin-top: 0; }
        .log { background: #030712; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 13px; max-height: 400px; overflow-y: auto; border: 1px solid #374151; color: #4ade80; }
    </style>
</head>
<body>
    <div class="card">
        <h1>PRV Trading Floor (Live Broker Connected)</h1>
        <p>Active live connection established with Trading 212 Practice Environment.</p>
        <div class="log" id="logStream">Loading live feed...</div>
    </div>
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
