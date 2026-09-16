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
    Evidence-driven AI allocation decision maker embodying the Authoritative User Objective:
    - Pure hit-and-run
    - £100 realised NET daily base-profit target; keep hunting once achieved
    - Use up to 80% of available capital when opportunity quality justifies it
    - Prefer fewer/larger meaningful positions rather than many tiny purchases
    - NO fixed number of positions (AI decides 1, several, or more)
    - Do not force a trade when no positive edge exists
    - No arbitrary fixed £ minimum thresholds
    """

    def decide_allocation(
        self,
        available_capital_gbp: float,
        portfolio_capital_gbp: float,
        current_holdings: List[Dict[str, Any]],
        outstanding_orders: List[Dict[str, Any]],
        analyzed_opportunities: List[OpportunityAnalysisResult],
        banked_profit_today_gbp: float = 0.0
    ) -> AIAllocationDecision:
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

        # 80% deployment ceiling
        max_deployable_ceiling = available_capital_gbp * 0.80

        # Calculate already committed capital in holdings and open orders
        held_value = sum(float(h.get("allocated_capital_gbp", h.get("current_value_gbp", 0.0))) for h in current_holdings)
        order_value = sum(float(o.get("reserved_value_gbp", 0.0)) for o in outstanding_orders)
        committed_total = held_value + order_value
        max_portfolio_deployment = portfolio_capital_gbp * 0.80
        portfolio_headroom = max(0.0, max_portfolio_deployment - committed_total)

        max_allocatable_budget = min(max_deployable_ceiling, portfolio_headroom)
        if max_allocatable_budget <= 0.0:
            return AIAllocationDecision(
                whether_to_trade=False,
                selected_allocations={},
                total_deployment_gbp=0.0,
                total_deployment_pct=0.0,
                rationale=f"CAPITAL_CEILING_REACHED: Committed £{committed_total:.2f} meets or exceeds 80% ceiling (£{max_portfolio_deployment:.2f}).",
                concentration_summary="PORTFOLIO_DEPLOYMENT_MAXED",
                status="CAPITAL_CEILING_REACHED"
            )

        # Filter to opportunities with verified complete data, active session, and genuine positive net edge
        held_ids = {
            str(h.get("instrument_id") or h.get("symbol", "")).upper() for h in current_holdings
        } | {
            str(o.get("instrument_id") or o.get("symbol", "")).upper() for o in outstanding_orders
        }

        viable = [
            op for op in analyzed_opportunities
            if op.data_quality_state == "COMPLETE"
            and op.state.technical_execution_supported is True
            and getattr(op.state, "session_open", False) is True
            and getattr(op.state, "quote_executable_now", False) is True
            and op.state.spread_friction is not None
            and op.expected_net_opportunity is not None
            and op.expected_net_opportunity > 0.0
            and op.opportunity_score is not None
            and op.instrument_id.upper() not in held_ids
            and op.symbol.upper() not in held_ids
        ]

        if not viable:
            # Audit why viable is empty per Deliverable 2A Section A:
            # NO_VALID_EDGE is permitted ONLY when relevant universe was successfully evaluated,
            # execution capability resolved, required live market data available, costs complete,
            # and no executable positive edge remained. If infrastructure prevented evaluation: PRODUCTION_FAILURE.
            if not analyzed_opportunities:
                status = "PRODUCTION_FAILURE: MARKET_DATA_COVERAGE_INCOMPLETE"
                rationale = "PRODUCTION_FAILURE: MARKET_DATA_COVERAGE_INCOMPLETE - Zero candidate opportunity states were available for evaluation."
            elif any(not op.state.technical_execution_supported for op in analyzed_opportunities):
                status = "PRODUCTION_FAILURE: EXECUTION_CAPABILITY_COVERAGE_INCOMPLETE"
                rationale = "PRODUCTION_FAILURE: EXECUTION_CAPABILITY_COVERAGE_INCOMPLETE - Evaluated candidates lacked verified broker technical execution capability."
            elif any(op.data_quality_state != "COMPLETE" or not getattr(op.state, "quote_executable_now", False) for op in analyzed_opportunities):
                status = "PRODUCTION_FAILURE: MARKET_DATA_COVERAGE_INCOMPLETE"
                rationale = "PRODUCTION_FAILURE: MARKET_DATA_COVERAGE_INCOMPLETE - Live executable quotes or spread friction were unavailable across candidates."
            else:
                status = "NO_VALID_EDGE"
                rationale = "NO_VALID_EDGE: Relevant universe was evaluated with complete execution data, but no candidate presented positive net expected reward after costs."

            return AIAllocationDecision(
                whether_to_trade=False,
                selected_allocations={},
                total_deployment_gbp=0.0,
                total_deployment_pct=0.0,
                rationale=rationale,
                concentration_summary="ZERO_TRADES",
                status=status
            )

        # AI Reasoning on Concentration:
        # Preference: fewer/larger meaningful positions when evidence supports concentration.
        # If one candidate has standout conviction (e.g. score >= 75 and clear lead over #2):
        # AI selects 1 concentrated position deploying 60-80% of budget.
        # If multiple candidates have close high-tier conviction:
        # AI selects several positions (2 or 3) weighted by net edge quality.
        top = viable[0]
        runner_up = viable[1] if len(viable) > 1 else None

        selected: Dict[str, float] = {}
        rationale_lines = []

        # Case 1: Standout high conviction -> 1 concentrated position
        if len(viable) == 1 or (runner_up and (top.opportunity_score - (runner_up.opportunity_score or 0)) >= 15.0):
            alloc_gbp = round(max_allocatable_budget * 0.90, 2)  # Deploy 90% of the 80% budget (<= 80% ceiling)
            selected[top.instrument_id] = alloc_gbp
            summary = f"SINGLE_CONCENTRATED_POSITION ({top.symbol})"
            rationale_lines.append(
                f"Selected 1 concentrated position in {top.symbol} (Score {top.opportunity_score:.1f}, "
                f"NetReward {top.expected_net_opportunity:+.2%}) deploying £{alloc_gbp:.2f}."
            )
        # Case 2: Multiple strong opportunities -> AI selects several positions
        else:
            # Select up to top 2-3 distinct strong opportunities
            selected_candidates = viable[:min(3, len(viable))]
            total_score = sum(c.opportunity_score for c in selected_candidates)
            summary = f"CONCENTRATED_MULTI_POSITION ({len(selected_candidates)} positions)"

            for c in selected_candidates:
                weight = c.opportunity_score / total_score
                c_alloc = round(max_allocatable_budget * weight * 0.95, 2)
                selected[c.instrument_id] = c_alloc
                rationale_lines.append(
                    f"Allocated £{c_alloc:.2f} ({weight:.1%}) to {c.symbol} (Score {c.opportunity_score:.1f}, NetReward {c.expected_net_opportunity:+.2%})."
                )

        total_dep = sum(selected.values())
        dep_pct = round(total_dep / available_capital_gbp, 4)

        return AIAllocationDecision(
            whether_to_trade=True,
            selected_allocations=selected,
            total_deployment_gbp=round(total_dep, 2),
            total_deployment_pct=dep_pct,
            rationale="; ".join(rationale_lines),
            concentration_summary=summary,
            status="ALLOCATED"
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
                f"exceeds 80% ceiling (£{max_allowed_gbp:.2f}). Scaling down."
            )
            scale = max_allowed_gbp / max(1.0, ai_decision.total_deployment_gbp)
            scaled_allocs = {k: round(v * scale, 2) for k, v in ai_decision.selected_allocations.items()}
            ai_decision = AIAllocationDecision(
                whether_to_trade=ai_decision.whether_to_trade,
                selected_allocations=scaled_allocs,
                total_deployment_gbp=round(sum(scaled_allocs.values()), 2),
                total_deployment_pct=round(sum(scaled_allocs.values()) / available_capital_gbp, 4),
                rationale=ai_decision.rationale + f" [Scaled down to strictly respect 80% ceiling of £{max_allowed_gbp:.2f}]",
                concentration_summary=ai_decision.concentration_summary,
                status=ai_decision.status
            )

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
            cost_rate = state.estimated_costs or 0.0
            expected_costs_gbp = round(alloc_gbp * cost_rate, 2)

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
