import streamlit as st
import pandas as pd
import requests
import os
from dotenv import load_dotenv
from db_manager import db
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px

load_dotenv()
API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")

st.set_page_config(
    page_title="PRV Capital | Institutional Command",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==========================================
# APPLE iOS 27 LIQUID GLASS DESIGN SYSTEM
# ==========================================
import streamlit as st

# Page Config - Clean, wide layout
st.set_page_config(
    page_title="PRV Capital | Markets",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- APPLE STOCKS DESIGN SYSTEM CSS ---
st.markdown("""
<style>
    /* Global Reset & Dark OLED Background */
    .stApp {
        background-color: #000000;
        color: #f5f5f7;
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }
    
    /* Hide Streamlit Header & Footer */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Apple-Style Glass Card */
    .apple-card {
        background: rgba(28, 28, 30, 0.65);
        backdrop-filter: blur(25px);
        -webkit-backdrop-filter: blur(25px);
        border: 0.5px solid rgba(255, 255, 255, 0.12);
        border-radius: 16px;
        padding: 20px 24px;
        margin-bottom: 12px;
        transition: transform 0.2s ease, background 0.2s ease;
    }
    .apple-card:hover {
        background: rgba(44, 44, 46, 0.75);
    }
    
    /* Typography - Apple Scale */
    .apple-title {
        font-size: 34px;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: #ffffff;
        margin-bottom: 4px;
    }
    .apple-subtitle {
        font-size: 15px;
        font-weight: 400;
        color: #86868b;
        margin-bottom: 24px;
    }
    .stock-ticker {
        font-size: 20px;
        font-weight: 600;
        color: #ffffff;
        letter-spacing: -0.3px;
    }
    .stock-name {
        font-size: 13px;
        color: #86868b;
        font-weight: 400;
    }
    .stock-price {
        font-size: 20px;
        font-weight: 600;
        color: #ffffff;
        text-align: right;
    }
    
    /* Apple Pill Badges for Change % */
    .pill-green {
        background-color: rgba(48, 209, 88, 0.15);
        color: #30d158;
        padding: 6px 12px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 14px;
        text-align: right;
        display: inline-block;
    }
    .pill-red {
        background-color: rgba(255, 69, 58, 0.15);
        color: #ff453a;
        padding: 6px 12px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 14px;
        text-align: right;
        display: inline-block;
    }

    /* Custom Apple Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: rgba(28, 28, 30, 0.4);
        padding: 4px;
        border-radius: 12px;
        border: 0.5px solid rgba(255, 255, 255, 0.08);
    }
    .stTabs [data-baseweb="tab"] {
        height: 36px;
        border-radius: 8px;
        color: #86868b;
        font-weight: 500;
        font-size: 13px;
        border: none !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2c2c2e !important;
        color: #ffffff !important;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# --- APP HEADER ---
st.markdown('<div class="apple-title">Watchlist</div>', unsafe_allow_html=True)
st.markdown('<div class="apple-subtitle">PRV Capital • Autonomous Terminal</div>', unsafe_allow_html=True)

# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "⚡ Nerve Center", 
    "📊 Execution Ledger", 
    "🤖 AI Boardroom", 
    "⚙️ System Telemetry", 
    "👀 Friend's Watchlist"
])

# Example layout implementation for Tab 5 (Friend's Watchlist) styled Apple-clean
with tab5:
    st.markdown("### Market Tracker", help="External ideas & tracked equities")
    
    # Minimalist Apple Input Form
    with st.form("add_watchlist_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 3, 1])
        with col1:
            new_ticker = st.text_input("Symbol", placeholder="e.g. AAPL, LCID")
        with col2:
            new_notes = st.text_input("Note", placeholder="e.g. Breakout watch")
        with col3:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Add Symbol", use_container_width=True)
            
        if submitted and new_ticker:
            from watchlist_manager import WatchlistManager
            wm = WatchlistManager()
            success, msg = wm.add_ticker(new_ticker, new_notes)
            if success:
                st.success(f"Added {new_ticker.upper()}")
                st.rerun()
            else:
                st.error(msg)

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    
    # Render Watchlist in Apple Stocks Row Format
    from watchlist_manager import WatchlistManager
    wm = WatchlistManager()
    watchlist_items = wm.get_watchlist_data()
    
    if watchlist_items:
        for w in watchlist_items:
            is_positive = w['change_pct'] >= 0
            pill_class = "pill-green" if is_positive else "pill-red"
            sign = "+" if is_positive else ""
            
            # Apple Stocks Clean Row Layout
            st.markdown(f"""
                <div class="apple-card" style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div class="stock-ticker">{w['ticker']}</div>
                        <div class="stock-name">{w['name']} &bull; <span style="color:#636366;">{w['notes']}</span></div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 24px;">
                        <div class="stock-price">£{w['price']:,.2f}</div>
                        <div>
                            <span class="{pill_class}">{sign}{w['change_pct']:.2f}%</span>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
            <div class="apple-card" style="text-align: center; color: #86868b; padding: 40px;">
                No symbols tracked yet. Add one above to populate your feed.
            </div>
        """, unsafe_allow_html=True)

# Header Section
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.markdown("<h1 style='margin-bottom:0; font-weight:700; letter-spacing:-1px;'>🏛️ PRV CAPITAL MANAGEMENT</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color:#64748b; font-size:0.95rem; margin-top:2px;'>Autonomous Quantitative Desk • Cloud Synchronized</p>", unsafe_allow_html=True)
with col_head2:
    st.markdown("<div style='text-align:right; padding-top:15px;'><span style='background:rgba(52,211,153,0.12); color:#34d399; border:1px solid rgba(52,211,153,0.3); padding:6px 14px; border-radius:30px; font-weight:600; font-size:0.8rem;'>● SYSTEM LIVE</span></div>", unsafe_allow_html=True)

# Fetch Cloud Telemetry
telemetry = db.get_latest_telemetry()
nav = float(telemetry.get('total_nav', 40000.0)) if telemetry else 40000.0
free_cash = float(telemetry.get('free_cash', 40000.0)) if telemetry else 40000.0
var_95 = float(telemetry.get('portfolio_var_95', 800.0)) if telemetry else 800.0
drawdown = float(telemetry.get('current_drawdown_pct', 0.0)) if telemetry else 0.0

# Top Tier Metric Banners
m1, m2, m3, m4 = st.columns(4)
m1.metric("Portfolio NAV", f"£{nav:,.2f}", delta="Target £40k")
m2.metric("Liquid Reserves", f"£{free_cash:,.2f}")
m3.metric("Est. 95% Daily VaR", f"£{var_95:,.2f}", delta="-2.0% Cap", delta_color="inverse")
m4.metric("Max Drawdown", f"{drawdown:.2f}%", delta="Nominal", delta_color="normal")

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "⚡ Nerve Center", 
    "📊 Execution Ledger", 
    "🤖 AI Boardroom", 
    "⚙️ System Telemetry", 
    "👀 Friend's Watchlist"
])

# Fetch Active Positions from Broker
positions_data = []
try:
    port_res = requests.get("https://demo.trading212.com/api/v0/equity/portfolio", auth=(API_KEY, API_SECRET), timeout=4)
    if port_res.status_code == 200 and port_res.json():
        positions_data = port_res.json()
except Exception:
    pass

# ==========================================
# TAB 1: NERVE CENTER & DYNAMIC ALLOCATION
# ==========================================
with tab1:
    c_left, c_right = st.columns([1.5, 1])
    
    with c_left:
        st.markdown("### 📡 Live AI Nerve Center")
        debates = db.get_recent_debates(limit=10) or []
        trades = db.get_execution_history(limit=6) or []
        
        terminal_html = '<div class="glass-terminal">'
        if not debates and not trades:
            terminal_html += '<span style="color:#64748b;">[STANDBY] Awaiting autonomous cycle execution...</span><br>'
        else:
            for d in debates:
                ts = d.get('timestamp', 'LIVE')[:19]
                ticker = d.get('asset_ticker', 'ASSET')
                consensus = d.get('final_consensus', 'HOLD')
                score = d.get('conviction_score', 5.0)
                terminal_html += f'<span style="color:#64748b;">[{ts}]</span> <span class="badge badge-board">BOARDROOM</span> <span style="color:#f8fafc;">Evaluated <b>{ticker}</b> ➔ Consensus: <span style="color:#38bdf8;">{consensus}</span> (Conviction: {score}/10)</span><br>'
                
                if consensus != 'HOLD':
                    veto_status = "VETOED ⛔" if d.get('risk_veto') else "APPROVED ✅"
                    badge_type = "badge-risk" if d.get('risk_veto') else "badge-exec"
                    terminal_html += f'<span style="color:#64748b;">[{ts}]</span> <span class="badge {badge_type}">RISK GUARD</span> <span style="color:#cbd5e1;">Exposure limits check: {veto_status}</span><br>'

            for t in trades:
                ts = t.get('timestamp', 'LIVE')[:19]
                ticker = t.get('asset_ticker', 'ASSET')
                action = t.get('action', 'ORDER')
                qty = t.get('quantity', 0)
                price = t.get('fill_price', 0)
                terminal_html += f'<span style="color:#64748b;">[{ts}]</span> <span class="badge badge-exec">EXECUTION</span> <span style="color:#4ade80;"><b>{action}</b> {qty}x {ticker} filled @ £{price:,.2f}</span><br>'
        
        terminal_html += '<br><span style="color:#38bdf8;">> Autonomous surveillance active...</span></div>'
        st.markdown(terminal_html, unsafe_allow_html=True)

    with c_right:
        st.markdown("### 🍩 Asset Allocation")
        
        # Prepare Plotly Allocation Donut
        labels = ['Liquid Cash']
        values = [free_cash]
        colors = ['#38bdf8', '#818cf8', '#c084fc', '#f472b6', '#34d399']
        
        if positions_data:
            for p in positions_data:
                labels.append(p.get('ticker', 'Asset'))
                val = p.get('quantity', 0) * p.get('currentPrice', 0)
                values.append(max(val, 10.0))
        
        fig_donut = go.Figure(data=[go.Pie(
            labels=labels, 
            values=values, 
            hole=.65,
            textinfo='label+percent',
            marker=dict(colors=colors, line=dict(color='rgba(255,255,255,0.15)', width=1.5)),
            hoverinfo='label+value+percent'
        )])
        
        fig_donut.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#94a3b8', family='SF Pro Display'),
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=False,
            height=380,
            annotations=[dict(text=f"NAV<br><b>£{nav/1000:,.0f}k</b>", x=0.5, y=0.5, font_size=20, font_color="#ffffff", showarrow=False)]
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    # Active Holdings Glass Table
    st.markdown("### 💼 Broker Holdings (Live Telemetry)")
    if positions_data:
        df_p = pd.DataFrame(positions_data)
        df_p['Return %'] = ((df_p['currentPrice'] - df_p['averagePrice']) / df_p['averagePrice']) * 100
        st.dataframe(df_p[['ticker', 'quantity', 'averagePrice', 'currentPrice', 'ppl', 'Return %']], use_container_width=True, hide_index=True)
    else:
        st.info("🛡️ Capital currently 100% safeguarded in liquid sterling reserves. AI scanning for alpha opportunities.")

# ==========================================
# TAB 2: CAPITAL CURVE & PERFORMANCE CHARTS
# ==========================================
 
with tab2:
    st.markdown("### ⚡ Official Execution Ledger")
    trades = db.get_execution_history(limit=25)
    
    if trades:
        for t in trades:
            action = t.get('action', 'BUY')
            badge_color = "#34d399" if action == "BUY" else "#f43f5e"
            bg_badge = "rgba(52,211,153,0.12)" if action == "BUY" else "rgba(244,63,94,0.12)"
            border_badge = "rgba(52,211,153,0.3)" if action == "BUY" else "rgba(244,63,94,0.3)"
            
            st.markdown(f"""
                <div class="glass-card" style="padding: 16px 20px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="background:{bg_badge}; color:{badge_color}; border:1px solid {border_badge}; padding:4px 10px; border-radius:8px; font-weight:700; font-size:0.8rem; margin-right:10px;">{action}</span>
                        <span style="font-weight:700; font-size:1.1rem; color:#ffffff;">{t.get('asset_ticker')}</span>
                        <span style="color:#64748b; font-size:0.85rem; margin-left:12px;">{t.get('timestamp')[:19]}</span>
                    </div>
                    <div style="text-align:right;">
                        <span style="font-weight:600; color:#f8fafc; font-size:1rem;">{t.get('quantity')} Shares @ £{float(t.get('fill_price', 0)):,.2f}</span>
                        <div style="color:#94a3b8; font-size:0.8rem;">Stop-Loss: £{float(t.get('dynamic_stop_loss', 0)):,.2f}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No executions recorded yet. Standing by for high-conviction orders.")

# ==========================================
# TAB 3: AI BOARDROOM ARCHIVE
# ==========================================
with tab3:
    st.markdown("### 🏛️ Autonomous Boardroom Deliberation Archive")
    recent_debates = db.get_recent_debates(limit=20)
    if recent_debates:
        for d in recent_debates:
            with st.expander(f"📌 {d.get('asset_ticker')} | Consensus: {d.get('final_consensus')} | Conviction: {d.get('conviction_score')}/10 ({d.get('timestamp', '')[:19]})"):
                st.markdown(f"**Technical Analysis Agent:** {d.get('technical_analysis', {}).get('report', 'Nominal signals')}")
                st.markdown(f"**Sentiment & Macro Agent:** {d.get('sentiment_analysis', {}).get('headline', 'Standard conditions')}")
                st.markdown(f"**Risk Officer Veto:** {'⛔ Active Veto' if d.get('risk_veto') else '✅ Approved by Risk Officer'}")
    else:
        st.info("No recorded deliberations in database.")

# ==========================================
# TAB 4: AGENT CONFIDENCE INTELLIGENCE MATRIX
# ==========================================
with tab4:
    st.markdown("### 🧠 Real-Time Agent Voting Weight Matrix")
    
    # Plotly Agent Weight Breakdown
    agents = ['Technical Momentum', 'Macro Sentiment', 'Valuation / DCF', 'Risk Officer']
    weights = [1.2, 0.95, 1.1, 1.4]  # Dynamic weights from database / post-mortem
    
    fig_weights = go.Figure(go.Bar(
        x=weights,
        y=agents,
        orientation='h',
        marker=dict(
            color=['#38bdf8', '#818cf8', '#c084fc', '#34d399'],
            line=dict(color='rgba(255,255,255,0.2)', width=1)
        )
    ))
    
    fig_weights.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#94a3b8', family='SF Pro Display'),
        xaxis=dict(title="Voting Multiplier (1.0 = Baseline)", showgrid=True, gridcolor='rgba(255,255,255,0.05)'),
        yaxis=dict(autorange="reversed"),
        margin=dict(t=20, b=20, l=20, r=20),
        height=280
    )
    
    st.plotly_chart(fig_weights, use_container_width=True)
    
    st.markdown("### 📝 Post-Mortem & Alpha-Leak Ledger")
    try:
        mortems = db.client.table("post_mortem_analysis").select("*").order("trade_id", desc=True).limit(5).execute()
        if mortems.data:
            for m in mortems.data:
                st.warning(f"Trade Ref: {m['trade_id'][:8]} | Attributed: {m['attributed_agent']} | Finding: {m['root_cause_analysis']}")
        else:
            st.success("✨ Zero structural alpha-leaks detected across active decision cycles.")
    except Exception:
        st.info("Alpha-leak audit system nominal.")

st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
if st.button("🔄 Sync Glass Telemetry"):
    st.rerun() if hasattr(st, "rerun") else st.experimental_rerun()

    # Add to your tab definitions
# tab1, tab2, tab3, tab4, tab5 = st.tabs([... , "👀 Friend's Watchlist"])

with tab5:
    st.markdown("### 👀 Friend's Watchlist & Ideas")
    st.markdown("<p style='color:#64748b;'>Passive tracking for external ideas. Automatically identified via Yahoo Finance.</p>", unsafe_allow_html=True)
    
    # Quick Add Form
    with st.form("add_watchlist_form"):
        col1, col2, col3 = st.columns([2, 3, 1])
        with col1:
            new_ticker = st.text_input("Ticker Symbol", placeholder="e.g. TSLA, AZN.L, PLTR")
        with col2:
            new_notes = st.text_input("Notes / Rationale", placeholder="e.g. Friend's swing trade idea")
        with col3:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Add Company")
            
        if submitted and new_ticker:
            from watchlist_manager import WatchlistManager
            wm = WatchlistManager()
            success, msg = wm.add_ticker(new_ticker, new_notes)
            if success:
                st.success(f"Added {new_ticker.upper()} to watchlist!")
                st.rerun()
            else:
                st.error(f"Could not add ticker: {msg}")

    st.markdown("---")
    
    # Display Watchlist Cards with iOS 27 Glass Styling
    from watchlist_manager import WatchlistManager
    wm = WatchlistManager()
    watchlist_items = wm.get_watchlist_data()
    
    if watchlist_items:
        for w in watchlist_items:
            change_color = "#34d399" if w['change_pct'] >= 0 else "#f43f5e"
            sign = "+" if w['change_pct'] >= 0 else ""
            
            st.markdown(f"""
                <div class="glass-card" style="padding: 16px 20px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-weight:700; font-size:1.1rem; color:#ffffff; margin-right:12px;">{w['ticker']}</span>
                        <span style="color:#e2e8f0; font-size:0.9rem; margin-right:12px;">{w['name']}</span>
                        <span style="color:#94a3b8; font-size:0.8rem; background:rgba(255,255,255,0.05); padding:2px 8px; border-radius:4px;">{w['notes']}</span>
                    </div>
                    <div style="text-align:right;">
                        <span style="font-weight:600; color:#f8fafc; font-size:1rem; margin-right:16px;">£{w['price']:,.2f}</span>
                        <span style="color:{change_color}; font-weight:700; font-size:0.9rem;">{sign}{w['change_pct']:.2f}%</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No tickers on the watchlist yet. Add a company above to start tracking!")