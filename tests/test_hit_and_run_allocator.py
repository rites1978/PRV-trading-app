"""
TDD Tests: Hit-and-Run Dynamic Capital Allocator
Verifies:
1. Strict invariant: Total deployment (existing + working + new) <= 80% of portfolio capital.
2. Dynamic sizing: Can allocate to single high-conviction opportunity or multiple opportunities.
3. Concentration preference: Concentrates into highest-conviction opportunities rather than dilution.
4. Token allocation rejection: Drops economically insignificant allocations and re-concentrates capital.
5. Accounts for existing positions and outstanding working orders.
"""
import unittest
from src.hit_and_run.models import OpportunityCandidate


class TestDynamicCapitalAllocator(unittest.TestCase):

    def setUp(self):
        from src.hit_and_run.allocator import DynamicCapitalAllocator
        self.allocator = DynamicCapitalAllocator(
            max_deployment_pct=0.80,
            min_allocation_gbp=250.0
        )

    def _make_candidate(self, symbol, score, price_gbp=100.0, qualified=True):
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
            downside_risk=0.045,  # 4.5% stop loss
            expected_net_reward=0.090,  # 9.0% target
            risk_reward_ratio=2.0
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

    def test_rejects_token_allocations_and_reconcentrates(self):
        """When budget is small, drops low-conviction candidates rather than creating token positions < £250."""
        portfolio_nav = 1000.0  # Small portfolio
        available_cash = 1000.0
        # 80% ceiling = £800
        c1 = self._make_candidate("C1", score=90.0)
        c2 = self._make_candidate("C2", score=85.0)
        c3 = self._make_candidate("C3", score=65.0)
        c4 = self._make_candidate("C4", score=62.0)

        allocations = self.allocator.allocate(
            portfolio_capital=portfolio_nav,
            available_cash=available_cash,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[c1, c2, c3, c4]
        )

        for a in allocations:
            self.assertGreaterEqual(a.allocated_capital_gbp, 250.0)

        total_allocated = sum(a.allocated_capital_gbp for a in allocations)
        self.assertLessEqual(total_allocated, 800.0)


if __name__ == "__main__":
    unittest.main()
