"""
TDD Tests: Hit-and-Run Dynamic Capital Allocator
Verifies:
1. Strict invariant: Total deployment (existing + working + new) <= 80% of portfolio capital.
2. Dynamic sizing: Can allocate to single high-conviction opportunity or multiple opportunities.
3. Concentration preference: Concentrates into highest-conviction opportunities rather than dilution.
4. Dynamic economic viability: Rejects trades where expected NET profit after all costs <= 0.
   Confirms NO fixed 1.5x friction multiplier and NO arbitrary fixed £ amount threshold (e.g. £0.50 or £250).
5. Modular allocation interface: Verifies custom AllocationPolicy can be injected without hardcoded curves.
6. Strict 5% max-loss invariant: stop_price >= fill_price * 0.95 rounded UP to next valid broker tick.
"""
import unittest
from typing import List, Tuple
from src.hit_and_run.models import OpportunityCandidate
from src.hit_and_run.allocator import (
    DynamicCapitalAllocator,
    AllocationPolicy,
    EvidenceConcentrationPolicy
)


class TestDynamicCapitalAllocator(unittest.TestCase):

    def setUp(self):
        self.allocator = DynamicCapitalAllocator(
            max_deployment_pct=0.80
        )

    def _make_candidate(
        self,
        symbol,
        score,
        price_gbp=100.0,
        qualified=True,
        estimated_costs=0.002,
        expected_net_reward=0.080
    ):
        return OpportunityCandidate(
            instrument_id=f"{symbol}_EQ",
            symbol=symbol,
            feed_ticker=symbol,
            product_type="STOCK",
            currency="GBP",
            is_uk_pence=False,
            quote_divisor=1.0,
            current_price=price_gbp,
            current_price_gbp=price_gbp,
            opportunity_score=score,
            strategy_qualified=qualified,
            downside_risk=0.045,  # 4.5% stop loss (within 5% max)
            estimated_costs=estimated_costs,
            expected_net_reward=expected_net_reward,
            risk_reward_ratio=expected_net_reward / 0.045
        )

    def test_single_high_conviction_candidate_receives_concentrated_allocation(self):
        """A single top opportunity can receive the full 80% deployable budget."""
        portfolio_nav = 10000.0
        available_cash = 10000.0
        cand = self._make_candidate("AAPL", score=88.0, price_gbp=150.0)

        allocations = self.allocator.allocate(
            portfolio_capital=portfolio_nav,
            available_cash=available_cash,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[cand]
        )

        self.assertEqual(len(allocations), 1)
        alloc = allocations[0]
        self.assertEqual(alloc.symbol, "AAPL")
        self.assertLessEqual(alloc.allocated_capital_gbp, 8000.0)
        self.assertGreaterEqual(alloc.allocated_capital_gbp, 7900.0)
        self.assertLessEqual(alloc.allocation_pct_of_portfolio, 0.80)
        # Verify 5% max loss invariant on allocation
        self.assertLessEqual(alloc.max_loss_pct, 0.05)
        self.assertGreaterEqual(alloc.stop_loss_price, alloc.estimated_fill_price * 0.95)

    def test_multiple_candidates_concentrates_into_highest_conviction(self):
        """Without external AI sizing decisions, concentrates deployable budget into top candidate (no weighting curve)."""
        portfolio_nav = 10000.0
        available_cash = 10000.0

        c_top = self._make_candidate("TOP", score=90.0, price_gbp=100.0)
        c_mid = self._make_candidate("MID", score=75.0, price_gbp=50.0)
        c_low = self._make_candidate("LOW", score=65.0, price_gbp=25.0)

        allocations = self.allocator.allocate(
            portfolio_capital=portfolio_nav,
            available_cash=available_cash,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[c_top, c_mid, c_low]
        )

        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0].symbol, "TOP")
        self.assertLessEqual(allocations[0].allocated_capital_gbp, 8000.0)
        self.assertGreaterEqual(allocations[0].allocated_capital_gbp, 7900.0)

    def test_multi_position_allocation_with_ai_sizing_decisions(self):
        """When AI decision layer provides sizing decisions, allocator respects them within 80% ceiling."""
        policy = EvidenceConcentrationPolicy(sizing_decisions={"TOP": 5000.0, "MID": 2500.0})
        allocator = DynamicCapitalAllocator(policy=policy)

        c_top = self._make_candidate("TOP", score=90.0, price_gbp=100.0)
        c_mid = self._make_candidate("MID", score=75.0, price_gbp=50.0)

        allocs = allocator.allocate(
            portfolio_capital=10000.0,
            available_cash=10000.0,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[c_top, c_mid]
        )

        self.assertEqual(len(allocs), 2)
        alloc_map = {a.symbol: a.allocated_capital_gbp for a in allocs}
        self.assertGreater(alloc_map["TOP"], alloc_map["MID"])
        self.assertLessEqual(sum(alloc_map.values()), 8000.0)

    def test_modular_allocation_policy_interface(self):
        """Verifies custom AllocationPolicy (e.g. AI allocation layer) can be injected cleanly."""
        class MockAIAllocationPolicy(AllocationPolicy):
            def allocate_capital(
                self,
                deployable_budget_gbp: float,
                portfolio_capital: float,
                candidates: List[OpportunityCandidate]
            ) -> List[Tuple[OpportunityCandidate, float]]:
                # AI decides to put 100% of budget into top conviction candidate
                sorted_cands = sorted(candidates, key=lambda c: c.opportunity_score, reverse=True)
                return [(sorted_cands[0], deployable_budget_gbp)]

        allocator = DynamicCapitalAllocator(policy=MockAIAllocationPolicy())
        c1 = self._make_candidate("AI_PICK", score=95.0, price_gbp=100.0)
        c2 = self._make_candidate("OTHER", score=70.0, price_gbp=50.0)

        allocs = allocator.allocate(
            portfolio_capital=10000.0,
            available_cash=10000.0,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[c1, c2]
        )

        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs[0].symbol, "AI_PICK")
        self.assertGreater(allocs[0].allocated_capital_gbp, 7900.0)

    def test_respects_existing_exposure_and_orders(self):
        """Existing positions (£3000) and orders (£1000) count toward the 80% ceiling (£8000), leaving <= £4000."""
        portfolio_nav = 10000.0
        available_cash = 6000.0
        existing = [{"ticker": "EXISTING_EQ", "current_value_gbp": 3000.0}]
        orders = [{"ticker": "ORDER_EQ", "reserved_value_gbp": 1000.0}]

        cand = self._make_candidate("NEW", score=85.0)

        allocations = self.allocator.allocate(
            portfolio_capital=portfolio_nav,
            available_cash=available_cash,
            existing_positions=existing,
            outstanding_orders=orders,
            candidates=[cand]
        )

        total_allocated = sum(a.allocated_capital_gbp for a in allocations)
        # Total committed = 3000 + 1000 + total_allocated <= 8000
        self.assertLessEqual(total_allocated + 4000.0, 8000.01)

    def test_dynamic_economic_viability_no_1_5x_multiplier_no_fixed_050_minimum(self):
        """
        Dynamic viability:
        - Rejects when expected NET profit after costs <= 0.
        - Does NOT reject when net profit is positive even if < 1.5x friction (NO 1.5x multiplier).
        - Does NOT reject when net profit is positive even if < £0.50 (NO fixed £0.50 threshold).
        """
        # 1. Viable allocation: positive net profit after costs
        cand = self._make_candidate("VIABLE", score=80.0, estimated_costs=0.005, expected_net_reward=0.05)
        viable, reason = DynamicCapitalAllocator.evaluate_economic_viability(1000.0, cand)
        self.assertTrue(viable)
        self.assertEqual(reason, "ECONOMICALLY_VIABLE")

        # 2. Zero or negative capital -> rejected
        not_viable_zero, _ = DynamicCapitalAllocator.evaluate_economic_viability(0.0, cand)
        self.assertFalse(not_viable_zero)

        # 3. Negative net reward (net loss after costs) -> rejected
        neg_cand = self._make_candidate("LOSS", score=80.0, estimated_costs=0.03, expected_net_reward=-0.01)
        not_viable_neg, reason_neg = DynamicCapitalAllocator.evaluate_economic_viability(500.0, neg_cand)
        self.assertFalse(not_viable_neg)
        self.assertIn("NON_POSITIVE_NET_PROFIT", reason_neg)

        # 4. Positive net profit where net reward is less than 1.5x friction (e.g. friction=2%, net reward=1.2% > 0)
        # MUST BE VIABLE (NO 1.5x friction buffer rejection)
        mod_cand = self._make_candidate("MODEST", score=80.0, estimated_costs=0.02, expected_net_reward=0.012)
        viable_mod, reason_mod = DynamicCapitalAllocator.evaluate_economic_viability(500.0, mod_cand)
        self.assertTrue(viable_mod, f"Expected viable without 1.5x buffer, got: {reason_mod}")

        # 5. Small nominal gain (< £0.50, e.g. £0.15) with positive net reward
        # MUST BE VIABLE (NO arbitrary £0.50 threshold)
        tiny_cand = self._make_candidate("TINY", score=80.0, estimated_costs=0.001, expected_net_reward=0.003)
        viable_tiny, reason_tiny = DynamicCapitalAllocator.evaluate_economic_viability(50.0, tiny_cand)
        self.assertTrue(viable_tiny, f"Expected viable without £0.50 threshold, got: {reason_tiny}")

    def test_excludes_candidates_with_non_positive_net_reward(self):
        """Candidates with expected net reward <= 0 are excluded from allocation."""
        c1 = self._make_candidate("PROFITABLE", score=90.0, price_gbp=50.0, expected_net_reward=0.05)
        c2 = self._make_candidate("UNPROFITABLE", score=85.0, price_gbp=50.0, expected_net_reward=-0.01)

        allocs = self.allocator.allocate(
            portfolio_capital=1000.0,
            available_cash=1000.0,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[c1, c2]
        )

        self.assertEqual(len(allocs), 1)
        self.assertEqual(allocs[0].symbol, "PROFITABLE")


if __name__ == "__main__":
    unittest.main()
