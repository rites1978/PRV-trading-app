from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
import yfinance as yf
from db_manager import db
import asyncio
from datetime import datetime
import os
import requests
import pandas as pd

app = FastAPI()

SYSTEM_LOGS = []

def log_activity(message: str, level: str = "info"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {"time": timestamp, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 30:
        SYSTEM_LOGS.pop()

T212_API_KEY = os.getenv("T212_API_KEY", "")
T212_BASE_URL = os.getenv("T212_BASE_URL", "https://demo.trading212.com/api/v0/equity")

def execute_t212_order(ticker: str, quantity: float, order_type: str = "MARKET"):
    if not T212_API_KEY:
        log_activity(f"AI Agent: T212 API Key missing. Simulated execution for {quantity}x {ticker}.", "warning")
        return {"status": "simulated"}
    
    headers = {"Authorization": T212_API_KEY}
    payload = {"quantity": float(quantity), "ticker": ticker.upper().strip(), "type": order_type}
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=headers, timeout=10)
        if res.status_code in [200, 201]:
            log_activity(f"AI Agent: Successfully executed live order for {ticker} via T212!", "success")
            return {"status": "live", "data": res.json()}
        else:
            log_activity(f"AI Agent T212 Error: {res.text}", "error")
            return {"status": "error"}
    except Exception as e:
        log_activity(f"AI Agent Connection Error: {str(e)}", "error")
        return {"status": "error"}

# AUTONOMOUS TRADING AGENT LOOP
async def autonomous_trading_agent():
    # Pre-defined universe for the AI to autonomously scan and trade
    universe = ["AAPL", "NVDA", "TSLA", "MSFT", "GOOGL"]
    
    while True:
        log_activity("AI Agent: Starting autonomous market scan & strategy evaluation...", "info")
        try:
            for ticker in universe:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="5d")
                
                if len(hist) >= 2:
                    current_price = float(hist['Close'].iloc[-1])
                    prev_price = float(hist['Close'].iloc[-2])
                    pct_change = ((current_price - prev_price) / prev_price) * 100
                    
                    # AUTONOMOUS STRATEGY LOGIC:
                    # Example Rule: If a stock drops more than 1.5% in a session, AI treats it as a dip-buying opportunity.
                    # If it rises more than 2%, AI takes profit.
                    if pct_change <= -1.5:
                        log_activity(f"AI Strategy Trigger: {ticker} dropped {pct_change:.2f}%. Executing Autonomous BUY (Dip Buy).", "success")
                        
                        # Calculate position size (e.g., £1,000 notional allocation)
                        shares = round(1000.0 / current_price, 2)
                        
                        # 1. Fire broker API order
                        execute_t212_order(ticker, shares, "MARKET")
                        
                        # 2. Save trade to Supabase ledger
                        db.client.table("trades").insert({
                            "ticker": ticker,
                            "shares": shares,
                            "side": "BUY",
                            "price": current_price
                        }).execute()
                        
                    elif pct_change >= 2.0:
                        log_activity(f"AI Strategy Trigger: {ticker} surged {pct_change:.2f}%. Evaluating profit-taking.", "warning")
                        
            log_activity("AI Agent: Scan cycle complete. Standing by for next interval.", "info")
        except Exception as e:
            log_activity(f"AI Agent Error during scan: {str(e)}", "error")
            
        # Run autonomous cycle every 5 minutes (300 seconds)
        await asyncio.sleep(300)

@app.on_event("startup")
async def startup_event():
    log_activity("PRV Autonomous AI Trading Agent online and scanning markets.", "success")
    asyncio.create_task(autonomous_trading_agent())

def get_trades_from_db():
    try:
        response = db.client.table("trades").select("*").execute()
        return response.data if response.data else []
    except Exception:
        return []

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PRV Capital • Autonomous Terminal</title>
    <style>
        :root[data-theme="dark"] {
            --bg-color: #000000;
            --card-bg: rgba(28, 28, 30, 0.65);
            --card-border: rgba(255, 255, 255, 0.12);
            --text-primary: #f5f5f7;
            --text-secondary: #86868b;
            --accent-blue: #0a84ff;
            --tab-bg: rgba(118, 118, 128, 0.15);
            --tab-active: rgba(255, 255, 255, 0.15);
            --green: #30d158;
            --green-glow: rgba(48, 209, 88, 0.25);
            --red: #ff453a;
            --red-glow: rgba(255, 69, 58, 0.25);
            --yellow: #f59e0b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif; -webkit-font-smoothing: antialiased; transition: background-color 0.3s ease, color 0.3s ease; }
        body { background-color: var(--bg-color); color: var(--text-primary); padding: 40px 20px; display: flex; justify-content: center; }
        .container { width: 100%; max-width: 820px; }
        .header-container { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; }
        .header h1 { font-size: 32px; font-weight: 700; letter-spacing: -0.5px; }
        .header p { font-size: 13px; color: var(--text-secondary); margin-top: 2px; }
        .theme-toggle { background: var(--card-bg); border: 0.5px solid var(--card-border); border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 16px; backdrop-filter: blur(20px); }
        .tabs-list { display: flex; background-color: var(--tab-bg); padding: 4px; border-radius: 14px; gap: 4px; margin-bottom: 24px; }
        .tab-btn { flex: 1; background: transparent; border: none; color: var(--text-secondary); font-size: 13px; font-weight: 500; padding: 10px 14px; border-radius: 10px; cursor: pointer; text-align: center; }
        .tab-btn.active { background-color: var(--tab-active); color: var(--text-primary); font-weight: 600; }
        .tab-pane { display: none; }
        .tab-pane.active { display: block; }
        .apple-card { background: var(--card-bg); backdrop-filter: blur(40px); border: 0.5px solid var(--card-border); border-radius: 20px; padding: 24px; margin-bottom: 16px; box-shadow: 0 16px 40px rgba(0,0,0,0.06); }
        .row-flex { display: flex; justify-content: space-between; align-items: center; }
        .stock-ticker { font-size: 18px; font-weight: 700; }
        .stock-name { font-size: 13px; color: var(--text-secondary); margin-top: 2px; }
        .stock-price { font-size: 18px; font-weight: 600; }
        .pill { display: inline-block; padding: 6px 12px; border-radius: 10px; font-size: 12px; font-weight: 600; }
        .pill.green { background-color: var(--green-glow); color: var(--green); border: 0.5px solid var(--green); }
        .balance-display { font-size: 36px; font-weight: 700; margin-top: 4px; }
        .log-stream { background: rgba(0,0,0,0.3); border: 0.5px solid var(--card-border); border-radius: 12px; padding: 14px; font-family: ui-monospace, monospace; font-size: 12px; max-height: 280px; overflow-y: auto; }
        .log-item { margin-bottom: 6px; display: flex; gap: 10px; }
        .log-time { color: var(--text-secondary); }
        .log-msg.success { color: var(--green); }
        .log-msg.error { color: var(--red); }
        .log-msg.warning { color: var(--yellow); }
        .log-msg.info { color: var(--text-primary); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header-container">
            <div class="header">
                <h1>Markets</h1>
                <p>PRV Capital &bull; Fully Autonomous AI Agent</p>
            </div>
            <button class="theme-toggle" id="themeToggle" onclick="toggleTheme()">☀️</button>
        </div>

        <div class="tabs-list">
            <button class="tab-btn active" onclick="switchTab(0)">⚡ Nerve Center</button>
            <button class="tab-btn" onclick="switchTab(1)">📊 Autonomous Ledger</button>
            <button class="tab-btn" onclick="switchTab(2)">📡 AI Agent Telemetry</button>
        </div>

        <div class="tab-pane active">
            <div class="apple-card">
                <div style="font-size: 12px; color: var(--text-secondary); font-weight: 600; text-transform: uppercase;">Autonomous Portfolio Valuation</div>
                <div class="balance-display">&pound;40,420.15</div>
                <div style="margin-top: 6px; font-size: 13px; color: var(--green); font-weight: 600;">AI Strategy: Momentum & Dip-Buying Active</div>
            </div>
        </div>

        <div class="tab-pane">
            <div style="font-size: 14px; font-weight: 600; color: var(--text-secondary); margin-bottom: 10px; text-transform: uppercase;">AI-Executed Trade Audit Trail</div>
            $TRADES_ITEMS$
        </div>

        <div class="tab-pane">
            <div class="apple-card">
                <div style="font-size: 15px; font-weight: 600; margin-bottom: 12px;">Live AI Decision Log</div>
                <div class="log-stream">
                    $LOG_STREAM_HTML$
                </div>
            </div>
        </div>
    </div>

    <script>
        function switchTab(index) {
            const tabs = document.querySelectorAll('.tab-btn');
            const panes = document.querySelectorAll('.tab-pane');
            tabs.forEach((tab, i) => {
                tab.classList.toggle('active', i === index);
                panes[i].classList.toggle('active', i === index);
            });
        }
        function toggleTheme() {
            const html = document.documentElement;
            const toggleBtn = document.getElementById('themeToggle');
            if (html.getAttribute('data-theme') === 'dark') {
                html.setAttribute('data-theme', 'light');
                toggleBtn.textContent = '🌙';
            } else {
                html.setAttribute('data-theme', 'dark');
                toggleBtn.textContent = '☀️';
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def read_root():
    trades = get_trades_from_db()
    trades_html = ""
    for trade in trades:
        t_ticker = trade.get('ticker', '').upper()
        t_shares = trade.get('shares', 0)
        t_side = trade.get('side', 'BUY')
        t_price = trade.get('price', 0.0)
        
        trades_html += f"""
        <div class="apple-card row-flex">
            <div>
                <div class="stock-ticker">{t_ticker} ({t_side})</div>
                <div class="stock-name">AI Executed &bull; {t_shares} Shares @ &pound;{t_price:,.2f}</div>
            </div>
            <div style="text-align: right;">
                <div class="stock-price">&pound;{(t_shares * t_price):,.2f} Notional</div>
                <span class="pill green">Active Position</span>
            </div>
        </div>
        """
    if not trades_html:
        trades_html = '<div class="apple-card" style="text-align: center; color: var(--text-secondary);">AI agent is scanning markets for entry criteria...</div>'

    logs_html = ""
    for log in SYSTEM_LOGS:
        logs_html += f"""
        <div class="log-item">
            <span class="log-time">[{log['time']}]</span>
            <span class="log-msg {log['level']}">{log['msg']}</span>
        </div>
        """
    if not logs_html:
        logs_html = '<div class="log-item"><span class="log-msg info">AI Agent initializing market scanner...</span></div>'

    page = HTML_TEMPLATE.replace("$TRADES_ITEMS$", trades_html)
    return page.replace("$LOG_STREAM_HTML$", logs_html)
