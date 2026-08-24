"""
Unit & Integration Tests for Evidence Classification Engine
"""
import unittest
from fastapi.testclient import TestClient
from main import app
from src.analytics.evidence_classification_engine import evidence_classifier

class TestEvidenceClassificationEngine(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_01_classification_dashboard_endpoint(self):
        """Verify GET /api/evidence/classification_dashboard returns all modules and tier summaries."""
        res = self.client.get("/api/evidence/classification_dashboard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("platform_tier_summary", data)
        self.assertIn("modules_evidence_ledger", data)
        self.assertIn("success_criterion_summary", data)
        
        tiers = [t["tier_name"] for t in data["platform_tier_summary"]]
        self.assertIn("LIVE VALIDATED", tiers)
        self.assertIn("HISTORICAL", tiers)
        self.assertIn("BACKTEST", tiers)
        self.assertIn("THEORETICAL", tiers)

    def test_02_all_eight_modules_classified(self):
        """Verify all 8 required modules are present in the evidence ledger."""
        dashboard = evidence_classifier.get_platform_evidence_dashboard()
        modules = dashboard["modules_evidence_ledger"]
        
        expected_modules = [
            "market_regime_intelligence",
            "probability_calibration",
            "signal_decay_analytics",
            "forecast_accuracy",
            "alpha_attribution",
            "portfolio_health",
            "ranking_engine",
            "opportunity_cost_analysis"
        ]
        
        for m in expected_modules:
            self.assertIn(m, modules)
            self.assertGreaterEqual(len(modules[m]), 1)
            item = modules[m][0]
            self.assertIn("metric", item)
            self.assertIn("value", item)
            self.assertIn("evidence_tier", item)
            self.assertIn("sample_size", item)
            self.assertIn("last_updated", item)

    def test_03_badge_icons_valid(self):
        """Verify that badge icons correctly match epistemic tiers."""
        dashboard = evidence_classifier.get_platform_evidence_dashboard()
        for mod_name, metrics in dashboard["modules_evidence_ledger"].items():
            for m in metrics:
                tier = m["evidence_tier"]
                icon = m["badge_icon"]
                if tier == "LIVE_VALIDATED":
                    self.assertEqual(icon, "🟢")
                elif tier == "HISTORICAL":
                    self.assertEqual(icon, "🟡")
                elif tier == "BACKTEST":
                    self.assertEqual(icon, "🟠")
                elif tier == "THEORETICAL":
                    self.assertEqual(icon, "🔴")

if __name__ == "__main__":
    unittest.main()
