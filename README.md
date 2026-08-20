# 🏛️ PRV Capital | Autonomous Quantitative Intelligence Desk

PRV Capital is an institutional-grade, multi-agent autonomous trading system. It integrates global market scanning, macro-regime hedging, and AI-driven boardroom deliberations to execute trades on Trading 212 with high-conviction alpha.

## 🚀 System Architecture
The system operates as a continuous daemon, processing data through a specialized pipeline:

1. **Macro Hedging Engine:** Analyzes global benchmarks (SPY) against moving averages to detect bear regimes.
2. **Global Screener:** Scans US and UK equities for momentum/oversold conditions (RSI/SMA).
3. **AI Boardroom:** Multi-agent evaluation (Technical Agent + Sentiment Agent) to reach a consensus trade.
4. **Fee Intelligence Layer:** Calculates net-alpha by subtracting real-time FX conversion (0.15%) and spread costs before approval.
5. **Visual Trader Engine:** Executes orders via Trading 212 API and logs telemetry to Supabase.

## 🧠 Core Intelligence Modules
* **Daemon Runner:** 24/7 background worker maintaining the system pulse.
* **Risk Guard:** Enforces stop-loss parameters and correlation limits.
* **Nerve Center:** Real-time logging of agent deliberations and trade executions.

## 📊 Dashboard Visuals (iOS 27 Glass)
The frontend is built with Streamlit using a custom "Liquid Glass" design system, featuring:
* Interactive Plotly growth curves.
* Real-time Agent Confidence Matrix.
* Frosted glass execution receipts.

## ⚙️ Operational Logic (Rules.md)
* **Execution:** Only executes trades if `Net Alpha > 0.2%` after accounting for FX fees and spreads.
* **Market Regime:** Automatically shifts capital to inverse ETFs (e.g., `QQQS.L`) if `SPY` drops below its 200-day moving average.
* **Env Management:** Seamless switching between `demo` and `live` via `.env` configuration.

## 🛠️ Infrastructure
* **Frontend:** Streamlit + Plotly
* **Database:** Supabase (PostgreSQL)
* **Brokerage:** Trading 212 API
* **Cloud Execution:** Render Background Worker

---
*Built for autonomous market dominance.*