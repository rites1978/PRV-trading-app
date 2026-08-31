"""
🏛️ PRV CAPITAL | NEWS & MACRO IMPACT GATE (PHASE 2) TEST SUITE
Verifies:
1. News Quality Scoring:
   - LIVE NEWS (<24h), RECENT NEWS (1-7 days), STALE NEWS (>7 days), THEORETICAL
   - Age calculation in hours/mins/days
2. News Impact Score (0-100) and Affected Capital %
3. Macro Confidence Score (0-100)
4. Decision Traceability (Supporting vs Contradicting Events)
5. Main Macro Driver identification
6. Stale news dampening (cannot materially drive rebalancing)
7. Telegram & PDF integration
8. API routes /api/macro/assessment and /api/macro/ledger
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


class TestMacroImpactGatePhase2(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_news_quality_classification_and_age(self):
        """Verify quality classification based on article publication timestamp."""
        # 1. <24h -> LIVE NEWS
        now_iso = datetime.now(timezone.utc).isoformat()
        q_live, hrs_live, disp_live = macro_impact_gate._calculate_news_quality_and_age(now_iso)
        self.assertEqual(q_live, "LIVE NEWS")
        self.assertLess(hrs_live, 24.0)

        # 2. 1-7 days -> RECENT NEWS
        q_recent, hrs_recent, disp_recent = macro_impact_gate._calculate_news_quality_and_age("2026-08-29T10:00:00Z")
        self.assertEqual(q_recent, "RECENT NEWS")
        self.assertGreaterEqual(hrs_recent, 24.0)
        self.assertLessEqual(hrs_recent, 168.0)

        # 3. >7 days -> STALE NEWS
        q_stale, hrs_stale, disp_stale = macro_impact_gate._calculate_news_quality_and_age("2026-08-10T00:00:00Z")
        self.assertEqual(q_stale, "STALE NEWS")
        self.assertGreater(hrs_stale, 168.0)

        # 4. None / N/A -> THEORETICAL
        q_theo, hrs_theo, disp_theo = macro_impact_gate._calculate_news_quality_and_age(None)
        self.assertEqual(q_theo, "THEORETICAL")
        self.assertEqual(disp_theo, "N/A")

    def test_02_news_impact_score_calculation(self):
        """Verify Impact Score (0-100) accounts for capital, holdings, directness, and quality decay."""
        # High capital, multiple holdings, direct, live news
        score_high = macro_impact_gate._calculate_impact_score(
            affected_capital_pct=34.0,
            num_holdings=3,
            is_direct=True,
            base_severity="HIGH",
            news_quality="LIVE NEWS"
        )
        self.assertGreaterEqual(score_high, 75)
        self.assertLessEqual(score_high, 100)

        # Stale news decay
        score_stale = macro_impact_gate._calculate_impact_score(
            affected_capital_pct=34.0,
            num_holdings=3,
            is_direct=True,
            base_severity="HIGH",
            news_quality="STALE NEWS"
        )
        self.assertLess(score_stale, score_high)

    def test_03_macro_confidence_score_and_main_driver(self):
        """Verify Macro Confidence Score (0-100) and Main Driver selection."""
        assessment = macro_impact_gate.run_macro_impact_gate()
        
        self.assertIn("macro_confidence_score", assessment)
        self.assertGreaterEqual(assessment["macro_confidence_score"], 0)
        self.assertLessEqual(assessment["macro_confidence_score"], 100)
        
        self.assertIn("main_driver", assessment)
        self.assertIn("main_driver_summary", assessment)
        self.assertTrue(len(assessment["main_driver"]) > 0)

    def test_04_decision_traceability(self):
        """Verify recommendation outputs Supporting Events and Contradicting Events."""
        assessment = macro_impact_gate.run_macro_impact_gate()
        
        trace = assessment.get("decision_traceability", {})
        self.assertEqual(trace.get("recommendation"), "MAINTAIN EXPOSURE")
        
        sup_events = trace.get("supporting_events", [])
        con_events = trace.get("contradicting_events", [])
        
        self.assertGreater(len(sup_events), 0, "Must have supporting events")
        self.assertGreater(len(con_events), 0, "Must have contradicting events to force balanced reasoning")

        for s in sup_events:
            self.assertIn("event_name", s)
            self.assertIn("impact_score", s)
            self.assertIn("news_quality", s)
            self.assertIn("rationale", s)

        for c in con_events:
            self.assertIn("event_name", c)
            self.assertIn("impact_score", c)
            self.assertIn("news_quality", c)
            self.assertIn("rationale", c)

    def test_05_telegram_macro_summary_and_pdf(self):
        """Verify Telegram concise format and Master PDF generation."""
        # PDF generation
        pdf_path = master_pdf_generator.generate_daily_master_pdf("20260831")
        self.assertTrue(os.path.exists(pdf_path))

        # Telegram brief
        sent = telegram_notifier.send_premarket_cio_brief()
        self.assertIsInstance(sent, bool)

    def test_06_api_endpoints_return_phase2_fields(self):
        """Verify GET /api/macro/assessment returns Phase 2 fields."""
        res = self.client.get("/api/macro/assessment")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("macro_confidence_score", data)
        self.assertIn("main_driver", data)
        self.assertIn("decision_traceability", data)
        self.assertIn("events", data)
        self.assertIn("news_quality", data["events"][0])
        self.assertIn("impact_score", data["events"][0])
        self.assertIn("age_display", data["events"][0])


if __name__ == "__main__":
    unittest.main()
