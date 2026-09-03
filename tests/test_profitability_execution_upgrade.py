"""
🏛️ PRV CAPITAL | COMPREHENSIVE PROFITABILITY & EXECUTION UPGRADE TEST SUITE
Validates all 20 requirements of the Profitability & Execution Upgrade Directive:
1. NAV & Balance Sheet Reconciliation (6 Invariants)
2. True Net P&L Accounting (Broker fees, SDRT, FX, SEC fees, Spread, Slippage)
3. Hard Net Edge Gate & "Why Not Trade?" Gating
4. Cost / Expected Profit Ratio (<30% ceiling)
5. Net Expectancy & Payoff Distribution
6. Net Capital-Time Efficiency (% / day)
7. Formal Dead Capital & 1.50% Net Recycling Hurdle
8. Unified Conviction Engine (Zero Contradictions)
9. Order Execution Telemetry & Marketable Limits
10. 4-Way Parallel Shadow Strategy Benchmark (A, B, C, D)
11. Master PDF & Daily Report Reconciliation Status
"""
import unittest
import os
from src.database.db import db
from src.portfolio.portfolio_snapshot import portfolio_snapshot
from src.execution.cost_model import cost_model
from src.execution.net_edge_gate import net_edge_gate
from src.analytics.unified_conviction_engine import unified_conviction_engine
from src.analytics.expectancy_engine import expectancy_engine
from src.portfolio.dead_capital_manager import dead_capital_manager
from src.analytics.shadow_portfolio_engine import shadow_portfolio_engine
from src.execution.order_router import order_router
from src.reporting.master_pdf_generator import master_pdf_generator
from src.reporting.daily_executive_report import daily_report_service


class TestProfitabilityExecutionUpgrade(unittest.TestCase):

    def setUp(self):
        from src.execution.order_state_machine import portfolio_reservations
        portfolio_reservations.reset()

    def test_nav_reconciliation_and_invariants(self):
        """Test authoritative snapshot verifies all 6 balance sheet invariants."""
        snap = portfolio_snapshot.get_authoritative_snapshot()
        acc = snap["account_summary"]
        positions = snap["positions"]

        self.assertTrue(snap["is_reconciled"])
        self.assertEqual(snap["reconciliation_status"], "VERIFIED")
        self.assertEqual(len(snap["failed_invariants"]), 0)

        # Invariant 1: Sum of market values equals invested capital
        market_sum = sum(p["market_value_gbp"] for p in positions)
        self.assertLessEqual(abs(market_sum - acc["invested_capital"]), 0.05)

        # Invariant 2: Cash + Invested Capital == Total NAV
        self.assertLessEqual(abs((acc["free_cash"] + acc["invested_capital"]) - acc["total_nav"]), 0.05)

        # Invariant 3: Position count equals unique positions
        self.assertEqual(len(positions), acc["active_holdings_count"])
        self.assertEqual(len({p["symbol"] for p in positions}), len(positions))

        # Invariant 4: Sum of weights matches invested percentage
        sum_weights = sum(p["weight_pct"] for p in positions)
        self.assertLessEqual(abs(sum_weights - acc["invested_pct"]), 0.20)

        # Invariant 5: Non-empty valid holding quantities
        for p in positions:
            self.assertGreater(p["quantity"], 0)
            self.assertGreater(p["market_value_gbp"], 0)
            self.assertGreater(p["average_price_gbp"], 0)
            self.assertGreater(p["current_price_gbp"], 0)

    def test_institutional_cost_model_and_taxes(self):
        """Test true net P&L accounting with UK SDRT, FX fees, SEC charges, and spread/slippage."""
        # 1. UK Equity Buy (£2,500 buy in SHEL)
        uk_buy = cost_model.calculate_trade_friction(
            nominal_value=2500.0,
            is_buy=True,
            is_uk=True,
            is_foreign=False
        )
        self.assertEqual(uk_buy["stamp_duty"], 12.50)   # 0.50% SDRT
        self.assertEqual(uk_buy["fx_cost"], 0.0)
        self.assertEqual(uk_buy["spread_cost"], 1.50)    # 6 bps half spread
        self.assertEqual(uk_buy["slippage_cost"], 2.50)  # 10 bps slippage
        self.assertEqual(uk_buy["total_friction"], 16.50)

        # 2. US Equity Buy (£2,500 buy in CRM)
        us_buy = cost_model.calculate_trade_friction(
            nominal_value=2500.0,
            is_buy=True,
            is_uk=False,
            is_foreign=True
        )
        self.assertEqual(us_buy["stamp_duty"], 0.0)
        self.assertEqual(us_buy["fx_cost"], 3.75)       # 0.15% T212 FX fee
        self.assertEqual(us_buy["spread_cost"], 1.00)   # 4 bps half spread
        self.assertEqual(us_buy["slippage_cost"], 2.50) # 10 bps slippage
        self.assertEqual(us_buy["total_friction"], 7.25)

        # 3. Round-Trip Net Realized P&L Calculation
        # £2,500 entry -> £2,700 exit (+£200 gross gain) on US stock
        net_calc = cost_model.compute_net_realized_pnl(
            gross_entry_value=2500.0,
            gross_exit_value=2700.0,
            is_uk=False,
            is_foreign=True
        )
        self.assertEqual(net_calc["gross_profit_loss"], 200.00)
        self.assertGreater(net_calc["total_transaction_costs"], 0)
        self.assertEqual(net_calc["net_realized_pnl"], round(200.00 - net_calc["total_transaction_costs"], 2))
        self.assertLess(net_calc["cost_as_pct_of_gross_profit"], 30.0)

    def test_hard_net_edge_gate_and_rejections(self):
        """Test Hard Net Edge Gate filters marginal trades and enforces Hold Cash."""
        # 1. Marginal Setup where friction destroys profit -> REJECT to HOLD CASH
        # Entry: 100, Target: 100.50 (+0.5% gross), Stop: 99.00 (-1.0%), Nominal: £2,000 UK stock
        gate_fail = net_edge_gate.evaluate_candidate(
            symbol="TEST_FAIL",
            entry_price=100.0,
            target_price=100.50,
            stop_loss_price=99.00,
            nominal_value=2000.0,
            is_uk=True,
            is_foreign=False
        )
        self.assertFalse(gate_fail["approved"])
        self.assertEqual(gate_fail["action"], "HOLD CASH")
        self.assertGreater(len(gate_fail["rejection_reasons"]), 0)
        self.assertTrue(any("Net expected return is negative/zero" in r or "Cost-to-Expected-Profit" in r for r in gate_fail["rejection_reasons"]))

        # 2. Wide Spread Setup (60 bps spread) -> REJECT
        gate_spread_fail = net_edge_gate.evaluate_candidate(
            symbol="WIDE_SPREAD",
            entry_price=100.0,
            target_price=108.0,
            stop_loss_price=97.5,
            nominal_value=2500.0,
            is_uk=False,
            is_foreign=True,
            current_spread_pct=0.0060 # 60 bps (breaches 50 bps ceiling)
        )
        self.assertFalse(gate_spread_fail["approved"])
        self.assertTrue(any("Bid-ask spread" in r or "liquidity circuit breaker" in r for r in gate_spread_fail["rejection_reasons"]))

        # 3. High-Conviction Institutional Setup -> APPROVE
        # Entry: 280, Target: 305 (+8.9%), Stop: 272 (-2.86%), Nominal: £2,500
        gate_pass = net_edge_gate.evaluate_candidate(
            symbol="CRM",
            entry_price=280.0,
            target_price=305.0,
            stop_loss_price=272.0,
            nominal_value=2500.0,
            is_uk=False,
            is_foreign=True,
            current_spread_pct=0.0004,
            fundamental_score=85.0,
            technical_score=80.0
        )
        self.assertTrue(gate_pass["approved"])
        self.assertEqual(gate_pass["action"], "BUY")
        self.assertGreater(gate_pass["predicted_net_return_pct"], 0)
        self.assertGreaterEqual(gate_pass["net_reward_risk"], 2.0)
        self.assertLessEqual(gate_pass["cost_to_profit_pct"], 30.0)

    def test_unified_conviction_engine_consistency(self):
        """Test Unified Conviction Engine produces non-contradictory thesis and working classifications."""
        snap = portfolio_snapshot.get_authoritative_snapshot()
        convictions = unified_conviction_engine.get_all_holdings_convictions()
        self.assertEqual(len(convictions), len(snap["positions"]))

        for c in convictions:
            self.assertGreaterEqual(c["conviction_score"], 0.0)
            self.assertIn(c["thesis_status"], ["STRENGTHENING", "UNCHANGED", "DETERIORATING"])
            self.assertIn(c["working"], ["YES", "NO"])
            self.assertIn(c["buy_again"], ["YES", "NO"])
            self.assertGreater(c["net_capital_efficiency"], 0.0)

            # Rule: Strongest convictions must not contradict buy_again without documented reason
            if c["conviction_score"] >= 85.0 and c["thesis_status"] == "STRENGTHENING":
                self.assertEqual(c["buy_again"], "YES")

    def test_net_expectancy_and_capital_time_efficiency(self):
        """Test Net Expectancy, Profit Factor, and Capital-Time Efficiency math."""
        closed_sample = [
            {"action": "SELL", "net_realized_pnl": 120.0, "holding_period_days": 10, "mfe": 6.0, "mae": 1.5},
            {"action": "SELL", "net_realized_pnl": 85.0, "holding_period_days": 12, "mfe": 5.2, "mae": 1.8},
            {"action": "SELL", "net_realized_pnl": -40.0, "holding_period_days": 8, "mfe": 1.0, "mae": 2.5},
            {"action": "SELL", "net_realized_pnl": 95.0, "holding_period_days": 14, "mfe": 5.8, "mae": 1.2},
            {"action": "SELL", "net_realized_pnl": -35.0, "holding_period_days": 7, "mfe": 0.8, "mae": 2.4}
        ]
        metrics = expectancy_engine.compute_expectancy_metrics(closed_sample)
        self.assertEqual(metrics["trade_count"], 5)
        self.assertEqual(metrics["win_count"], 3)
        self.assertEqual(metrics["loss_count"], 2)
        self.assertEqual(metrics["win_rate_pct"], 60.0)
        self.assertGreater(metrics["net_expectancy_gbp"], 0)
        self.assertGreater(metrics["profit_factor"], 1.0)

        # Capital efficiency calculation
        cap_eff = expectancy_engine.calculate_capital_efficiency(
            predicted_net_return_pct=5.60,
            expected_holding_days=14
        )
        self.assertEqual(cap_eff["net_capital_efficiency_per_day"], 0.40)
        self.assertEqual(cap_eff["annualized_capital_efficiency_pct"], 100.80)

    def test_formal_dead_capital_hurdle_and_recycling(self):
        """Test formal Dead Capital standard requires positive net advantage after switching costs."""
        # 1. Holding with intact thesis and positive remaining return -> NOT dead capital
        intact_eval = dead_capital_manager.evaluate_position_recycling(
            holding_symbol="EXPN",
            holding_days_active=6,
            unrealized_pnl_pct=2.08
        )
        self.assertFalse(intact_eval["is_dead_capital"])
        self.assertEqual(intact_eval["recommendation"], "MAINTAIN EXPOSURE")

        # 2. Holding evaluation
        deteriorated_eval = dead_capital_manager.evaluate_position_recycling(
            holding_symbol="PM",
            holding_days_active=30,
            unrealized_pnl_pct=-2.5
        )
        self.assertIn("switching_cost_gbp", deteriorated_eval)
        self.assertGreater(deteriorated_eval["switching_cost_gbp"], 0)

    def test_four_way_shadow_strategy_platform(self):
        """Test 4-way parallel shadow strategy benchmarking and SQLite persistence."""
        shadow_eval = shadow_portfolio_engine.evaluate_shadow_comparison()
        strats = shadow_eval["strategies"]

        self.assertEqual(len(strats), 4)
        ids = [s["strategy_id"] for s in strats]
        self.assertEqual(ids, ["STRATEGY_A", "STRATEGY_B", "STRATEGY_C", "STRATEGY_D"])

        # Verify Strategy D (Full net edge + capital efficiency) outperforms Strategy A (Baseline)
        strat_a = next(s for s in strats if s["strategy_id"] == "STRATEGY_A")
        strat_d = next(s for s in strats if s["strategy_id"] == "STRATEGY_D")

        self.assertGreater(strat_d["net_expectancy"], strat_a["net_expectancy"])
        self.assertGreater(strat_d["profit_factor"], strat_a["profit_factor"])
        self.assertLess(strat_d["cost_to_gross_profit_ratio"], strat_a["cost_to_gross_profit_ratio"])

        # Verify SQLite persistence
        db_entries = db.get_shadow_strategy_ledger()
        self.assertGreater(len(db_entries), 0)

    def test_order_telemetry_and_marketable_limits(self):
        """Test order routing records full execution telemetry and price controls."""
        from unittest.mock import patch
        with patch("src.portfolio.daily_objective_service.daily_objective_service.get_daily_status", return_value={"new_discretionary_entries_allowed": True, "gate_reason": "CLEAR", "sizing_multiplier": 1.0, "emergency_risk_mode": False}):
            success, msg, data = order_router.route_entry_order(
                symbol="CRM",
                t212_ticker="CRM_US_EQ",
                quantity=10.0,
                price=280.0,
                target_price=305.0,
                stop_loss_price=272.0,
                sector="Technology",
                confidence_score=85.0,
                market_regime="STRONG_BULL",
                agent_votes={"Trend": "BUY", "Momentum": "BUY"},
                risk_approved=True,
                is_paper=True,
                bypass_market_hours=True
            )
            self.assertTrue(success)
        telemetry = db.get_order_telemetry_entries(limit=5)
        self.assertGreater(len(telemetry), 0)
        latest = telemetry[0]
        self.assertEqual(latest["symbol"], "CRM")
        self.assertEqual(latest["order_type"], "MARKETABLE_LIMIT")
        self.assertIn(latest["status"], ["FILLED", "SIMULATED_FILLED"])

    def test_master_pdf_and_report_reconciliation_integrity(self):
        """Test Master PDF and Daily Executive Report generate with 100% verified reconciliation."""
        # 1. Master PDF
        pdf_path = master_pdf_generator.generate_daily_master_pdf()
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 1000)

        # 2. Daily Executive Report
        rep = daily_report_service.generate_daily_report()
        self.assertEqual(rep["reconciliation_status"], "VERIFIED")
        self.assertTrue(rep["is_reconciled"])
        self.assertGreater(rep["portfolio_summary"]["nav"], 0)
        self.assertGreater(rep["portfolio_summary"]["free_cash"], 0)
        self.assertGreaterEqual(rep["portfolio_summary"]["invested"], 0)
        snap = portfolio_snapshot.get_authoritative_snapshot()
        self.assertEqual(len(rep["open_positions"]), len(snap["positions"]))

    def test_instrument_specific_cost_exemptions(self):
        """Test instrument-specific cost rules: ETF/AIM SDRT exemptions, PTM levy, US SEC sell-only."""
        # 1. UK ETF Buy (£5,000 in CSPX) -> SDRT is EXEMPT
        etf_buy = cost_model.calculate_trade_friction(
            nominal_value=5000.0,
            is_buy=True,
            is_uk=True,
            is_foreign=False,
            instrument_type="ETF"
        )
        self.assertEqual(etf_buy["stamp_duty"], 0.0) # Exempt
        self.assertEqual(etf_buy["ptm_levy"], 0.0)

        # 2. UK AIM Share Buy (£3,000 in AIM stock) -> SDRT is EXEMPT
        aim_buy = cost_model.calculate_trade_friction(
            nominal_value=3000.0,
            is_buy=True,
            is_uk=True,
            is_foreign=False,
            instrument_type="AIM"
        )
        self.assertEqual(aim_buy["stamp_duty"], 0.0) # Exempt

        # 3. UK Qualifying Equity Buy > £10,000 (£15,000 in SHEL) -> 0.50% SDRT + £1.50 PTM
        large_uk_buy = cost_model.calculate_trade_friction(
            nominal_value=15000.0,
            is_buy=True,
            is_uk=True,
            is_foreign=False,
            instrument_type="EQUITY"
        )
        self.assertEqual(large_uk_buy["stamp_duty"], 75.00) # 0.50%
        self.assertEqual(large_uk_buy["ptm_levy"], 1.50)    # PTM Levy

        # 4. US Equity Sell (£3,000 in NVDA, 25 shares) -> SEC Section 31 + FINRA TAF + 0.15% FX
        us_sell = cost_model.calculate_trade_friction(
            nominal_value=3000.0,
            is_buy=False,
            is_uk=False,
            is_foreign=True,
            shares_count=25.0,
            instrument_type="EQUITY"
        )
        self.assertEqual(us_sell["stamp_duty"], 0.0)
        self.assertEqual(us_sell["fx_cost"], 4.50) # 0.15%
        self.assertGreater(us_sell["sec_fees"], 0.0)
        self.assertGreater(us_sell["finra_fees"], 0.0)

    def test_contextual_spread_gating_ratio(self):
        """Test contextual spread gating: allows wide spread on large moves, blocks tight spread on tiny moves."""
        # Case A: 21 bps spread on a 7.0% target move -> APPROVED (spread consumes 3.0% of profit <= 15% limit, Net R:R >= 2.0x)
        pass_wide = net_edge_gate.evaluate_candidate(
            symbol="WIDE_BUT_LARGE_TARGET",
            entry_price=100.0,
            target_price=107.0,
            stop_loss_price=98.0,
            nominal_value=2500.0,
            is_uk=False,
            is_foreign=True,
            current_spread_pct=0.0021 # 21 bps
        )
        self.assertTrue(pass_wide["approved"])
        self.assertEqual(pass_wide["action"], "BUY")

        # Case B: 18 bps spread on a 0.4% target move -> REJECTED (spread consumes 45% of profit > 15% limit)
        fail_tight = net_edge_gate.evaluate_candidate(
            symbol="TIGHT_BUT_TINY_TARGET",
            entry_price=100.0,
            target_price=100.4,
            stop_loss_price=99.8,
            nominal_value=2500.0,
            is_uk=False,
            is_foreign=True,
            current_spread_pct=0.0018 # 18 bps
        )
        self.assertFalse(fail_tight["approved"])
        self.assertEqual(fail_tight["action"], "HOLD CASH")
        self.assertTrue(any("spread friction" in r for r in fail_tight["rejection_reasons"]))

        # Case C: 60 bps spread on any move -> REJECTED (Emergency 50 bps liquidity circuit breaker)
        fail_emergency = net_edge_gate.evaluate_candidate(
            symbol="ILLIQUID_BREAKER",
            entry_price=100.0,
            target_price=110.0,
            stop_loss_price=95.0,
            nominal_value=2500.0,
            is_uk=False,
            is_foreign=True,
            current_spread_pct=0.0060 # 60 bps
        )
        self.assertFalse(fail_emergency["approved"])
        self.assertTrue(any("emergency liquidity circuit breaker" in r for r in fail_emergency["rejection_reasons"]))

    def test_implementation_shortfall_calculation(self):
        """Test Implementation Shortfall calculation decomposed into delay, spread, market impact, and fees."""
        shortfall = order_router.calculate_implementation_shortfall(
            decision_price=100.0,
            arrival_price=100.02, # 2 bps delay
            fill_price=100.05,    # 3 bps market impact
            quantity=50.0,
            nominal_value=5000.0,
            is_buy=True,
            is_uk=True,
            is_foreign=False,
            custom_spread_pct=0.0006 # 6 bps spread -> 3 bps half-spread
        )
        self.assertEqual(shortfall["delay_cost_bps"], 2.0)
        self.assertEqual(shortfall["spread_cost_bps"], 3.0)
        self.assertEqual(shortfall["market_impact_bps"], 3.0)
        self.assertGreater(shortfall["implementation_shortfall_bps"], 0.0)
        self.assertGreater(shortfall["implementation_shortfall_gbp"], 0.0)

    def test_snapshot_id_and_config_propagation(self):
        """Test that snapshot_id and configuration_version propagate identically across snapshot, daily report, and PDF."""
        snap = portfolio_snapshot.get_authoritative_snapshot()
        rep = daily_report_service.generate_daily_report(snapshot=snap)
        
        self.assertIn("snapshot_id", snap)
        self.assertIn("snapshot_id", rep)
        self.assertEqual(snap["snapshot_id"], rep["snapshot_id"])
        self.assertEqual(snap["configuration_version"], rep["configuration_version"])
        self.assertEqual(snap["reconciliation_status"], rep["reconciliation_status"])

    def test_invariant_6_pnl_continuity_bridge(self):
        """Test Invariant 6 P&L continuity bridge reconciles NAV delta with realized, unrealized, and fees."""
        snap = portfolio_snapshot.get_authoritative_snapshot(force_refresh=True)
        inv6 = snap["invariants_audit"]["inv6_pnl_continuity_bridge"]
        
        self.assertTrue(inv6["passed"])
        self.assertLessEqual(inv6["variance_gbp"], 0.10)
        self.assertEqual(inv6["starting_capital_gbp"], 50000.0)
        self.assertIsInstance(inv6["nav_delta_lhs_gbp"], (int, float))
        self.assertLessEqual(inv6["realized_gross_pnl_gbp"], 0.0)
        self.assertGreaterEqual(inv6["unrealized_pnl_gbp"], 0.0)
        self.assertGreaterEqual(inv6["uk_stamp_duty_taxes_gbp"], 0.0)
        self.assertGreaterEqual(inv6["fx_conversion_fees_gbp"], 0.0)

    def test_2026_regulatory_fee_schedule_constants(self):
        """Test authoritative 2026 SEC Section 31 and FINRA TAF fee schedule."""
        from src.config.settings import settings
        self.assertEqual(settings.SEC_SECTION_31_RATE, 0.0000206) # $20.60 per $1,000,000
        self.assertEqual(settings.FINRA_TAF_PER_SHARE, 0.000195)  # $0.000195 per share
        self.assertEqual(settings.FINRA_TAF_MAX_FEE, 9.79)        # $9.79 cap per trade
        
        # Verify effective-dated fee registry
        schedule = cost_model.get_effective_fee_schedule()
        fee_types = {f["fee_type"] for f in schedule}
        self.assertTrue({"FINRA_TAF", "SEC_SECTION_31", "UK_SDRT", "PTM_LEVY", "T212_FX_FEE"}.issubset(fee_types))

    def test_42_trade_shadow_dataset_expectancy_and_profit_factor_reconciliation(self):
        """Test that all 4 shadow strategies compute expectancy and profit factor strictly bottom-up with zero math mismatch."""
        from src.analytics.shadow_dataset import shadow_dataset_service
        ledger = shadow_dataset_service.generate_full_42_trade_ledger()
        self.assertEqual(len(ledger), 42)
        
        for s_key in ["strategy_A_decision", "strategy_B_decision", "strategy_C_decision", "strategy_D_decision"]:
            summary = shadow_dataset_service.compute_strategy_summary(s_key)
            self.assertEqual(summary["signals_evaluated"], 42)
            self.assertEqual(summary["accepted_trades"] + summary["rejected_trades"], 42)
            
            # Mathematical identity: Expectancy (sum/N) == P(win)*AvgWin - P(loss)*AvgLoss
            self.assertLessEqual(abs(summary["net_expectancy_per_trade"] - summary["reconciled_expectancy"]), 0.02)
            
            # Profit factor identity: sum_wins / sum_losses
            if summary["sum_net_losses"] > 0:
                expected_pf = round(summary["sum_net_wins"] / summary["sum_net_losses"], 2)
                self.assertLessEqual(abs(summary["profit_factor"] - expected_pf), 0.02)

    def test_2026_ptm_levy_150p_and_exemption_rules(self):
        """Test Takeover Panel PTM levy 150p (£1.50) on trades > £10,000 and exemptions on ETFs/AIM/US."""
        # 1. UK qualifying equity buy > £10k (£15,000 buy in SHEL)
        uk_large_buy = cost_model.calculate_trade_friction(
            nominal_value=15000.0,
            is_buy=True,
            is_uk=True,
            is_foreign=False,
            instrument_type="EQUITY"
        )
        self.assertEqual(uk_large_buy["ptm_levy"], 1.50) # 150p PTM levy
        self.assertEqual(uk_large_buy["stamp_duty"], 75.0) # 0.50% SDRT

        # 2. UK qualifying equity buy <= £10k (£5,000 buy in AZN)
        uk_small_buy = cost_model.calculate_trade_friction(
            nominal_value=5000.0,
            is_buy=True,
            is_uk=True,
            is_foreign=False,
            instrument_type="EQUITY"
        )
        self.assertEqual(uk_small_buy["ptm_levy"], 0.0) # Exempt below £10k

        # 3. UK ETF buy > £10k (£15,000 in CSPX)
        uk_etf_large = cost_model.calculate_trade_friction(
            nominal_value=15000.0,
            is_buy=True,
            is_uk=True,
            is_foreign=False,
            instrument_type="ETF"
        )
        self.assertEqual(uk_etf_large["ptm_levy"], 0.0) # ETFs exempt from PTM & SDRT
        self.assertEqual(uk_etf_large["stamp_duty"], 0.0)

    def test_financial_cost_self_reconciliation_assertion(self):
        """Test that sum of cost components equals total friction for all calculated transactions."""
        # Test across UK, US, ETF, and AIM instruments
        for test_case in [
            {"nominal": 2500.0, "is_buy": True, "is_uk": True, "is_foreign": False, "type": "EQUITY"},
            {"nominal": 2500.0, "is_buy": False, "is_uk": True, "is_foreign": False, "type": "EQUITY"},
            {"nominal": 2500.0, "is_buy": True, "is_uk": False, "is_foreign": True, "type": "EQUITY"},
            {"nominal": 2500.0, "is_buy": False, "is_uk": False, "is_foreign": True, "type": "EQUITY"},
            {"nominal": 12000.0, "is_buy": True, "is_uk": True, "is_foreign": False, "type": "EQUITY"}
        ]:
            f = cost_model.calculate_trade_friction(
                nominal_value=test_case["nominal"],
                is_buy=test_case["is_buy"],
                is_uk=test_case["is_uk"],
                is_foreign=test_case["is_foreign"],
                instrument_type=test_case["type"]
            )
            component_sum = round(
                f["broker_fees"] + f["taxes"] + f["fx_cost"] + f["regulatory_fees"] + f["spread_cost"] + f["slippage_cost"],
                2
            )
            self.assertEqual(component_sum, round(f["total_friction"], 2))

    def test_portfolio_opportunity_allocator_dual_regime(self):
        """Test Dual-Regime Portfolio Opportunity Allocator under Scarce vs Abundant capital modes."""
        from src.analytics.portfolio_opportunity_allocator import portfolio_opportunity_allocator
        res = portfolio_opportunity_allocator.evaluate_dual_regime_allocation(
            starting_nav=50000.0,
            current_free_cash=24029.20
        )
        self.assertEqual(res["recommended_allocation_mode"], "CAPITAL_ABUNDANT")
        self.assertGreater(res["capital_abundant_results"]["net_pnl_gbp"], res["capital_scarce_results"]["net_pnl_gbp"])
        self.assertGreater(res["capital_scarce_results"]["net_expectancy_per_trade_gbp"], res["capital_abundant_results"]["net_expectancy_per_trade_gbp"])
        self.assertGreaterEqual(res["capital_scarce_results"]["annualized_capital_efficiency_pct"], 200.0)

    def test_out_of_sample_untouched_validation(self):
        """Test untouched 40-signal out-of-sample dataset execution and anti-lookahead provenance."""
        from src.analytics.oos_validation_engine import oos_validation_engine
        ledger = oos_validation_engine.generate_oos_trade_ledger()
        self.assertEqual(len(ledger), 40)
        
        # Verify provenance and anti-lookahead checks
        for t in ledger:
            p = t["provenance"]
            self.assertTrue(p["lookahead_audit_passed"])
            self.assertLessEqual(p["source_bar_timestamp"], p["signal_timestamp"])
            self.assertIn("signal_hash", p)
            self.assertGreater(len(p["signal_hash"]), 8)

        # Bottom-up summary evaluation
        summary_d = oos_validation_engine.compute_oos_strategy_summary("strategy_D_decision")
        self.assertEqual(summary_d["validation_tier"], "OUT_OF_SAMPLE_VALIDATION")
        self.assertGreaterEqual(summary_d["win_rate_pct"], 75.0)
        self.assertGreaterEqual(summary_d["profit_factor"], 8.0)
        self.assertLessEqual(abs(summary_d["net_expectancy_per_trade"] - summary_d["reconciled_expectancy"]), 0.02)

    def test_walk_forward_multi_window_matrix(self):
        """Test rolling 3-window walk-forward validation matrix."""
        from src.analytics.walk_forward_engine import walk_forward_engine
        wf_res = walk_forward_engine.evaluate_walk_forward_matrix()
        self.assertEqual(len(wf_res["windows"]), 3)
        self.assertIn("median_summary", wf_res)
        self.assertGreaterEqual(wf_res["median_summary"]["strategy_D_capital_hurdle"]["median_win_rate_pct"], 80.0)
        self.assertGreaterEqual(wf_res["median_summary"]["strategy_D_capital_hurdle"]["median_expectancy_gbp"], 60.0)

    def test_parameter_manifest_and_sha256_hash(self):
        """Test immutable parameter manifest contains all Strategy D & cash reserve parameters with deterministic hash."""
        from src.config.settings import settings
        manifest = settings.generate_parameter_manifest()
        manifest_hash = settings.get_parameter_manifest_hash()
        
        self.assertIn("required_cash_reserve_pct", manifest)
        self.assertEqual(manifest["required_cash_reserve_pct"], 45.0)
        self.assertIn("max_expected_holding_period_days", manifest)
        self.assertEqual(manifest["max_expected_holding_period_days"], 14)
        self.assertIn("fundamental_velocity_threshold", manifest)
        self.assertEqual(manifest["fundamental_velocity_threshold"], 70.0)
        self.assertIn("capital_efficiency_min_score", manifest)
        self.assertEqual(manifest["capital_efficiency_min_score"], 70.0)
        self.assertEqual(manifest["ptm_levy_amount_gbp"], 1.50)
        
        self.assertEqual(len(manifest_hash), 64) # Valid SHA-256 hash
        self.assertEqual(manifest_hash, settings.get_parameter_manifest_hash())

    def test_security_level_ptm_levy_and_aim_rules(self):
        """Test Takeover Panel PTM levy applies to UK companies on AIM MTF > £10k, but exempts ETFs and US issuers."""
        # 1. UK incorporated company on AIM MTF > £10k (£12,000 in ASOS / BOO)
        aim_uk_large = cost_model.evaluate_ptm_levy_applicability(
            nominal_value=12000.0,
            instrument_type="EQUITY",
            issuer_jurisdiction="UK",
            venue="AIM_MTF"
        )
        self.assertTrue(aim_uk_large["ptm_applicable"])
        self.assertEqual(aim_uk_large["ptm_levy_amount"], 1.50) # 150p flat levy

        # 2. UK company on AIM MTF <= £10k (£4,000)
        aim_uk_small = cost_model.evaluate_ptm_levy_applicability(
            nominal_value=4000.0,
            instrument_type="EQUITY",
            issuer_jurisdiction="UK",
            venue="AIM_MTF"
        )
        self.assertTrue(aim_uk_small["ptm_applicable"])
        self.assertEqual(aim_uk_small["ptm_levy_amount"], 0.0) # Exempt below £10k threshold

        # 3. ETF on LSE > £10k (£15,000 in CSPX)
        etf_eval = cost_model.evaluate_ptm_levy_applicability(
            nominal_value=15000.0,
            instrument_type="ETF",
            issuer_jurisdiction="UK",
            venue="LSE_MAIN"
        )
        self.assertFalse(etf_eval["ptm_applicable"])
        self.assertEqual(etf_eval["ptm_levy_amount"], 0.0) # Categorically exempt

        # 4. US issuer on NYSE > £10k (£15,000 in CRM)
        us_eval = cost_model.evaluate_ptm_levy_applicability(
            nominal_value=15000.0,
            instrument_type="EQUITY",
            issuer_jurisdiction="US",
            venue="NYSE"
        )
        self.assertFalse(us_eval["ptm_applicable"])
        self.assertEqual(us_eval["ptm_levy_amount"], 0.0) # Non-UK venue/jurisdiction

    def test_full_universe_replay_funnel_and_point_in_time_provenance(self):
        """Test Full Universe historical scanning replay across 103 securities and Point-in-Time provenance."""
        from src.analytics.full_universe_replay_engine import full_universe_replay_engine
        res = full_universe_replay_engine.replay_holdout_universe_scan()
        
        self.assertEqual(res["dataset_classification"], "VALIDATION / HOLDOUT (UNTOUCHED)")
        self.assertFalse(res["is_touched"])
        self.assertEqual(res["total_universe_securities"], 103)
        self.assertEqual(res["trading_days_scanned"], 45)
        self.assertGreaterEqual(res["total_security_evaluations"], 4500)
        self.assertGreaterEqual(res["total_security_evaluations"], 4500)
        
        funnel = res["funnel_summary"]
        self.assertGreater(funnel["raw_technical_candidates"], 0)
        self.assertGreater(funnel["fundamental_velocity_failures"], 0)
        self.assertGreater(funnel["cost_and_net_edge_failures"], 0)
        self.assertGreater(funnel["strategy_B_net_edge_approved"], 0)

    def test_event_driven_50k_portfolio_simulator(self):
        """Test Event-Driven £50,000 portfolio replay enforcing 45% cash preservation floor and position caps."""
        from src.analytics.event_driven_portfolio_simulator import event_driven_portfolio_simulator
        res_b = event_driven_portfolio_simulator.run_portfolio_replay("strategy_B_decision")
        
        self.assertEqual(res_b["starting_nav_gbp"], 50000.0)
        self.assertGreater(res_b["ending_nav_gbp"], 50000.0)
        self.assertGreaterEqual(res_b["win_rate_pct"], 80.0)
        self.assertGreaterEqual(res_b["profit_factor"], 8.0)
        self.assertLessEqual(res_b["max_portfolio_drawdown_pct"], 1.0)
        self.assertFalse(res_b["cash_preservation_floor_breached"])
        self.assertGreater(res_b["capital_days_metrics"]["net_bps_per_capital_day"], 40.0)

    def test_stress_monte_carlo_block_bootstrap_and_quad_stress(self):
        """Test 10,000-iteration Block Bootstrap and adversarial stress matrix."""
        from src.analytics.stress_monte_carlo_engine import stress_monte_carlo_engine
        
        # 1. Block Bootstrap
        bb_res = stress_monte_carlo_engine.run_block_bootstrap("strategy_B_decision", horizon_trades=50)
        self.assertEqual(bb_res["iterations"], 10000)
        self.assertEqual(bb_res["block_size_trades"], 5)
        self.assertGreater(bb_res["net_expectancy_ci_95"]["p2_5_lower_bound_gbp"], 40.0)
        self.assertIn("0 of 10000", bb_res["empirical_sample_frequency"]["negative_expectancy_occurrences"])

        # 2. Adversarial Stress Matrix
        matrix = stress_monte_carlo_engine.evaluate_adversarial_stress_matrix()
        strat_b_stress = matrix["strategy_B_decision"]
        self.assertGreater(strat_b_stress["compound_quad_stress"]["net_profit_gbp"], 2000.0)
        self.assertGreater(strat_b_stress["compound_quad_stress"]["profit_factor"], 4.0)
        self.assertLessEqual(strat_b_stress["compound_quad_stress"]["max_drawdown_pct"], 1.0)


if __name__ == "__main__":
    unittest.main()
