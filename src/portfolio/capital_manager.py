from typing import Dict, Any, Tuple
from src.config.settings import settings
from src.database.db import db

class CapitalManager:
    """
    PRV Capital Three-Tier Capital Architecture:
    1. Core Capital: The active risk pool used for position sizing and trading (Baseline: £50,000 max minus losses).
    2. Active Capital: Total capital currently deployed across open market positions.
    3. Profit Vault: Realized gains locked and completely excluded from future position sizing.
    """
    def __init__(self, starting_capital: float = settings.STARTING_CAPITAL):
        self.starting_capital = starting_capital

    def get_capital_state(self, total_broker_nav: float, total_invested: float, available_cash: float) -> Dict[str, Any]:
        """
        Calculate three-tier capital states.
        """
        vault_balance = db.get_vault_balance()
        
        # Core Capital is total broker NAV minus secured Profit Vault
        core_capital = max(0.0, total_broker_nav - vault_balance)
        active_capital = total_invested
        idle_core_cash = max(0.0, available_cash - vault_balance)
        
        utilization_pct = (active_capital / core_capital * 100.0) if core_capital > 0 else 0.0
        
        return {
            "starting_capital": self.starting_capital,
            "total_broker_nav": total_broker_nav,
            "core_capital": round(core_capital, 2),
            "active_capital": round(active_capital, 2),
            "idle_core_cash": round(idle_core_cash, 2),
            "profit_vault_balance": round(vault_balance, 2),
            "capital_utilization_pct": round(utilization_pct, 2)
        }

    def determine_market_regime(self, market_breadth_score: float, sp500_trend_score: float) -> Tuple[str, float]:
        """
        Determine market regime and target deployment capacity:
        - NEUTRAL: 20% max deployment target
        - STRONG: 50% max deployment target
        - EXCEPTIONAL: 80% max deployment target
        """
        composite_regime_score = (market_breadth_score * 0.5) + (sp500_trend_score * 0.5)
        
        if composite_regime_score >= 80.0:
            return "EXCEPTIONAL", settings.MAX_DEPLOYMENT_EXCEPTIONAL
        elif composite_regime_score >= 50.0:
            return "STRONG", settings.MAX_DEPLOYMENT_STRONG
        else:
            return "NEUTRAL", settings.MAX_DEPLOYMENT_NEUTRAL

    def calculate_deployment_allowance(
        self,
        core_capital: float,
        active_capital: float,
        market_regime: str
    ) -> Tuple[float, float]:
        """
        Calculate maximum remaining deployable capital for new positions under current market regime.
        Returns: (remaining_allowance: float, target_deployment_pct: float)
        """
        if market_regime == "EXCEPTIONAL":
            target_pct = settings.MAX_DEPLOYMENT_EXCEPTIONAL
        elif market_regime == "STRONG":
            target_pct = settings.MAX_DEPLOYMENT_STRONG
        else:
            target_pct = settings.MAX_DEPLOYMENT_NEUTRAL
            
        max_allowed_active = core_capital * target_pct
        remaining_allowance = max(0.0, max_allowed_active - active_capital)
        
        return round(remaining_allowance, 2), target_pct

    def process_realized_trade(self, trade_id: str, symbol: str, realized_pnl: float) -> Dict[str, Any]:
        """
        On trade close:
        - If profit > 0: Automatically deposit 100% into Profit Vault.
        - Profit Vault cannot be reused and is removed from trading risk pool.
        """
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
