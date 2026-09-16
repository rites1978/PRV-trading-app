"""
TDD Tests: OpportunityCandidate and Hit-and-Run Data Models
Tests that OpportunityCandidate accurately encapsulates all short-term evaluation metrics,
validates fields, enforces non-negative prices, and provides serialization.
"""
import unittest
from datetime import datetime, timezone


class TestOpportunityCandidateModel(unittest.TestCase):

    def test_opportunity_candidate_initialization_and_validation(self):
        from src.hit_and_run.models import OpportunityCandidate

        candidate = OpportunityCandidate(
            instrument_id="AAPL_US_EQ",
            symbol="AAPL",
            feed_ticker="AAPL",
            product_type="STOCK",
            currency="USD",
            is_uk_pence=False,
            quote_divisor=1.0,
            current_price=220.50,
            current_price_gbp=168.32,
            momentum=0.035,
            acceleration=0.012,
            relative_strength=0.85,
            liquidity=50000000.0,
            spread_friction=0.0005,
            volatility=0.018,
            volume_activity=1.45,
            distance_from_high=0.015,
            distance_from_low=0.045,
            estimated_costs=0.0020,
            expected_net_reward=0.0280,
            downside_risk=0.0140,
            risk_reward_ratio=2.0,
            opportunity_score=82.5,
            entry_thesis="Strong intraday breakout with 1.45x volume acceleration above morning consolidation",
            technical_execution_supported=True,
            strategy_qualified=True,
            qualification_reasons=["High momentum acceleration", "Favorable risk-reward 2.0x"]
        )

        self.assertEqual(candidate.symbol, "AAPL")
        self.assertEqual(candidate.currency, "USD")
        self.assertEqual(candidate.current_price, 220.50)
        self.assertEqual(candidate.current_price_gbp, 168.32)
        self.assertTrue(candidate.strategy_qualified)
        self.assertTrue(candidate.technical_execution_supported)
        self.assertEqual(candidate.opportunity_score, 82.5)

    def test_candidate_rejects_invalid_price(self):
        from src.hit_and_run.models import OpportunityCandidate

        # Current price must be strictly positive
        with self.assertRaises(ValueError):
            OpportunityCandidate(
                instrument_id="INVALID_EQ",
                symbol="INV",
                feed_ticker="INV",
                product_type="STOCK",
                currency="GBP",
                is_uk_pence=False,
                quote_divisor=1.0,
                current_price=0.0,  # Invalid
                current_price_gbp=0.0
            )

    def test_candidate_serialization(self):
        from src.hit_and_run.models import OpportunityCandidate

        candidate = OpportunityCandidate(
            instrument_id="TSLA_US_EQ",
            symbol="TSLA",
            feed_ticker="TSLA",
            product_type="STOCK",
            currency="USD",
            is_uk_pence=False,
            quote_divisor=1.0,
            current_price=240.0,
            current_price_gbp=183.0,
            opportunity_score=78.0,
            strategy_qualified=True
        )

        d = candidate.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["symbol"], "TSLA")
        self.assertEqual(d["opportunity_score"], 78.0)


if __name__ == "__main__":
    unittest.main()
