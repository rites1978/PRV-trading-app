"""
Unit & Integration Tests for Capital Recycling Shadow Portfolio Engine
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.analytics.shadow_portfolio_engine import shadow_portfolio_engine

class TestShadowPortfolioEngine(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_evaluate_shadow_comparison(self):
        """Verify shadow comparison computes Portfolio A vs Portfolio B correctly."""
        res = shadow_portfolio_engine.evaluate_shadow_comparison()
        self.assertIn("winning_portfolio", res)
        self.assertIn("portfolio_a_live", res)
        self.assertIn("portfolio_b_shadow", res)
        self.assertIn("spread_summary", res)

        a = res["portfolio_a_live"]
        b = res["portfolio_b_shadow"]
        spread = res["spread_summary"]

        self.assertEqual(a["name"], "Portfolio A (Current Live Holdings)")
        self.assertEqual(b["name"], "Portfolio B (Ideal Rankings & Sizing)")
        self.assertEqual(res["winning_portfolio"], "PORTFOLIO B (SHADOW IDEAL)")
        self.assertGreater(b["return_pct"], a["return_pct"])
        self.assertGreater(b["average_ev_pct"], a["average_ev_pct"])
        self.assertGreater(spread["opportunity_cost_gbp"], 0)

    def test_02_api_shadow_comparison_endpoint(self):
        """Verify GET /api/shadow/comparison returns 200 OK with full payload."""
        res = self.client.get("/api/shadow/comparison")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["winning_portfolio"], "PORTFOLIO B (SHADOW IDEAL)")
        self.assertIn("spread_summary", data)

    def test_03_api_shadow_history_endpoint(self):
        """Verify GET /api/shadow/history returns comparison audit records."""
        res = self.client.get("/api/shadow/history")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("comparison_history", data)
        self.assertGreaterEqual(len(data["comparison_history"]), 1)

if __name__ == "__main__":
    unittest.main()
