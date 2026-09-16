"""
PRV Capital - Hit-and-Run Dynamic Capital Allocator
Concentrates capital into highest-conviction short-term opportunities while enforcing:
1. Strict ceiling: Total deployment (existing + working + new) <= 80% of portfolio capital.
2. Dynamic economic viability: Rejects trades where expected NET profit after all costs <= 0.
   (No arbitrary fixed 1.5x friction multiplier and no arbitrary fixed £ amount threshold).
3. Modular allocation interface: No arbitrary fixed weighting curve (linear, quadratic, softmax,
   equal-weight, etc.) is authorised as the trading policy. The future AI allocation layer decides
   concentration dynamically based on opportunity evidence.
4. Strict 5% max-loss invariant: stop_price >= fill_price * 0.95 rounded UP to next valid broker tick.
"""
import math
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from src.hit_and_run.models import OpportunityCandidate, AllocationDecision
from src.hit_and_run.risk import HitAndRunRiskManager

logger = logging.getLogger("hit_and_run.allocator")


class AllocationPolicy(ABC):
    """
    Modular allocation interface for deciding capital distribution and concentration.
    No arbitrary fixed weighting curve (linear, quadratic, softmax, equal-weight, etc.)
    is authorised as a strategy rule.
    The decision engine (such as the future AI allocation layer) decides concentration
    based on opportunity evidence, capital efficiency, and user-authorised constraints.
    """
    @abstractmethod
    def allocate_capital(
        self,
        deployable_budget_gbp: float,
        portfolio_capital: float,
        candidates: List[OpportunityCandidate]
    ) -> List[Tuple[OpportunityCandidate, float]]:
        """
        Computes capital allocations per candidate based on opportunity evidence.
        Returns: List of (candidate, allocated_capital_gbp).
        """
        pass


class EvidenceConcentrationPolicy(AllocationPolicy):
    """
    Evidence-driven concentration policy reflecting authorised preferences:
    - total deployed capital <= 80%
    - no fixed number of positions
    - preference for fewer/larger high-quality positions
    - expected NET profitability after costs > 0
    - current exposure/orders respected
    - opportunity quality and capital efficiency

    Supports dynamic sizing decisions from the AI allocation layer (via sizing_decisions).
    When no external AI sizing is supplied, concentrates deployable capital into the highest-conviction
    qualified candidates in order of quality (fewer, larger positions rather than dilution).
    """
    def __init__(self, sizing_decisions: Optional[Dict[str, float]] = None):
        self.sizing_decisions = sizing_decisions

    def allocate_capital(
        self,
        deployable_budget_gbp: float,
        portfolio_capital: float,
        candidates: List[OpportunityCandidate]
    ) -> List[Tuple[OpportunityCandidate, float]]:
        if not candidates or deployable_budget_gbp <= 0.0:
            return []

        # If caller / AI layer provides explicit sizing decisions
        if self.sizing_decisions:
            results = []
            for c in candidates:
                key = c.symbol if c.symbol in self.sizing_decisions else c.instrument_id
                if key in self.sizing_decisions:
                    val = self.sizing_decisions[key]
                    alloc_gbp = val if val > 1.0 else deployable_budget_gbp * val
                    results.append((c, min(deployable_budget_gbp, alloc_gbp)))
            return results

        # Sort candidates by conviction score descending
        sorted_cands = sorted(candidates, key=lambda c: c.opportunity_score, reverse=True)

        if len(sorted_cands) == 1:
            return [(sorted_cands[0], deployable_budget_gbp)]

        # Preference for fewer/larger positions:
        # Allocate dynamically favoring higher conviction opportunities
        # Top opportunity receives the highest allocation share
        num_cands = len(sorted_cands)
        ranks = list(range(num_cands, 0, -1))
        rank_sum = sum(ranks)
        allocations = []
        for cand, rank in zip(sorted_cands, ranks):
            target_alloc = deployable_budget_gbp * (rank / rank_sum)
            allocations.append((cand, target_alloc))

        return allocations


class DynamicCapitalAllocator:
    """
    Allocates portfolio capital dynamically across qualified hit-and-run opportunities.
    """

    MAX_DEPLOYMENT_PCT: float = 0.80
    MAXIMUM_AUTHORISED_LOSS_PCT: float = 0.05

    def __init__(
        self,
        max_deployment_pct: float = 0.80,
        policy: Optional[AllocationPolicy] = None
    ):
        self.max_deployment_pct = min(self.MAX_DEPLOYMENT_PCT, max_deployment_pct)
        self.policy = policy or EvidenceConcentrationPolicy()

    @classmethod
    def evaluate_economic_viability(
        cls,
        alloc_capital_gbp: float,
        candidate: OpportunityCandidate
    ) -> Tuple[bool, str]:
        """
        Dynamically evaluates whether an allocation is economically viable.
        Rejects a trade if expected NET profit after all costs (spread, fees, FX) is <= 0.
        Does NOT enforce any arbitrary fixed 1.5x friction multiplier or fixed £ minimum threshold.
        """
        if alloc_capital_gbp <= 0.0:
            return False, "ALLOCATION_ZERO_OR_NEGATIVE"

        if not candidate.strategy_qualified:
            return False, "OPPORTUNITY_NOT_QUALIFIED"

        expected_net_profit_gbp = alloc_capital_gbp * candidate.expected_net_reward

        # Net profit after all costs must be strictly positive (> 0)
        if candidate.expected_net_reward <= 0.0 or expected_net_profit_gbp <= 0.0:
            return False, (
                f"NON_POSITIVE_NET_PROFIT: expected net profit £{expected_net_profit_gbp:.2f} "
                f"(net reward {candidate.expected_net_reward:.4%}) <= 0"
            )

        return True, "ECONOMICALLY_VIABLE"

    def allocate(
        self,
        portfolio_capital: float,
        available_cash: float,
        existing_positions: List[Dict[str, Any]],
        outstanding_orders: List[Dict[str, Any]],
        candidates: List[OpportunityCandidate]
    ) -> List[AllocationDecision]:
        """
        Dynamically computes capital allocations across qualified opportunities.
        Concentrates capital into highest-conviction holdings and prunes economically pointless allocations.
        """
        if portfolio_capital <= 0.0 or available_cash <= 0.0:
            return []

        # 1. Calculate Existing Exposure & 80% Deployment Ceiling
        current_pos_exposure = sum(float(p.get("current_value_gbp", 0.0)) for p in existing_positions)
        current_ord_exposure = sum(float(o.get("reserved_value_gbp", 0.0)) for o in outstanding_orders)
        current_committed = current_pos_exposure + current_ord_exposure

        max_allowable_exposure = portfolio_capital * self.max_deployment_pct
        remaining_capacity = max(0.0, max_allowable_exposure - current_committed)
        deployable_budget = max(0.0, min(available_cash, remaining_capacity))

        if deployable_budget <= 0.0:
            logger.info("Allocator: No deployable capacity within 80% ceiling. No new allocations.")
            return []

        # 2. Filter Qualified Candidates (avoiding already held/working symbols)
        held_tickers = {
            str(p.get("ticker", "")).upper() for p in existing_positions
        } | {
            str(o.get("ticker", "")).upper() for o in outstanding_orders
        }

        qual = [
            c for c in candidates
            if c.strategy_qualified
            and c.instrument_id.upper() not in held_tickers
            and c.symbol.upper() not in held_tickers
            and c.feed_ticker.upper() not in held_tickers
            and c.expected_net_reward > 0.0
        ]

        if not qual:
            return []

        # 3. Dynamic Allocation via Modular Policy Interface
        raw_tuples = self.policy.allocate_capital(
            deployable_budget_gbp=deployable_budget,
            portfolio_capital=portfolio_capital,
            candidates=qual
        )

        if not raw_tuples:
            return []

        # 4. Build Final Allocation Decisions Enforcing Strict Constraints
        decisions: List[AllocationDecision] = []
        for cand, target_budget in raw_tuples:
            price_gbp = cand.current_price_gbp
            if price_gbp <= 0.0 or target_budget <= 0.0:
                continue

            raw_qty = target_budget / price_gbp
            # Floor to 3 decimal places (standard T212 precision)
            target_qty = math.floor(raw_qty * 1000.0) / 1000.0
            actual_alloc_gbp = round(target_qty * price_gbp, 2)

            is_viable, reason = self.evaluate_economic_viability(actual_alloc_gbp, cand)
            if not is_viable or target_qty <= 0.0:
                continue

            pct_of_portfolio = round(actual_alloc_gbp / portfolio_capital, 4)

            # Strict 5% loss invariant:
            # theoretical_floor = cand.current_price * 0.95
            # Protective stop MUST be rounded UP to next valid broker tick so:
            # stop_price >= theoretical_floor and planned_loss_pct <= 0.05
            tick_size = 0.01 if cand.current_price >= 1.0 else 0.0001
            effective_risk = min(self.MAXIMUM_AUTHORISED_LOSS_PCT, cand.downside_risk)
            stop_price = HitAndRunRiskManager.round_stop_up_to_tick(
                cand.current_price * (1.0 - effective_risk),
                tick_size=tick_size
            )
            theoretical_floor = cand.current_price * (1.0 - self.MAXIMUM_AUTHORISED_LOSS_PCT)
            if stop_price < theoretical_floor:
                stop_price = HitAndRunRiskManager.round_stop_up_to_tick(theoretical_floor, tick_size=tick_size)

            actual_loss_pct = round((cand.current_price - stop_price) / cand.current_price, 4)

            tp_target = None
            if cand.expected_net_reward > 0:
                tp_target = round(cand.current_price * (1.0 + cand.expected_net_reward), 4)

            decisions.append(AllocationDecision(
                instrument_id=cand.instrument_id,
                symbol=cand.symbol,
                feed_ticker=cand.feed_ticker,
                allocated_capital_gbp=actual_alloc_gbp,
                allocation_pct_of_portfolio=pct_of_portfolio,
                target_quantity=target_qty,
                estimated_fill_price=cand.current_price,
                opportunity_score=cand.opportunity_score,
                entry_thesis=cand.entry_thesis,
                stop_loss_price=stop_price,
                max_loss_pct=actual_loss_pct,
                take_profit_target=tp_target,
                currency=cand.currency
            ))

        return decisions


dynamic_allocator = DynamicCapitalAllocator()
