"""
🏛️ PRV CAPITAL | SIMULATOR FOUNDATION INDEPENDENT VERIFICATION SUITE
Validates all 9 core requirements of the research laboratory foundation:
A. Data ingestion & normalization
B. Monotonic chronological replay clock
C. Point-in-time information boundary (Zero lookahead guarantee)
D. Versioned transaction-cost engine integration
E. Realistic execution/fill simulator (next-bar fills, limit/stop rules)
F. Portfolio double-entry cash and position ledger (exact reconciliation)
G. Deterministic reproducibility (byte-for-byte identical ledger hash)
H. OOS cryptographic sealing and access violation enforcement
I. Benchmark & control framework evaluation
J. Practice account safety invariant (clean £50,000 completely untouched)
"""
import unittest
from datetime import datetime, date
import pandas as pd
import numpy as np

from src.research.clock import ReplayClock, ReplayClockViolationError
from src.research.pit_boundary import PointInTimeBoundary, CatalystEvent, LookAheadViolationError
from src.research.cost_schedule import CostScheduleRepository, Jurisdiction, InstrumentClass, FeeType
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType
from src.research.portfolio_ledger import PortfolioLedger, LedgerDiscrepancyError
from src.research.oos_sealer import OOSSealer, OOSAccessViolationError, PartitionType
from src.research.benchmarks import BenchmarkEvaluator
from src.research.simulation_engine import SimulationEngine
from src.config.settings import settings


class TestSimulatorFoundation(unittest.TestCase):
    def setUp(self):
        # Create a clean synthetic dataset for rigorous invariant testing
        dates = pd.date_range("2024-01-01 09:30", periods=50, freq="5min")
        self.timeline = list(dates)
        
        # Price path: 100 -> 105 -> 98 -> 102
        np.random.seed(42)
        base_price = 100.0
        prices = [base_price]
        for _ in range(49):
            step = np.random.normal(0.1, 0.5)
            prices.append(prices[-1] + step)
            
        data = {
            "Open": prices,
            "High": [p + 0.3 for p in prices],
            "Low": [p - 0.3 for p in prices],
            "Close": [p + 0.1 for p in prices],
            "Volume": [100000.0] * 50
        }
        self.df_synthetic = pd.DataFrame(data, index=dates)

    # ---------------------------------------------------------
    # A & B. REPLAY CLOCK INVARIANTS
    # ---------------------------------------------------------
    def test_clock_monotonic_advance_and_backward_rejection(self):
        clock = ReplayClock(self.timeline)
        self.assertEqual(clock.current_time, self.timeline[0])
        self.assertFalse(clock.is_completed)

        # Advance one step
        next_t = clock.advance()
        self.assertEqual(next_t, self.timeline[1])
        self.assertEqual(clock.current_time, self.timeline[1])

        # Advance to specific future time
        clock.advance_to(self.timeline[10])
        self.assertEqual(clock.current_time, self.timeline[10])

        # Invariant: Backward time jump must raise ReplayClockViolationError
        with self.assertRaises(ReplayClockViolationError):
            clock.advance_to(self.timeline[5])

    # ---------------------------------------------------------
    # C. POINT-IN-TIME INFORMATION BOUNDARY INVARIANTS
    # ---------------------------------------------------------
    def test_pit_boundary_blocks_future_data(self):
        boundary = PointInTimeBoundary()
        boundary.register_market_data("TEST_SYM", self.df_synthetic)

        current_time = self.timeline[10]

        # Query up to current_time: must only return bars <= timeline[10]
        visible_bars = boundary.get_bars_up_to("TEST_SYM", current_time)
        self.assertEqual(len(visible_bars), 11)
        self.assertTrue(visible_bars.index[-1] <= current_time)

        # Invariant: Attempting to query future bar via integrity check must fail
        future_time = self.timeline[15]
        with self.assertRaises(LookAheadViolationError):
            boundary.verify_query_integrity(future_time, current_time)

    def test_pit_catalyst_visibility(self):
        boundary = PointInTimeBoundary()
        event_early = CatalystEvent("E1", "TEST_SYM", "EARNINGS", self.timeline[5], {"eps": 1.5})
        event_future = CatalystEvent("E2", "TEST_SYM", "GUIDANCE", self.timeline[15], {"rev": 100e6})
        boundary.register_catalysts("TEST_SYM", [event_early, event_future])

        # At timeline[10], only event_early is visible
        visible = boundary.get_catalysts_up_to("TEST_SYM", self.timeline[10])
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].event_id, "E1")

        # At timeline[20], both are visible
        visible_all = boundary.get_catalysts_up_to("TEST_SYM", self.timeline[20])
        self.assertEqual(len(visible_all), 2)

    # ---------------------------------------------------------
    # D & E. EXECUTION & COST ENGINE INTEGRATION INVARIANTS
    # ---------------------------------------------------------
    def test_execution_next_bar_fill_and_cost_accounting(self):
        cost_repo = CostScheduleRepository()
        sim = ExecutionSimulator(cost_repo)

        order_time = self.timeline[2]
        fill_time = self.timeline[3]
        execution_bar = self.df_synthetic.loc[fill_time]

        # US Equity Market Buy Order
        order = Order(
            order_id="ORD_001",
            symbol="NVDA",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100.0,
            created_at=order_time,
            jurisdiction=Jurisdiction.US,
            instrument_class=InstrumentClass.EQUITY
        )

        fill = sim.simulate_fill(order, execution_bar, fill_time, gbpusd_rate=1.30)
        self.assertIsNotNone(fill)
        self.assertEqual(fill.fill_time, fill_time)
        # Verify execution price equals the Open of the execution bar
        self.assertAlmostEqual(fill.fill_price_gbp, float(execution_bar["Open"]) / 1.30, places=3)
        
        # Verify 0.15% FX fee was itemized
        self.assertIn("buy_fx_gbp", fill.itemized_frictions)
        self.assertGreater(fill.itemized_frictions["buy_fx_gbp"], 0.0)

    def test_execution_limit_order_boundary_rules(self):
        cost_repo = CostScheduleRepository()
        sim = ExecutionSimulator(cost_repo)
        bar = self.df_synthetic.iloc[5]
        bar_low = float(bar["Low"])

        # Limit order with price below bar low -> does NOT fill
        unfilled_order = Order(
            order_id="ORD_UNFILLED",
            symbol="NVDA",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=50.0,
            created_at=self.timeline[4],
            limit_price=bar_low - 1.0,
            jurisdiction=Jurisdiction.US
        )
        self.assertIsNone(sim.simulate_fill(unfilled_order, bar, self.timeline[5]))

        # Limit order with price above bar low -> DOES fill
        filled_order = Order(
            order_id="ORD_FILLED",
            symbol="NVDA",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=50.0,
            created_at=self.timeline[4],
            limit_price=bar_low + 0.5,
            jurisdiction=Jurisdiction.US
        )
        fill = sim.simulate_fill(filled_order, bar, self.timeline[5])
        self.assertIsNotNone(fill)
        self.assertEqual(fill.order_id, "ORD_FILLED")

    # ---------------------------------------------------------
    # F. PORTFOLIO DOUBLE-ENTRY LEDGER RECONCILIATION
    # ---------------------------------------------------------
    def test_portfolio_ledger_exact_reconciliation(self):
        ledger = PortfolioLedger(initial_capital_gbp=50000.0)
        t1 = self.timeline[0]
        t2 = self.timeline[5]

        # Open £15,000 position in GBP ETF
        pos = ledger.open_position(
            timestamp=t1,
            symbol="CSP1",
            jurisdiction="UK",
            instrument_class="ETF",
            shares=30.0,
            price_gbp=500.0,  # 30 * 500 = £15,000
            itemized_entry_frictions={"buy_spread_gbp": 3.75, "buy_slippage_gbp": 2.25}
        )
        self.assertEqual(len(ledger.positions), 1)
        # Cash must be exactly 50,000 - 15,000 - 6.00 = £34,994.00
        self.assertAlmostEqual(ledger.cash_gbp, 34994.00, places=2)

        # Mark to market at £510.00
        ledger.mark_to_market({"CSP1": 510.0})
        self.assertEqual(ledger.get_portfolio_nav(), 34994.00 + (30.0 * 510.0))

        # Close position at £510.00 (£300 gross profit)
        closed = ledger.close_position(
            timestamp=t2,
            symbol="CSP1",
            price_gbp=510.0,
            itemized_exit_frictions={"sell_spread_gbp": 3.82, "sell_slippage_gbp": 2.30},
            exit_reason="PROFIT_TARGET"
        )
        # Total friction = 6.00 entry + 6.12 exit = 12.12
        self.assertAlmostEqual(closed.total_friction_gbp, 12.12, places=2)
        # Net profit = 300.00 gross - 12.12 = £287.88
        self.assertAlmostEqual(closed.net_pnl_gbp, 287.88, places=2)

        # Invariant: Reconcile must succeed without raising LedgerDiscrepancyError
        self.assertTrue(ledger.reconcile())

    # ---------------------------------------------------------
    # G. DETERMINISTIC REPRODUCIBILITY
    # ---------------------------------------------------------
    def test_simulation_deterministic_reproducibility(self):
        engine1 = SimulationEngine(initial_capital_gbp=50000.0)
        engine2 = SimulationEngine(initial_capital_gbp=50000.0)

        def simple_strategy(t, boundary, ledger, sim):
            if t == self.timeline[2] and not ledger.positions:
                bar = boundary.get_latest_bar("TEST_SYM", t)
                if bar is not None:
                    order = Order("BUY_1", "TEST_SYM", OrderSide.BUY, OrderType.MARKET, 50.0, t)
                    fill = sim.simulate_fill(order, bar, t)
                    if fill:
                        ledger.open_position(t, "TEST_SYM", "US", "EQUITY", fill.quantity, fill.fill_price_gbp, fill.itemized_frictions)
            elif t == self.timeline[10] and "TEST_SYM" in ledger.positions:
                bar = boundary.get_latest_bar("TEST_SYM", t)
                if bar is not None:
                    order = Order("SELL_1", "TEST_SYM", OrderSide.SELL, OrderType.MARKET, 50.0, t)
                    fill = sim.simulate_fill(order, bar, t)
                    if fill:
                        ledger.close_position(t, "TEST_SYM", fill.fill_price_gbp, fill.itemized_frictions, "TIME_EXIT")

        res1 = engine1.run_strategy("STRAT_A", self.timeline, ["TEST_SYM"], simple_strategy, {"TEST_SYM": self.df_synthetic})
        res2 = engine2.run_strategy("STRAT_A", self.timeline, ["TEST_SYM"], simple_strategy, {"TEST_SYM": self.df_synthetic})

        # Invariant: Byte-for-byte identical ledger hash
        self.assertEqual(res1.ledger_hash, res2.ledger_hash)
        self.assertEqual(res1.net_pnl_gbp, res2.net_pnl_gbp)
        self.assertEqual(res1.final_nav_gbp, res2.final_nav_gbp)
        self.assertTrue(res1.reconciliation_verified)

    # ---------------------------------------------------------
    # H. OOS CRYPTOGRAPHIC SEALING INVARIANTS
    # ---------------------------------------------------------
    def test_oos_cryptographic_sealing_and_access_enforcement(self):
        # Create dates spanning Train, Validation, OOS
        dates_full = pd.date_range("2022-01-01", "2026-08-01", freq="D")
        df_full = pd.DataFrame({"Close": [100.0] * len(dates_full)}, index=dates_full)
        bars_map = {"AAPL": df_full}

        sealer = OOSSealer()
        manifest_hash = sealer.seal_oos_partition(bars_map)
        self.assertTrue(sealer.is_sealed)
        self.assertGreater(len(manifest_hash), 30)

        # Invariant: Attempt to access sealed OOS data must raise OOSAccessViolationError
        with self.assertRaises(OOSAccessViolationError):
            sealer.get_sealed_oos_data(bars_map)

        # Only filtered data up to validation end is accessible
        allowed = sealer.filter_allowed_data(bars_map, allow_validation=True)
        self.assertLessEqual(allowed["AAPL"].index.max(), sealer.val_end)

        # Unsealing requires formal signature and records audit
        audit = sealer.unseal_for_final_audit(
            auditor_signature="PRV_GOVERNANCE_CHIEF",
            rationale="Formal OOS Evaluation Milestone"
        )
        self.assertFalse(sealer.is_sealed)
        self.assertIn("unsealed_at", audit)
        # Now accessible
        oos_data = sealer.get_sealed_oos_data(bars_map)
        self.assertGreater(len(oos_data["AAPL"]), 0)

    # ---------------------------------------------------------
    # I. BENCHMARK & CONTROL FRAMEWORK INVARIANTS
    # ---------------------------------------------------------
    def test_benchmark_controls(self):
        sim = ExecutionSimulator()
        evaluator = BenchmarkEvaluator(sim, initial_capital_gbp=50000.0)

        # Cash benchmark
        cash_res = evaluator.run_cash_benchmark(self.timeline)
        self.assertEqual(cash_res.final_nav_gbp, 50000.0)
        self.assertEqual(cash_res.total_return_pct, 0.0)
        self.assertEqual(cash_res.total_trades, 0)

        # Passive buy and hold
        bh_res = evaluator.run_passive_buy_and_hold("CSP1", self.df_synthetic)
        self.assertEqual(bh_res.total_trades, 1)
        self.assertGreater(bh_res.total_friction_gbp, 0.0)

    # ---------------------------------------------------------
    # J. PRACTICE ACCOUNT SAFETY INVARIANT
    # ---------------------------------------------------------
    def test_practice_account_safety_invariant(self):
        # Invariant: Simulation harness has zero permission to trade Practice account
        self.assertFalse(
            settings.PRACTICE_NEW_ENTRIES_ALLOWED,
            "CRITICAL VIOLATION: PRACTICE_NEW_ENTRIES_ALLOWED must remain False!"
        )


if __name__ == "__main__":
    unittest.main()
