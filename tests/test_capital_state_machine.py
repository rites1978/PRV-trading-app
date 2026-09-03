import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.config.settings import settings
from src.database.db import db
from src.portfolio.capital_state_machine import CapitalStateMachine, CapitalState
from src.portfolio.capital_manager import CapitalManager
from src.portfolio.daily_objective_service import DailyObjectiveService
from src.execution.order_router import OrderRouter
from src.risk.market_stress_detector import market_stress_detector


class TestCapitalStateMachineMandate(unittest.TestCase):
    """
    Deterministic institutional test suite for:
    PRV CAPITAL — CAPITAL PRESERVATION, DAILY BANKING & LOSS-RECOVERY STATE MACHINE
    """
    def setUp(self):
        self.csm = CapitalStateMachine()
        # Reset testing session
        self.csm._topup_declined_sessions.clear()
        market_stress_detector.set_mock_stress(False, "")

    # 1. £50,000 -> £50,300 -> £300 banked
    def test_normal_mode_banking_excess_above_50k(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "deposit_profit_vault", return_value=300.0) as mock_deposit:
            
            res = self.csm.process_trade_close(
                trade_id="TRD_NORM_01",
                symbol="LLOY.L",
                net_realized_pnl=300.0,
                current_active_equity=50000.0
            )

            self.assertEqual(res["banked_amount_gbp"], 300.0)
            self.assertEqual(res["active_trading_equity_gbp"], 50000.0)
            mock_deposit.assert_called_once()
            self.assertEqual(mock_deposit.call_args[1]["realized_profit"], 300.0)

    # 2. £50,000 -> £49,500 -> recovery mode
    def test_loss_triggers_recovery_mode(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_net_strategy_profit", return_value=-500.0), \
             patch.object(db, "record_state_transition") as mock_trans:

            eval_res = self.csm.evaluate_capital_state(
                current_broker_nav=49500.0,
                daily_realized_pnl=-200.0,
                daily_unrealized_pnl=0.0
            )

            self.assertTrue(eval_res["in_recovery_mode"])
            self.assertEqual(eval_res["base_capital_deficit_gbp"], 500.0)
            self.assertEqual(eval_res["active_trading_equity_gbp"], 49500.0)
            self.assertEqual(eval_res["current_state"], CapitalState.RECOVERY.value)

    # 3. £49,500 -> £49,800 -> zero banked
    def test_recovery_mode_zero_banking(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "deposit_profit_vault") as mock_deposit:

            res = self.csm.process_trade_close(
                trade_id="TRD_REC_01",
                symbol="AZN.L",
                net_realized_pnl=300.0,
                current_active_equity=49500.0
            )

            # In recovery, profits stay inside active capital; ZERO is banked
            self.assertEqual(res["banked_amount_gbp"], 0.0)
            self.assertEqual(res["active_trading_equity_gbp"], 49800.0)
            self.assertTrue(res["is_in_deficit"])
            mock_deposit.assert_not_called()

    # 4. £49,800 -> £50,150 -> £150 banked
    def test_recovery_restores_50k_and_banks_excess_only(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "deposit_profit_vault", return_value=150.0) as mock_deposit:

            res = self.csm.process_trade_close(
                trade_id="TRD_REC_02",
                symbol="BP.L",
                net_realized_pnl=350.0,
                current_active_equity=49800.0
            )

            # £49,800 + £350 = £50,150
            # £50,000 restored as operating base; exactly £150 excess banked
            self.assertEqual(res["active_trading_equity_gbp"], 50000.0)
            self.assertEqual(res["banked_amount_gbp"], 150.0)
            self.assertFalse(res["is_in_deficit"])
            mock_deposit.assert_called_once()
            self.assertEqual(mock_deposit.call_args[1]["realized_profit"], 150.0)

    # 5. Bank reserve exists + deficit -> permission requested
    def test_bank_reserve_exists_plus_deficit_requests_permission(self):
        with patch.object(db, "get_vault_balance", return_value=4250.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_net_strategy_profit", return_value=3150.0):

            # Broker NAV = 48900 unvaulted + 4250 vault = 53150 total NAV
            eval_res = self.csm.evaluate_capital_state(
                current_broker_nav=53150.0,
                daily_realized_pnl=0.0,
                daily_unrealized_pnl=0.0
            )

            self.assertEqual(eval_res["active_trading_equity_gbp"], 48900.0)
            self.assertEqual(eval_res["base_capital_deficit_gbp"], 1100.0)
            self.assertEqual(eval_res["banked_profit_reserve_gbp"], 4250.0)
            self.assertTrue(eval_res["topup_permission_required"])
            self.assertEqual(eval_res["proposed_topup_amount_gbp"], 1100.0)
            self.assertEqual(eval_res["current_state"], CapitalState.USER_TOPUP_PENDING.value)

    # 6. Top-up approved -> active equity restored
    def test_topup_approved_restores_active_equity(self):
        with patch.object(self.csm, "get_current_active_state", return_value={
                "active_trading_equity_gbp": 48900.0,
                "base_capital_deficit_gbp": 1100.0,
                "banked_profit_reserve_gbp": 4250.0
             }), \
             patch.object(db, "get_vault_balance", return_value=4250.0), \
             patch.object(db, "withdraw_profit_vault", return_value=3150.0) as mock_withdraw, \
             patch.object(db, "record_capital_transfer") as mock_xfer, \
             patch.object(db, "record_state_transition"):

            res = self.csm.approve_topup(user_name="PORTFOLIO_MANAGER")

            self.assertTrue(res["success"])
            self.assertEqual(res["amount_gbp"], 1100.0)
            self.assertEqual(res["active_equity_after_gbp"], 50000.0)
            self.assertEqual(res["banked_reserve_after_gbp"], 3150.0)
            self.assertEqual(res["new_state"], CapitalState.NORMAL.value)
            self.assertFalse(res["is_trading_pnl"])
            mock_withdraw.assert_called_once_with(amount=1100.0, notes=unittest.mock.ANY)
            mock_xfer.assert_called_once()

    # 7. Top-up declined -> recovery continues
    def test_topup_declined_continues_recovery(self):
        with patch.object(self.csm, "get_current_active_state", return_value={
                "active_trading_equity_gbp": 48900.0,
                "base_capital_deficit_gbp": 1100.0,
                "banked_profit_reserve_gbp": 4250.0
             }), \
             patch.object(db, "record_state_transition"):

            res = self.csm.decline_topup(user_name="PORTFOLIO_MANAGER")

            self.assertTrue(res["success"])
            self.assertEqual(res["new_state"], CapitalState.RECOVERY.value)
            self.assertEqual(res["active_trading_equity_gbp"], 48900.0)
            self.assertEqual(res["base_capital_deficit_gbp"], 1100.0)

    # 8. Top-up never counted as P&L
    def test_topup_never_counted_as_pnl(self):
        with patch.object(db, "get_net_strategy_profit", return_value=125.50), \
             patch.object(db, "get_total_capital_transfers", return_value=1100.0), \
             patch.object(db, "get_vault_balance", return_value=3150.0):

            eval_res = self.csm.evaluate_capital_state(
                current_broker_nav=53150.0,
                daily_realized_pnl=0.0,
                daily_unrealized_pnl=0.0
            )

            # Assert net strategy profit reflects only true trading P&L (£125.50), NOT capital transfers (£1,100)
            self.assertEqual(eval_res["net_strategy_profit_gbp"], 125.50)
            self.assertEqual(eval_res["total_capital_transfers_gbp"], 1100.0)

    # 9. £250 daily target achieved -> new entries disabled
    def test_daily_target_achieved_disables_new_entries(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_net_strategy_profit", return_value=280.0):

            eval_res = self.csm.evaluate_capital_state(
                current_broker_nav=50280.0,
                daily_realized_pnl=280.0,
                daily_unrealized_pnl=10.0
            )

            self.assertTrue(eval_res["daily_target_achieved"])
            self.assertEqual(eval_res["current_state"], CapitalState.TARGET_ACHIEVED.value)
            self.assertFalse(eval_res["new_discretionary_entries_allowed"])
            self.assertEqual(eval_res["sizing_multiplier"], 0.0)

    # 10. Target not achieved -> no forced trading
    def test_target_not_achieved_no_forced_trading(self):
        self.assertFalse(settings.FORCE_TRADE_TO_REACH_DAILY_TARGET)
        eval_res = self.csm.evaluate_capital_state(
            current_broker_nav=50050.0,
            daily_realized_pnl=50.0,
            daily_unrealized_pnl=0.0
        )
        self.assertFalse(eval_res["daily_target_achieved"])
        self.assertTrue(eval_res["new_discretionary_entries_allowed"])
        self.assertFalse(eval_res["anti_gambling_safeguards"]["force_trade_to_reach_daily_target"])

    # 11. Daily loss lock -> new entries disabled (uses realized + unrealized)
    def test_daily_loss_lock_realized_plus_unrealized(self):
        eval_res = self.csm.evaluate_capital_state(
            current_broker_nav=49450.0,
            daily_realized_pnl=-200.0,
            daily_unrealized_pnl=-350.0 # Total net daily = -£550 <= -£500 limit
        )

        self.assertTrue(eval_res["hard_loss_limit_breached"])
        self.assertEqual(eval_res["current_state"], CapitalState.DAILY_LOSS_LOCK.value)
        self.assertFalse(eval_res["new_discretionary_entries_allowed"])
        self.assertEqual(eval_res["sizing_multiplier"], 0.0)

    # 12. Market crash -> risk reduction permitted but new discretionary risk blocked
    def test_market_crash_blocks_discretionary_longs_allows_exits(self):
        market_stress_detector.set_mock_stress(True, "S&P 500 down 2.8% market crash")
        eval_res = self.csm.evaluate_capital_state(
            current_broker_nav=50000.0,
            daily_realized_pnl=0.0,
            daily_unrealized_pnl=0.0,
            market_stress_active=True,
            market_stress_reason="S&P 500 down 2.8% market crash"
        )

        self.assertEqual(eval_res["current_state"], CapitalState.MARKET_STRESS.value)
        self.assertFalse(eval_res["new_discretionary_entries_allowed"])

        # Order Router verification: Entry blocked, Exit permitted
        router = OrderRouter()
        with patch.object(DailyObjectiveService, "get_daily_status", return_value={
            "new_discretionary_entries_allowed": False,
            "gate_reason": "MARKET STRESS: S&P down 2.8%",
            "current_capital_state": "MARKET_STRESS"
        }):
            ok, msg, _ = router.route_entry_order(
                symbol="AAPL",
                t212_ticker="AAPL_US_EQ",
                quantity=10,
                price=150.0,
                target_price=160.0,
                stop_loss_price=145.0,
                sector="TECHNOLOGY",
                confidence_score=90.0,
                market_regime="BULL",
                agent_votes={"TREND": "BUY", "MOMENTUM": "BUY"},
                risk_approved=True,
                bypass_market_hours=True
            )
            self.assertFalse(ok)
            self.assertIn("HOLD", msg)

        # Risk exit must NOT be blocked
        with patch.object(db, "record_trade"), \
             patch("src.portfolio.daily_objective_service.DailyObjectiveService.process_trade_close"):
            exit_ok, exit_msg, _ = router.route_exit_order(
                symbol="AAPL",
                t212_ticker="AAPL_US_EQ",
                quantity=10,
                current_price=145.0,
                entry_price=150.0,
                exit_reason="STOP_LOSS_TRIGGERED",
                is_paper=True
            )
            self.assertTrue(exit_ok)

    # 13. Recovery mode cannot increase risk/sizing/turnover
    def test_recovery_mode_cannot_increase_risk_sizing_or_turnover(self):
        # Equity is £45,000 (Deficit £5,000)
        eval_res = self.csm.evaluate_capital_state(
            current_broker_nav=45000.0,
            daily_realized_pnl=0.0,
            daily_unrealized_pnl=0.0
        )

        self.assertTrue(eval_res["in_recovery_mode"])
        # Sizing multiplier must be strictly <= 1.0 (scales down with remaining equity: 45000/50000 = 0.90)
        self.assertLessEqual(eval_res["sizing_multiplier"], 1.0)
        self.assertEqual(eval_res["sizing_multiplier"], 0.90)
        self.assertTrue(eval_res["anti_gambling_safeguards"]["martingale_prohibited"])
        self.assertTrue(eval_res["anti_gambling_safeguards"]["averaging_down_prohibited"])


if __name__ == "__main__":
    unittest.main()
