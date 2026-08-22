"""
Unit & Integration Tests for Statistical Validity & Sample Size Gate Engine
Validates acceptance test cases A, B, and C as well as API endpoints.
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.cycles.validity_engine import validity_engine
from src.cycles.comparison_engine import comparison_engine

class TestStatisticalValidityGate(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_acceptance_case_a(self):
        """
        Acceptance Test Case A:
        Trades: 0, Days: 1, Round-Trip: 0
        Expected:
        Status: INSUFFICIENT DATA (evaluation_eligible=False)
        Score: null (None)
        Confidence: LOW
        """
        eval_result = validity_engine.evaluate_cycle(
            trade_count=0,
            days_running=1,
            round_trip_trades=0
        )
        self.assertFalse(eval_result["evaluation_eligible"])
        self.assertEqual(eval_result["confidence_level"], "LOW")
        self.assertEqual(eval_result["sample_size_classification"], "LOW")
        self.assertIn("More trading evidence required", eval_result["evaluation_reason"])

    def test_02_acceptance_case_b(self):
        """
        Acceptance Test Case B:
        Trades: 25, Days: 35, Round-Trip: 15
        Expected:
        Status: VALID (evaluation_eligible=True)
        Score: Calculated
        Confidence: MEDIUM
        """
        eval_result = validity_engine.evaluate_cycle(
            trade_count=25,
            days_running=35,
            round_trip_trades=15
        )
        self.assertTrue(eval_result["evaluation_eligible"])
        self.assertEqual(eval_result["confidence_level"], "MEDIUM")
        self.assertEqual(eval_result["sample_size_classification"], "MEDIUM")
        self.assertIn("Statistically valid", eval_result["evaluation_reason"])

    def test_03_acceptance_case_c(self):
        """
        Acceptance Test Case C:
        Trades: 120, Days: 180, Round-Trip: 120
        Expected:
        Status: VALID (evaluation_eligible=True)
        Score: Calculated
        Confidence: VERY_HIGH
        """
        eval_result = validity_engine.evaluate_cycle(
            trade_count=120,
            days_running=180,
            round_trip_trades=120
        )
        self.assertTrue(eval_result["evaluation_eligible"])
        self.assertEqual(eval_result["confidence_level"], "VERY_HIGH")
        self.assertEqual(eval_result["sample_size_classification"], "VERY_HIGH")
        self.assertIn("Statistically valid", eval_result["evaluation_reason"])

    def test_04_confidence_classification_model(self):
        """Verify the 4-tier confidence classification model."""
        self.assertEqual(validity_engine.classify_sample_size(0), "LOW")
        self.assertEqual(validity_engine.classify_sample_size(19), "LOW")
        self.assertEqual(validity_engine.classify_sample_size(20), "MEDIUM")
        self.assertEqual(validity_engine.classify_sample_size(49), "MEDIUM")
        self.assertEqual(validity_engine.classify_sample_size(50), "HIGH")
        self.assertEqual(validity_engine.classify_sample_size(99), "HIGH")
        self.assertEqual(validity_engine.classify_sample_size(100), "VERY_HIGH")
        self.assertEqual(validity_engine.classify_sample_size(250), "VERY_HIGH")

    def test_05_api_current_cycle_validity(self):
        """Verify GET /api/cycle/current contains statistical validity fields."""
        res = self.client.get("/api/cycle/current")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("evaluation_eligible", data)
        self.assertIn("confidence_level", data)
        self.assertIn("sample_size_classification", data)
        self.assertIn("evaluation_reason", data)
        self.assertIn("validity_thresholds", data)

    def test_06_api_history_validity(self):
        """Verify GET /api/cycle/history contains statistical validity fields."""
        res = self.client.get("/api/cycle/history")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        for c in data:
            self.assertIn("evaluation_eligible", c)
            self.assertIn("confidence_level", c)
            self.assertIn("duration_days", c)

    def test_07_api_comparison_gating_ineligible(self):
        """Verify GET /api/cycle/comparison blocks scoring when target cycle is ineligible."""
        res = self.client.get("/api/cycle/comparison?mode=previous")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Active cycle has 0 trades and 0 days -> ineligible
        self.assertFalse(data["evaluation_eligible"])
        self.assertEqual(data["classification"], "INSUFFICIENT_DATA")
        self.assertIsNone(data["ai_effectiveness_score"])
        self.assertEqual(data["confidence_level"], "LOW")
        self.assertIn("More trading evidence required", data["evaluation_reason"])

    def test_08_api_comparison_gating_eligible(self):
        """Verify GET /api/cycle/comparison produces score when comparing eligible historical cycles."""
        res = self.client.get("/api/cycle/comparison?cycle_a=CYCLE-001&cycle_b=CYCLE-001&mode=custom")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # CYCLE-001 has 38 trades and 46 days -> eligible
        self.assertTrue(data["evaluation_eligible"])
        self.assertIsNotNone(data["ai_effectiveness_score"])
        self.assertEqual(data["confidence_level"], "MEDIUM")
        self.assertEqual(data["classification"], "NEUTRAL")

if __name__ == "__main__":
    unittest.main()
