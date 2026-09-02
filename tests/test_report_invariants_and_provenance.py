"""
Unit Tests for Report Invariants & Data Provenance
Verifies that ReportInvariantGuard blocks stale tickers, enforces single snapshot consistency,
and validates that cash + invested == NAV.
"""
import unittest
from src.reporting.report_invariants import report_invariant_guard
from src.portfolio.portfolio_snapshot import portfolio_snapshot
from src.reporting.master_pdf_generator import master_pdf_generator


class TestReportInvariantsAndProvenance(unittest.TestCase):
    def setUp(self):
        self.snap = portfolio_snapshot.get_authoritative_snapshot(force_refresh=True)

    def test_report_invariants_clean_challenge_pass(self):
        """Verify authoritative challenge snapshot passes all 8 report invariants."""
        current_holding_syms = {p.get("symbol", "").upper() for p in self.snap["positions"]}
        watchlist = {"CRM", "AZN", "NVDA", "MSFT", "LIN"}
        
        sections_meta = {
            "challenge_start_nav": 50000.00,
            "benchmark_history_start_timestamp": "2026-09-02 00:27:00 UTC",
            "section_snapshot_ids": [self.snap["snapshot_id"]] * 4,
            "section_tickers": {
                "holdings": list(current_holding_syms),
                "watchlist": list(watchlist)
            },
            "attributions": []
        }

        ok, failures, telemetry = report_invariant_guard.validate_report_invariants(
            snapshot=self.snap,
            report_sections=sections_meta,
            explicit_watchlist_tickers=watchlist
        )

        self.assertTrue(ok, f"Report invariants failed: {failures}")
        self.assertEqual(len(failures), 0)
        self.assertEqual(telemetry["checks_passed"], 9)
        self.assertEqual(telemetry["status"], "VERIFIED")

    def test_report_invariants_blocks_stale_tickers(self):
        """Verify stale pre-reset tickers (EXPN, BMY, LLY) are caught and rejected."""
        watchlist = {"CRM", "AZN", "NVDA"}
        contaminated_sections = {
            "challenge_start_nav": 50000.00,
            "benchmark_history_start_timestamp": "2026-09-02 00:27:00 UTC",
            "section_snapshot_ids": [self.snap["snapshot_id"]] * 4,
            "section_tickers": {
                "holdings": ["EXPN", "BMY", "LLY"],  # Contaminated!
                "watchlist": list(watchlist)
            },
            "attributions": []
        }

        ok, failures, telemetry = report_invariant_guard.validate_report_invariants(
            snapshot=self.snap,
            report_sections=contaminated_sections,
            explicit_watchlist_tickers=watchlist
        )

        self.assertFalse(ok)
        self.assertGreater(len(failures), 0)
        self.assertTrue(any("EXPN" in f for f in failures))
        self.assertTrue(any("BMY" in f for f in failures))
        self.assertTrue(any("LLY" in f for f in failures))

    def test_master_pdf_generation_succeeds(self):
        """Verify Master PDF builds cleanly and produces valid PDF file without errors."""
        pdf_path = master_pdf_generator.generate_daily_master_pdf("20260902", snapshot=self.snap)
        import os
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 5000)


if __name__ == "__main__":
    unittest.main()
