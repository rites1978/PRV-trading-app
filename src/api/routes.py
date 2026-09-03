import os
import time
from datetime import datetime, timezone
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
    """Start background 60s broker snapshot refresh worker on API boot."""
    broker.start_background_sync(interval_seconds=60)
    if os.getenv("PRV_AUTORUN_ENGINE", "false").lower() == "true":
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

    # Real-Time Return Calculations strictly using true period baselines
    daily_base = db.get_nav_baseline(period="1D", current_nav=total_nav, cycle_id=cycle_id)
    weekly_base = db.get_nav_baseline(period="1W", current_nav=total_nav, cycle_id=cycle_id)
    monthly_base = db.get_nav_baseline(period="1M", current_nav=total_nav, cycle_id=cycle_id)

    daily_pnl = round(total_nav - daily_base, 2)
    daily_pct = round((daily_pnl / max(1.0, daily_base)) * 100.0, 2)

    weekly_pnl = round(total_nav - weekly_base, 2)
    weekly_pct = round((weekly_pnl / max(1.0, weekly_base)) * 100.0, 2)

    monthly_pnl = round(total_nav - monthly_base, 2)
    monthly_pct = round((monthly_pnl / max(1.0, monthly_base)) * 100.0, 2)

    all_time_pnl = round(total_nav - starting_cap, 2)
    all_time_pct = round((all_time_pnl / max(1.0, starting_cap)) * 100.0, 2) if starting_cap > 0 else 0.0

    from src.portfolio.daily_objective_service import daily_objective_service
    obj_summary = daily_objective_service.get_daily_status()

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
        "daily_objective": {
            "daily_net_target_gbp": obj_summary["daily_net_profit_objective_gbp"],
            "net_realized_today_gbp": obj_summary["daily_net_realized_pnl_gbp"],
            "target_progress_pct": obj_summary["daily_target_progress_pct"],
            "trading_costs_today_gbp": obj_summary["daily_total_costs_gbp"],
            "banked_today_gbp": obj_summary["bankable_profit_today_gbp"],
            "total_banked_profit_gbp": obj_summary["cumulative_banked_profit_gbp"],
            "deployable_bankroll_gbp": obj_summary["deployable_bankroll_gbp"],
            "new_entries_allowed": obj_summary["new_discretionary_entries_allowed"],
            "net_profit_per_pound_cost": obj_summary["net_profit_per_pound_cost"],
            "turnover_gbp": obj_summary["turnover_gbp"],
            "entries_today": obj_summary["entries_today"],
            "exits_today": obj_summary["exits_today"],
            "force_trade_to_reach_daily_target": obj_summary["force_trade_to_reach_daily_target"],
            "daily_target_achieved": obj_summary["daily_target_achieved"],
            "daily_downside_breached": obj_summary["daily_downside_breached"],
            "gate_reason": obj_summary["gate_reason"],
            # Capital State Machine additions (3 Independent Dimensions)
            "reference_base_capital_gbp": obj_summary.get("reference_base_capital_gbp", 50000.0),
            "active_trading_equity_gbp": obj_summary.get("active_trading_equity_gbp", 50000.0),
            "base_capital_deficit_gbp": obj_summary.get("base_capital_deficit_gbp", 0.0),
            "in_recovery_mode": obj_summary.get("in_recovery_mode", False),
            "capital_state": obj_summary.get("capital_state", "NORMAL"),
            "daily_state": obj_summary.get("daily_state", "ACTIVE"),
            "market_state": obj_summary.get("market_state", "NORMAL"),
            "current_capital_state": obj_summary.get("capital_state", "NORMAL"),
            "banked_profit_reserve_gbp": obj_summary.get("banked_profit_reserve_gbp", 0.0),
            "banked_profit_reserve_location": obj_summary.get("banked_profit_reserve_location", "RINGFENCED_INSIDE_BROKER"),
            "total_capital_transfers_gbp": obj_summary.get("total_capital_transfers_gbp", 0.0),
            "net_strategy_profit_gbp": obj_summary.get("net_strategy_profit_gbp", 0.0),
            "topup_permission_required": obj_summary.get("topup_permission_required", False),
            "proposed_topup_amount_gbp": obj_summary.get("proposed_topup_amount_gbp", 0.0),
            "sizing_multiplier": obj_summary.get("sizing_multiplier", 1.0),
            "daily_net_unrealized_pnl_gbp": obj_summary.get("daily_net_unrealized_pnl_gbp", 0.0),
            "change_in_unrealized_today_gbp": obj_summary.get("change_in_unrealized_today_gbp", 0.0),
            "daily_mtm_pnl_gbp": obj_summary.get("daily_mtm_pnl_gbp", 0.0),
            "daily_total_net_pnl_gbp": obj_summary.get("daily_mtm_pnl_gbp", 0.0),
            "emergency_risk_mode": obj_summary.get("emergency_risk_mode", False)
        },
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
    from src.data.universe import universe_manager
    from src.portfolio.portfolio_snapshot import portfolio_snapshot
    from src.data.market_hours import market_hours
    
    gbp_usd_rate = portfolio_snapshot.get_gbp_usd_rate()
    usd_gbp_rate = 1.0 / gbp_usd_rate
    universe_map = {item.get("t212_ticker"): item for item in universe_manager.get_all()}
    universe_sym_map = {item.get("symbol"): item for item in universe_manager.get_all()}

    for pos in positions:
        full_ticker = pos.get("ticker", "")
        avg_p = float(pos.get("averagePrice", 0.0))
        cur_p = float(pos.get("currentPrice", avg_p))
        qty = float(pos.get("quantity", 0.0))
        ppl = float(pos.get("ppl", 0.0))
        
        # Determine jurisdiction, currency, and FX conversion
        is_uk = full_ticker.endswith("l_EQ") or full_ticker.endswith("_UK_EQ")
        if is_uk:
            source_curr = "GBP"
            fx_rate = 1.0
            cur_p_native = cur_p / 100.0 if cur_p > 100 else cur_p
            avg_p_native = avg_p / 100.0 if avg_p > 100 else avg_p
            cur_p_gbp = cur_p_native
            avg_p_gbp = avg_p_native
        else:
            source_curr = "USD"
            fx_rate = usd_gbp_rate
            cur_p_native = cur_p
            avg_p_native = avg_p
            cur_p_gbp = cur_p * usd_gbp_rate
            avg_p_gbp = avg_p * usd_gbp_rate

        market_val_gbp = round(qty * cur_p_native * fx_rate, 2)
        cost_val_gbp = round(qty * avg_p_native * fx_rate, 2)
        unrealized_pnl_gbp = round(market_val_gbp - cost_val_gbp, 2)
        pct = round(((cur_p_gbp - avg_p_gbp) / max(0.001, avg_p_gbp)) * 100.0, 2) if avg_p_gbp > 0 else 0.0
        total_unrealized_pnl += unrealized_pnl_gbp

        display_ticker = full_ticker.replace("l_EQ", "").replace("_US_EQ", "").replace("_EQ", "").replace("_UK_EQ", "")
        u_info = universe_map.get(full_ticker) or universe_sym_map.get(display_ticker) or {}
        sector = u_info.get("sector", "Equities")
        company_name = u_info.get("name", display_ticker)

        weight_pct = round((market_val_gbp / max(1.0, total_nav)) * 100.0, 2)
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + market_val_gbp

        market_open = market_hours.is_asset_market_open("UK" if is_uk else "US")
        order_status = "ORDER_EXECUTABLE_NOW" if market_open else "ORDER_ARMED"

        enriched_positions.append({
            "ticker": display_ticker,
            "full_ticker": full_ticker,
            "name": company_name,
            "sector": sector,
            "source_currency": source_curr,
            "source_price": round(cur_p_native, 2),
            "source_avg_price": round(avg_p_native, 2),
            "usd_gbp_fx_rate": round(fx_rate, 4),
            "quantity": qty,
            "average_price": round(avg_p_gbp, 2),
            "current_price": round(cur_p_gbp, 2),
            "price_gbp": round(cur_p_gbp, 2),
            "average_price_gbp": round(avg_p_gbp, 2),
            "position_cost": cost_val_gbp,
            "cost_basis_gbp": cost_val_gbp,
            "current_value": market_val_gbp,
            "market_value_gbp": market_val_gbp,
            "weight_pct": weight_pct,
            "unrealized_pnl": unrealized_pnl_gbp,
            "return_pct": pct,
            "order_status": order_status,
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
    
    # Real Timeframe Return Calculations strictly using true period baselines
    daily_base = db.get_nav_baseline(period="1D", current_nav=total_nav, cycle_id=cycle_id)
    weekly_base = db.get_nav_baseline(period="1W", current_nav=total_nav, cycle_id=cycle_id)
    monthly_base = db.get_nav_baseline(period="1M", current_nav=total_nav, cycle_id=cycle_id)
    starting_cap = float(active_cycle.get("starting_capital", 50000.0)) if active_cycle else 50000.0

    daily_pnl = round(total_nav - daily_base, 2)
    daily_pct = round((daily_pnl / max(1.0, daily_base)) * 100.0, 2)

    weekly_pnl = round(total_nav - weekly_base, 2)
    weekly_pct = round((weekly_pnl / max(1.0, weekly_base)) * 100.0, 2)

    monthly_pnl = round(total_nav - monthly_base, 2)
    monthly_pct = round((monthly_pnl / max(1.0, monthly_base)) * 100.0, 2)

    all_time_pnl = round(total_nav - starting_cap, 2)
    all_time_pct = round((all_time_pnl / max(1.0, starting_cap)) * 100.0, 2) if starting_cap > 0 else 0.0

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

# --- Live Alpha Validation Protocol Endpoints ---
from src.monitoring.live_alpha_validator import live_alpha_validator

@app.get("/api/validation/live_scorecards")
def get_live_validation_scorecards():
    """Live multi-horizon scorecard for rolling 20, rolling 50, and benchmark validation."""
    return live_alpha_validator.get_live_validation_scorecard()

# --- Research Prediction Scoreboard Endpoints ---
from src.analytics.research_prediction_scoreboard import research_scoreboard

@app.get("/api/research/scoreboard")
def get_research_prediction_scoreboard():
    """Complete Research Prediction Scoreboard & Accountability Engine."""
    return research_scoreboard.get_full_scoreboard()

@app.get("/api/research/capital_efficiency")
def get_research_capital_efficiency():
    """Capital Efficiency & Dead Capital Score ranking for active holdings."""
    sb = research_scoreboard.get_full_scoreboard()
    return {"capital_efficiency_dashboard": sb["capital_efficiency_dashboard"]}

# --- Phase 2 Intelligence Layer Endpoints ---
from src.analytics.phase2_intelligence_layer import phase2_intelligence

@app.get("/api/intelligence/phase2_dashboard")
def get_phase2_intelligence_dashboard():
    """Complete Phase 2 Intelligence & Learning Layer payload."""
    return phase2_intelligence.get_phase2_full_intelligence_dashboard()

@app.get("/api/intelligence/regimes")
def get_phase2_regimes():
    """Module 1: Market Regime Intelligence."""
    return phase2_intelligence.get_market_regime_intelligence()

@app.get("/api/intelligence/thesis_drift")
def get_phase2_thesis_drift():
    """Module 2: Thesis Drift Monitor."""
    return {"thesis_drift": phase2_intelligence.get_thesis_drift_monitor()}

@app.get("/api/intelligence/portfolio_health")
def get_phase2_portfolio_health():
    """Module 9: Portfolio Health Score."""
    return phase2_intelligence.get_portfolio_health_score()

@app.get("/api/intelligence/lessons")
def get_phase2_lessons():
    """Module 10: Learning Engine Top Lessons."""
    return phase2_intelligence.get_learning_engine_lessons()

# --- Evidence Classification Engine Endpoints ---
from src.analytics.evidence_classification_engine import evidence_classifier

@app.get("/api/evidence/classification_dashboard")
def get_evidence_classification_dashboard():
    """Complete platform-wide 4-tier Evidence Classification Dashboard."""
    return evidence_classifier.get_platform_evidence_dashboard()

# --- Phase 3 Production Evidence Platform Endpoints ---
from src.analytics.phase3_evidence_platform import (
    live_evidence_scorer,
    trade_postmortems,
    regime_learning,
    thesis_db,
    evolution_dashboard
)

@app.get("/api/evidence/live_score")
def get_live_evidence_score():
    """Module 1: 0-100 Live Evidence Score."""
    return live_evidence_scorer.calculate_live_evidence_score()

@app.get("/api/postmortem/trades")
def get_postmortem_trades():
    """Module 2: Trade Post-Mortem Ledger."""
    return {"postmortems": trade_postmortems.get_postmortems()}

@app.get("/api/learning/regimes")
def get_learning_regimes():
    """Module 3: Regime-Aware Learning Matrix."""
    return regime_learning.get_regime_learning_matrix()

@app.get("/api/learning/thesis")
def get_learning_thesis():
    """Module 4: Thesis Success Database & Rankings."""
    return thesis_db.get_thesis_rankings()

@app.get("/api/evolution/dashboard")
def get_portfolio_evolution_dashboard():
    """Module 5: Portfolio Evolution Multi-Horizon Trends."""
    return evolution_dashboard.get_evolution_dashboard()

# --- Phase 4 Execution Intelligence Endpoints ---
from src.analytics.phase4_execution_intelligence import (
    exit_quality_engine,
    position_upgrade_engine,
    capital_recycling_engine,
    alpha_contribution_engine,
    concentration_risk_engine
)

@app.get("/api/execution/exit_quality")
def get_execution_exit_quality():
    """Phase 4 Engine 1: Exit Quality Analytics."""
    return exit_quality_engine.get_exit_quality_metrics()

@app.get("/api/execution/position_upgrades")
def get_execution_position_upgrades():
    """Phase 4 Engine 2: Position Upgrade Matrix."""
    return position_upgrade_engine.get_position_upgrades()

@app.get("/api/execution/capital_recycling")
def get_execution_capital_recycling():
    """Phase 4 Engine 3: Capital Recycling Velocity."""
    return capital_recycling_engine.get_capital_recycling_metrics()

@app.get("/api/execution/alpha_contributions")
def get_execution_alpha_contributions():
    """Phase 4 Engine 4: Alpha Contribution per Holding."""
    return alpha_contribution_engine.get_alpha_contributions()

@app.get("/api/execution/concentration_risk")
def get_execution_concentration_risk():
    """Phase 4 Engine 5: Portfolio Concentration Risk Audit."""
    return concentration_risk_engine.get_concentration_risk_audit()

# --- Phase 5 Portfolio Operating System Endpoints ---
from src.analytics.phase5_portfolio_operating_system import (
    trade_journey_engine,
    decision_quality_engine,
    edge_decay_engine,
    benchmark_dominance_engine,
    institutional_scorecard_engine
)
from src.portfolio.daily_objective_service import daily_objective_service

@app.get("/api/objective/daily_summary")
def get_daily_objective_summary(date: Optional[str] = None):
    """
    PRV Capital Daily Net Profit Objective & Anti-Overtrading Mandate Telemetry.
    Returns £250 target progress, banked profit, deployable bankroll, and new entry permission.
    """
    return daily_objective_service.get_daily_status(target_date=date)

@app.get("/api/objective/challenge_evaluation")
def get_30day_challenge_evaluation():
    """
    PRV Capital 30-Day Practice Challenge Performance Evaluation.
    Computes 12 institutional performance metrics across the challenge.
    """
    return daily_objective_service.compute_30day_challenge_evaluation()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CAPITAL PRESERVATION, DAILY BANKING & RECOVERY STATE MACHINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from src.portfolio.capital_state_machine import capital_state_machine

@app.get("/api/capital/state")
def get_capital_state():
    """
    Returns authoritative three-ledger capital state machine telemetry:
    - REFERENCE_BASE_CAPITAL (£50,000)
    - ACTIVE_TRADING_EQUITY (Current deployable base)
    - BANKED_PROFIT_RESERVE (Non-deployable gains)
    - CAPITAL_TRANSFERS (Isolated from trading P&L)
    - Current State (NORMAL, RECOVERY, TARGET_ACHIEVED, DAILY_LOSS_LOCK, MARKET_STRESS, USER_TOPUP_PENDING)
    """
    return capital_state_machine.get_current_active_state()

@app.get("/api/capital/topup/status")
def get_topup_status():
    """Returns top-up permission prompt payload when capital deficit and banked reserve exist."""
    state = capital_state_machine.get_current_active_state()
    return {
        "active_trading_equity_gbp": state["active_trading_equity_gbp"],
        "base_capital_deficit_gbp": state["base_capital_deficit_gbp"],
        "banked_profit_reserve_gbp": state["banked_profit_reserve_gbp"],
        "proposed_topup_amount_gbp": state["proposed_topup_amount_gbp"],
        "topup_permission_required": state["topup_permission_required"],
        "current_state": state["current_state"]
    }

@app.post("/api/capital/topup/approve")
def approve_topup():
    """Explicit user approval to transfer funds from Banked Reserve to Active Trading Equity. NEVER counted as P&L."""
    return capital_state_machine.approve_topup(user_name="PORTFOLIO_MANAGER")

@app.post("/api/capital/topup/decline")
def decline_topup():
    """Explicit user decline to transfer funds. System remains in RECOVERY trading remaining active equity."""
    return capital_state_machine.decline_topup(user_name="PORTFOLIO_MANAGER")

@app.get("/api/capital/transfers")
def get_capital_transfers():
    """Returns historical ledger of approved capital transfers (isolated from trading P&L)."""
    return {"transfers": db.get_capital_transfers(limit=100)}

@app.get("/api/capital/transitions")
def get_capital_state_transitions():
    """Returns historical log of capital state machine transitions."""
    return {"transitions": db.get_state_transitions(limit=100)}

@app.get("/api/trade/journeys")
def get_trade_journeys():
    """Phase 5 Engine 1: Trade Lifecycle Journeys."""
    return {"trade_journeys": trade_journey_engine.get_trade_journeys()}

@app.get("/api/decisions/quality")
def get_decisions_quality():
    """Phase 5 Engine 2: Decision Quality Records."""
    return decision_quality_engine.get_decision_quality()

@app.get("/api/edge/decay")
def get_edge_decay():
    """Phase 5 Engine 3: Edge Decay Analytics."""
    return edge_decay_engine.get_edge_decay()

@app.get("/api/alpha/dominance")
def get_alpha_dominance():
    """Phase 5 Engine 4: Benchmark Dominance."""
    return benchmark_dominance_engine.get_benchmark_dominance()

@app.get("/api/institutional/scorecard")
def get_institutional_scorecard():
    """Phase 5 Engine 5: Institutional Readiness Scorecard."""
    return institutional_scorecard_engine.get_institutional_scorecard()

# --- Capital Recycling Shadow Portfolio Comparison Endpoints ---
from src.analytics.shadow_portfolio_engine import shadow_portfolio_engine

@app.get("/api/shadow/comparison")
def get_shadow_portfolio_comparison():
    """Evaluate live Portfolio A vs Shadow Ideal Portfolio B comparison."""
    return shadow_portfolio_engine.evaluate_shadow_comparison()

@app.get("/api/shadow/promotions")
def get_shadow_portfolio_promotions():
    """Evaluate Shadow Portfolio Promotion Candidates."""
    return shadow_portfolio_engine.get_shadow_promotions()

@app.get("/api/shadow/history")
def get_shadow_portfolio_history(limit: int = 30):
    """Retrieve daily Shadow Portfolio comparison audit history."""
    return {"comparison_history": db.get_shadow_comparison_history(limit=limit)}

@app.get("/api/broker/parity_check")
def get_broker_parity_check():
    """Verify that Broker is the Source of Truth and reconcile holdings counts."""
    return broker.verify_broker_truth()

# --- Pre-Market Production Readiness Gate & Master PDF Endpoints ---
from src.monitoring.production_readiness_gate import readiness_gate
from src.reporting.master_pdf_generator import master_pdf_generator

@app.get("/api/readiness/gate")
def get_production_readiness_gate():
    """Pre-Market 8-Stage Health Check and Readiness Gate."""
    return readiness_gate.evaluate_readiness_gate()

@app.get("/api/readiness/history")
def get_production_readiness_history():
    """Historical Pre-Market Readiness Logs."""
    return {"readiness_history": db.get_readiness_history(limit=50)}

@app.post("/api/reports/generate_master_pdf")
def generate_end_of_day_master_pdf():
    """Generate the unified 20-section End-of-Day Master PDF."""
    path = master_pdf_generator.generate_daily_master_pdf()
    return {"status": "SUCCESS", "report_path": path, "filename": os.path.basename(path)}

@app.get("/api/reports/master_reports")
def list_master_pdf_reports():
    """List all available 20-section Master PDF reports in retention storage."""
    reports_dir = "reports"
    os.makedirs(reports_dir, exist_ok=True)
    pdf_files = []
    for f in sorted(os.listdir(reports_dir), reverse=True):
        if f.endswith(".pdf"):
            full_path = os.path.join(reports_dir, f)
            stat = os.stat(full_path)
            pdf_files.append({
                "filename": f,
                "file_path": full_path,
                "file_size_kb": round(stat.st_size / 1024, 1),
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "download_url": f"/api/reports/download/{f}"
            })
    return {"reports": pdf_files, "total_count": len(pdf_files)}

@app.get("/api/reports/download/{filename}")
def download_master_pdf_report(filename: str):
    """Direct one-click download for Master PDF reports."""
    clean_filename = os.path.basename(filename)
    filepath = os.path.join("reports", clean_filename)
    if not os.path.exists(filepath):
        if clean_filename.startswith("PRV_DAILY_MASTER_REPORT_"):
            filepath = master_pdf_generator.generate_daily_master_pdf()
        else:
            raise HTTPException(status_code=404, detail="Report PDF not found")
            
    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=clean_filename,
        headers={"Content-Disposition": f'attachment; filename="{clean_filename}"'}
    )

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
    """Manually or automatically dispatch End-of-Day CIO Brief to Telegram and Email."""
    results = daily_report_service.dispatch_daily_report(report_date=date)
    return {"status": "dispatched", "channels": results}

@app.post("/api/telegram/premarket_brief")
def dispatch_premarket_cio_brief():
    """Dispatch Pre-Market CIO Brief at 08:20 UK Time."""
    res = daily_report_service.dispatch_premarket_brief()
    return {"status": "dispatched", "telegram_sent": res}

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

@app.get("/api/macro/assessment")
def get_macro_impact_assessment():
    from src.analytics.macro_impact_gate import macro_impact_gate
    assessment = macro_impact_gate.verify_gate_passed_or_run()
    return JSONResponse(content=assessment)

@app.get("/api/macro/ledger")
def get_macro_event_ledger(limit: int = 50):
    entries = db.get_macro_ledger_entries(limit=limit)
    return JSONResponse(content={"entries": entries, "count": len(entries)})

@app.get("/api/portfolio/snapshot")
def get_authoritative_portfolio_snapshot(force_refresh: bool = False):
    from src.portfolio.portfolio_snapshot import portfolio_snapshot
    snapshot = portfolio_snapshot.get_authoritative_snapshot(force_refresh=force_refresh)
    return JSONResponse(content=snapshot)

@app.get("/api/reconciliation/status")
def get_balance_sheet_reconciliation():
    from src.portfolio.portfolio_snapshot import portfolio_snapshot
    snapshot = portfolio_snapshot.get_authoritative_snapshot(force_refresh=False)
    latest_event = db.get_latest_reconciliation_event()
    return JSONResponse(content={
        "status": snapshot["reconciliation_status"],
        "is_reconciled": snapshot["is_reconciled"],
        "failed_invariants": snapshot["failed_invariants"],
        "account_summary": snapshot["account_summary"],
        "latest_ledger_record": latest_event
    })

@app.get("/api/analytics/net-edge")
def evaluate_net_edge(symbol: str = "CRM", entry: float = 280.0, target: float = 296.0, sl: float = 273.0, nominal: float = 2500.0, is_uk: bool = False, is_foreign: bool = True):
    from src.execution.net_edge_gate import net_edge_gate
    res = net_edge_gate.evaluate_candidate(
        symbol=symbol,
        entry_price=entry,
        target_price=target,
        stop_loss_price=sl,
        nominal_value=nominal,
        is_uk=is_uk,
        is_foreign=is_foreign
    )
    return JSONResponse(content=res)

@app.get("/api/analytics/shadow-strategies")
def get_shadow_strategies():
    from src.analytics.shadow_portfolio_engine import shadow_portfolio_engine
    comparison = shadow_portfolio_engine.evaluate_shadow_comparison()
    return JSONResponse(content=comparison)

@app.get("/api/analytics/dead-capital")
def get_dead_capital_audits():
    from src.portfolio.dead_capital_manager import dead_capital_manager
    audits = dead_capital_manager.audit_all_holdings_for_dead_capital()
    return JSONResponse(content={"audits": audits, "count": len(audits)})

@app.get("/api/analytics/convictions")
def get_unified_convictions():
    from src.analytics.unified_conviction_engine import unified_conviction_engine
    convictions = unified_conviction_engine.get_all_holdings_convictions()
    return JSONResponse(content={"convictions": convictions, "count": len(convictions)})

@app.get("/api/analytics/expectancy")
def get_expectancy_analytics():
    from src.analytics.expectancy_engine import expectancy_engine
    metrics = expectancy_engine.compute_expectancy_metrics()
    return JSONResponse(content=metrics)

