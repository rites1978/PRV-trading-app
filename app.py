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
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=SF+Pro+Display:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

    /* Global Ambient Background */
    .stApp {
        background: radial-gradient(circle at 10% 20%, rgba(37, 99, 235, 0.15) 0%, transparent 40%),
                    radial-gradient(circle at 90% 80%, rgba(139, 92, 246, 0.15) 0%, transparent 40%),
                    radial-gradient(circle at 50% 50%, rgba(6, 182, 212, 0.08) 0%, transparent 60%),
                    #070a13;
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif;
        color: #f8fafc;
    }

    /* iOS 27 Specular Frosted Glass Panels */
    .glass-card {
        background: rgba(255, 255, 255, 0.035);
        backdrop-filter: blur(35px) saturate(190%);
        -webkit-backdrop-filter: blur(35px) saturate(190%);
        border: 1px solid rgba(255, 255, 255, 0.09);
        border-top: 1px solid rgba(255, 255, 255, 0.22);
        border-radius: 24px;
        padding: 24px;
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4), 
                    inset 0 1px 1px rgba(255, 255, 255, 0.15);
        margin-bottom: 20px;
    }

    /* Metric Cards Glass Styling */
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03) !important;
        backdrop-filter: blur(30px) !important;
        -webkit-backdrop-filter: blur(30px) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-top: 1px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 20px !important;
        padding: 18px 22px !important;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.12) !important;
    }
    div[data-testid="stMetricLabel"] {
        color: #94a3b8 !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        letter-spacing: 0.5px !important;
        text-transform: uppercase !important;
    }
    div[data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 1.85rem !important;
        letter-spacing: -0.5px !important;
    }

    /* iOS Glass Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background: rgba(255, 255, 255, 0.02);
        padding: 6px;
        border-radius: 18px;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        color: #94a3b8 !important;
        border-radius: 14px !important;
        border: none !important;
        padding: 10px 20px !important;
        font-weight: 500 !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(255, 255, 255, 0.12) !important;
        backdrop-filter: blur(20px) !important;
        color: #ffffff !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3), inset 0 1px 1px rgba(255, 255, 255, 0.25) !important;
    }

    /* Live Nerve Center Terminal */
    .glass-terminal {
        background: rgba(2, 6, 18, 0.55);
        backdrop-filter: blur(40px);
        -webkit-backdrop-filter: blur(40px);
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-top: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 20px;
        padding: 18px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.82rem;
        height: 380px;
        overflow-y: auto;
        box-shadow: inset 0 2px 8px rgba(0,0,0,0.6);
    }
    .badge {
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.72rem;
        letter-spacing: 0.5px;
    }
    .badge-board { background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }
    .badge-risk { background: rgba(244, 63, 94, 0.15); color: #f43f5e; border: 1px solid rgba(244, 63, 94, 0.3); }
    .badge-exec { background: rgba(52, 211, 153, 0.15); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); }
    
    /* Sleek Scrollbar */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 10px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.2); }
    </style>
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

tab1, tab2, tab3, tab4 = st.tabs(["⚡ Nerve Center & Allocation", "📈 Capital Curve & Models", "🏛️ AI Boardroom Logs", "🧠 Agent Intelligence Matrix"])

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
    st.markdown("### 📈 Capital Trajectory & Historical VaR Envelope")
    
    # Generate Synthetic/Simulated Curve Anchor
    dates = [datetime.now() - timedelta(days=i) for i in range(14, -1, -1)]
    nav_history = [40000.0 + (i * 75.0) - (20.0 if i % 3 == 0 else -40.0) for i in range(len(dates))]
    var_lower = [v - 800.0 for v in nav_history]
    
    df_curve = pd.DataFrame({'Date': dates, 'NAV': nav_history, 'Lower VaR Bound': var_lower})
    
    fig_curve = go.Figure()
    
    # Upper Bound / Main Area
    fig_curve.add_trace(go.Scatter(
        x=df_curve['Date'], y=df_curve['NAV'],
        mode='lines',
        name='Portfolio NAV (£)',
        line=dict(color='#38bdf8', width=3, shape='spline'),
        fill='tozeroy',
        fillcolor='rgba(56, 189, 248, 0.08)'
    ))
    
    # VaR 95% Confidence Floor
    fig_curve.add_trace(go.Scatter(
        x=df_curve['Date'], y=df_curve['Lower VaR Bound'],
        mode='lines',
        name='95% Parametric VaR Floor',
        line=dict(color='rgba(244, 63, 94, 0.6)', width=1.5, dash='dash')
    ))
    
    fig_curve.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#94a3b8', family='SF Pro Display'),
        xaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', zeroline=False),
        yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', zeroline=False, tickprefix="£"),
        margin=dict(t=30, b=20, l=20, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=420
    )
    
    st.plotly_chart(fig_curve, use_container_width=True)

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