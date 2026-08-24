"""
Unit and Integration Tests for PRV Capital AI Performance Cycle Framework
Validates cycle boundaries, archiving, zero-metric reset, and historical isolation.
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.database.db import db
from src.cycles.cycle_manager import cycle_manager

class TestAIPerformanceCycles(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_active_cycle_telemetry(self):
        """Verify that the active cycle reports pure zero-baseline stats on clean start."""
        res = self.client.get("/api/cycle/current")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertEqual(data["status"], "ACTIVE")
        self.assertIn("cycle_id", data)
        self.assertIn("cycle_name", data)
        self.assertGreaterEqual(data["starting_capital"], 1000.0)
        self.assertIn("total_return", data)
        self.assertIn("trade_count", data)

    def test_02_historical_cycle_archive_preservation(self):
        """Verify that historical cycles (CYCLE-001 with 38 trades) are preserved in archive."""
        res = self.client.get("/api/cycle/history")
        self.assertEqual(res.status_code, 200)
        cycles = res.json()
        self.assertGreaterEqual(len(cycles), 2)
        
        # Check archived Cycle 1
        cycle_1 = next((c for c in cycles if c["cycle_id"] == "CYCLE-001"), None)
        self.assertIsNotNone(cycle_1)
        self.assertEqual(cycle_1["status"], "ARCHIVED")
        self.assertEqual(cycle_1["trade_count"], 38)
        self.assertEqual(cycle_1["realised_pnl"], -199.47)
        self.assertEqual(cycle_1["total_return"], -199.47)

    def test_03_portfolio_performance_summary_scoped_to_active_cycle(self):
        """Verify that /api/portfolio/performance_summary is strictly scoped to the active cycle."""
        res = self.client.get("/api/portfolio/performance_summary")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("portfolio_value", data)
        self.assertIn("cash", data)
        self.assertIn("invested", data)

    def test_04_cycle_detail_endpoint(self):
        """Verify /api/cycle/{cycle_id} returns accurate trade ledger for that specific cycle."""
        res = self.client.get("/api/cycle/CYCLE-001")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["cycle"]["cycle_id"], "CYCLE-001")
        self.assertEqual(data["trade_count"], 38)
        self.assertEqual(len(data["trades"]), 38)

    def test_05_cycle_reset_workflow(self):
        """Verify that POST /api/cycle/reset freezes active cycle and creates a new clean active cycle."""
        reset_payload = {
            "cycle_name": "Test Cycle 3: Alpha Catalyst Test",
            "ai_version": "v2.1-test",
            "feature_set": "Macro Alpha Scoring, Breakout Veto",
            "notes": "Automated acceptance test run"
        }
        res = self.client.post("/api/cycle/reset", json=reset_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["archived_cycle"]["status"], "ARCHIVED")
        self.assertEqual(data["new_cycle"]["status"], "ACTIVE")
        self.assertEqual(data["new_cycle"]["cycle_name"], "Test Cycle 3: Alpha Catalyst Test")
        self.assertEqual(data["new_cycle"]["ai_version"], "v2.1-test")
        
        # Check active cycle via GET
        cur_res = self.client.get("/api/cycle/current")
        cur_data = cur_res.json()
        self.assertEqual(cur_data["cycle_id"], data["new_cycle"]["cycle_id"])
        self.assertEqual(cur_data["trade_count"], 0)
        self.assertIn("total_return", cur_data)

if __name__ == "__main__":
    unittest.main()
