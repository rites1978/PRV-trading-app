from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import asyncio
from datetime import datetime
import os
import requests
import base64
import time
from contextlib import asynccontextmanager
from db_manager import db
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

SYSTEM_LOGS = []
LIVE_COMMENTARY = "AI Trading Floor: Multi-Market Engine Online. Tracking Global Hours."

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": 50000.00, "free": 50000.00}
AI_COOLDOWN_MEMORY = {} 
VALID_T212_TICKERS = set()

# Unified Global Market Universe
MARKET_UNIVERSE = {
    # UK STOCKS (LSE)
    "BARC.L": {"t212": "BARC_l_EQ", "market": "UK", "qty": 25.0},
    "LLOY.L": {"t212": "LLOY_l_EQ", "market": "UK", "qty": 50.0},
    "BP.L": {"t212": "BP_l_EQ", "market": "UK", "qty": 10.0},
    "VOD.L": {"t212": "VOD_l_EQ", "market": "UK", "qty": 50.0},
    "TSCO.L": {"t212": "TSCO_l_EQ", "market": "UK", "qty": 15.0},
    "SHEL.L": {"t212": "SHEL_l_EQ", "market": "UK", "qty": 5.0},
    # US STOCKS (NASDAQ/NYSE)
    "AAPL": {"t212": "AAPL_US_EQ", "market": "US", "qty": 1.0},
    "NVDA": {"t212": "NVDA_US_EQ", "market": "US", "qty": 1.0},
    "TSLA": {"t212": "TSLA_US_EQ", "market": "US", "qty": 1.0},
    "MSFT": {"t212": "MSFT_US_EQ", "market": "US", "qty": 1.0},
    "AMZN": {"t212": "AMZN_US_EQ", "market": "US", "qty": 1.0},
    "META": {"t212": "META_US_EQ", "market": "US", "qty": 1.0}
}

def is_market_open(market_code: str) -> bool:
    """Checks if a specific market is currently open based on UTC time."""
    now = datetime.utcnow()
    if now.weekday() >= 5: return False # Markets closed on weekends
    
    time_decimal = now.hour + (now.minute / 60.0)
    
    if market_code == "UK":
        # London Stock Exchange: 07:00 to 15:30 UTC
        return 7.0 <= time_decimal < 15.5
    elif market_code == "US":
        # NYSE / NASDAQ: 13:30 to 20:00 UTC
        return 13.5 <= time_decimal < 20.0
    return False

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
    payload = {"ticker": exact_ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    
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
            return {"status": "REJECTED"}
    except Exception as e:
        log_activity(f"Order Exception: {str(e)}", "error")
        return {"status": "EXCEPTION"}

def fetch_live_data():
    global CACHED_PORTFOLIO, CACHED_ACCOUNT
    if not T212_API_KEY: return
    headers = get_t212_auth_headers()
    
    try:
        res_cash = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res_cash.status_code == 200: CACHED_ACCOUNT = res_cash.json()
    except Exception: pass
    
    try:
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200: CACHED_PORTFOLIO = res_port.json()
    except Exception: pass

async def autonomous_ai_brain():
    await asyncio.sleep(2)
    
    # 1. Sync valid tickers from T212
    try:
        res = requests.get(f"{T212_BASE_URL}/metadata/instruments", headers=get_t212_auth_headers(), timeout=15)
        if res.status_code == 200:
            for inst in res.json():
                if inst.get("ticker"):
                    VALID_T212_TICKERS.add(inst["ticker"])
            log_activity(f"Synced {len(VALID_T212_TICKERS)} official instrument codes.", "success")
    except Exception: pass

    await asyncio.sleep(3)
    log_activity("HFT Global Brain Online: Scanning actively open markets...", "success")
    
    while True:
        try:
            fetch_live_data()
            owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
            action_taken = False
            
            # --- PHASE 1: EVALUATE SELLS (TAKE PROFIT / STOP LOSS) ---
            for t212_ticker, pos in owned_tickers.items():
                qty = float(pos.get("quantity", 0))
                avg = float(pos.get("averagePrice", 0))
                cur = float(pos.get("currentPrice", 0))
                
                if avg > 0:
                    ret_pct = ((cur - avg) / avg) * 100
                    if ret_pct >= 0.05 or ret_pct <= -0.05:
                        log_activity(f"⚡ HFT TRIGGER: Auto-Selling {t212_ticker} (P/L: {ret_pct:+.2f}%)", "warning" if ret_pct < 0 else "success")
                        execute_live_order(t212_ticker, -qty)
                        action_taken = True
                        break 
            
            if action_taken:
                await asyncio.sleep(5)
                continue 
                
            # --- PHASE 2: EVALUATE BUYS ACROSS OPEN MARKETS ---
            for yf_ticker, info in MARKET_UNIVERSE.items():
                market_code = info["market"]
                t212_ticker = info["t212"]
                
                # Check 1: Is this specific market exchange currently open?
                if not is_market_open(market_code):
                    continue
                    
                # Check 2: Did the API confirm this ticker exists?
                if t212_ticker not in VALID_T212_TICKERS:
                    continue
                
                # Check 3: Do we already own it or did we just buy it?
                if t212_ticker in owned_tickers or (time.time() - AI_COOLDOWN_MEMORY.get(t212_ticker, 0) < 60):
                    continue 
                
                # Check 4: Momentum Analysis
                data = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
                
                if not data.empty and len(data) >= 3:
                    closes = [float(x) for x in data['Close'].values.flatten()]
                    recent_avg = sum(closes[-2:]) / 2.0
                    older_avg = sum(closes[-4:-2]) / 2.0 if len(closes) >= 4 else closes[0]
                    momentum = ((recent_avg - older_avg) / older_avg) * 100.0
                    
                    if momentum > 0.005: 
                        log_activity(f"🚀 RAPID MOMENTUM on {yf_ticker} ({momentum:+.3f}%). Executing BUY...", "success")
                        execute_live_order(t212_ticker, info["qty"])
                        AI_COOLDOWN_MEMORY[t212_ticker] = time.time()
                        action_taken = True
                        break 
                
                await asyncio.sleep(1) 
                
        except Exception as e:
            log_activity(f"AI Brain error: {str(e)}", "error")
            
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(autonomous_ai_brain())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/api/trigger-trade")
def trigger_manual_trade():
    if is_market_open("UK"):
        return execute_live_order("BARC_l_EQ", 10.0)
    elif is_market_open("US"):
        return execute_live_order("AAPL_US_EQ", 1.0)
    return {"status": "ERROR", "detail": "Both UK and US markets are closed."}

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    fetch_live_data()
    total_equity = float(CACHED_ACCOUNT.get("total", 50000.00))
    cash_balance = float(CACHED_ACCOUNT.get("free", 50000.00))
    
    return {
        "total_equity": total_equity,
        "cash_balance": cash_balance,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "markets": {
            "UK": is_market_open("UK"),
            "US": is_market_open("US")
        }
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
        .btn { background: #38bdf8; color: #0b0f19; font-weight: bold; padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; margin-right: 15px; }
        .btn:hover { background: #0ea5e9; }
        .market-status { display: flex; gap: 15px; padding: 8px 12px; background: #1f2937; border-radius: 6px; border: 1px solid #374151;}
        .market-indicator { font-size: 12px; font-weight: bold; display: flex; align-items: center; gap: 5px; }
        .dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; }
    </style>
</head>
<body>
    <div class="header">
        <h1>PRV HFT Autonomous AI Engine</h1>
        <div style="display: flex; align-items: center;">
            <button class="btn" onclick="triggerTrade()">Force Open Market Trade</button>
            <div class="market-status">
                <div class="market-indicator" id="ukStatus"><span class="dot" style="background: #6b7280;"></span> UK: LSE</div>
                <div class="market-indicator" id="usStatus"><span class="dot" style="background: #6b7280;"></span> US: NYSE</div>
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
            <h2>AI Global Execution Logs</h2>
            <div class="log-box" id="logStream">Initializing market routing...</div>
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
                    <tr><td colspan="5" style="text-align: center; color: #6b7280; padding: 30px;">HFT Scanner starting. Awaiting targets on open markets...</td></tr>
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
                
                // Update Market Hours Indicators
                const ukOpen = data.markets.UK;
                const usOpen = data.markets.US;
                
                document.getElementById('ukStatus').innerHTML = `<span class="dot" style="background: ${ukOpen ? '#34d399' : '#f87171'};"></span> UK: ${ukOpen ? 'OPEN' : 'CLOSED'}`;
                document.getElementById('ukStatus').style.color = ukOpen ? '#34d399' : '#94a3b8';
                
                document.getElementById('usStatus').innerHTML = `<span class="dot" style="background: ${usOpen ? '#34d399' : '#f87171'};"></span> US: ${usOpen ? 'OPEN' : 'CLOSED'}`;
                document.getElementById('usStatus').style.color = usOpen ? '#34d399' : '#94a3b8';

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
                        const cleanTicker = pos.ticker.replace('_l_EQ', '').replace('_US_EQ', '');
                        
                        return `
                        <tr>
                            <td style="font-weight: bold;">${cleanTicker}</td>
                            <td>${pos.quantity}</td>
                            <td>${pos.averagePrice.toFixed(4)}</td>
                            <td>${pos.currentPrice.toFixed(4)}</td>
                            <td class="${retClass}">${retSign}${retPct.toFixed(3)}%</td>
                        </tr>
                        `;
                    }).join('');
                } else {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #6b7280; padding: 20px;">No active positions. Scanning open markets for entry point...</td></tr>';
                }
            } catch(e) {}
        }
        
        setInterval(updateDashboard, 5000);
        updateDashboard();
    </script>
</body>
</html>
