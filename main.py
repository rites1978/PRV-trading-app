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
            --card-bg: rgba(28, 28, 30, 0.75);
            --card-hover: rgba(44, 44, 46, 0.85);
            --text-primary: #ffffff;
            --text-secondary: #86868b;
            --border-color: rgba(255, 255, 255, 0.12);
            --accent-blue: #0a84ff;
            --tab-bg: rgba(118, 118, 128, 0.12);
            --tab-active: #636366;
            --green: #30d158;
            --green-bg: rgba(48, 209, 88, 0.15);
            --red: #ff453a;
            --red-bg: rgba(255, 69, 58, 0.15);
        }
        :root[data-theme="light"] {
            --bg-color: #f5f5f7;
            --card-bg: rgba(255, 255, 255, 0.85);
            --card-hover: rgba(255, 255, 255, 1);
            --text-primary: #1d1d1f;
            --text-secondary: #86868b;
            --border-color: rgba(0, 0, 0, 0.1);
            --accent-blue: #0071e3;
            --tab-bg: rgba(118, 118, 128, 0.08);
            --tab-active: #ffffff;
            --green: #248a3d;
            --green-bg: rgba(40, 205, 65, 0.12);
            --red: #d70015;
            --red-bg: rgba(255, 59, 48, 0.12);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif; -webkit-font-smoothing: antialiased; transition: background-color 0.3s ease, color 0.3s ease; }
        body { background-color: var(--bg-color); color: var(--text-primary); padding: 40px 20px; display: flex; justify-content: center; }
        .container { width: 100%; max-width: 760px; }
        .header-container { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
        .header h1 { font-size: 34px; font-weight: 700; letter-spacing: -0.5px; }
        .header p { font-size: 14px; color: var(--text-secondary); margin-top: 2px; }
        .theme-toggle { background: var(--card-bg); border: 0.5px solid var(--border-color); border-radius: 50%; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 18px; }
        .tabs-list { display: flex; background-color: var(--tab-bg); padding: 4px; border-radius: 12px; gap: 4px; margin-bottom: 24px; overflow-x: auto; }
        .tab-btn { flex: 1; background: transparent; border: none; color: var(--text-secondary); font-size: 13px; font-weight: 500; padding: 8px 12px; border-radius: 8px; cursor: pointer; white-space: nowrap; text-align: center; }
        .tab-btn.active { background-color: var(--tab-active); color: var(--text-primary); font-weight: 600; box-shadow: 0 2px 6px rgba(0,0,0,0.15); }
        .tab-pane { display: none; }
        .tab-pane.active { display: block; }
        .apple-card { background: var(--card-bg); backdrop-filter: blur(40px); border: 0.5px solid var(--border-color); border-radius: 16px; padding: 20px 24px; margin-bottom: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.05); }
        .row-flex { display: flex; justify-content: space-between; align-items: center; }
        .stock-ticker { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
        .stock-name { font-size: 13px; color: var(--text-secondary); margin-top: 2px; }
        .stock-price { font-size: 20px; font-weight: 600; }
        .pill { display: inline-block; padding: 5px 10px; border-radius: 8px; font-size: 13px; font-weight: 600; }
        .pill.green { background-color: var(--green-bg); color: var(--green); }
        .pill.red { background-color: var(--red-bg); color: var(--red); }
        .form-group { display: flex; gap: 12px; margin-bottom: 0; }
        .apple-input { flex: 1; background: var(--tab-bg); border: 0.5px solid var(--border-color); border-radius: 10px; padding: 10px 14px; color: var(--text-primary); font-size: 14px; outline: none; }
        .apple-input:focus { border-color: var(--accent-blue); }
        .apple-btn { background: var(--accent-blue); color: #ffffff; border: none; border-radius: 10px; padding: 0 20px; font-weight: 600; cursor: pointer; }
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
                <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">System Status</div>
                <div style="color: var(--text-secondary); font-size: 14px;">All algorithmic execution nodes active. Volatility circuit breakers nominal.</div>
            </div>
        </div>

        <div class="tab-pane">
            <div class="apple-card row-flex">
                <div>
                    <div class="stock-ticker">NVDA (LONG)</div>
                    <div class="stock-name">Filled &bull; 50 Shares @ £875.20</div>
                </div>
                <div style="text-align: right;">
                    <div class="stock-price">+£1,240.00</div>
                    <span class="pill green">Active</span>
                </div>
            </div>
        </div>

        <div class="tab-pane">
            <div class="apple-card">
                <div style="font-size: 16px; font-weight: 600; margin-bottom: 6px;">Alpha Feed Veto</div>
                <div style="color: var(--text-secondary); font-size: 14px;">Macro sentiment analysis indicates bullish continuation for mega-cap tech.</div>
            </div>
        </div>

        <div class="tab-pane">
            <div class="apple-card">
                <div style="font-size: 16px; font-weight: 600; margin-bottom: 6px;">API Latency & Health</div>
                <div style="color: var(--text-secondary); font-size: 14px;">Supabase DB: Connected (14ms)<br>Yahoo Finance Feeds: Operational</div>
            </div>
        </div>

        <div class="tab-pane">
            <div class="apple-card" style="margin-bottom: 20px;">
                <form action="/add" method="post" class="form-group">
                    <input type="text" name="ticker" class="apple-input" placeholder="Symbol (e.g. LCID)" required />
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
                <div class="stock-price">£{price:,.2f}</div>
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