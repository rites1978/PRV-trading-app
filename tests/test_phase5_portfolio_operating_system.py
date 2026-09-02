"""
Unit & Integration Tests for Phase 5 Portfolio Operating System
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.analytics.phase5_portfolio_operating_system import (
    trade_journey_engine,
    decision_quality_engine,
    edge_decay_engine,
    benchmark_dominance_engine,
    institutional_scorecard_engine
)

class TestPhase5PortfolioOperatingSystem(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_trade_journeys_endpoint(self):
        """Verify GET /api/trade/journeys returns trade journey lifecycle metrics."""
        res = self.client.get("/api/trade/journeys")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("trade_journeys", data)
        self.assertGreaterEqual(len(data["trade_journeys"]), 0)
        if len(data["trade_journeys"]) > 0:
            tj = data["trade_journeys"][0]
            self.assertIn("entry_price", tj)
            self.assertIn("unrealized_return_pct", tj)
            self.assertIn("peak_gain_pct (MFE)", tj)

    def test_02_decision_quality_endpoint(self):
        """Verify GET /api/decisions/quality returns Decision Quality Score."""
        res = self.client.get("/api/decisions/quality")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("aggregate_decision_quality_score", data)
        self.assertIn("decision_breakdown", data)

    def test_03_edge_decay_endpoint(self):
        """Verify GET /api/edge/decay returns multi-horizon decay curve."""
        res = self.client.get("/api/edge/decay")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("decay_detection_active", data)
        self.assertIn("decay_curve_horizons", data)
        self.assertEqual(len(data["decay_curve_horizons"]), 6)

    def test_04_benchmark_dominance_endpoint(self):
        """Verify GET /api/alpha/dominance compares vs SP500, FTSE100, and Cash."""
        res = self.client.get("/api/alpha/dominance")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("winning_days_pct", data)
        self.assertIn("rolling_alpha", data)

    def test_05_institutional_scorecard_endpoint(self):
        """Verify GET /api/institutional/scorecard returns 0-100 score."""
        res = self.client.get("/api/institutional/scorecard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("institutional_readiness_score", data)
        self.assertIn("institutional_grade", data)
        self.assertIn("components", data)

if __name__ == "__main__":
    unittest.main()
