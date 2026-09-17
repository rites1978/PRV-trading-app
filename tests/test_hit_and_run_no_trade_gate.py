"""
Unit Tests: Non-Negotiable No-Trade Truth Gate, Decoupled Dashboard State & Failure Classification
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Verifies:
1. Scan Outcome State Model (Section 1 & 7A, 7H)
2. NO_VALID_EDGE Hard Gate (Section 2 & 7B, 7H)
3. Product Failure Classification (Section 3 & 7A, 7C, 7D, 7E, 7F, 7G, 7J)
4. Loss vs Product Failure Distinction (Section 9 & 7I)
5. Dashboard / API State (Section 8 & 10)
"""
import unittest
from datetime import datetime, timezone
from typing import Dict, Any, List

from src.hit_and_run.models import (
    ProductionClassification,
    ProductionTelemetry,
    DashboardScanStatus,
)
from src.hit_and_run.telemetry import production_telemetry_classifier
from src.hit_and_run.dashboard import dashboard_presenter
from src.hit_and_run.engine import HitAndRunEngine


class TestScanOutcomeStateModel(unittest.TestCase):
    """Verifies independent scan outcome product states (Section 1)."""

    def test_scan_process_completed_does_not_imply_market_evaluation_complete(self):
        """
        The fact that the scan loop completed successfully MUST NOT imply that the
        market was evaluated successfully.
        Example:
        SCAN_PROCESS_STATUS = COMPLETED
        MARKET_EVALUATION_STATUS = INCOMPLETE
        TRADE_OUTCOME = NONE
        PRODUCTION_FAILURE_REASON = EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=0,
            scan_process_completed=True,  # Loop completed normally
            market_data_status="MISSING",
            all_relevant_candidates_evaluated=False
        )
        self.assertEqual(telem.scan_process_status, "COMPLETED")
        self.assertEqual(telem.market_evaluation_status, "INCOMPLETE")
        self.assertEqual(telem.trade_outcome, "NONE")
        self.assertEqual(telem.production_failure_reason, "EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING")
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertFalse(telem.market_evaluation_complete)
        self.assertFalse(telem.no_valid_edge_prerequisites_proven)

        # Dictionary export must expose both exact upper and lower case
        d = telem.to_dict()
        self.assertEqual(d["SCAN_PROCESS_STATUS"], "COMPLETED")
        self.assertEqual(d["MARKET_EVALUATION_STATUS"], "INCOMPLETE")
        self.assertEqual(d["TRADE_OUTCOME"], "NONE")
        self.assertEqual(d["PRODUCTION_FAILURE_REASON"], "EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING")


class TestNoValidEdgeHardGate(unittest.TestCase):
    """Verifies strict gating before NO_VALID_EDGE can be produced (Section 2 & 5)."""

    def test_7B_test_subset_with_zero_approvals_cannot_authorize_global_no_valid_edge(self):
        """
        B. Six-symbol/test subset evaluates successfully with zero approvals
        => TEST_SUBSET = TRUE
        => NOT global NO_VALID_EDGE
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=6,
            technically_executable_count=17441,
            cost_complete_count=6,
            strategy_analysed_count=6,
            positive_edge_candidate_count=0,
            ai_evaluated_count=0,
            final_approval_count=0,
            orders_submitted_count=0,
            scan_universe_type="TEST_SUBSET",  # Explicit test subset
            all_relevant_candidates_evaluated=False
        )
        self.assertTrue(telem.test_subset)
        self.assertEqual(telem.to_dict()["TEST_SUBSET"], True)
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertNotEqual(telem.classification, ProductionClassification.NO_VALID_EDGE)
        self.assertFalse(telem.market_evaluation_complete)
        self.assertFalse(telem.no_valid_edge_prerequisites_proven)
        self.assertEqual(telem.production_failure_reason, "UNIVERSE_COVERAGE_INCOMPLETE")

    def test_7H_complete_applicable_open_universe_with_zero_positive_edge_allows_no_valid_edge(self):
        """
        H. Complete applicable open-universe evaluation
        + complete product prerequisites
        + zero positive executable net-edge candidates
        => NO_VALID_EDGE allowed (with NO_VALID_EDGE_PREREQUISITES_PROVEN = TRUE).
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            broker_tradability_unknown_count=0,
            open_session_count=5288,
            market_data_requested_count=5288,
            market_data_success_count=5288,
            market_data_failure_count=0,
            current_execution_grade_quote_count=5288,
            technically_executable_count=17441,
            cost_complete_count=5288,
            strategy_analysed_count=5288,
            positive_edge_candidate_count=0,  # Genuine zero edge
            ai_evaluated_count=5288,
            final_approval_count=0,
            orders_submitted_count=0,
            scan_process_completed=True,
            scan_universe_type="FULL_UNIVERSE",
            all_relevant_candidates_evaluated=True,
            universe_discovery_status="COMPLETE",
            broker_tradability_status="RESOLVED_FOR_EVALUATED_SET",
            session_status="RESOLVED",
            market_data_status="CURRENT_AND_EXECUTION_GRADE",
            quote_status="EXECUTABLE",
            bid_ask_status="KNOWN",
            cost_status="COMPLETE",
            technical_execution_status="PROVEN",
            expected_move_decision_status="AVAILABLE",
            ai_allocation_decision_status="AVAILABLE",
            strategy_analysis_status="COMPLETE"
        )
        self.assertEqual(telem.classification, ProductionClassification.NO_VALID_EDGE)
        self.assertEqual(telem.trade_outcome, "NO_VALID_EDGE")
        self.assertTrue(telem.no_valid_edge_prerequisites_proven)
        self.assertTrue(telem.market_evaluation_complete)
        self.assertEqual(telem.market_evaluation_status, "COMPLETE")
        self.assertEqual(len(telem.failures_found), 0)
        self.assertIsNone(telem.production_failure_reason)

    def test_no_valid_edge_forbidden_if_any_prerequisite_is_unproven(self):
        """NO_VALID_EDGE is FORBIDDEN if any prerequisite is UNKNOWN, UNAVAILABLE, or INCOMPLETE."""
        prereq_tests = [
            ("universe_discovery_status", "INCOMPLETE", "UNIVERSE_COVERAGE_INCOMPLETE"),
            ("broker_tradability_status", "UNRESOLVED", "BROKER_TRADABILITY_UNRESOLVED"),
            ("session_status", "METADATA_UNRESOLVED", "SESSION_METADATA_UNRESOLVED"),
            ("market_data_status", "MISSING", "EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING"),
            ("quote_status", "INCOMPLETE", "QUOTE_DATA_INCOMPLETE"),
            ("cost_status", "UNKNOWN", "COST_MODEL_UNKNOWN"),
            ("technical_execution_status", "INCOMPLETE", "EXECUTION_CAPABILITY_COVERAGE_INCOMPLETE"),
            ("expected_move_decision_status", "UNAVAILABLE", "EXPECTED_MOVE_MODEL_UNAVAILABLE"),
            ("ai_allocation_decision_status", "UNAVAILABLE", "AI_ALLOCATION_PROVIDER_UNAVAILABLE"),
        ]
        for field, invalid_val, exp_reason in prereq_tests:
            with self.subTest(field=field):
                kwargs = {
                    "discovered_count": 17566,
                    "broker_tradable_known_count": 17441,
                    "open_session_count": 5288,
                    "current_execution_grade_quote_count": 5288,
                    "technically_executable_count": 17441,
                    "cost_complete_count": 5288,
                    "strategy_analysed_count": 5288,
                    "positive_edge_candidate_count": 0,
                    "scan_universe_type": "FULL_UNIVERSE",
                    "all_relevant_candidates_evaluated": True,
                    "universe_discovery_status": "COMPLETE",
                    "broker_tradability_status": "RESOLVED_FOR_EVALUATED_SET",
                    "session_status": "RESOLVED",
                    "market_data_status": "CURRENT_AND_EXECUTION_GRADE",
                    "quote_status": "EXECUTABLE",
                    "bid_ask_status": "KNOWN",
                    "cost_status": "COMPLETE",
                    "technical_execution_status": "PROVEN",
                    "expected_move_decision_status": "AVAILABLE",
                    "ai_allocation_decision_status": "AVAILABLE",
                    "strategy_analysis_status": "COMPLETE"
                }
                kwargs[field] = invalid_val
                telem = production_telemetry_classifier.classify_run(**kwargs)
                self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
                self.assertNotEqual(telem.classification, ProductionClassification.NO_VALID_EDGE)
                self.assertFalse(telem.market_evaluation_complete)
                self.assertFalse(telem.no_valid_edge_prerequisites_proven)
                self.assertIn(exp_reason, telem.production_failure_reason)


class TestProductFailureClassification(unittest.TestCase):
    """Verifies canonical product failure reason codes (Section 3 & 7)."""

    def test_7A_missing_execution_grade_market_data(self):
        """A. Missing execution-grade market data => PRODUCTION_FAILURE (EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING)."""
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=0,
            market_data_status="MISSING"
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertEqual(telem.production_failure_reason, "EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING")

    def test_7C_execution_capability_incomplete(self):
        """C. Execution capability incomplete => PRODUCTION_FAILURE (EXECUTION_CAPABILITY_COVERAGE_INCOMPLETE)."""
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            technically_executable_count=0,
            technical_execution_status="INCOMPLETE"
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertEqual(telem.production_failure_reason, "EXECUTION_CAPABILITY_COVERAGE_INCOMPLETE")

    def test_7D_cost_state_unknown(self):
        """D. Cost state UNKNOWN => PRODUCTION_FAILURE (COST_MODEL_UNKNOWN)."""
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            cost_complete_count=0,
            cost_status="UNKNOWN"
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertEqual(telem.production_failure_reason, "COST_MODEL_UNKNOWN")

    def test_7E_expected_move_model_unavailable(self):
        """E. Expected-move model unavailable => PRODUCTION_FAILURE (EXPECTED_MOVE_MODEL_UNAVAILABLE)."""
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            technically_executable_count=17441,
            cost_complete_count=5288,
            cost_status="COMPLETE",
            technical_execution_status="PROVEN",
            expected_move_decision_status="UNAVAILABLE"
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertEqual(telem.production_failure_reason, "EXPECTED_MOVE_MODEL_UNAVAILABLE")

    def test_7F_ai_allocation_provider_unavailable(self):
        """F. AI allocation provider unavailable => PRODUCTION_FAILURE (AI_ALLOCATION_PROVIDER_UNAVAILABLE)."""
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            technically_executable_count=17441,
            cost_complete_count=5288,
            cost_status="COMPLETE",
            technical_execution_status="PROVEN",
            expected_move_decision_status="AVAILABLE",
            ai_allocation_decision_status="UNAVAILABLE"
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertEqual(telem.production_failure_reason, "AI_ALLOCATION_PROVIDER_UNAVAILABLE")

    def test_7G_session_metadata_unresolved(self):
        """G. Session metadata unresolved => PRODUCTION_FAILURE (SESSION_METADATA_UNRESOLVED)."""
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            technically_executable_count=17441,
            cost_complete_count=5288,
            cost_status="COMPLETE",
            technical_execution_status="PROVEN",
            metadata_defect=True,
            session_status="METADATA_UNRESOLVED"
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertEqual(telem.production_failure_reason, "SESSION_METADATA_UNRESOLVED")

    def test_7J_broker_execution_error_prevents_valid_order(self):
        """J. Product/broker execution error prevents order => BROKER_EXECUTION_FAILURE, NOT strategy failure."""
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            orders_submitted_count=1,
            broker_execution_error="500 Internal Server Error: Trading212 Order Submission Gateway Timeout"
        )
        self.assertEqual(telem.classification, ProductionClassification.BROKER_EXECUTION_FAILURE)
        self.assertNotEqual(telem.classification, ProductionClassification.STRATEGY_OUTCOME)
        self.assertIn("BROKER_EXECUTION_FAILURE", telem.production_failure_reason)


class TestLossVsProductFailureDistinction(unittest.TestCase):
    """Verifies that trading loss after a valid trade is a STRATEGY OUTCOME, not product failure (Section 9 & 7I)."""

    def test_7I_authorised_trade_subsequent_loss_remains_strategy_trading_outcome(self):
        """
        I. Correctly authorised trade is executed and subsequently loses money
        => product execution remains successful
        => trading result classified as STRATEGY/TRADING OUTCOME
        => NOT reclassified as product failure merely because P&L < 0.
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            technically_executable_count=17441,
            cost_complete_count=5288,
            strategy_analysed_count=5288,
            positive_edge_candidate_count=1,
            orders_submitted_count=0,
            active_holdings_count=0,
            banked_net_profit_today_gbp=-24.50,  # Realised trading loss
            details={"closed_trades_count": 1, "had_trading_loss": True}
        )
        self.assertIn(
            telem.classification,
            (ProductionClassification.STRATEGY_OUTCOME, ProductionClassification.TRADING_LOSS)
        )
        self.assertNotEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertEqual(len(telem.failures_found), 0)
        self.assertIsNone(telem.production_failure_reason)

    def test_three_mutually_distinguishable_states(self):
        """Prove the three core states remain strictly mutually distinguishable."""
        # 1. Trading loss after valid operation
        s1 = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            banked_net_profit_today_gbp=-10.0,
            details={"closed_trades_count": 1}
        )
        # 2. Product inability
        s2 = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            open_session_count=5288,
            current_execution_grade_quote_count=0
        )
        # 3. Complete valid market evaluation + no positive edge
        s3 = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            technically_executable_count=17441,
            cost_complete_count=5288,
            strategy_analysed_count=5288,
            positive_edge_candidate_count=0,
            scan_universe_type="FULL_UNIVERSE",
            all_relevant_candidates_evaluated=True,
            universe_discovery_status="COMPLETE",
            broker_tradability_status="RESOLVED_FOR_EVALUATED_SET",
            session_status="RESOLVED",
            market_data_status="CURRENT_AND_EXECUTION_GRADE",
            quote_status="EXECUTABLE",
            bid_ask_status="KNOWN",
            cost_status="COMPLETE",
            technical_execution_status="PROVEN",
            expected_move_decision_status="AVAILABLE",
            ai_allocation_decision_status="AVAILABLE",
            strategy_analysis_status="COMPLETE"
        )
        # S1 must be STRATEGY_OUTCOME / TRADING_LOSS
        self.assertIn(s1.classification, ("STRATEGY_OUTCOME", "TRADING_LOSS"))
        # S2 must be PRODUCTION_FAILURE
        self.assertEqual(s2.classification, "PRODUCTION_FAILURE")
        # S3 must be NO_VALID_EDGE
        self.assertEqual(s3.classification, "NO_VALID_EDGE")
        # All three must have different classifications
        self.assertNotEqual(s1.classification, s2.classification)
        self.assertNotEqual(s2.classification, s3.classification)
        self.assertNotEqual(s1.classification, s3.classification)


class TestDashboardApiState(unittest.TestCase):
    """Verifies independent dashboard fields and prohibits ambiguous green banners (Section 8 & 10)."""

    def setUp(self):
        self.engine = HitAndRunEngine()

    def test_dashboard_independent_states_on_incomplete_market_evaluation(self):
        """
        Dashboard must independently expose:
        ENGINE_HEALTH = HEALTHY
        SCAN_PROCESS_STATUS = COMPLETED
        MARKET_EVALUATION_STATUS = INCOMPLETE
        TRADE_OUTCOME = NONE
        PRODUCTION_STATUS = FAILURE
        PRODUCTION_FAILURE_REASON = EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=0,
            scan_process_completed=True,
            market_data_status="MISSING"
        )
        dash = production_telemetry_classifier.get_dashboard_status(telem)
        dash_dict = dash.to_dict()

        self.assertEqual(dash.engine_health, "HEALTHY")
        self.assertEqual(dash.scan_process_status, "COMPLETED")
        self.assertEqual(dash.market_evaluation_status, "INCOMPLETE")
        self.assertEqual(dash.trade_outcome, "NONE")
        self.assertEqual(dash.production_status, "FAILURE")
        self.assertEqual(dash.production_failure_reason, "EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING")

        # Invariant: Never show ambiguous green 'NO TRADE — SCAN COMPLETED SUCCESSFULLY'
        banner = dashboard_presenter.render_dashboard_banner(dash)
        self.assertNotIn("NO TRADE — SCAN COMPLETED SUCCESSFULLY", banner)
        self.assertIn("PRODUCTION_STATUS=FAILURE", banner)
        self.assertIn("MARKET_EVALUATION_STATUS=INCOMPLETE", banner)

    def test_all_15_scan_coverage_telemetry_metrics_exposed(self):
        """Verify all 15 required scan coverage telemetry metrics are present and measurable."""
        res = self.engine.evaluate_live_pipeline(
            portfolio_capital_gbp=10000.0,
            available_cash_gbp=10000.0,
            market_snapshots=[]
        )
        required_15 = [
            "discovered_count",
            "broker_tradable_known_count",
            "broker_tradability_unknown_count",
            "open_session_count",
            "market_data_requested_count",
            "market_data_success_count",
            "market_data_failure_count",
            "current_execution_grade_quote_count",
            "technically_executable_count",
            "cost_complete_count",
            "strategy_analysed_count",
            "ai_evaluated_count",
            "positive_edge_candidate_count",
            "final_approval_count",
            "orders_submitted_count"
        ]
        for metric in required_15:
            with self.subTest(metric=metric):
                self.assertIn(metric, res)
                val = res[metric]
                self.assertTrue(isinstance(val, (int, float)) or val == "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
