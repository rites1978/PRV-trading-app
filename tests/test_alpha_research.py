import unittest
import numpy as np
import pandas as pd
from src.research.fundamental_alpha import fundamental_alpha
from src.research.sector_rotation import sector_rotation
from src.research.news_sentiment import news_sentiment
from src.research.alpha_engine import alpha_engine
from src.risk.event_risk import event_risk_engine
from src.validation.backtest_engine import validation_engine
from src.risk.risk_engine import risk_engine

class TestAlphaResearchAndValidation(unittest.TestCase):

    def test_news_sentiment_polarity(self):
        """Test NLP polarity scoring on bullish vs bearish headlines."""
        bullish_text = "Strong revenue surge and upgrade with record earnings beat"
        bearish_text = "Severe profit plunge and lawsuit warning with downgrade"
        
        pos_pol = news_sentiment.analyze_headline_sentiment(bullish_text)
        neg_pol = news_sentiment.analyze_headline_sentiment(bearish_text)
        
        self.assertGreater(pos_pol, 0.0)
        self.assertLess(neg_pol, 0.0)

    def test_monte_carlo_resampling(self):
        """Test Monte Carlo 1,000-path bootstrap calculations."""
        # 30 synthetic trade returns (60% wins @ +7.0%, 40% losses @ -2.5%)
        synthetic_returns = np.array([0.07 if i % 10 < 6 else -0.025 for i in range(30)])
        mc_results = validation_engine.run_monte_carlo_simulation(synthetic_returns, num_simulations=500)
        
        self.assertEqual(mc_results["simulations_count"], 500)
        self.assertGreater(mc_results["probability_of_profit_pct"], 50.0)
        self.assertGreater(mc_results["ci_95_drawdown_pct"], 0.0)

    def test_event_risk_blackout(self):
        """Test event risk engine blackout verification."""
        safe, reason, meta = event_risk_engine.evaluate_event_blackout("AAPL", "AAPL")
        self.assertIsInstance(safe, bool)
        self.assertIn("status", meta)

    def test_progressive_derisking_tiers(self):
        """Test progressive de-risking at Tier 1 (3%) and Tier 2 (5%)."""
        risk_engine.initialize_day(50000.0)
        open_pos = [{"ticker": "TEST_US_EQ", "quantity": 10.0, "averagePrice": 100.0, "currentPrice": 95.0, "ppl": -50.0}]
        
        # 1. Test nominal NAV (1% drawdown)
        safe, msg, derisked = risk_engine.evaluate_active_derisking(49500.0, open_pos, is_paper=True)
        self.assertTrue(safe)
        self.assertEqual(len(derisked), 0)

        # 2. Test Tier 1 drawdown (3.5% drawdown) -> Should trim 50%
        safe_t1, msg_t1, derisked_t1 = risk_engine.evaluate_active_derisking(48250.0, open_pos, is_paper=True)
        self.assertTrue(safe_t1)
        self.assertTrue(risk_engine.tier1_triggered)
        self.assertEqual(len(derisked_t1), 1)

        # 3. Test Tier 2 drawdown (5.5% drawdown) -> Hard circuit breaker
        safe_t2, msg_t2, derisked_t2 = risk_engine.evaluate_active_derisking(47200.0, open_pos, is_paper=True)
        self.assertFalse(safe_t2)
        self.assertTrue(risk_engine.circuit_breaker_tripped)

if __name__ == "__main__":
    unittest.main()
