import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import json
import os
import time
from datetime import datetime

from src.config.settings import settings
from src.database.db import db
from src.brokers.trading212 import broker
from src.data.universe import universe_manager
from src.data.market_data import market_data
from src.portfolio.capital_manager import capital_manager
from src.risk.risk_engine import risk_engine
from src.core.engine import quant_engine

# -------------------------------------------------------------
# 1. Institutional Layout & Custom Dark Theme
# -------------------------------------------------------------
st.set_page_config(
    page_title="PRV Capital | Autonomous Quantitative Terminal",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main-header {
        font-family: 'Helvetica Neue', sans-serif;
        font-weight: 800;
        letter-spacing: -0.5px;
        color: #ffffff;
        margin-bottom: 0px;
    }
    .sub-header {
        font-family: 'Helvetica Neue', sans-serif;
        font-size: 0.95rem;
        color: #90a4ae;
        margin-top: -5px;
        margin-bottom: 20px;
    }
    .vault-card {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 16px;
        border-radius: 10px;
        color: white;
        border: 1px solid #4a90e2;
    }
    .badge-approved {
        background-color: rgba(0, 230, 118, 0.2);
        color: #00e676;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        border: 1px solid #00e676;
    }
    .badge-rejected {
        background-color: rgba(255, 82, 82, 0.2);
        color: #ff5252;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        border: 1px solid #ff5252;
    }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 2. Sidebar: Engine Master Controls
# -------------------------------------------------------------
st.sidebar.markdown("### 🏛️ PRV CAPITAL")
st.sidebar.caption("Autonomous Quantitative Trading System v2.0")

if quant_engine.is_running:
    st.sidebar.success("● ENGINE ACTIVE (AUTONOMOUS)")
    if st.sidebar.button("🛑 STOP ENGINE", use_container_width=True, type="primary"):
        quant_engine.stop()
        st.rerun()
else:
    st.sidebar.error("● ENGINE HALTED (STANDBY)")
    if st.sidebar.button("🚀 ENGAGE ENGINE", use_container_width=True, type="primary"):
        quant_engine.start()
        st.rerun()

st.sidebar.divider()

# Mode Switch
exec_mode = st.sidebar.radio(
    "Execution Protocol",
    options=["🧪 Paper Trading (Simulated)", "⚡ Live Trading (Real Capital)"],
    index=0 if quant_engine.paper_mode else 1
)
quant_engine.paper_mode = ("Paper" in exec_mode)

st.sidebar.divider()
st.sidebar.subheader("🛡️ Risk & Allocation Caps")
st.sidebar.info(f"""
- **Daily Drawdown Limit:** {settings.MAX_DAILY_DRAWDOWN_PCT * 100:.1f}%
- **Max Position Size:** {settings.MAX_POSITION_SIZE_PCT * 100:.1f}% of Core
- **Max Sector Exposure:** {settings.MAX_SECTOR_EXPOSURE_PCT * 100:.1f}%
- **Min Net Reward/Risk:** {settings.MIN_REWARD_RISK_RATIO:.1f}:1
- **Min Confidence:** {settings.MIN_CONFIDENCE_THRESHOLD:.0f}%
""")

# -------------------------------------------------------------
# 3. Live Account & Capital Fetch
# -------------------------------------------------------------
account = broker.get_account_summary()
positions = broker.get_open_positions()

st.markdown('<h1 class="main-header">PRV CAPITAL | QUANTITATIVE EXECUTION PLATFORM</h1>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Institutional-Grade Algorithmic Asset Allocation & Execution System</div>', unsafe_allow_html=True)

if account.get("success"):
    total_nav = account["total_value"]
    available_cash = account["available_cash"]
    invested = account["invested"]
    
    cap_state = capital_manager.get_capital_state(total_nav, invested, available_cash)
    
    # 5-Metric Capital Top Bar
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Portfolio NAV", f"£{cap_state['total_broker_nav']:,.2f}")
    c2.metric("Core Capital (Trading Pool)", f"£{cap_state['core_capital']:,.2f}")
    c3.metric("Active Capital (Invested)", f"£{cap_state['active_capital']:,.2f}")
    c4.metric("Profit Vault (Secured)", f"£{cap_state['profit_vault_balance']:,.2f}", delta=f"{cap_state['profit_vault_balance']:+,.2f} Locked")
    c5.metric("Capital Utilisation", f"{cap_state['capital_utilization_pct']:.1f}%")
else:
    st.error(f"Broker connection error: {account.get('error')}")

st.divider()

# -------------------------------------------------------------
# 4. Multi-Tab Navigation
# -------------------------------------------------------------
tab_overview, tab_scanner, tab_portfolio, tab_audit, tab_history = st.tabs([
    "📊 Capital Deployment & Regime",
    "🧠 Boardroom & AI Scanner",
    "💼 Active Portfolio & Risk",
    "📜 Institutional Audit Trail",
    "💰 Trade History & Profit Vault"
])

# -------------------------------------------------------------
# Tab 1: Capital Deployment & Regime
# -------------------------------------------------------------
with tab_overview:
    st.subheader("🎯 Dynamic Capital Allocation Engine")
    
    sp500_snapshot = market_data.get_market_snapshot("^GSPC")
    sp500_trend = 80.0 if (sp500_snapshot.get("success") and sp500_snapshot["indicators"]["sma_20"] > sp500_snapshot["indicators"]["sma_50"]) else 45.0
    regime, target_pct = capital_manager.determine_market_regime(70.0, sp500_trend)
    
    col_reg1, col_reg2 = st.columns([1, 2])
    with col_reg1:
        st.markdown(f"**Detected Market Regime:** `{regime}`")
        st.markdown(f"**Target Max Allocation Capacity:** `{target_pct * 100:.0f}% of Core Capital`")
        
        target_allocation_val = cap_state["core_capital"] * target_pct
        st.write(f"Target Invested Capital: **£{target_allocation_val:,.2f}**")
        st.write(f"Current Invested Capital: **£{cap_state['active_capital']:,.2f}**")
        
        allowance = max(0.0, target_allocation_val - cap_state['active_capital'])
        st.info(f"💡 **Dynamic Deployment Capacity Remaining:** £{allowance:,.2f}")
        
    with col_reg2:
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=cap_state["capital_utilization_pct"],
            title={'text': "Capital Utilization vs Target Regime Capacity (%)"},
            delta={'reference': target_pct * 100},
            gauge={
                'axis': {'range': [0, 100]},
                'bar': {'color': "#00e676"},
                'steps': [
                    {'range': [0, 20], 'color': "rgba(255,255,255,0.05)"},
                    {'range': [20, 50], 'color': "rgba(255,255,255,0.1)"},
                    {'range': [50, 80], 'color': "rgba(255,255,255,0.15)"}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': target_pct * 100
                }
            }
        ))
        fig_gauge.update_layout(template="plotly_dark", height=280, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_gauge, use_container_width=True)

# -------------------------------------------------------------
# Tab 2: Boardroom & AI Scanner
# -------------------------------------------------------------
with tab_scanner:
    st.subheader("🧠 Multi-Agent Quantitative Boardroom Scanner")
    
    col_sc1, col_sc2 = st.columns([1, 4])
    with col_sc1:
        if st.button("🔄 Execute Quantitative Scan", use_container_width=True):
            with st.spinner("Convening boardroom & evaluating 8-factor models..."):
                res = quant_engine.run_cycle()
                st.success(f"Scan complete. Scanned: {res.get('scanned_count', 0)} assets.")
                st.rerun()

    universe = universe_manager.get_all()
    scan_rows = []
    
    for item in universe:
        sym = item["symbol"]
        yf_sym = item["yf_ticker"]
        t212_sym = item["t212_ticker"]
        is_uk_pence = item.get("is_uk_pence", False)
        
        snap = market_data.get_market_snapshot(yf_sym, is_uk_pence=is_uk_pence)
        if not snap.get("success"):
            continue
            
        p = snap["current_price"]
        conf, factors = ai_scoring.compute_composite_confidence(sym, snap, regime, cap_state["capital_utilization_pct"], 0.10)
        
        scan_rows.append({
            "Symbol": sym,
            "Name": item["name"],
            "Price": f"£{p:.2f}" if item["currency"]=="GBP" else f"${p:.2f}",
            "Confidence": conf,
            "Trend (20%)": factors["trend_strength"],
            "RSI (15%)": factors["relative_strength"],
            "MACD (15%)": factors["momentum"],
            "Volume (15%)": factors["volume_confirmation"],
            "Volatility (10%)": factors["volatility_condition"],
            "Approval": "✅ APPROVED" if conf >= 80.0 else "❌ HOLD CASH"
        })

    df_scanner = pd.DataFrame(scan_rows)
    st.dataframe(df_scanner, use_container_width=True, height=350)
    
    st.divider()
    st.subheader("📈 Quantitative Chart & Indicator Dissection")
    sel_sym = st.selectbox("Inspect Asset:", options=[item["symbol"] for item in universe])
    sel_item = universe_manager.get_by_symbol(sel_sym)
    
    if sel_item:
        sel_snap = market_data.get_market_snapshot(sel_item["yf_ticker"], is_uk_pence=sel_item.get("is_uk_pence", False))
        if sel_snap.get("success"):
            df_chart = sel_snap["dataframe"]
            
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
            fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], name="Candles"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_20'], line=dict(color='#ff9800', width=1.5), name="SMA 20"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_50'], line=dict(color='#29b6f6', width=1.5), name="SMA 50"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['RSI'], line=dict(color='#ab47bc', width=2), name="RSI 14"), row=2, col=1)
            fig.add_hline(y=70, line=dict(color='red', dash='dash'), row=2, col=1)
            fig.add_hline(y=30, line=dict(color='green', dash='dash'), row=2, col=1)
            fig.update_layout(template="plotly_dark", height=500, xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

# -------------------------------------------------------------
# Tab 3: Active Portfolio & Risk
# -------------------------------------------------------------
with tab_portfolio:
    st.subheader("💼 Active Position Risk Matrix")
    if positions and len(positions) > 0:
        pos_data = []
        for p in positions:
            sym = p.get("ticker")
            qty = float(p.get("quantity", 0))
            avg_p = float(p.get("averagePrice", 0))
            cur_p = float(p.get("currentPrice", 0))
            ppl = float(p.get("ppl", 0))
            pnl_pct = ((cur_p - avg_p) / avg_p * 100) if avg_p > 0 else 0
            
            sl_price = avg_p * (1 - settings.DEFAULT_STOP_LOSS_PCT)
            tp_price = avg_p * (1 + settings.DEFAULT_TAKE_PROFIT_PCT)
            
            pos_data.append({
                "Symbol": sym,
                "Shares": qty,
                "Avg Price": f"£{avg_p:.2f}",
                "Current Price": f"£{cur_p:.2f}",
                "Unrealized P&L (£)": f"£{ppl:+.2f}",
                "Return (%)": f"{pnl_pct:+.2f}%",
                "Stop-Loss (-2.5%)": f"£{sl_price:.2f}",
                "Take-Profit (+7.5%)": f"£{tp_price:.2f}"
            })
            
        st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
    else:
        st.info("No active positions currently open.")

# -------------------------------------------------------------
# Tab 4: Institutional Audit Trail
# -------------------------------------------------------------
with tab_audit:
    st.subheader("📜 Immutable Execution & Risk Audit Trail")
    audit_logs = db.get_audit_logs(limit=100)
    if audit_logs:
        st.dataframe(pd.DataFrame(audit_logs), use_container_width=True, height=400)
    else:
        st.info("No audit logs recorded yet.")

# -------------------------------------------------------------
# Tab 5: Trade History & Profit Vault
# -------------------------------------------------------------
with tab_history:
    st.subheader("💰 Realized Trade History & Profit Vault Deposits")
    trades = db.get_trades(limit=100)
    if trades:
        st.dataframe(pd.DataFrame(trades), use_container_width=True)
    else:
        st.info("No executed trades recorded yet.")
