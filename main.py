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
LIVE_COMMENTARY = "AI Trading Floor: Global multi-market autonomous agent online..."

# Mapping Yahoo Finance tickers to exact Trading 212 Instrument Codes
WATCHLIST = {
    "LLOY.L": "LLOY_L_EQ",   # Lloyds Banking Group (UK - OPEN NOW)
    "BARC.L": "BARC_L_EQ",   # Barclays (UK - OPEN NOW)
    "VOD.L": "VOD_L_EQ",     # Vodafone (UK - OPEN NOW)
    "RR.L": "RR_L_EQ",       # Rolls Royce (UK - OPEN NOW)
    "AAPL": "AAPL_US_EQ",    # Apple (US - Opens 2:30 PM BST)
    "NVDA": "NVDA_US_EQ"     # Nvidia (US - Opens 2:30 PM BST)
}

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

def execute_live_order(t212_ticker: str, quantity: float):
    if not T212_API_KEY:
        return {"status": "ERROR"}
    
    payload = {
        "ticker": t212_ticker,
        "quantity": float(quantity)
    }
    
    url = f"{T212_BASE_URL}/orders/market"
    log_activity(f"AI Dispatching live order: {t212_ticker} (Qty: {quantity})", "info")
    
    try:
        res = requests.post(url, json=payload, headers=get_t212_auth_headers(), timeout=15)
        
        if res.status_code in [200, 201]:
            res_json = res.json()
            order_status = res_json.get("status", "NEW")
            final_status = "QUEUED" if order_status == "NEW" else "FILLED"
            
            try:
                db.client.table("trades").insert({
                    "ticker": t212_ticker,
                    "side": "BUY",
                    "quantity": float(quantity),
                    "status": final_status
                }).execute()
            except Exception:
                pass
                
            log_activity(f"Order Accepted by T212! Status: {final_status}", "success")
            return {"status": "SUCCESS", "detail": final_status}
        else:
            log_activity(f"T212 Rejection: {res.text}", "error")
            return {"status": "REJECTED"}
    except Exception as e:
        log_activity(f"API Error: {str(e)}", "error")
        return {"status": "EXCEPTION"}

def fetch_live_account_balance():
    if not T212_API_KEY:
        return 50000.00
    try:
        res = requests.get(f"{T212_BASE_URL}/account/cash", headers=get_t212_auth_headers(), timeout=10)
        if res.status_code == 200:
            return float(res.json().get("total", 50000.00))
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
    await asyncio.sleep(10) # Give server time to boot
    while True:
        log_activity("AI Agent: Commencing multi-market momentum scan...", "info")
        for yf_ticker, t212_ticker in WATCHLIST.items():
            try:
                data = yf.download(yf_ticker, period="5d", interval="1d", progress=False)
                if not data.empty and len(data) >= 2:
                    c1 = float(data['Close'].iloc[-1].item())
                    c0 = float(data['Close'].iloc[-2].item())
                    change = ((c1 - c0) / c0) * 100
                    
                    log_activity(f"AI Analysis [{t212_ticker}]: Price {c1:.2f} | Momentum: {change:+.2f}%", "info")
                    
                    # AI Trading Rule: Execute buy if short-term momentum is positive
                    if change > 0.2:
                        log_activity(f"Breakout momentum detected on {t212_ticker}. AI executing autonomous trade...", "success")
                        # Buy larger quantities for UK penny stocks (like LLOY) to simulate real weighting
                        qty = 100.0 if "L_EQ" in t212_ticker else 1.0
                        execute_live_order(t212_ticker, qty)
                        break # Execute one trade per cycle, then sleep
            except Exception as e:
                pass
            
            await asyncio.sleep(3) # Briefly pause between fetching tickers
            
        log_activity("Scan cycle complete. Monitoring positions. Next scan in 10 minutes.", "info")
        await asyncio.sleep(600) # Wait 10 mins before next full market scan

@asynccontextmanager
async def lifespan(app: FastAPI):
    log_activity("PRV Autonomous Multi-Market Engine booting up...", "success")
    task = asyncio.create_task(background_autonomous_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    # Manual trigger now buys a UK stock to prove instant fill while US is closed
    return execute_live_order("BARC_L_EQ", 10.0)

@app.api_route("/api/valuation", methods=["GET", "HEAD"])
def get_live_valuation():
    return {
        "valuation": fetch_live_account_balance(),
        "trades": get_trades_from_db()[:15],
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
            <h1>PRV Autonomous Trading Floor (Global Markets)</h1>
            <p>AI is evaluating UK (LSE) and US (NASDAQ/NYSE) markets for live execution.</p>
            <button class="btn" onclick="triggerTrade()">Force AI Trade (Barclays UK - Instant Fill Test)</button>
            <span id="execStatus" style="margin-left: 15px; font-weight: bold; color: #38bdf8;"></span>
        </div>
        
        <div class="card card-half">
            <h2>Live Practice Balance</h2>
            <div class="metric" id="valuation">Synchronizing...</div>
            <p>Status: <span style="color: #34d399; font-weight: bold;">AI TRADING AGENT ONLINE</span></p>
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
                    <tr><td colspan="5" style="color: #6b7280;">Loading trade history...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    <script>
        async function triggerTrade() {
            document.getElementById('execStatus').innerText = "Routing UK market order...";
            try {
                const res = await fetch('/api/trigger-trade');
                const data = await res.json();
                document.getElementById('execStatus').innerText = "Result: " + data.status + (data.detail ? " (" + data.detail + ")" : "");
                fetchDashboard();
            } catch(e) {
                document.getElementById('execStatus').innerText = "Network fail.";
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
                    tbody.innerHTML = data.trades.map(t => {
                        let statusColor = t.status === 'QUEUED' ? '#facc15' : '#34d399';
                        return `
                        <tr>
                            <td>${t.created_at.split('T')[1].substring(0, 8) || 'Just now'}</td>
                            <td><b>${t.ticker}</b></td>
                            <td style="color: #34d399">${t.side}</td>
                            <td>${t.quantity}</td>
                            <td><span style="color: ${statusColor}; font-weight: bold;">${t.status}</span></td>
                        </tr>
                        `;
                    }).join('');
                }
            } catch(e) {}
        }
        setInterval(fetchDashboard, 2000);
        fetchDashboard();
    </script>
</body>
</html>
"""
