import streamlit as st
import pandas as pd
import requests
import os
from dotenv import load_dotenv
from db_manager import db

load_dotenv()
API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")

st.set_page_config(
    page_title="PRV Capital | Institutional Command",
    page_icon="🏛️",
    layout="wide"
)

# Dark theme styling
st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; color: #f3f4f6; }
    div[data-testid="stMetric"] { background-color: #161e2e; border: 1px solid #1f2937; border-radius: 8px; }
    .stTabs [data-baseweb="tab"] { background-color: #161e2e; color: #9ca3af; border: 1px solid #1f2937; }
    .stTabs [aria-selected="true"] { background-color: #2563eb !important; color: #ffffff !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🏛️ PRV CAPITAL MANAGEMENT")
st.caption("Autonomous Quantitative Intelligence Desk • Cloud Synchronized")

tab1, tab2, tab3, tab4 = st.tabs(["💼 Portfolio & NAV", "⚡ Execution Ledger", "🏛️ AI Boardroom Transcripts", "🧠 Agent Intelligence"])

with tab1:
    st.subheader("Fund Performance & Risk Console")
    telemetry = db.get_latest_telemetry()
    if telemetry:
        c1, c2, c3 = st.columns(3)
        c1.metric("Portfolio NAV", f"£{float(telemetry['total_nav']):,.2f}")
        c2.metric("Free Cash", f"£{float(telemetry['free_cash']):,.2f}")
        c3.metric("Est. 95% Daily VaR", f"£{float(telemetry['portfolio_var_95'] or 0):,.2f}")
    
    st.markdown("---")
    st.markdown("### 🛡️ Risk Parameters")
    try:
        telemetry = db.get_latest_telemetry()
        drawdown = float(telemetry.get('current_drawdown_pct', 0.0))
        
        risk_color = "🟢" if drawdown > -0.05 else "🟡" if drawdown > -0.10 else "🔴"
        st.metric("Current Portfolio Drawdown", f"{drawdown:.2f}%")
        st.markdown(f"**Risk Status:** {risk_color} System operating within Volatility-Adjusted parameters.")
    except Exception:
        st.info("Risk telemetry recalibrating...")

    st.markdown("---")
    st.subheader("Active Positions (Broker Telemetry)")
    try:
        port_res = requests.get("https://demo.trading212.com/api/v0/equity/portfolio", auth=(API_KEY, API_SECRET), timeout=5)
        if port_res.status_code == 200 and port_res.json():
            df = pd.DataFrame(port_res.json())
            df['Return %'] = ((df['currentPrice'] - df['averagePrice']) / df['averagePrice']) * 100
            st.dataframe(df[['ticker', 'quantity', 'averagePrice', 'currentPrice', 'ppl', 'Return %']], use_container_width=True, hide_index=True)
        else:
            st.info("No active positions held. AI is holding capital in cash.")
    except Exception:
        st.warning("Connecting to broker telemetry...")

with tab2:
    st.subheader("Official Execution Ledger (PostgreSQL)")
    trades = db.get_execution_history(limit=25)
    if trades:
        st.dataframe(pd.DataFrame(trades)[['timestamp', 'asset_ticker', 'action', 'fill_price', 'quantity', 'dynamic_stop_loss']], use_container_width=True, hide_index=True)
    else:
        st.info("No executions recorded yet. Standing by for high-conviction orders.")

with tab3:
    st.subheader("AI Boardroom Deliberation History")
    debates = db.get_recent_debates(limit=15)
    if debates:
        for d in debates:
            with st.expander(f"📌 {d['asset_ticker']} | Consensus: {d['final_consensus']} | Conviction: {d['conviction_score']} ({d['timestamp'][:19]})"):
                st.write("**Technical Agent:**", d['technical_analysis'].get('report'))
                st.write("**Sentiment Driver:**", d['sentiment_analysis'].get('headline'))
                st.write(f"**Risk Veto:** {'Active ⛔' if d['risk_veto'] else 'Cleared ✅'}")
    else:
        st.info("No debate transcripts available.")

if st.button("🔄 Sync Telemetry"):
    st.rerun() if hasattr(st, "rerun") else st.experimental_rerun()

with tab1:
    st.subheader("Fund Performance & Risk Console")
    # ... existing NAV/Cash metrics ...
    
    st.markdown("### 🛡️ Risk Parameters")
    # Calculate Drawdown from Database
    try:
        telemetry = db.get_latest_telemetry()
        drawdown = float(telemetry['current_drawdown_pct'])
        
        # Color-coded risk status
        risk_color = "🟢" if drawdown > -0.05 else "🟡" if drawdown > -0.10 else "🔴"
        st.metric("Current Portfolio Drawdown", f"{drawdown:.2f}%", delta_color="inverse")
        st.markdown(f"**Risk Status:** {risk_color} System operating within Volatility-Adjusted parameters.")
    except:
        st.info("Risk telemetry recalibrating...")
with tab4: # Add this to your st.tabs list in app.py
    st.subheader("🧠 Intelligence Attribution (Alpha-Leak Analysis)")
    st.markdown("Real-time agent confidence weights. If an agent performs poorly, its voting power is automatically throttled.")
    
    weights = db.client.table("agent_weights").select("*").execute()
    if weights.data:
        df_weights = pd.DataFrame(weights.data)
        st.dataframe(df_weights, use_container_width=True, hide_index=True)
    
    st.markdown("### 📝 Recent Post-Mortem Reports")
    mortems = db.client.table("post_mortem_analysis").select("*").order("trade_id", desc=True).limit(5).execute()
    if mortems.data:
        for m in mortems.data:
            st.warning(f"Trade ID: {m['trade_id'][:8]} | Agent: {m['attributed_agent']} | Root Cause: {m['root_cause_analysis']}")
    else:
        st.info("System currently operating at high confidence. No major alpha-leaks detected.")