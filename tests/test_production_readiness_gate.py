"""
Unit & Integration Tests for 08:30 Production Readiness Gate & Master PDF Generator
"""
import os
import unittest
from fastapi.testclient import TestClient
from main import app
from src.monitoring.production_readiness_gate import readiness_gate
from src.reporting.master_pdf_generator import master_pdf_generator

class TestProductionReadinessGate(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_readiness_gate_endpoint(self):
        """Verify GET /api/readiness/gate evaluates all 8 verification suites."""
        res = self.client.get("/api/readiness/gate")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("overall_status", data)
        self.assertIn("verification_suites", data)
        self.assertIn(data["overall_status"], ["READY FOR TRADING", "NOT READY FOR TRADING"])
        
        suites = data["verification_suites"]
        self.assertEqual(len(suites), 8)
        self.assertIn("1_infrastructure", suites)
        self.assertIn("2_broker", suites)
        self.assertIn("3_data", suites)
        self.assertIn("4_research_engines", suites)
        self.assertIn("5_phase2_engines", suites)
        self.assertIn("6_phase4_engines", suites)
        self.assertIn("7_phase5_engines", suites)
        self.assertIn("8_reporting", suites)
        
        # Verify all individual suites are PASS
        for s_name, s_data in suites.items():
            self.assertEqual(s_data["status"], "PASS")

    def test_02_master_pdf_generation_endpoint(self):
        """Verify POST /api/reports/generate_master_pdf compiles 20-section PDF."""
        res = self.client.post("/api/reports/generate_master_pdf")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertEqual(data["status"], "SUCCESS")
        self.assertIn("PRV_DAILY_MASTER_REPORT_", data["filename"])
        self.assertTrue(os.path.exists(data["report_path"]))
        self.assertGreater(os.path.getsize(data["report_path"]), 1000)

    def test_03_readiness_history_endpoint(self):
        """Verify GET /api/readiness/history retrieves audit logs."""
        res = self.client.get("/api/readiness/history")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("readiness_history", data)
        self.assertGreaterEqual(len(data["readiness_history"]), 1)

if __name__ == "__main__":
    unittest.main()
