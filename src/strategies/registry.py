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

        self._active_strategy_id = "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1"
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

        # 2. PRV Strategy V2: Net Profit Capital Rotation (Decommissioned after falsification audit)
        v2_rules = {
            "min_net_return_pct": 0.50,
            "max_intended_loss_pct": 1.00,
            "min_net_reward_risk_ratio": 2.0,
            "no_fixed_cash_floor": True,
            "profit_vault_enabled": True,
            "recovery_mode_threshold_gbp": 50000.0,
            "broker_native_stop_protection": True,
            "trend_aware_trailing_exit": True,
        }
        v2_hash = hashlib.sha256(json.dumps(v2_rules, sort_keys=True).encode("utf-8")).hexdigest()

        self._strategies["V2"] = {
            "strategy_id": "V2",
            "version": "PRV_STRATEGY_V2",
            "name": "Net Profit Capital Rotation (Legacy)",
            "status": "DECOMMISSIONED_AUDIT_HALT",
            "execution_mode": "SHADOW",
            "config_hash": v2_hash,
            "rules": v2_rules,
            "activation_timestamp": "2026-09-06T00:00:00Z",
            "deactivation_timestamp": "2026-09-07T12:00:00Z",
            "broker_trades": 1,
            "realised_net_pnl": 0.0,
            "banked_profit": 0.0,
            "number_of_trades": 1,
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

        # 3. Legacy Challenger: PRV HIT-AND-RUN ETF V1 (Decommissioned Lookahead Halt)
        etf_entry = {
            "strategy_id": "PRV_HIT_AND_RUN_ETF_V1",
            "version": "PRV_HIT_AND_RUN_ETF_V1",
            "name": "GBP SDRT-Exempt Index ETF Hit-and-Run (Decommissioned)",
            "status": "DECOMMISSIONED_LOOKAHEAD_HALT",
            "execution_mode": "SHADOW",
            "config_hash": "3ee18df44ac71eaacbcc5496047ab51dc2956d890b7ad755fa10a5a25d0f800a",
            "rules": {},
            "activation_timestamp": "2026-09-08T00:00:00Z",
            "deactivation_timestamp": "2026-09-08T09:30:00Z",
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
        self._strategies["ETF_V1"] = etf_entry
        self._strategies["PRV_HIT_AND_RUN_ETF_V1"] = etf_entry

        # 4. Ratified Core Compounding Engine: PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1
        core_rules = {
            "universe": ["CSP1.L", "EQQQ.L", "IWDA.L", "ISF.L", "EMIM.L", "SGLN.L", "IGLT.L"],
            "mom_lookback_bars": 20,
            "vol_lookback_bars": 20,
            "rebalance_days": 10,
            "position_size_gbp": 40000.0,
            "max_concurrent_positions": 1,
            "stop_loss_pct": 0.02,
            "use_sharpe_metric": True,
            "regime_sma_lookback": 200,
            "execution_time_bst": "08:00:00",
            "cost_model": "TRADING212_UK_ETF_ZERO_SDRT_ZERO_FX",
            "slippage_model": "SQUARE_ROOT_IMPACT_2BPS_BASE"
        }
        core_manifest_hash = "e5026d52086a5cdf5597cccbba96233a3f263411d84dea8bd3e36891d60be361"
        core_code_hash = "9f4942f11bd56a87cd2c651a24eff2f64a528d46f9ba95be7bb33b7589189929"

        core_entry = {
            "strategy_id": "PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1",
            "version": "PRV_CORE_COMPOUNDING_V1",
            "name": "London Multi-Asset SDRT-Exempt ETF Cross-Sectional Compounding Engine",
            "status": "RATIFIED_FOR_PRACTICE_PRODUCTION_INTEGRATION",
            "execution_mode": "PRACTICE",
            "config_hash": core_manifest_hash,
            "code_hash": core_code_hash,
            "rules": core_rules,
            "activation_timestamp": "2026-09-08T12:00:00Z",
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
        self._strategies["CORE_V1"] = core_entry
        self._strategies["PRV_CAUSAL_CROSS_SECTIONAL_ETF_V1"] = core_entry

    def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._strategies.get(strategy_id.upper())

    def get_all_strategies(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._strategies)

    def get_active_execution_strategy_id(self) -> str:
        return self._active_strategy_id

    def can_strategy_route_orders(self, strategy_id: str, bypass_gate: bool = False) -> bool:
        """
        Only the ratified active strategy has broker routing authority,
        and strictly when PRACTICE_NEW_ENTRIES_ALLOWED is explicitly enabled.
        Canary/diagnostic scripts can pass bypass_gate=True for single controlled validation.
        """
        from src.config.settings import settings
        strat = self.get_strategy(strategy_id)
        if not strat:
            return False
        if strat.get("execution_mode") != "PRACTICE" or strat.get("status") != "RATIFIED_FOR_PRACTICE_PRODUCTION_INTEGRATION":
            return False
        if strat.get("strategy_id") != self._active_strategy_id:
            return False
        if not getattr(settings, "PRACTICE_NEW_ENTRIES_ALLOWED", False) and not bypass_gate:
            return False
        return True

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
