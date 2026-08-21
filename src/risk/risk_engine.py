from typing import Dict, Any, List, Tuple
from datetime import datetime
from src.config.settings import settings
from src.database.db import db

class RiskEngine:
    """
    PRV Capital Institutional Risk & Exposure Engine:
    - 5% Hard Daily Drawdown Circuit Breaker
    - Target Position Sizing: 6% (~£3,000) of Core Capital
    - Max Position Sizing Cap: 8% (~£4,000) of Core Capital
    - Sector Concentration Caps: Max 30% of Core Capital per sector
    - Dynamic Concurrency Cap: Up to 40 positions
    - Trailing Stop-Loss & Take-Profit validation
    - Absolute Veto Authority
    """
    def __init__(
        self,
        max_daily_drawdown: float = settings.MAX_DAILY_DRAWDOWN_PCT,
        target_position_pct: float = settings.TARGET_POSITION_SIZE_PCT,
        max_position_pct: float = settings.MAX_POSITION_SIZE_PCT,
        max_sector_pct: float = settings.MAX_SECTOR_EXPOSURE_PCT,
        max_positions: int = settings.MAX_CONCURRENT_POSITIONS
    ):
        self.max_daily_drawdown = max_daily_drawdown
        self.target_position_pct = target_position_pct
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
        self.max_positions = max_positions
        self.day_start_nav: float = 0.0
        self.circuit_breaker_tripped: bool = False

    def initialize_day(self, starting_nav: float):
        self.day_start_nav = starting_nav
        self.circuit_breaker_tripped = False

    def check_circuit_breaker(self, current_nav: float) -> Tuple[bool, str]:
        """Check if 5% Daily Drawdown Circuit Breaker is triggered."""
        if self.day_start_nav <= 0:
            self.day_start_nav = current_nav
            return True, "Day initialized."

        drawdown = (self.day_start_nav - current_nav) / self.day_start_nav
        if drawdown >= self.max_daily_drawdown:
            self.circuit_breaker_tripped = True
            db.record_risk_event(
                event_type="CIRCUIT_BREAKER_TRIPPED",
                severity="CRITICAL",
                description=f"Daily drawdown reached {drawdown * 100:.2f}% (Limit: {self.max_daily_drawdown * 100:.1f}%). All trading halted.",
                portfolio_value=current_nav,
                action_taken="ENTER_CAPITAL_PROTECTION_MODE"
            )
            return False, f"🚨 5% DAILY DRAWDOWN LIMIT REACHED: Drawdown is {drawdown * 100:.2f}%. Trading permanently blocked for current session."
        
        return True, f"Risk within parameters. Daily drawdown: {drawdown * 100:+.2f}%."

    def calculate_target_position_capital(self, core_capital: float) -> float:
        """Target nominal capital deployment for a single position (~£3,000)."""
        return core_capital * self.target_position_pct

    def calculate_max_position_capital(self, core_capital: float) -> float:
        """Maximum allowable nominal capital for a single position (~£4,000)."""
        return core_capital * self.max_position_pct

    def validate_new_order(
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
        """Comprehensive Risk Veto Validation."""
        # 1. Circuit Breaker Check
        if self.circuit_breaker_tripped:
            return False, "VETO: Circuit breaker active. Capital protection mode engaged."

        # 2. Concurrency Check
        if len(current_positions) >= self.max_positions:
            return False, f"VETO: Maximum portfolio concurrency ({self.max_positions} positions) reached."

        # 3. Position Sizing Cap (Max 8% of Core Capital)
        existing_pos = next((p for p in current_positions if p.get("symbol") == symbol or p.get("ticker") == t212_ticker), None)
        current_holding_val = 0.0
        if existing_pos:
            current_holding_val = float(existing_pos.get("quantity", 0)) * float(existing_pos.get("currentPrice", 0))

        max_pos_size = self.calculate_max_position_capital(core_capital)
        if (current_holding_val + order_cost) > max_pos_size:
            return False, f"VETO: Total position value (£{current_holding_val + order_cost:.2f}) exceeds maximum position limit of £{max_pos_size:.2f} (8% of Core Capital)."

        # 4. Cash Buffer Check
        min_cash_required = core_capital * settings.MIN_CASH_BUFFER_PCT
        if (available_cash - order_cost) < min_cash_required:
            return False, f"VETO: Order cost (£{order_cost:.2f}) breaches minimum cash safety buffer of £{min_cash_required:.2f}."

        # 5. Sector Concentration Check (Max 30% of Core Capital)
        current_sector_exposure = sum(
            float(p.get("currentPrice", 0)) * float(p.get("quantity", 0))
            for p in current_positions if p.get("sector") == sector
        )
        max_sector_size = core_capital * self.max_sector_pct
        if (current_sector_exposure + order_cost) > max_sector_size:
            return False, f"VETO: Sector exposure for '{sector}' (£{current_sector_exposure + order_cost:.2f}) exceeds limit of £{max_sector_size:.2f} (30%)."

        # 6. Dynamic Regime Deployment Cap Check
        if order_cost > remaining_regime_allowance:
            return False, f"VETO: Order cost (£{order_cost:.2f}) exceeds remaining dynamic regime deployment allowance of £{remaining_regime_allowance:.2f}."

        return True, "Risk validation approved."

    def calculate_position_units(
        self,
        price: float,
        core_capital: float,
        available_cash: float,
        remaining_allowance: float,
        current_holding_val: float = 0.0
    ) -> float:
        """
        Calculate target share units to scale or deploy capital up to target allocation (~£3,000).
        """
        if price <= 0:
            return 0.0

        target_allocation = self.calculate_target_position_capital(core_capital)
        needed_capital = max(0.0, target_allocation - current_holding_val)
        
        deployable = min(needed_capital, available_cash * 0.90, remaining_allowance)
        
        if deployable < price * 0.5:
            return 0.0

        quantity = deployable / price
        return round(quantity, 2) if quantity >= 1.0 else round(quantity, 4)

risk_engine = RiskEngine()
