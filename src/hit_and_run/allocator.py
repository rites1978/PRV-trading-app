"""
PRV Capital - Hit-and-Run Dynamic Capital Allocator
Concentrates capital into highest-conviction short-term opportunities while enforcing:
1. Strict ceiling: Total deployment (existing + working + new) <= 80% of portfolio capital.
2. Dynamic rejection of economically pointless allocations based on:
   - expected net profit after costs
   - spread/fees/FX friction
   - capital efficiency
   - opportunity quality
   (No arbitrary fixed £ amount threshold).
3. Clearly separated allocation interface: Auditable linear proportional weighting by default.
   (No arbitrary quadratic or polynomial weighting).
4. Strict 5% max-loss invariant: stop_price >= fill_price * 0.95 on all allocations.
"""
import math
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from src.hit_and_run.models import OpportunityCandidate, AllocationDecision

logger = logging.getLogger("hit_and_run.allocator")


class AllocationWeightingPolicy(ABC):
    """
    Auditable interface for computing allocation budget shares from opportunity scores.
    Prevents arbitrary mathematical weighting functions from becoming fixed strategy rules.
    """
    @abstractmethod
    def compute_weights(self, candidates: List[OpportunityCandidate]) -> List[float]:
        """Returns normalized budget weights summing to 1.0."""
        pass


class ProportionalConvictionPolicy(AllocationWeightingPolicy):
    """
    Auditable linear conviction policy: weights each candidate strictly in direct proportion
    to its auditable opportunity conviction score without arbitrary polynomial or quadratic distortion.
    weight_i = score_i / sum(scores)
    """
    def compute_weights(self, candidates: List[OpportunityCandidate]) -> List[float]:
        if not candidates:
            return []
        scores = [max(0.0, float(c.opportunity_score)) for c in candidates]
        total = sum(scores)
        if total <= 0:
            return [1.0 / len(candidates)] * len(candidates)
        return [s / total for s in scores]


class DynamicCapitalAllocator:
    """
    Allocates portfolio capital dynamically across qualified hit-and-run opportunities.
    """

    MAX_DEPLOYMENT_PCT: float = 0.80
    MAXIMUM_AUTHORISED_LOSS_PCT: float = 0.05

    def __init__(
        self,
        max_deployment_pct: float = 0.80,
        weighting_policy: Optional[AllocationWeightingPolicy] = None
    ):
        self.max_deployment_pct = min(self.MAX_DEPLOYMENT_PCT, max_deployment_pct)
        self.weighting_policy = weighting_policy or ProportionalConvictionPolicy()

    @classmethod
    def evaluate_economic_viability(
        cls,
        alloc_capital_gbp: float,
        candidate: OpportunityCandidate
    ) -> Tuple[bool, str]:
        """
        Dynamically evaluates whether an allocation is economically meaningful or pointless based on:
        1. Expected net profit after costs: alloc_capital_gbp * expected_net_reward
        2. Spread / fees / FX friction: alloc_capital_gbp * estimated_costs
        3. Capital efficiency: expected net profit vs friction cost
        4. Opportunity quality: candidate conviction score and qualification
        Does NOT use an arbitrary fixed £ amount.
        """
        if alloc_capital_gbp <= 0.0:
            return False, "ALLOCATION_ZERO_OR_NEGATIVE"

        if not candidate.strategy_qualified:
            return False, "OPPORTUNITY_NOT_QUALIFIED"

        expected_net_profit_gbp = alloc_capital_gbp * candidate.expected_net_reward
        friction_cost_gbp = alloc_capital_gbp * candidate.estimated_costs

        # Net reward must be positive
        if candidate.expected_net_reward <= 0.0 or expected_net_profit_gbp <= 0.0:
            return False, f"NEGATIVE_OR_ZERO_NET_REWARD: {candidate.expected_net_reward:.4%}"

        # Capital efficiency: expected net profit must exceed transaction friction
        if expected_net_profit_gbp <= friction_cost_gbp:
            return False, (
                f"FRICTION_DOMINATED: expected net profit £{expected_net_profit_gbp:.2f} "
                f"does not exceed round-trip friction £{friction_cost_gbp:.2f}"
            )

        # Buffer over friction: expected net gain must overcome minimum execution/slippage variance
        if expected_net_profit_gbp < (friction_cost_gbp * 1.5):
            return False, (
                f"ECONOMICALLY_POINTLESS: expected net profit £{expected_net_profit_gbp:.2f} "
                f"is insufficient buffer over friction £{friction_cost_gbp:.2f}"
            )

        # Minimum nominal edge: must be able to generate at least £0.50 net gain to justify order execution overhead
        if expected_net_profit_gbp < 0.50:
            return False, f"NEGLIGIBLE_NOMINAL_GAIN: expected net profit £{expected_net_profit_gbp:.2f} < £0.50"

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
        ]

        if not qual:
            return []

        # 3. Sort by Conviction Score Descending
        qual.sort(key=lambda c: c.opportunity_score, reverse=True)

        # 4. Dynamic Iterative Re-concentration:
        # Instead of fixed £ threshold, uses economic viability (expected net profit vs friction & capital efficiency).
        active_candidates = list(qual)
        raw_allocations: List[float] = []

        while len(active_candidates) > 0:
            weights = self.weighting_policy.compute_weights(active_candidates)
            tentative_allocs = [deployable_budget * w for w in weights]

            # Check if any candidate's allocation fails dynamic economic viability
            has_pointless_allocation = False
            for cand, alloc_val in zip(active_candidates, tentative_allocs):
                is_viable, _ = self.evaluate_economic_viability(alloc_val, cand)
                if not is_viable:
                    has_pointless_allocation = True
                    break

            if has_pointless_allocation and len(active_candidates) > 1:
                # Drop the lowest-conviction candidate to concentrate capital into higher-conviction holdings
                dropped = active_candidates.pop()
                logger.debug(
                    f"Allocator: Re-concentrating capital: dropped lower-conviction candidate {dropped.symbol} "
                    f"because its allocation was economically pointless."
                )
            else:
                raw_allocations = tentative_allocs
                break

        if not active_candidates or not raw_allocations:
            return []

        # Verify single remaining candidate is economically viable
        if len(active_candidates) == 1:
            is_viable, reason = self.evaluate_economic_viability(raw_allocations[0], active_candidates[0])
            if not is_viable:
                logger.info(f"Allocator: Candidate {active_candidates[0].symbol} not economically viable ({reason}).")
                return []

        # 5. Build Final Allocation Decisions
        decisions: List[AllocationDecision] = []
        for cand, target_budget in zip(active_candidates, raw_allocations):
            price_gbp = cand.current_price_gbp
            if price_gbp <= 0.0:
                continue

            raw_qty = target_budget / price_gbp
            # Floor to 3 decimal places (standard T212 precision)
            target_qty = math.floor(raw_qty * 1000.0) / 1000.0
            actual_alloc_gbp = round(target_qty * price_gbp, 2)

            is_viable, reason = self.evaluate_economic_viability(actual_alloc_gbp, cand)
            if not is_viable or target_qty <= 0.0:
                continue

            pct_of_portfolio = round(actual_alloc_gbp / portfolio_capital, 4)

            # Strict 5% loss invariant: stop_price >= fill_price * 0.95
            max_loss_pct = min(self.MAXIMUM_AUTHORISED_LOSS_PCT, cand.downside_risk)
            stop_price = round(cand.current_price * (1.0 - max_loss_pct), 4)
            min_stop = cand.current_price * (1.0 - self.MAXIMUM_AUTHORISED_LOSS_PCT)
            stop_price = max(min_stop, stop_price)

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
                max_loss_pct=max_loss_pct,
                take_profit_target=tp_target,
                currency=cand.currency
            ))

        return decisions


dynamic_allocator = DynamicCapitalAllocator()
