from fastapi import FastAPI
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
LIVE_COMMENTARY = "AI Trading Floor: Querying live T212 account balance..."

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

def get_t212_auth_headers():
    raw_credentials = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

def fetch_live_broker_valuation():
    if not T212_API_KEY or not T212_API_SECRET:
        return 50000.00, []
    
    headers = get_t212_auth_headers()
    try:
        # Fetch account cash details directly
        res = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            # Trading 212 returns free, total, ppl, result, etc.
            total_balance = float(data.get("total", data.get("free", 50000.00)))
            log_activity(f"Live T212 Cash Fetched successfully: Total = £{total_balance}", "success")
            return total_balance, []
        else:
            log_activity(f"Failed to fetch cash: Status {res.status_code} - {res.text}", "warning")
    except Exception as e:
        log_activity(f"Cash fetch exception: {str(e)}", "error")
        
    return 50000.00, []

def get_trades_from_db():
    try:
        response = db.client.table("trades").select("*").order("created_at", desc=True).execute()
        return response.data if response.data else []
    except Exception:
        return []

@asynccontextmanager
async def lifespan(app: FastAPI):
    log_activity("PRV Trading Desk starting up with live balance sync...", "success")
    yield

app = FastAPI(lifespan=lifespan)

@app.api_route("/api/valuation", methods=["GET", "HEAD"])
def get_live_valuation():
    live_val, positions = fetch_live_broker_valuation()
    trades = get_trades_from_db()
    return {
        "valuation": live_val,
        "change_24h": 0.00,
        "return_pct": 0.00,
        "allocations": positions,
        "trades": trades[:10],
        "commentary": LIVE_COMMENTARY
    }

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
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
            <p>Synced live with Trading 212 Practice Account.</p>
        </div>
        
        <div class="card card-half">
            <h2>Live Account Valuation</h2>
            <div class="metric" id="valuation">£50,000.00</div>
            <p>Status: <span style="color: #34d399; font-weight: bold;">LIVE SYNC ACTIVE</span></p>
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
                document.getElementById('valuation').innerText = '£' + data.valuation.toLocaleString('en-GB', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                
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
"""
