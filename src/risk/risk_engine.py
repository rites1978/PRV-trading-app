from typing import Dict, Any, List, Tuple
from src.config.settings import settings
from src.database.db import db
from src.brokers.trading212 import broker

class ExposureBasedRiskEngine:
    """
    Institutional Risk Engine with Progressive Active De-Risking:
    1. Tier 1 Drawdown (3.0%): Halts new buying & evaluates trimming losing/high-beta positions by 50%.
    2. Tier 2 Hard Circuit Breaker (5.0%): Enforces Full Capital Protection & active liquidation of losing risk assets.
    3. Portfolio Value-at-Risk (VaR) Budgeting (Max 5.0% Core Capital).
    4. Position & Sector Concentration Exposure Caps.
    """
    def __init__(
        self,
        tier1_drawdown_pct: float = 0.03,
        max_daily_drawdown: float = settings.MAX_DAILY_DRAWDOWN_PCT,
        max_position_cap_pct: float = settings.MAX_POSITION_SIZE_PCT,
        max_sector_pct: float = settings.MAX_SECTOR_EXPOSURE_PCT,
        max_portfolio_risk_budget_pct: float = 0.05
    ):
        self.tier1_drawdown_pct = tier1_drawdown_pct
        self.max_daily_drawdown = max_daily_drawdown
        self.max_position_cap_pct = max_position_cap_pct
        self.max_sector_pct = max_sector_pct
        self.max_portfolio_risk_budget_pct = max_portfolio_risk_budget_pct
        self.day_start_nav: float = 0.0
        self.tier1_triggered: bool = False
        self.circuit_breaker_tripped: bool = False

    def initialize_day(self, starting_nav: float):
        self.day_start_nav = starting_nav
        self.tier1_triggered = False
        self.circuit_breaker_tripped = False

    def check_circuit_breaker(self, current_nav: float) -> Tuple[bool, str]:
        """Check circuit breaker (backwards compatibility)."""
        safe, msg, _ = self.evaluate_active_derisking(current_nav, [])
        return safe, msg

    def evaluate_active_derisking(
        self,
        current_nav: float,
        open_positions: List[Dict[str, Any]],
        is_paper: bool = False
    ) -> Tuple[bool, str, List[str]]:
        """
        Progressive Circuit Breaker:
        Actively sheds risk and reduces portfolio exposure when drawdown thresholds are breached.
        """
        if self.day_start_nav <= 0:
            self.day_start_nav = current_nav
            return True, "Session initialized.", []

        drawdown = (self.day_start_nav - current_nav) / self.day_start_nav
        derisked_tickers = []

        # Tier 2: Hard Circuit Breaker (5.0% Drawdown) -> Liquidate losing positions & lock down
        if drawdown >= self.max_daily_drawdown:
            self.circuit_breaker_tripped = True
            db.record_risk_event(
                event_type="CIRCUIT_BREAKER_TIER_2",
                severity="CRITICAL",
                description=f"Hard daily drawdown limit reached {drawdown * 100:.2f}% (Limit: {self.max_daily_drawdown * 100:.1f}%). Liquidating losing holdings and engaging full capital protection.",
                portfolio_value=current_nav,
                action_taken="FULL_CAPITAL_PROTECTION"
            )

            # Actively liquidate losing positions to preserve capital
            for pos in open_positions:
                ticker = pos.get("ticker")
                qty = float(pos.get("quantity", 0))
                ppl = float(pos.get("ppl", 0))
                if ppl < 0 and qty > 0:
                    if not is_paper:
                        broker.place_market_order(ticker, -qty)
                    derisked_tickers.append(ticker)

            return False, f"🚨 TIER 2 CIRCUIT BREAKER: Drawdown {drawdown * 100:.2f}% breached 5.0% limit. Active de-risking executed.", derisked_tickers

        # Tier 1: Warning Drawdown (3.0%) -> Trim losing positions by 50% to reduce gross exposure
        elif drawdown >= self.tier1_drawdown_pct and not self.tier1_triggered:
            self.tier1_triggered = True
            db.record_risk_event(
                event_type="CIRCUIT_BREAKER_TIER_1",
                severity="WARNING",
                description=f"Drawdown reached Tier 1 threshold of {drawdown * 100:.2f}%. Trimming losing positions by 50% to reduce gross portfolio exposure.",
                portfolio_value=current_nav,
                action_taken="TRIM_EXPOSURE_50_PCT"
            )

            for pos in open_positions:
                ticker = pos.get("ticker")
                qty = float(pos.get("quantity", 0))
                ppl = float(pos.get("ppl", 0))
                if ppl < 0 and qty > 0:
                    trim_qty = round(qty * 0.5, 2) if qty >= 1.0 else round(qty * 0.5, 4)
                    if trim_qty > 0:
                        if not is_paper:
                            broker.place_market_order(ticker, -trim_qty)
                        derisked_tickers.append(f"{ticker} (-50%)")

            return True, f"⚠️ TIER 1 RISK SHEDDING: Drawdown {drawdown * 100:.2f}%. Trimmed 50% exposure on losing positions.", derisked_tickers

        return True, f"Drawdown nominal ({drawdown * 100:+.2f}%).", []

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

        if self.tier1_triggered:
            return False, "VETO: Tier 1 drawdown active. New buying paused until recovery."

        # Phase 47 Forward Validation Protocol: 10-Day Post-Stop Cooldown for Trades 51+
        historical_trades = db.get_trades(limit=500)
        if len(historical_trades) >= 50:
            from datetime import datetime, timezone
            for t in historical_trades:
                if t.get("symbol") == symbol or t.get("symbol") == t212_ticker:
                    t_time_str = t.get("timestamp", "")
                    if t_time_str:
                        try:
                            t_time = datetime.fromisoformat(t_time_str.replace("Z", "+00:00"))
                            if t_time.tzinfo is None:
                                t_time = t_time.replace(tzinfo=timezone.utc)
                            now = datetime.now(timezone.utc)
                            days_since = (now - t_time).total_seconds() / 86400.0
                            if days_since < 10.0 and "STOP" in t.get("trade_reason", ""):
                                return False, f"VETO: 10-Day Cooldown active for '{symbol}' ({days_since:.1f}/10.0 days elapsed since stop-loss exit)."
                        except Exception:
                            pass
                    break

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

# Aliases
RiskEngine = ExposureBasedRiskEngine
risk_engine = ExposureBasedRiskEngine()
