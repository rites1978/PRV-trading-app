"""
PRV Capital Statistical Validity & Sample Size Gate Engine
Enforces statistical significance thresholds before permitting AI Scorecard evaluation.
"""
from typing import Dict, Any

class StatisticalValidityEngine:
    MIN_TRADES = 20
    MIN_DAYS = 30
    MIN_ROUND_TRIP = 10

    @classmethod
    def classify_sample_size(cls, trade_count: int) -> str:
        """
        Confidence Model:
        - LOW: 0-19 trades
        - MEDIUM: 20-49 trades
        - HIGH: 50-99 trades
        - VERY_HIGH: 100+ trades
        """
        if trade_count >= 100:
            return "VERY_HIGH"
        elif trade_count >= 50:
            return "HIGH"
        elif trade_count >= 20:
            return "MEDIUM"
        else:
            return "LOW"

    @classmethod
    def evaluate_cycle(
        cls,
        trade_count: int,
        days_running: int,
        round_trip_trades: int
    ) -> Dict[str, Any]:
        """
        Evaluate whether a cycle has achieved statistical validity for AI effectiveness scoring.
        Rules:
        - trade_count >= 20
        - cycle_runtime_days >= 30
        - round_trip_trades >= 10
        """
        classification = cls.classify_sample_size(trade_count)
        
        has_trades = trade_count >= cls.MIN_TRADES
        has_days = days_running >= cls.MIN_DAYS
        has_round_trips = round_trip_trades >= cls.MIN_ROUND_TRIP

        is_eligible = has_trades and has_days and has_round_trips

        if is_eligible:
            confidence_level = classification
            reason = f"Statistically valid sample size met ({trade_count} trades, {days_running} days running)."
        else:
            confidence_level = "LOW" if trade_count < cls.MIN_TRADES else classification
            reason = (
                f"Trades Recorded: {trade_count} / {cls.MIN_TRADES}, "
                f"Days Running: {days_running} / {cls.MIN_DAYS}, "
                f"Round-Trip: {round_trip_trades} / {cls.MIN_ROUND_TRIP}. "
                f"More trading evidence required before evaluation."
            )

        return {
            "evaluation_eligible": is_eligible,
            "sample_size_classification": classification,
            "confidence_level": confidence_level,
            "evaluation_reason": reason,
            "thresholds": {
                "trades_recorded": trade_count,
                "min_trades_required": cls.MIN_TRADES,
                "days_running": days_running,
                "min_days_required": cls.MIN_DAYS,
                "round_trip_trades": round_trip_trades,
                "min_round_trip_required": cls.MIN_ROUND_TRIP
            }
        }

validity_engine = StatisticalValidityEngine()
