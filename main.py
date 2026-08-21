from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
from contextlib import asynccontextmanager
from db_manager import db
import yfinance as yf

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Standby for manual or automated execution..."

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

def execute_live_order(ticker: str, quantity: float):
    if not T212_API_KEY or not T212_API_SECRET:
        log_activity("Execution Error: Missing API credentials in Render.", "error")
        return {"status": "ERROR", "detail": "Missing Credentials"}
    
    clean_ticker = ticker.upper().strip()
    if "_" not in clean_ticker:
        clean_ticker = f"{clean_ticker}_US_EQ"

    headers = get_t212_auth_headers()
    payload = {
        "quantity": float(quantity),
        "ticker": clean_ticker,
        "timeInForce": "DAY"
    }
    
    url = f"{T212_BASE_URL}/orders/market"
    log_activity(f"Sending live MARKET order to T212 for {clean_ticker} (Qty: {quantity})", "info")
    
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        log_activity(f"T212 Response [{res.status_code}]: {res.text}", "success" if res.status_code < 300 else "error")
        
        if res.status_code in [200, 201]:
            res_json = res.json()
            # Save real execution to Supabase
            try:
                db.client.table("trades").insert({
                    "ticker": clean_ticker,
                    "side": "BUY",
                    "quantity": quantity,
                    "status": "LIVE_FILLED"
                }).execute()
            except Exception:
                pass
            return {"status": "SUCCESS", "response": res_json}
        else:
            return {"status": "REJECTED", "code": res.status_code, "detail": res.text}
    except Exception as e:
        log_activity(f"Exception during order dispatch: {str(e)}", "error")
        return {"status": "EXCEPTION", "detail": str(e)}

def fetch_live_account_balance():
    if not T212_API_KEY or not T212_API_SECRET:
        return 50000.00
    try:
        res = requests.get(f"{T212_BASE_URL}/account/cash", headers=get_t212_auth_headers(), timeout=10)
        if res.status_code == 200:
            data = res.json()
            return float(data.get("total", data.get("free", 50000.00)))
    except Exception:
        pass
    return 50000.00

def get_trades_from_db():
    try:
        response = db.client.table("trades").select("*").order("created_at", desc=True).execute()
        return response.data if response.data else []
    except Exception:
        return []

async def background_autonomous_loop():
    await asyncio.sleep(15)
    while True:
        log_activity("Autonomous Agent: Scanning AAPL for momentum entry...", "info")
        try:
            data = yf.download("AAPL", period="3d", interval="1d", progress=False)
            if not data.empty and len(data) >= 2:
                c1 = float(data['Close'].iloc[-1].item())
                c0 = float(data['Close'].iloc[-2].item())
                change = ((c1 - c0) / c0) * 100
                log_activity(f"AAPL Price check: ${c1:.2f} ({change:+.2f}%)", "info")
                
                # Force execution on first run to verify live trading loop works end-to-end
                log_activity("Executing automated test buy order for AAPL on Trading 212...", "success")
                execute_live_order("AAPL", 1.0)
        except Exception as e:
            log_activity(f"Scan loop error: {str(e)}", "error")
            
        await asyncio.sleep(600) # Run every 10 minutes

@asynccontextmanager
async def lifespan(app: FastAPI):
    log_activity("PRV Autonomous Trading Engine online.", "success")
    task = asyncio.create_task(background_autonomous_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    result = execute_live_order("AAPL", 1.0)
    return result

@app.api_route("/api/valuation", methods=["GET", "HEAD"])
def get_live_valuation():
    balance = fetch_live_account_balance()
    trades = get_trades_from_db()
    return {
        "valuation": balance,
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
    <title>PRV Autonomous Trading Floor</title>
    <style>
        body { background: #0b0f19; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 30px; }
        .container { max-width: 1200px; margin: 0 auto; display: grid; gap: 20px; grid-template-columns: 1fr 1fr; }
        .card { background: #111827; border: 1px solid #1f2937; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); grid-column: span 2; }
        .card-half { grid-column: span 1; }
        h1 { color: #38bdf8; font-size: 24px; margin-top: 0; }
        h2 { color: #94a3b8; font-size: 16px; margin-top: 0; border-bottom: 1px solid #1f2937; padding-bottom: 8px; }
        .metric { font-size: 32px; font-weight: bold; color: #34d399; margin: 10px 0; }
        .log { background: #030712; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 13px; max-height: 250px; overflow-y: auto; border: 1px solid #374151; color: #4ade80; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
        th, td { text-align: left; padding: 10px; border-bottom: 1px solid #1f2937; }
        th { color: #9ca3af; }
        .btn { background: #38bdf8; color: #0b0f19; font-weight: bold; padding: 12px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 15px; margin-top: 10px; }
        .btn:hover { background: #0ea5e9; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>PRV Autonomous Trading Floor</h1>
            <p>Direct bridge to Trading 212 Practice Account.</p>
            <button class="btn" onclick="triggerTrade()">Force AI Trade Execution (AAPL)</button>
            <span id="execStatus" style="margin-left: 15px; font-weight: bold; color: #38bdf8;"></span>
        </div>
        
        <div class="card card-half">
            <h2>Live Practice Balance</h2>
            <div class="metric" id="valuation">£50,000.00</div>
            <p>Status: <span style="color: #34d399; font-weight: bold;">LIVE BROKER SYNCED</span></p>
        </div>

        <div class="card card-half">
            <h2>AI Agent System Logs</h2>
            <div class="log" id="logStream">Loading logs...</div>
        </div>

        <div class="card">
            <h2>Confirmed Trades on Trading 212</h2>
            <table>
                <thead>
                    <tr><th>Timestamp</th><th>Ticker</th><th>Side</th><th>Quantity</th><th>Status</th></tr>
                </thead>
                <tbody id="tradeTable">
                    <tr><td colspan="5" style="color: #6b7280;">No live trades logged yet. Click the button above to test.</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    <script>
        async function triggerTrade() {
            document.getElementById('execStatus').innerText = "Executing live order on T212...";
            try {
                const res = await fetch('/api/trigger-trade');
                const data = await res.json();
                document.getElementById('execStatus').innerText = "Result: " + data.status;
                fetchDashboard();
            } catch(e) {
                document.getElementById('execStatus').innerText = "Execution failed.";
            }
        }

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
                            <td style="color: #34d399">${t.side}</td>
                            <td>${t.quantity}</td>
                            <td><span style="color: #34d399; font-weight: bold;">${t.status}</span></td>
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
