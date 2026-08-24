"""
Unit & Integration Tests for Research Prediction Scoreboard & Accountability Engine
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.analytics.research_prediction_scoreboard import research_scoreboard
from src.database.db import db

class TestResearchPredictionScoreboard(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_scoreboard_endpoint(self):
        """Verify GET /api/research/scoreboard returns all required dashboards."""
        res = self.client.get("/api/research/scoreboard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("accuracy_dashboard", data)
        self.assertIn("ev_validation_dashboard", data)
        self.assertIn("probability_calibration_dashboard", data)
        self.assertIn("catalyst_attribution_dashboard", data)
        self.assertIn("alpha_attribution_engine", data)
        self.assertIn("capital_efficiency_dashboard", data)
        self.assertIn("validation_rules", data)
        self.assertIn("five_core_questions", data)
        self.assertIn("recent_prediction_ledger", data)

    def test_02_accuracy_dashboard_structure(self):
        """Verify that accuracy dashboard tracks predictions, correct/incorrect, and accuracy %."""
        sb = research_scoreboard.get_full_scoreboard()
        acc = sb["accuracy_dashboard"]
        
        self.assertIn("predictions_tracked", acc)
        self.assertIn("open_active_predictions", acc)
        self.assertIn("completed_predictions", acc)
        self.assertIn("correct_predictions", acc)
        self.assertIn("incorrect_predictions", acc)
        self.assertIn("research_accuracy_pct", acc)
        self.assertGreaterEqual(acc["predictions_tracked"], 13)

    def test_03_ev_validation_buckets(self):
        """Verify EV validation dashboard contains all 4 required buckets."""
        sb = research_scoreboard.get_full_scoreboard()
        ev_dash = sb["ev_validation_dashboard"]
        
        bucket_names = [b["ev_bucket"] for b in ev_dash]
        self.assertIn("5.5%+", bucket_names)
        self.assertIn("5.0% - 5.5%", bucket_names)
        self.assertIn("4.5% - 5.0%", bucket_names)
        self.assertIn("Below 4.5%", bucket_names)

    def test_04_catalyst_categories_tracked(self):
        """Verify all 8 catalyst categories are present in catalyst attribution dashboard."""
        sb = research_scoreboard.get_full_scoreboard()
        cat_dash = sb["catalyst_attribution_dashboard"]
        
        cats = [c["catalyst_category"] for c in cat_dash]
        expected_cats = ["EARNINGS", "FDA", "PRODUCT_LAUNCH", "AI", "M_AND_A", "COMMODITY", "MACRO", "REGULATORY"]
        for c in expected_cats:
            self.assertIn(c, cats)

    def test_05_capital_efficiency_dead_capital_score(self):
        """Verify capital efficiency dashboard ranks holdings by dead capital score."""
        res = self.client.get("/api/research/capital_efficiency")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        cap_eff = data["capital_efficiency_dashboard"]
        self.assertGreaterEqual(len(cap_eff), 1)
        self.assertIn("dead_capital_score", cap_eff[0])
        self.assertIn("opportunity_cost_gbp", cap_eff[0])

    def test_06_validation_rules_enforcement(self):
        """Verify that validation rules block claims until 20 completed trades."""
        sb = research_scoreboard.get_full_scoreboard()
        rules = sb["validation_rules"]
        self.assertIn("declaration_permission", rules)
        self.assertIn("BLOCKED", rules["declaration_permission"])

if __name__ == "__main__":
    unittest.main()
