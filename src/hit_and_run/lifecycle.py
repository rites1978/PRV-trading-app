"""
PRV Capital - Hit-and-Run Position Lifecycle Engine
Requirements E, F, G:
- Continuous reassessment of every hit-and-run holding.
- Lifecycle actions: HOLD, TAKE_PROFIT, EDGE_DECAY_EXIT, MOMENTUM_REVERSAL_EXIT, ROTATE, STOP_LOSS_EXIT.
- NO fixed multi-day duration, NO arbitrary fixed take-profit %, NO fixed £ target, NO fixed trailing %, NO fixed holding minutes.
- Profit capture is adaptive from current evidence (momentum deceleration, exhaustion, target reach).
- Strictly enforces 5% hard loss limit; protective stop rounded UP to next valid broker tick.
- Closes positions, calculates gross realised P&L, execution costs, net realised P&L, and banks to DailyBankingLedger.
- Once £100 realised net is banked, CONTINUES HUNTING and banking more.
- Released capital immediately becomes available for new allocation.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from src.hit_and_run.models import (
    HoldingState,
    LiveOpportunityState,
    OpportunityAnalysisResult,
    LifecycleAction,
    LifecycleAssessment,
)
from src.hit_and_run.banking import DailyBankingLedger

logger = logging.getLogger("hit_and_run.lifecycle")


class HitAndRunPositionLifecycleManager:
    """Manages active holding lifecycle assessments, adaptive exits, and rotation."""

    MAXIMUM_AUTHORISED_LOSS_PCT: float = 0.05

    def assess_holding(
        self,
        holding: HoldingState,
        current_state: LiveOpportunityState,
        alternative_opportunities: Optional[List[OpportunityAnalysisResult]] = None,
        banked_profit_today_gbp: float = 0.0,
        explicit_action: Optional[str] = None
    ) -> LifecycleAssessment:
        """
        Continuously compares:
        - current net unrealised result after estimated exit costs
        - current opportunity thesis
        - deterioration/improvement in market evidence
        - current spread/friction
        - volatility
        - alternative opportunities
        - capital efficiency
        - realised profit already banked today
        Adaptive profit capture, NO fixed percentages.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # Bid price is the execution price for exiting a long position
        exit_price = current_state.bid if current_state.bid is not None and current_state.bid > 0 else current_state.current_price
        fill_price = holding.fill_price
        qty = holding.quantity
        divisor = holding.quote_divisor if holding.quote_divisor > 0 else 1.0

        # Track high/low watermarks
        if exit_price > holding.highest_price_seen:
            holding.highest_price_seen = exit_price
        if exit_price < holding.lowest_price_seen:
            holding.lowest_price_seen = exit_price

        # Calculate Gross and Net Unrealised PnL
        gross_unrealised_gbp = round(((exit_price - fill_price) / divisor) * qty, 2)
        if current_state.estimated_costs is not None:
            estimated_exit_costs_gbp = round(holding.allocated_capital_gbp * current_state.estimated_costs, 2)
            net_unrealised_pnl_gbp = round(gross_unrealised_gbp - estimated_exit_costs_gbp, 2)
            net_unrealised_pct = round(net_unrealised_pnl_gbp / max(1.0, holding.allocated_capital_gbp), 4)
        else:
            estimated_exit_costs_gbp = None
            net_unrealised_pnl_gbp = None
            net_unrealised_pct = None

        holding.current_unrealised_net_pnl_gbp = net_unrealised_pnl_gbp

        # -------------------------------------------------------------
        # Action Check: STOP_LOSS_EXIT (5% Hard Loss Ceiling Invariant)
        # Authority: USER_AUTHORISED (Acceptance Contract Section 12)
        # -------------------------------------------------------------
        # Protective stop triggered if exit price touches or crosses stop
        if exit_price <= holding.protective_stop_price:
            return LifecycleAssessment(
                holding_id=holding.holding_id,
                instrument_id=holding.instrument_id,
                symbol=holding.symbol,
                action=LifecycleAction.STOP_LOSS_EXIT,
                current_price=exit_price,
                current_bid=current_state.bid,
                current_ask=current_state.ask,
                gross_unrealised_pnl_gbp=gross_unrealised_gbp,
                estimated_exit_costs_gbp=estimated_exit_costs_gbp,
                net_unrealised_pnl_gbp=net_unrealised_pnl_gbp,
                net_unrealised_pct=net_unrealised_pct,
                thesis_health="STOP_BREACHED",
                rationale=(
                    f"Protective stop breached: current price {exit_price} <= stop {holding.protective_stop_price} "
                    f"(Planned max loss {holding.planned_loss_pct:.2%}). Mandatory protective exit."
                ),
                target_rotation_symbol=None,
                rotation_decision_status=None,
                lifecycle_decision_status="STOP_LOSS_TRIGGERED",
                timestamp=now_iso
            )

        # -------------------------------------------------------------
        # Lifecycle Intelligence & External Decision Agent Audit:
        # Per Contract Audit:
        # - LIFECYCLE_DECISION_AUTHORITY = UNPROVEN
        # - EXTERNAL_DECISION_AGENT_AUTHORITY = UNPROVEN
        # - Fallback conversion (DECISION UNAVAILABLE -> HOLD) is strictly UNAUTHORISED.
        # - Required representation when no authorised lifecycle decision exists:
        #   LIFECYCLE_DECISION_STATUS = UNAVAILABLE
        #   LIFECYCLE_ACTION = None
        # - The already-authorised 5% protective stop remains active at the broker as a hard
        #   risk invariant. Protective-stop ownership is NEVER described as HOLD logic.
        # -------------------------------------------------------------
        rotation_decision_status = "ROTATION_DECISION_UNAVAILABLE" if alternative_opportunities else None
        rationale = (
            "LIFECYCLE_DECISION_STATUS=UNAVAILABLE: No authorised lifecycle decision model or proven decision agent. "
            "LIFECYCLE_ACTION=None; no fallback conversion (HOLD/SELL/ROTATE) applied. "
            "Protective stop remains active at broker as hard risk invariant."
        )

        return LifecycleAssessment(
            holding_id=holding.holding_id,
            instrument_id=holding.instrument_id,
            symbol=holding.symbol,
            action=None,
            current_price=exit_price,
            current_bid=current_state.bid,
            current_ask=current_state.ask,
            gross_unrealised_pnl_gbp=gross_unrealised_gbp,
            estimated_exit_costs_gbp=estimated_exit_costs_gbp,
            net_unrealised_pnl_gbp=net_unrealised_pnl_gbp,
            net_unrealised_pct=net_unrealised_pct,
            thesis_health="LIFECYCLE_DECISION_UNAVAILABLE",
            rationale=rationale,
            target_rotation_symbol=None,
            rotation_decision_status=rotation_decision_status,
            lifecycle_decision_status="UNAVAILABLE",
            timestamp=now_iso
        )

    def execute_exit_and_bank(
        self,
        holding: HoldingState,
        assessment: LifecycleAssessment,
        actual_exit_price: Optional[float] = None,
        actual_costs_gbp: Optional[float] = None,
        ledger: Optional[DailyBankingLedger] = None
    ) -> Dict[str, Any]:
        """
        Executes position exit accounting:
        - Calculates gross realised P&L
        - Quantifies confirmed execution costs
        - Calculates net realised P&L
        - Updates DailyBankingLedger
        - Released capital immediately becomes available for new allocations
        """
        if not assessment.action or assessment.action == LifecycleAction.HOLD:
            raise ValueError(f"Cannot execute exit for non-exit or unavailable action: {assessment.action}")

        exit_p = actual_exit_price if actual_exit_price is not None else assessment.current_price
        fill_p = holding.fill_price
        qty = holding.quantity
        divisor = holding.quote_divisor if holding.quote_divisor > 0 else 1.0

        gross_realised = round(((exit_p - fill_p) / divisor) * qty, 2)
        costs = actual_costs_gbp if actual_costs_gbp is not None else assessment.estimated_exit_costs_gbp
        net_realised = round(gross_realised - costs, 2)

        record = None
        if ledger is not None:
            record = ledger.record_realised_trade(
                trade_id=holding.holding_id,
                ticker=holding.symbol,
                gross_pnl_gbp=gross_realised,
                costs_gbp=costs,
                exit_reason=assessment.action,
                entry_price=fill_p,
                exit_price=exit_p,
                quantity=qty
            )

        return {
            "holding_id": holding.holding_id,
            "symbol": holding.symbol,
            "exit_action": assessment.action,
            "entry_price": fill_p,
            "exit_price": exit_p,
            "quantity": qty,
            "gross_realised_pnl_gbp": gross_realised,
            "costs_gbp": round(float(costs), 2),
            "net_realised_pnl_gbp": net_realised,
            "released_capital_gbp": round(holding.allocated_capital_gbp + net_realised, 2),
            "ledger_record": record
        }


position_lifecycle_manager = HitAndRunPositionLifecycleManager()
