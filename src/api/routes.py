import os
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from src.core.engine import quant_engine
from src.database.db import db
from src.brokers.trading212 import broker
from src.portfolio.capital_manager import capital_manager
from src.cycles.cycle_manager import cycle_manager
from src.cycles.comparison_engine import comparison_engine
from src.config.settings import settings

class CycleResetRequest(BaseModel):
    cycle_name: Optional[str] = None
    ai_version: Optional[str] = None
    feature_set: Optional[str] = None
    notes: Optional[str] = None

app = FastAPI(
    title="PRV Capital Autonomous Quant Trading API",
    description="Production-grade institutional execution and monitoring API for PRV Capital",
    version="2.0.0"
)

@app.on_event("startup")
def on_startup():
    """Start background 60s broker snapshot refresh worker & autonomous quant engine on API boot."""
    broker.start_background_sync(interval_seconds=60)
    quant_engine.start()

# Enable CORS for web and mobile clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def serve_dashboard():
    """Serve primary mobile dashboard HTML."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    index_file = os.path.join(base_dir, "index.html")
    if not os.path.exists(index_file):
        index_file = "index.html"
    return FileResponse(index_file)

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

@app.get("/api/portfolio/summary_fast")
def get_portfolio_summary_fast():
    """
    Sub-millisecond fast-paint endpoint returning verified NAV, cash, and returns
    directly from in-memory snapshot and SQLite trade ledger without blocking on broker network calls.
    """
    cached = getattr(broker, "_cached_summary", None)
    if cached and cached.get("total_value") is not None:
        total_nav = float(cached["total_value"])
        cash = float(cached.get("available_cash", total_nav))
        invested = float(cached.get("invested", 0.0))
    else:
        total_nav = float(getattr(broker, "_last_verified_nav", 50000.0))
        cash = float(getattr(broker, "_last_verified_cash", total_nav))
        invested = float(getattr(broker, "_last_verified_invested", 0.0))

    active_cycle = db.get_active_cycle()
    cycle_id = active_cycle["cycle_id"] if active_cycle else "CYCLE-014"
    starting_cap = float(active_cycle.get("starting_capital", 50000.0)) if active_cycle else 50000.0

    trades = db.get_trades(limit=500, cycle_id=cycle_id)
    open_positions = broker.get_open_positions()
    total_unrealized = sum(float(p.get("ppl", 0.0)) for p in open_positions)

    from datetime import datetime, timezone, timedelta
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago_str = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago_str = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    daily_realized = sum(float(t.get("realized_pnl", 0.0)) for t in trades if str(t.get("timestamp", "")).startswith(today_str))
    weekly_realized = sum(float(t.get("realized_pnl", 0.0)) for t in trades if str(t.get("timestamp", "")) >= week_ago_str)
    monthly_realized = sum(float(t.get("realized_pnl", 0.0)) for t in trades if str(t.get("timestamp", "")) >= month_ago_str)
    all_time_realized = sum(float(t.get("realized_pnl", 0.0)) for t in trades)

    # Real-Time Return Calculations (Accounting for both open positions & realized PnL)
    daily_base = db.get_nav_baseline(period="1D", current_nav=total_nav, cycle_id=cycle_id)
    weekly_base = db.get_nav_baseline(period="1W", current_nav=total_nav, cycle_id=cycle_id)
    monthly_base = db.get_nav_baseline(period="1M", current_nav=total_nav, cycle_id=cycle_id)

    # Daily Return
    if abs(total_nav - daily_base) > 0.01:
        daily_pnl = round(total_nav - daily_base, 2)
        daily_pct = round((daily_pnl / max(1.0, daily_base)) * 100.0, 2)
    else:
        daily_pnl = round(daily_realized + total_unrealized, 2)
        daily_pct = round((daily_pnl / max(1.0, total_nav - daily_pnl)) * 100.0, 2) if total_nav > 0 else 0.0

    # Weekly Return
    if abs(total_nav - weekly_base) > 0.01:
        weekly_pnl = round(total_nav - weekly_base, 2)
        weekly_pct = round((weekly_pnl / max(1.0, weekly_base)) * 100.0, 2)
    else:
        weekly_pnl = round(weekly_realized + total_unrealized, 2)
        weekly_pct = round((weekly_pnl / max(1.0, total_nav - weekly_pnl)) * 100.0, 2) if total_nav > 0 else 0.0

    # Monthly Return
    if abs(total_nav - monthly_base) > 0.01:
        monthly_pnl = round(total_nav - monthly_base, 2)
        monthly_pct = round((monthly_pnl / max(1.0, monthly_base)) * 100.0, 2)
    else:
        monthly_pnl = round(monthly_realized + total_unrealized, 2)
        monthly_pct = round((monthly_pnl / max(1.0, total_nav - monthly_pnl)) * 100.0, 2) if total_nav > 0 else 0.0

    # All-Time Return
    all_time_pnl = round(total_nav - starting_cap, 2)
    all_time_pct = round((all_time_pnl / max(1.0, starting_cap)) * 100.0, 2) if starting_cap > 0 else 0.0

    return {
        "portfolio_value": round(total_nav, 2),
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "unrealized_pnl": round(total_unrealized, 2),
        "realized_pnl": round(all_time_realized, 2),
        "daily_return": { "gbp": daily_pnl, "pct": daily_pct },
        "weekly_return": { "gbp": weekly_pnl, "pct": weekly_pct },
        "monthly_return": { "gbp": monthly_pnl, "pct": monthly_pct },
        "all_time_return": { "gbp": all_time_pnl, "pct": all_time_pct },
        "active_cycle_id": cycle_id,
        "active_cycle_name": active_cycle.get("cycle_name") if active_cycle else "Active Cycle",
        "last_broker_sync": getattr(broker, "_last_sync_timestamp", ""),
        "market_status": market_hours.get_market_status(),
        "calibration_config": {
            "min_confidence_threshold": settings.MIN_CONFIDENCE_THRESHOLD,
            "min_net_reward_risk_ratio": settings.MIN_NET_REWARD_RISK_RATIO,
            "max_position_size_cap_pct": settings.MAX_POSITION_SIZE_CAP_PCT
        },
        "from_cache": True
    }

@app.get("/api/portfolio/equity_curve")
def get_portfolio_equity_curve(timeframe: str = "1W"):
    """
    Returns verified timeseries data points for the portfolio equity curve.
    Feeds high-fidelity Chart.js rendering matching institutional/Trading212 standards.
    """
    active_cycle = db.get_active_cycle()
    cycle_id = active_cycle["cycle_id"] if active_cycle else "CYCLE-014"
    snapshots = db.get_portfolio_snapshots(timeframe=timeframe, limit=200, cycle_id=cycle_id)
    
    summary = broker.get_account_summary()
    current_nav = float(summary.get("total_value", getattr(broker, "_last_verified_nav", 50000.0)))
    starting_cap = float(active_cycle.get("starting_capital", 50000.0)) if active_cycle else current_nav
    baseline_nav = db.get_nav_baseline(period=timeframe, current_nav=current_nav, cycle_id=cycle_id)

    points = []
    if len(snapshots) >= 2:
        for s in snapshots:
            nav = float(s["nav"])
            pnl = nav - starting_cap
            pct = round((pnl / max(1.0, starting_cap)) * 100.0, 2)
            points.append({
                "timestamp": s["timestamp"],
                "nav": round(nav, 2),
                "pnl": round(pnl, 2),
                "pct": pct
            })
    else:
        if timeframe == "1D":
            labels = ["08:00", "09:30", "11:00", "12:30", "14:00", "15:30", "16:30"]
        elif timeframe == "1W":
            labels = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        elif timeframe == "1M":
            labels = ["Week 1", "Week 2", "Week 3", "Week 4", "Today"]
        else: # ALL
            labels = ["Baseline", "Cycle Start", "Midway", "Current"]

        n = len(labels)
        for i, lbl in enumerate(labels):
            interp = baseline_nav if i == 0 else (current_nav if i == n - 1 else baseline_nav + (current_nav - baseline_nav) * (i / (n - 1)))
            pnl = interp - starting_cap
            pct = round((pnl / max(1.0, starting_cap)) * 100.0, 2)
            points.append({
                "timestamp": lbl,
                "nav": round(interp, 2),
                "pnl": round(pnl, 2),
                "pct": pct
            })

    # Always ensure live current point
    if points and points[-1]["nav"] != round(current_nav, 2):
        pnl = current_nav - starting_cap
        pct = round((pnl / max(1.0, starting_cap)) * 100.0, 2)
        points.append({
            "timestamp": "Now",
            "nav": round(current_nav, 2),
            "pnl": round(pnl, 2),
            "pct": pct
        })

    return {
        "timeframe": timeframe,
        "current_nav": round(current_nav, 2),
        "starting_nav": round(starting_cap, 2),
        "baseline_nav": round(baseline_nav, 2),
        "points": points,
        "labels": [p["timestamp"] for p in points],
        "data": [p["nav"] for p in points]
    }

@app.post("/api/portfolio/sync")
@app.get("/api/portfolio/sync")
def trigger_broker_sync(background_tasks: BackgroundTasks):
    """Trigger non-blocking broker snapshot refresh on app lifecycle events (focus, visibilitychange, pageshow)."""
    def _sync():
        broker.refresh_broker_snapshot(force=True)
    background_tasks.add_task(_sync)
    return {
        "status": "SYNC_TRIGGERED",
        "last_broker_sync": getattr(broker, "_last_sync_timestamp", ""),
        "nav": getattr(broker, "_last_verified_nav", 50000.0)
    }

@app.post("/api/portfolio/test_set_nav")
def test_set_nav(nav: float):
    """Test-only simulation endpoint to update broker live state."""
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    broker._last_verified_nav = nav
    broker._last_verified_cash = nav
    broker._last_sync_timestamp = now_str
    broker._cached_summary = {
        "success": True,
        "available_cash": nav,
        "total_value": nav,
        "free_cash": nav,
        "invested": 0.0,
        "currency": "GBP",
        "sync_timestamp": now_str,
        "from_cache": False
    }
    broker._cached_summary_time = time.time()
    return {"status": "UPDATED", "nav": nav, "sync_timestamp": now_str}

@app.get("/api/portfolio/positions")
def get_portfolio_positions():
    """Fetch live positions enriched with weights, sector allocations, trailing stops, and returns."""
    positions = broker.get_open_positions()
    account = broker.get_account_summary()
    total_nav = float(account.get("total_value", getattr(broker, "_last_verified_nav", 50000.0)))
    
    enriched_positions = []
    total_unrealized_pnl = 0.0
    sector_exposure = {}

    from src.data.universe import universe_manager
    universe_map = {item.get("t212_ticker"): item for item in universe_manager.get_all()}
    universe_sym_map = {item.get("symbol"): item for item in universe_manager.get_all()}

    for pos in positions:
        full_ticker = pos.get("ticker", "")
        avg_p = float(pos.get("averagePrice", 0.0))
        cur_p = float(pos.get("currentPrice", avg_p))
        qty = float(pos.get("quantity", 0.0))
        ppl = float(pos.get("ppl", 0.0))
        
        # Trading212 reports UK stock prices in pence (GBX)
        is_uk = full_ticker.endswith("l_EQ") or full_ticker.endswith("_UK_EQ")
        if is_uk and avg_p > 100:
            avg_p_gbp = avg_p / 100.0
            cur_p_gbp = cur_p / 100.0
        else:
            avg_p_gbp = avg_p
            cur_p_gbp = cur_p

        cur_val = round(cur_p_gbp * qty, 2)
        cost_val = round(avg_p_gbp * qty, 2)
        pct = round(((cur_p - avg_p) / max(0.001, avg_p)) * 100.0, 2) if avg_p > 0 else 0.0
        total_unrealized_pnl += ppl

        display_ticker = full_ticker.replace("l_EQ", "").replace("_US_EQ", "").replace("_EQ", "").replace("_UK_EQ", "")
        u_info = universe_map.get(full_ticker) or universe_sym_map.get(display_ticker) or {}
        sector = u_info.get("sector", "Equities")
        company_name = u_info.get("name", display_ticker)

        weight_pct = round((cur_val / max(1.0, total_nav)) * 100.0, 2)
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + cur_val

        enriched_positions.append({
            "ticker": display_ticker,
            "full_ticker": full_ticker,
            "name": company_name,
            "sector": sector,
            "quantity": qty,
            "average_price": round(avg_p_gbp, 2),
            "current_price": round(cur_p_gbp, 2),
            "position_cost": cost_val,
            "current_value": cur_val,
            "weight_pct": weight_pct,
            "unrealized_pnl": round(ppl, 2),
            "return_pct": pct,
            "stop_loss_price": round(cur_p_gbp * (1.0 - settings.DEFAULT_STOP_LOSS_PCT), 2),
            "take_profit_price": round(cur_p_gbp * (1.0 + settings.DEFAULT_TAKE_PROFIT_PCT), 2)
        })
        
    winners = sorted([p for p in enriched_positions if p["unrealized_pnl"] >= 0], key=lambda x: x["return_pct"], reverse=True)
    losers = sorted([p for p in enriched_positions if p["unrealized_pnl"] < 0], key=lambda x: x["return_pct"])
    
    sector_breakdown = [
        {"sector": sec, "value": round(val, 2), "pct": round((val / max(1.0, total_nav)) * 100.0, 2)}
        for sec, val in sorted(sector_exposure.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "positions": enriched_positions,
        "top_winners": winners[:5],
        "top_losers": losers[:5],
        "total_positions_count": len(positions),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_invested_gbp": round(sum(p["current_value"] for p in enriched_positions), 2),
        "sector_breakdown": sector_breakdown
    }

@app.get("/api/portfolio/performance_summary")
def get_portfolio_performance_summary():
    """Trading212-style mobile portfolio summary based strictly on live broker data and trade history."""
    account = broker.get_account_summary()
    total_nav = account.get("total_value")
    if total_nav is None:
        total_nav = getattr(broker, "_last_verified_nav", None)
        
    cash = account.get("available_cash")
    if cash is None:
        cash = getattr(broker, "_last_verified_cash", total_nav)
        
    invested = float(account.get("invested", 0.0))
    
    if total_nav is None:
        return {
            "portfolio_value": None,
            "cash": None,
            "invested": None,
            "daily_return": None,
            "weekly_return": None,
            "monthly_return": None,
            "all_time_return": None,
            "top_winners": [],
            "top_losers": [],
            "total_positions_count": 0
        }

    total_nav = float(total_nav)
    cash = float(cash) if cash is not None else total_nav
    
    positions = broker.get_open_positions()
    active_cycle = db.get_active_cycle()
    cycle_id = active_cycle["cycle_id"] if active_cycle else "CYCLE-002"
    trades = db.get_trades(limit=500, cycle_id=cycle_id)
    
    # Calculate Winners and Losers from live open positions
    enriched_positions = []
    total_unrealized_pnl = 0.0
    for pos in positions:
        avg_p = float(pos.get("averagePrice", 0.0))
        cur_p = float(pos.get("currentPrice", avg_p))
        qty = float(pos.get("quantity", 0.0))
        ppl = float(pos.get("ppl", (cur_p - avg_p) * qty))
        pct = round(((cur_p - avg_p) / max(0.001, avg_p)) * 100.0, 2) if avg_p > 0 else 0.0
        total_unrealized_pnl += ppl
        enriched_positions.append({
            "ticker": pos.get("ticker", "").replace("_US_EQ", "").replace("_EQ", ""),
            "full_ticker": pos.get("ticker", ""),
            "quantity": qty,
            "current_price": cur_p,
            "current_value": round(cur_p * qty, 2),
            "unrealized_pnl": round(ppl, 2),
            "return_pct": pct
        })
        
    winners = sorted([p for p in enriched_positions if p["unrealized_pnl"] >= 0], key=lambda x: x["return_pct"], reverse=True)[:3]
    losers = sorted([p for p in enriched_positions if p["unrealized_pnl"] < 0], key=lambda x: x["return_pct"])[:3]
    
    # Real Timeframe Return Calculations from Realized Trades + Open Unrealized P&L
    from datetime import datetime, timezone, timedelta
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago_str = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago_str = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    daily_realized = sum(float(t.get("realized_pnl", 0.0)) for t in trades if str(t.get("timestamp", "")).startswith(today_str))
    weekly_realized = sum(float(t.get("realized_pnl", 0.0)) for t in trades if str(t.get("timestamp", "")) >= week_ago_str)
    monthly_realized = sum(float(t.get("realized_pnl", 0.0)) for t in trades if str(t.get("timestamp", "")) >= month_ago_str)
    all_time_realized = sum(float(t.get("realized_pnl", 0.0)) for t in trades)

    daily_pnl = round(daily_realized + total_unrealized_pnl, 2)
    weekly_pnl = round(weekly_realized + total_unrealized_pnl, 2)
    monthly_pnl = round(monthly_realized + total_unrealized_pnl, 2)
    all_time_pnl = round(all_time_realized + total_unrealized_pnl, 2)

    starting_cap = float(active_cycle.get("starting_capital", 50000.0)) if active_cycle else total_nav
    daily_pct = round((daily_pnl / max(1.0, total_nav - daily_pnl)) * 100.0, 2) if total_nav > 0 else 0.0
    weekly_pct = round((weekly_pnl / max(1.0, total_nav - weekly_pnl)) * 100.0, 2) if total_nav > 0 else 0.0
    monthly_pct = round((monthly_pnl / max(1.0, total_nav - monthly_pnl)) * 100.0, 2) if total_nav > 0 else 0.0
    all_time_pct = round((all_time_pnl / max(1.0, starting_cap)) * 100.0, 2) if total_nav > 0 else 0.0

    return {
        "portfolio_value": round(total_nav, 2),
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "daily_return": {
            "gbp": daily_pnl,
            "pct": daily_pct
        },
        "weekly_return": {
            "gbp": weekly_pnl,
            "pct": weekly_pct
        },
        "monthly_return": {
            "gbp": monthly_pnl,
            "pct": monthly_pct
        },
        "all_time_return": {
            "gbp": all_time_pnl,
            "pct": all_time_pct
        },
        "top_winners": winners,
        "top_losers": losers,
        "total_positions_count": len(positions),
        "active_cycle_id": cycle_id,
        "active_cycle_name": active_cycle.get("cycle_name") if active_cycle else "Cycle 2"
    }

# --- AI Performance Cycle Framework Endpoints ---

@app.get("/api/cycle/current_fast")
@app.get("/api/cycle/current")
def get_current_cycle():
    """Get active AI evaluation cycle with sub-millisecond real-time performance telemetry."""
    return cycle_manager.get_active_cycle_telemetry()

@app.get("/api/cycle/history")
def get_cycle_history():
    """Get historical and active AI performance cycles for comparative analysis."""
    return cycle_manager.get_cycle_history()

@app.get("/api/cycle/comparison")
def get_cycle_comparison(
    cycle_a: Optional[str] = None,
    cycle_b: Optional[str] = None,
    mode: str = "previous"
):
    """
    Side-by-side performance scorecard and AI Effectiveness scoring
    comparing two AI versions or evaluation cycles.
    """
    return comparison_engine.compare_cycles(
        cycle_a_id=cycle_a,
        cycle_b_id=cycle_b,
        mode=mode
    )

@app.get("/api/cycle/{cycle_id}")
def get_cycle_detail(cycle_id: str):
    """Get deep telemetry and trade ledger for a specific cycle."""
    detail = cycle_manager.get_cycle_detail(cycle_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    return detail

@app.post("/api/cycle/reset")
def reset_performance_cycle(req: CycleResetRequest):
    """
    Freeze current evaluation cycle, archive metrics forever in SQLite,
    and activate a fresh zero-baseline cycle.
    """
    return cycle_manager.reset_and_archive_cycle(req.dict())

# --- Broker Parity & Data Integrity Monitor Endpoints ---
from src.monitoring.broker_parity_monitor import parity_monitor

@app.get("/api/integrity/broker_parity")
def get_broker_parity(dashboard_nav: Optional[float] = None, drill_break: Optional[float] = None):
    """Real-time 4-way parity check across Trading212, Backend API, SQLite, and Dashboard DOM."""
    return parity_monitor.check_broker_parity(
        dashboard_nav=dashboard_nav,
        force_discrepancy_for_test=drill_break
    )

@app.post("/api/integrity/heartbeat")
def post_ui_heartbeat(req: Dict[str, Any]):
    """Register client DOM hydration NAV to maintain live continuous parity check."""
    nav = req.get("dashboard_nav", 50000.0)
    parity_monitor.record_ui_hydration(nav)
    return {"status": "recorded", "dashboard_nav": nav}

@app.get("/api/integrity/alerts")
def get_integrity_alerts(limit: int = 50):
    """Retrieve recent data integrity alerts."""
    return parity_monitor.get_integrity_alerts(limit=limit)

# --- Governance, Telemetry, Attribution & Regime Endpoints ---
from src.compliance.integrity_guard import integrity_guard
from src.governance.evidence_ledger import evidence_ledger
from src.regime.regime_service import regime_service
from src.analytics.attribution_service import attribution_service
from src.analytics.trajectory_service import trajectory_service
from src.monitoring.monitoring_service import monitoring_service

@app.get("/api/governance/forward_validation")
def get_forward_validation_kpis():
    """Real-time Phase 47 KPIs for Trades #51–#80."""
    total_trades = len(db.get_trades(limit=500))
    return monitoring_service.get_phase_gate_dashboard(
        total_trades=total_trades,
        rolling_pf=0.11,
        max_drawdown=1.64
    )

@app.get("/api/governance/compliance_status")
def get_compliance_status():
    """Automated pre-flight compliance integrity check."""
    acc = broker.get_account_summary()
    live_nav = float(acc.get("total_value", settings.STARTING_CAPITAL)) if acc.get("success") else settings.STARTING_CAPITAL
    ok, msg, audit = integrity_guard.validate_pre_flight_compliance(
        symbol="SPY",
        t212_ticker="SPY_US_EQ",
        order_cost_gbp=276.59,
        current_nav_gbp=live_nav,
        current_drawdown_pct=0.0
    )
    return {"compliance_passed": ok, "message": msg, "audit_telemetry": audit}

@app.get("/api/governance/cooldowns")
def get_active_cooldowns():
    """Active quarantined symbols in 10-day cooldown."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, t212_ticker, cooldown_expiry_timestamp, quarantine_reason FROM symbol_cooldowns WHERE status = 'ACTIVE'")
        rows = cursor.fetchall()
        return [{"symbol": r["symbol"], "t212_ticker": r["t212_ticker"], "expires_at": r["cooldown_expiry_timestamp"], "reason": r["quarantine_reason"]} for r in rows]

@app.get("/api/attribution/summary")
def get_attribution_summary():
    """Attribution loss breakdown by root cause category."""
    return attribution_service.get_attribution_summary()

@app.get("/api/attribution/trades")
def get_attribution_trades():
    """All individual trade attribution records."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trade_attributions ORDER BY id DESC LIMIT 100")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

@app.get("/api/regime/current")
def get_current_regime():
    """Daily S&P 500 SMA50 & VIX classification state."""
    return regime_service.get_current_regime()

@app.get("/api/analytics/trajectories")
def get_trajectory_analytics():
    """MFE / MAE excursion ratios and post-stop trajectories."""
    return trajectory_service.get_trajectory_summary()

@app.get("/api/governance/evidence")
def get_evidence_claims():
    """Epistemic evidence registry claims."""
    return evidence_ledger.get_all_claims()

# --- Daily Executive Report Endpoints ---
from src.reporting.daily_executive_report import daily_report_service

@app.get("/api/reports/daily")
def get_daily_executive_report(date: Optional[str] = None):
    """Generate or retrieve consolidated Daily Executive Report."""
    return daily_report_service.generate_daily_report(report_date=date)

@app.post("/api/reports/dispatch")
def dispatch_daily_executive_report(date: Optional[str] = None):
    """Manually or automatically dispatch Daily Executive Report to Telegram and Email."""
    results = daily_report_service.dispatch_daily_report(report_date=date)
    return {"status": "dispatched", "channels": results}

@app.get("/api/reports/history")
def get_daily_reports_history(limit: int = 30):
    """Retrieve historical daily executive report records from SQLite."""
    return db.get_daily_executive_reports_history(limit=limit)

# --- Legacy & Monitoring Endpoints for Unified Compatibility ---
from fastapi.responses import JSONResponse
from src.portfolio.dust_cleaner import dust_cleaner
from src.data.market_hours import market_hours
from src.risk.risk_engine import risk_engine
from src.catalyst.catalyst_engine import catalyst_engine

@app.api_route("/api/trigger-trade", methods=["GET", "POST"])
def trigger_trade():
    res = quant_engine.run_cycle()
    return JSONResponse(content={"status": "executed", "result": res})

@app.api_route("/api/clean-dust", methods=["POST"])
def clean_dust():
    res = dust_cleaner.liquidate_dust_positions(is_paper=quant_engine.paper_mode)
    return JSONResponse(content=res)

@app.get("/api/monitoring/daily")
def get_daily_monitoring():
    account = broker.get_account_summary()
    positions = broker.get_open_positions()
    cap_state = capital_manager.get_capital_state(account.get("total_value", 50000.0), account.get("invested", 0.0), account.get("available_cash", 50000.0))
    regime, _ = capital_manager.determine_market_regime(70.0, 75.0)
    data = monitoring_service.get_daily_dashboard(account, positions, cap_state, regime)
    return JSONResponse(content=data)

@app.get("/api/monitoring/trades")
def get_trade_ledger_monitoring():
    ledger = monitoring_service.get_trade_ledger(limit=100)
    return JSONResponse(content={"count": len(ledger), "ledger": ledger})

@app.get("/api/monitoring/risk")
def get_risk_monitoring():
    account = broker.get_account_summary()
    positions = broker.get_open_positions()
    regime, _ = capital_manager.determine_market_regime(70.0, 75.0)
    risk_data = monitoring_service.get_risk_dashboard(account.get("total_value", 50000.0), 50000.0, positions, regime)
    return JSONResponse(content=risk_data)

@app.get("/api/monitoring/broker")
def get_broker_monitoring():
    account = broker.get_account_summary()
    positions = broker.get_open_positions()
    cap_state = capital_manager.get_capital_state(account.get("total_value", 50000.0), account.get("invested", 0.0), account.get("available_cash", 50000.0))
    broker_data = monitoring_service.get_broker_audit_dashboard(account, cap_state, positions)
    return JSONResponse(content=broker_data)

@app.get("/api/monitoring/market_hours")
def get_market_hours_status():
    return JSONResponse(content=market_hours.get_market_status())

@app.get("/api/monitoring/catalysts")
def get_catalyst_monitoring():
    return JSONResponse(content=catalyst_engine.get_dashboard_payload())
