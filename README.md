# PRV Capital • Autonomous Quant Trading Desk

An institutional-grade, Apple-styled autonomous trading and market-scouring terminal built on **FastAPI**, **Supabase**, and the **Trading 212 API**, deployed live on **Render**.

---

## 🏗️ System Architecture

1. **Autonomous Market-Scouring Agent (`main.py`)**
   - Runs continuously in the background via asynchronous Python daemons (`asyncio`).
   - Dynamically pulls and screens a broad market universe (S&P 500 liquid equities) every 15 minutes.
   - Evaluates quantitative price action rules (intraday momentum surges and oversold dips) to make independent buy/sell decisions without manual intervention.

2. **Brokerage API Gateway (`Trading 212`)**
   - Automatically routes AI-generated signals straight to the Trading 212 execution endpoint (supports both Demo/Paper and Live environments).
   - Features graceful fallback simulation if API credentials are absent.

3. **Persistent Data Storage (`Supabase`)**
   - **Trades Table (`trades`):** Stores the audit trail of every autonomous trade executed by the scouter (Ticker, Shares, Side, Price, Timestamp).
   - **Watchlist Table (`friend_watchlist`):** Tracks custom symbols and investment theses injected manually via the user interface.

4. **Interface & Telemetry**
   - Built with high-end glassmorphic design principles, dynamic SVG data grids, light/dark mode switching, and a live terminal activity feed showing the AI's real-time decision-making logs.

---

## ⚙️ Environment Configuration

To run the application and execute live trades, the following environment variables must be configured on your hosting provider (Render):

- `SUPABASE_URL`: Your Supabase project API URL.
- `SUPABASE_KEY`: Your Supabase public/service role key.
- `T212_API_KEY`: Your Trading 212 API authorization token.
- `T212_BASE_URL`: `https://demo.trading212.com/api/v0/equity` (Paper) or `https://live.trading212.com/api/v0/equity` (Live).

---

## 🚀 Deployment Specifications

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Runtime:** Python 3.14 (Uvicorn ASGI Server)
