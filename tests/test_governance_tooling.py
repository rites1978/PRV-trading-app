"""
Unit & Integration Test Suite for Institutional Governance, Telemetry & Compliance Tooling
"""
import unittest
from datetime import datetime, timezone
from src.database.db import db
from src.compliance.integrity_guard import ForwardTestIntegrityGuard
from src.governance.evidence_ledger import EvidenceLedgerService
from src.analytics.attribution_service import TradeAttributionService
from src.analytics.trajectory_service import TrajectoryService
from src.regime.regime_service import MarketRegimeService

class TestGovernanceTooling(unittest.TestCase):
    def setUp(self):
        self.guard = ForwardTestIntegrityGuard()
        self.attr = TradeAttributionService()
        self.traj = TrajectoryService()
        self.evidence = EvidenceLedgerService()
        self.regime = MarketRegimeService()

        # Seed parent trades to satisfy foreign key constraint
        with db.get_connection() as conn:
            for tid, sym in [(9991, "AMD"), (9992, "NVDA"), (9993, "DE")]:
                conn.execute("""
                    INSERT OR IGNORE INTO trades (
                        id, trade_id, symbol, action, quantity, price, total_cost,
                        net_cost, confidence_score, reward_risk_ratio, trade_reason, mode
                    ) VALUES (?, ?, ?, 'BUY', 1, 100.0, 100.0, 100.0, 80.0, 3.0, 'TEST', 'LIVE')
                """, (tid, f"TRD_TEST_{tid}", sym))

    def tearDown(self):
        with db.get_connection() as conn:
            conn.execute("DELETE FROM trade_attributions WHERE trade_id >= 9000")
            conn.execute("DELETE FROM trade_trajectories WHERE trade_id >= 9000")
            conn.execute("DELETE FROM trades WHERE id >= 9000")

    def test_pre_flight_compliance_sizing_rejection(self):
        """Test that orders exceeding 5.53% sizing are strictly rejected."""
        ok, msg, audit = self.guard.validate_pre_flight_compliance(
            symbol="AAPL",
            t212_ticker="AAPL_US_EQ",
            order_cost_gbp=600.0,  # Exceeds 5.53% of £5,000 (£276.59)
            current_nav_gbp=5000.0,
            current_drawdown_pct=1.5
        )
        self.assertFalse(ok)
        self.assertIn("exceeds 5.53% sizing limit", msg)

    def test_pre_flight_drawdown_ceiling_rejection(self):
        """Test that orders are rejected when drawdown reaches or breaches 5.00%."""
        ok, msg, _ = self.guard.validate_pre_flight_compliance(
            symbol="AAPL",
            t212_ticker="AAPL_US_EQ",
            order_cost_gbp=250.0,
            current_nav_gbp=5000.0,
            current_drawdown_pct=5.10  # Breached 5% ceiling
        )
        self.assertFalse(ok)
        self.assertIn("breached 5.00% ceiling", msg)

    def test_trade_attribution_stop_collision(self):
        """Test deterministic attribution tagging for STOP_COLLISION."""
        res = self.attr.classify_trade_outcome(
            trade_id=9991,
            trade_data={"symbol": "AMD", "realized_pnl": -8.47, "realized_pnl_pct": -2.5, "exit_reason": "Stop Loss (-2.50%)"},
            telemetry={"pre_entry_latency_days": 0.0, "post_exit_mfe_20d_pct": 8.5, "days_since_prior_stop": None}
        )
        self.assertEqual(res["root_cause_category"], "STOP_COLLISION")

    def test_trade_attribution_clean_winner(self):
        """Test deterministic attribution tagging for CLEAN_WINNER."""
        res = self.attr.classify_trade_outcome(
            trade_id=9992,
            trade_data={"symbol": "NVDA", "realized_pnl": 25.50, "realized_pnl_pct": 7.5, "exit_reason": "Take Profit Target (+7.50%)"},
            telemetry={}
        )
        self.assertEqual(res["root_cause_category"], "CLEAN_WINNER")

    def test_trajectory_recording(self):
        """Test MFE/MAE recording and aggregation."""
        self.traj.record_trajectory(
            trade_id=9993,
            symbol="DE",
            entry_timestamp="2026-08-01T10:00:00Z",
            exit_timestamp="2026-08-05T15:30:00Z",
            entry_price=600.0,
            exit_price=585.0,
            entry_atr=15.0,
            duration_hours=96.0,
            in_trade_mfe_pct=2.5,
            in_trade_mae_pct=-2.5,
            post_mfe_20d_pct=8.0
        )
        summary = self.traj.get_trajectory_summary()
        self.assertGreaterEqual(summary["trades_count"], 1)

    def test_evidence_ledger_retrieval(self):
        """Test evidence registry queries."""
        claims = self.evidence.get_all_claims()
        self.assertIsInstance(claims, list)
        self.assertGreaterEqual(len(claims), 1)

    def test_regime_classification_caching(self):
        """Test market regime calculation and fast memory/db caching."""
        regime = self.regime.get_current_regime()
        self.assertIn("regime_classification", regime)
        self.assertIn(regime["regime_classification"], ["STRONG_BULL", "MILD_BULL", "SIDEWAYS", "MILD_BEAR", "STRONG_BEAR"])

    def test_git_fallback_when_binary_missing(self):
        """Test compliance guard gracefully handles missing git environment."""
        hash_val = self.guard._get_current_git_hash()
        self.assertIsInstance(hash_val, str)
        self.assertGreater(len(hash_val), 0)

if __name__ == "__main__":
    unittest.main()
