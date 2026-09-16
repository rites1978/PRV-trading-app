"""
TDD Tests: Hit-and-Run Realised-Net Daily Banking Ledger
Verifies:
1. Base target = £100 REALISED NET profit after all trading costs.
2. When net realised P&L reaches £100, it is marked as BANKED.
3. System continues trading after £100 target is reached (never stops merely because target met).
4. Unrealised gains NEVER count toward the £100 target or banked profit.
5. Accurate tracking of:
   - gross_realised_pnl
   - estimated/actual costs
   - net_realised_pnl
   - banked_net_profit_today
   - remaining_to_base_target
"""
import unittest


class TestDailyBankingLedger(unittest.TestCase):

    def setUp(self):
        from src.hit_and_run.banking import DailyBankingLedger
        self.ledger = DailyBankingLedger(trading_date="2026-09-16", base_target_gbp=100.0)

    def test_initial_state(self):
        summary = self.ledger.get_banking_summary()
        self.assertEqual(summary["trading_date"], "2026-09-16")
        self.assertEqual(summary["base_target_gbp"], 100.0)
        self.assertEqual(summary["gross_realised_pnl"], 0.0)
        self.assertEqual(summary["trading_costs"], 0.0)
        self.assertEqual(summary["net_realised_pnl"], 0.0)
        self.assertEqual(summary["banked_net_profit_today"], 0.0)
        self.assertEqual(summary["remaining_to_base_target"], 100.0)
        self.assertFalse(summary["base_target_achieved"])
        self.assertTrue(summary["continue_trading"])

    def test_unrealised_gains_do_not_count_toward_banking(self):
        """Unrealised paper gains must NEVER increase banked profit or reduce remaining target."""
        # Simulated open position with £150 unrealised gain
        summary = self.ledger.get_banking_summary(unrealised_pnl_gbp=150.0)

        self.assertEqual(summary["banked_net_profit_today"], 0.0)
        self.assertEqual(summary["remaining_to_base_target"], 100.0)
        self.assertFalse(summary["base_target_achieved"])
        # Telemetry may report unrealised PnL for visibility, but NOT banked
        self.assertEqual(summary.get("unrealised_pnl_gbp"), 150.0)

    def test_recording_realised_trades_towards_target(self):
        """Trades contribute gross PnL minus costs to net realised PnL."""
        # Trade 1: +£60 gross, £4 costs => +£56 net
        self.ledger.record_realised_trade(
            trade_id="TR_1",
            ticker="AAPL_US_EQ",
            gross_pnl_gbp=60.0,
            costs_gbp=4.0,
            exit_reason="TAKE_PROFIT"
        )

        s1 = self.ledger.get_banking_summary()
        self.assertEqual(s1["gross_realised_pnl"], 60.0)
        self.assertEqual(s1["trading_costs"], 4.0)
        self.assertEqual(s1["net_realised_pnl"], 56.0)
        self.assertEqual(s1["banked_net_profit_today"], 56.0)
        self.assertEqual(s1["remaining_to_base_target"], 44.0)
        self.assertFalse(s1["base_target_achieved"])
        self.assertTrue(s1["continue_trading"])

        # Trade 2: +£50 gross, £3 costs => +£47 net (Total net = £103)
        self.ledger.record_realised_trade(
            trade_id="TR_2",
            ticker="TSLA_US_EQ",
            gross_pnl_gbp=50.0,
            costs_gbp=3.0,
            exit_reason="TAKE_PROFIT"
        )

        s2 = self.ledger.get_banking_summary()
        self.assertEqual(s2["gross_realised_pnl"], 110.0)
        self.assertEqual(s2["trading_costs"], 7.0)
        self.assertEqual(s2["net_realised_pnl"], 103.0)
        self.assertEqual(s2["banked_net_profit_today"], 103.0)
        self.assertEqual(s2["remaining_to_base_target"], 0.0)
        self.assertTrue(s2["base_target_achieved"])
        # MANDATORY: DO NOT stop trading merely because £100 has been reached!
        self.assertTrue(s2["continue_trading"])

    def test_continue_hunting_and_banking_beyond_target(self):
        """After banking £100, continuing trading banks additional profit."""
        self.ledger.record_realised_trade(trade_id="T1", ticker="T1", gross_pnl_gbp=105.0, costs_gbp=5.0)
        # Now at £100 banked

        # Trade 3 adds another £40 net
        self.ledger.record_realised_trade(trade_id="T3", ticker="T3", gross_pnl_gbp=42.0, costs_gbp=2.0)

        s = self.ledger.get_banking_summary()
        self.assertEqual(s["net_realised_pnl"], 140.0)
        self.assertEqual(s["banked_net_profit_today"], 140.0)
        self.assertEqual(s["remaining_to_base_target"], 0.0)
        self.assertTrue(s["continue_trading"])

    def test_handling_loss_trade(self):
        """A loss trade reduces net realised PnL and increases remaining target."""
        self.ledger.record_realised_trade(
            trade_id="TLOSS",
            ticker="BAD_EQ",
            gross_pnl_gbp=-25.0,
            costs_gbp=2.0,
            exit_reason="STOP_LOSS_EXIT"
        )

        s = self.ledger.get_banking_summary()
        self.assertEqual(s["gross_realised_pnl"], -25.0)
        self.assertEqual(s["trading_costs"], 2.0)
        self.assertEqual(s["net_realised_pnl"], -27.0)
        # Banked profit cannot be negative
        self.assertEqual(s["banked_net_profit_today"], 0.0)
        self.assertEqual(s["remaining_to_base_target"], 127.0)


if __name__ == "__main__":
    unittest.main()
