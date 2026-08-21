import os
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
from src.brokers.trading212 import broker
from src.database.db import db
from src.risk.risk_engine import risk_engine

def is_uk_market_open() -> bool:
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:  # Saturday/Sunday
        return False
    # LSE open: 08:00 - 16:30 London (UTC in winter / UTC+1 in summer)
    current_time = now_utc.time()
    return dtime(8, 0) <= current_time <= dtime(16, 30)

def is_us_market_open() -> bool:
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:  # Saturday/Sunday
        return False
    # NYSE/NASDAQ open: 14:30 - 21:00 UTC
    current_time = now_utc.time()
    return dtime(14, 30) <= current_time <= dtime(21, 0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the autonomous quant engine in the background
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
    account = broker.get_account_summary()
    positions = broker.get_open_positions()
    
    total_equity = account.get("total_value", settings.STARTING_CAPITAL) if account.get("success") else settings.STARTING_CAPITAL
    available_cash = account.get("available_cash", settings.STARTING_CAPITAL) if account.get("success") else settings.STARTING_CAPITAL
    invested = account.get("invested", 0.0) if account.get("success") else 0.0
    
    cap_state = capital_manager.get_capital_state(total_equity, invested, available_cash)
    
    # Audit logs for UI stream
    audit_records = db.get_audit_logs(limit=25)
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
        "trading_halted": risk_engine.circuit_breaker_tripped,
        "engine_active": quant_engine.is_running
    }

@app.api_route("/api/trigger-trade", methods=["GET", "POST"])
def trigger_trade():
    res = quant_engine.run_cycle()
    return JSONResponse(content={"status": "executed", "result": res})