import unittest
import os
import sqlite3
from src.database.db import Database, CREATE_TABLES_SQL
from src.portfolio.capital_manager import CapitalManager
from src.risk.risk_engine import RiskEngine
from src.execution.cost_model import SpreadAwareCostModel
from src.agents.boardroom import BoardroomDeliberation

class TestPRVQuantPlatform(unittest.TestCase):

    def setUp(self):
        # Isolated test database
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
            os.remove(self.test_db_path)

    def test_capital_manager_three_tier_and_vault(self):
        """Test Core Capital, Active Capital, and Profit Vault isolation."""
        # Initial state before any vault deposits
        state = self.capital_mgr.get_capital_state(total_broker_nav=50000.0, total_invested=3260.0, available_cash=46740.0)
        self.assertEqual(state["total_broker_nav"], 50000.0)
        self.assertEqual(state["active_capital"], 3260.0)
        
        # Test profit vault deposit
        self.test_db.deposit_profit_vault("TEST_1", "BARC", 500.0, "Test profit")
        vault_bal = self.test_db.get_vault_balance()
        self.assertEqual(vault_bal, 500.0)

    def test_dynamic_regime_deployment(self):
        """Test 20% (Neutral), 50% (Strong), 80% (Exceptional) deployment allowances."""
        regime_n, target_n = self.capital_mgr.determine_market_regime(40.0, 40.0)
        self.assertEqual(regime_n, "NEUTRAL")
        self.assertEqual(target_n, 0.20)
        
        regime_s, target_s = self.capital_mgr.determine_market_regime(60.0, 60.0)
        self.assertEqual(regime_s, "STRONG")
        self.assertEqual(target_s, 0.50)
        
        regime_e, target_e = self.capital_mgr.determine_market_regime(85.0, 85.0)
        self.assertEqual(regime_e, "EXCEPTIONAL")
        self.assertEqual(target_e, 0.80)

    def test_cost_model_friction_and_rr(self):
        """Test spread-aware cost calculation and 3:1 Reward/Risk enforcement."""
        # Valid trade: 2.5% risk, 7.5% reward -> Gross R:R = 3.0
        entry = 100.0
        stop = 97.5
        target = 107.5
        approved, res = self.cost_mdl.evaluate_net_edge(entry, target, stop, 2000.0, False, True)
        self.assertTrue(approved)
        self.assertGreaterEqual(res["gross_reward_risk"], 2.95)
        self.assertGreaterEqual(res["net_reward_risk"], 2.4)

        # Sub-standard R:R trade (e.g. 1:1) should be strictly rejected
        approved_bad, res_bad = self.cost_mdl.evaluate_net_edge(100.0, 102.0, 98.0, 2000.0, False, True)
        self.assertFalse(approved_bad)

    def test_risk_circuit_breaker(self):
        """Test 5% hard daily drawdown circuit breaker."""
        self.risk_eng.initialize_day(50000.0)
        
        # 2% drawdown -> Safe
        safe, msg = self.risk_eng.check_circuit_breaker(49000.0)
        self.assertTrue(safe)
        
        # 6% drawdown -> Circuit breaker trips
        tripped_safe, tripped_msg = self.risk_eng.check_circuit_breaker(47000.0)
        self.assertFalse(tripped_safe)
        self.assertTrue(self.risk_eng.circuit_breaker_tripped)

    def test_boardroom_quorum_rejection_low_confidence(self):
        """Test that boardroom rejects any trade with Confidence < 80."""
        factors = {
            "trend_strength": 50.0, "relative_strength": 50.0, "momentum": 50.0,
            "volume_confirmation": 50.0, "volatility_condition": 50.0, "market_regime": 50.0,
            "portfolio_exposure": 50.0, "trading_cost_impact": 50.0
        }
        approved, data = self.boardroom_delib.convene_boardroom("TEST", factors, 65.0, "NEUTRAL", True, True)
        self.assertFalse(approved)
        self.assertFalse(data["approved"])

if __name__ == "__main__":
    unittest.main()
