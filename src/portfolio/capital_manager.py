from typing import Dict, Any, List, Tuple
from src.config.settings import settings
from src.database.db import db

class CapitalManager:
    """
    PRV Capital Three-Tier Capital Architecture:
    1. Core Capital: Active trading risk pool (NAV minus Vaulted Gains).
    2. Active Capital: Capital deployed in active market positions.
    3. Profit Vault: Realized gains swept on trade close and excluded from sizing.
    """
    def __init__(self, starting_capital: float = settings.STARTING_CAPITAL):
        self.starting_capital = starting_capital

    def get_capital_state(self, total_broker_nav: float, total_invested: float, available_cash: float) -> Dict[str, Any]:
        """Calculate three-tier capital states."""
        vault_balance = db.get_vault_balance()
        
        core_capital = max(0.0, total_broker_nav - vault_balance)
        active_capital = total_invested
        idle_core_cash = max(0.0, available_cash - vault_balance)
        
        utilization_pct = (active_capital / core_capital * 100.0) if core_capital > 0 else 0.0
        
        return {
            "starting_capital": self.starting_capital,
            "total_broker_nav": round(total_broker_nav, 2),
            "core_capital": round(core_capital, 2),
            "active_capital": round(active_capital, 2),
            "idle_core_cash": round(idle_core_cash, 2),
            "profit_vault_balance": round(vault_balance, 2),
            "capital_utilization_pct": round(utilization_pct, 2)
        }

    def determine_market_regime(self, market_breadth_score: float, sp500_trend_score: float) -> Tuple[str, float]:
        """
        Determine market regime and target deployment capacity:
        - NEUTRAL: 20% - 40% (Target: 35% max deployment)
        - STRONG: 40% - 70% (Target: 65% max deployment)
        - EXCEPTIONAL: 70% - 85% (Target: 80% max deployment)
        """
        composite_regime_score = (market_breadth_score * 0.5) + (sp500_trend_score * 0.5)
        
        if composite_regime_score >= 80.0:
            return "EXCEPTIONAL", 0.80
        elif composite_regime_score >= 50.0:
            return "STRONG", 0.65
        else:
            return "NEUTRAL", 0.35

    def calculate_deployment_allowance(
        self,
        core_capital: float,
        active_capital: float,
        market_regime: str
    ) -> Tuple[float, float]:
        """Calculate maximum remaining deployable capital for current regime."""
        if market_regime == "EXCEPTIONAL":
            target_pct = 0.80
        elif market_regime == "STRONG":
            target_pct = 0.65
        else:
            target_pct = 0.35
            
        max_allowed_active = core_capital * target_pct
        remaining_allowance = max(0.0, max_allowed_active - active_capital)
        
        return round(remaining_allowance, 2), target_pct

    def generate_idle_cash_audit(
        self,
        core_capital: float,
        available_cash: float,
        active_capital: float,
        market_regime: str,
        rejected_candidates: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Precise accounting of why every pound remains in cash:
        Breaks down idle cash into exact buckets and conditions required to deploy.
        """
        idle_cash = available_cash
        breakdown = []
        
        # 1. Mandatory 5% Cash Safety Buffer
        cash_buffer = core_capital * settings.MIN_CASH_BUFFER_PCT
        breakdown.append({
            "bucket": "Cash Safety Buffer",
            "amount": round(cash_buffer, 2),
            "pct_of_idle": round((cash_buffer / idle_cash * 100.0) if idle_cash > 0 else 0.0, 1),
            "status": "LOCKED_RISK_RULE",
            "reason": "Hard rule: 5% liquidity reserve preserved for margin safety and slippage buffer",
            "deploy_condition": "Never deployed (permanent liquidity safeguard)"
        })
        
        # 2. Regime Capacity Reserve (Capital held back based on macro regime)
        _, target_pct = self.determine_market_regime(70.0, 75.0)
        regime_max_invested = core_capital * target_pct
        unallocated_regime_reserve = max(0.0, core_capital * (1.0 - target_pct) - cash_buffer)
        
        if unallocated_regime_reserve > 0:
            breakdown.append({
                "bucket": f"Regime Macro Reserve ({market_regime})",
                "amount": round(unallocated_regime_reserve, 2),
                "pct_of_idle": round((unallocated_regime_reserve / idle_cash * 100.0) if idle_cash > 0 else 0.0, 1),
                "status": "MACRO_GATED",
                "reason": f"Regime is {market_regime} (capping active exposure at {target_pct * 100:.0f}% of Core Capital)",
                "deploy_condition": "Requires Market Regime upgrade to EXCEPTIONAL (S&P 500 breakout + breadth > 80%)"
            })

        # 3. Active Opportunity Deployment Queue (Capital immediately available for high-conviction signals)
        active_deployable_queue = max(0.0, idle_cash - cash_buffer - unallocated_regime_reserve)
        breakdown.append({
            "bucket": "High-Conviction Opportunity Queue",
            "amount": round(active_deployable_queue, 2),
            "pct_of_idle": round((active_deployable_queue / idle_cash * 100.0) if idle_cash > 0 else 0.0, 1),
            "status": "AWAITING_SIGNAL_TRIGGER",
            "reason": "Allocated for top-ranked candidate entries and scale-in executions",
            "deploy_condition": "Deploys when universe candidates achieve Confidence >= 70.0% and Net R:R >= 3.0"
        })

        return breakdown

    def process_realized_trade(self, trade_id: str, symbol: str, realized_pnl: float) -> Dict[str, Any]:
        """On trade close: Sweep 100% of realized gain to Profit Vault."""
        if realized_pnl > 0:
            new_vault_total = db.deposit_profit_vault(
                trade_id=trade_id,
                symbol=symbol,
                realized_profit=realized_pnl,
                notes="Automated profit sweep from closed position."
            )
            return {"vaulted": True, "amount": realized_pnl, "new_vault_total": new_vault_total}
        return {"vaulted": False, "amount": 0.0, "realized_loss": realized_pnl}

capital_manager = CapitalManager()
