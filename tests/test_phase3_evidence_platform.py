"""
Unit & Integration Tests for Phase 3 Production Evidence Platform
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.analytics.phase3_evidence_platform import (
    live_evidence_scorer,
    trade_postmortems,
    regime_learning,
    thesis_db,
    evolution_dashboard
)

class TestPhase3EvidencePlatform(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_live_evidence_score_rules(self):
        """Verify Live Evidence Score respects the 0-20 trades cap of 25."""
        res = self.client.get("/api/evidence/live_score")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("live_evidence_score", data)
        self.assertIn("score_ceiling_cap", data)
        self.assertLessEqual(data["live_evidence_score"], 25.0)
        self.assertEqual(data["score_ceiling_cap"], 25.0)

    def test_02_postmortem_endpoint(self):
        """Verify GET /api/postmortem/trades returns trade postmortems."""
        res = self.client.get("/api/postmortem/trades")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("postmortems", data)
        self.assertGreaterEqual(len(data["postmortems"]), 1)
        pm = data["postmortems"][0]
        self.assertIn("prediction_summary", pm)
        self.assertIn("actual_outcome", pm)
        self.assertIn("lessons_learned", pm)

    def test_03_learning_regimes_endpoint(self):
        """Verify GET /api/learning/regimes returns all 5 regimes."""
        res = self.client.get("/api/learning/regimes")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("STRONG_BULL", data)
        self.assertIn("MILD_BULL", data)
        self.assertIn("SIDEWAYS", data)
        self.assertIn("MILD_BEAR", data)
        self.assertIn("HIGH_VOL_BEAR", data)

    def test_04_learning_thesis_endpoint(self):
        """Verify GET /api/learning/thesis returns best and worst thesis rankings."""
        res = self.client.get("/api/learning/thesis")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("best_thesis_types", data)
        self.assertIn("worst_thesis_types", data)
        self.assertGreaterEqual(len(data["best_thesis_types"]), 1)
        self.assertGreaterEqual(len(data["worst_thesis_types"]), 1)

    def test_05_evolution_dashboard_trends(self):
        """Verify GET /api/evolution/dashboard returns 7d, 30d, 90d, lifetime trends."""
        res = self.client.get("/api/evolution/dashboard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        trends = data["evolution_trends"]
        self.assertIn("7d", trends)
        self.assertIn("30d", trends)
        self.assertIn("90d", trends)
        self.assertIn("lifetime", trends)

if __name__ == "__main__":
    unittest.main()
