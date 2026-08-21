from typing import Dict, Any, List, Tuple
from src.config.settings import settings
from src.database.db import db

class ExposureBasedRiskEngine:
    """
    Exposure-Based Quantitative Risk Engine:
    Replaces arbitrary ticker count limits with:
    1. 5% Hard Daily Drawdown Circuit Breaker
    2. Portfolio Capital at Risk (Total VaR Budget <= 5.0% of Core Capital)
    3. Single Position Capital Cap (Max 8.0% = ~£4,000)
    4. Sector Concentration Exposure Cap (Max 30.0% = ~£15,000)
    5. Dynamic Market Regime Deployment Capacity
    """
    def __init__(
        self,
        max_daily_drawdown: float = settings.MAX_DAILY_DRAWDOWN_PCT,
        max_position_cap_pct: float = settings.MAX_POSITION_SIZE_PCT,
        max_sector_pct: float = settings.MAX_SECTOR_EXPOSURE_PCT,
        max_portfolio_risk_budget_pct: float = 0.05
    ):
        self.max_daily_drawdown = max_daily_drawdown
        self.max_position_cap_pct = max_position_cap_pct
        self.max_sector_pct = max_sector_pct
        self.max_portfolio_risk_budget_pct = max_portfolio_risk_budget_pct
        self.day_start_nav: float = 0.0
        self.circuit_breaker_tripped: bool = False

    def initialize_day(self, starting_nav: float):
        self.day_start_nav = starting_nav
        self.circuit_breaker_tripped = False

    def check_circuit_breaker(self, current_nav: float) -> Tuple[bool, str]:
        """Check if 5% Daily Drawdown Circuit Breaker is triggered."""
        if self.day_start_nav <= 0:
            self.day_start_nav = current_nav
            return True, "Session initialized."

        drawdown = (self.day_start_nav - current_nav) / self.day_start_nav
        if drawdown >= self.max_daily_drawdown:
            self.circuit_breaker_tripped = True
            db.record_risk_event(
                event_type="CIRCUIT_BREAKER_TRIPPED",
                severity="CRITICAL",
                description=f"Daily drawdown reached {drawdown * 100:.2f}% (Limit: {self.max_daily_drawdown * 100:.1f}%). All buying halted.",
                portfolio_value=current_nav,
                action_taken="ENTER_CAPITAL_PROTECTION_MODE"
            )
            return False, f"🚨 5% DAILY DRAWDOWN LIMIT REACHED: Drawdown is {drawdown * 100:.2f}%. Trading permanently blocked."
        
        return True, f"Risk parameters nominal. Daily drawdown: {drawdown * 100:+.2f}%."

    def calculate_portfolio_capital_at_risk(self, current_positions: List[Dict[str, Any]]) -> float:
        """Calculate total capital at risk if all open positions hit their stop-losses."""
        total_risk = 0.0
        for pos in current_positions:
            qty = float(pos.get("quantity", 0))
            avg_p = float(pos.get("averagePrice", 0))
            stop_p = avg_p * (1.0 - settings.DEFAULT_STOP_LOSS_PCT)
            pos_risk = qty * (avg_p - stop_p)
            total_risk += max(0.0, pos_risk)
        return total_risk

    def validate_exposure_order(
        self,
        symbol: str,
        t212_ticker: str,
        sector: str,
        order_cost: float,
        core_capital: float,
        available_cash: float,
        current_positions: List[Dict[str, Any]],
        remaining_regime_allowance: float
    ) -> Tuple[bool, str]:
        """Pure exposure and risk validation without position count constraints."""
        if self.circuit_breaker_tripped:
            return False, "VETO: Circuit breaker active. Capital protection mode engaged."

        min_cash_required = core_capital * settings.MIN_CASH_BUFFER_PCT
        if (available_cash - order_cost) < min_cash_required:
            return False, f"VETO: Order cost (£{order_cost:.2f}) breaches minimum cash safety buffer of £{min_cash_required:.2f}."

        existing_pos = next((p for p in current_positions if p.get("symbol") == symbol or p.get("ticker") == t212_ticker), None)
        current_holding_val = 0.0
        if existing_pos:
            current_holding_val = float(existing_pos.get("quantity", 0)) * float(existing_pos.get("currentPrice", 0))

        max_pos_cap = core_capital * self.max_position_cap_pct
        if (current_holding_val + order_cost) > (max_pos_cap + 1.0):
            return False, f"VETO: Total position value (£{current_holding_val + order_cost:.2f}) exceeds maximum position cap of £{max_pos_cap:.2f} (8% of Core Capital)."

        current_sector_exposure = sum(
            float(p.get("currentPrice", 0)) * float(p.get("quantity", 0))
            for p in current_positions if p.get("sector") == sector or p.get("ticker") == t212_ticker
        )
        max_sector_cap = core_capital * self.max_sector_pct
        if (current_sector_exposure + order_cost) > (max_sector_cap + 1.0):
            return False, f"VETO: Sector exposure for '{sector}' (£{current_sector_exposure + order_cost:.2f}) exceeds limit of £{max_sector_cap:.2f} (30%)."

        order_risk = order_cost * settings.DEFAULT_STOP_LOSS_PCT
        current_var = self.calculate_portfolio_capital_at_risk(current_positions)
        max_allowed_var = core_capital * self.max_portfolio_risk_budget_pct
        if (current_var + order_risk) > max_allowed_var:
            return False, f"VETO: Total portfolio risk (£{current_var + order_risk:.2f}) exceeds max VaR budget of £{max_allowed_var:.2f} (5% of Core Capital)."

        if order_cost > (remaining_regime_allowance + 1.0):
            return False, f"VETO: Order cost (£{order_cost:.2f}) exceeds remaining dynamic regime capacity of £{remaining_regime_allowance:.2f}."

        return True, "Risk validation approved."

# Backward compatibility alias
RiskEngine = ExposureBasedRiskEngine
risk_engine = ExposureBasedRiskEngine()
