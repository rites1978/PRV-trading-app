"""
Unit & Integration Tests for Phase 4 Execution Intelligence
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.analytics.phase4_execution_intelligence import (
    exit_quality_engine,
    position_upgrade_engine,
    capital_recycling_engine,
    alpha_contribution_engine,
    concentration_risk_engine
)

class TestPhase4ExecutionIntelligence(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_exit_quality_endpoint(self):
        """Verify GET /api/execution/exit_quality returns MFE/MAE and efficiency."""
        res = self.client.get("/api/execution/exit_quality")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("average_exit_efficiency_pct", data)
        self.assertIn("mfe_capture_ratio", data)
        self.assertIn("mae_avoidance_ratio", data)

    def test_02_position_upgrades_endpoint(self):
        """Verify GET /api/execution/position_upgrades identifies upgrade pairs."""
        res = self.client.get("/api/execution/position_upgrades")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("total_upgrade_opportunities", data)
        self.assertIn("upgrade_pairs", data)
        self.assertGreaterEqual(len(data["upgrade_pairs"]), 1)
        pair = data["upgrade_pairs"][0]
        self.assertIn("held_symbol", pair)
        self.assertIn("upgrade_candidate", pair)
        self.assertIn("ev_differential", pair)

    def test_03_capital_recycling_endpoint(self):
        """Verify GET /api/execution/capital_recycling returns velocity metrics."""
        res = self.client.get("/api/execution/capital_recycling")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("recycling_efficiency_score", data)
        self.assertIn("available_dry_powder_gbp", data)

    def test_04_alpha_contributions_endpoint(self):
        """Verify GET /api/execution/alpha_contributions decomposes bps contribution."""
        res = self.client.get("/api/execution/alpha_contributions")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("top_accretive_contributors", data)
        self.assertIn("top_dilutive_contributors", data)
        self.assertIn("full_holdings_contribution_matrix", data)

    def test_05_concentration_risk_endpoint(self):
        """Verify GET /api/execution/concentration_risk audits stock/sector limits and HHI."""
        res = self.client.get("/api/execution/concentration_risk")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("max_single_stock", data)
        self.assertIn("max_sector", data)
        self.assertIn("herfindahl_hirschman_index", data)
        self.assertIn("concentration_risk_status", data)

if __name__ == "__main__":
    unittest.main()
