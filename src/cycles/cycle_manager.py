"""
PRV Capital AI Performance Cycle Manager
Enforces strict evaluation boundaries, cycle archiving, and historical performance preservation.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import subprocess

from src.database.db import db
from src.brokers.trading212 import broker
from src.config.settings import settings

from src.cycles.validity_engine import validity_engine

class CycleManager:
    def __init__(self):
        pass

    def _get_current_git_commit(self) -> str:
        """Resolve current git commit hash safely."""
        try:
            res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return "HEAD"

    def get_active_cycle(self) -> Dict[str, Any]:
        """Fetch active cycle or create a fallback default."""
        active = db.get_active_cycle()
        if not active:
            # Create default Cycle 2
            cid = "CYCLE-002"
            db.create_cycle({
                "cycle_id": cid,
                "cycle_name": "Cycle 2: Autonomous Production Engine v2.0",
                "start_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "status": "ACTIVE",
                "starting_capital": 50000.0,
                "ending_capital": 50000.0,
                "git_commit": self._get_current_git_commit(),
                "ai_version": "v2.0-lean-fastapi",
                "feature_set": "Unified Ingress, Single Daily Executive Report, Zero-Fallback Broker Parity",
                "notes": "Evaluation cycle initialized after broker reset to £50,000.00"
            })
            active = db.get_active_cycle()
        return active

    def get_active_cycle_telemetry(self, force_live_broker: bool = False) -> Dict[str, Any]:
        """
        Calculate real-time metrics strictly scoped to the active cycle.
        Uses in-memory snapshot and SQLite trade ledger for sub-millisecond execution.
        Preserves zero contamination from prior archived cycles.
        """
        active_cycle = self.get_active_cycle()
        cycle_id = active_cycle["cycle_id"]
        
        # In-memory snapshot state (sub-millisecond, zero network blocking)
        cached = getattr(broker, "_cached_summary", None)
        if cached and cached.get("total_value") is not None:
            live_nav = float(cached["total_value"])
            live_cash = float(cached.get("available_cash", live_nav))
            live_invested = float(cached.get("invested", 0.0))
        else:
            live_nav = float(getattr(broker, "_last_verified_nav", 50000.0))
            live_cash = float(getattr(broker, "_last_verified_cash", live_nav))
            live_invested = float(getattr(broker, "_last_verified_invested", 0.0))

        positions = getattr(broker, "_cached_positions", []) or []
        unrealized_pnl = sum(float(p.get("ppl", 0.0)) for p in positions) if positions else 0.0

        # Cycle-scoped trade ledger from SQLite
        cycle_trades = db.get_trades(limit=1000, cycle_id=cycle_id)
        realized_pnl = sum(float(t.get("realized_pnl", 0.0)) for t in cycle_trades)
        
        starting_cap = float(active_cycle.get("starting_capital", 50000.0))
        total_return = round(realized_pnl + unrealized_pnl, 2)
        total_return_pct = round((total_return / max(1.0, starting_cap)) * 100.0, 2)

        wins = [t for t in cycle_trades if float(t.get("realized_pnl", 0.0)) > 0]
        losses = [t for t in cycle_trades if float(t.get("realized_pnl", 0.0)) < 0]
        tot_win = sum(float(t.get("realized_pnl", 0.0)) for t in wins)
        tot_loss = abs(sum(float(t.get("realized_pnl", 0.0)) for t in losses))

        win_rate = round((len(wins) / max(1, len(cycle_trades))) * 100.0, 1) if cycle_trades else 0.0
        profit_factor = round(tot_win / max(1.0, tot_loss), 2) if tot_loss > 0 else (round(tot_win, 2) if tot_win > 0 else 0.0)

        # Days running
        start_dt_str = active_cycle.get("start_date", "")
        days_running = 0
        try:
            clean_start = start_dt_str.replace("Z", "+00:00")
            if " " in clean_start:
                s_dt = datetime.strptime(clean_start.split(".")[0], "%Y-%m-%d %H:%M:%S")
            else:
                s_dt = datetime.fromisoformat(clean_start)
            now_dt = datetime.now() if s_dt.tzinfo is None else datetime.now(timezone.utc)
            days_running = max(0, (now_dt - s_dt).days)
        except Exception:
            days_running = 0

        # Calculate cycle max drawdown
        peak = starting_cap
        calc_max_dd = 0.0
        eq = starting_cap
        for t in reversed(cycle_trades):
            eq += float(t.get("realized_pnl", 0.0))
            if eq > peak:
                peak = eq
            dd = (peak - eq) / max(1.0, peak) * 100.0
            if dd > calc_max_dd:
                calc_max_dd = dd

        # Evaluate statistical validity
        validity = validity_engine.evaluate_cycle(
            trade_count=len(cycle_trades),
            days_running=days_running,
            round_trip_trades=len(cycle_trades)
        )

        return {
            "cycle_id": cycle_id,
            "cycle_name": active_cycle.get("cycle_name"),
            "status": "ACTIVE",
            "start_date": active_cycle.get("start_date"),
            "days_running": days_running,
            "starting_capital": starting_cap,
            "current_nav": live_nav,
            "current_cash": live_cash,
            "invested": live_invested,
            "realised_pnl": round(realized_pnl, 2),
            "unrealised_pnl": round(unrealized_pnl, 2),
            "total_return": total_return,
            "total_return_pct": total_return_pct,
            "trade_count": len(cycle_trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown": round(calc_max_dd, 2),
            "git_commit": active_cycle.get("git_commit"),
            "ai_version": active_cycle.get("ai_version"),
            "feature_set": active_cycle.get("feature_set"),
            "data_source_type": active_cycle.get("data_source_type", "LIVE"),
            "evaluation_eligible": validity["evaluation_eligible"],
            "sample_size_classification": validity["sample_size_classification"],
            "confidence_level": validity["confidence_level"],
            "evaluation_reason": validity["evaluation_reason"],
            "validity_thresholds": validity.get("thresholds")
        }

    def reset_and_archive_cycle(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        1. Freeze & calculate final metrics of active cycle.
        2. Archive active cycle permanently in SQLite.
        3. Create and activate a fresh evaluation cycle.
        4. Reset real-time cycle return metrics to £0.00 / 0.00%.
        """
        active_telemetry = self.get_active_cycle_telemetry()
        old_cycle_id = active_telemetry["cycle_id"]

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Finalize & archive active cycle
        archive_updates = {
            "end_date": now_iso,
            "status": "ARCHIVED",
            "ending_capital": active_telemetry["current_nav"] or active_telemetry["starting_capital"],
            "realised_pnl": active_telemetry["realised_pnl"],
            "unrealised_pnl": active_telemetry["unrealised_pnl"],
            "total_return": active_telemetry["total_return"],
            "total_return_pct": active_telemetry["total_return_pct"],
            "trade_count": active_telemetry["trade_count"],
            "win_count": active_telemetry["win_count"],
            "loss_count": active_telemetry["loss_count"],
            "win_rate": active_telemetry["win_rate"],
            "max_drawdown": active_telemetry["max_drawdown"],
            "profit_factor": active_telemetry["profit_factor"],
            "evaluation_eligible": 1 if active_telemetry["evaluation_eligible"] else 0,
            "sample_size_classification": active_telemetry["sample_size_classification"],
            "confidence_level": active_telemetry["confidence_level"],
            "evaluation_reason": active_telemetry["evaluation_reason"]
        }
        db.update_cycle(old_cycle_id, archive_updates)

        # 2. Determine next cycle ID
        all_cycles = db.get_all_cycles()
        next_num = len(all_cycles) + 1
        new_cycle_id = f"CYCLE-{next_num:03d}"

        # 3. Create fresh active cycle
        new_cycle_name = params.get("cycle_name") or f"Cycle {next_num}: AI Evaluation Release"
        new_ai_version = params.get("ai_version") or "v2.1"
        new_features = params.get("feature_set") or "Autonomous Alpha Scoring & Execution"
        new_notes = params.get("notes") or f"Rollover triggered at {now_iso}"
        starting_nav = active_telemetry["current_nav"] or 50000.0

        new_cycle_data = {
            "cycle_id": new_cycle_id,
            "cycle_name": new_cycle_name,
            "start_date": now_iso,
            "end_date": None,
            "status": "ACTIVE",
            "starting_capital": starting_nav,
            "ending_capital": starting_nav,
            "realised_pnl": 0.0,
            "unrealised_pnl": 0.0,
            "total_return": 0.0,
            "total_return_pct": 0.0,
            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "git_commit": self._get_current_git_commit(),
            "ai_version": new_ai_version,
            "feature_set": new_features,
            "notes": new_notes,
            "data_source_type": "LIVE",
            "evaluation_eligible": 0,
            "sample_size_classification": "LOW",
            "confidence_level": "LOW",
            "evaluation_reason": "Trades Recorded: 0 / 20, Days Running: 0 / 30. More trading evidence required before evaluation."
        }
        db.create_cycle(new_cycle_data)

        # 4. Return archived & new cycle payloads
        archived_cycle = db.get_cycle_by_id(old_cycle_id)
        new_active_cycle = db.get_cycle_by_id(new_cycle_id)

        return {
            "status": "success",
            "message": f"Cycle {old_cycle_id} archived successfully. New evaluation cycle {new_cycle_id} active.",
            "archived_cycle": archived_cycle,
            "new_cycle": new_active_cycle
        }

    def get_cycle_history(self) -> List[Dict[str, Any]]:
        """Return all historical and active cycles with statistical validity."""
        cycles = db.get_all_cycles()
        res = []
        for c in cycles:
            c_dict = dict(c)
            # calculate runtime duration in days
            start_str = c_dict.get("start_date", "")
            end_str = c_dict.get("end_date")
            days = 0
            try:
                s_dt = datetime.strptime(start_str.split(".")[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                if end_str:
                    e_dt = datetime.strptime(end_str.split(".")[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                else:
                    e_dt = datetime.now()
                days = max(0, (e_dt - s_dt).days)
            except Exception:
                days = 0
            c_dict["duration_days"] = days
            
            # calculate or ensure validity evaluation
            v = validity_engine.evaluate_cycle(
                trade_count=int(c_dict.get("trade_count", 0)),
                days_running=days,
                round_trip_trades=int(c_dict.get("trade_count", 0))
            )
            c_dict["evaluation_eligible"] = v["evaluation_eligible"]
            c_dict["sample_size_classification"] = v["sample_size_classification"]
            c_dict["confidence_level"] = v["confidence_level"]
            c_dict["evaluation_reason"] = v["evaluation_reason"]
            res.append(c_dict)
        return res

    def get_cycle_detail(self, cycle_id: str) -> Optional[Dict[str, Any]]:
        """Get deep-dive metrics and trade ledger for a specific cycle."""
        cycle = db.get_cycle_by_id(cycle_id)
        if not cycle:
            return None
        trades = db.get_trades(limit=500, cycle_id=cycle_id)
        return {
            "cycle": cycle,
            "trades": trades,
            "trade_count": len(trades)
        }

cycle_manager = CycleManager()
