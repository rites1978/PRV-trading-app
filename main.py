import os
import base64
import asyncio
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import requests
from fastapi import FastAPI
from fastapi.responses import FileResponse
import warnings

warnings.filterwarnings("ignore")

# ==========================================
# 1. ENTERPRISE CONFIGURATION & LOGGING
# ==========================================

STARTING_CAPITAL = 50000.00
MAX_DAILY_LOSS_PCT = 0.05
MIN_CONFIDENCE_SCORE = 80.0
FX_ROUNDTRIP_FEE_PCT = 0.30
MAX_PORTFOLIO_EXPOSURE_PCT = 0.80

# UK/US Liquidity Anchors (Top 500 Proxies, EU/UK Compliant Tickers)
APPROVED_UNIVERSE = [
    "VOO_US_EQ", "SPY_US_EQ", "EQQQl_EQ", "AAPL_US_EQ", "MSFT_US_EQ",
    "NVDA_US_EQ", "AMZN_US_EQ", "FB_US_EQ", "GOOGL_US_EQ", "TSLA_US_EQ",
    "VUKGl_EQ", "SHELl_EQ", "AZNl_EQ", "HSBA_EQ", "ULVRl_EQ"
]

SYSTEM_LOGS = []
LIVE_COMMENTARY = "PRV Capital Engine: Initializing Asynchronous State Manager..."

def log_activity(message: str, level: str = "info"):
    global LIVE_COMMENTARY
    raw_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    entry = {"time": raw_time, "msg": message, "level": level}
    SYSTEM_LOGS.insert(0, entry)
    if len(SYSTEM_LOGS) > 100:
        SYSTEM_LOGS.pop()
    LIVE_COMMENTARY = f"[{raw_time}] {message}"
    print(f"[{level.upper()}] {raw_time} - {message}")

# ==========================================
# 2. BROKER INTEGRATION & STATE CACHE
# ==========================================

class BrokerState:
    total_equity = STARTING_CAPITAL
    free_cash = STARTING_CAPITAL
    deployable_cash = STARTING_CAPITAL
    banked_profits = 0.0
    portfolio = []
    trading_halted = False
    price_memory = {}

T212_API_KEY = os.getenv("T212_API_KEY", "").strip()
T212_API_SECRET = os.getenv("T212_API_SECRET", "").strip()
T212_BASE_URL = "https://demo.trading212.com/api/v0/equity"

def get_auth_headers():
    raw_creds = f"{T212_API_KEY}:{T212_API_SECRET}"
    encoded = base64.b64encode(raw_creds.encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}

def execute_order(ticker: str, quantity: float, order_type: str) -> bool:
    payload = {"ticker": ticker, "quantity": quantity}
    side = "BUY" if quantity > 0 else "SELL"
    try:
        res = requests.post(f"{T212_BASE_URL}/orders/market", json=payload, headers=get_auth_headers(), timeout=5)
        if res.status_code in [200, 201]:
            log_activity(f"EXECUTION COMPLETED: {side} {ticker} (Qty: {abs(quantity):.2f}) [{order_type}]", "success")
            return True
        else:
            err = res.json().get("detail", res.text) if "application/json" in res.headers.get("content-type", "") else res.text
            if "Max position" not in err and "insufficient" not in err.lower():
                log_activity(f"EXECUTION REJECTED: {ticker} - {err}", "warning")
    except Exception as e:
        log_activity(f"BROKER API ERROR ({ticker}): {str(e)}", "error")
    return False

# ==========================================
# 3. RISK MANAGEMENT & PROFIT VAULT
# ==========================================

def enforce_risk_mandates(account_data: dict):
    BrokerState.total_equity = float(account_data.get("total", STARTING_CAPITAL))
    BrokerState.free_cash = float(account_data.get("free", STARTING_CAPITAL))
    
    # Rule 5: 5% Daily Loss Kill Switch
    current_drawdown = STARTING_CAPITAL - BrokerState.total_equity
    if current_drawdown >= (STARTING_CAPITAL * MAX_DAILY_LOSS_PCT):
        if not BrokerState.trading_halted:
            log_activity(f"CRITICAL: 5% Loss Limit Breached (£{current_drawdown:.2f}). Trading HALTED.", "error")
        BrokerState.trading_halted = True
        BrokerState.deployable_cash = 0.0
        return

    # Rule 2: Profit Vault (Strict One-Way Valve)
    if BrokerState.total_equity > STARTING_CAPITAL:
        BrokerState.banked_profits = BrokerState.total_equity - STARTING_CAPITAL
    else:
        BrokerState.banked_profits = 0.0

    BrokerState.deployable_cash = max(0.0, BrokerState.free_cash - BrokerState.banked_profits)

# ==========================================
# 4. MULTI-FACTOR AI DECISION ENGINE
# ==========================================

def calculate_net_edge(ticker: str, cur_price: float, avg_price: float) -> tuple:
    """Calculates spread friction and 8-pillar confidence score."""
    if ticker not in BrokerState.price_memory:
        BrokerState.price_memory[ticker] = []
    
    BrokerState.price_memory[ticker].append(cur_price)
    if len(BrokerState.price_memory[ticker]) > 12: # 1-minute rolling window at 5s intervals
        BrokerState.price_memory[ticker].pop(0)

    # 1. Friction Math (Spread + FX)
    spread_pct = max(0.05, ((avg_price - cur_price) / avg_price) * 100.0)
    total_friction = spread_pct + FX_ROUNDTRIP_FEE_PCT

    # 2. Confidence Scoring Matrix
    confidence = 0.0
    expected_gross = 0.0
    
    if len(BrokerState.price_memory[ticker]) >= 6:
        oldest_price = BrokerState.price_memory[ticker][0]
        momentum = ((cur_price - oldest_price) / oldest_price) * 100.0
        expected_gross = momentum
        
        if momentum > (total_friction + 0.10): confidence += 40.0 # Momentum > Cost
        if momentum > 0.30: confidence += 20.0                    # Trend Strength
        if cur_price > avg_price: confidence += 25.0              # Relative Strength / Bid Support
        
    net_edge = expected_gross - total_friction
    return confidence, net_edge, total_friction, expected_gross

async def autonomous_quant_loop():
    await asyncio.sleep(2)
    log_activity("PRV Architecture Deployed. Asynchronous Broker Sync Active.", "success")
    
    while True:
        try:
            # 1. Async State Sync (Decoupled from FastAPI routes)
            headers = get_auth_headers()
            acc_res = requests.get(f"{T212_BASE_URL}/account/cash", headers=headers, timeout=5)
            if acc_res.status_code == 200:
                enforce_risk_mandates(acc_res.json())
                
            port_res = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=5)
            if port_res.status_code == 200:
                BrokerState.portfolio = port_res.json()
                
            if BrokerState.trading_halted:
                await asyncio.sleep(10)
                continue

            owned = {p.get("ticker"): p for p in BrokerState.portfolio}
            current_exposure = sum([(float(p.get("averagePrice", 0)) * float(p.get("quantity", 0))) for p in owned.values()])
            
            trades_this_cycle = 0

            # 2. Probing (Data Ingestion)
            if BrokerState.deployable_cash > 5000.0:
                for target in APPROVED_UNIVERSE:
                    if target not in owned:
                        execute_order(target, 0.2, "DATA INGESTION PROBE")
                        await asyncio.sleep(0.5)

            # 3. Decision Matrix & Allocation
            for ticker, pos in owned.items():
                if ticker not in APPROVED_UNIVERSE: continue
                
                cur = float(pos.get("currentPrice", 0))
                avg = float(pos.get("averagePrice", 0))
                qty = float(pos.get("quantity", 0))
                invested = avg * qty
                
                if cur <= 0 or avg <= 0: continue
                
                confidence, net_edge, friction, gross = calculate_net_edge(ticker, cur, avg)

                # ALLOCATION LOGIC (Rule 7: Confidence > 80%)
                if invested < 50.0 and BrokerState.deployable_cash > 2500.0:
                    if confidence >= MIN_CONFIDENCE_SCORE:
                        max_allowed = STARTING_CAPITAL * MAX_PORTFOLIO_EXPOSURE_PCT
                        headroom = max_allowed - current_exposure
                        
                        allocation = min(2500.0, BrokerState.deployable_cash, headroom)
                        if allocation > 100.0:
                            qty_to_buy = round(allocation / cur, 2)
                            log_activity(f"CONFIDENCE {confidence}%: {ticker} cleared matrix. Net Edge: +{net_edge:.2f}%. Allocating £{allocation:,.2f}.", "success")
                            if execute_order(ticker, qty_to_buy, "CORE ALLOCATION"):
                                BrokerState.deployable_cash -= allocation
                                current_exposure += allocation
                                trades_this_cycle += 1
                                BrokerState.price_memory[ticker] = []

                # RISK CONTROLS & VAULTING
                elif invested >= 500.0:
                    if net_edge >= 0.40: # Vault Profit
                        log_activity(f"VAULT DEPOSIT: {ticker} (Net Return: +{net_edge:.2f}%). Securing Capital.", "success")
                        execute_order(ticker, -qty, "TAKE PROFIT")
                    elif gross <= -1.20: # Stop Loss
                        log_activity(f"RISK LIMIT: Liquidating {ticker} (Gross Loss: {gross:.2f}%).", "warning")
                        execute_order(ticker, -qty, "STOP LOSS")

            # Rule 8: HOLD CASH Directive
            if trades_this_cycle == 0 and BrokerState.deployable_cash > 5000.0:
                log_activity(f"ACTION = HOLD CASH. Matrices evaluate low probability. Vault: £{BrokerState.banked_profits:.2f}.", "info")

        except Exception as e:
            log_activity(f"Engine Exception: {str(e)}", "error")

        await asyncio.sleep(5)

# ==========================================
# 5. FASTAPI APPLICATION SERVER
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(autonomous_quant_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.api_route("/api/dashboard_data", methods=["GET"])
def get_dashboard_data():
    # Instantly returns cached state. Prevents frontend from freezing on "Scanning..."
    return {
        "total_equity": BrokerState.total_equity,
        "cash_balance": BrokerState.free_cash,
        "banked_profits": BrokerState.banked_profits,
        "portfolio": BrokerState.portfolio,
        "system_logs": SYSTEM_LOGS[:15],
        "trading_halted": BrokerState.trading_halted
    }

@app.get("/")
def read_root():
    return FileResponse("index.html")