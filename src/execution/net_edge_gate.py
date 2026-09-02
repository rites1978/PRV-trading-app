"""
🏛️ PRV CAPITAL | HARD NET EDGE GATE & CONTEXTUAL SPREAD/FRICTION FILTER
Enforces strict net profitability hurdles before any order may be submitted.

Mandatory Gating Conditions to Trade:
1. predicted_net_return > 0 (Gross return minus all transaction friction)
2. Net Reward-to-Risk >= 2.0x (expected_net_profit / expected_net_downside)
3. Cost-to-Expected-Profit Ratio <= 30% (Total transaction friction consumes <= 30% of profit)
4. Contextual Spread Friction Ratio <= 15% (Spread drag consumes <= 15% of expected target move)
5. Emergency Liquidity Ceiling (Spread <= 50 bps circuit breaker)
6. Fundamental Outlook >= Neutral (Score >= 50)
7. Technical Trend == Supportive (Score >= 50)
8. Minimum Liquidity verified (Daily volume >= £500,000)

If ANY condition fails:
ACTION = "HOLD CASH" (Capital Preservation Cash)
Populates detailed "Why Not Trade?" rejection dossier.
"""
from typing import Dict, Any, List, Tuple, Optional
from src.config.settings import settings
from src.execution.cost_model import cost_model


class NetEdgeGate:
    """
    Evaluates candidate setups against hard net profitability hurdles.
    Prioritizes Capital Preservation and Net Gain Realization over trade volume.
    """
    def __init__(
        self,
        min_net_reward_risk: float = settings.MIN_NET_REWARD_RISK_RATIO,
        max_cost_to_profit_ratio: float = settings.MAX_COST_TO_PROFIT_RATIO_PCT / 100.0,
        max_spread_to_profit_ratio: float = settings.MAX_SPREAD_TO_PROFIT_RATIO_PCT / 100.0,
        max_emergency_spread_pct: float = settings.MAX_EMERGENCY_SPREAD_BPS / 10000.0
    ):
        self.min_net_reward_risk = min_net_reward_risk
        self.max_cost_to_profit_ratio = max_cost_to_profit_ratio
        self.max_spread_to_profit_ratio = max_spread_to_profit_ratio
        self.max_emergency_spread_pct = max_emergency_spread_pct

    def evaluate_candidate(
        self,
        symbol: str,
        entry_price: float,
        target_price: float,
        stop_loss_price: float,
        nominal_value: float,
        is_uk: bool,
        is_foreign: bool,
        instrument_type: str = "EQUITY",
        current_spread_pct: float = 0.0006,
        fundamental_score: float = 80.0,
        technical_score: float = 80.0,
        catalyst_score: float = 80.0,
        avg_daily_volume_gbp: float = 5000000.0
    ) -> Dict[str, Any]:
        """
        Executes complete Net Edge Gate audit on target candidate.
        """
        rejection_reasons: List[str] = []

        if entry_price <= 0 or target_price <= entry_price or stop_loss_price >= entry_price:
            return {
                "approved": False,
                "action": "HOLD CASH",
                "symbol": symbol,
                "rejection_reasons": ["Invalid price targets: Target must exceed Entry, and Entry must exceed Stop Loss."],
                "predicted_net_return": 0.0,
                "cost_to_profit_ratio": 1.0,
                "decision": "DO NOTHING / HOLD CASH"
            }

        # 1. Gross Return & Downside Math
        gross_return_pct = (target_price - entry_price) / entry_price
        gross_loss_pct = (entry_price - stop_loss_price) / entry_price

        expected_gross_profit = nominal_value * gross_return_pct
        expected_gross_loss = nominal_value * gross_loss_pct

        # 2. Complete Transaction Friction Math
        exit_value_target = nominal_value * (1.0 + gross_return_pct)
        friction_data = cost_model.calculate_round_trip_friction(
            entry_value=nominal_value,
            exit_value=exit_value_target,
            is_uk=is_uk,
            is_foreign=is_foreign,
            instrument_type=instrument_type,
            custom_spread_pct=current_spread_pct
        )
        total_round_trip_cost = friction_data["total_round_trip_cost"]
        cost_rate_pct = friction_data["total_round_trip_pct"] / 100.0
        round_trip_spread_cost = friction_data["breakdown"]["spread_cost"]

        # 3. Net Return & Net Downside Math
        predicted_net_return_pct = gross_return_pct - cost_rate_pct
        expected_net_profit = expected_gross_profit - total_round_trip_cost
        expected_net_downside = expected_gross_loss + total_round_trip_cost

        net_reward_risk = expected_net_profit / max(0.01, expected_net_downside)
        gross_reward_risk = expected_gross_profit / max(0.01, expected_gross_loss)

        cost_to_profit_ratio = total_round_trip_cost / max(0.01, expected_gross_profit)
        spread_to_profit_ratio = round_trip_spread_cost / max(0.01, expected_gross_profit)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # HARD INVARIANT GATING CHECKS
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        # G1: Net Expected Return must be positive
        if predicted_net_return_pct <= 0 or expected_net_profit <= 0:
            rejection_reasons.append(
                f"Net expected return is negative/zero ({predicted_net_return_pct*100:.2f}%) after transaction costs of £{total_round_trip_cost:.2f}."
            )

        # G2: Net Reward-to-Risk >= 2.0x
        if net_reward_risk < self.min_net_reward_risk:
            rejection_reasons.append(
                f"Net Reward-to-Risk ({net_reward_risk:.2f}x) is below minimum institutional threshold of {self.min_net_reward_risk:.1f}x."
            )

        # G3: Cost-to-Expected-Profit Ratio <= 30%
        if cost_to_profit_ratio > self.max_cost_to_profit_ratio:
            rejection_reasons.append(
                f"Cost-to-Expected-Profit ratio ({cost_to_profit_ratio*100:.1f}%) exceeds maximum allowable ceiling of {self.max_cost_to_profit_ratio*100:.0f}%."
            )

        # G4: Contextual Spread Friction Ratio <= 15% of Expected Target Profit
        if spread_to_profit_ratio > self.max_spread_to_profit_ratio:
            rejection_reasons.append(
                f"Bid-ask spread friction ({round_trip_spread_cost:.2f} / {spread_to_profit_ratio*100:.1f}% of profit) exceeds 15% profit consumption threshold on a {gross_return_pct*100:.2f}% target move."
            )

        # G5: Emergency Liquidity Circuit Breaker (Max Spread 50 bps)
        if current_spread_pct > self.max_emergency_spread_pct:
            rejection_reasons.append(
                f"Bid-ask spread ({current_spread_pct*10000:.1f} bps) exceeds emergency liquidity circuit breaker of {self.max_emergency_spread_pct*10000:.0f} bps."
            )

        # G6: Fundamental Outlook >= Neutral
        if fundamental_score < 50.0:
            rejection_reasons.append(
                f"Fundamental outlook score ({fundamental_score:.1f}/100) is below neutral threshold of 50.0."
            )

        # G7: Technical Trend supportive
        if technical_score < 50.0:
            rejection_reasons.append(
                f"Technical trend score ({technical_score:.1f}/100) is unsupportive (< 50.0)."
            )

        # G8: Sufficient Liquidity
        if avg_daily_volume_gbp < 500000.0:
            rejection_reasons.append(
                f"Average daily liquidity (£{avg_daily_volume_gbp:,.0f}) is below minimum institutional requirement of £500,000."
            )

        approved = (len(rejection_reasons) == 0)
        action = "BUY" if approved else "HOLD CASH"

        return {
            "approved": approved,
            "action": action,
            "symbol": symbol,
            "rejection_reasons": rejection_reasons,
            "configuration_version": settings.CONFIGURATION_VERSION,
            "gross_return_pct": round(gross_return_pct * 100.0, 2),
            "predicted_gross_return_pct": round(gross_return_pct * 100.0, 2),
            "cost_drag_pct": round(cost_rate_pct * 100.0, 2),
            "predicted_net_return_pct": round(predicted_net_return_pct * 100.0, 2),
            "expected_gross_profit_gbp": round(expected_gross_profit, 2),
            "expected_net_profit_gbp": round(expected_net_profit, 2),
            "expected_gross_loss_gbp": round(expected_gross_loss, 2),
            "expected_net_downside_gbp": round(expected_net_downside, 2),
            "gross_reward_risk": round(gross_reward_risk, 2),
            "net_reward_risk": round(net_reward_risk, 2),
            "total_round_trip_cost_gbp": round(total_round_trip_cost, 2),
            "cost_to_profit_pct": round(cost_to_profit_ratio * 100.0, 1),
            "spread_to_profit_pct": round(spread_to_profit_ratio * 100.0, 1),
            "current_spread_bps": round(current_spread_pct * 10000.0, 1),
            "friction_breakdown": friction_data["breakdown"],
            "decision": "EXECUTE TRADE" if approved else "DO NOTHING / HOLD CAPITAL PRESERVATION CASH"
        }


net_edge_gate = NetEdgeGate()
