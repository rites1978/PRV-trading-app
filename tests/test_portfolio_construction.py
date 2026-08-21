import unittest
import numpy as np
import pandas as pd
from src.portfolio.portfolio_constructor import portfolio_constructor
from src.portfolio.capital_manager import capital_manager

class TestPortfolioConstruction(unittest.TestCase):

    def setUp(self):
        # Create synthetic price series
        dates = pd.date_range("2026-01-01", periods=60)
        prices = [100.0 + i * 0.5 + np.sin(i) * 2 for i in range(60)]
        self.df = pd.DataFrame({"Close": prices, "High": [p + 1.0 for p in prices], "Low": [p - 1.0 for p in prices]}, index=dates)

    def test_atr_risk_sizing(self):
        """Verify ATR risk sizing calculation scales properly."""
        units, cost, meta = portfolio_constructor.calculate_optimal_position_size(
            symbol="TEST",
            price=100.0,
            atr=2.5,
            df=self.df,
            core_capital=50000.0,
            available_cash=45000.0,
            remaining_capacity=25000.0,
            current_holding_val=0.0
        )
        self.assertGreater(units, 0.0)
        self.assertLessEqual(cost, 4000.0) # Within 8% position cap
        self.assertIn("vol_multiplier", meta)
        self.assertIn("correlation_multiplier", meta)

    def test_idle_cash_audit_breakdown(self):
        """Verify idle cash accounting divides cash into exact buckets."""
        breakdown = capital_manager.generate_idle_cash_audit(
            core_capital=50000.0,
            available_cash=44678.46,
            active_capital=5315.18,
            market_regime="STRONG"
        )
        self.assertEqual(len(breakdown), 3)
        self.assertEqual(breakdown[0]["bucket"], "Cash Safety Buffer")
        self.assertEqual(breakdown[0]["amount"], 2500.0) # 5% of 50k

if __name__ == "__main__":
    unittest.main()
