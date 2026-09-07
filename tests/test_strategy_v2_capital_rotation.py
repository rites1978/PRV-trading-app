"""
🏛️ PRV CAPITAL | STRATEGY V2: NET PROFIT CAPITAL ROTATION
Test-Driven Development (TDD) Test Suite.
Tests all 20 mandatory invariants specified in Section 19:
1. +0.5% target calculated from deployed capital
2. -1.0% loss calculated from deployed capital
3. SDRT inclusion
4. FX fee inclusion
5. estimated exit cost inclusion
6. no double-counted embedded costs
7. profit protection activates only after +0.5% NET
8. profitable trend may continue after +0.5%
9. profit floor ratchets upward
10. vault receives only actual realised broker profit
11. vault cannot be used for sizing
12. vault cannot be withdrawn without user authorization
13. Recovery Mode restores £50k before banking
14. no martingale after loss
15. V1 frozen and unchanged
16. only V2 may route orders
17. broker fill required before execution is counted
18. broker-native stop synchronization
19. stale stop removed after exit
20. no fixed 45% cash floor in V2
"""
import unittest
from unittest.mock import patch, MagicMock
from src.config.settings import settings
from src.strategies.registry import strategy_registry
from src.strategies.v2_rotation import StrategyV2, PositionState
from src.portfolio.capital_manager import CapitalManager


class TestStrategyV2CapitalRotation(unittest.TestCase):

    def setUp(self):
        self.v2 = StrategyV2()
        self.cap_mgr = CapitalManager(starting_capital=50000.0)

    # -------------------------------------------------------------------------
    # Invariant 15: V1 Frozen and Unchanged
    # -------------------------------------------------------------------------
    def test_15_v1_frozen_and_unchanged(self):
        """V1 parameter manifest must match the frozen benchmark hash exactly."""
        manifest_hash = settings.get_parameter_manifest_hash()
        self.assertEqual(manifest_hash, "7c512be5bc26910c1c4ed81a3e650480a676cd750faa49bc8dbd8901360bc708")
        
        # Registry record must show V1 as FROZEN_BENCHMARK and SHADOW
        v1_meta = strategy_registry.get_strategy("V1")
        self.assertIsNotNone(v1_meta)
        self.assertEqual(v1_meta["status"], "FROZEN_BENCHMARK")
        self.assertEqual(v1_meta["execution_mode"], "SHADOW")
        self.assertEqual(v1_meta["config_hash"], manifest_hash)

    # -------------------------------------------------------------------------
    # Invariant 16: Only V2 May Route Practice Orders
    # -------------------------------------------------------------------------
    def test_16_only_v2_may_route_orders(self):
        """V1 is strictly shadow; only V2 has broker routing authority."""
        can_v1_route = strategy_registry.can_strategy_route_orders("V1")
        self.assertFalse(can_v1_route)
        
        can_v2_route = strategy_registry.can_strategy_route_orders("V2")
        self.assertTrue(can_v2_route)
        
        self.assertEqual(strategy_registry.get_active_execution_strategy_id(), "V2")

        # Calling order_router with strategy_id="V1" must be blocked unconditionally
        from src.execution.order_router import order_router
        success, reason, data = order_router.route_entry_order(
            symbol="HSBA.L",
            t212_ticker="HSBAl_EQ",
            quantity=10,
            price=100.0,
            target_price=105.0,
            stop_loss_price=98.0,
            sector="Financials",
            confidence_score=85.0,
            market_regime="BULL",
            agent_votes={},
            risk_approved=True,
            bypass_market_hours=True,
            strategy_id="V1"
        )
        self.assertFalse(success)
        self.assertIn("STRATEGY_V1_SHADOW_ONLY", data.get("rejection_reasons", []))

    # -------------------------------------------------------------------------
    # Invariant 1: +0.50% Net Target Calculated from Deployed Capital
    # -------------------------------------------------------------------------
    def test_01_target_calculated_from_deployed_capital(self):
        """Min net return must be at least +0.50% NET of capital deployed in that transaction."""
        test_cases = [
            (5000.0, 25.0),
            (10000.0, 50.0),
            (20000.0, 100.0),
            (50000.0, 250.0),
        ]
        for deployed, expected_min_net in test_cases:
            target = self.v2.calculate_min_net_profit_target(deployed)
            self.assertAlmostEqual(target, expected_min_net, places=2)

    # -------------------------------------------------------------------------
    # Invariant 2: -1.00% Loss Calculated from Deployed Capital
    # -------------------------------------------------------------------------
    def test_02_loss_calculated_from_deployed_capital(self):
        """Max intended loss must be exactly 1.00% of capital deployed in that transaction."""
        test_cases = [
            (5000.0, 50.0),
            (10000.0, 100.0),
            (25000.0, 250.0),
            (50000.0, 500.0),
        ]
        for deployed, expected_max_loss in test_cases:
            max_loss = self.v2.calculate_max_intended_loss(deployed)
            self.assertAlmostEqual(max_loss, expected_max_loss, places=2)

    # -------------------------------------------------------------------------
    # Invariant 3: SDRT Inclusion in Net Edge & Net Liquidation P&L
    # -------------------------------------------------------------------------
    def test_03_sdrt_inclusion_in_net_liquidation(self):
        """UK equity purchases incur 0.50% SDRT, which must reduce net liquidation P&L."""
        capital_deployed = 10000.0
        # Buy 100 shares at £100 = £10,000. SDRT = 0.5% = £50.
        # If current price is £100.50 (+0.50% gross = £10,050 gross value)
        pnl = self.v2.calculate_estimated_net_liquidation_pnl(
            current_value=10050.0,
            true_entry_capital=10000.0,
            entry_costs=50.0, # £50 SDRT
            ticker="VODl_EQ",
            is_uk=True,
            is_foreign=False,
            shares_count=100
        )
        self.assertLessEqual(pnl["estimated_net_pnl"], 0.0)
        self.assertFalse(pnl["target_reached"])

    # -------------------------------------------------------------------------
    # Invariant 4: FX Fee Inclusion
    # -------------------------------------------------------------------------
    def test_04_fx_fee_inclusion(self):
        """Foreign trades incur 0.15% FX on entry AND estimated 0.15% on exit."""
        pnl = self.v2.calculate_estimated_net_liquidation_pnl(
            current_value=10060.0,
            true_entry_capital=10000.0,
            entry_costs=15.0, # £15 Entry FX
            ticker="AAPL_US_EQ",
            is_uk=False,
            is_foreign=True,
            shares_count=50
        )
        self.assertAlmostEqual(pnl["estimated_exit_costs"]["fx_fee"], 15.09, delta=0.5)
        self.assertLess(pnl["estimated_net_pnl"], 35.0)

    # -------------------------------------------------------------------------
    # Invariant 5: Estimated Exit Costs Inclusion
    # -------------------------------------------------------------------------
    def test_05_estimated_exit_costs_inclusion(self):
        """Net liquidation calculation must include uncharged exit costs (regulatory, FX, spread)."""
        pnl = self.v2.calculate_estimated_net_liquidation_pnl(
            current_value=20000.0,
            true_entry_capital=19800.0,
            entry_costs=30.0,
            ticker="MSFT_US_EQ",
            is_uk=False,
            is_foreign=True,
            shares_count=50
        )
        self.assertGreater(pnl["estimated_exit_costs"]["total_exit_costs"], 0.0)
        self.assertEqual(
            pnl["estimated_net_pnl"],
            round(20000.0 - 19800.0 - 30.0 - pnl["estimated_exit_costs"]["total_exit_costs"], 2)
        )

    # -------------------------------------------------------------------------
    # Invariant 6: No Double-Counted Embedded Costs
    # -------------------------------------------------------------------------
    def test_06_no_double_counted_embedded_costs(self):
        """Spread/slippage already inside broker fill price must not be deducted again as explicit entry cost."""
        costs = self.v2.compute_entry_friction(
            nominal_capital=10000.0,
            fill_price_includes_spread=True,
            is_uk=False,
            is_foreign=True,
            shares_count=100
        )
        self.assertEqual(costs["embedded_spread_fee"], 0.0)
        self.assertEqual(costs["explicit_entry_fee"], 15.0) # FX fee only

    # -------------------------------------------------------------------------
    # Invariant 7: Profit Protection Activates Only After +0.50% NET
    # -------------------------------------------------------------------------
    def test_07_profit_protection_activates_only_after_point_five_percent_net(self):
        """Position state transitions from OPEN to PROFIT_PROTECTED only when net return >= +0.50%."""
        capital_deployed = 10000.0

        eval_a = self.v2.evaluate_position_lifecycle(
            current_state=PositionState.OPEN,
            capital_deployed=capital_deployed,
            estimated_net_pnl=45.0,
            peak_net_pnl=45.0,
            trend_score=80.0
        )
        self.assertEqual(eval_a["new_state"], PositionState.OPEN)
        self.assertFalse(eval_a["target_reached"])

        eval_b = self.v2.evaluate_position_lifecycle(
            current_state=PositionState.OPEN,
            capital_deployed=capital_deployed,
            estimated_net_pnl=50.0,
            peak_net_pnl=50.0,
            trend_score=80.0
        )
        self.assertEqual(eval_b["new_state"], PositionState.PROFIT_PROTECTED)
        self.assertTrue(eval_b["target_reached"])
        self.assertGreaterEqual(eval_b["protected_floor_gbp"], 50.0)

    # -------------------------------------------------------------------------
    # Invariant 8: Profitable Trend May Continue After +0.50%
    # -------------------------------------------------------------------------
    def test_08_profitable_trend_may_continue_after_target(self):
        """When target is reached and trend is strong, position is NOT auto-sold; it HOLDS."""
        eval_res = self.v2.evaluate_position_lifecycle(
            current_state=PositionState.PROFIT_PROTECTED,
            capital_deployed=50000.0,
            estimated_net_pnl=350.0, # Target was £250, now +£350
            peak_net_pnl=350.0,
            trend_score=75.0 # Strong trend
        )
        self.assertEqual(eval_res["action"], "HOLD")
        self.assertFalse(eval_res["should_exit"])

    # -------------------------------------------------------------------------
    # Invariant 9: Profit Floor Ratchets Upward
    # -------------------------------------------------------------------------
    def test_09_profit_floor_ratchets_upward(self):
        """As profit increases, protected floor ratchets upward and exits on trend breakdown."""
        capital_deployed = 50000.0
        
        step1 = self.v2.evaluate_position_lifecycle(
            current_state=PositionState.PROFIT_PROTECTED,
            capital_deployed=capital_deployed,
            estimated_net_pnl=500.0,
            peak_net_pnl=500.0,
            trend_score=75.0
        )
        self.assertEqual(step1["action"], "HOLD")
        ratchet_floor = step1["protected_floor_gbp"]
        self.assertGreater(ratchet_floor, 250.0)

        step2 = self.v2.evaluate_position_lifecycle(
            current_state=PositionState.PROFIT_PROTECTED,
            capital_deployed=capital_deployed,
            estimated_net_pnl=320.0,
            peak_net_pnl=500.0,
            trend_score=35.0 # Trend deterioration
        )
        self.assertEqual(step2["action"], "EXIT_PROFIT_PROTECTION")
        self.assertTrue(step2["should_exit"])

    # -------------------------------------------------------------------------
    # Invariant 10: Vault Receives Only Actual Realised Broker Profit
    # -------------------------------------------------------------------------
    def test_10_vault_receives_only_actual_realised_broker_profit(self):
        """Unrealized profit is NEVER banked. Only confirmed broker fills trigger vault transfer."""
        vault_before = self.cap_mgr.get_capital_state(50000.0, 10000.0, 40000.0)["profit_vault_balance"]
        
        self.v2.record_unrealized_mtm("AAPL_US_EQ", 500.0)
        self.assertEqual(self.cap_mgr.get_capital_state(50000.0, 10000.0, 40000.0)["profit_vault_balance"], vault_before)

        vault_change = self.v2.process_realized_trade_close(
            ticker="AAPL_US_EQ",
            deployed_capital=10000.0,
            realized_net_pnl=350.0,
            active_equity_before=50000.0
        )
        self.assertEqual(vault_change["banked_to_vault"], 350.0)

    # -------------------------------------------------------------------------
    # Invariant 11: Vault Cannot Be Used for Sizing
    # -------------------------------------------------------------------------
    def test_11_vault_cannot_be_used_for_sizing(self):
        """Position sizing must strictly use active_trading_equity, excluding profit_vault."""
        sizing = self.v2.calculate_order_sizing(
            total_broker_nav=55000.0,
            vault_balance=5000.0,
            available_cash=50000.0,
            target_allocation_pct=20.0,
            stock_price=100.0,
            stop_loss_price=98.0
        )
        self.assertEqual(sizing["capital_base_used"], 50000.0)
        self.assertEqual(sizing["nominal_allocation_gbp"], 10000.0)

    # -------------------------------------------------------------------------
    # Invariant 12: Vault Cannot Be Withdrawn Without User Authorization
    # -------------------------------------------------------------------------
    def test_12_vault_cannot_be_withdrawn_without_user_authorization(self):
        """Vault balance is strictly locked; withdrawal or recycling raises exception without user flag."""
        with self.assertRaises(PermissionError):
            self.v2.withdraw_from_vault(amount=500.0, user_authorized=False)
        
        res = self.v2.withdraw_from_vault(amount=500.0, user_authorized=True)
        self.assertTrue(res["success"])

    # -------------------------------------------------------------------------
    # Invariant 13: Recovery Mode Restores £50k Before Banking
    # -------------------------------------------------------------------------
    def test_13_recovery_mode_restores_50k_before_banking(self):
        """When active equity < £50k, realized profits restore base to £50,000 before vaulting."""
        t1 = self.v2.process_realized_trade_close(
            ticker="V_US_EQ",
            deployed_capital=10000.0,
            realized_net_pnl=150.0,
            active_equity_before=49800.0
        )
        self.assertEqual(t1["restored_to_base"], 150.0)
        self.assertEqual(t1["banked_to_vault"], 0.0)
        self.assertEqual(t1["new_active_equity"], 49950.0)

        t2 = self.v2.process_realized_trade_close(
            ticker="JNJ_US_EQ",
            deployed_capital=10000.0,
            realized_net_pnl=120.0,
            active_equity_before=49950.0
        )
        self.assertEqual(t2["restored_to_base"], 50.0)
        self.assertEqual(t2["banked_to_vault"], 70.0)
        self.assertEqual(t2["new_active_equity"], 50000.0)

    # -------------------------------------------------------------------------
    # Invariant 14: No Martingale After Loss
    # -------------------------------------------------------------------------
    def test_14_no_martingale_after_loss(self):
        """After a loss, position size must decrease or remain proportional, never increase."""
        size_normal = self.v2.calculate_order_sizing(
            total_broker_nav=50000.0,
            vault_balance=0.0,
            available_cash=50000.0,
            target_allocation_pct=10.0,
            stock_price=100.0,
            stop_loss_price=98.0
        )
        
        size_after_loss = self.v2.calculate_order_sizing(
            total_broker_nav=49000.0,
            vault_balance=0.0,
            available_cash=49000.0,
            target_allocation_pct=10.0,
            stock_price=100.0,
            stop_loss_price=98.0
        )
        self.assertLess(size_after_loss["nominal_allocation_gbp"], size_normal["nominal_allocation_gbp"])
        self.assertLessEqual(size_after_loss["order_quantity"], size_normal["order_quantity"])

    # -------------------------------------------------------------------------
    # Invariant 17: Broker Fill Required Before Execution Is Counted
    # -------------------------------------------------------------------------
    def test_17_broker_fill_required_before_execution_is_counted(self):
        """SIGNAL_APPROVED and DISPATCH_ATTEMPTED are telemetry only, not executed trades."""
        status_pending = self.v2.record_order_lifecycle("ORD-001", "DISPATCH_ATTEMPTED")
        self.assertFalse(status_pending["is_executed_trade"])

        status_filled = self.v2.record_order_lifecycle("ORD-001", "FILLED", fill_price=150.0, fill_qty=20)
        self.assertTrue(status_filled["is_executed_trade"])

    # -------------------------------------------------------------------------
    # Invariant 18: Broker-Native Stop Synchronization
    # -------------------------------------------------------------------------
    def test_18_broker_native_stop_synchronization(self):
        """Stop ratchet calls broker cancel/replace and records stop order ID."""
        with patch("src.brokers.trading212.broker.sync_broker_stop_order") as mock_sync:
            mock_sync.return_value = {"success": True, "action": "PLACED_NEW", "order_id": "STP-999", "stopPrice": 105.0}
            res = self.v2.update_broker_stop_protection(ticker="ULVRl_EQ", quantity=50, stop_price=105.0)
            self.assertTrue(res["success"])
            self.assertEqual(res["broker_stop_id"], "STP-999")
            mock_sync.assert_called_once_with("ULVRl_EQ", 50, 105.0)

    # -------------------------------------------------------------------------
    # Invariant 19: Stale Stop Removed After Exit
    # -------------------------------------------------------------------------
    def test_19_stale_stop_removed_after_exit(self):
        """When position closes, existing broker protective stops must be cancelled immediately."""
        with patch("src.brokers.trading212.broker.cancel_stop_orders_for_ticker") as mock_cancel:
            mock_cancel.return_value = ["STP-999"]
            cancelled = self.v2.cleanup_stops_after_exit("ULVRl_EQ")
            self.assertEqual(cancelled, ["STP-999"])
            mock_cancel.assert_called_once_with("ULVRl_EQ")

    # -------------------------------------------------------------------------
    # Invariant 20: No Fixed 45% Cash Floor in V2
    # -------------------------------------------------------------------------
    def test_20_no_fixed_45_percent_cash_floor_in_v2(self):
        """V2 allows dynamic allocation from 0% cash to 100% cash based on evidence."""
        alloc_100 = self.v2.calculate_deployable_capacity(
            active_equity=50000.0,
            evidence_score=95.0,
            regime="STRONG_BULL"
        )
        self.assertEqual(alloc_100["min_cash_floor_gbp"], 0.0)
        self.assertEqual(alloc_100["max_deployable_capital"], 50000.0)

        alloc_cash = self.v2.calculate_deployable_capacity(
            active_equity=50000.0,
            evidence_score=20.0,
            regime="BEAR_STRESS"
        )
        self.assertEqual(alloc_cash["max_deployable_capital"], 0.0)

    # -------------------------------------------------------------------------
    # Invariant 21: Deterministic Accounting - Normal Profit Vaulting
    # -------------------------------------------------------------------------
    def test_21_deterministic_accounting_invariant_normal_profit_vaulting(self):
        """
        Deterministic test for Invariant A: Normal Profit Vaulting
        Starting base: £50,000
        Trade deployed: £20,000
        Actual realised net P&L: +£137
        Expected:
          - Active base after exit: £50,000
          - Profit vault: £137
          - Deployable capital: £50,000
        """
        starting_base = 50000.0
        trade_deployed = 20000.0
        realized_net_pnl = 137.0

        close_result = self.v2.process_realized_trade_close(
            ticker="VODl_EQ",
            deployed_capital=trade_deployed,
            realized_net_pnl=realized_net_pnl,
            active_equity_before=starting_base
        )
        self.assertEqual(close_result["new_active_equity"], 50000.0)
        self.assertEqual(close_result["banked_to_vault"], 137.0)
        self.assertEqual(close_result["restored_to_base"], 0.0)
        self.assertEqual(close_result["new_deficit"], 0.0)

        # Verify deployable capacity on £50,000 active base
        capacity = self.v2.calculate_deployable_capacity(
            active_equity=close_result["new_active_equity"],
            evidence_score=85.0,
            regime="BULL_TREND"
        )
        self.assertEqual(capacity["max_deployable_capital"], 50000.0)

    # -------------------------------------------------------------------------
    # Invariant 22: Deterministic Accounting - Recovery Mode Deficit Restoration
    # -------------------------------------------------------------------------
    def test_22_deterministic_accounting_invariant_recovery_mode_deficit_restoration(self):
        """
        Deterministic test for Invariant B: Recovery Mode Deficit Restoration
        Starting base: £50,000
        Trade loss: -£200 -> Active base: £49,800
        Next trade profit: +£260
        Expected:
          - £200 -> restore base to £50,000
          - £60  -> profit vault
          - Active base after exit: £50,000
          - Profit vault: £60
        """
        starting_base = 50000.0
        trade_loss = -200.0

        # First trade: -£200 loss
        loss_result = self.v2.process_realized_trade_close(
            ticker="SLB_US_EQ",
            deployed_capital=10000.0,
            realized_net_pnl=trade_loss,
            active_equity_before=starting_base
        )
        self.assertEqual(loss_result["new_active_equity"], 49800.0)
        self.assertEqual(loss_result["new_deficit"], 200.0)
        self.assertEqual(loss_result["banked_to_vault"], 0.0)
        self.assertEqual(loss_result["restored_to_base"], 0.0)

        # Second trade: +£260 profit
        profit_result = self.v2.process_realized_trade_close(
            ticker="NVDA_US_EQ",
            deployed_capital=15000.0,
            realized_net_pnl=260.0,
            active_equity_before=loss_result["new_active_equity"]
        )
        self.assertEqual(profit_result["restored_to_base"], 200.0)
        self.assertEqual(profit_result["banked_to_vault"], 60.0)
        self.assertEqual(profit_result["new_active_equity"], 50000.0)
        self.assertEqual(profit_result["new_deficit"], 0.0)

    # -------------------------------------------------------------------------
    # Invariant 23: Persistent V2 Rotation Ledger Schema and Storage
    # -------------------------------------------------------------------------
    def test_23_persistent_v2_rotation_ledger_schema_and_storage(self):
        """
        Proves the V2 rotation ledger stores every completed rotation independently:
        rotation_id, strategy_id = V2, ticker, deployed_capital, entry_broker_ids,
        exit_broker_ids, gross_pnl, SDRT, FX, regulatory_fees, other_costs,
        realised_net_pnl, recovery_allocation, vault_allocation.
        """
        from src.database.db import db
        rotation_id = "ROT_V2_UNIT_001"
        rec = self.v2.record_rotation(
            rotation_id=rotation_id,
            ticker="HSBAl_EQ",
            deployed_capital=5000.0,
            entry_broker_ids=["54400018132"],
            exit_broker_ids=["54400025900"],
            gross_pnl=85.50,
            sdrt=13.65,
            fx=0.0,
            regulatory_fees=0.0,
            other_costs=0.0,
            realised_net_pnl=71.85,
            active_equity_before=50000.0
        )
        self.assertEqual(rec["rotation_id"], rotation_id)
        self.assertEqual(rec["strategy_id"], "V2")
        self.assertEqual(rec["ticker"], "HSBAl_EQ")
        self.assertEqual(rec["deployed_capital"], 5000.0)
        self.assertEqual(rec["entry_broker_ids"], '["54400018132"]')
        self.assertEqual(rec["exit_broker_ids"], '["54400025900"]')
        self.assertEqual(rec["gross_pnl"], 85.50)
        self.assertEqual(rec["sdrt"], 13.65)
        self.assertEqual(rec["fx"], 0.0)
        self.assertEqual(rec["regulatory_fees"], 0.0)
        self.assertEqual(rec["other_costs"], 0.0)
        self.assertEqual(rec["realised_net_pnl"], 71.85)
        self.assertEqual(rec["recovery_allocation"], 0.0)
        self.assertEqual(rec["vault_allocation"], 71.85)

        # Verify DB query
        fetched = db.get_v2_rotation_by_id(rotation_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["rotation_id"], rotation_id)
        self.assertEqual(fetched["strategy_id"], "V2")
        self.assertEqual(fetched["ticker"], "HSBAl_EQ")
        self.assertEqual(fetched["realised_net_pnl"], 71.85)
        self.assertEqual(fetched["vault_allocation"], 71.85)

        # Cleanup
        with db.get_connection() as conn:
            conn.execute("DELETE FROM v2_rotations WHERE rotation_id = ?", (rotation_id,))
            conn.commit()

    # -------------------------------------------------------------------------
    # Invariant 24: Zero-Fill vs Deployed Capital Invariant
    # -------------------------------------------------------------------------
    def test_24_zero_fill_vs_deployed_capital_invariant(self):
        """
        Proves the Zero-Fill vs Deployed Capital Invariant:
        If fill quantity is 0, actual_deployed_capital MUST be £0.00.
        Planned sizing (£2,457.53) must be strictly isolated in planned_capital.
        Never count planned/unfilled capital as deployed capital.
        """
        from src.database.db import db
        rotation_id = "ROT_V2_ZERO_FILL_001"
        rec = self.v2.record_rotation(
            rotation_id=rotation_id,
            ticker="LLOYl_EQ",
            deployed_capital=2457.53,
            planned_capital=2457.53,
            filled_quantity=0.0,
            entry_broker_ids=["54500759929"],
            exit_broker_ids=["54500759931"],
            gross_pnl=0.0,
            sdrt=0.0,
            fx=0.0,
            regulatory_fees=0.0,
            other_costs=0.0,
            realised_net_pnl=0.0,
            active_equity_before=50000.0
        )
        self.assertEqual(rec["rotation_id"], rotation_id)
        self.assertEqual(rec["strategy_id"], "V2")
        self.assertEqual(rec["ticker"], "LLOYl_EQ")
        self.assertEqual(rec["planned_capital"], 2457.53)
        self.assertEqual(rec["deployed_capital"], 0.00) # Enforced £0.00 for zero fill
        self.assertEqual(rec["realised_net_pnl"], 0.00)
        self.assertEqual(rec["recovery_allocation"], 0.00)
        self.assertEqual(rec["vault_allocation"], 0.00)

        # Verify DB query reflects planned_capital = £2,457.53 and deployed_capital = £0.00
        fetched = db.get_v2_rotation_by_id(rotation_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["planned_capital"], 2457.53)
        self.assertEqual(fetched["deployed_capital"], 0.00)
        self.assertEqual(fetched["realised_net_pnl"], 0.00)

        # Cleanup
        with db.get_connection() as conn:
            conn.execute("DELETE FROM v2_rotations WHERE rotation_id = ?", (rotation_id,))
            conn.commit()

    # -------------------------------------------------------------------------
    # Invariant 25: Minimum 1p SDRT Enforcement & Canary Penny Attribution
    # -------------------------------------------------------------------------
    def test_25_small_order_sdrt_minimum_and_canary_reconciliation(self):
        """
        Verify that UK equity purchases enforce a minimum 1p (£0.01) SDRT charge,
        even on tiny transactions (e.g. 1 share of £1.13), preventing 1p ledger variance.
        """
        # 1. Test entry friction enforces 1p minimum SDRT on tiny UK trades
        friction = self.v2.compute_entry_friction(nominal_capital=1.13, is_uk=True, is_foreign=False)
        self.assertEqual(friction["sdrt"], 0.01)
        self.assertGreaterEqual(friction["total_entry_friction"], 0.01)

        # 2. Test entry friction on sub-£1 UK trades still enforces 1p minimum SDRT
        friction_tiny = self.v2.compute_entry_friction(nominal_capital=0.50, is_uk=True, is_foreign=False)
        self.assertEqual(friction_tiny["sdrt"], 0.01)

        # 3. Non-UK trades have £0.00 SDRT
        friction_us = self.v2.compute_entry_friction(nominal_capital=1.13, is_uk=False, is_foreign=True)
        self.assertEqual(friction_us["sdrt"], 0.00)

        # 4. Transaction-specific reconciliation arithmetic
        gross_pnl = 0.00
        entry_sdrt = 0.01
        exit_costs = 0.00
        total_costs = entry_sdrt + exit_costs
        realised_net_pnl = gross_pnl - total_costs
        self.assertEqual(realised_net_pnl, -0.01)

        # Cash delta: debit £1.14 on entry, credit £1.13 on exit = -£0.01
        cash_delta = round(1.13 - 1.14, 2)
        variance = round(abs(cash_delta - realised_net_pnl), 4)
        self.assertEqual(variance, 0.00)


if __name__ == "__main__":
    unittest.main()
