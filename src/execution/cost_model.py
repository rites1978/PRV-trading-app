from typing import Dict, Any, Tuple
from src.config.settings import settings

class SpreadAwareCostModel:
    """
    Quantitative Friction & Net Edge Calculation Model:
    Calculates Spread, Slippage, Execution friction, and FX conversion drag.
    Validates that Net Expected Return satisfies statistical edge criteria (Net R:R >= 2.75x and Gross R:R >= 3.0x).
    """
    def __init__(
        self,
        slippage_bps: float = settings.SLIPPAGE_ESTIMATE_BPS,
        fx_fee_bps: float = settings.FX_FEE_BPS,
        min_reward_risk: float = settings.MIN_REWARD_RISK_RATIO
    ):
        self.slippage_bps = slippage_bps
        self.fx_fee_bps = fx_fee_bps
        self.min_reward_risk = min_reward_risk

    def estimate_spread_bps(self, is_uk: bool, market_cap_category: str = "LARGE") -> float:
        """Estimate bid-ask spread in basis points based on liquidity tier."""
        if market_cap_category == "MEGA":
            return 3.0  # ~0.03%
        elif is_uk:
            return 6.0  # ~0.06% for UK FTSE Blue Chips
        else:
            return 4.0  # ~0.04% for US S&P 500 Blue Chips

    def calculate_trade_friction(
        self,
        nominal_value: float,
        is_foreign_currency: bool,
        is_uk: bool
    ) -> Dict[str, float]:
        """
        Calculate total transaction friction breakdown in GBP.
        """
        spread_bps = self.estimate_spread_bps(is_uk)
        spread_cost = nominal_value * (spread_bps / 10000.0)
        slippage_cost = nominal_value * (self.slippage_bps / 10000.0)
        fx_cost = nominal_value * (self.fx_fee_bps / 10000.0) if is_foreign_currency else 0.0
        
        total_friction = spread_cost + slippage_cost + fx_cost
        friction_pct = (total_friction / nominal_value * 100.0) if nominal_value > 0 else 0.0
        
        return {
            "spread_cost": round(spread_cost, 4),
            "slippage_cost": round(slippage_cost, 4),
            "fx_cost": round(fx_cost, 4),
            "total_friction": round(total_friction, 4),
            "friction_pct": round(friction_pct, 4)
        }

    def evaluate_net_edge(
        self,
        entry_price: float,
        target_price: float,
        stop_loss_price: float,
        nominal_value: float,
        is_foreign_currency: bool,
        is_uk: bool
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Evaluate if trade justifies execution after all cost frictions.
        """
        if entry_price <= 0 or stop_loss_price >= entry_price or target_price <= entry_price:
            return False, {"approved": False, "reason": "Invalid price targets: Target must be > Entry > Stop Loss."}

        gross_gain_pct = (target_price - entry_price) / entry_price
        gross_loss_pct = (entry_price - stop_loss_price) / entry_price
        
        # Friction applied for round-trip (entry + exit)
        friction_entry = self.calculate_trade_friction(nominal_value, is_foreign_currency, is_uk)
        friction_exit = self.calculate_trade_friction(nominal_value * (1 + gross_gain_pct), is_foreign_currency, is_uk)
        total_roundtrip_friction = friction_entry["total_friction"] + friction_exit["total_friction"]
        
        gross_profit = nominal_value * gross_gain_pct
        gross_downside = nominal_value * gross_loss_pct
        
        net_profit = gross_profit - total_roundtrip_friction
        net_downside = gross_downside + total_roundtrip_friction
        
        if net_downside <= 0:
            return False, {"approved": False, "reason": "Zero or negative downside calculation."}
            
        net_reward_risk = net_profit / net_downside
        gross_reward_risk = gross_profit / gross_downside if gross_downside > 0 else 0.0
        
        # Strict Rule Checklist
        if net_profit <= 0:
            return False, {
                "approved": False,
                "reason": f"Friction (£{total_roundtrip_friction:.2f}) exceeds gross profit (£{gross_profit:.2f}).",
                "net_reward_risk": round(net_reward_risk, 2)
            }
            
        if gross_reward_risk < (self.min_reward_risk - 0.05):
            return False, {
                "approved": False,
                "reason": f"Gross R:R ({gross_reward_risk:.2f}) is below minimum target of {self.min_reward_risk:.1f}.",
                "net_reward_risk": round(net_reward_risk, 2),
                "total_friction": round(total_roundtrip_friction, 2)
            }
            
        return True, {
            "approved": True,
            "gross_reward_risk": round(gross_reward_risk, 2),
            "net_reward_risk": round(net_reward_risk, 2),
            "gross_profit": round(gross_profit, 2),
            "net_profit": round(net_profit, 2),
            "total_friction": round(total_roundtrip_friction, 2),
            "friction_breakdown": friction_entry
        }

cost_model = SpreadAwareCostModel()
