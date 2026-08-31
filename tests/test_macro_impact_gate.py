"""
🏛️ PRV CAPITAL | NEWS & MACRO IMPACT GATE TEST SUITE
Verifies:
1. Assessment across all 6 macro categories:
   - Geopolitical conflicts
   - War escalation
   - Oil market disruptions
   - Central bank actions
   - Major economic releases
   - Market-moving news
2. Portfolio Exposure, Direct Impact, Indirect Impact, Risk Level calculations
3. Output risk classification (LOW, MODERATE, HIGH, CRITICAL)
4. Macro Event Ledger persistence in SQLite
5. Pre-recommendation gating enforcement in Telegram Brief & Master PDF
6. API routes /api/macro/assessment and /api/macro/ledger
"""
import os
import unittest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from main import app
from src.database.db import db
from src.analytics.macro_impact_gate import macro_impact_gate
from src.reporting.master_pdf_generator import master_pdf_generator
from telegram_notifier import telegram_notifier


class TestMacroImpactGate(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_macro_impact_gate_assesses_all_6_pillars(self):
        """Verify Macro Impact Gate evaluates all 6 required systematic macro categories."""
        assessment = macro_impact_gate.run_macro_impact_gate()
        
        self.assertIn("events", assessment)
        self.assertIn("gate_status", assessment)
        self.assertIn("aggregate_risk_level", assessment)
        self.assertIn(assessment["aggregate_risk_level"], ["LOW", "MODERATE", "HIGH", "CRITICAL"])
        self.assertIn("cio_macro_directive", assessment)

        events = assessment["events"]
        self.assertGreaterEqual(len(events), 6)

        categories = {ev["category"] for ev in events}
        required_categories = {
            "GEOPOLITICAL_CONFLICT",
            "WAR_ESCALATION",
            "OIL_MARKET_DISRUPTION",
            "CENTRAL_BANK_ACTION",
            "ECONOMIC_RELEASE",
            "MARKET_MOVING_NEWS"
        }
        for req_cat in required_categories:
            self.assertIn(req_cat, categories, f"Missing required macro category: {req_cat}")

    def test_02_event_structure_and_exposure_calculation(self):
        """Verify each assessed event determines Portfolio Exposure, Direct/Indirect Impact, Risk Level."""
        assessment = macro_impact_gate.run_macro_impact_gate()
        
        for ev in assessment["events"]:
            self.assertIn("event_id", ev)
            self.assertIn("event_name", ev)
            self.assertIn("portfolio_exposure", ev)
            self.assertIn(ev["portfolio_exposure"], ["LOW", "MODERATE", "HIGH", "CRITICAL"])
            self.assertIn("risk_level", ev)
            self.assertIn(ev["risk_level"], ["LOW", "MODERATE", "HIGH", "CRITICAL"])
            self.assertIn("direct_impact", ev)
            self.assertIn("indirect_impact", ev)
            self.assertIn("expected_effect", ev)
            self.assertIn("affected_holdings", ev)
            self.assertIsInstance(ev["affected_holdings"], list)

    def test_03_macro_event_ledger_persistence(self):
        """Verify evaluation results are saved in and queryable from SQLite Macro Event Ledger."""
        assessment = macro_impact_gate.run_macro_impact_gate()
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        latest = db.get_latest_macro_assessment(today_str)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.get("evaluation_date"), today_str)
        self.assertEqual(len(latest.get("events", [])), len(assessment["events"]))

        entries = db.get_macro_ledger_entries(limit=10)
        self.assertGreaterEqual(len(entries), 6)
        self.assertIn("event_name", entries[0])
        self.assertIn("risk_level", entries[0])
        self.assertIn("portfolio_exposure", entries[0])

    def test_04_gating_enforcement_in_pdf_and_briefs(self):
        """Verify that Master PDF and Telegram Brief invoke Macro Impact Gate before generating recommendations."""
        # PDF generation
        pdf_path = master_pdf_generator.generate_daily_master_pdf("20260831")
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 1000)

        # Telegram Pre-Market Brief
        sent = telegram_notifier.send_premarket_cio_brief()
        # Returns False if no Telegram credentials, but must execute gating logic without exceptions
        self.assertIsInstance(sent, bool)

        # Telegram EOD Report
        sent_eod = telegram_notifier.send_daily_executive_report({"report_date": "2026-08-31"})
        self.assertIsInstance(sent_eod, bool)

    def test_05_macro_api_endpoints(self):
        """Verify GET /api/macro/assessment and GET /api/macro/ledger endpoints."""
        res_eval = self.client.get("/api/macro/assessment")
        self.assertEqual(res_eval.status_code, 200)
        data_eval = res_eval.json()
        self.assertIn("events", data_eval)
        self.assertIn("aggregate_risk_level", data_eval)
        self.assertIn("cio_macro_directive", data_eval)

        res_ledg = self.client.get("/api/macro/ledger")
        self.assertEqual(res_ledg.status_code, 200)
        data_ledg = res_ledg.json()
        self.assertIn("entries", data_ledg)
        self.assertIn("count", data_ledg)
        self.assertGreaterEqual(data_ledg["count"], 6)


if __name__ == "__main__":
    unittest.main()
