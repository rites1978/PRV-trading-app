"""
Unit and Integration Tests for Live Alpha Validation Protocol Service
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.monitoring.live_alpha_validator import live_alpha_validator

class TestLiveAlphaValidator(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_live_validation_scorecard_endpoint(self):
        """Verify that GET /api/validation/live_scorecards returns all scorecards and frozen status."""
        res = self.client.get("/api/validation/live_scorecards")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("strategy_status", data)
        self.assertEqual(data["strategy_status"], "FROZEN (Zero Changes Allowed)")
        self.assertIn("validation_stage", data)
        self.assertIn("scoreboard_a_rolling_20", data)
        self.assertIn("scoreboard_b_rolling_50", data)
        self.assertIn("scoreboard_c_benchmarks", data)
        self.assertIn("recent_trade_ledger", data)
        
        sb_a = data["scoreboard_a_rolling_20"]
        self.assertIn("sample_status", sb_a)
        self.assertIn("brier_score", sb_a)
        
        sb_b = data["scoreboard_b_rolling_50"]
        self.assertIn("sample_status", sb_b)
        self.assertIn("sharpe_ratio", sb_b)
        self.assertIn("sortino_ratio", sb_b)
        
        sb_c = data["scoreboard_c_benchmarks"]
        self.assertIn("prv_capital_return_pct", sb_c)
        self.assertIn("sp500_benchmark_pct", sb_c)
        self.assertIn("ftse100_benchmark_pct", sb_c)
        self.assertIn("cash_risk_free_pct", sb_c)

    def test_02_validation_progression_gates(self):
        """Verify that validation gates correctly lock statistical claims until milestones are reached."""
        scorecard = live_alpha_validator.get_live_validation_scorecard()
        # If total completed trades < 20, stage must be STAGE_1_EVIDENCE_COLLECTION
        if scorecard["total_completed_trades"] < 20:
            self.assertEqual(scorecard["validation_stage"], "STAGE_1_EVIDENCE_COLLECTION")
            self.assertEqual(scorecard["confidence_level"], "LOW")
            self.assertEqual(scorecard["scoreboard_a_rolling_20"]["is_active"], False)
            self.assertEqual(scorecard["scoreboard_b_rolling_50"]["is_active"], False)

if __name__ == "__main__":
    unittest.main()
