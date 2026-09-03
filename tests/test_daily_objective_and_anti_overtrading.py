"""
🏛️ PRV CAPITAL | DAILY NET PROFIT OBJECTIVE & ANTI-OVERTRADING MANDATE TESTS
Validates:
1. £250 Daily Net Profit Objective accounting (gross P&L minus all transaction costs, taxes, FX, friction).
2. Anti-overtrading invariant: FORCE_TRADE_TO_REACH_DAILY_TARGET = False (Hold Cash when no setup).
3. Cost-First Entry Gate:
   - Reject when expected_net_profit <= 0
   - Reject when cost_to_expected_gross_profit > 30%
   - Reject when net_reward_to_risk < 2.0
   - Preferred cost threshold <= 25%
4. Sell Decision Logic:
   - Discretionary exits: Compare economic benefit of selling now vs sell costs + remaining upside.
   - Risk / stop / thesis-invalidation exits: Override transaction-cost optimization and execute immediately.
5. Daily Profit Lock:
   - When DAILY_NET_REALIZED_PNL >= £250, NEW_DISCRETIONARY_ENTRIES_ALLOWED = False.
   - Ongoing risk management and stop losses continue.
   - Full profit banked (e.g. £300 if profit is £300).
6. Capital Banking Logic:
   - Segregated accounting: ACTIVE_TRADING_BANKROLL and BANKED_PROFIT.
   - Invariant: ACTIVE_TRADING_BANKROLL <= £50,000.
   - Banked profit is NON-DEPLOYABLE.
7. Daily Downside Control:
   - Daily max net loss (£500 / 1.0%) halts new discretionary entries.
8. Institutional 30-Day Challenge 12-Metric Performance Evaluation.
"""
import unittest
from unittest.mock import patch, MagicMock
from src.config.settings import settings
from src.portfolio.daily_objective_service import daily_objective_service
from src.execution.net_edge_gate import net_edge_gate
from src.execution.order_router import order_router
from src.portfolio.capital_manager import capital_manager
from src.database.db import db


class TestDailyObjectiveAndAntiOvertrading(unittest.TestCase):
    """
    Test suite for the PRV Capital Daily Net Profit Objective and Anti-Overtrading Mandate.
    """
    def setUp(self):
        # Reset testing state if needed
        pass

    def test_settings_mandate_constants(self):
        """Test central settings contain exact mandated thresholds."""
        self.assertEqual(settings.BASE_TRADING_CAPITAL, 50000.0)
        self.assertEqual(settings.MAX_DEPLOYABLE_TRADING_CAPITAL, 50000.0)
        self.assertEqual(settings.DAILY_NET_PROFIT_OBJECTIVE, 250.0)
        self.assertEqual(settings.DAILY_NET_RETURN_OBJECTIVE_PCT, 0.50)
        self.assertTrue(settings.BANKED_PROFIT_IS_NON_DEPLOYABLE)
        self.assertFalse(settings.FORCE_TRADE_TO_REACH_DAILY_TARGET)
        self.assertEqual(settings.PREFERRED_COST_TO_EXPECTED_GROSS_PROFIT_PCT, 25.0)
        self.assertEqual(settings.MAX_COST_TO_PROFIT_RATIO_PCT, 30.0)
        self.assertEqual(settings.MIN_NET_REWARD_RISK_RATIO, 2.0)
        self.assertEqual(settings.DAILY_MAX_NET_LOSS_PCT, 1.0)
        self.assertEqual(settings.DAILY_MAX_NET_LOSS_GBP, 500.0)

    def test_parameter_manifest_contains_daily_mandate(self):
        """Test parameter manifest includes frozen daily objective fields."""
        manifest = settings.generate_parameter_manifest()
        self.assertIn("base_trading_capital_gbp", manifest)
        self.assertIn("max_deployable_trading_capital_gbp", manifest)
        self.assertIn("daily_net_profit_objective_gbp", manifest)
        self.assertIn("daily_net_return_objective_pct", manifest)
        self.assertIn("banked_profit_is_non_deployable", manifest)
        self.assertIn("force_trade_to_reach_daily_target", manifest)
        self.assertIn("preferred_cost_to_expected_gross_profit_pct", manifest)
        self.assertIn("daily_max_net_loss_gbp", manifest)
        self.assertEqual(manifest["daily_net_profit_objective_gbp"], 250.0)
        self.assertFalse(manifest["force_trade_to_reach_daily_target"])

    def test_anti_overtrading_never_forces_trades(self):
        """Test system preserves HOLD CASH and never lowers thresholds to force trades."""
        self.assertFalse(settings.FORCE_TRADE_TO_REACH_DAILY_TARGET)
        status = daily_objective_service.get_daily_status()
        self.assertFalse(status["force_trade_to_reach_daily_target"])

    def test_cost_first_entry_gate_rejections_and_approvals(self):
        """Test Cost-First Entry Gate rejects unprofitable, high-friction, or poor R:R trades."""
        # 1. Unprofitable after costs -> REJECT
        unprofitable_res = net_edge_gate.evaluate_candidate(
            symbol="TEST_UNPROF",
            entry_price=100.0,
            target_price=100.20, # tiny 0.20% move eaten by 0.50% SDRT + spread
            stop_loss_price=98.0,
            nominal_value=2500.0,
            is_uk=True,
            is_foreign=False
        )
        self.assertFalse(unprofitable_res["approved"])
        self.assertEqual(unprofitable_res["action"], "HOLD CASH")
        self.assertTrue(any("REJECT: Net expected return is negative/zero" in r for r in unprofitable_res["rejection_reasons"]))

        # 2. Friction consumes > 30% of profit -> REJECT
        high_friction_res = net_edge_gate.evaluate_candidate(
            symbol="TEST_HIGH_COST",
            entry_price=100.0,
            target_price=102.0, # 2% move, but wide spread causes cost > 30%
            stop_loss_price=99.0,
            nominal_value=2500.0,
            is_uk=True,
            is_foreign=False,
            current_spread_pct=0.0030 # 30 bps spread
        )
        self.assertFalse(high_friction_res["approved"])
        self.assertTrue(any("exceeds maximum allowable ceiling of 30%" in r for r in high_friction_res["rejection_reasons"]))

        # 3. Net Reward to Risk < 2.0x -> REJECT
        poor_rr_res = net_edge_gate.evaluate_candidate(
            symbol="TEST_POOR_RR",
            entry_price=100.0,
            target_price=105.0, # 5% profit target
            stop_loss_price=97.0, # 3% downside target -> Gross R:R = 1.67x < 2.0x
            nominal_value=2500.0,
            is_uk=False,
            is_foreign=True
        )
        self.assertFalse(poor_rr_res["approved"])
        self.assertTrue(any("below minimum institutional threshold of 2.0x" in r for r in poor_rr_res["rejection_reasons"]))

        # 4. Valid High-Expectancy Setup -> APPROVED
        valid_res = net_edge_gate.evaluate_candidate(
            symbol="TEST_VALID",
            entry_price=100.0,
            target_price=108.0, # 8% profit target
            stop_loss_price=97.5, # 2.5% stop loss -> Gross R:R = 3.2x
            nominal_value=2500.0,
            is_uk=False, # US equity (no SDRT)
            is_foreign=True,
            current_spread_pct=0.0004
        )
        self.assertTrue(valid_res["approved"])
        self.assertEqual(valid_res["action"], "BUY")
        self.assertGreater(valid_res["expected_net_profit_gbp"], 0.0)
        self.assertLessEqual(valid_res["cost_to_profit_pct"], 30.0)
        self.assertGreaterEqual(valid_res["net_reward_risk"], 2.0)
        # Check explicit cost breakdown keys
        self.assertIn("expected_buy_cost", valid_res)
        self.assertIn("expected_sell_cost", valid_res)
        self.assertIn("expected_spread", valid_res)
        self.assertIn("expected_slippage", valid_res)
        self.assertIn("expected_sdrt", valid_res)
        self.assertIn("expected_fx", valid_res)
        self.assertIn("expected_regulatory_fees", valid_res)
        self.assertIn("other_applicable_friction", valid_res)

    def test_sell_decision_logic_discretionary_vs_risk_exit(self):
        """Test sell decision logic: discretionary exits evaluate costs vs upside; risk exits execute unconditionally."""
        with patch.object(db, "record_trade") as mock_record, \
             patch.object(daily_objective_service, "process_trade_close") as mock_close:
            # 1. Discretionary exit with insufficient net benefit (friction consumes profit) -> HOLD
            ok, msg, net_calc = order_router.route_exit_order(
                symbol="DISC_HOLD",
                t212_ticker="DISC_US_EQ",
                quantity=10,
                current_price=100.05,
                entry_price=100.00, # Gross gain = £0.50, but sell costs > £0.50
                exit_reason="PROFIT_OPTIMIZATION_TAKE",
                is_paper=True
            )
            self.assertFalse(ok)
            self.assertIn("HOLD: Discretionary exit rejected", msg)

            # 2. Risk exit (STOP LOSS) with same tiny gain/loss -> MUST EXECUTE UNCONDITIONALLY
            ok_stop, msg_stop, _ = order_router.route_exit_order(
                symbol="RISK_STOP",
                t212_ticker="RISK_US_EQ",
                quantity=10,
                current_price=97.50,
                entry_price=100.00,
                exit_reason="STOP_LOSS_TRIGGERED",
                is_paper=True
            )
            self.assertTrue(ok_stop)
            self.assertIn("Simulated Exit", msg_stop)

            # 3. Risk exit (EMERGENCY) -> MUST EXECUTE UNCONDITIONALLY
            ok_emerg, msg_emerg, _ = order_router.route_exit_order(
                symbol="RISK_EMERG",
                t212_ticker="EMERG_US_EQ",
                quantity=10,
                current_price=98.00,
                entry_price=100.00,
                exit_reason="EMERGENCY_DERISKING_EVENT",
                is_paper=True
            )
            self.assertTrue(ok_emerg)

    def test_daily_profit_lock_at_250_gbp(self):
        """Test that once daily net profit >= £250, new discretionary entries are halted."""
        # Mock daily status returning £280 net profit
        mock_status = {
            "date": "2026-09-03",
            "daily_net_profit_objective_gbp": 250.0,
            "daily_net_return_objective_pct": 0.50,
            "base_trading_capital_gbp": 50000.0,
            "max_deployable_trading_capital_gbp": 50000.0,
            "deployable_bankroll_gbp": 50000.0,
            "banked_profit_is_non_deployable": True,
            "force_trade_to_reach_daily_target": False,
            "daily_gross_realized_pnl_gbp": 300.0,
            "daily_total_costs_gbp": 20.0,
            "daily_net_realized_pnl_gbp": 280.0,
            "daily_target_progress_pct": 112.0,
            "daily_target_achieved": True,
            "bankable_profit_today_gbp": 280.0,
            "cumulative_banked_profit_gbp": 280.0,
            "daily_max_net_loss_gbp": 500.0,
            "daily_max_net_loss_pct": 1.0,
            "daily_downside_breached": False,
            "new_discretionary_entries_allowed": False,
            "gate_reason": "PROFIT LOCK: Daily target (£250.00) achieved (+£280.00 net). No unnecessary risk permitted.",
            "turnover_gbp": 5000.0,
            "entries_today": 2,
            "exits_today": 2,
            "net_profit_per_pound_cost": 14.0
        }

        with patch.object(daily_objective_service, "get_daily_status", return_value=mock_status):
            allowed, reason = daily_objective_service.are_new_discretionary_entries_allowed()
            self.assertFalse(allowed)
            self.assertIn("PROFIT LOCK", reason)

            # Test order router entry rejection under profit lock
            success, router_msg, _ = order_router.route_entry_order(
                symbol="AAPL",
                t212_ticker="AAPL_US_EQ",
                quantity=10,
                price=150.0,
                target_price=165.0,
                stop_loss_price=146.0,
                sector="Technology",
                confidence_score=90.0,
                market_regime="BULL",
                agent_votes={"agent": "BUY"},
                risk_approved=True,
                is_paper=True,
                bypass_market_hours=True,
                bypass_audit_freeze=True
            )
            self.assertFalse(success)
            self.assertIn("PROFIT LOCK", router_msg)

    def test_daily_downside_control_halts_entries(self):
        """Test that daily net loss >= £500 halts new discretionary entries."""
        mock_downside_status = {
            "date": "2026-09-03",
            "daily_net_profit_objective_gbp": 250.0,
            "daily_net_return_objective_pct": 0.50,
            "base_trading_capital_gbp": 50000.0,
            "max_deployable_trading_capital_gbp": 50000.0,
            "deployable_bankroll_gbp": 50000.0,
            "banked_profit_is_non_deployable": True,
            "force_trade_to_reach_daily_target": False,
            "daily_gross_realized_pnl_gbp": -480.0,
            "daily_total_costs_gbp": 30.0,
            "daily_net_realized_pnl_gbp": -510.0,
            "daily_target_progress_pct": -204.0,
            "daily_target_achieved": False,
            "bankable_profit_today_gbp": 0.0,
            "cumulative_banked_profit_gbp": 0.0,
            "daily_max_net_loss_gbp": 500.0,
            "daily_max_net_loss_pct": 1.0,
            "daily_downside_breached": True,
            "new_discretionary_entries_allowed": False,
            "gate_reason": "DAILY DOWNSIDE HALT: Daily net loss limit reached (-£510.00 / £500.00). New entries paused.",
            "turnover_gbp": 5000.0,
            "entries_today": 2,
            "exits_today": 2,
            "net_profit_per_pound_cost": 0.0
        }

        with patch.object(daily_objective_service, "get_daily_status", return_value=mock_downside_status):
            allowed, reason = daily_objective_service.are_new_discretionary_entries_allowed()
            self.assertFalse(allowed)
            self.assertIn("DAILY DOWNSIDE HALT", reason)

            # Route entry order fails closed
            success, router_msg, _ = order_router.route_entry_order(
                symbol="MSFT",
                t212_ticker="MSFT_US_EQ",
                quantity=10,
                price=300.0,
                target_price=330.0,
                stop_loss_price=292.0,
                sector="Technology",
                confidence_score=90.0,
                market_regime="BULL",
                agent_votes={"agent": "BUY"},
                risk_approved=True,
                is_paper=True,
                bypass_market_hours=True,
                bypass_audit_freeze=True
            )
            self.assertFalse(success)
            self.assertIn("DAILY DOWNSIDE HALT", router_msg)

    def test_capital_banking_invariant_and_non_deployability(self):
        """Test ACTIVE_TRADING_BANKROLL <= £50,000 and banked profit is non-deployable."""
        # Scenario: NAV is £52,000, Vault Balance is £2,000
        # Active Trading Bankroll should be strictly capped at £50,000
        cap_state = capital_manager.get_capital_state(
            total_broker_nav=52000.0,
            total_invested=20000.0,
            available_cash=32000.0
        )
        self.assertLessEqual(cap_state["active_trading_bankroll"], 50000.0)
        self.assertEqual(cap_state["max_deployable_trading_capital"], 50000.0)
        self.assertTrue(cap_state["banked_profit_is_non_deployable"])

        # Sizing must use core_capital / active_trading_bankroll, NOT total NAV
        self.assertLessEqual(cap_state["core_capital"], 50000.0)

    def test_30day_challenge_evaluation_12_metrics(self):
        """Test computation of the 12 required challenge evaluation metrics."""
        eval_metrics = daily_objective_service.compute_30day_challenge_evaluation()
        required_keys = [
            "total_banked_net_profit_gbp",
            "average_daily_net_profit_gbp",
            "median_daily_net_profit_gbp",
            "number_of_days_target_met",
            "profitable_day_pct",
            "no_trade_day_count",
            "worst_day_gbp",
            "maximum_drawdown_pct",
            "net_expectancy_per_trade_gbp",
            "profit_factor",
            "total_trading_costs_gbp",
            "net_profit_per_pound_cost"
        ]
        for k in required_keys:
            self.assertIn(k, eval_metrics)

        self.assertEqual(eval_metrics["challenge_target_daily_gbp"], 250.0)
        self.assertGreaterEqual(eval_metrics["profit_factor"], 0.0)
        self.assertGreaterEqual(eval_metrics["maximum_drawdown_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
