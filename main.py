from fastapi import FastAPI
from fastapi.responses import FileResponse
import asyncio
from datetime import datetime, timezone
import os
import requests
import base64
import warnings
from contextlib import asynccontextmanager
warnings.filterwarnings("ignore")

app = FastAPI()

# --- SYSTEM CONFIGURATION & STATE ---
SYSTEM_LOGS = []
LIVE_COMMENTARY = "PRV Capital Engine: Dynamic Allocation Engine Online."

STARTING_CAPITAL = 50000.00
MAX_DAILY_LOSS_PCT = 0.05
FX_ROUNDTRIP_FEE_PCT = 0.30
MAX_PORTFOLIO_EXPOSURE_PCT = 0.80  # Max 80% capital deployed at any time

CACHED_PORTFOLIO = []
CACHED_ACCOUNT = {"total": STARTING_CAPITAL, "free": STARTING_CAPITAL}
BANKED_PROFITS = 0.00
TRADING_HALTED = False
PRICE_MEMORY = {}

# UK/US Liquidity Anchors
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
            
            # Risk Control: 5% Daily Loss Kill Switch
            max_allowed_loss = STARTING_CAPITAL * MAX_DAILY_LOSS_PCT
            current_drawdown = STARTING_CAPITAL - total_eq
            if current_drawdown >= max_allowed_loss:
                if not TRADING_HALTED:
                    log_activity(f"CRITICAL: 5% Loss Limit Reached. Trading HALTED. Drawdown: £{current_drawdown:.2f}", "error")
                TRADING_HALTED = True
            
            # Risk Control: Profit Vault
            if total_eq > STARTING_CAPITAL:
                BANKED_PROFITS = total_eq - STARTING_CAPITAL
            else:
                BANKED_PROFITS = 0.00
                
        res_port = requests.get(f"{T212_BASE_URL}/portfolio", headers=headers, timeout=10)
        if res_port.status_code == 200:
            CACHED_PORTFOLIO = res_port.json()
    except Exception as e:
        log_activity(f"State Sync Error: {str(e)}", "error")

def calculate_dynamic_allocation(deployable_cash: float, current_exposure: float, alpha_edge: float) -> float:
    """
    Dynamically allocates capital based on edge strength.
    Preserves 20% minimum cash at all times.
    """
    max_allowed_exposure = STARTING_CAPITAL * MAX_PORTFOLIO_EXPOSURE_PCT
    available_allocation_headroom = max_allowed_exposure - current_exposure
    
    if available_allocation_headroom <= 0:
        return 0.0

    # Sizing matrix based on Alpha Edge magnitude
    if alpha_edge > 0.50:
        target_allocation = deployable_cash * 0.30  # Hyper-conviction: 30% of cash
    elif alpha_edge > 0.25:
        target_allocation = deployable_cash * 0.20  # Strong conviction: 20% of cash
    elif alpha_edge > 0.10:
        target_allocation = deployable_cash * 0.10  # Baseline edge: 10% of cash
    else:
        return 0.0
        
    return min(target_allocation, available_allocation_headroom)

async def prv_quantitative_engine():
    await asyncio.sleep(2)
    log_activity("PRV Capital Engine Online. Dynamic Allocation Matrix Active.", "success")
    
    while True:
        sync_broker_state()
        
        if TRADING_HALTED:
            await asyncio.sleep(60)
            continue

        owned_tickers = {pos.get("ticker"): pos for pos in CACHED_PORTFOLIO} if CACHED_PORTFOLIO else {}
        
        raw_free_cash = float(CACHED_ACCOUNT.get("free", 0))
        deployable_cash = max(0.0, raw_free_cash - BANKED_PROFITS)
        
        current_total_exposure = sum([(float(pos.get("averagePrice", 0)) * float(pos.get("quantity", 0))) for pos in owned_tickers.values()])

        # SEEDING (Live Bid/Ask Matrix)
        if deployable_cash > 5000.0:
            for target in APPROVED_UNIVERSE:
                if target not in owned_tickers:
                    execute_live_order(target, 0.05, "DATA PROBE")
                    await asyncio.sleep(0.5)

        # DYNAMIC ALLOCATION & PROFIT HARVESTING
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
                # Expand memory to 30 ticks (5-minute rolling window at 10s intervals) to capture true trend
                if len(PRICE_MEMORY[ticker]) > 30: PRICE_MEMORY[ticker].pop(0)
                
                live_spread_pct = max(0.05, ((avg_price - cur_price) / avg_price) * 100.0)
                total_friction_pct = live_spread_pct + FX_ROUNDTRIP_FEE_PCT
                
                # ENTRY LOGIC (5-minute window maturation)
                if invested < 50.0 and len(PRICE_MEMORY[ticker]) >= 15:
                    oldest_price = PRICE_MEMORY[ticker][0]
                    momentum_pct = ((cur_price - oldest_price) / oldest_price) * 100.0
                    
                    alpha_edge = momentum_pct - total_friction_pct
                    
                    if alpha_edge > 0.10:
                        allocation = calculate_dynamic_allocation(deployable_cash, current_total_exposure, alpha_edge)
                        if allocation > 100.0:
                            target_qty = round(allocation / cur_price, 2)
                            log_activity(f"DYNAMIC SCALING: {ticker}. Edge: +{alpha_edge:.2f}%. Allocating £{allocation:,.2f}.", "success")
                            execute_live_order(ticker, target_qty, "CORE ALLOCATION")
                            deployable_cash -= allocation
                            current_total_exposure += allocation
                            trades_executed += 1
                            PRICE_MEMORY[ticker] = [] # Reset after scaling

                # RISK & EXIT LOGIC (For Core Positions)
                elif invested >= 500.0:
                    gross_ret_pct = ((cur_price - avg_price) / avg_price) * 100.0
                    net_ret_pct = gross_ret_pct - total_friction_pct
                    
                    if net_ret_pct >= 0.60:
                        log_activity(f"HARVESTING ALPHA: {ticker} (Net: +{net_ret_pct:.2f}%). Vaulting Cash.", "success")
                        execute_live_order(ticker, -qty, "TAKE PROFIT")
                        
                    elif gross_ret_pct <= -1.50:
                        log_activity(f"RISK LIMIT ENFORCED: Liquidating {ticker} ({gross_ret_pct:.2f}%).", "warning")
                        execute_live_order(ticker, -qty, "STOP LOSS")

        # HOLD CASH DIRECTIVE
        if trades_executed == 0 and deployable_cash > 5000.0:
            log_activity(f"Hold Cash Directive Active. Deployable Cash: £{deployable_cash:,.2f}. Awaiting Alpha.", "info")

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