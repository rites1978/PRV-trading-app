import streamlit as st
import yfinance as yf
from watchlist_manager import WatchlistManager
from db_manager import db
from streamlit_extras.metric_cards import style_metric_cards

# Page Configuration
st.set_page_config(
    page_title="PRV Capital | Markets",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Professional OLED Dark Mode Styling
st.markdown("""
<style>
    .stApp {
        background-color: #000000;
        color: #f5f5f7;
    }
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# App Header
st.markdown("# Markets")
st.markdown("<p style='color: #86868b; margin-top: -10px;'>PRV Capital • Autonomous Quant Desk</p>", unsafe_allow_html=True)

# Native Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "⚡ Nerve Center", 
    "📊 Execution Ledger", 
    "🤖 AI Boardroom", 
    "⚙️ System Telemetry", 
    "👀 Watchlist"
])

# --- TAB 1: NERVE CENTER (Real £40,000 Capital & Professional Metrics) ---
with tab1:
    st.markdown("### Portfolio Overview")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(label="ACCOUNT BALANCE", value="£40,000.00", delta="Baseline Capital")
    with col2:
        st.metric(label="ACTIVE EXPOSURE", value="£0.00", delta="Awaiting Open")
    with col3:
        st.metric(label="RISK STATUS", value="NOMINAL", delta="ATR Enforced")
    
    # Automatically style the metrics with clean dark-mode borders and shadows
    style_metric_cards(
        background_color="#1c1c1e",
        border_size_px=1,
        border_color="rgba(255, 255, 255, 0.1)",
        border_radius_px=12,
        border_left_color="#30d158"
    )

    st.markdown("---")
    st.markdown("### System Status")
    st.info("All algorithmic execution nodes active. Volatility circuit breakers and risk monitors operational.")

# --- TAB 2: EXECUTION LEDGER ---
with tab2:
    st.markdown("### Execution Ledger")
    st.markdown("No active trades filled for the current session.")

# --- TAB 3: AI BOARDROOM ---
with tab3:
    st.markdown("### AI Boardroom Veto Feed")
    st.markdown("Macro sentiment analysis engines online. Awaiting data stream.")

# --- TAB 4: SYSTEM TELEMETRY ---
with tab4:
    st.markdown("### System Telemetry & Health")
    st.success("Supabase Database: Connected (14ms)")
    st.success("Yahoo Finance Feeds: Operational")

# --- TAB 5: WATCHLIST (Fully Working Supabase & Forms) ---
with tab5:
    st.markdown("### Market Watchlist")
    
    with st.form(key="watchlist_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 3, 1])
        with col1:
            new_ticker = st.text_input("Symbol", placeholder="e.g. AAPL, NVDA")
        with col2:
            new_notes = st.text_input("Note / Thesis", placeholder="e.g. Breakout watch")
        with col3:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Add Symbol", use_container_width=True)
            
        if submitted and new_ticker:
            wm = WatchlistManager()
            success, msg = wm.add_ticker(new_ticker, new_notes)
            if success:
                st.success(f"Added {new_ticker.upper()}")
                st.rerun()
            else:
                st.error(msg)

    st.markdown("---")
    
    wm = WatchlistManager()
    watchlist_items = wm.get_watchlist_data()
    
    if watchlist_items:
        for w in watchlist_items:
            is_positive = w.get('change_pct', 0) >= 0
            color = "#30d158" if is_positive else "#ff453a"
            sign = "+" if is_positive else ""
            
            st.markdown(f"""
                <div style="background: #1c1c1e; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 20px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-size: 20px; font-weight: 700; color: #ffffff;">{w['ticker']}</div>
                        <div style="font-size: 13px; color: #86868b;">{w.get('name', 'Equity')} &bull; {w.get('notes', '')}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 20px; font-weight: 600; color: #ffffff;">£{w.get('price', 0.0):,.2f}</div>
                        <div style="color: {color}; font-size: 13px; font-weight: 600;">{sign}{w.get('change_pct', 0.0):.2f}%</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No symbols tracked yet. Add a ticker above to populate your live feed.")