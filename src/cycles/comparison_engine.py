"""
PRV Capital AI Cycle Comparison Engine & Effectiveness Scorecard
Quantifies whether subsequent AI versions improve execution and alpha generation over previous baselines.
Gated by Statistical Validity & Sample Size engine.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from src.database.db import db
from src.cycles.cycle_manager import cycle_manager
from src.cycles.validity_engine import validity_engine

class ComparisonEngine:
    def __init__(self):
        pass

    def calculate_effectiveness_score(
        self,
        return_pct_delta: float,
        profit_factor_delta: float,
        win_rate_delta: float,
        drawdown_delta: float
    ) -> Dict[str, Any]:
        """
        Calculate the derived AI Effectiveness Score (0 to 100).
        Weights:
        - 40% Return Improvement
        - 25% Profit Factor Improvement
        - 20% Win Rate Improvement
        - 15% Drawdown Improvement
        """
        def clamp(val: float, min_v: float = 0.0, max_v: float = 100.0) -> float:
            return max(min_v, min(max_v, val))

        s_ret = clamp(50.0 + (return_pct_delta * 13.5))
        s_pf = clamp(50.0 + (profit_factor_delta * 40.0))
        s_win = clamp(50.0 + (win_rate_delta * 0.92))
        s_dd = clamp(50.0 + (drawdown_delta * 14.5))

        score = round((0.40 * s_ret) + (0.25 * s_pf) + (0.20 * s_win) + (0.15 * s_dd), 1)

        if score >= 90.0:
            classification = "EXCEPTIONAL"
        elif score >= 75.0:
            classification = "IMPROVED"
        elif score >= 50.0:
            classification = "NEUTRAL"
        else:
            classification = "DEGRADED"

        return {
            "ai_effectiveness_score": score,
            "classification": classification,
            "sub_scores": {
                "return_score": round(s_ret, 1),
                "profit_factor_score": round(s_pf, 1),
                "win_rate_score": round(s_win, 1),
                "drawdown_score": round(s_dd, 1)
            }
        }

    def _get_cycle_duration_days(self, cycle: Dict[str, Any]) -> int:
        """Calculate runtime duration in days for a cycle dict."""
        start_str = cycle.get("start_date", "")
        end_str = cycle.get("end_date")
        try:
            s_dt = datetime.strptime(start_str.split(".")[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
            if end_str:
                e_dt = datetime.strptime(end_str.split(".")[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
            else:
                e_dt = datetime.now()
            return max(0, (e_dt - s_dt).days)
        except Exception:
            return 0

    def compare_cycles(
        self,
        cycle_a_id: Optional[str] = None,
        cycle_b_id: Optional[str] = None,
        mode: str = "previous"
    ) -> Dict[str, Any]:
        """
        Perform side-by-side comparative analysis between two AI Performance Cycles.
        Modes: 'previous', 'best', 'custom'
        Enforces statistical sample size gating.
        """
        all_cycles = db.get_all_cycles()
        if not all_cycles:
            return {
                "error": "No cycles available for comparison"
            }

        # 1. Resolve Cycle A (Target / Current Cycle)
        cycle_a = None
        if cycle_a_id:
            cycle_a = db.get_cycle_by_id(cycle_a_id)
        if not cycle_a:
            # Default to active cycle with real-time telemetry if available
            telemetry = cycle_manager.get_active_cycle_telemetry()
            cycle_a = telemetry if telemetry else dict(all_cycles[0])
        else:
            cycle_a = dict(cycle_a)

        # 2. Resolve Cycle B (Baseline / Benchmark Cycle)
        cycle_b = None
        if mode == "custom" and cycle_b_id:
            cycle_b = db.get_cycle_by_id(cycle_b_id)
        elif mode == "best":
            archived = [c for c in all_cycles if c["cycle_id"] != cycle_a.get("cycle_id")]
            if archived:
                cycle_b = max(archived, key=lambda c: float(c["total_return_pct"] if c["total_return_pct"] is not None else 0.0))
        
        # Default fallback to previous chronological cycle
        if not cycle_b:
            candidates = [c for c in all_cycles if c["cycle_id"] != cycle_a.get("cycle_id")]
            if candidates:
                cycle_b = candidates[0]
            else:
                cycle_b = cycle_a

        cycle_b = dict(cycle_b)

        # Calculate durations
        a_days = cycle_a.get("days_running") if "days_running" in cycle_a else self._get_cycle_duration_days(cycle_a)
        b_days = cycle_b.get("days_running") if "days_running" in cycle_b else self._get_cycle_duration_days(cycle_b)

        # Extract normalized metrics
        a_ret = float(cycle_a.get("total_return_pct", 0.0) or 0.0)
        b_ret = float(cycle_b.get("total_return_pct", 0.0) or 0.0)

        a_win = float(cycle_a.get("win_rate", 0.0) or 0.0)
        b_win = float(cycle_b.get("win_rate", 0.0) or 0.0)

        a_pf = float(cycle_a.get("profit_factor", 0.0) or 0.0)
        b_pf = float(cycle_b.get("profit_factor", 0.0) or 0.0)

        a_dd = float(cycle_a.get("max_drawdown", 0.0) or 0.0)
        b_dd = float(cycle_b.get("max_drawdown", 0.0) or 0.0)

        a_trades = int(cycle_a.get("trade_count", 0) or 0)
        b_trades = int(cycle_b.get("trade_count", 0) or 0)

        # Deltas
        ret_delta = round(a_ret - b_ret, 2)
        win_delta = round(a_win - b_win, 2)
        pf_delta = round(a_pf - b_pf, 2)
        dd_delta = round(b_dd - a_dd, 2) # Lower drawdown in A is positive improvement
        trade_delta = a_trades - b_trades

        # 3. Statistical Validity Evaluation on Target Cycle A
        validity_a = validity_engine.evaluate_cycle(
            trade_count=a_trades,
            days_running=a_days,
            round_trip_trades=a_trades
        )

        validity_b = validity_engine.evaluate_cycle(
            trade_count=b_trades,
            days_running=b_days,
            round_trip_trades=b_trades
        )

        is_eligible = validity_a["evaluation_eligible"]

        if is_eligible:
            score_eval = self.calculate_effectiveness_score(ret_delta, pf_delta, win_delta, dd_delta)
            score_val = score_eval["ai_effectiveness_score"]
            classification = score_eval["classification"]
            sub_scores = score_eval["sub_scores"]
        else:
            score_val = None
            classification = "INSUFFICIENT_DATA"
            sub_scores = None

        comparison_payload = {
            "comparison_mode": mode,
            "evaluation_eligible": is_eligible,
            "classification": classification,
            "ai_effectiveness_score": score_val,
            "confidence_level": validity_a["confidence_level"],
            "sample_size_classification": validity_a["sample_size_classification"],
            "evaluation_reason": validity_a["evaluation_reason"],
            "validity_thresholds": validity_a["thresholds"],
            "current_cycle": {
                "cycle_id": cycle_a.get("cycle_id"),
                "cycle_name": cycle_a.get("cycle_name"),
                "ai_version": cycle_a.get("ai_version"),
                "git_commit": cycle_a.get("git_commit"),
                "return_pct": a_ret,
                "return_gbp": float(cycle_a.get("total_return", 0.0) or 0.0),
                "win_rate": a_win,
                "profit_factor": a_pf,
                "max_drawdown": a_dd,
                "trade_count": a_trades,
                "duration_days": a_days,
                "status": cycle_a.get("status", "ACTIVE"),
                "data_source_type": cycle_a.get("data_source_type", "LIVE"),
                "evaluation_eligible": validity_a["evaluation_eligible"],
                "confidence_level": validity_a["confidence_level"]
            },
            "previous_cycle": {
                "cycle_id": cycle_b.get("cycle_id"),
                "cycle_name": cycle_b.get("cycle_name"),
                "ai_version": cycle_b.get("ai_version"),
                "git_commit": cycle_b.get("git_commit"),
                "return_pct": b_ret,
                "return_gbp": float(cycle_b.get("total_return", 0.0) or 0.0),
                "win_rate": b_win,
                "profit_factor": b_pf,
                "max_drawdown": b_dd,
                "trade_count": b_trades,
                "duration_days": b_days,
                "status": cycle_b.get("status", "ARCHIVED"),
                "data_source_type": cycle_b.get("data_source_type", "SIMULATED_TEST" if cycle_b.get("cycle_id") == "CYCLE-001" else "LIVE"),
                "evaluation_eligible": validity_b["evaluation_eligible"],
                "confidence_level": validity_b["confidence_level"]
            },
            "improvement": {
                "return_pct_delta": ret_delta,
                "win_rate_delta": win_delta,
                "profit_factor_delta": pf_delta,
                "drawdown_delta": dd_delta,
                "trade_count_delta": trade_delta
            },
            "sub_scores": sub_scores,
            "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        }

        # Persist audit record
        try:
            db.record_cycle_comparison({
                "comparison_id": f"CMP_{cycle_a.get('cycle_id')}_{cycle_b.get('cycle_id')}_{int(datetime.now().timestamp())}",
                "cycle_a": cycle_a.get("cycle_id", "CYCLE-A"),
                "cycle_b": cycle_b.get("cycle_id", "CYCLE-B"),
                "return_delta": ret_delta,
                "win_rate_delta": win_delta,
                "profit_factor_delta": pf_delta,
                "drawdown_delta": dd_delta,
                "ai_effectiveness_score": score_val,
                "classification": classification,
                "comparison_json": comparison_payload
            })
        except Exception:
            pass

        return comparison_payload

comparison_engine = ComparisonEngine()
