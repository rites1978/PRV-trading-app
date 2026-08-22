"""
Unit and Integration Tests for PRV Capital Daily Executive Report Feature
"""
import unittest
from fastapi.testclient import TestClient
from src.api.routes import app
from src.database.db import db
from src.reporting.daily_executive_report import daily_report_service

class TestDailyExecutiveReport(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.service = daily_report_service

    def test_generate_daily_report_structure(self):
        report = self.service.generate_daily_report()
        self.assertIn("report_date", report)
        self.assertIn("portfolio_summary", report)
        self.assertIn("daily_pnl", report)
        self.assertIn("cash_position", report)
        self.assertIn("trades_opened", report)
        self.assertIn("trades_closed", report)
        self.assertIn("ai_decisions", report)
        self.assertIn("rejected_opportunities", report)
        self.assertIn("compliance_events", report)
        self.assertIn("cooldown_events", report)
        self.assertIn("market_regime", report)
        self.assertIn("open_positions", report)

    def test_database_persistence_and_retrieval(self):
        report = self.service.generate_daily_report(report_date="2026-08-22")
        db.save_daily_executive_report(report)
        
        saved = db.get_latest_daily_executive_report("2026-08-22")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.get("report_date"), "2026-08-22")
        self.assertEqual(saved.get("compliance_events", {}).get("status"), "PASS")

        history = db.get_daily_executive_reports_history(limit=5)
        self.assertIsInstance(history, list)
        self.assertGreater(len(history), 0)

    def test_api_get_daily_report(self):
        res = self.client.get("/api/reports/daily")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("portfolio_summary", data)
        self.assertEqual(data["portfolio_summary"]["nav"], 49998.0)

    def test_api_dispatch_daily_report(self):
        res = self.client.post("/api/reports/dispatch")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "dispatched")
        self.assertIn("channels", data)

    def test_api_get_reports_history(self):
        res = self.client.get("/api/reports/history")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)

if __name__ == "__main__":
    unittest.main()
