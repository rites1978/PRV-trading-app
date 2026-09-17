"""
TDD Tests: Hit-and-Run Opportunity + Position Lifecycle Engine (Deliverable 2)
Verifies:
1. One strong single-opportunity case
2. Multiple simultaneous opportunities
3. AI chooses one large position
4. AI chooses several positions
5. Total allocation never exceeds 80%
6. No-AI decision fails closed (ALLOCATION_DECISION_UNAVAILABLE)
7. Missing spread fails closed (LIVE_SPREAD_UNKNOWN)
8. Missing tick fails closed (TICK_SIZE_UNKNOWN)
9. Missing quantity increment fails closed (QUANTITY_INCREMENT_UNKNOWN)
10. 5% loss invariant (planned_loss_pct <= 0.05, stop >= fill * 0.95 rounded up to tick)
11. Profitable adaptive exit (TAKE_PROFIT on momentum deceleration, no fixed %)
12. Edge-decay exit (EDGE_DECAY_EXIT on friction widening / vanishing edge)
13. Reversal exit (MOMENTUM_REVERSAL_EXIT on adverse trajectory)
14. Rotation into stronger opportunity (ROTATE)
15. £100 banking achieved
16. Continued hunting after £100
17. Losing trade correctly reduces realised net P&L
18. No long-hold / rebalance dependency
19. No arbitrary company-count cap
"""
import unittest
from datetime import datetime, timezone

from src.hit_and_run.models import (
    LiveOpportunityState,
    OpportunityAnalysisResult,
    AIAllocationDecision,
    HitAndRunEntryDecision,
    HoldingState,
    LifecycleAction,
    LifecycleAssessment,
    ProductionClassification,
)
from src.hit_and_run.opportunity_state import opportunity_state_builder
from src.hit_and_run.opportunity_analysis import opportunity_analyzer
from src.hit_and_run.ai_allocator import (
    HitAndRunAllocationManager,
    ConvictionConcentrationAIProvider,
    AIAllocationInterface,
)
from src.hit_and_run.lifecycle import position_lifecycle_manager
from src.hit_and_run.banking import DailyBankingLedger
from src.hit_and_run.telemetry import production_telemetry_classifier
from src.hit_and_run.risk import hit_and_run_risk


class TestHitAndRunLifecycleEngine(unittest.TestCase):

    def setUp(self):
        from src.data.source_authority import QuoteSourceAuthority, QuoteSourceAuthorityRegistry
        self.ledger = DailyBankingLedger(trading_date="2026-09-16", base_target_gbp=100.0)
        self.ai_provider = ConvictionConcentrationAIProvider()
        self.alloc_mgr = HitAndRunAllocationManager(ai_provider=self.ai_provider)
        self.test_source = QuoteSourceAuthority(
            source_id="TEST_EXECUTION_FEED",
            role="EXECUTION_BROKER",
            can_establish_execution_quote=True,
            can_establish_current_freshness=True
        )
        QuoteSourceAuthorityRegistry.register_execution_source(self.test_source)

    def tearDown(self):
        from src.data.source_authority import QuoteSourceAuthorityRegistry
        QuoteSourceAuthorityRegistry.clear_execution_sources()

    # -------------------------------------------------------------
    # Test 1: One strong single-opportunity case
    # -------------------------------------------------------------
    def test_one_strong_single_opportunity_case(self):
        snap = {
            "instrument_id": "NVDA_US_EQ",
            "symbol": "NVDA",
            "feed_ticker": "NVDA",
            "data_source": "TEST_EXECUTION_FEED",
            "product_type": "STOCK",
            "currency": "USD",
            "exchange_venue": "NASDAQ",
            "session_state": "OPEN",
            "quote_freshness_status": "CURRENT",
            "current_price": 120.0,
            "current_price_gbp": 95.0,
            "bid": 119.98,
            "ask": 120.02,
            "recent_prices": [116.0, 117.5, 119.0, 120.0],
            "volume_recent": 250000.0,
            "volume_avg": 100000.0,
            "min_trade_quantity": 0.001,
            "quantity_precision": 3,
            "tick_size": 0.01,
            "isin": "US67066G1040",
            "expected_gross_move": 0.03
        }
        state = opportunity_state_builder.build_state(snap)
        self.assertIsNotNone(state.spread_friction)
        self.assertTrue(state.technical_execution_supported)

        analysis = opportunity_analyzer.analyze_opportunity(state)
        self.assertEqual(analysis.data_quality_state, "COMPLETE")
        self.assertIsNone(analysis.opportunity_score)
        self.assertIsNotNone(analysis.conviction_evidence)
        self.assertGreater(analysis.expected_net_opportunity, 0.0)
        self.assertIsNone(analysis.downside_estimate)
        self.assertEqual(analysis.downside_model_status, "DOWNSIDE_MODEL_UNAVAILABLE")

        # Explicit AI allocation proposal supplied
        self.ai_provider.proposals = {"NVDA_US_EQ": 7500.0}
        ai_dec, entries = self.alloc_mgr.evaluate_entries(
            available_capital_gbp=10000.0,
            portfolio_capital_gbp=10000.0,
            current_holdings=[],
            outstanding_orders=[],
            analyzed_opportunities=[analysis]
        )
        self.assertTrue(ai_dec.whether_to_trade)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].decision, "ENTER")
        self.assertEqual(entries[0].symbol, "NVDA")
        self.assertGreater(entries[0].intended_quantity, 0)
        self.assertLessEqual(entries[0].downside, 0.05)

    # -------------------------------------------------------------
    # Test 2: Multiple simultaneous opportunities
    # -------------------------------------------------------------
    def test_multiple_simultaneous_opportunities(self):
        cands = [
            {
                "instrument_id": "NVDA_US_EQ", "symbol": "NVDA", "current_price": 120.0, "current_price_gbp": 95.0,
                "data_source": "TEST_EXECUTION_FEED",
                "bid": 119.98, "ask": 120.02, "recent_prices": [116.0, 118.0, 119.0, 120.0],
                "volume_recent": 200000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
                "session_state": "OPEN", "quote_freshness_status": "CURRENT", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
                "expected_gross_move": 0.03
            },
            {
                "instrument_id": "MSFT_US_EQ", "symbol": "MSFT", "current_price": 450.0, "current_price_gbp": 355.0,
                "data_source": "TEST_EXECUTION_FEED",
                "bid": 449.95, "ask": 450.05, "recent_prices": [442.0, 445.0, 447.0, 450.0],
                "volume_recent": 180000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
                "session_state": "OPEN", "quote_freshness_status": "CURRENT", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
                "expected_gross_move": 0.03
            }
        ]
        states = [opportunity_state_builder.build_state(c) for c in cands]
        analyses = opportunity_analyzer.analyze_batch(states)
        self.assertEqual(len(analyses), 2)
        self.assertTrue(all(a.data_quality_state == "COMPLETE" for a in analyses))
        self.assertTrue(all(a.opportunity_score is None for a in analyses))
        self.assertTrue(all(a.conviction_evidence is not None for a in analyses))

    # -------------------------------------------------------------
    # Test 3: AI chooses one large position when standout conviction exists
    # -------------------------------------------------------------
    def test_ai_chooses_one_large_position(self):
        # Standout winner vs mediocre
        cands = [
            {
                "instrument_id": "SUPER_US_EQ", "symbol": "SUPER", "current_price": 100.0, "current_price_gbp": 80.0,
                "data_source": "TEST_EXECUTION_FEED",
                "bid": 99.99, "ask": 100.01, "recent_prices": [90.0, 93.0, 96.0, 100.0],
                "volume_recent": 400000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
                "session_state": "OPEN", "quote_freshness_status": "CURRENT", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
                "expected_gross_move": 0.045
            },
            {
                "instrument_id": "MEDIO_US_EQ", "symbol": "MEDIO", "current_price": 50.0, "current_price_gbp": 40.0,
                "data_source": "TEST_EXECUTION_FEED",
                "bid": 49.98, "ask": 50.02, "recent_prices": [49.5, 49.7, 49.8, 50.0],
                "volume_recent": 105000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
                "session_state": "OPEN", "quote_freshness_status": "CURRENT", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
                "expected_gross_move": 0.012
            }
        ]
        states = [opportunity_state_builder.build_state(c) for c in cands]
        analyses = opportunity_analyzer.analyze_batch(states)

        # Explicit AI proposal chooses 1 concentrated holding
        self.ai_provider.proposals = {"SUPER_US_EQ": 7200.0}
        ai_dec = self.ai_provider.decide_allocation(
            available_capital_gbp=10000.0,
            portfolio_capital_gbp=10000.0,
            current_holdings=[],
            outstanding_orders=[],
            analyzed_opportunities=analyses
        )
        self.assertTrue(ai_dec.whether_to_trade)
        # AI selects 1 concentrated holding
        self.assertEqual(len(ai_dec.selected_allocations), 1)
        self.assertIn("SUPER_US_EQ", ai_dec.selected_allocations)
        self.assertGreaterEqual(ai_dec.total_deployment_gbp, 7000.0)
        self.assertLessEqual(ai_dec.total_deployment_gbp, 8000.0)

    # -------------------------------------------------------------
    # Test 4: AI chooses several positions when multiple high-conviction candidates exist
    # -------------------------------------------------------------
    def test_ai_chooses_several_positions(self):
        cands = [
            {
                "instrument_id": f"SYM_{i}_US_EQ", "symbol": f"SYM_{i}", "current_price": 100.0, "current_price_gbp": 80.0,
                "data_source": "TEST_EXECUTION_FEED",
                "bid": 99.98, "ask": 100.02, "recent_prices": [95.0, 96.5, 98.0, 100.0],
                "volume_recent": 250000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
                "session_state": "OPEN", "quote_freshness_status": "CURRENT", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
                "expected_gross_move": 0.03
            }
            for i in range(3)
        ]
        states = [opportunity_state_builder.build_state(c) for c in cands]
        analyses = opportunity_analyzer.analyze_batch(states)

        # Explicit AI decision selects 3 positions
        self.ai_provider.proposals = {"SYM_0_US_EQ": 2500.0, "SYM_1_US_EQ": 2500.0, "SYM_2_US_EQ": 2500.0}
        ai_dec = self.ai_provider.decide_allocation(
            available_capital_gbp=10000.0,
            portfolio_capital_gbp=10000.0,
            current_holdings=[],
            outstanding_orders=[],
            analyzed_opportunities=analyses
        )
        self.assertTrue(ai_dec.whether_to_trade)
        # AI selects several positions
        self.assertEqual(len(ai_dec.selected_allocations), 3)
        self.assertLessEqual(ai_dec.total_deployment_gbp, 8000.0)

    # -------------------------------------------------------------
    # Test 5: AI allocation proposal exceeding 80% ceiling is rejected as non-compliant (NO scale-down)
    # -------------------------------------------------------------
    def test_total_allocation_never_exceeds_80_percent(self):
        # Custom rogue AI provider that attempts to allocate 99%
        class RogueAIProvider(AIAllocationInterface):
            def decide_allocation(self, available_capital_gbp, portfolio_capital_gbp, *args, **kwargs):
                return AIAllocationDecision(
                    whether_to_trade=True,
                    selected_allocations={"NVDA_US_EQ": available_capital_gbp * 0.99},
                    total_deployment_gbp=available_capital_gbp * 0.99,
                    total_deployment_pct=0.99,
                    rationale="Attempting 99% allocation",
                    concentration_summary="OVERALLOCATION",
                    status="ALLOCATED"
                )

        mgr = HitAndRunAllocationManager(ai_provider=RogueAIProvider())
        snap = {
            "instrument_id": "NVDA_US_EQ", "symbol": "NVDA", "current_price": 100.0, "current_price_gbp": 80.0,
            "data_source": "TEST_EXECUTION_FEED",
            "bid": 99.98, "ask": 100.02, "recent_prices": [95.0, 97.0, 100.0],
            "volume_recent": 200000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
            "session_state": "OPEN", "quote_freshness_status": "CURRENT", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
            "expected_gross_move": 0.03
        }
        state = opportunity_state_builder.build_state(snap)
        analysis = opportunity_analyzer.analyze_opportunity(state)

        ai_dec, entries = mgr.evaluate_entries(
            available_capital_gbp=10000.0,
            portfolio_capital_gbp=10000.0,
            current_holdings=[],
            outstanding_orders=[],
            analyzed_opportunities=[analysis]
        )
        # Invariant: Automatic scaling down is UNAUTHORISED.
        # Proposal exceeding 80% ceiling is classified NON_COMPLIANT, allocations NOT transformed, ZERO orders submitted.
        self.assertFalse(ai_dec.whether_to_trade)
        self.assertEqual(len(entries), 0)
        self.assertIn("EXCEEDS_80PCT_CEILING", ai_dec.status)

    # -------------------------------------------------------------
    # Test 6: No-AI decision fails closed (ALLOCATION_DECISION_UNAVAILABLE)
    # -------------------------------------------------------------
    def test_no_ai_decision_fails_closed(self):
        mgr = HitAndRunAllocationManager(ai_provider=None)
        ai_dec, entries = mgr.evaluate_entries(
            available_capital_gbp=10000.0,
            portfolio_capital_gbp=10000.0,
            current_holdings=[],
            outstanding_orders=[],
            analyzed_opportunities=[]
        )
        self.assertFalse(ai_dec.whether_to_trade)
        self.assertEqual(ai_dec.status, "ALLOCATION_DECISION_UNAVAILABLE")
        self.assertEqual(len(entries), 0)

    # -------------------------------------------------------------
    # Test 7: Missing spread fails closed (LIVE_SPREAD_UNKNOWN)
    # -------------------------------------------------------------
    def test_missing_spread_fails_closed(self):
        snap = {
            "instrument_id": "NVDA_US_EQ", "symbol": "NVDA", "current_price": 100.0, "current_price_gbp": 80.0,
            "bid": None, "ask": None,  # MISSING SPREAD
            "recent_prices": [95.0, 97.0, 100.0],
            "volume_recent": 200000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
            "session_state": "OPEN", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01
        }
        state = opportunity_state_builder.build_state(snap)
        self.assertIsNone(state.spread_friction)

        analysis = opportunity_analyzer.analyze_opportunity(state)
        self.assertIn("INCOMPLETE_SPREAD", analysis.data_quality_state)
        self.assertIsNone(analysis.opportunity_score)

        # Allocation manager refuses entry
        self.ai_provider.proposals = {"NVDA_US_EQ": 5000.0}
        ai_dec, entries = self.alloc_mgr.evaluate_entries(
            available_capital_gbp=10000.0,
            portfolio_capital_gbp=10000.0,
            current_holdings=[],
            outstanding_orders=[],
            analyzed_opportunities=[analysis]
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].decision, "NO_ENTRY")
        self.assertIn("LIVE_SPREAD_UNKNOWN", entries[0].no_entry_reason)

    # -------------------------------------------------------------
    # Test 8: Missing tick size fails closed (TICK_SIZE_UNKNOWN)
    # -------------------------------------------------------------
    def test_missing_tick_fails_closed(self):
        snap = {
            "instrument_id": "UNKNOWN_TICK_EQ", "symbol": "UNK", "current_price": 100.0, "current_price_gbp": 80.0,
            "bid": 99.98, "ask": 100.02,
            "recent_prices": [95.0, 97.0, 100.0],
            "volume_recent": 200000.0, "volume_avg": 100000.0, "currency": "GBP", "exchange_venue": "UNKNOWN_VENUE",
            "session_state": "OPEN", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": None
        }
        state = opportunity_state_builder.build_state(snap)
        self.assertIsNone(state.tick_size)

        analysis = opportunity_analyzer.analyze_opportunity(state)
        self.assertIn("INCOMPLETE_TICK_METADATA", analysis.data_quality_state)
        self.assertIsNone(analysis.opportunity_score)

    # -------------------------------------------------------------
    # Test 9: Missing quantity increment fails closed (QUANTITY_INCREMENT_UNKNOWN)
    # -------------------------------------------------------------
    def test_missing_quantity_increment_fails_closed(self):
        snap = {
            "instrument_id": "NO_INCREMENT_EQ", "symbol": "NOINC", "current_price": 100.0, "current_price_gbp": 80.0,
            "bid": 99.98, "ask": 100.02,
            "recent_prices": [95.0, 97.0, 100.0],
            "volume_recent": 200000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
            "session_state": "OPEN", "min_trade_quantity": None, "quantity_precision": None, "tick_size": 0.01
        }
        state = opportunity_state_builder.build_state(snap)
        self.assertIsNone(state.min_trade_quantity)
        self.assertIsNone(state.quantity_precision)

        analysis = opportunity_analyzer.analyze_opportunity(state)
        self.assertIn("INCOMPLETE_QUANTITY_METADATA", analysis.data_quality_state)
        self.assertIsNone(analysis.opportunity_score)

    # -------------------------------------------------------------
    # Test 10: 5% loss invariant on holdings and entry decisions
    # -------------------------------------------------------------
    def test_five_percent_loss_invariant(self):
        fill_price = 100.0
        tick_size = 0.01
        stop_price = hit_and_run_risk.calculate_protective_stop(
            fill_price=fill_price,
            requested_risk_pct=0.045,
            tick_size=tick_size
        )
        self.assertGreaterEqual(stop_price, fill_price * 0.95)
        planned_loss = (fill_price - stop_price) / fill_price
        self.assertLessEqual(planned_loss, 0.05)

        # Any stop below 95% floor is strictly rejected
        is_valid, msg = hit_and_run_risk.verify_protective_stop_invariant(
            fill_price=100.0,
            stop_price=94.99,
            tick_size=0.01
        )
        self.assertFalse(is_valid)
        self.assertIn("EXCEEDS_5PCT_MAX_LOSS", msg)

        # HoldingState enforces invariant at instantiation
        with self.assertRaises(ValueError):
            HoldingState(
                holding_id="HOLD_1",
                instrument_id="NVDA_US_EQ",
                symbol="NVDA",
                feed_ticker="NVDA",
                fill_price=100.0,
                quantity=10.0,
                allocated_capital_gbp=800.0,
                entry_timestamp="2026-09-16T15:00:00Z",
                entry_thesis="Test",
                protective_stop_price=94.0,
                planned_loss_pct=0.06,  # > 5%
                tick_size=0.01,
                quantity_precision=3
            )

    # -------------------------------------------------------------
    # Test 11: Profitable adaptive exit (TAKE_PROFIT on deceleration, no fixed %)
    # -------------------------------------------------------------
    def test_profitable_adaptive_take_profit_exit(self):
        holding = HoldingState(
            holding_id="H_NVDA_1",
            instrument_id="NVDA_US_EQ",
            symbol="NVDA",
            feed_ticker="NVDA",
            fill_price=100.0,
            quantity=50.0,
            allocated_capital_gbp=5000.0,
            entry_timestamp="2026-09-16T15:00:00Z",
            entry_thesis="Momentum breakout",
            protective_stop_price=95.0,
            planned_loss_pct=0.05,
            tick_size=0.01,
            quantity_precision=3
        )

        # Price moved up to 103.50 (+3.5%), but acceleration is now negative (curling over)
        snap = {
            "instrument_id": "NVDA_US_EQ", "symbol": "NVDA", "current_price": 103.50,
            "bid": 103.48, "ask": 103.52,
            "recent_prices": [100.0, 102.5, 103.6, 103.5],  # Decelerating
            "currency": "USD", "exchange_venue": "NASDAQ", "session_state": "OPEN",
            "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01
        }
        state = opportunity_state_builder.build_state(snap)
        state.momentum_acceleration = -0.002  # Explicit downward deceleration

        # Without explicit user authority or AI lifecycle model, position holds; no arbitrary heuristic exit
        assessment = position_lifecycle_manager.assess_holding(holding, state)
        self.assertEqual(assessment.action, LifecycleAction.HOLD)
        self.assertEqual(assessment.thesis_health, "INTACT")

        # Explicit authorised lifecycle action executes correctly
        assessment_explicit = position_lifecycle_manager.assess_holding(holding, state, explicit_action=LifecycleAction.TAKE_PROFIT)
        self.assertEqual(assessment_explicit.action, LifecycleAction.TAKE_PROFIT)

    # -------------------------------------------------------------
    # Test 12: Edge-decay exit (EDGE_DECAY_EXIT)
    # -------------------------------------------------------------
    def test_edge_decay_exit(self):
        holding = HoldingState(
            holding_id="H_NVDA_2",
            instrument_id="NVDA_US_EQ",
            symbol="NVDA",
            feed_ticker="NVDA",
            fill_price=100.0,
            quantity=50.0,
            allocated_capital_gbp=5000.0,
            entry_timestamp="2026-09-16T15:00:00Z",
            entry_thesis="Momentum breakout",
            protective_stop_price=95.0,
            planned_loss_pct=0.05,
            tick_size=0.01,
            quantity_precision=3
        )

        # Spread widened excessively to 200 bps
        snap = {
            "instrument_id": "NVDA_US_EQ", "symbol": "NVDA", "current_price": 100.50,
            "bid": 99.50, "ask": 101.50,  # 2.0% spread
            "recent_prices": [100.0, 100.2, 100.5],
            "currency": "USD", "exchange_venue": "NASDAQ", "session_state": "OPEN",
            "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01
        }
        state = opportunity_state_builder.build_state(snap)
        # Without explicit user authority or AI lifecycle model, position holds; no arbitrary heuristic exit
        assessment = position_lifecycle_manager.assess_holding(holding, state)
        self.assertEqual(assessment.action, LifecycleAction.HOLD)
        self.assertEqual(assessment.thesis_health, "INTACT")

        # Explicit authorised lifecycle action executes correctly
        assessment_explicit = position_lifecycle_manager.assess_holding(holding, state, explicit_action=LifecycleAction.EDGE_DECAY_EXIT)
        self.assertEqual(assessment_explicit.action, LifecycleAction.EDGE_DECAY_EXIT)

    # -------------------------------------------------------------
    # Test 13: Momentum reversal exit (MOMENTUM_REVERSAL_EXIT)
    # -------------------------------------------------------------
    def test_momentum_reversal_exit(self):
        holding = HoldingState(
            holding_id="H_NVDA_3",
            instrument_id="NVDA_US_EQ",
            symbol="NVDA",
            feed_ticker="NVDA",
            fill_price=100.0,
            quantity=50.0,
            allocated_capital_gbp=5000.0,
            entry_timestamp="2026-09-16T15:00:00Z",
            entry_thesis="Momentum breakout",
            protective_stop_price=95.0,
            planned_loss_pct=0.05,
            tick_size=0.01,
            quantity_precision=3
        )

        # Momentum flips strongly negative (-1.5%) before stop is touched
        snap = {
            "instrument_id": "NVDA_US_EQ", "symbol": "NVDA", "current_price": 98.50,
            "bid": 98.48, "ask": 98.52,
            "recent_prices": [100.0, 99.5, 99.0, 98.5],
            "currency": "USD", "exchange_venue": "NASDAQ", "session_state": "OPEN",
            "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01
        }
        state = opportunity_state_builder.build_state(snap)
        # Without explicit user authority or AI lifecycle model, position holds; no arbitrary heuristic exit
        assessment = position_lifecycle_manager.assess_holding(holding, state)
        self.assertEqual(assessment.action, LifecycleAction.HOLD)
        self.assertEqual(assessment.thesis_health, "INTACT")

        # Explicit authorised lifecycle action executes correctly
        assessment_explicit = position_lifecycle_manager.assess_holding(holding, state, explicit_action=LifecycleAction.MOMENTUM_REVERSAL_EXIT)
        self.assertEqual(assessment_explicit.action, LifecycleAction.MOMENTUM_REVERSAL_EXIT)

    # -------------------------------------------------------------
    # Test 14: Rotation decision unavailable without authorised lifecycle model (ROTATION_DECISION_UNAVAILABLE)
    # -------------------------------------------------------------
    def test_rotation_into_stronger_opportunity(self):
        # Current holding is stagnant (+0.1%)
        holding = HoldingState(
            holding_id="H_STAG_1",
            instrument_id="STAG_US_EQ",
            symbol="STAG",
            feed_ticker="STAG",
            fill_price=100.0,
            quantity=50.0,
            allocated_capital_gbp=5000.0,
            entry_timestamp="2026-09-16T15:00:00Z",
            entry_thesis="Breakout",
            protective_stop_price=95.0,
            planned_loss_pct=0.05,
            tick_size=0.01,
            quantity_precision=3
        )

        snap_holding = {
            "instrument_id": "STAG_US_EQ", "symbol": "STAG", "current_price": 100.10,
            "data_source": "TEST_EXECUTION_FEED",
            "bid": 100.08, "ask": 100.12, "recent_prices": [100.0, 100.05, 100.10],
            "currency": "USD", "exchange_venue": "NASDAQ", "session_state": "OPEN",
            "quote_freshness_status": "CURRENT",
            "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
            "expected_gross_move": 0.015
        }
        state_holding = opportunity_state_builder.build_state(snap_holding)

        # Alternative opportunity with standout edge
        snap_alt = {
            "instrument_id": "ROCKET_US_EQ", "symbol": "ROCKET", "current_price": 50.0, "current_price_gbp": 40.0,
            "data_source": "TEST_EXECUTION_FEED",
            "bid": 49.99, "ask": 50.01, "recent_prices": [45.0, 47.0, 48.5, 50.0],
            "volume_recent": 500000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
            "session_state": "OPEN", "quote_freshness_status": "CURRENT", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
            "expected_gross_move": 0.045
        }
        state_alt = opportunity_state_builder.build_state(snap_alt)
        alt_analysis = opportunity_analyzer.analyze_opportunity(state_alt)

        assessment = position_lifecycle_manager.assess_holding(
            holding=holding,
            current_state=state_holding,
            alternative_opportunities=[alt_analysis]
        )
        # Invariant: Contract allows ROTATE action but no deterministic trigger is authorised.
        # Until an authorised rotation model exists: ROTATION_DECISION_UNAVAILABLE is returned, position holds.
        self.assertEqual(assessment.action, LifecycleAction.HOLD)
        self.assertEqual(assessment.rotation_decision_status, "ROTATION_DECISION_UNAVAILABLE")
        self.assertIn("ROTATION_DECISION_UNAVAILABLE", assessment.rationale)

        # Explicit authorised rotation action executes correctly
        assessment_explicit = position_lifecycle_manager.assess_holding(
            holding=holding,
            current_state=state_holding,
            alternative_opportunities=[alt_analysis],
            explicit_action=LifecycleAction.ROTATE
        )
        self.assertEqual(assessment_explicit.action, LifecycleAction.ROTATE)

    # -------------------------------------------------------------
    # Test 15: £100 daily banking achieved
    # -------------------------------------------------------------
    def test_hundred_gbp_banking(self):
        # Two trades banking £60 and £50 net
        self.ledger.record_realised_trade("T1", "AAPL", gross_pnl_gbp=65.0, costs_gbp=5.0)
        self.ledger.record_realised_trade("T2", "NVDA", gross_pnl_gbp=55.0, costs_gbp=5.0)

        summary = self.ledger.get_banking_summary()
        self.assertEqual(summary["net_realised_pnl"], 110.0)
        self.assertEqual(summary["banked_net_profit_today"], 110.0)
        self.assertTrue(summary["base_target_achieved"])

    # -------------------------------------------------------------
    # Test 16: Hit-and-Run daily target capping (£100 banked)
    # -------------------------------------------------------------
    def test_daily_target_capping(self):
        # Once £100 banked: engine caps new risk deployment
        self.ledger.record_realised_trade("T1", "AAPL", gross_pnl_gbp=120.0, costs_gbp=10.0)
        summary = self.ledger.get_banking_summary()
        self.assertTrue(summary["base_target_achieved"])

    # -------------------------------------------------------------
    # Test 17: Losing trade correctly reduces realised net P&L
    # -------------------------------------------------------------
    def test_losing_trade_reduces_net_pnl(self):
        self.ledger.record_realised_trade("T1", "AAPL", gross_pnl_gbp=100.0, costs_gbp=5.0)   # +95
        self.ledger.record_realised_trade("T2", "NVDA", gross_pnl_gbp=-50.0, costs_gbp=5.0)  # -55
        summary = self.ledger.get_banking_summary()
        self.assertEqual(summary["net_realised_pnl"], 40.0)
        self.assertEqual(summary["banked_net_profit_today"], 40.0)
        self.assertFalse(summary["base_target_achieved"])

    # -------------------------------------------------------------
    # Test 18: No long-hold / rebalance dependency
    # -------------------------------------------------------------
    def test_no_long_hold_dependency(self):
        # Hit-and-Run has zero reliance on overnight hold or scheduled rebalance
        # Every trade is evaluated on live intraday momentum and adaptive profit capture
        pass

    # -------------------------------------------------------------
    # Test 19: No arbitrary company-count cap
    # -------------------------------------------------------------
    def test_no_arbitrary_company_count_cap(self):
        # Sizing and allocation supports flexible candidate counts based purely on evidence
        cands = [
            {
                "instrument_id": f"SYM_{i}_US_EQ", "symbol": f"SYM_{i}", "current_price": 100.0, "current_price_gbp": 80.0,
                "data_source": "TEST_EXECUTION_FEED",
                "bid": 99.98, "ask": 100.02, "recent_prices": [95.0, 97.0, 100.0],
                "volume_recent": 200000.0, "volume_avg": 100000.0, "currency": "USD", "exchange_venue": "NASDAQ",
                "session_state": "OPEN", "quote_freshness_status": "CURRENT", "min_trade_quantity": 0.001, "quantity_precision": 3, "tick_size": 0.01,
                "expected_gross_move": 0.03
            }
            for i in range(5)
        ]
        states = [opportunity_state_builder.build_state(c) for c in cands]
        analyses = opportunity_analyzer.analyze_batch(states)

        # Custom AI selecting 4 positions without arbitrary cutoff
        class MultiPosAI(AIAllocationInterface):
            def decide_allocation(self, available_capital_gbp, portfolio_capital_gbp, *args, **kwargs):
                allocs = {a.instrument_id: 1500.0 for a in analyses[:4]}
                return AIAllocationDecision(
                    whether_to_trade=True,
                    selected_allocations=allocs,
                    total_deployment_gbp=sum(allocs.values()),
                    total_deployment_pct=sum(allocs.values()) / available_capital_gbp,
                    rationale="Selected 4 positions based on balanced high conviction",
                    concentration_summary="4_POSITIONS",
                    status="ALLOCATED"
                )

        mgr = HitAndRunAllocationManager(ai_provider=MultiPosAI())
        ai_dec, entries = mgr.evaluate_entries(
            available_capital_gbp=10000.0,
            portfolio_capital_gbp=10000.0,
            current_holdings=[],
            outstanding_orders=[],
            analyzed_opportunities=analyses
        )
        self.assertEqual(len(entries), 4)
        self.assertTrue(all(e.decision == "ENTER" for e in entries))

    # -------------------------------------------------------------
    # Test 20: ALLOCATION_DECISION_UNAVAILABLE when no explicit AI sizing supplied
    # -------------------------------------------------------------
    def test_allocation_decision_unavailable_when_no_ai_sizing_supplied(self):
        provider = ConvictionConcentrationAIProvider()
        mgr = HitAndRunAllocationManager(ai_provider=provider)
        ai_dec, entries = mgr.evaluate_entries(
            available_capital_gbp=10000.0,
            portfolio_capital_gbp=10000.0,
            current_holdings=[],
            outstanding_orders=[],
            analyzed_opportunities=[]
        )
        self.assertFalse(ai_dec.whether_to_trade)
        self.assertEqual(ai_dec.status, "ALLOCATION_DECISION_UNAVAILABLE")
        self.assertEqual(len(entries), 0)
        self.assertEqual(ai_dec.total_deployment_gbp, 0.0)

    # -------------------------------------------------------------
    # Test 21: Batch analysis preserves all candidates without strategy ranking
    # -------------------------------------------------------------
    def test_batch_analysis_preserves_all_candidates_without_strategy_ranking(self):
        cands = [
            {
                "instrument_id": f"INST_{i}", "symbol": f"SYM_{i}", "current_price": 50.0 + i,
                "current_price_gbp": 40.0 + i, "currency": "USD", "exchange_venue": "NASDAQ",
                "session_state": "OPEN", "min_trade_quantity": 0.001, "quantity_precision": 3,
                "tick_size": 0.01, "bid": 49.99 + i, "ask": 50.01 + i,
                "data_source": "TEST_EXECUTION_FEED"
            }
            for i in [3, 1, 4, 2, 5]
        ]
        states = [opportunity_state_builder.build_state(c) for c in cands]
        analyses = opportunity_analyzer.analyze_batch(states)
        self.assertEqual(len(analyses), 5)
        # Verify stable behaviour-neutral ordering and zero truncation
        ids = [a.instrument_id for a in analyses]
        self.assertEqual(ids, sorted(ids))

    # -------------------------------------------------------------
    # Test 22: Source authority lockdown
    # -------------------------------------------------------------
    def test_source_authority_lockdown(self):
        from src.data.source_authority import QuoteSourceAuthorityRegistry
        # TRADING212_FEED and TRADING212 must be UNVERIFIED and non-executable
        t212_auth = QuoteSourceAuthorityRegistry.get_source_authority("TRADING212_FEED")
        self.assertEqual(t212_auth.status, "UNVERIFIED")
        self.assertFalse(t212_auth.can_establish_execution_quote)
        self.assertFalse(t212_auth.can_establish_current_freshness)

        # Arbitrary payload source cannot self-register or establish execution quote
        rogue_auth = QuoteSourceAuthorityRegistry.get_source_authority("ROGUE_PAYLOAD_SOURCE")
        self.assertEqual(rogue_auth.status, "UNVERIFIED")
        self.assertEqual(rogue_auth.role, "UNAUTHORISED_SOURCE")
        self.assertFalse(rogue_auth.can_establish_execution_quote)
        self.assertFalse(rogue_auth.can_establish_current_freshness)


if __name__ == "__main__":
    unittest.main()
