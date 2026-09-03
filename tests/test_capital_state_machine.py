"""
🏛️ PRV CAPITAL | CAPITAL PRESERVATION & LOSS-RECOVERY STATE MACHINE TEST SUITE
Deterministic verification of:
1. 3-Ledger Architecture (Active Equity, Banked Reserve, Capital Transfers)
2. 3 Independent State Dimensions (Capital State, Daily State, Market State)
3. Corridor Risk Policy (+£250 Target Lock, -£250 Entry Loss Lock, -£500 Emergency Lock)
4. Bankable Net Profit Invariant (Zero banking with open losses)
5. Delta MTM P&L Accounting (Start-of-day snapshot deltas)
6. Correct Partial Top-Up Logic (Never falsely restores NORMAL)
7. Composable Non-Mutually-Exclusive States (RECOVERY + STRESS + LOSS_LOCK)
8. Anti-Martingale / Anti-Gambling Invariants
"""
import unittest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.config.settings import settings
from src.database.db import db
from src.portfolio.capital_state_machine import (
    CapitalStateMachine,
    CapitalState,
    DailyState,
    MarketState
)
from src.portfolio.daily_objective_service import DailyObjectiveService, daily_objective_service
from src.execution.order_router import OrderRouter
from src.risk.market_stress_detector import MarketStressDetector


class TestCapitalStateMachineMandate(unittest.TestCase):
    def setUp(self):
        self.csm = CapitalStateMachine()
        self.csm._topup_declined_sessions.clear()
        self.today_str = self.csm.get_today_str()

    # 1. Normal mode banking excess above £50,000
    def test_normal_mode_banking_excess_above_50k(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 50000.0, "start_unrealized_pnl": 0.0
             }), \
             patch.object(db, "deposit_profit_vault") as mock_deposit:
            
            # Start £50,000, trade realizes £300, NAV is £50,300
            res = self.csm.evaluate_portfolio_states(
                current_broker_nav=50300.0,
                current_unrealized_pnl=0.0,
                daily_realized_pnl=300.0
            )

            self.assertEqual(res["capital_state"], CapitalState.NORMAL.value)
            self.assertEqual(res["daily_state"], DailyState.TARGET_LOCK.value)
            self.assertEqual(res["bankable_profit_today_gbp"], 300.0)
            self.assertFalse(res["new_discretionary_entries_allowed"])

            # Close trade sweeps £300 to vault
            close_res = self.csm.process_trade_close(
                trade_id="TR_TEST_1",
                symbol="BARC.L",
                net_realized_pnl=300.0,
                current_active_equity=50000.0
            )
            self.assertEqual(close_res["banked_amount_gbp"], 300.0)
            self.assertEqual(close_res["active_trading_equity_gbp"], 50000.0)
            mock_deposit.assert_called_once()

    # 2. Deficit triggers RECOVERY mode
    def test_loss_triggers_recovery_mode(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 50000.0, "start_unrealized_pnl": 0.0
             }):

            eval_res = self.csm.evaluate_portfolio_states(
                current_broker_nav=49500.0,
                current_unrealized_pnl=0.0,
                daily_realized_pnl=-200.0
            )

            self.assertTrue(eval_res["in_recovery_mode"])
            self.assertEqual(eval_res["base_capital_deficit_gbp"], 500.0)
            self.assertEqual(eval_res["active_trading_equity_gbp"], 49500.0)
            self.assertEqual(eval_res["capital_state"], CapitalState.RECOVERY.value)
            self.assertEqual(eval_res["daily_state"], DailyState.ACTIVE.value)

    # 3. Bankable profit with open loss (Crucial mandate rule!)
    def test_bankable_profit_with_open_loss(self):
        """
        Realized +£300, open positions -£400, total active equity £49,900.
        BANKABLE = £0.00! RECOVERY = TRUE! ZERO PROFIT BANKED!
        """
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 50000.0, "start_unrealized_pnl": 0.0
             }):

            res = self.csm.evaluate_portfolio_states(
                current_broker_nav=49900.0,
                current_unrealized_pnl=-400.0,
                daily_realized_pnl=300.0
            )

            self.assertEqual(res["bankable_profit_today_gbp"], 0.0)
            self.assertEqual(res["capital_state"], CapitalState.RECOVERY.value)
            self.assertTrue(res["in_recovery_mode"])
            self.assertFalse(res["daily_target_achieved"])

    # 4. Recovery mode restores £50,000 base and banks excess only
    def test_recovery_restores_50k_and_banks_excess_only(self):
        with patch.object(db, "deposit_profit_vault") as mock_deposit, \
             patch.object(db, "get_vault_balance", return_value=150.0):
            
            # Active equity starts at £49,800 (deficit £200). Closed trade is +£350.
            close_res = self.csm.process_trade_close(
                trade_id="TR_TEST_REC",
                symbol="LLOY.L",
                net_realized_pnl=350.0,
                current_active_equity=49800.0
            )
            # Exactly £50,000 restored, only £150 excess banked
            self.assertEqual(close_res["active_trading_equity_gbp"], 50000.0)
            self.assertEqual(close_res["banked_amount_gbp"], 150.0)
            mock_deposit.assert_called_once()

    # 5. -£250 Daily MTM Loss Lock stops entries completely (No halving, no trading)
    def test_daily_loss_lock_stops_entries_completely(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 50000.0, "start_unrealized_pnl": 0.0
             }):

            res = self.csm.evaluate_portfolio_states(
                current_broker_nav=49750.0,
                current_unrealized_pnl=0.0,
                daily_realized_pnl=-250.0
            )

            self.assertEqual(res["daily_state"], DailyState.LOSS_LOCK.value)
            self.assertFalse(res["new_discretionary_entries_allowed"])
            self.assertEqual(res["sizing_multiplier"], 0.0)

    # 6. -£500 Emergency Loss Level cancels unfilled orders & allows exits only
    def test_daily_emergency_loss_level(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 50000.0, "start_unrealized_pnl": 0.0
             }):

            res = self.csm.evaluate_portfolio_states(
                current_broker_nav=49400.0,
                current_unrealized_pnl=-100.0,
                daily_realized_pnl=-400.0 # Total daily MTM = -500.0
            )

            self.assertEqual(res["daily_state"], DailyState.EMERGENCY_LOCK.value)
            self.assertTrue(res["emergency_risk_mode"])
            self.assertTrue(res["cancel_unfilled_entry_orders"])
            self.assertFalse(res["new_discretionary_entries_allowed"])

    # 7. Partial top-up logic: Keeps RECOVERY mode!
    def test_partial_topup_keeps_recovery_mode(self):
        # Deficit £3,000, Bank reserve £1,000
        with patch.object(self.csm, "get_current_active_state", return_value={
            "active_trading_equity_gbp": 47000.0,
            "base_capital_deficit_gbp": 3000.0,
            "banked_profit_reserve_gbp": 1000.0
        }), \
        patch.object(db, "get_vault_balance", return_value=1000.0), \
        patch.object(db, "withdraw_profit_vault", return_value=0.0), \
        patch.object(db, "record_capital_transfer"), \
        patch.object(db, "record_state_transition"):

            res = self.csm.approve_topup(user_name="PORTFOLIO_MANAGER")
            self.assertTrue(res["success"])
            self.assertEqual(res["amount_gbp"], 1000.0)
            self.assertEqual(res["active_equity_after_gbp"], 48000.0)
            self.assertEqual(res["base_deficit_remaining_gbp"], 2000.0)
            # CRITICAL MANDATE TEST: Must remain RECOVERY! Never falsely NORMAL!
            self.assertEqual(res["capital_state"], CapitalState.RECOVERY.value)

    # 8. Full top-up restores NORMAL mode
    def test_full_topup_restores_normal_mode(self):
        with patch.object(self.csm, "get_current_active_state", return_value={
            "active_trading_equity_gbp": 48000.0,
            "base_capital_deficit_gbp": 2000.0,
            "banked_profit_reserve_gbp": 2500.0
        }), \
        patch.object(db, "get_vault_balance", return_value=2500.0), \
        patch.object(db, "withdraw_profit_vault", return_value=500.0), \
        patch.object(db, "record_capital_transfer"), \
        patch.object(db, "record_state_transition"):

            res = self.csm.approve_topup(user_name="PORTFOLIO_MANAGER")
            self.assertTrue(res["success"])
            self.assertEqual(res["amount_gbp"], 2000.0)
            self.assertEqual(res["active_equity_after_gbp"], 50000.0)
            self.assertEqual(res["base_deficit_remaining_gbp"], 0.0)
            self.assertEqual(res["capital_state"], CapitalState.NORMAL.value)

    # 9. Composable non-mutually-exclusive states (RECOVERY + MARKET_STRESS + LOSS_LOCK)
    def test_composable_states_and_normalization_safety(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 48000.0, "start_unrealized_pnl": 0.0
             }):

            # Portfolio has deficit (£48k), market is in stress, daily loss lock hit (-£260)
            res = self.csm.evaluate_portfolio_states(
                current_broker_nav=47740.0,
                current_unrealized_pnl=0.0,
                daily_realized_pnl=-260.0,
                market_stress_active=True,
                market_stress_reason="S&P down 2.5%"
            )

            self.assertEqual(res["capital_state"], CapitalState.RECOVERY.value)
            self.assertEqual(res["daily_state"], DailyState.LOSS_LOCK.value)
            self.assertEqual(res["market_state"], MarketState.STRESS.value)
            self.assertFalse(res["new_discretionary_entries_allowed"])

            # Market stress clears -> Market State becomes NORMAL, but RECOVERY and LOSS_LOCK remain!
            res_norm = self.csm.evaluate_portfolio_states(
                current_broker_nav=47740.0,
                current_unrealized_pnl=0.0,
                daily_realized_pnl=-260.0,
                market_stress_active=False
            )
            self.assertEqual(res_norm["capital_state"], CapitalState.RECOVERY.value)
            self.assertEqual(res_norm["daily_state"], DailyState.LOSS_LOCK.value)
            self.assertEqual(res_norm["market_state"], MarketState.NORMAL.value)
            self.assertFalse(res_norm["new_discretionary_entries_allowed"])

    # 10. Delta MTM P&L Accounting using SOD snapshot
    def test_delta_mtm_pnl_accounting_using_sod_snapshot(self):
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 50000.0,
                 "start_unrealized_pnl": 400.0 # Started day with +£400 unrealized
             }):

            # Current unrealized is +£300 (intraday drop of -£100)
            # Realized net today is -£160
            # Delta unrealized = 300 - 400 = -£100
            # Daily MTM = -160 + (-100) = -£260
            res = self.csm.evaluate_portfolio_states(
                current_broker_nav=49740.0,
                current_unrealized_pnl=300.0,
                daily_realized_pnl=-160.0
            )

            self.assertEqual(res["change_in_unrealized_today_gbp"], -100.0)
            self.assertEqual(res["daily_mtm_pnl_gbp"], -260.0)
            # Successfully trips the -£250 loss lock!
            self.assertEqual(res["daily_state"], DailyState.LOSS_LOCK.value)
            self.assertFalse(res["new_discretionary_entries_allowed"])

    # 11. Top-up timing: No transient intraday noise
    def test_topup_timing_intraday_vs_sod_eod(self):
        with patch.object(db, "get_vault_balance", return_value=2000.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 50000.0, "start_unrealized_pnl": 0.0
             }):

            # Intraday fluctuation (is_sod_or_eod_check=False)
            res_intra = self.csm.evaluate_portfolio_states(
                current_broker_nav=49985.0, # -£15 deficit
                current_unrealized_pnl=-15.0,
                daily_realized_pnl=0.0,
                is_sod_or_eod_check=False
            )
            self.assertFalse(res_intra["topup_permission_required"])

            # Pre-session / EOD check (is_sod_or_eod_check=True)
            res_eod = self.csm.evaluate_portfolio_states(
                current_broker_nav=49000.0,
                current_unrealized_pnl=0.0,
                daily_realized_pnl=-1000.0,
                is_sod_or_eod_check=True
            )
            self.assertTrue(res_eod["topup_permission_required"])
            self.assertEqual(res_eod["capital_state"], CapitalState.USER_TOPUP_PENDING.value)

    # 12. Top-up never counted as trading P&L
    def test_topup_never_counted_as_pnl(self):
        with patch.object(self.csm, "get_current_active_state", return_value={
            "active_trading_equity_gbp": 48900.0,
            "base_capital_deficit_gbp": 1100.0,
            "banked_profit_reserve_gbp": 4250.0
        }), \
        patch.object(db, "get_vault_balance", return_value=4250.0), \
        patch.object(db, "withdraw_profit_vault", return_value=3150.0), \
        patch.object(db, "record_capital_transfer") as mock_record, \
        patch.object(db, "record_state_transition"):

            res = self.csm.approve_topup(user_name="PORTFOLIO_MANAGER")
            self.assertTrue(res["success"])
            self.assertFalse(res["is_trading_pnl"])
            mock_record.assert_called_once()

            # db.get_net_strategy_profit() strictly queries trades table
            strat_pnl = db.get_net_strategy_profit()
            self.assertIsInstance(strat_pnl, float)

    # 13. Banked reserve location is RINGFENCED_INSIDE_BROKER
    def test_banked_reserve_location_practice(self):
        self.assertEqual(settings.BANKED_PROFIT_RESERVE_LOCATION, "RINGFENCED_INSIDE_BROKER")
        self.assertEqual(self.csm.reserve_location, "RINGFENCED_INSIDE_BROKER")

    # 14. Recovery mode cannot increase risk or sizing
    def test_recovery_mode_cannot_increase_risk_or_sizing(self):
        # Active equity £45,000 (deficit £5,000)
        with patch.object(db, "get_vault_balance", return_value=0.0), \
             patch.object(db, "get_total_capital_transfers", return_value=0.0), \
             patch.object(db, "get_or_create_sod_snapshot", return_value={
                 "start_active_equity": 45000.0, "start_unrealized_pnl": 0.0
             }):

            res = self.csm.evaluate_portfolio_states(
                current_broker_nav=45000.0,
                current_unrealized_pnl=0.0,
                daily_realized_pnl=0.0
            )

            self.assertEqual(res["capital_state"], CapitalState.RECOVERY.value)
            # Sizing multiplier is strictly 45000 / 50000 = 0.90 (never > 1.0)
            self.assertAlmostEqual(res["sizing_multiplier"], 0.90, places=2)


if __name__ == "__main__":
    unittest.main()
