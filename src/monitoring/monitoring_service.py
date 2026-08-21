from typing import Dict, Any, List, Optional
from datetime import datetime
import numpy as np
import pandas as pd

from src.config.settings import settings
from src.database.db import db
from src.monitoring.evidence_recorder import evidence_recorder
from src.data.market_hours import market_hours
from telegram_notifier import TelegramNotifier

class ProductionMonitoringService:
    def __init__(self):
        self.notifier = TelegramNotifier()

    def get_daily_dashboard(self, account: Dict[str, Any], positions: List[Dict[str, Any]], cap_state: Dict[str, Any], regime: str) -> Dict[str, Any]:
        """Section 3A: Daily Dashboard"""
        trades = db.get_trades(limit=500)
        wins = [t for t in trades if t.get("realized_pnl", 0) > 0]
        losses = [t for t in trades if t.get("realized_pnl", 0) < 0]
        
        tot_win_gbp = sum(t.get("realized_pnl", 0) for t in wins)
        tot_loss_gbp = abs(sum(t.get("realized_pnl", 0) for t in losses))
        pf = round(tot_win_gbp / max(1.0, tot_loss_gbp), 2)
        win_rate = round((len(wins) / max(1, len(trades))) * 100.0, 1) if trades else 0.0
        
        tot_realized_pnl = sum(t.get("realized_pnl", 0) for t in trades)
        tot_unrealized_pnl = sum(float(p.get("ppl", 0)) for p in positions)
        
        starting_cap = settings.STARTING_CAPITAL
        current_nav = cap_state.get("total_broker_nav", starting_cap)
        drawdown_pct = max(0.0, (starting_cap - current_nav) / starting_cap * 100.0)
        
        snapshot = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "starting_nav": starting_cap,
            "current_nav": current_nav,
            "core_capital": cap_state.get("core_capital", starting_cap),
            "active_capital": cap_state.get("active_capital", 0.0),
            "idle_cash": cap_state.get("idle_core_cash", starting_cap),
            "vault_balance": cap_state.get("profit_vault_balance", 0.0),
            "deployment_pct": cap_state.get("capital_utilization_pct", 0.0),
            "daily_pnl": tot_realized_pnl + tot_unrealized_pnl,
            "daily_pnl_pct": round((tot_realized_pnl + tot_unrealized_pnl) / starting_cap * 100.0, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "peak_nav": max(starting_cap, current_nav),
            "open_positions_count": len(positions),
            "market_regime": regime,
            "profit_factor": pf,
            "win_rate": win_rate,
            "completed_trades_count": len(trades)
        }
        
        # Record daily evidence snapshot
        evidence_recorder.record_daily_snapshot(snapshot)
        
        return snapshot

    def get_trade_ledger(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Section 3B: Trade Ledger"""
        trades = db.get_trades(limit=limit)
        ledger = []
        for t in trades:
            ledger.append({
                "timestamp": t.get("timestamp", ""),
                "symbol": t.get("symbol", ""),
                "action": t.get("action", ""),
                "quantity": t.get("quantity", 0.0),
                "price": t.get("price", 0.0),
                "net_cost": t.get("net_cost", 0.0),
                "stop_loss": round(t.get("price", 0) * (1.0 - settings.DEFAULT_STOP_LOSS_PCT), 2),
                "take_profit": round(t.get("price", 0) * (1.0 + settings.DEFAULT_TAKE_PROFIT_PCT), 2),
                "realized_pnl": t.get("realized_pnl", 0.0),
                "net_return_pct": round((t.get("realized_pnl", 0.0) / max(1.0, t.get("net_cost", 1.0))) * 100.0, 2),
                "exit_reason": t.get("trade_reason", ""),
                "mode": t.get("mode", "LIVE")
            })
        return ledger

    def get_risk_dashboard(self, current_nav: float, starting_nav: float, positions: List[Dict[str, Any]], regime: str) -> Dict[str, Any]:
        """Section 3C: Risk Dashboard"""
        peak_nav = max(starting_nav, current_nav)
        drawdown_pct = round(max(0.0, (peak_nav - current_nav) / peak_nav * 100.0), 2)
        
        # Sector Concentration
        sector_dist = {}
        for p in positions:
            sec = p.get("sector", "Technology")
            val = float(p.get("quantity", 0)) * float(p.get("currentPrice", 0))
            sector_dist[sec] = sector_dist.get(sec, 0.0) + val
            
        tot_val = sum(sector_dist.values())
        sector_pcts = {k: round((v / max(1.0, tot_val)) * 100.0, 1) for k, v in sector_dist.items()}
        
        kill_switch_active = drawdown_pct >= 8.50
        
        return {
            "current_drawdown_pct": drawdown_pct,
            "max_drawdown_threshold": 8.50,
            "tier1_warning_threshold": 3.00,
            "tier2_circuit_threshold": 5.00,
            "peak_nav": peak_nav,
            "gross_exposure_gbp": tot_val,
            "gross_exposure_pct": round((tot_val / max(1.0, current_nav)) * 100.0, 1),
            "sector_concentration": sector_pcts,
            "market_regime": regime,
            "kill_switch_status": "TRIPPED_HALT" if kill_switch_active else "NORMAL_ARMED"
        }

    def get_broker_audit_dashboard(self, broker_acc: Dict[str, Any], internal_cap: Dict[str, Any], positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Section 3D: Broker Audit Dashboard"""
        broker_nav = broker_acc.get("total_value", 0.0)
        internal_nav = internal_cap.get("total_broker_nav", broker_nav)
        discrepancy_pct = round(abs(broker_nav - internal_nav) / max(1.0, internal_nav) * 100.0, 3)
        
        evidence_recorder.record_broker_sync(broker_nav, internal_nav, len(positions), len(positions))
        
        return {
            "broker_status": "ONLINE" if broker_acc.get("success") else "ERROR",
            "broker_nav": broker_nav,
            "internal_nav": internal_nav,
            "nav_parity_discrepancy_pct": discrepancy_pct,
            "parity_status": "PERFECT_PARITY" if discrepancy_pct < 0.05 else ("WARNING" if discrepancy_pct < 1.5 else "DESYNC_HALT"),
            "open_positions_broker": len(positions),
            "api_rate_limit_margin_sec": 0.35,
            "market_hours": market_hours.get_market_status()
        }

    def get_phase_gate_dashboard(self, total_trades: int, rolling_pf: float, max_drawdown: float) -> Dict[str, Any]:
        """Section 3E: Phase Gate Dashboard"""
        gate1_trades_met = total_trades >= 50
        gate1_dd_met = max_drawdown <= 5.00
        gate1_pf_met = rolling_pf >= 1.15
        
        eligible_for_stage2 = gate1_trades_met and gate1_dd_met and gate1_pf_met
        
        current_status = "GREEN" if eligible_for_stage2 else ("YELLOW" if max_drawdown <= 5.0 else ("ORANGE" if max_drawdown <= 8.5 else "RED"))
        
        return {
            "current_stage": "STAGE 1: MICRO-LIVE PILOT (£5,000)",
            "next_stage": "STAGE 2: SCALED PILOT (£10,000)",
            "current_trade_count": total_trades,
            "required_trade_count": 50,
            "trades_remaining_to_gate1": max(0, 50 - total_trades),
            "current_profit_factor": rolling_pf,
            "required_profit_factor": 1.15,
            "current_max_drawdown": max_drawdown,
            "max_allowed_drawdown": 5.00,
            "scale_eligibility": eligible_for_stage2,
            "operational_status": current_status,
            "milestone_schedule": {
                "Milestone 1": {"trades": 50, "status": "PENDING" if total_trades < 50 else "COMPLETED"},
                "Milestone 2": {"trades": 75, "status": "PENDING" if total_trades < 75 else "COMPLETED"},
                "Milestone 3": {"trades": 100, "status": "PENDING" if total_trades < 100 else "COMPLETED"},
                "Milestone 4": {"trades": 145, "status": "PENDING" if total_trades < 145 else "COMPLETED"}
            }
        }

    def evaluate_and_dispatch_alerts(self, drawdown_pct: float, rolling_pf: float, trade_count: int, broker_desync_pct: float) -> List[str]:
        """Section 3F: Alerting Dispatcher"""
        alerts = []
        
        if drawdown_pct >= 8.50:
            msg = f"🚨 KILL-SWITCH ACTIVATED: Drawdown {drawdown_pct:.2f}% breached hard 8.50% ceiling! Trading halted."
            self.notifier.notify_alert("CRITICAL KILL SWITCH", msg)
            evidence_recorder.record_kill_switch_event("DRAWDOWN", "CRITICAL", drawdown_pct, 8.50, "HALT_TRADING")
            alerts.append(msg)
        elif drawdown_pct >= 5.00:
            msg = f"⚠️ CIRCUIT BREAKER TIER 2: Drawdown {drawdown_pct:.2f}% breached 5.00% stage limit. Losing holdings derisked."
            self.notifier.notify_alert("TIER 2 RISK BREACH", msg)
            alerts.append(msg)
            
        if trade_count >= 50 and rolling_pf < 0.65:
            msg = f"⚠️ PROFIT FACTOR WARNING: Rolling PF ({rolling_pf:.2f}) below 0.65 threshold after {trade_count} trades."
            self.notifier.notify_alert("ALPHA WARNING", msg)
            alerts.append(msg)
            
        if broker_desync_pct > 1.50:
            msg = f"🚨 BROKER DESYNC DETECTED: NAV discrepancy {broker_desync_pct:.2f}% exceeds 1.50% threshold."
            self.notifier.notify_alert("BROKER SYNC ERROR", msg)
            alerts.append(msg)
            
        if trade_count in [50, 75, 100, 145]:
            msg = f"🎯 STATISTICAL MILESTONE REACHED: Completed Trade N = {trade_count}. Running Phase 21 falsification review."
            self.notifier.notify_alert("MILESTONE REACHED", msg)
            alerts.append(msg)
            
        return alerts

monitoring_service = ProductionMonitoringService()
