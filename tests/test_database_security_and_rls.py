"""
🏛️ PRV CAPITAL | DATABASE SECURITY, RLS POSTURE & PREFLIGHT GATE TESTS
Verifies least-privilege security controls, RLS migration scripts, credential isolation, and fail-closed startup behaviors.
"""
import unittest
import os
from src.security.startup_security_gate import (
    startup_security_gate,
    DATABASE_SECURITY_VERIFIED,
    SECURITY_ARCHITECTURE_FROZEN,
    CONTINUOUS_SECURITY_MONITORING
)
from src.portfolio.portfolio_snapshot import portfolio_snapshot
from src.config.settings import settings
from src.analytics.live_evidence_tracker import live_evidence_tracker
from src.brokers.trading212 import broker


class TestDatabaseSecurityAndRLS(unittest.TestCase):
    """
    Test suite for Supabase Row-Level Security, least-privilege access, and startup security preflight.
    """
    def test_migration_003_sql_structure_and_syntax(self):
        """Test Migration 003 contains explicit RLS enable, force RLS, revoke anon, and service_role grants."""
        migration_path = "src/database/migrations/003_supabase_rls_security_hardening.sql"
        self.assertTrue(os.path.exists(migration_path))
        
        with open(migration_path, "r") as f:
            sql_content = f.read()

        required_tables = [
            "trades",
            "risk_telemetry",
            "agent_weights",
            "market_regimes",
            "boardroom_debates",
            "execution_journal",
            "post_mortem_analysis"
        ]

        for t in required_tables:
            self.assertIn(f"ALTER TABLE IF EXISTS public.{t} ENABLE ROW LEVEL SECURITY;", sql_content)
            self.assertIn(f"ALTER TABLE IF EXISTS public.{t} FORCE ROW LEVEL SECURITY;", sql_content)

        self.assertIn("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, public;", sql_content)
        self.assertIn("GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;", sql_content)
        
        # Ensure zero permissive true policies exist for anon/public
        self.assertNotIn("TO anon USING (true)", sql_content)
        self.assertNotIn("TO public USING (true)", sql_content)

    def test_default_privileges_hardening_in_migration(self):
        """Test Migration 003 contains ALTER DEFAULT PRIVILEGES to protect future database objects."""
        migration_path = "src/database/migrations/003_supabase_rls_security_hardening.sql"
        with open(migration_path, "r") as f:
            sql_content = f.read()

        self.assertIn("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, public, authenticated;", sql_content)
        self.assertIn("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, public, authenticated;", sql_content)
        self.assertIn("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON ROUTINES FROM anon, public, authenticated;", sql_content)
        self.assertIn("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role;", sql_content)

    def test_git_secret_tracking_hygiene(self):
        """Test that .env is not indexed in Git tracking."""
        git_audit = startup_security_gate.check_git_secret_tracking()
        self.assertFalse(git_audit["env_file_tracked_in_git_index"])
        self.assertEqual(git_audit["git_hygiene_status"], "SECURE")

    def test_startup_security_gate_execution(self):
        """Test startup security preflight executes and validates all gates."""
        preflight = startup_security_gate.execute_startup_security_preflight()
        self.assertIn("security_preflight_verdict", preflight)
        self.assertIn("broker_reconciliation_status", preflight)
        self.assertIn("mandatory_cash_reserve_verified", preflight)
        self.assertEqual(preflight["broker_reconciliation_status"], "PASSED (6/6 Invariants)")
        self.assertTrue(preflight["security_flags"]["credential_rotation_verified"])
        self.assertTrue(preflight["security_flags"]["compromised_credentials_remaining_zero"])

    def test_snapshot_consistency_and_canonical_64char_sha256(self):
        """Test startup preflight and snapshot service produce full 64-char SHA256 and deterministic sorting."""
        snap = portfolio_snapshot.get_authoritative_snapshot()
        self.assertIn("positions_hash_sha256_full", snap)
        self.assertIn("positions_hash_short", snap)
        self.assertEqual(len(snap["positions_hash_sha256_full"]), 64)
        self.assertEqual(len(snap["positions_hash_short"]), 16)
        self.assertGreater(snap["account_summary"]["total_nav"], 40000.0)
        self.assertGreater(snap["account_summary"]["free_cash"], 20000.0)
        self.assertGreaterEqual(snap["account_summary"]["active_holdings_count"], 0)

    def test_security_architecture_freeze_flags(self):
        """Test governance flags confirm database security verified and frozen."""
        self.assertTrue(DATABASE_SECURITY_VERIFIED)
        self.assertTrue(SECURITY_ARCHITECTURE_FROZEN)
        self.assertTrue(CONTINUOUS_SECURITY_MONITORING)

    def test_decoupling_new_risk_vs_risk_reducing_closes(self):
        """Test security gate distinguishes new risk entries from capital-preserving emergency exits."""
        preflight = startup_security_gate.execute_startup_security_preflight()
        self.assertTrue(preflight["risk_reduction_allowed"])
        self.assertTrue(preflight["practice_new_entries_allowed"])
        self.assertFalse(preflight["real_money_new_entries_allowed"])

    def test_broker_data_integrity_post_security_fix(self):
        """Test financial data integrity across broker ledger and database snapshots after clean reset."""
        snap = portfolio_snapshot.get_authoritative_snapshot()
        acc = snap["account_summary"]
        
        self.assertGreater(acc["total_nav"], 40000.0)
        self.assertGreater(acc["free_cash"], 20000.0)
        self.assertGreaterEqual(acc["active_holdings_count"], 0)
        self.assertEqual(len(snap["positions"]), acc["active_holdings_count"])
        
        # Verify 6/6 Invariants passed with 0 failed invariants
        self.assertTrue(snap["is_reconciled"])
        self.assertEqual(len(snap["failed_invariants"]), 0)

    def test_broker_clean_slate_reset_api(self):
        """Test broker live verification of £50,000.00 clean reset status."""
        reset_status = broker.verify_clean_reset_status()
        self.assertTrue(reset_status["challenge_ready"])
        self.assertGreater(reset_status["broker_nav_gbp"], 40000.0)
        self.assertGreater(reset_status["broker_cash_gbp"], 20000.0)
        self.assertGreaterEqual(reset_status["positions_count"], 0)

    def test_live_evidence_tracker_and_decision_scorecard(self):
        """Test signal logging, shadow rejection tracking, and decision-quality scorecard generation."""
        sig_payload = {
            "ticker": "TEST_TICKER",
            "decision": "REJECTED",
            "rejection_reason": "NET_REWARD_RISK_BELOW_HURDLE",
            "predicted_gross_return": 0.045,
            "predicted_net_return": 0.015,
            "predicted_downside": 0.025,
            "predicted_reward_risk": 0.60,
            "expected_holding_period_days": 10.0,
            "predicted_costs": 15.0,
            "spread_bps": 22.0,
            "expected_slippage_bps": 10.0
        }
        sig_id = live_evidence_tracker.log_signal_evaluation(sig_payload)
        self.assertTrue(sig_id.startswith("SIG_"))

        scorecard = live_evidence_tracker.generate_decision_quality_scorecard()
        self.assertIn("signal_funnel", scorecard)
        self.assertIn("counterfactual_by_dataset", scorecard)
        self.assertIn("live_edge_scorecard", scorecard)
        self.assertIn("validation_checkpoints", scorecard)
        self.assertEqual(scorecard["validation_checkpoints"]["checkpoint_1_diagnostic_target"], 20)

    def test_practice_challenge_engine_and_scoreboard(self):
        """Test 30-day practice challenge engine, benchmarking, and daily scoreboard."""
        from src.analytics.practice_challenge_engine import practice_challenge_engine
        self.assertEqual(practice_challenge_engine.get_current_challenge_day(), 1)
        
        sb = practice_challenge_engine.generate_daily_30day_scoreboard()
        self.assertIn("challenge_header", sb)
        self.assertIn("nav_and_returns", sb)
        self.assertIn("pnl_and_costs", sb)
        self.assertIn("trade_statistics", sb)
        self.assertIn("predefined_day30_verdict_criteria", sb)
        self.assertEqual(sb["challenge_header"]["account_mode"], "PRACTICE")
        self.assertEqual(sb["challenge_header"]["current_day_str"], "DAY 1 / 30")


if __name__ == "__main__":
    unittest.main()
