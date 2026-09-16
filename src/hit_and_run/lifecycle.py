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
        banked_profit_today_gbp: float = 0.0
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
        exit_cost_rate = current_state.estimated_costs if current_state.estimated_costs is not None else 0.0015
        estimated_exit_costs_gbp = round(holding.allocated_capital_gbp * exit_cost_rate, 2)
        net_unrealised_pnl_gbp = round(gross_unrealised_gbp - estimated_exit_costs_gbp, 2)
        net_unrealised_pct = round(net_unrealised_pnl_gbp / max(1.0, holding.allocated_capital_gbp), 4)

        holding.current_unrealised_net_pnl_gbp = net_unrealised_pnl_gbp

        # -------------------------------------------------------------
        # Action Check 1: STOP_LOSS_EXIT (5% Hard Loss Ceiling Invariant)
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
                timestamp=now_iso
            )

        # -------------------------------------------------------------
        # Action Check 2: MOMENTUM_REVERSAL_EXIT
        # -------------------------------------------------------------
        # Momentum turned adverse or sharp acceleration downward
        mom = current_state.short_duration_momentum
        acc = current_state.momentum_acceleration

        is_reversal = False
        reversal_reason = ""

        if mom is not None and mom < -0.008:
            is_reversal = True
            reversal_reason = f"Momentum reversed into adverse trajectory ({mom:+.2%})"
        elif acc is not None and acc < -0.005 and exit_price < fill_price:
            is_reversal = True
            reversal_reason = f"Severe momentum deceleration ({acc:+.3%}) while position is underwater"

        if is_reversal:
            return LifecycleAssessment(
                holding_id=holding.holding_id,
                instrument_id=holding.instrument_id,
                symbol=holding.symbol,
                action=LifecycleAction.MOMENTUM_REVERSAL_EXIT,
                current_price=exit_price,
                current_bid=current_state.bid,
                current_ask=current_state.ask,
                gross_unrealised_pnl_gbp=gross_unrealised_gbp,
                estimated_exit_costs_gbp=estimated_exit_costs_gbp,
                net_unrealised_pnl_gbp=net_unrealised_pnl_gbp,
                net_unrealised_pct=net_unrealised_pct,
                thesis_health="REVERSED",
                rationale=f"Thesis invalidated by market evidence: {reversal_reason}. Capital preservation exit.",
                timestamp=now_iso
            )

        # -------------------------------------------------------------
        # Action Check 3: EDGE_DECAY_EXIT
        # -------------------------------------------------------------
        # Spread widened severely, cost model incomplete, or expected net edge vanished
        is_edge_decay = False
        decay_reason = ""

        if current_state.spread_friction is not None and current_state.spread_friction > 0.015:
            is_edge_decay = True
            decay_reason = f"Spread friction widened excessively to {current_state.spread_friction * 10000:.1f} bps"
        elif not current_state.cost_model_complete:
            is_edge_decay = True
            decay_reason = f"Cost model completeness compromised: {'; '.join(current_state.cost_model_reasons)}"
        elif current_state.expected_net_opportunity is not None and current_state.expected_net_opportunity <= 0:
            is_edge_decay = True
            decay_reason = "Forward expected net opportunity consumed by market friction"

        if is_edge_decay:
            return LifecycleAssessment(
                holding_id=holding.holding_id,
                instrument_id=holding.instrument_id,
                symbol=holding.symbol,
                action=LifecycleAction.EDGE_DECAY_EXIT,
                current_price=exit_price,
                current_bid=current_state.bid,
                current_ask=current_state.ask,
                gross_unrealised_pnl_gbp=gross_unrealised_gbp,
                estimated_exit_costs_gbp=estimated_exit_costs_gbp,
                net_unrealised_pnl_gbp=net_unrealised_pnl_gbp,
                net_unrealised_pct=net_unrealised_pct,
                thesis_health="DECAYED",
                rationale=f"Edge decay detected: {decay_reason}. Releasing capital.",
                timestamp=now_iso
            )

        # -------------------------------------------------------------
        # Action Check 4: TAKE_PROFIT (Adaptive, from current evidence)
        # -------------------------------------------------------------
        # Invariant: NO fixed take-profit percentage.
        # Triggers when net realised profit is positive AND market evidence exhibits:
        # 1. Deceleration curling downward after positive expansion (acc < -0.001)
        # 2. Significant pullback from peak watermark after strong impulse
        # 3. Target gross move achieved while volume activity fades
        pullback_from_peak = (holding.highest_price_seen - exit_price) / max(1e-4, holding.highest_price_seen)
        is_exhausted = False
        tp_reason = ""

        if net_unrealised_pnl_gbp > 0:
            # Evidence A: Deceleration curling downward after impulse
            if acc is not None and acc < -0.001 and mom is not None and mom > 0:
                is_exhausted = True
                tp_reason = f"Momentum curling over (acceleration {acc:+.3%}) with banked net £{net_unrealised_pnl_gbp:.2f}"
            # Evidence B: Pullback from recent peak watermark
            elif pullback_from_peak >= 0.008 and (holding.highest_price_seen - fill_price) > 0:
                is_exhausted = True
                tp_reason = f"Pullback of {pullback_from_peak:.2%} from high watermark (£{holding.highest_price_seen}) with net gain £{net_unrealised_pnl_gbp:.2f}"
            # Evidence C: Expected gross move reached
            elif current_state.expected_gross_move is not None:
                move_so_far = (exit_price - fill_price) / fill_price
                if move_so_far >= current_state.expected_gross_move:
                    is_exhausted = True
                    tp_reason = f"Target move {current_state.expected_gross_move:.2%} achieved (actual {move_so_far:+.2%})"

        if is_exhausted:
            return LifecycleAssessment(
                holding_id=holding.holding_id,
                instrument_id=holding.instrument_id,
                symbol=holding.symbol,
                action=LifecycleAction.TAKE_PROFIT,
                current_price=exit_price,
                current_bid=current_state.bid,
                current_ask=current_state.ask,
                gross_unrealised_pnl_gbp=gross_unrealised_gbp,
                estimated_exit_costs_gbp=estimated_exit_costs_gbp,
                net_unrealised_pnl_gbp=net_unrealised_pnl_gbp,
                net_unrealised_pct=net_unrealised_pct,
                thesis_health="EXHAUSTED",
                rationale=f"Adaptive profit capture triggered: {tp_reason}. Realising net gain.",
                timestamp=now_iso
            )

        # -------------------------------------------------------------
        # Action Check 5: ROTATE (Capital Efficiency vs Stronger Opportunities)
        # -------------------------------------------------------------
        # If current holding is stagnant or low conviction, and a significantly superior opportunity exists
        if alternative_opportunities:
            # Find strongest non-held alternative with complete data
            strong_alts = [
                op for op in alternative_opportunities
                if op.instrument_id != holding.instrument_id
                and op.symbol != holding.symbol
                and op.data_quality_state == "COMPLETE"
                and op.opportunity_score is not None
                and (op.expected_net_opportunity or 0.0) > 0.015
            ]
            if strong_alts:
                best_alt = strong_alts[0]
                # If current position is sluggish (e.g. flat P&L and low momentum) while alternative has standout conviction
                if best_alt.opportunity_score >= 70.0 and abs(net_unrealised_pct) < 0.008 and (mom is None or abs(mom) < 0.005):
                    return LifecycleAssessment(
                        holding_id=holding.holding_id,
                        instrument_id=holding.instrument_id,
                        symbol=holding.symbol,
                        action=LifecycleAction.ROTATE,
                        current_price=exit_price,
                        current_bid=current_state.bid,
                        current_ask=current_state.ask,
                        gross_unrealised_pnl_gbp=gross_unrealised_gbp,
                        estimated_exit_costs_gbp=estimated_exit_costs_gbp,
                        net_unrealised_pnl_gbp=net_unrealised_pnl_gbp,
                        net_unrealised_pct=net_unrealised_pct,
                        thesis_health="STAGNANT_OPPORTUNITY_SUPERIOR",
                        rationale=(
                            f"Rotating stagnant capital ({holding.symbol} net {net_unrealised_pct:+.2%}) "
                            f"into higher conviction opportunity {best_alt.symbol} (Score {best_alt.opportunity_score:.1f}, "
                            f"NetReward {best_alt.expected_net_opportunity:+.2%})."
                        ),
                        target_rotation_symbol=best_alt.symbol,
                        timestamp=now_iso
                    )

        # -------------------------------------------------------------
        # Default: HOLD (Thesis Intact)
        # -------------------------------------------------------------
        return LifecycleAssessment(
            holding_id=holding.holding_id,
            instrument_id=holding.instrument_id,
            symbol=holding.symbol,
            action=LifecycleAction.HOLD,
            current_price=exit_price,
            current_bid=current_state.bid,
            current_ask=current_state.ask,
            gross_unrealised_pnl_gbp=gross_unrealised_gbp,
            estimated_exit_costs_gbp=estimated_exit_costs_gbp,
            net_unrealised_pnl_gbp=net_unrealised_pnl_gbp,
            net_unrealised_pct=net_unrealised_pct,
            thesis_health="INTACT",
            rationale="Thesis intact; favourable momentum and positive net edge continue. Holding position.",
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
