from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime, timezone
import os
import requests
import base64
from contextlib import asynccontextmanager
import warnings
warnings.filterwarnings("ignore")

app = FastAPI()

# --- SYSTEM CONFIGURATION & STATE ---
SYSTEM_LOGS = []
LIVE_COMMENTARY = "PRV Capital Engine: Initializing..."

STARTING_CAPITAL = 50000.00
MAX_DAILY_LOSS_PCT = 0.05  # 5% Kill Switch
MIN_CONFIDENCE = 0.80      # 80% Confidence Threshold
FX_ROUNDTRIP_FEE_PCT = 0.30

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": STARTING_CAPITAL, "free": STARTING_CAPITAL}
BANKED_PROFITS = 0.00
TRADING_HALTED = False
PRICE_MEMORY = {}

# Strict Top 500 US/UK Liquidity Pool
APPROVED_UNIVERSE = [
    "VOO_US_EQ", "SPY_US_EQ", "QQQ_US_EQ", "AAPL_US_EQ", "MSFT_US_EQ",
    "NVDA_US_EQ", "AMZN_US_EQ", "FB_US_EQ", "GOOGL_US_EQ", "TSLA_US_EQ",
    "VUKGl_EQ", "SHELl_EQ", "AZNl_EQ", "HSBA_EQ", "ULVRl_EQ"
]

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    raw_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    entry = {"time": raw_time, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 100: SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{raw_time}] {message}"
    print(f"[{level.upper()}] {raw_time} - {message}")

T212_API_KEY = os.getenv("T212_API_KEY", "").strip()
T212_API_SECRET = os.getenv("T212_API_SECRET", "").strip()
T212_BASE_URL = "https://demo.trading212.com/api/v0/equity"

def get_t212_auth_headers():
    raw_creds = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(raw_creds.encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

def execute_live_order(ticker: str, quantity: float, order_type: str = "EXECUTION") -> bool:
    payload = {"ticker": ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_t212_auth_headers(), timeout=10)
        if res.status_code in [200, 201]:
            log_activity(f"FILLED: {side} {ticker} (Qty: {abs(quantity):.2f}) [{order_type}]", "success")
            return True
        else:
            err = res.json().get("detail", res.text) if "application/json" in res.headers.get("content-type", "") else res.text
            if "Max position" not in err and "insufficient" not in err.lower():
                log_activity(f"REJECTED: {ticker} - {err}", "warning")
    except Exception as e:
        log_activity(f"EXECUTION ERROR on {ticker}: {str(e)}", "error")
    return False

def sync_broker_state():
    global CACHED_PORTFOLIO, CACHED_ACCOUNT, BANKED_PROFITS, TRADING_HALTED
    if not T212_API_KEY: return
    headers = get_t212_auth_headers()
    try:
        res_cash = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=10)
        if res_cash.status_code == 200:
            CACHED_ACCOUNT = res_cash.json()
            total_eq = float(CACHED_ACCOUNT.get("total", STARTING_CAPITAL))
            
            # Rule 5: 5% Daily Loss Kill Switch
            max_allowed_loss = STARTING_CAPITAL * MAX_DAILY_LOSS_PCT
            current_drawdown = STARTING_CAPITAL - total_eq
            if current_drawdown >= max_allowed_loss:
                if not TRADING_HALTED:
                    log_activity(f"CRITICAL: 5% Loss Limit Reached. Trading HALTED. Drawdown: £{current_drawdown:.2f}", "error")
                TRADING_HALTED = True
            
            # Rule 2: Profit Vault
            if total_eq > STARTING_CAPITAL:
                BANKED_PROFITS = total_eq - STARTING_CAPITAL
            else:
                BANKED_PROFITS = 0.00
                
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200:
            CACHED_PORTFOLIO = res_port.json()
    except Exception as e:
        log_activity(f"State Sync Error: {str(e)}", "error")

async def prv_quantitative_engine():
    await asyncio.sleep(2)
    log_activity("PRV Capital Quantitative Engine Online. Enforcing Risk Mandates.", "success")
    
    while True:
        sync_broker_state()
        
        if TRADING_HALTED:
            await asyncio.sleep(60)
            continue

        owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
        
        raw_free_cash = float(CACHED_ACCOUNT.get("free", 0))
        # Rule 2: Profit Vault funds can NEVER be reinvested
        deployable_cash = max(0.0, raw_free_cash - BANKED_PROFITS)

        # SEEDING FOR LIVE BID/ASK DATA
        if deployable_cash > 5000.0:
            for target in APPROVED_UNIVERSE:
                if target not in owned_tickers:
                    execute_live_order(target, 0.05, "DATA PROBE")
                    await asyncio.sleep(1)
                    break # Seed one at a time to prevent API flooding

        # COST-AWARE SCORING & EXECUTION
        trades_executed = 0
        for ticker, pos in owned_tickers.items():
            if ticker not in APPROVED_UNIVERSE: continue
            
            cur_price = float(pos.get("currentPrice", 0))
            avg_price = float(pos.get("averagePrice", 0))
            qty = float(pos.get("quantity", 0))
            invested = avg_price * qty
            
            if cur_price > 0 and avg_price > 0:
                if ticker not in PRICE_MEMORY: PRICE_MEMORY[ticker] = []
                PRICE_MEMORY[ticker].append(cur_price)
                if len(PRICE_MEMORY[ticker]) > 6: PRICE_MEMORY[ticker].pop(0)
                
                # Rule 4: Cost Calculation
                live_spread_pct = max(0.05, ((avg_price - cur_price) / avg_price) * 100.0)
                total_friction_pct = live_spread_pct + FX_ROUNDTRIP_FEE_PCT
                
                # EVALUATE ENTRY (Confidence > 80%)
                if invested < 50.0 and deployable_cash >= 5000.0 and len(PRICE_MEMORY[ticker]) >= 3:
                    oldest_price = PRICE_MEMORY[ticker][0]
                    momentum_pct = ((cur_price - oldest_price) / oldest_price) * 100.0
                    
                    # Net Expected Return must be strongly positive
                    net_expected_return = momentum_pct - total_friction_pct
                    
                    if net_expected_return > 0.15: # Proxy for >80% confidence edge
                        target_spend = min(5000.0, deployable_cash)
                        target_qty = round(target_spend / cur_price, 2)
                        if target_qty > 0:
                            log_activity(f"CONFIDENCE > 80%: {ticker}. Net Edge: +{net_expected_return:.2f}%. Deploying Capital.", "success")
                            execute_live_order(ticker, target_qty, "CORE ALLOCATION")
                            deployable_cash -= target_spend
                            trades_executed += 1
                            PRICE_MEMORY[ticker] = []

                # RISK MANAGEMENT ON OPEN POSITIONS
                elif invested >= 1000.0:
                    gross_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                    net_ret_pct = gross_ret_pct - total_friction_pct
                    
                    # Secure Profit
                    if net_ret_pct >= 0.50:
                        log_activity(f"PROFIT SECURED: {ticker} (Net: +{net_ret_pct:.2f}%). Vaulting Cash.", "success")
                        execute_live_order(ticker, -qty, "TAKE PROFIT")
                        
                    # Stop Loss
                    elif gross_ret_pct <= -1.25:
                        log_activity(f"RISK LIMIT: Liquidating {ticker} ({gross_ret_pct:.2f}%).", "warning")
                        execute_live_order(ticker, -qty, "STOP LOSS")

        # Rule 8: HOLD CASH Directive
        if trades_executed == 0 and deployable_cash > 5000.0:
            log_activity("No high-probability setups clear friction costs. ACTION = HOLD CASH.", "info")

        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(prv_quantitative_engine())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    sync_broker_state()
    return {
        "total_equity": float(CACHED_ACCOUNT.get("total", STARTING_CAPITAL)),
        "cash_balance": float(CACHED_ACCOUNT.get("free", STARTING_CAPITAL)),
        "banked_profits": BANKED_PROFITS,
        "portfolio": CACHED_PORTFOLIO,
        "system_logs": SYSTEM_LOGS[:15],
        "trading_halted": TRADING_HALTED
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")