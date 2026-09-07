"""
🏛️ PRV CAPITAL | STRATEGY V1: SWING STRATEGY (FROZEN BENCHMARK)
Immutable frozen reference implementation.
EXECUTION MODE: SHADOW ONLY.
Under no circumstances may V1 dispatch or submit live or practice orders to Trading212.
Calculates shadow decisions for benchmarking and performance attribution comparison against V2.
"""
import logging
from typing import Dict, Any, List
from src.config.settings import settings

logger = logging.getLogger("strategy_v1_frozen")


class StrategyV1:
    """
    Frozen Strategy V1: Swing Strategy Benchmark.
    Fixed 45% cash floor, 14-day holding period, +7.5% take-profit target, -2.5% stop-loss.
    """
    def __init__(self):
        self.strategy_id = "V1"
        self.version = "PRV_STRATEGY_V1"
        self.status = "FROZEN_BENCHMARK"
        self.execution_mode = "SHADOW"
        self.config_hash = settings.get_parameter_manifest_hash()

    def evaluate_shadow_signal(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates a shadow decision for comparative telemetry.
        """
        score = candidate.get("composite_score", 0.0)
        passes_hurdles = (score >= settings.MIN_CONFIDENCE_THRESHOLD)
        return {
            "strategy_id": self.strategy_id,
            "ticker": candidate.get("ticker"),
            "shadow_decision": "BUY" if passes_hurdles else "REJECT",
            "score": score,
            "target_take_profit_pct": settings.DEFAULT_TAKE_PROFIT_PCT * 100.0,
            "target_stop_loss_pct": settings.DEFAULT_STOP_LOSS_PCT * 100.0,
            "execution_permitted": False,
            "reason": "V1 is a frozen shadow benchmark. Execution prohibited."
        }

    def route_order(self, *args, **kwargs):
        raise PermissionError("Strategy V1 is a frozen benchmark operating in SHADOW mode. Practice order dispatch is strictly prohibited.")


strategy_v1 = StrategyV1()
