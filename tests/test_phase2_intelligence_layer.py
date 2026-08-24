"""
Unit & Integration Tests for Phase 2 Intelligence Layer
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.analytics.phase2_intelligence_layer import phase2_intelligence

class TestPhase2IntelligenceLayer(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_phase2_full_dashboard(self):
        """Verify GET /api/intelligence/phase2_dashboard returns all 10 modules."""
        res = self.client.get("/api/intelligence/phase2_dashboard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("module_1_market_regime", data)
        self.assertIn("module_2_thesis_drift", data)
        self.assertIn("module_3_research_batting_average", data)
        self.assertIn("module_4_capital_allocation_iq", data)
        self.assertIn("module_5_signal_decay", data)
        self.assertIn("module_6_confidence_vs_reality", data)
        self.assertIn("module_7_investment_committee_ai", data)
        self.assertIn("module_8_alpha_forecast_tracker", data)
        self.assertIn("module_9_portfolio_health_score", data)
        self.assertIn("module_10_learning_engine", data)
        self.assertIn("phase_2_ten_answers", data)

    def test_02_regime_intelligence_breakdown(self):
        """Verify all 5 regimes exist in module 1."""
        regimes = phase2_intelligence.get_market_regime_intelligence()["regimes_breakdown"]
        names = [r["regime"] for r in regimes]
        self.assertIn("STRONG_BULL", names)
        self.assertIn("MILD_BULL", names)
        self.assertIn("SIDEWAYS", names)
        self.assertIn("MILD_BEAR", names)
        self.assertIn("HIGH_VOL_BEAR", names)

    def test_03_thesis_drift_structure(self):
        """Verify thesis drift contains required fields and valid integrity states."""
        drift = phase2_intelligence.get_thesis_drift_monitor()
        self.assertGreaterEqual(len(drift), 1)
        item = drift[0]
        self.assertIn("symbol", item)
        self.assertIn("thesis_strength_score", item)
        self.assertIn("thesis_integrity", item)
        self.assertIn(item["thesis_integrity"], ["STRENGTHENING", "UNCHANGED", "DETERIORATING"])

    def test_04_signal_decay_and_optimal_holding(self):
        """Verify signal decay analytics determines optimal holding period."""
        decay = phase2_intelligence.get_signal_decay_analytics()
        self.assertIn("optimal_holding_period_days", decay)
        self.assertIn("decay_curve", decay)
        self.assertEqual(len(decay["decay_curve"]), 6)

    def test_05_portfolio_health_score_weights(self):
        """Verify portfolio health score composite range and trend."""
        health = phase2_intelligence.get_portfolio_health_score()
        score = health["portfolio_health_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        self.assertIn(health["trend"], ["IMPROVING", "STABLE", "DETERIORATING"])

    def test_06_ten_answers_evidence(self):
        """Verify all 10 Phase 2 success questions are answered."""
        dashboard = phase2_intelligence.get_phase2_full_intelligence_dashboard()
        answers = dashboard["phase_2_ten_answers"]
        self.assertEqual(len(answers), 10)

if __name__ == "__main__":
    unittest.main()
