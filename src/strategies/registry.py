"""
🏛️ PRV CAPITAL | STRATEGY VERSIONING & GOVERNANCE REGISTRY
Maintains the immutable strategy registry for benchmarking and execution authority.
Enforces single execution authority:
- V1 = Frozen Swing Strategy (Shadow Benchmark Only, zero broker routing)
- V2 = Net Profit Capital Rotation (Authoritative Practice Candidate)
"""
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger("strategy_registry")


class StrategyRegistry:
    """
    Central strategy registry managing versions, deterministic config hashes,
    and single-authority execution gating.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(StrategyRegistry, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._active_strategy_id = "V2"
        self._strategies: Dict[str, Dict[str, Any]] = {}
        self._init_strategies()
        self._initialized = True

    def _init_strategies(self):
        from src.config.settings import settings

        # 1. PRV Strategy V1: Current Swing Strategy (Frozen Benchmark)
        v1_manifest = settings.generate_parameter_manifest()
        v1_hash = hashlib.sha256(json.dumps(v1_manifest, sort_keys=True).encode("utf-8")).hexdigest()

        self._strategies["V1"] = {
            "strategy_id": "V1",
            "version": "PRV_STRATEGY_V1",
            "name": "Swing Strategy (Frozen Benchmark)",
            "status": "FROZEN_BENCHMARK",
            "execution_mode": "SHADOW",
            "config_hash": v1_hash,
            "rules": {
                "holding_period_days": 14,
                "profit_target_pct": 7.5,
                "stop_loss_pct": 2.5,
                "reward_risk_ratio": 3.0,
                "required_cash_reserve_pct": 45.0,
                "max_position_size_pct": 8.0,
                "daily_bankable_target_gbp": 250.0,
            },
            "activation_timestamp": "2026-09-02T00:00:00Z",
            "deactivation_timestamp": None,
            "broker_trades": 0,
            "realised_net_pnl": 0.0,
            "banked_profit": 0.0,
            "number_of_trades": 0,
            "winners": 0,
            "losers": 0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "total_costs": 0.0,
            "capital_utilisation": 0.0,
            "average_holding_time_days": 0.0,
            "net_profit_per_pound_friction": 0.0
        }

        # 2. PRV Strategy V2: Net Profit Capital Rotation
        v2_rules = {
            "min_net_return_pct": 0.50, # +0.50% min net on capital deployed
            "max_intended_loss_pct": 1.00, # -1.00% max intended loss on capital deployed
            "min_net_reward_risk_ratio": 2.0,
            "no_fixed_cash_floor": True, # Dynamic allocation: 0% to 100% cash
            "profit_vault_enabled": True, # Hard locked, excluded from sizing
            "recovery_mode_threshold_gbp": 50000.0, # Restore £50k base before banking
            "broker_native_stop_protection": True,
            "trend_aware_trailing_exit": True,
        }
        v2_hash = hashlib.sha256(json.dumps(v2_rules, sort_keys=True).encode("utf-8")).hexdigest()

        self._strategies["V2"] = {
            "strategy_id": "V2",
            "version": "PRV_STRATEGY_V2",
            "name": "Net Profit Capital Rotation",
            "status": "ACTIVE_PRACTICE_CANDIDATE",
            "execution_mode": "PRACTICE",
            "config_hash": v2_hash,
            "rules": v2_rules,
            "activation_timestamp": "2026-09-06T00:00:00Z",
            "deactivation_timestamp": None,
            "broker_trades": 0,
            "realised_net_pnl": 0.0,
            "banked_profit": 0.0,
            "number_of_trades": 0,
            "winners": 0,
            "losers": 0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "total_costs": 0.0,
            "capital_utilisation": 0.0,
            "average_holding_time_days": 0.0,
            "net_profit_per_pound_friction": 0.0
        }

    def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._strategies.get(strategy_id.upper())

    def get_all_strategies(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._strategies)

    def get_active_execution_strategy_id(self) -> str:
        return self._active_strategy_id

    def can_strategy_route_orders(self, strategy_id: str) -> bool:
        """
        Only the active strategy (V2) has broker routing authority.
        V1 is frozen benchmark (shadow only).
        """
        strat = self.get_strategy(strategy_id)
        if not strat:
            return False
        if strat.get("execution_mode") == "SHADOW" or strat.get("status") == "FROZEN_BENCHMARK":
            return False
        return strat.get("strategy_id") == self._active_strategy_id

    def record_trade_result(self, strategy_id: str, net_pnl: float, costs: float = 0.0, is_winner: bool = None, holding_time_days: float = 0.0):
        strat = self.get_strategy(strategy_id)
        if not strat:
            return

        strat["broker_trades"] += 1
        strat["number_of_trades"] += 1
        strat["realised_net_pnl"] = round(strat["realised_net_pnl"] + net_pnl, 2)
        strat["total_costs"] = round(strat["total_costs"] + costs, 2)

        if is_winner is None:
            is_winner = (net_pnl > 0)

        if is_winner:
            strat["winners"] += 1
        else:
            strat["losers"] += 1

        total = strat["number_of_trades"]
        strat["win_rate"] = round((strat["winners"] / total) * 100.0, 2) if total > 0 else 0.0

        total_costs = strat["total_costs"]
        if total_costs > 0:
            strat["net_profit_per_pound_friction"] = round(strat["realised_net_pnl"] / total_costs, 2)

    def get_v2_config_hash(self) -> str:
        return self._strategies["V2"]["config_hash"]

    def get_v1_config_hash(self) -> str:
        return self._strategies["V1"]["config_hash"]


strategy_registry = StrategyRegistry()
