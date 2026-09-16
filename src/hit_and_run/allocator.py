"""
PRV Capital - Hit-and-Run Dynamic Capital Allocator
Concentrates capital into highest-conviction short-term opportunities while enforcing:
1. Strict ceiling: Total deployment (existing + working + new) <= 80% of portfolio capital.
2. Preference for fewer, larger positions over dilution into token trades.
3. Re-concentration: Drops low-allocation candidates below minimum threshold (£250) and re-allocates.
4. Per-holding maximum loss capped at 5.0%.
"""
import math
import logging
from typing import List, Dict, Any, Optional
from src.hit_and_run.models import OpportunityCandidate, AllocationDecision

logger = logging.getLogger("hit_and_run.allocator")


class DynamicCapitalAllocator:
    """
    Allocates portfolio capital dynamically across qualified hit-and-run opportunities.
    """

    def __init__(
        self,
        max_deployment_pct: float = 0.80,
        min_allocation_gbp: float = 250.0
    ):
        self.max_deployment_pct = max_deployment_pct
        self.min_allocation_gbp = min_allocation_gbp

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
        Returns a list of AllocationDecision objects.
        """
        if portfolio_capital <= 0.0 or available_cash <= 0.0:
            return []

        # 1. Calculate Existing Exposure & Ceiling
        current_pos_exposure = sum(float(p.get("current_value_gbp", 0.0)) for p in existing_positions)
        current_ord_exposure = sum(float(o.get("reserved_value_gbp", 0.0)) for o in outstanding_orders)
        current_committed = current_pos_exposure + current_ord_exposure

        max_allowable_exposure = portfolio_capital * self.max_deployment_pct
        remaining_capacity = max(0.0, max_allowable_exposure - current_committed)
        deployable_budget = max(0.0, min(available_cash, remaining_capacity))

        if deployable_budget < self.min_allocation_gbp:
            logger.info(
                f"Allocator: Deployable budget £{deployable_budget:.2f} below minimum allocation threshold "
                f"£{self.min_allocation_gbp:.2f}. No new allocations."
            )
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

        # 4. Iterative Re-concentration: Ensure no allocation is a token trade
        active_candidates = list(qual)
        raw_allocations = []

        while len(active_candidates) > 0:
            scores = [c.opportunity_score for c in active_candidates]
            # Quadratic weighting to favor higher conviction
            weights = [s ** 2 for s in scores]
            sum_w = sum(weights)
            if sum_w <= 0:
                break

            tentative_allocs = [deployable_budget * (w / sum_w) for w in weights]

            # Check if smallest allocation is below minimum threshold
            if len(active_candidates) > 1 and min(tentative_allocs) < self.min_allocation_gbp:
                # Drop lowest candidate and re-concentrate into higher conviction
                dropped = active_candidates.pop()
                logger.debug(f"Allocator: Dropping lower-conviction candidate {dropped.symbol} to avoid token allocation.")
            else:
                raw_allocations = tentative_allocs
                break

        if not active_candidates or not raw_allocations:
            return []

        # Check if single remaining candidate is below minimum threshold
        if raw_allocations[0] < self.min_allocation_gbp:
            return []

        # 5. Build Final Allocation Decisions
        decisions: List[AllocationDecision] = []
        for cand, target_budget in zip(active_candidates, raw_allocations):
            price_gbp = cand.current_price_gbp
            if price_gbp <= 0.0:
                continue

            raw_qty = target_budget / price_gbp
            # Floor to 3 decimal places
            target_qty = math.floor(raw_qty * 1000.0) / 1000.0
            actual_alloc_gbp = round(target_qty * price_gbp, 2)

            if actual_alloc_gbp < self.min_allocation_gbp or target_qty <= 0.0:
                continue

            pct_of_portfolio = round(actual_alloc_gbp / portfolio_capital, 4)
            # Enforce 5.0% maximum loss invariant on holding
            max_loss_pct = min(0.05, cand.downside_risk)
            stop_price = round(cand.current_price * (1.0 - max_loss_pct), 4)

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
