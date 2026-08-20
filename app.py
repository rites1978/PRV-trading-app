import streamlit as st
import pandas as pd
import requests
import os
from dotenv import load_dotenv
from db_manager import db
from datetime import datetime

load_dotenv()
API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")

st.set_page_config(
    page_title="PRV Capital | Institutional Command",
    page_icon="🏛️",
    layout="wide"
)

# Upgraded Dark Theme & Terminal Styling
st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; color: #f3f4f6; }
    div[data-testid="stMetric"] { background-color: #161e2e; border: 1px solid #1f2937; border-radius: 8px; padding: 15px; }
    .stTabs [data-baseweb="tab"] { background-color: #161e2e; color: #9ca3af; border: 1px solid #1f2937; }
    .stTabs [aria-selected="true"] { background-color: #2563eb !important; color: #ffffff !important; }
    
    /* Nerve Center Terminal Styling */
    .terminal-container {
        background-color: #050505;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 15px;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.9rem;
        height: 350px;
        overflow-y: auto;
        box-shadow: inset 0 0 10px #000000;
    }
    .log-time { color: #555555; }
    .log-agent { color: #00d2ff; font-weight: bold; }
    .log-risk { color: #ff007f; font-weight: bold; }
    .log-exec { color: #00ff00; font-weight: bold; }
    .log-msg { color: #cccccc; }
    </style>
""", unsafe_allow_html=True)

st.title("🏛️ PRV CAPITAL MANAGEMENT")
st.caption("Autonomous Quantitative Intelligence Desk • Cloud Synchronized")

tab1, tab2, tab3, tab4 = st.tabs(["💼 Nerve Center & Portfolio", "⚡ Execution Ledger", "🏛️ AI Boardroom Transcripts", "🧠 Agent Intelligence"])

with tab1:
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.subheader("📡 Live AI Nerve Center")
        st.markdown("<p style='color: #888; font-size: 0.85rem;'>Monitoring multi-agent pipeline and broker telemetry streams...</p>", unsafe_allow_html=True)
        
        # Build the Nerve Center Feed from Supabase Data
        debates = db.get_recent_debates(limit=10) or []
        trades = db.get_execution_history(limit=5) or []
        
        # Create HTML for the terminal feed
        terminal_html = '<div class="terminal-container">'
        if not debates and not trades:
            terminal_html += '<span class="log-msg">Initiating system... awaiting first AI boardroom cycle.</span><br><span class="log-msg blinking-cursor">_</span>'
        else:
            for d in debates:
                ts = d.get('timestamp', 'LIVE')[:19]
                ticker = d.get('asset_ticker', 'UNKNOWN')
                consensus = d.get('final_consensus', 'HOLD')
                terminal_html += f'<span class="log-time">[{ts}]</span> <span class="log-agent">[BOARDROOM]</span> <span class="log-msg">Scanning {ticker}. Consensus: {consensus}.</span><br>'
                
                if consensus != 'HOLD':
                    veto_status = "VETOED" if d.get('risk_veto') else "CLEARED"
                    veto_color = "log-risk" if d.get('risk_veto') else "log-exec"
                    terminal_html += f'<span class="log-time">[{ts}]</span> <span class="{veto_color}">[RISK GUARD]</span> <span class="log-msg">{ticker} correlation check: {veto_status}.</span><br>'

            for t in trades:
                ts = t.get('timestamp', 'LIVE')[:19]
                ticker = t.get('asset_ticker', 'UNKNOWN')
                action = t.get('action', 'TRADE')
                qty = t.get('quantity', 0)
                price = t.get('fill_price', 0)
                terminal_html += f'<span class="log-time">[{ts}]</span> <span class="log-exec">[EXECUTION]</span> <span class="log-msg">{action} {qty}x {ticker} filled @ £{price:,.2f}</span><br>'
        
        terminal_html += '<br><span class="log-msg" style="color:#00ff00;">> System standing by...</span><span class="blinking-cursor">_</span></div>'
        st.markdown(terminal_html, unsafe_allow_html=True)

    with c2:
        st.subheader("Fund Telemetry")
        telemetry = db.get_latest_telemetry()
        nav = float(telemetry.get('total_nav', 40000.0)) if telemetry else 40000.0
        cash = float(telemetry.get('free_cash', 40000.0)) if telemetry else 40000.0
        
        st.metric("Portfolio NAV", f"£{nav:,.2f}", delta="+£0.00 (Live)")
        st.metric("Free Cash", f"£{cash:,.2f}")
        
        drawdown = float(telemetry.get('current_drawdown_pct', 0.0)) if telemetry else 0.0
        risk_color = "🟢" if drawdown > -0.05 else "🟡" if drawdown > -0.10 else "🔴"
        st.markdown(f"**Status:** {risk_color} Operations Nominal")

    st.markdown("---")
    st.subheader("Active Positions (Broker Telemetry)")
    try:
        port_res = requests.get("https://demo.trading212.com/api/v0/equity/portfolio", auth=(API_KEY, API_SECRET), timeout=5)
        if port_res.status_code == 200 and port_res.json():
            df = pd.DataFrame(port_res.json())
            df['Return %'] = ((df['currentPrice'] - df['averagePrice']) / df['averagePrice']) * 100
            # Color code the returns for visual pop
            def color_returns(val):
                color = '#00ff00' if val > 0 else '#ff4b4b'
                return f'color: {color}; font-weight: bold;'
            st.dataframe(df[['ticker', 'quantity', 'averagePrice', 'currentPrice', 'ppl', 'Return %']].style.map(color_returns, subset=['Return %', 'ppl']), use_container_width=True, hide_index=True)
        else:
            st.info("No active positions held. AI is holding capital in cash.")
    except Exception:
        st.warning("Connecting to broker telemetry...")

with tab2:
    st.subheader("Official Execution Ledger")
    trades = db.get_execution_history(limit=25)
    if trades:
        st.dataframe(pd.DataFrame(trades)[['timestamp', 'asset_ticker', 'action', 'fill_price', 'quantity', 'dynamic_stop_loss']], use_container_width=True, hide_index=True)

with tab3:
    st.subheader("AI Boardroom Deliberation History")
    debates = db.get_recent_debates(limit=15)
    if debates:
        for d in debates:
            with st.expander(f"📌 {d['asset_ticker']} | Consensus: {d['final_consensus']} | Conviction: {d['conviction_score']} ({d['timestamp'][:19]})"):
                st.write("**Technical Agent:**", d['technical_analysis'].get('report'))
                st.write("**Sentiment Driver:**", d['sentiment_analysis'].get('headline'))
                st.write(f"**Risk Veto:** {'Active ⛔' if d['risk_veto'] else 'Cleared ✅'}")

with tab4:
    st.subheader("🧠 Intelligence Attribution (Alpha-Leak Analysis)")
    weights = db.client.table("agent_weights").select("*").execute()
    if weights.data:
        st.dataframe(pd.DataFrame(weights.data), use_container_width=True, hide_index=True)
    
    st.markdown("### 📝 Recent Post-Mortem Reports")
    mortems = db.client.table("post_mortem_analysis").select("*").order("trade_id", desc=True).limit(5).execute()
    if mortems.data:
        for m in mortems.data:
            st.warning(f"Trade ID: {m['trade_id'][:8]} | Agent: {m['attributed_agent']} | Root Cause: {m['root_cause_analysis']}")

st.markdown("---")
if st.button("🔄 Sync Telemetry"):
    st.rerun() if hasattr(st, "rerun") else st.experimental_rerun()