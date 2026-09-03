from typing import Dict, Any, List, Tuple
from src.config.settings import settings
from src.database.db import db

class CapitalManager:
    """
    Phase 5 Capital & Regime Management Architecture:
    1. Core Capital: Active trading risk pool (NAV minus Vaulted Gains).
    2. Active Capital: Capital deployed in active market positions.
    3. Profit Vault: Realized gains swept on trade close and excluded from sizing.
    4. Regime Targets:
       - Bear Market: 15% - 30% (Target: 25% max deployment)
       - Neutral Market: 30% - 50% (Target: 45% max deployment)
       - Bull Market: 60% - 80% (Target: 75% max deployment)
    """
    def __init__(self, starting_capital: float = settings.STARTING_CAPITAL):
        self.starting_capital = starting_capital

    def get_capital_state(self, total_broker_nav: float, total_invested: float, available_cash: float) -> Dict[str, Any]:
        """Calculate three-tier capital states."""
        vault_balance = db.get_vault_balance()
        # Mandate Invariant: Active Trading Bankroll <= £50,000
        # Banked profit is non-deployable and ring-fenced outside the active strategy bankroll
        unvaulted_nav = max(0.0, total_broker_nav - vault_balance)
        core_capital = min(settings.MAX_DEPLOYABLE_TRADING_CAPITAL, unvaulted_nav)
        active_capital = total_invested
        idle_core_cash = max(0.0, min(available_cash, core_capital - active_capital))
        
        utilization_pct = (active_capital / core_capital * 100.0) if core_capital > 0 else 0.0
        base_deficit = max(0.0, round(settings.REFERENCE_BASE_CAPITAL - core_capital, 2))
        in_recovery = (core_capital < settings.REFERENCE_BASE_CAPITAL)
        total_transfers = db.get_total_capital_transfers()
        net_strat_profit = db.get_net_strategy_profit()
        topup_needed = (in_recovery and vault_balance > 0)
        proposed_topup = round(min(base_deficit, vault_balance), 2) if topup_needed else 0.0
        
        return {
            "starting_capital": self.starting_capital,
            "reference_base_capital": settings.REFERENCE_BASE_CAPITAL,
            "max_deployable_trading_capital": settings.MAX_DEPLOYABLE_TRADING_CAPITAL,
            "max_normal_deployable_capital": settings.MAX_NORMAL_DEPLOYABLE_CAPITAL,
            "total_broker_nav": round(total_broker_nav, 2),
            "core_capital": round(core_capital, 2),
            "active_trading_equity": round(core_capital, 2),
            "active_trading_bankroll": round(core_capital, 2),
            "base_capital_deficit": base_deficit,
            "in_recovery_mode": in_recovery,
            "active_capital": round(active_capital, 2),
            "idle_core_cash": round(idle_core_cash, 2),
            "profit_vault_balance": round(vault_balance, 2),
            "banked_profit": round(vault_balance, 2),
            "banked_profit_reserve": round(vault_balance, 2),
            "total_capital_transfers": round(total_transfers, 2),
            "net_strategy_profit": net_strat_profit,
            "banked_profit_is_non_deployable": settings.BANKED_PROFIT_IS_NON_DEPLOYABLE,
            "topup_permission_required": topup_needed,
            "proposed_topup_amount": proposed_topup,
            "capital_utilization_pct": round(utilization_pct, 2)
        }

    def determine_market_regime(self, market_breadth_score: float, sp500_trend_score: float) -> Tuple[str, float]:
        """
        Determine market regime and target deployment capacity:
        - BULL: 60% - 80% (Target: 75% max deployment)
        - NEUTRAL: 30% - 50% (Target: 45% max deployment)
        - BEAR: 15% - 30% (Target: 25% max deployment)
        """
        composite_regime_score = (market_breadth_score * 0.5) + (sp500_trend_score * 0.5)
        
        if composite_regime_score >= 70.0:
            return "BULL", settings.MAX_DEPLOYMENT_BULL
        elif composite_regime_score >= 45.0:
            return "NEUTRAL", settings.MAX_DEPLOYMENT_NEUTRAL
        else:
            return "BEAR", settings.MAX_DEPLOYMENT_BEAR

    def calculate_deployment_allowance(
        self,
        core_capital: float,
        active_capital: float,
        market_regime: str
    ) -> Tuple[float, float]:
        """Calculate maximum remaining deployable capital for current regime."""
        if market_regime == "BULL" or market_regime == "EXCEPTIONAL" or market_regime == "STRONG":
            target_pct = settings.MAX_DEPLOYMENT_BULL
        elif market_regime == "BEAR":
            target_pct = settings.MAX_DEPLOYMENT_BEAR
        else:
            target_pct = settings.MAX_DEPLOYMENT_NEUTRAL
            
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
        """Precise accounting of why every pound remains in cash."""
        idle_cash = available_cash
        breakdown = []
        
        cash_buffer = core_capital * settings.MIN_CASH_BUFFER_PCT
        breakdown.append({
            "bucket": "Cash Safety Buffer",
            "amount": round(cash_buffer, 2),
            "pct_of_idle": round((cash_buffer / idle_cash * 100.0) if idle_cash > 0 else 0.0, 1),
            "status": "LOCKED_RISK_RULE",
            "reason": "Hard rule: 5% liquidity reserve preserved for margin safety and slippage buffer",
            "deploy_condition": "Never deployed (permanent liquidity safeguard)"
        })
        
        if market_regime == "BULL" or market_regime == "EXCEPTIONAL" or market_regime == "STRONG":
            target_pct = settings.MAX_DEPLOYMENT_BULL
            deploy_cond = "Maximum Bull allocation capacity (75% of Core Capital). 20% preserved as macro volatility safeguard."
        elif market_regime == "BEAR":
            target_pct = settings.MAX_DEPLOYMENT_BEAR
            deploy_cond = "Requires Market Regime upgrade to NEUTRAL / BULL (Breadth > 45%, S&P 500 trend recovery)."
        else:
            target_pct = settings.MAX_DEPLOYMENT_NEUTRAL
            deploy_cond = "Requires Market Regime upgrade to BULL (S&P 500 breakout + breadth > 70%)."

        unallocated_regime_reserve = max(0.0, core_capital * (1.0 - target_pct) - cash_buffer)
        
        if unallocated_regime_reserve > 0:
            breakdown.append({
                "bucket": f"Regime Macro Reserve ({market_regime})",
                "amount": round(unallocated_regime_reserve, 2),
                "pct_of_idle": round((unallocated_regime_reserve / idle_cash * 100.0) if idle_cash > 0 else 0.0, 1),
                "status": "MACRO_GATED",
                "reason": f"Regime is {market_regime} (capping active exposure at {target_pct * 100:.0f}% of Core Capital)",
                "deploy_condition": deploy_cond
            })

        active_deployable_queue = max(0.0, idle_cash - cash_buffer - unallocated_regime_reserve)
        breakdown.append({
            "bucket": "High-Conviction Opportunity Queue",
            "amount": round(active_deployable_queue, 2),
            "pct_of_idle": round((active_deployable_queue / idle_cash * 100.0) if idle_cash > 0 else 0.0, 1),
            "status": "AWAITING_SIGNAL_TRIGGER",
            "reason": "Allocated for top-ranked candidate entries and scale-in executions (3% - 8% dynamic sizing)",
            "deploy_condition": "Deploys when candidates achieve Technical Confidence >= 65.0% and Net R:R >= 3.0"
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
