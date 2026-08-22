import unittest
from src.catalyst.catalyst_engine import catalyst_engine, CatalystCategory
from src.database.db import db

class TestCatalystIntelligenceEngine(unittest.TestCase):
    def test_scoring_high_conviction_earnings(self):
        score, tier, factors = catalyst_engine.compute_catalyst_score(
            category=CatalystCategory.COMPANY_EARNINGS,
            source="EARNINGS_RELEASE",
            news_importance=90.0,
            sentiment_polarity=0.85,
            volume_expansion_ratio=2.5,
            price_reaction_pct=3.5,
            sector_relevance=85.0
        )
        self.assertGreaterEqual(score, 81.0)
        self.assertEqual(tier, "HIGH_CONVICTION_CATALYST")
        self.assertIn("news_importance", factors)

    def test_scoring_social_post_veto(self):
        score, tier, factors = catalyst_engine.compute_catalyst_score(
            category=CatalystCategory.POLITICAL_POLICY,
            source="PUBLIC_FIGURE_TRUTH_SOCIAL",
            news_importance=60.0,
            sentiment_polarity=0.50,
            volume_expansion_ratio=1.0,
            price_reaction_pct=0.5,
            sector_relevance=40.0
        )
        self.assertLess(score, 66.0)
        self.assertIn(tier, ["WATCH", "IGNORE"])

    def test_anti_hype_safety_gating(self):
        # Scenario: High catalyst score but failed technicals -> MUST BE VETOED
        approved, summary, reasons = catalyst_engine.evaluate_catalyst_deployment_gate(
            catalyst_score=90.0,
            technical_score=50.0,  # Below 65.0 threshold
            boardroom_quorum=80.0,
            reward_risk_ratio=3.5,
            sector_exposure_pct_nav=10.0,
            max_correlation=0.40,
            is_market_open=True
        )
        self.assertFalse(approved)
        self.assertTrue(any("Anti-Hype" in r for r in reasons))

    def test_catalyst_dashboard_payload(self):
        payload = catalyst_engine.get_dashboard_payload()
        self.assertEqual(payload["module_status"], "RESEARCH_MONITOR_ACTIVE")
        self.assertGreaterEqual(payload["active_catalysts_count"], 1)
        self.assertIn("active_catalysts", payload)
        self.assertIn("catalyst_reserve_capital", payload)

if __name__ == "__main__":
    unittest.main()
