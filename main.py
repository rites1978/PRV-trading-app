import os
import time
import asyncio
from datetime import datetime, timezone, time as dtime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# Load credentials from any environment variable standard
os.environ["TRADING212_API_KEY"] = os.getenv("TRADING212_API_KEY") or os.getenv("T212_API_KEY", "")
os.environ["TRADING212_API_SECRET"] = os.getenv("TRADING212_API_SECRET") or os.getenv("T212_API_SECRET", "")

from src.config.settings import settings
from src.core.engine import quant_engine
from src.portfolio.capital_manager import capital_manager
from src.portfolio.dust_cleaner import dust_cleaner
from src.brokers.trading212 import broker
from src.database.db import db
from src.risk.risk_engine import risk_engine

CACHE = {
    "last_sync": 0.0,
    "account": {
        "total_value": settings.STARTING_CAPITAL,
        "available_cash": settings.STARTING_CAPITAL,
        "invested": 0.0,
        "currency": "GBP"
    },
    "positions": []
}

def is_uk_market_open() -> bool:
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:
        return False
    current_time = now_utc.time()
    return dtime(8, 0) <= current_time <= dtime(16, 30)

def is_us_market_open() -> bool:
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:
        return False
    current_time = now_utc.time()
    return dtime(14, 30) <= current_time <= dtime(21, 0)

def sync_broker_data(force: bool = False):
    """Synchronize with broker with rate-limiting protection & persistent caching."""
    now = time.time()
    if not force and (now - CACHE["last_sync"]) < 4.0:
        return CACHE["account"], CACHE["positions"]

    try:
        acc = broker.get_account_summary()
        if acc.get("success"):
            CACHE["account"]["total_value"] = float(acc.get("total_value", CACHE["account"]["total_value"]))
            CACHE["account"]["available_cash"] = float(acc.get("available_cash", CACHE["account"]["available_cash"]))
            CACHE["account"]["invested"] = float(acc.get("invested", CACHE["account"]["invested"]))
            CACHE["account"]["currency"] = acc.get("currency", "GBP")

        pos = broker.get_open_positions()
        if isinstance(pos, list):
            CACHE["positions"] = pos

        CACHE["last_sync"] = now
    except Exception as e:
        print(f"[Broker Sync Error] {e}")

    return CACHE["account"], CACHE["positions"]

@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_broker_data(force=True)
    quant_engine.start()
    yield
    quant_engine.stop()

app = FastAPI(
    title="PRV Capital Autonomous AI Trading Floor",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return FileResponse("index.html")

@app.get("/api/dashboard_data")
def get_dashboard_data():
    account, positions = sync_broker_data()
    
    total_equity = account["total_value"]
    available_cash = account["available_cash"]
    invested = account["invested"]
    
    cap_state = capital_manager.get_capital_state(total_equity, invested, available_cash)
    regime, target_pct = capital_manager.determine_market_regime(70.0, 75.0)
    
    # Audit logs for UI stream
    audit_records = db.get_audit_logs(limit=30)
    formatted_logs = []
    for log in audit_records:
        ts = log.get("timestamp", "")
        time_part = ts.split(" ")[-1] if " " in ts else ts
        evt = log.get("event_type", "INFO")
        sym = log.get("symbol", "")
        reason = log.get("trade_reason", "")
        
        level = "success" if "BUY" in evt or "PROFIT" in evt else ("error" if "VETO" in evt or "CIRCUIT" in evt else ("warning" if "SELL" in evt else "info"))
        msg = f"{evt} ({sym}): {reason}" if sym else f"{evt}: {reason}"
        formatted_logs.append({"time": time_part, "msg": msg, "level": level})

    if not formatted_logs:
        now_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        formatted_logs.append({"time": now_time, "msg": "PRV Quantitative Engine active. Scanning top 500 UK & US universe.", "level": "info"})

    # Idle Cash Accounting
    idle_audit = capital_manager.generate_idle_cash_audit(
        core_capital=cap_state["core_capital"],
        available_cash=cap_state["idle_core_cash"],
        active_capital=cap_state["active_capital"],
        market_regime=regime
    )

    return {
        "total_equity": cap_state["total_broker_nav"],
        "cash_balance": cap_state["idle_core_cash"],
        "banked_profits": cap_state["profit_vault_balance"],
        "core_capital": cap_state["core_capital"],
        "active_capital": cap_state["active_capital"],
        "capital_utilization": cap_state["capital_utilization_pct"],
        "portfolio": positions,
        "system_logs": formatted_logs,
        "markets": {
            "UK": is_uk_market_open(),
            "US": is_us_market_open()
        },
        "market_regime": regime,
        "target_deployment_pct": round(target_pct * 100, 1),
        "idle_cash_audit": idle_audit,
        "trading_halted": risk_engine.circuit_breaker_tripped,
        "engine_active": quant_engine.is_running
    }

@app.api_route("/api/trigger-trade", methods=["GET", "POST"])
def trigger_trade():
    res = quant_engine.run_cycle()
    sync_broker_data(force=True)
    return JSONResponse(content={"status": "executed", "result": res})

@app.api_route("/api/clean-dust", methods=["POST"])
def clean_dust():
    res = dust_cleaner.liquidate_dust_positions(is_paper=quant_engine.paper_mode)
    sync_broker_data(force=True)
    return JSONResponse(content=res)