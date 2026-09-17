"""
PRV Capital - Hit-and-Run AI Allocation & Entry Decision Engine
Requirements C & D:
- AI decides whether to trade, which instrument(s), how many concurrent positions, capital allocated, total deployment.
- Hard constraint: total intended deployed capital <= 80% of currently available capital.
- Preference: fewer/larger meaningful positions when evidence supports concentration (no arbitrary fixed minimum £).
- NO fixed number of positions, NO equal-weight default, NO linear/quadratic/rank weighting fallback, NO top-candidate fallback.
- If AI allocation is unavailable: ALLOCATION_DECISION_UNAVAILABLE, ZERO NEW ORDERS, FAIL CLOSED.
- Produces explicit HitAndRunEntryDecision objects with ENTER / NO_ENTRY and comprehensive audit fields.
"""
import math
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from src.hit_and_run.models import (
    LiveOpportunityState,
    OpportunityAnalysisResult,
    AIAllocationDecision,
    HitAndRunEntryDecision,
)
from src.hit_and_run.risk import hit_and_run_risk

logger = logging.getLogger("hit_and_run.ai_allocator")


class AIAllocationInterface(ABC):
    """
    Abstract AI Allocation Interface.
    Authoritative decision layer determining trade selection, position count, and capital distribution.
    """
    @abstractmethod
    def decide_allocation(
        self,
        available_capital_gbp: float,
        portfolio_capital_gbp: float,
        current_holdings: List[Dict[str, Any]],
        outstanding_orders: List[Dict[str, Any]],
        analyzed_opportunities: List[OpportunityAnalysisResult],
        banked_profit_today_gbp: float = 0.0
    ) -> AIAllocationDecision:
        """
        Decides whether to trade, which instruments, position count, and capital distribution.
        """
        pass


class ConvictionConcentrationAIProvider(AIAllocationInterface):
    """
    AI Allocation Provider interface implementation.
    The contract requires that an AI decides:
    - whether to trade
    - which instruments
    - number of positions
    - capital allocated to each
    - total deployment
    Constraint: total deployment <= 80% of available capital.
    No deterministic fallback sizing formula (equal, rank, score, net-edge, linear, quadratic, softmax, etc.)
    is authorised.
    If an explicit AI decision proposal is provided (e.g. from an authorised AI model/caller),
    it validates and returns that proposal.
    If no explicit AI allocation decision is supplied:
    Returns ALLOCATION_DECISION_UNAVAILABLE with zero allocations, zero orders (fail closed).
    """

    def __init__(
        self,
        explicit_decision: Optional[AIAllocationDecision] = None,
        proposals: Optional[Dict[str, float]] = None,
        whether_to_trade: bool = True,
        rationale: str = "Authorised AI allocation decision"
    ):
        self.explicit_decision = explicit_decision
        self.proposals = proposals
        self.whether_to_trade = whether_to_trade
        self.rationale = rationale

    def decide_allocation(
        self,
        available_capital_gbp: float,
        portfolio_capital_gbp: float,
        current_holdings: List[Dict[str, Any]],
        outstanding_orders: List[Dict[str, Any]],
        analyzed_opportunities: List[OpportunityAnalysisResult],
        banked_profit_today_gbp: float = 0.0
    ) -> AIAllocationDecision:
        if self.explicit_decision is not None:
            return self.explicit_decision

        if available_capital_gbp <= 0.0 or portfolio_capital_gbp <= 0.0:
            return AIAllocationDecision(
                whether_to_trade=False,
                selected_allocations={},
                total_deployment_gbp=0.0,
                total_deployment_pct=0.0,
                rationale="ZERO_AVAILABLE_CAPITAL: Available capital or portfolio capital is zero or negative.",
                concentration_summary="NO_ALLOCATION",
                status="NO_CAPITAL_AVAILABLE"
            )

        if self.proposals is not None:
            total_dep = round(sum(self.proposals.values()), 2)
            dep_pct = round(total_dep / max(1.0, available_capital_gbp), 4)
            return AIAllocationDecision(
                whether_to_trade=self.whether_to_trade,
                selected_allocations=dict(self.proposals),
                total_deployment_gbp=total_dep,
                total_deployment_pct=dep_pct,
                rationale=self.rationale,
                concentration_summary=f"EXPLICIT_AI_ALLOCATION ({len(self.proposals)} positions)",
                status="ALLOCATED" if self.whether_to_trade and self.proposals else "ZERO_TRADES"
            )

        # No explicit AI decision proposal provided:
        # Contract Section 9: If AI allocation is unavailable:
        # ALLOCATION_DECISION_UNAVAILABLE => zero new allocations, zero new orders, fail closed.
        # Deterministic sizing formulas (net-edge, equal, rank, linear, quadratic, softmax) are strictly prohibited.
        return AIAllocationDecision(
            whether_to_trade=False,
            selected_allocations={},
            total_deployment_gbp=0.0,
            total_deployment_pct=0.0,
            rationale=(
                "ALLOCATION_DECISION_UNAVAILABLE: No explicit AI allocation decision supplied. "
                "Deterministic sizing formulas are unauthorised without explicit user authority. "
                "Failing closed with zero new allocations."
            ),
            concentration_summary="ALLOCATION_DECISION_UNAVAILABLE",
            status="ALLOCATION_DECISION_UNAVAILABLE"
        )


class HitAndRunAllocationManager:
    """
    Coordinates AI allocation decisions and generates definitive HitAndRunEntryDecision objects.
    Enforces <=80% capital ceiling, fails closed if AI is unavailable, and validates protective levels.
    """

    MAX_DEPLOYMENT_CEILING_PCT: float = 0.80
    MAX_LOSS_PCT: float = 0.05

    def __init__(self, ai_provider: Optional[AIAllocationInterface] = None):
        self.ai_provider = ai_provider

    def evaluate_entries(
        self,
        available_capital_gbp: float,
        portfolio_capital_gbp: float,
        current_holdings: List[Dict[str, Any]],
        outstanding_orders: List[Dict[str, Any]],
        analyzed_opportunities: List[OpportunityAnalysisResult],
        banked_profit_today_gbp: float = 0.0
    ) -> Tuple[AIAllocationDecision, List[HitAndRunEntryDecision]]:
        """
        Executes full allocation and entry decision workflow.
        Returns: (AIAllocationDecision, List[HitAndRunEntryDecision])
        """
        # If AI allocation provider is unavailable: FAIL CLOSED FOR NEW ENTRIES
        if self.ai_provider is None:
            logger.warning("AllocationManager: AI provider unavailable. Failing closed with ZERO NEW ORDERS.")
            no_ai_decision = AIAllocationDecision(
                whether_to_trade=False,
                selected_allocations={},
                total_deployment_gbp=0.0,
                total_deployment_pct=0.0,
                rationale="ALLOCATION_DECISION_UNAVAILABLE: No authorised AI allocation provider configured. Failing closed.",
                concentration_summary="NO_AI_DECISION",
                status="ALLOCATION_DECISION_UNAVAILABLE"
            )
            return no_ai_decision, []

        ai_decision = self.ai_provider.decide_allocation(
            available_capital_gbp=available_capital_gbp,
            portfolio_capital_gbp=portfolio_capital_gbp,
            current_holdings=current_holdings,
            outstanding_orders=outstanding_orders,
            analyzed_opportunities=analyzed_opportunities,
            banked_profit_today_gbp=banked_profit_today_gbp
        )

        # Strict constraint verification: total deployment <= 80% of available capital
        max_allowed_gbp = round(available_capital_gbp * self.MAX_DEPLOYMENT_CEILING_PCT, 2)
        if ai_decision.total_deployment_gbp > max_allowed_gbp:
            logger.warning(
                f"AllocationManager: AI proposed deployment £{ai_decision.total_deployment_gbp:.2f} "
                f"exceeds 80% ceiling (£{max_allowed_gbp:.2f}). Proposal rejected as non-compliant."
            )
            non_compliant_decision = AIAllocationDecision(
                whether_to_trade=False,
                selected_allocations={},
                total_deployment_gbp=0.0,
                total_deployment_pct=0.0,
                rationale=(
                    f"NON_COMPLIANT_ALLOCATION_PROPOSAL: EXCEEDS_80PCT_CEILING. "
                    f"Proposed deployment £{ai_decision.total_deployment_gbp:.2f} exceeds 80% ceiling "
                    f"(£{max_allowed_gbp:.2f}). Automatic scaling is unauthorized. Proposal rejected with zero orders."
                ),
                concentration_summary="REJECTED_NON_COMPLIANT",
                status="NON_COMPLIANT_ALLOCATION_PROPOSAL: EXCEEDS_80PCT_CEILING"
            )
            return non_compliant_decision, []

        if not ai_decision.whether_to_trade or not ai_decision.selected_allocations:
            return ai_decision, []

        # Map opportunities by instrument_id and symbol
        opp_map = {op.instrument_id: op for op in analyzed_opportunities}
        opp_map.update({op.symbol: op for op in analyzed_opportunities})

        entry_decisions: List[HitAndRunEntryDecision] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for inst_key, alloc_gbp in ai_decision.selected_allocations.items():
            op = opp_map.get(inst_key)
            if not op:
                entry_decisions.append(HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=inst_key,
                    symbol=inst_key,
                    feed_ticker=inst_key,
                    no_entry_reason=f"INSTRUMENT_NOT_FOUND: {inst_key} not present in analyzed opportunities",
                    decision_timestamp=now_iso,
                    data_timestamp=now_iso
                ))
                continue

            state = op.state

            # Gate 1: Live Spread Check
            if state.spread_friction is None or state.bid is None or state.ask is None:
                entry_decisions.append(HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=state.instrument_id,
                    symbol=state.symbol,
                    feed_ticker=state.feed_ticker,
                    current_bid=state.bid,
                    current_ask=state.ask,
                    current_price=state.current_price,
                    expected_net_opportunity=op.expected_net_opportunity,
                    thesis=op.opportunity_thesis,
                    no_entry_reason="LIVE_SPREAD_UNKNOWN: Live bid/ask spread unavailable; execution prohibited",
                    decision_timestamp=now_iso,
                    data_timestamp=state.data_timestamp
                ))
                continue

            # Gate 2: Authoritative Tick Size Check (Protective stop requires authoritative tick)
            if state.tick_size is None or state.tick_size <= 0:
                entry_decisions.append(HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=state.instrument_id,
                    symbol=state.symbol,
                    feed_ticker=state.feed_ticker,
                    current_bid=state.bid,
                    current_ask=state.ask,
                    current_price=state.current_price,
                    expected_net_opportunity=op.expected_net_opportunity,
                    thesis=op.opportunity_thesis,
                    no_entry_reason="TICK_SIZE_UNKNOWN: Authoritative broker tick size unavailable for stop protection",
                    decision_timestamp=now_iso,
                    data_timestamp=state.data_timestamp
                ))
                continue

            # Gate 3: Quantity Precision Check
            prec = state.quantity_precision
            min_qty = state.min_trade_quantity
            if prec is None and min_qty is None:
                entry_decisions.append(HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=state.instrument_id,
                    symbol=state.symbol,
                    feed_ticker=state.feed_ticker,
                    current_bid=state.bid,
                    current_ask=state.ask,
                    current_price=state.current_price,
                    expected_net_opportunity=op.expected_net_opportunity,
                    thesis=op.opportunity_thesis,
                    no_entry_reason="QUANTITY_INCREMENT_UNKNOWN: Missing quantity precision metadata",
                    decision_timestamp=now_iso,
                    data_timestamp=state.data_timestamp
                ))
                continue

            if prec is None and min_qty is not None:
                from src.data.technical_execution_capability import technical_execution_capability
                prec = technical_execution_capability.derive_quantity_precision(min_qty)

            # Gate 4: Session State Check
            if state.session_state not in ("REGULAR", "OPEN"):
                entry_decisions.append(HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=state.instrument_id,
                    symbol=state.symbol,
                    feed_ticker=state.feed_ticker,
                    current_bid=state.bid,
                    current_ask=state.ask,
                    current_price=state.current_price,
                    expected_net_opportunity=op.expected_net_opportunity,
                    thesis=op.opportunity_thesis,
                    no_entry_reason=f"SESSION_INACTIVE: Market session is {state.session_state}",
                    decision_timestamp=now_iso,
                    data_timestamp=state.data_timestamp
                ))
                continue

            # Gate 5: Positive Net Reward Check
            if op.expected_net_opportunity is None or op.expected_net_opportunity <= 0:
                entry_decisions.append(HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=state.instrument_id,
                    symbol=state.symbol,
                    feed_ticker=state.feed_ticker,
                    current_bid=state.bid,
                    current_ask=state.ask,
                    current_price=state.current_price,
                    expected_net_opportunity=op.expected_net_opportunity,
                    thesis=op.opportunity_thesis,
                    no_entry_reason="NON_POSITIVE_NET_EDGE: Expected net return after costs <= 0",
                    decision_timestamp=now_iso,
                    data_timestamp=state.data_timestamp
                ))
                continue

            # Calculate Exact Executable Quantity
            price_gbp = state.current_price_gbp
            raw_qty = alloc_gbp / price_gbp
            factor = 10.0 ** prec
            intended_qty = math.floor(raw_qty * factor) / factor

            if intended_qty <= 0.0:
                entry_decisions.append(HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=state.instrument_id,
                    symbol=state.symbol,
                    feed_ticker=state.feed_ticker,
                    current_bid=state.bid,
                    current_ask=state.ask,
                    current_price=state.current_price,
                    no_entry_reason=f"INTENDED_QUANTITY_ZERO: Allocated capital £{alloc_gbp} yields 0 shares at price £{price_gbp}",
                    decision_timestamp=now_iso,
                    data_timestamp=state.data_timestamp
                ))
                continue

            # Calculate Protective Stop Level (Strictly enforced <= 5% loss ceiling, rounded UP to next tick)
            fill_ref_price = state.ask or state.current_price
            effective_downside = (
                min(self.MAX_LOSS_PCT, op.downside_estimate)
                if op.downside_estimate is not None
                else self.MAX_LOSS_PCT
            )

            stop_price = hit_and_run_risk.calculate_protective_stop(
                fill_price=fill_ref_price,
                requested_risk_pct=effective_downside,
                tick_size=state.tick_size
            )

            # Invariant check
            is_valid_stop, stop_reason = hit_and_run_risk.verify_protective_stop_invariant(
                fill_price=fill_ref_price,
                stop_price=stop_price,
                tick_size=state.tick_size
            )
            if not is_valid_stop:
                entry_decisions.append(HitAndRunEntryDecision(
                    decision="NO_ENTRY",
                    instrument_id=state.instrument_id,
                    symbol=state.symbol,
                    feed_ticker=state.feed_ticker,
                    no_entry_reason=f"PROTECTIVE_STOP_INVALID: {stop_reason}",
                    decision_timestamp=now_iso,
                    data_timestamp=state.data_timestamp
                ))
                continue

            # Expected Costs in GBP
            if state.estimated_costs is not None:
                expected_costs_gbp = round(alloc_gbp * state.estimated_costs, 2)
            else:
                expected_costs_gbp = None

            entry_decisions.append(HitAndRunEntryDecision(
                decision="ENTER",
                instrument_id=state.instrument_id,
                symbol=state.symbol,
                feed_ticker=state.feed_ticker,
                intended_capital_gbp=round(alloc_gbp, 2),
                intended_quantity=intended_qty,
                current_bid=state.bid,
                current_ask=state.ask,
                current_price=state.current_price,
                expected_costs_gbp=expected_costs_gbp,
                expected_net_opportunity=op.expected_net_opportunity,
                thesis=op.opportunity_thesis,
                downside=round(effective_downside, 4),
                quantity_increment=10.0 ** (-prec) if prec > 0 else 1.0,
                quantity_precision=prec,
                tick_size=state.tick_size,
                required_protective_level=stop_price,
                allocation_rationale=f"Allocated £{alloc_gbp:.2f} per AI decision ({ai_decision.concentration_summary})",
                decision_timestamp=now_iso,
                data_timestamp=state.data_timestamp
            ))

        return ai_decision, entry_decisions


ai_allocation_manager = HitAndRunAllocationManager(
    ai_provider=ConvictionConcentrationAIProvider()
)
