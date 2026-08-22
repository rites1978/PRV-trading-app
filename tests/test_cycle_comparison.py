"""
Unit & Integration Tests for AI Cycle Comparison Scorecard
Validates effectiveness scoring, delta computation, and persistence.
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.database.db import db
from src.cycles.comparison_engine import comparison_engine

class TestCycleComparisonScorecard(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_scoring_model_acceptance_criteria(self):
        """
        Acceptance Test:
        Cycle 001: Return -0.40%, Win Rate 10.5%, Profit Factor 0.61, Drawdown 4.2%
        Cycle 002: Return +2.10%, Win Rate 48.0%, Profit Factor 1.47, Drawdown 1.8%
        Improvement: Return +2.50%, Win Rate +37.5%, PF +0.86, Drawdown +2.4%
        Expected Output: AI Effectiveness Score: 84.2, Classification: IMPROVED
        """
        eval_result = comparison_engine.calculate_effectiveness_score(
            return_pct_delta=2.50,
            profit_factor_delta=0.86,
            win_rate_delta=37.5,
            drawdown_delta=2.4
        )
        self.assertEqual(eval_result["ai_effectiveness_score"], 84.2)
        self.assertEqual(eval_result["classification"], "IMPROVED")

    def test_02_scoring_model_exceptional_classification(self):
        """Verify 90+ score yields EXCEPTIONAL."""
        eval_result = comparison_engine.calculate_effectiveness_score(
            return_pct_delta=4.00,
            profit_factor_delta=1.50,
            win_rate_delta=50.0,
            drawdown_delta=3.5
        )
        self.assertGreaterEqual(eval_result["ai_effectiveness_score"], 90.0)
        self.assertEqual(eval_result["classification"], "EXCEPTIONAL")

    def test_03_scoring_model_degraded_classification(self):
        """Verify negative deltas yield DEGRADED score."""
        eval_result = comparison_engine.calculate_effectiveness_score(
            return_pct_delta=-2.50,
            profit_factor_delta=-0.80,
            win_rate_delta=-25.0,
            drawdown_delta=-2.0
        )
        self.assertLess(eval_result["ai_effectiveness_score"], 50.0)
        self.assertEqual(eval_result["classification"], "DEGRADED")

    def test_04_api_cycle_comparison_previous_mode(self):
        """Verify GET /api/cycle/comparison with default previous mode."""
        res = self.client.get("/api/cycle/comparison?mode=previous")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("current_cycle", data)
        self.assertIn("previous_cycle", data)
        self.assertIn("improvement", data)
        self.assertIn("ai_effectiveness_score", data)
        self.assertIn("classification", data)
        self.assertIn("return_pct_delta", data["improvement"])
        self.assertIn("win_rate_delta", data["improvement"])
        self.assertIn("profit_factor_delta", data["improvement"])
        self.assertIn("drawdown_delta", data["improvement"])

    def test_05_api_cycle_comparison_custom_mode(self):
        """Verify GET /api/cycle/comparison with custom cycle_a and cycle_b."""
        res = self.client.get("/api/cycle/comparison?cycle_a=CYCLE-001&cycle_b=CYCLE-001&mode=custom")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertEqual(data["current_cycle"]["cycle_id"], "CYCLE-001")
        self.assertEqual(data["previous_cycle"]["cycle_id"], "CYCLE-001")
        self.assertEqual(data["previous_cycle"]["trade_count"], 38)
        self.assertTrue(data["evaluation_eligible"])
        self.assertIsInstance(data["ai_effectiveness_score"], float)

    def test_06_comparison_persistence(self):
        """Verify comparisons are persisted into ai_cycle_comparisons table."""
        records = db.get_recent_comparisons(limit=10)
        self.assertIsInstance(records, list)
        self.assertGreater(len(records), 0)
        latest = records[0]
        self.assertIn("ai_effectiveness_score", latest)
        self.assertIn("classification", latest)

if __name__ == "__main__":
    unittest.main()
