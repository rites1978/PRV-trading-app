from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
from src.core.engine import quant_engine
from src.database.db import db
from src.brokers.trading212 import broker
from src.portfolio.capital_manager import capital_manager

app = FastAPI(
    title="PRV Capital Autonomous Quant Trading API",
    description="Production-grade institutional execution and monitoring API for PRV Capital",
    version="2.0.0"
)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "engine_running": quant_engine.is_running,
        "paper_mode": quant_engine.paper_mode,
        "environment": broker.env
    }

@app.get("/capital")
def get_capital_status():
    account = broker.get_account_summary()
    if not account.get("success"):
        raise HTTPException(status_code=500, detail=account.get("error"))
    
    total_nav = account["total_value"]
    invested = account["invested"]
    cash = account["available_cash"]
    
    return capital_manager.get_capital_state(total_nav, invested, cash)

@app.get("/positions")
def get_positions():
    return broker.get_open_positions()

@app.get("/trades")
def get_trades(limit: int = 50):
    return db.get_trades(limit=limit)

@app.get("/audit")
def get_audit_logs(limit: int = 100):
    return db.get_audit_logs(limit=limit)

@app.post("/engine/start")
def start_engine():
    quant_engine.start()
    return {"status": "started", "is_running": quant_engine.is_running}

@app.post("/engine/stop")
def stop_engine():
    quant_engine.stop()
    return {"status": "stopped", "is_running": quant_engine.is_running}

@app.post("/engine/cycle")
def execute_cycle():
    result = quant_engine.run_cycle()
    return result
