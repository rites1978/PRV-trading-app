from fastapi import FastAPI
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
LIVE_COMMENTARY = "AI Trading Floor: Autonomous agent online and scanning markets..."

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

def execute_autonomous_trade(ticker: str, quantity: float, side: str = "BUY"):
    if not T212_API_KEY or not T212_API_SECRET:
        log_activity("Autonomous Trade Error: Missing T212 credentials.", "error")
        return False
    
    clean_ticker = ticker.upper().strip().replace(".", "-")
    if "_" not in clean_ticker:
        clean_ticker = f"{clean_ticker}_US_EQ"

    final_qty = float(abs(quantity)) if side == "BUY" else float(-abs(quantity))
    headers = get_t212_auth_headers()
    
    payload = {
        "quantity": final_qty,
        "ticker": clean_ticker,
        "timeInForce": "DAY"
    }
    
    url = f"{T212_BASE_URL}/orders/market"
    log_activity(f"Autonomous AI initiating {side} order for {clean_ticker} (Qty: {final_qty})", "info")
    
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.status_code in [200, 201]:
            log_activity(f"SUCCESS: Autonomous order executed on Trading 212 for {clean_ticker}!", "success")
            # Log to Supabase db
            try:
                db.client.table("trades").insert({
                    "ticker": clean_ticker,
                    "side": side,
                    "quantity": final_qty,
                    "status": "EXECUTED"
                }).execute()
            except Exception:
                pass
            return True
        else:
            log_activity(f"T212 Rejected Autonomous Order [{res.status_code}]: {res.text}", "warning")
            return False
    except Exception as e:
        log_activity(f"Autonomous Execution Exception: {str(e)}", "error")
        return False

def fetch_live_broker_valuation():
    if not T212_API_KEY or not T212_API_SECRET:
        return 50000.00, []
    
    headers = get_t212_auth_headers()
    try:
        res = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return float(data.get("total", data.get("free", 50000.00))), []
    except Exception:
        pass
    return 50000.00, []

def get_trades_from_db():
    try:
        response = db.client.table("trades").select("*").order("created_at", desc=True).execute()
        return response.data if response.data else []
    except Exception:
        return []

async def autonomous_trading_agent():
    await asyncio.sleep(15) # Warm-up delay on startup
    watchlist = ["AAPL", "NVDA", "TSLA", "MSFT"]
    
    while True:
        log_activity("Autonomous Agent: Scanning market momentum across watchlist...", "info")
        for ticker in watchlist:
            try:
                # Pull recent price action using yfinance
                data = yf.download(ticker, period="5d", interval="1d", progress=False)
                if not data.empty and len(data) >= 2:
                    current_price = float(data['Close'].iloc[-1].item())
                    prev_price = float(data['Close'].iloc[-2].item())
                    change_pct = ((current_price - prev_price) / prev_price) * 100
                    
                    log_activity(f"Analyzed {ticker}: Price ${current_price:.2f} ({change_pct:+.2f}% 24h)", "info")
                    
                    # Autonomous decision rule: If momentum is positive (> +0.5%), execute a small buy position
                    if change_pct > 0.5:
                        log_activity(f"AI Signal Triggered: Bullish momentum detected on {ticker}. Executing trade...", "success")
                        execute_autonomous_trade(ticker, 1.0, "BUY")
                        break # Execute one trade per cycle to manage risk
                
            except Exception as e:
                log_activity(f"Error scanning {ticker}: {str(e)}", "error")
            
            await asyncio.sleep(5)
            
        # Sleep for 15 minutes before the next autonomous market scan cycle
        log_activity("Autonomous Agent: Scan complete. Entering sleep cycle for 15 minutes...", "info")
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    log_activity("PRV Autonomous Trading Desk online.", "success")
    task = asyncio.create_task(autonomous_trading_agent())
    yield
    task.cancel()

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
    <title>PRV Autonomous Trading Floor</title>
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
            <h1>PRV Autonomous Trading Floor</h1>
            <p>AI agent is actively scanning market momentum and executing live trades on Trading 212.</p>
        </div>
        
        <div class="card card-half">
            <h2>Live Account Valuation</h2>
            <div class="metric" id="valuation">Synchronizing...</div>
            <p>Status: <span style="color: #34d399; font-weight: bold;">AUTONOMOUS AI ACTIVE</span></p>
        </div>

        <div class="card card-half">
            <h2>Live AI Commentary & Scan Logs</h2>
            <div class="log" id="logStream">Loading live feed...</div>
        </div>

        <div class="card">
            <h2>Executed Trades on Trading 212</h2>
            <table>
                <thead>
                    <tr><th>Timestamp</th><th>Ticker</th><th>Side</th><th>Quantity</th><th>Status</th></tr>
                </thead>
                <tbody id="tradeTable">
                    <tr><td colspan="5" style="color: #6b7280;">Waiting for autonomous trade execution...</td></tr>
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
