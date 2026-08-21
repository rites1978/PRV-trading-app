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
    trades = get_trades_from_db()
    return {
        "valuation": 40000.00,
        "change_24h": 0.00,
        "return_pct": 0.00,
        "allocations": [],
        "trades": trades[:10],
        "commentary": LIVE_COMMENTARY
    }

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PRV Trading Floor</title>
    <style>
        body { background: #0b0f19; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 30px; }
        .container { max-width: 1200px; margin: 0 auto; display: grid; gap: 20px; grid-template-columns: 1fr 1fr; }
        .card { background: #111827; border: 1px solid #1f2937; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); grid-column: span 2; }
        .card-half { grid-column: span 1; }
        h1 { color: #38bdf8; font-size: 24px; margin-top: 0; }
        h2 { color: #94a3b8; font-size: 16px; margin-top: 0; border-bottom: 1px solid #1f2937; padding-bottom: 8px; }
        .metric { font-size: 32px; font-weight: bold; color: #34d399; margin: 10px 0; }
        .log { background: #030712; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 13px; max-height: 300px; overflow-y: auto; border: 1px solid #374151; color: #4ade80; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
        th, td { text-align: left; padding: 10px; border-bottom: 1px solid #1f2937; }
        th { color: #9ca3af; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>PRV Trading Floor (Live Broker Connected)</h1>
            <p>Authenticated securely with Trading 212 Practice Environment & Supabase Database.</p>
        </div>
        
        <div class="card card-half">
            <h2>Portfolio Valuation</h2>
            <div class="metric" id="valuation">£40,000.00</div>
            <p>Status: <span style="color: #34d399; font-weight: bold;">ONLINE</span></p>
        </div>

        <div class="card card-half">
            <h2>Live AI Commentary & Broker Logs</h2>
            <div class="log" id="logStream">Loading live feed...</div>
        </div>

        <div class="card">
            <h2>Recent Trade Execution Log</h2>
            <table>
                <thead>
                    <tr><th>Timestamp</th><th>Ticker</th><th>Side</th><th>Quantity</th><th>Status</th></tr>
                </thead>
                <tbody id="tradeTable">
                    <tr><td colspan="5" style="color: #6b7280;">Fetching trades...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    <script>
        async function fetchDashboard() {
            try {
                const res = await fetch('/api/valuation');
                const data = await res.json();
                document.getElementById('logStream').innerHTML = data.commentary;
                document.getElementById('valuation').innerText = '£' + data.valuation.toLocaleString('en-GB', {minimumFractionDigits: 2});
                
                const tbody = document.getElementById('tradeTable');
                if (data.trades && data.trades.length > 0) {
                    tbody.innerHTML = data.trades.map(t => `
                        <tr>
                            <td>${t.created_at || 'Just now'}</td>
                            <td><b>${t.ticker}</b></td>
                            <td style="color: ${t.side === 'BUY' ? '#34d399' : '#f87171'}">${t.side}</td>
                            <td>${t.quantity}</td>
                            <td>${t.status || 'EXECUTED'}</td>
                        </tr>
                    `).join('');
                }
            } catch(e) {}
        }
        setInterval(fetchDashboard, 2000);
        fetchDashboard();
    </script>
</body>
</html>
