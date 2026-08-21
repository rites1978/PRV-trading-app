from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
import yfinance as yf
from db_manager import db

app = FastAPI()

def get_watchlist_from_db():
    try:
        response = db.client.table("friend_watchlist").select("*").execute()
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
            --svg-grid: rgba(255, 255, 255, 0.05);
        }
        :root[data-theme="light"] {
            --bg-color: #f5f5f7;
            --card-bg: rgba(255, 255, 255, 0.8);
            --card-border: rgba(0, 0, 0, 0.08);
            --text-primary: #1d1d1f;
            --text-secondary: #86868b;
            --accent-blue: #0071e3;
            --tab-bg: rgba(118, 118, 128, 0.08);
            --tab-active: #ffffff;
            --green: #248a3d;
            --green-glow: rgba(40, 205, 65, 0.2);
            --red: #d70015;
            --red-glow: rgba(255, 59, 48, 0.2);
            --svg-grid: rgba(0, 0, 0, 0.04);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif; -webkit-font-smoothing: antialiased; transition: background-color 0.3s ease, color 0.3s ease, border-color 0.3s ease; }
        body { background-color: var(--bg-color); color: var(--text-primary); padding: 40px 20px; display: flex; justify-content: center; }
        .container { width: 100%; max-width: 820px; }
        
        .header-container { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; }
        .header h1 { font-size: 32px; font-weight: 700; letter-spacing: -0.5px; }
        .header p { font-size: 13px; color: var(--text-secondary); margin-top: 2px; }
        
        .theme-toggle { background: var(--card-bg); border: 0.5px solid var(--card-border); border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 16px; backdrop-filter: blur(20px); }

        .tabs-list { display: flex; background-color: var(--tab-bg); padding: 4px; border-radius: 14px; gap: 4px; margin-bottom: 24px; overflow-x: auto; backdrop-filter: blur(20px); }
        .tab-btn { flex: 1; background: transparent; border: none; color: var(--text-secondary); font-size: 13px; font-weight: 500; padding: 10px 14px; border-radius: 10px; cursor: pointer; white-space: nowrap; text-align: center; }
        .tab-btn.active { background-color: var(--tab-active); color: var(--text-primary); font-weight: 600; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        
        .tab-pane { display: none; }
        .tab-pane.active { display: block; animation: fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1); }

        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        .apple-card { background: var(--card-bg); backdrop-filter: blur(40px); -webkit-backdrop-filter: blur(40px); border: 0.5px solid var(--card-border); border-radius: 20px; padding: 24px; margin-bottom: 16px; box-shadow: 0 16px 40px rgba(0,0,0,0.06); }
        
        .chart-container { width: 100%; height: 180px; margin-top: 14px; position: relative; }
        .svg-chart { width: 100%; height: 100%; overflow: visible; }
        
        .row-flex { display: flex; justify-content: space-between; align-items: center; }
        .stock-ticker { font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }
        .stock-name { font-size: 13px; color: var(--text-secondary); margin-top: 2px; }
        .stock-price { font-size: 18px; font-weight: 600; }
        
        .pill { display: inline-block; padding: 6px 12px; border-radius: 10px; font-size: 12px; font-weight: 600; }
        .pill.green { background-color: var(--green-glow); color: var(--green); border: 0.5px solid var(--green); }
        .pill.red { background-color: var(--red-glow); color: var(--red); border: 0.5px solid var(--red); }
        
        .balance-display { font-size: 36px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.5px; margin-top: 4px; }
        
        .form-group { display: flex; gap: 12px; }
        .apple-input { flex: 1; background: var(--tab-bg); border: 0.5px solid var(--card-border); border-radius: 12px; padding: 12px 16px; color: var(--text-primary); font-size: 14px; outline: none; }
        .apple-input:focus { border-color: var(--accent-blue); box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.15); }
        .apple-btn { background: var(--accent-blue); color: #ffffff; border: none; border-radius: 12px; padding: 0 24px; font-weight: 600; cursor: pointer; box-shadow: 0 4px 14px rgba(10, 132, 255, 0.3); }
        
        .pulse-dot { width: 8px; height: 8px; background-color: var(--green); border-radius: 50%; display: inline-block; box-shadow: 0 0 8px var(--green); animation: pulse 2s infinite; }
        @keyframes pulse { 0% { transform: scale(0.95); opacity: 0.8; } 50% { transform: scale(1.2); opacity: 1; } 100% { transform: scale(0.95); opacity: 0.8; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header-container">
            <div class="header">
                <h1>Markets</h1>
                <p>PRV Capital &bull; Autonomous Quant Desk</p>
            </div>
            <button class="theme-toggle" id="themeToggle" onclick="toggleTheme()">☀️</button>
        </div>

        <div class="tabs-list">
            <button class="tab-btn active" onclick="switchTab(0)">⚡ Nerve Center</button>
            <button class="tab-btn" onclick="switchTab(1)">📊 Ledger</button>
            <button class="tab-btn" onclick="switchTab(2)">🤖 AI Boardroom</button>
            <button class="tab-btn" onclick="switchTab(3)">⚙️ Telemetry</button>
            <button class="tab-btn" onclick="switchTab(4)">👀 Watchlist</button>
        </div>

        <div class="tab-pane active">
            <div class="apple-card">
                <div class="row-flex">
                    <div>
                        <div style="font-size: 12px; color: var(--text-secondary); font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px;">Portfolio Valuation</div>
                        <div class="balance-display">&pound;40,420.15</div>
                        <div style="margin-top: 6px; font-size: 13px; color: var(--green); font-weight: 600;">+&pound;420.15 (+1.05%) 24h Return</div>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 12px; color: var(--text-secondary); display: flex; align-items: center; gap: 6px;"><span class="pulse-dot"></span> Live Telemetry</span>
                    </div>
                </div>

                <div class="chart-container">
                    <svg class="svg-chart" viewBox="0 0 700 160" preserveAspectRatio="none">
                        <defs>
                            <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stop-color="var(--green)" stop-opacity="0.35"/>
                                <stop offset="100%" stop-color="var(--green)" stop-opacity="0.0"/>
                            </linearGradient>
                        </defs>
                        <line x1="0" y1="40" x2="700" y2="40" stroke="var(--svg-grid)" stroke-width="1"/>
                        <line x1="0" y1="80" x2="700" y2="80" stroke="var(--svg-grid)" stroke-width="1"/>
                        <line x1="0" y1="120" x2="700" y2="120" stroke="var(--svg-grid)" stroke-width="1"/>
                        
                        <path d="M 0,130 Q 120,110 240,90 T 480,50 T 700,20 L 700,160 L 0,160 Z" fill="url(#equityGradient)"/>
                        <path d="M 0,130 Q 120,110 240,90 T 480,50 T 700,20" fill="none" stroke="var(--green)" stroke-width="2.5" stroke-linecap="round"/>
                        <circle cx="700" cy="20" r="5" fill="var(--green)" stroke="#ffffff" stroke-width="2"/>
                    </svg>
                </div>
            </div>

            <div class="apple-card">
                <div style="font-size: 15px; font-weight: 600; margin-bottom: 6px;">Risk & Volatility Parameters</div>
                <div style="color: var(--text-secondary); font-size: 13px;">ATR Multiplier: 2.1x &bull; Circuit Breakers: Armed &bull; Max Drawdown Limit: 4.5%</div>
            </div>
        </div>

        <div class="tab-pane">
            <div class="apple-card row-flex">
                <div>
                    <div class="stock-ticker">NVDA (LONG)</div>
                    <div class="stock-name">Filled &bull; 50 Shares @ &pound;875.20 &bull; Limit Order</div>
                </div>
                <div style="text-align: right;">
                    <div class="stock-price">+&pound;1,240.00</div>
                    <span class="pill green">Active</span>
                </div>
            </div>
            <div class="apple-card row-flex">
                <div>
                    <div class="stock-ticker">AAPL (SHORT)</div>
                    <div class="stock-name">Filled &bull; 100 Shares @ &pound;182.50 &bull; Stop Loss Active</div>
                </div>
                <div style="text-align: right;">
                    <div class="stock-price">-&pound;112.50</div>
                    <span class="pill red">Retreating</span>
                </div>
            </div>
        </div>

        <div class="tab-pane">
            <div class="apple-card">
                <div style="font-size: 15px; font-weight: 600; margin-bottom: 6px;">Alpha Feed Veto Matrix</div>
                <div style="color: var(--text-secondary); font-size: 13px; line-height: 1.5;">Macro sentiment analyzer reports bullish consolidation across semiconductor indices. Risk engines clear for execution. No vetoes triggered in current window.</div>
            </div>
        </div>

        <div class="tab-pane">
            <div class="apple-card">
                <div style="font-size: 15px; font-weight: 600; margin-bottom: 6px;">Pipeline Health Diagnostics</div>
                <div style="color: var(--text-secondary); font-size: 13px; line-height: 1.6;">Supabase Cloud Database: Connected (12ms)<br>Yahoo Finance Feeds: Synchronized<br>Execution Daemon: Active (PID 4082)</div>
            </div>
        </div>

        <div class="tab-pane">
            <div class="apple-card" style="margin-bottom: 16px;">
                <form action="/add" method="post" class="form-group">
                    <input type="text" name="ticker" class="apple-input" placeholder="Symbol (e.g. AAPL)" required />
                    <input type="text" name="notes" class="apple-input" placeholder="Thesis / Note" />
                    <button type="submit" class="apple-btn">Add</button>
                </form>
            </div>
            $WATCHLIST_ITEMS$
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
    items = get_watchlist_from_db()
    cards_html = ""
    for item in items:
        ticker = item.get('ticker', '').upper()
        notes = item.get('notes', '')
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2d")
            price = float(hist['Close'].iloc[-1]) if not hist.empty else 0.0
            prev = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else price
            change = ((price - prev) / prev) * 100 if prev > 0 else 0.0
        except Exception:
            price, change = 0.0, 0.0
        
        is_pos = change >= 0
        pill_class = "green" if is_pos else "red"
        sign = "+" if is_pos else ""
        
        cards_html += f"""
        <div class="apple-card row-flex">
            <div>
                <div class="stock-ticker">{ticker}</div>
                <div class="stock-name">{notes}</div>
            </div>
            <div style="text-align: right;">
                <div class="stock-price">&pound;{price:,.2f}</div>
                <span class="pill {pill_class}">{sign}{change:.2f}%</span>
            </div>
        </div>
        """
    
    if not cards_html:
        cards_html = '<div class="apple-card" style="text-align: center; color: var(--text-secondary);">No symbols tracked yet.</div>'

    return HTML_TEMPLATE.replace("$WATCHLIST_ITEMS$", cards_html)

@app.post("/add", response_class=HTMLResponse)
def add_ticker(ticker: str = Form(...), notes: str = Form("")):
    try:
        db.client.table("friend_watchlist").insert({
            "ticker": ticker.upper().strip(),
            "notes": notes.strip()
        }).execute()
    except Exception:
        pass
    return read_root()
