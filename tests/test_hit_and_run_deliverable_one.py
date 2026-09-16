"""
PRV Capital - Hit-and-Run Deliverable 1 Comprehensive Verification
Verifies all 6 components of Deliverable 1 together:
A. Trading212 full-universe discovery (unmocked against live metadata)
B. OpportunityCandidate data model
C. Short-term opportunity scoring interface
D. Dynamic capital allocator with <=80% deployment
E. Per-holding 5% max-loss invariant
F. Realised-net daily banking ledger

Strict Invariants:
- Broker writes == 0
- No mocks for universe discovery
- No modification of the running six-instrument system
"""
import unittest
from src.hit_and_run.universe import hit_and_run_universe
from src.hit_and_run.models import OpportunityCandidate, AllocationDecision, TradeAuditRecord
from src.hit_and_run.scoring import hit_and_run_scorer
from src.hit_and_run.allocator import dynamic_allocator, EvidenceConcentrationPolicy
from src.hit_and_run.risk import hit_and_run_risk
from src.hit_and_run.banking import DailyBankingLedger
from src.brokers.trading212 import broker


class TestHitAndRunDeliverableOneIntegration(unittest.TestCase):

    def setUp(self):
        # Intercept any potential broker writes to guarantee broker_writes == 0
        self.broker_writes = []
        self._orig_place_limit = getattr(broker, "place_limit_order", None)
        self._orig_place_market = getattr(broker, "place_market_order", None)
        self._orig_cancel_order = getattr(broker, "cancel_order", None)

        def mock_write(*args, **kwargs):
            self.broker_writes.append((args, kwargs))
            raise RuntimeError("FAIL_CLOSED: Unexpected broker write attempted!")

        if hasattr(broker, "place_limit_order"):
            broker.place_limit_order = mock_write
        if hasattr(broker, "place_market_order"):
            broker.place_market_order = mock_write
        if hasattr(broker, "cancel_order"):
            broker.cancel_order = mock_write

    def tearDown(self):
        if self._orig_place_limit:
            broker.place_limit_order = self._orig_place_limit
        if self._orig_place_market:
            broker.place_market_order = self._orig_place_market
        if self._orig_cancel_order:
            broker.cancel_order = self._orig_cancel_order

    def test_full_pipeline_deliverable_one(self):
        # --- Component A: Full Universe Discovery (Unmocked) ---
        telemetry = hit_and_run_universe.get_universe_telemetry()
        discovered_count = telemetry["DISCOVERED_INSTRUMENT_COUNT"]
        tradable_count = telemetry["TRADABLE_INSTRUMENT_COUNT"]
        product_families = telemetry["PRODUCT_FAMILIES"]

        self.assertGreater(discovered_count, 15000)
        self.assertGreater(tradable_count, 15000)
        self.assertIn("STOCK", product_families)
        self.assertIn("ETF", product_families)

        # Raw broker instruments lacking explicit minTradeQuantity fail closed with QUANTITY_INCREMENT_UNKNOWN.
        # Only instruments with authoritative/certified broker metadata (such as the 6 core ETFs) qualify.
        executable_universe = hit_and_run_universe.get_executable_universe()
        self.assertEqual(len(executable_universe), 6)

        # --- Component B & C: Candidate Data Model & Scoring ---
        # With authoritative broker metadata (minTradeQuantity, verified venue, ISIN)
        sample_inst = {
            "instrument_id": "BARCl_EQ",
            "symbol": "BARC",
            "feed_ticker": "BARC.L",
            "product_type": "STOCK",
            "currency": "GBX",
            "is_uk_pence": True,
            "quote_divisor": 100.0,
            "isin": "GB0031348658",
            "exchange_venue": "London Stock Exchange",
            "min_trade_quantity": 0.001,
            "max_open_quantity": 100000.0,
            "working_schedule_id": 56
        }
        snapshot = {
            "instrument_id": sample_inst["instrument_id"],
            "symbol": sample_inst["symbol"],
            "feed_ticker": sample_inst["feed_ticker"],
            "product_type": sample_inst["product_type"],
            "isin": sample_inst["isin"],
            "exchange_venue": sample_inst["exchange_venue"],
            "min_trade_quantity": sample_inst["min_trade_quantity"],
            "currency": sample_inst["currency"],
            "is_uk_pence": sample_inst["is_uk_pence"],
            "quote_divisor": sample_inst["quote_divisor"],
            "current_price": 100.0,
            "current_price_gbp": 100.0 if not sample_inst["is_uk_pence"] else 1.0,
            "intraday_open": 96.0,
            "intraday_high": 101.0,
            "intraday_low": 95.5,
            "recent_prices": [96.0, 96.5, 97.2, 98.0, 99.0, 100.0],
            "volume_recent": 200000,
            "volume_avg": 120000,
            "bid": 99.95,
            "ask": 100.05,
            "session_state": "REGULAR"
        }

        candidate = hit_and_run_scorer.evaluate_opportunity(snapshot)
        self.assertIsInstance(candidate, OpportunityCandidate)
        self.assertTrue(candidate.strategy_qualified)
        self.assertGreater(candidate.opportunity_score, 60.0)

        # --- Component D & E: Dynamic Allocation & 5% Max Loss Invariant ---
        portfolio_capital = 20000.0
        available_cash = 20000.0

        # Invariant: Without authorised AI sizing decisions, allocator fails closed with ALLOCATION_DECISION_UNAVAILABLE
        dynamic_allocator.policy = EvidenceConcentrationPolicy()
        allocations_no_ai = dynamic_allocator.allocate(
            portfolio_capital=portfolio_capital,
            available_cash=available_cash,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[candidate]
        )
        self.assertEqual(allocations_no_ai, [])
        self.assertEqual(dynamic_allocator.last_status, "ALLOCATION_DECISION_UNAVAILABLE")

        # When authorised AI sizing decision is supplied, allocator concentrates dynamically
        dynamic_allocator.policy = EvidenceConcentrationPolicy(sizing_decisions={candidate.symbol: 1.0})
        allocations = dynamic_allocator.allocate(
            portfolio_capital=portfolio_capital,
            available_cash=available_cash,
            existing_positions=[],
            outstanding_orders=[],
            candidates=[candidate]
        )

        self.assertGreaterEqual(len(allocations), 1)
        total_allocated = sum(a.allocated_capital_gbp for a in allocations)
        # Strict <= 80% deployment
        self.assertLessEqual(total_allocated, portfolio_capital * 0.80)

        for alloc in allocations:
            self.assertIsInstance(alloc, AllocationDecision)
            # Strict 5% max loss invariant on each holding
            self.assertLessEqual(alloc.max_loss_pct, 0.05)
            # Verify risk manager confirms stop price
            is_valid_stop, reason = hit_and_run_risk.verify_protective_stop_invariant(
                alloc.estimated_fill_price, alloc.stop_loss_price
            )
            self.assertTrue(is_valid_stop, f"Stop verification failed: {reason}")

        # --- Component F: Daily Banking Ledger ---
        ledger = DailyBankingLedger(trading_date="2026-09-16", base_target_gbp=100.0)

        # Simulate profit capture trades
        ledger.record_realised_trade("TR_A", candidate.instrument_id, gross_pnl_gbp=70.0, costs_gbp=5.0)
        ledger.record_realised_trade("TR_B", candidate.instrument_id, gross_pnl_gbp=45.0, costs_gbp=4.0)

        banking = ledger.get_banking_summary()
        self.assertEqual(banking["gross_realised_pnl"], 115.0)
        self.assertEqual(banking["trading_costs"], 9.0)
        self.assertEqual(banking["net_realised_pnl"], 106.0)
        self.assertEqual(banking["banked_net_profit_today"], 106.0)
        self.assertEqual(banking["remaining_to_base_target"], 0.0)
        self.assertTrue(banking["base_target_achieved"])
        # Invariant: Continue trading after target reached
        self.assertTrue(banking["continue_trading"])

        # Invariant: Zero broker writes
        self.assertEqual(len(self.broker_writes), 0)


if __name__ == "__main__":
    unittest.main()
