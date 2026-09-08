"""
🏛️ PRV CAPITAL | REGRESSION TEST: GBX / GBP TYPING & ANTO -£5,698.58 MTM DEFECT
Reproduces the false ANTO -£5,698.58 MTM emergency lock defect caused by implicit
pence (GBX) to pound (GBP) arithmetic scaling errors.
"""
import unittest
from unittest.mock import patch, MagicMock
from src.core.money import Money, Currency, CurrencyUnit
from src.strategies.v2_rotation import strategy_v2, PositionState
from src.portfolio.capital_state_machine import capital_state_machine, DailyState
from src.execution.order_router import order_router
from src.data.universe import universe_manager


class TestGbxGbpTypingAndAntoDefect(unittest.TestCase):
    def setUp(self):
        self.anto_t212 = "ANTOl_EQ"
        self.qty = 68.0
        # In Trading212, UK equities are quoted in pence (GBX)
        self.avg_price_gbx = 3929.0  # 3929.0 pence = £39.29
        self.cur_price_gbx = 3872.0  # 3872.0 pence = £38.72
        
    def test_reproduce_anto_implicit_scaling_defect(self):
        """
        Demonstrates how passing raw un-normalized GBX prices into calculations
        causes a 100x blowup resulting in false -£5,428.07 net P&L and -£2,671.72 max loss limit.
        """
        # Defective implicit arithmetic: treating GBX as GBP
        defective_deployed = self.qty * self.avg_price_gbx  # 267,172.00
        defective_cur_val = self.qty * self.cur_price_gbx   # 263,296.00
        
        self.assertAlmostEqual(defective_deployed, 267172.00, places=2)
        
        # Defective friction and liquidation calculation
        friction = strategy_v2.compute_entry_friction(defective_deployed, is_uk=True, is_foreign=False, shares_count=self.qty)
        defective_eval = strategy_v2.calculate_estimated_net_liquidation_pnl(
            current_value=defective_cur_val,
            true_entry_capital=defective_deployed,
            entry_costs=friction["total_entry_friction"],
            ticker=self.anto_t212,
            is_uk=True,
            is_foreign=False,
            shares_count=self.qty
        )
        
        # The defective net P&L is ~ -£5,346.51 (over £5,000 loss) instead of true ~ -£52.12!
        self.assertLess(defective_eval["estimated_net_pnl"], -5000.0)
        
        # And the defective max loss limit is -£2,671.72 (1% of £267,172)
        max_loss_defective = strategy_v2.calculate_max_intended_loss(defective_deployed)
        self.assertAlmostEqual(max_loss_defective, 2671.72, places=2)
        
        # Which triggers a false EXIT_HARD_STOP!
        lifecycle_defective = strategy_v2.evaluate_position_lifecycle(
            current_state=PositionState.OPEN,
            capital_deployed=defective_deployed,
            estimated_net_pnl=defective_eval["estimated_net_pnl"],
            peak_net_pnl=0.0
        )
        self.assertEqual(lifecycle_defective["action"], "EXIT_HARD_STOP")
        self.assertIn("breached max -1.00% loss limit (-£2671.72)", lifecycle_defective["reason"])

    def test_strong_money_typing_prevents_anto_defect(self):
        """
        Verifies that explicit Money typing converts GBX to GBP major unit,
        producing exact true arithmetic: deployed capital £2,671.72, gross loss -£38.76.
        """
        # Strong Money typing
        avg_money = Money(self.avg_price_gbx, Currency.GBX).to_major()
        cur_money = Money(self.cur_price_gbx, Currency.GBX).to_major()
        
        self.assertEqual(avg_money.currency, Currency.GBP)
        self.assertEqual(avg_money.unit, CurrencyUnit.MAJOR)
        self.assertAlmostEqual(avg_money.amount, 39.29, places=2)
        self.assertAlmostEqual(cur_money.amount, 38.72, places=2)
        
        true_deployed = round(self.qty * avg_money.amount, 2)
        true_cur_val = round(self.qty * cur_money.amount, 2)
        
        self.assertEqual(true_deployed, 2671.72)
        self.assertEqual(true_cur_val, 2632.96)
        
        friction = strategy_v2.compute_entry_friction(true_deployed, is_uk=True, is_foreign=False, shares_count=self.qty)
        true_eval = strategy_v2.calculate_estimated_net_liquidation_pnl(
            current_value=true_cur_val,
            true_entry_capital=true_deployed,
            entry_costs=friction["total_entry_friction"],
            ticker=self.anto_t212,
            is_uk=True,
            is_foreign=False,
            shares_count=self.qty
        )
        
        # Real gross P&L is -£38.76, NOT -£3,876.00
        self.assertEqual(true_eval["gross_pnl"], -38.76)
        # Real entry SDRT (0.5%) is £13.36, NOT £1,335.86
        self.assertEqual(friction["sdrt"], 13.36)
        # Max intended loss is £26.72, NOT £2,671.72
        max_loss_true = strategy_v2.calculate_max_intended_loss(true_deployed)
        self.assertEqual(max_loss_true, 26.72)

    def test_order_router_normalizes_gbx_prices(self):
        """
        Verifies that order_router.route_exit_order automatically validates and normalizes
        raw GBX prices for UK tickers so that nominal values are strictly in GBP.
        """
        # If route_exit_order is passed raw broker prices in pence (3929.0 and 3872.0)
        # with is_paper=True, it MUST normalize them to £39.29 and £38.72.
        success, msg, net_calc = order_router.route_exit_order(
            symbol="ANTOl_EQ",
            t212_ticker="ANTOl_EQ",
            quantity=68.0,
            current_price=self.cur_price_gbx,  # raw pence
            entry_price=self.avg_price_gbx,    # raw pence
            exit_reason="REGRESSION_TEST_EXIT",
            is_paper=True,
            is_simulation=True
        )
        self.assertTrue(success)
        # Gross profit/loss must be approximately -£38.76, NEVER -£3,876.00
        self.assertAlmostEqual(net_calc["gross_profit_loss"], -38.76, places=1)
        # Total transaction cost must be reasonable (£10-£20), NEVER > £1,000
        self.assertLess(net_calc["total_transaction_costs"], 50.0)
        # Net realized P&L must be approximately -£52.12, NEVER -£5,428.07
        self.assertGreater(net_calc["net_realized_pnl"], -100.0)


if __name__ == "__main__":
    unittest.main()
