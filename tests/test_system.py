import unittest
import os
from src.config.settings import settings
from src.database.db import Database
from src.portfolio.capital_manager import CapitalManager
from src.risk.risk_engine import RiskEngine
from src.execution.cost_model import SpreadAwareCostModel
from src.agents.boardroom import BoardroomDeliberation

class TestPRVQuantPlatform(unittest.TestCase):

    def setUp(self):
        self.test_db_path = "test_prv.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.test_db = Database(self.test_db_path)
        
        self.capital_mgr = CapitalManager(starting_capital=50000.0)
        self.risk_eng = RiskEngine()
        self.cost_mdl = SpreadAwareCostModel()
        self.boardroom_delib = BoardroomDeliberation()

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    def test_capital_manager_three_tier_and_vault(self):
        """Test Core Capital, Active Capital, and Profit Vault isolation."""
        state = self.capital_mgr.get_capital_state(total_broker_nav=50000.0, total_invested=3260.0, available_cash=46740.0)
        self.assertEqual(state["total_broker_nav"], 50000.0)
        self.assertEqual(state["active_capital"], 3260.0)
        
        self.test_db.deposit_profit_vault("TEST_1", "BARC", 500.0, "Test profit")
        vault_bal = self.test_db.get_vault_balance()
        self.assertEqual(vault_bal, 500.0)

    def test_dynamic_regime_deployment(self):
        """Test Bear, Neutral, and Bull deployment allowances."""
        regime_b, target_b = self.capital_mgr.determine_market_regime(30.0, 30.0)
        self.assertEqual(regime_b, "BEAR")
        self.assertEqual(target_b, settings.MAX_DEPLOYMENT_BEAR)

        regime_n, target_n = self.capital_mgr.determine_market_regime(55.0, 55.0)
        self.assertEqual(regime_n, "NEUTRAL")
        self.assertEqual(target_n, settings.MAX_DEPLOYMENT_NEUTRAL)
        
        regime_bull, target_bull = self.capital_mgr.determine_market_regime(80.0, 80.0)
        self.assertEqual(regime_bull, "BULL")
        self.assertEqual(target_bull, settings.MAX_DEPLOYMENT_BULL)

    def test_cost_model_friction_and_rr(self):
        """Test spread-aware cost calculation and 3:1 Reward/Risk enforcement."""
        entry = 100.0
        stop = 97.5
        target = 107.5
        approved, res = self.cost_mdl.evaluate_net_edge(entry, target, stop, 2000.0, False, True)
        self.assertTrue(approved)
        self.assertGreaterEqual(res["gross_reward_risk"], 2.95)
        self.assertGreaterEqual(res["net_reward_risk"], 2.0)

        approved_bad, res_bad = self.cost_mdl.evaluate_net_edge(100.0, 102.0, 98.0, 2000.0, False, True)
        self.assertFalse(approved_bad)

    def test_risk_circuit_breaker(self):
        """Test 5% hard daily drawdown circuit breaker."""
        self.risk_eng.initialize_day(50000.0)
        
        safe, msg = self.risk_eng.check_circuit_breaker(49000.0)
        self.assertTrue(safe)
        
        tripped_safe, tripped_msg = self.risk_eng.check_circuit_breaker(47000.0)
        self.assertFalse(tripped_safe)
        self.assertTrue(self.risk_eng.circuit_breaker_tripped)

    def test_boardroom_quorum_rejection_low_confidence(self):
        """Test that boardroom rejects any trade below technical confidence threshold."""
        factors = {
            "trend_strength": 40.0, "relative_strength": 40.0, "momentum": 40.0,
            "volume_confirmation": 40.0, "volatility_condition": 40.0, "market_regime": 40.0,
            "portfolio_exposure": 40.0, "trading_cost_impact": 40.0
        }
        approved, data = self.boardroom_delib.convene_boardroom("TEST", factors, 50.0, "NEUTRAL", True, True)
        self.assertFalse(approved)
        self.assertFalse(data["approved"])

    def test_market_hours_manager(self):
        """Test market hours timezone checks for UK and US."""
        from src.data.market_hours import market_hours
        status = market_hours.get_market_status()
        self.assertIn("uk_market_open", status)
        self.assertIn("us_market_open", status)
        self.assertIn("session_state", status)

    def test_evidence_recorder_and_monitoring(self):
        """Test permanent evidence recording and phase gate monitoring dashboard."""
        from src.monitoring.evidence_recorder import evidence_recorder
        from src.monitoring.monitoring_service import monitoring_service

        evidence_recorder.record_daily_snapshot({
            "starting_nav": 5000.0, "current_nav": 4956.10, "core_capital": 4956.10,
            "active_capital": 3431.10, "idle_cash": 1525.00, "vault_balance": 24.55,
            "deployment_pct": 69.23, "daily_pnl": -43.90, "daily_pnl_pct": -0.88,
            "drawdown_pct": 1.64, "peak_nav": 5000.0, "open_positions_count": 12,
            "market_regime": "BULL", "profit_factor": 0.11, "win_rate": 7.89,
            "completed_trades_count": 38
        })

        phase_data = monitoring_service.get_phase_gate_dashboard(total_trades=38, rolling_pf=0.11, max_drawdown=1.64)
        self.assertEqual(phase_data["current_trade_count"], 38)
        self.assertEqual(phase_data["trades_remaining_to_gate1"], 12)
        self.assertEqual(phase_data["operational_status"], "YELLOW")
        self.assertFalse(phase_data["scale_eligibility"])

if __name__ == "__main__":
    unittest.main()
