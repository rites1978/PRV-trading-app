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
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: HFT Engine online. Scanning 10 markets continuously..."
TICKER_MAP = {} 

CACHED_PORTFOLIO = []
CACHED_CASH = 50000.00

# Expanded UK Blue-Chip Universe for High Volume Trading
MARKET_UNIVERSE = {
    "BARC.L": "BARC",
    "LLOY.L": "LLOY",
    "BP.L": "BP",
    "VOD.L": "VOD",
    "TSCO.L": "TSCO",
    "SHEL.L": "SHEL",
    "RIO.L": "RIO",
    "ULVR.L": "ULVR",
    "HSBA.L": "HSBA",
    "BATS.L": "BATS"
}

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    timestamp = datetime.now().strftime("%H:%M:%S")
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

def execute_live_order(exact_ticker: str, quantity: float):
    # Official T212 API format: Positive quantity = BUY, Negative quantity = SELL
    payload = {"ticker": exact_ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    
    log_activity(f"AI Dispatched {side} order for {exact_ticker} (Qty: {abs(quantity)})", "info")
    
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_t212_auth_headers(), timeout=15)
        if res.status_code in [200, 201]:
            status = res.json().get("status", "FILLED")
            log_activity(f"✅ {side} Executed! {exact_ticker} is {status}.", "success")
            try:
                db.client.table("trades").insert({
                    "ticker": exact_ticker, "side": side, "quantity": abs(quantity), "status": status
                }).execute()
            except Exception: pass
            return {"status": "SUCCESS", "detail": status}
        else:
            log_activity(f"Order Rejected [{res.status_code}]: {res.text}", "error")
            return {"status": "REJECTED", "detail": res.text}
    except Exception as e:
        log_activity(f"Order Exception: {str(e)}", "error")
        return {"status": "EXCEPTION", "detail": str(e)}

def get_live_portfolio():
    global CACHED_PORTFOLIO
    if not T212_API_KEY: return CACHED_PORTFOLIO
    try:
        res = requests.get(f"{T212_BASE_URL}/portfolio", headers=get_t212_auth_headers(), timeout=10)
        if res.status_code == 200:
            CACHED_PORTFOLIO = res.json()
    except Exception: pass
    return CACHED_PORTFOLIO

def get_account_cash():
    global CACHED_CASH
    if not T212_API_KEY: return CACHED_CASH
    try:
        res = requests.get(f"{T212_BASE_URL}/account/cash", headers=get_t212_auth_headers(), timeout=10)
        if res.status_code == 200:
            CACHED_CASH = float(res.json().get("total", 50000.00))
    except Exception: pass
    return CACHED_CASH

async def autonomous_ai_brain():
    await asyncio.sleep(2)
    
    try:
        res = requests.get(f"{T212_BASE_URL}/metadata/instruments", headers=get_t212_auth_headers(), timeout=15)
        if res.status_code == 200:
            for inst in res.json():
                if inst.get("shortName") and inst.get("ticker"):
                    TICKER_MAP[inst["shortName"].upper()] = inst["ticker"]
            log_activity(f"Successfully mapped {len(TICKER_MAP)} official tickers.", "success")
    except Exception: pass

    await asyncio.sleep(3)
    log_activity("HFT Brain Online: Commencing rapid buy/sell cycles...", "success")
    
    while True:
        try:
            portfolio = get_live_portfolio()
            owned_tickers = {pos.get("ticker"): pos for pos in portfolio} if portfolio else {}
            action_taken = False
            
            # --- PHASE 1: EVALUATE SELLS (TAKE PROFIT / STOP LOSS) ---
            for t212_ticker, pos in owned_tickers.items():
                qty = float(pos.get("quantity", 0))
                avg = float(pos.get("averagePrice", 0))
                cur = float(pos.get("currentPrice", 0))
                
                if avg > 0:
                    ret_pct = ((cur - avg) / avg) * 100
                    # SELL CONDITION: Auto-sell if profit > +0.05% or loss < -0.05%
                    if ret_pct >= 0.05 or ret_pct <= -0.05:
                        log_activity(f"⚡ HFT TRIGGER: Auto-Selling {t212_ticker} (P/L: {ret_pct:+.2f}%)", "warning" if ret_pct < 0 else "success")
                        execute_live_order(t212_ticker, -qty) # Negative quantity triggers SELL
                        action_taken = True
                        break 
            
            # Pause briefly if we sold something to prevent rate limits
            if action_taken:
                await asyncio.sleep(5)
                continue 
                
            # --- PHASE 2: EVALUATE BUYS ---
            for yf_ticker, short_name in MARKET_UNIVERSE.items():
                exact_ticker = TICKER_MAP.get(short_name)
                
                if not exact_ticker or exact_ticker in owned_tickers:
                    continue 
                
                # Fetch 1-minute data for hyper-fast response
                data = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
                
                if len(data) >= 3:
                    closes = data['Close'].values
                    current_price = float(closes[-1].item())
                    recent_avg = sum(closes[-2:]) / 2
                    older_avg = sum(closes[-4:-2]) / 2 if len(closes) >= 4 else closes[0].item()
                    momentum = ((recent_avg - older_avg) / older_avg) * 100
                    
                    # BUY CONDITION: Hyper-sensitive trigger (just 0.005% upward movement)
                    if momentum > 0.005: 
                        log_activity(f"🚀 RAPID MOMENTUM on {yf_ticker} ({momentum:+.3f}%). Executing BUY...", "success")
                        qty = 25.0 if "GB_EQ" in exact_ticker or "UK" in exact_ticker or "L_EQ" in exact_ticker else 1.0
                        execute_live_order(exact_ticker, qty) # Positive quantity triggers BUY
                        action_taken = True
                        break 
                
                await asyncio.sleep(1) # Tiny pause between Yahoo Finance checks
                
        except Exception as e:
            log_activity(f"AI Brain error: {str(e)}", "error")
            
        # Loop every 10 seconds for constant, non-stop trading analysis
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(autonomous_ai_brain())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    exact_ticker = TICKER_MAP.get("BARC")
    if not exact_ticker: return {"status": "ERROR"}
    return execute_live_order(exact_ticker, 10.0)

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    portfolio = get_live_portfolio()
    cash = get_account_cash()
    invested_value = sum(float(p.get("currentPrice", 0)) * float(p.get("quantity", 0)) for p in portfolio) if portfolio else 0.0
    
    return {
        "total_equity": cash + invested_value,
        "cash_balance": cash,
        "portfolio": portfolio,
        "system_logs": SYSTEM_LOGS[:15]
    }

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>PRV Autonomous AI Trading Floor</title>
    <style>
        body { background: #0b0f19; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1f2937; padding-bottom: 15px; margin-bottom: 20px; }
        h1 { color: #38bdf8; font-size: 24px; margin: 0; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #111827; border: 1px solid #1f2937; padding: 20px; border-radius: 12px; }
        .full-width { grid-column: span 2; }
        h2 { color: #94a3b8; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-top: 0; border-bottom: 1px solid #1f2937; padding-bottom: 8px; }
        .value-large { font-size: 36px; font-weight: bold; color: #f3f4f6; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
        th, td { text-align: left; padding: 12px 10px; border-bottom: 1px solid #1f2937; }
        th { color: #6b7280; font-weight: 500; }
        .pos { color: #34d399; font-weight: bold; }
        .neg { color: #f87171; font-weight: bold; }
        .log-box { background: #030712; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 13px; height: 250px; overflow-y: auto; border: 1px solid #374151; }
        .log-entry { margin-bottom: 6px; }
        .log-time { color: #6b7280; margin-right: 8px; }
        .log-info { color: #94a3b8; }
        .log-success { color: #34d399; font-weight: bold; }
        .log-error { color: #f87171; font-weight: bold; }
        .log-warning { color: #facc15; font-weight: bold; }
        .btn { background: #38bdf8; color: #0b0f19; font-weight: bold; padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
        .btn:hover { background: #0ea5e9; }
    </style>
</head>
<body>
    <div class="header">
        <h1>PRV HFT Autonomous AI Engine</h1>
        <div style="text-align: right; display: flex; align-items: center; gap: 15px;">
            <button class="btn" onclick="triggerTrade()">Force Verified Trade (BARC)</button>
            <div>
                <div style="color: #94a3b8; font-size: 12px;">SYSTEM STATUS</div>
                <div style="color: #34d399; font-weight: bold; font-size: 14px;">● HIGH-FREQUENCY HFT ACTIVE</div>
            </div>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h2>Total Portfolio Equity</h2>
            <div class="value-large" id="totalEquity">£--.--</div>
            <div style="color: #94a3b8; margin-top: 5px;">Available Cash: <span id="cashBal" style="color: #f3f4f6;">£--.--</span></div>
        </div>

        <div class="card">
            <h2>AI HFT Execution Logs</h2>
            <div class="log-box" id="logStream">Initializing connection...</div>
        </div>

        <div class="card full-width">
            <h2>Live Active Holdings (Constant Refresh)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Instrument</th>
                        <th>Shares</th>
                        <th>Avg Buy Price</th>
                        <th>Current Price</th>
                        <th>Return (P/L)</th>
                    </tr>
                </thead>
                <tbody id="portfolioTable">
                    <tr><td colspan="5" style="text-align: center; color: #6b7280; padding: 30px;">HFT Scanner starting. Awaiting targets...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        async function triggerTrade() {
            try {
                await fetch('/api/trigger-trade');
                updateDashboard();
            } catch(e) {}
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/api/dashboard_data');
                const data = await res.json();
                
                document.getElementById('totalEquity').innerText = '£' + data.total_equity.toLocaleString('en-GB', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                document.getElementById('cashBal').innerText = '£' + data.cash_balance.toLocaleString('en-GB', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                
                const logHtml = data.system_logs.map(log => {
                    let colorClass = log.level === 'success' ? 'log-success' : (log.level === 'error' ? 'log-error' : (log.level === 'warning' ? 'log-warning' : 'log-info'));
                    return `<div class="log-entry"><span class="log-time">[${log.time}]</span><span class="${colorClass}">${log.msg}</span></div>`;
                }).join('');
                document.getElementById('logStream').innerHTML = logHtml;

                const tbody = document.getElementById('portfolioTable');
                if (data.portfolio && data.portfolio.length > 0) {
                    tbody.innerHTML = data.portfolio.map(pos => {
                        const avg = parseFloat(pos.averagePrice);
                        const cur = parseFloat(pos.currentPrice);
                        const retPct = ((cur - avg) / avg) * 100;
                        const retClass = retPct >= 0 ? 'pos' : 'neg';
                        const retSign = retPct >= 0 ? '+' : '';
                        
                        return `
                        <tr>
                            <td style="font-weight: bold;">${pos.ticker.replace('_EQ', '').replace('_', '.')}</td>
                            <td>${pos.quantity}</td>
                            <td>${pos.averagePrice.toFixed(4)}</td>
                            <td>${pos.currentPrice.toFixed(4)}</td>
                            <td class="${retClass}">${retSign}${retPct.toFixed(3)}%</td>
                        </tr>
                        `;
                    }).join('');
                } else {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #6b7280; padding: 20px;">No active positions. AI is hunting for the right entry point.</td></tr>';
                }
            } catch(e) {}
        }
        
        setInterval(updateDashboard, 5000);
        updateDashboard();
    </script>
</body>
</html>
"""
