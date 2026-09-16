"""
TDD Tests: Hit-and-Run Dynamic Capital Allocator
Verifies:
1. Strict invariant: Total deployment (existing + working + new) <= 80% of portfolio capital.
2. Dynamic sizing: Can allocate to single high-conviction opportunity or multiple opportunities.
3. Concentration preference: Concentrates into highest-conviction opportunities rather than dilution.
4. Dynamic economic viability: Rejects economically pointless allocations (friction-dominated, negligible net gain)
   and re-concentrates capital, with NO arbitrary fixed £ amount (e.g. £250 removed).
5. Auditable linear weighting policy: Strictly linear proportional weighting without quadratic distortion.
6. Accounts for existing positions and outstanding working orders.
"""
import unittest
from src.hit_and_run.models import OpportunityCandidate
from src.hit_and_run.allocator import (
    DynamicCapitalAllocator,
    AllocationWeightingPolicy,
    ProportionalConvictionPolicy
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
        """Concentrates into top-scoring candidates proportionally, maintaining <=80% total deployment."""
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

        total_allocated = sum(a.allocated_capital_gbp for a in allocations)
        self.assertLessEqual(total_allocated, 8000.0)

        # Top candidate must receive higher allocation than mid or low
        alloc_map = {a.symbol: a.allocated_capital_gbp for a in allocations}
        self.assertGreater(alloc_map["TOP"], alloc_map["MID"])
        if "LOW" in alloc_map:
            self.assertGreater(alloc_map["MID"], alloc_map["LOW"])

    def test_proportional_linear_weighting_policy_no_quadratic_distortion(self):
        """Weights are strictly linear in score proportion: w_i = score_i / sum(scores), not score**2."""
        policy = ProportionalConvictionPolicy()
        c1 = self._make_candidate("C1", score=80.0)
        c2 = self._make_candidate("C2", score=40.0)

        weights = policy.compute_weights([c1, c2])
        # Linear: 80 / (80 + 40) = 80 / 120 = 2/3 ≈ 0.6667
        # Quadratic would be: 80^2 / (80^2 + 40^2) = 6400 / 8000 = 0.80
        self.assertAlmostEqual(weights[0], 2.0 / 3.0, places=4)
        self.assertAlmostEqual(weights[1], 1.0 / 3.0, places=4)

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

    def test_dynamic_economic_viability_evaluation(self):
        """Dynamic viability checks net profit after costs, friction, and capital efficiency (no fixed £ amount)."""
        cand = self._make_candidate("TEST", score=80.0, estimated_costs=0.005, expected_net_reward=0.05)

        # Viable allocation: £1000, expected net profit = £50, friction = £5
        viable, reason = DynamicCapitalAllocator.evaluate_economic_viability(1000.0, cand)
        self.assertTrue(viable)
        self.assertEqual(reason, "ECONOMICALLY_VIABLE")

        # Zero or negative capital -> rejected
        not_viable, reason = DynamicCapitalAllocator.evaluate_economic_viability(0.0, cand)
        self.assertFalse(not_viable)

        # Friction-dominated candidate: friction exceeds expected reward
        friction_cand = self._make_candidate("FRICTION", score=80.0, estimated_costs=0.04, expected_net_reward=0.02)
        not_viable_fric, reason = DynamicCapitalAllocator.evaluate_economic_viability(500.0, friction_cand)
        self.assertFalse(not_viable_fric)
        self.assertIn("FRICTION_DOMINATED", reason)

        # Insufficient buffer over friction: net reward > friction, but < 1.5x friction
        buffer_cand = self._make_candidate("BUFFER", score=80.0, estimated_costs=0.02, expected_net_reward=0.025)
        not_viable_buf, reason_buf = DynamicCapitalAllocator.evaluate_economic_viability(500.0, buffer_cand)
        self.assertFalse(not_viable_buf)
        self.assertIn("ECONOMICALLY_POINTLESS", reason_buf)

        # Negligible nominal gain (< £0.50)
        tiny_gain_cand = self._make_candidate("TINY", score=80.0, estimated_costs=0.001, expected_net_reward=0.002)
        not_viable_tiny, reason = DynamicCapitalAllocator.evaluate_economic_viability(50.0, tiny_gain_cand)
        self.assertFalse(not_viable_tiny)
        self.assertIn("NEGLIGIBLE_NOMINAL_GAIN", reason)

    def test_no_arbitrary_fixed_250_minimum(self):
        """Verifies that an economically viable allocation under £250 is NOT arbitrarily rejected."""
        portfolio_nav = 200.0
        available_cash = 200.0
        # 80% ceiling = £160
        cand = self._make_candidate("SUB250", score=90.0, price_gbp=10.0, estimated_costs=0.001, expected_net_reward=0.08)

        allocations = self.allocator.allocate(
            portfolio_capital=portfolio_nav,
            available_cash=available_cash,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[cand]
        )

        self.assertEqual(len(allocations), 1)
        self.assertLess(allocations[0].allocated_capital_gbp, 250.0)
        self.assertGreaterEqual(allocations[0].allocated_capital_gbp, 150.0)

    def test_reconcentrates_when_lower_candidate_is_economically_pointless(self):
        """When multiple candidates are evaluated and lower candidates fail economic viability, capital re-concentrates."""
        portfolio_nav = 500.0
        available_cash = 500.0
        # Deployable budget = £400 (80%)
        # c1 has high score and high net reward
        c1 = self._make_candidate("HIGH", score=95.0, price_gbp=50.0, estimated_costs=0.002, expected_net_reward=0.10)
        # c2 has lower score and high friction / marginal net reward that makes small allocation pointless
        c2 = self._make_candidate("WEAK", score=65.0, price_gbp=20.0, estimated_costs=0.02, expected_net_reward=0.015)

        allocations = self.allocator.allocate(
            portfolio_capital=portfolio_nav,
            available_cash=available_cash,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[c1, c2]
        )

        # WEAK was dropped because its allocation was economically pointless, concentrating capital into HIGH
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0].symbol, "HIGH")
        self.assertGreater(allocations[0].allocated_capital_gbp, 300.0)


if __name__ == "__main__":
    unittest.main()
