"""
🏛️ PRV CAPITAL | DEAD CAPITAL & CAPITAL RECYCLING MANAGER
Formal quantitative definition and evaluation of stagnant capital.

Objective:
A position is NEVER classified as "Dead Capital" simply because it is temporarily flat or negative.

A position is evaluated for Capital Recycling ONLY when:
(Replacement Expected Net Return - Switching Costs) - (Remaining Expected Net Return) >= Hurdle (1.50%)

Calculates:
- remaining_expected_net_return
- remaining_expected_holding_time
- thesis_strength
- opportunity_cost
- replacement_expected_net_return
- replacement_expected_holding_time
- switching_cost
"""
from typing import Dict, Any, List, Optional
from src.execution.cost_model import cost_model
from src.analytics.unified_conviction_engine import unified_conviction_engine
from src.portfolio.portfolio_snapshot import portfolio_snapshot


class DeadCapitalManager:
    """
    Evaluates positions for true capital stagnation versus valid catalyst maturation.
    """
    def __init__(self, replacement_hurdle_pct: float = 1.50):
        self.replacement_hurdle_pct = replacement_hurdle_pct

    def evaluate_position_recycling(
        self,
        holding_symbol: str,
        holding_days_active: int,
        unrealized_pnl_pct: float,
        replacement_symbol: str = "CRM",
        replacement_expected_net_return_pct: float = 5.60,
        replacement_holding_days: int = 14
    ) -> Dict[str, Any]:
        """
        Formally calculates whether recycling capital from an existing holding into a replacement candidate
        yields a statistically superior net gain after deducting all switching transaction friction.
        """
        conv = unified_conviction_engine.get_conviction_record(holding_symbol)
        
        remaining_expected_net_return = conv.get("expected_net_return_pct", 4.0)
        remaining_holding_time = max(1, conv.get("expected_holding_days", 14) - holding_days_active)
        thesis_strength = conv.get("conviction_score", 75.0)

        # Calculate switching cost (Exit friction on existing + Entry friction on replacement)
        exit_friction = cost_model.calculate_trade_friction(
            nominal_value=2500.0,
            is_buy=False,
            is_uk=holding_symbol.endswith(".L") or holding_symbol in ["GLEN", "ULVR", "AAL", "HSBA"],
            is_foreign=holding_symbol not in ["GLEN", "ULVR", "AAL", "HSBA"] and not holding_symbol.endswith(".L")
        )
        entry_friction = cost_model.calculate_trade_friction(
            nominal_value=2500.0,
            is_buy=True,
            is_uk=replacement_symbol.endswith(".L") or replacement_symbol in ["AZN", "ULVR", "GLEN", "AAL", "HSBA"],
            is_foreign=replacement_symbol not in ["AZN", "ULVR", "GLEN", "AAL", "HSBA"] and not replacement_symbol.endswith(".L")
        )
        total_switching_cost_gbp = exit_friction["total_friction"] + entry_friction["total_friction"]
        switching_cost_pct = (total_switching_cost_gbp / 2500.0) * 100.0

        net_replacement_benefit = (replacement_expected_net_return_pct - switching_cost_pct) - remaining_expected_net_return

        # Formal dead capital condition
        is_dead_capital = (
            (net_replacement_benefit >= self.replacement_hurdle_pct) and
            (conv["thesis_status"] == "DETERIORATING" or holding_days_active > 28) and
            (thesis_strength < 72.0)
        )

        recommendation = "RECYCLE INTO REPLACEMENT" if is_dead_capital else "MAINTAIN EXPOSURE"

        return {
            "holding_symbol": holding_symbol,
            "days_active": holding_days_active,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "thesis_status": conv["thesis_status"],
            "thesis_strength": thesis_strength,
            "remaining_expected_net_return_pct": round(remaining_expected_net_return, 2),
            "remaining_expected_holding_days": remaining_holding_time,
            "replacement_candidate": replacement_symbol,
            "replacement_expected_net_return_pct": round(replacement_expected_net_return_pct, 2),
            "switching_cost_gbp": round(total_switching_cost_gbp, 2),
            "switching_cost_pct": round(switching_cost_pct, 2),
            "net_replacement_benefit_pct": round(net_replacement_benefit, 2),
            "is_dead_capital": is_dead_capital,
            "recommendation": recommendation,
            "rationale": (
                f"Net replacement advantage (+{net_replacement_benefit:.2f}%) exceeds {self.replacement_hurdle_pct:.1f}% hurdle."
                if is_dead_capital else
                f"Thesis remains intact ({conv['thesis_status']}); switching costs ({switching_cost_pct:.2f}%) destroy potential advantage."
            )
        }

    def audit_all_holdings_for_dead_capital(self, snapshot: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Audits all current holdings against the formal dead capital standard using single authoritative snapshot.
        """
        snap = snapshot or portfolio_snapshot.get_authoritative_snapshot()
        audits = []
        for pos in snap.get("positions", []):
            eval_res = self.evaluate_position_recycling(
                holding_symbol=pos["symbol"],
                holding_days_active=1, # Active Day 1 of 30-Day Practice Challenge
                unrealized_pnl_pct=pos["unrealized_pnl_pct"]
            )
            audits.append(eval_res)
        return audits


dead_capital_manager = DeadCapitalManager()
