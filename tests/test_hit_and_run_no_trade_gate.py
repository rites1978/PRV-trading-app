"""
Unit Tests: Non-Negotiable No-Trade Acceptance Gate & Failure Classification
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Verifies:
A. 6-symbol test subset + no approvals MUST NOT produce NO_VALID_EDGE for the global product.
B. Market-data provider unavailable => PRODUCTION_FAILURE (EXECUTION_GRADE_MARKET_DATA_MISSING), NOT NO_VALID_EDGE.
C. Execution capability incomplete => PRODUCTION_FAILURE (EXECUTION_CAPABILITY_INCOMPLETE), NOT NO_VALID_EDGE.
D. AI allocation provider unavailable => PRODUCTION_FAILURE (AI_ALLOCATION_PROVIDER_UNAVAILABLE), NOT NO_VALID_EDGE.
E. Cost status UNKNOWN => PRODUCTION_FAILURE (COST_MODEL_UNKNOWN), NOT NO_VALID_EDGE.
F. Full relevant open universe successfully evaluated, all required capability/data states complete,
   zero executable positive-net-edge candidates => NO_VALID_EDGE is allowed, with NO_VALID_EDGE_PREREQUISITES_PROVEN = TRUE.
G. Valid authorised trade that later loses money remains a STRATEGY/TRADING OUTCOME (or TRADING_LOSS),
   not a product-availability failure.
H. Scan completion != Market evaluation complete: SCAN_PROCESS_COMPLETED=True with MARKET_EVALUATION_COMPLETE=False
   correctly produces PRODUCTION_FAILURE.
I. All 15 required scan coverage telemetry metrics are exposed.
J. Dashboard state independently displays ENGINE_HEALTH, SCAN_PROCESS_STATUS, MARKET_EVALUATION_STATUS,
   TRADE_OUTCOME, PRODUCTION_STATUS, and PRODUCTION_FAILURE_REASON, and NEVER shows ambiguous
   'NO TRADE — SCAN COMPLETED SUCCESSFULLY' when evaluation was incomplete.
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


class TestNonNegotiableNoTradeGate(unittest.TestCase):

    def setUp(self):
        self.engine = HitAndRunEngine()

    def test_A_test_subset_with_no_approvals_must_not_produce_no_valid_edge(self):
        """
        A. 6-symbol test subset + no approvals MUST NOT produce NO_VALID_EDGE for the global product.
        Must produce PRODUCTION_FAILURE with UNIVERSE_COVERAGE_INCOMPLETE.
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
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertNotEqual(telem.classification, ProductionClassification.NO_VALID_EDGE)
        self.assertFalse(telem.market_evaluation_complete)
        self.assertFalse(telem.no_valid_edge_prerequisites_proven)
        self.assertTrue(any("UNIVERSE_COVERAGE_INCOMPLETE" in f for f in telem.failures_found))

    def test_B_market_data_provider_unavailable_yields_production_failure(self):
        """
        B. Market-data provider unavailable => PRODUCTION_FAILURE, NOT NO_VALID_EDGE.
        Reason: EXECUTION_GRADE_MARKET_DATA_MISSING.
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=0,  # No market data
            market_data_success_count=0,
            market_data_status="MISSING",
            technically_executable_count=17441,
            cost_complete_count=0,
            strategy_analysed_count=0,
            positive_edge_candidate_count=0,
            ai_evaluated_count=0,
            final_approval_count=0,
            orders_submitted_count=0,
            all_relevant_candidates_evaluated=False
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertNotEqual(telem.classification, ProductionClassification.NO_VALID_EDGE)
        self.assertFalse(telem.market_evaluation_complete)
        self.assertFalse(telem.no_valid_edge_prerequisites_proven)
        self.assertIn("EXECUTION_GRADE_MARKET_DATA_MISSING", telem.primary_failure_reason)

    def test_C_execution_capability_incomplete_yields_production_failure(self):
        """
        C. Execution capability incomplete => PRODUCTION_FAILURE, NOT NO_VALID_EDGE.
        Reason: EXECUTION_CAPABILITY_INCOMPLETE.
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            market_data_status="CURRENT_AND_EXECUTION_GRADE",
            technically_executable_count=0,  # Incomplete technical execution
            technical_execution_status="INCOMPLETE",
            cost_complete_count=5288,
            strategy_analysed_count=5288,
            positive_edge_candidate_count=0,
            ai_evaluated_count=0,
            final_approval_count=0,
            orders_submitted_count=0,
            all_relevant_candidates_evaluated=False
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertNotEqual(telem.classification, ProductionClassification.NO_VALID_EDGE)
        self.assertFalse(telem.market_evaluation_complete)
        self.assertFalse(telem.no_valid_edge_prerequisites_proven)
        self.assertIn("EXECUTION_CAPABILITY_INCOMPLETE", telem.primary_failure_reason)

    def test_D_ai_allocation_provider_unavailable_yields_production_failure(self):
        """
        D. AI allocation provider unavailable => PRODUCTION_FAILURE, NOT NO_VALID_EDGE.
        Reason: AI_ALLOCATION_PROVIDER_UNAVAILABLE.
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            market_data_status="CURRENT_AND_EXECUTION_GRADE",
            technically_executable_count=17441,
            technical_execution_status="PROVEN",
            cost_complete_count=5288,
            cost_status="COMPLETE",
            strategy_analysed_count=5288,
            positive_edge_candidate_count=5,
            ai_allocation_decision_status="UNAVAILABLE",  # AI Provider missing
            final_approval_count=0,
            orders_submitted_count=0,
            all_relevant_candidates_evaluated=True
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertNotEqual(telem.classification, ProductionClassification.NO_VALID_EDGE)
        self.assertFalse(telem.market_evaluation_complete)
        self.assertFalse(telem.no_valid_edge_prerequisites_proven)
        self.assertIn("AI_ALLOCATION_PROVIDER_UNAVAILABLE", telem.primary_failure_reason)

    def test_E_cost_status_unknown_yields_production_failure(self):
        """
        E. Cost status UNKNOWN => PRODUCTION_FAILURE, NOT NO_VALID_EDGE.
        Reason: COST_MODEL_UNKNOWN.
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            market_data_status="CURRENT_AND_EXECUTION_GRADE",
            technically_executable_count=17441,
            technical_execution_status="PROVEN",
            cost_complete_count=0,  # Unknown costs
            cost_status="UNKNOWN",
            strategy_analysed_count=5288,
            positive_edge_candidate_count=0,
            ai_evaluated_count=0,
            final_approval_count=0,
            orders_submitted_count=0,
            all_relevant_candidates_evaluated=True
        )
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertNotEqual(telem.classification, ProductionClassification.NO_VALID_EDGE)
        self.assertFalse(telem.market_evaluation_complete)
        self.assertFalse(telem.no_valid_edge_prerequisites_proven)
        self.assertIn("COST_MODEL_UNKNOWN", telem.primary_failure_reason)

    def test_F_full_relevant_open_universe_evaluated_with_zero_edge_yields_no_valid_edge(self):
        """
        F. Full relevant open universe successfully evaluated, all required capability/data states complete,
        zero executable positive-net-edge candidates => NO_VALID_EDGE is allowed.
        Prerequisites proven = True.
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
            positive_edge_candidate_count=0,  # Zero positive edge candidates
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
        self.assertTrue(telem.no_valid_edge_prerequisites_proven)
        self.assertTrue(telem.market_evaluation_complete)
        self.assertEqual(len(telem.failures_found), 0)
        self.assertIsNone(telem.primary_failure_reason)

    def test_G_valid_trade_loss_remains_strategy_outcome_not_product_failure(self):
        """
        G. A valid authorised trade that later loses money remains a STRATEGY/TRADING OUTCOME,
        not a product-availability failure.
        """
        # Scenario: 1 trade closed today with £15 loss
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=5288,
            technically_executable_count=17441,
            cost_complete_count=5288,
            strategy_analysed_count=5288,
            positive_edge_candidate_count=1,
            ai_evaluated_count=1,
            final_approval_count=1,
            orders_submitted_count=0,  # Completed previous order
            active_holdings_count=0,
            banked_net_profit_today_gbp=-15.00,  # Negative realized P&L
            details={"closed_trades_count": 1, "had_trading_loss": True}
        )
        self.assertIn(
            telem.classification,
            (ProductionClassification.STRATEGY_OUTCOME, ProductionClassification.TRADING_LOSS)
        )
        self.assertNotEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)
        self.assertEqual(len(telem.failures_found), 0)

    def test_H_scan_process_completed_decoupled_from_market_evaluation_complete(self):
        """
        H. Scan completion != Market evaluation complete.
        SCAN_PROCESS_COMPLETED = TRUE with MARKET_EVALUATION_COMPLETE = FALSE
        correctly produces PRODUCTION_FAILURE.
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=0,
            scan_process_completed=True,  # Loop did not crash
            market_data_status="MISSING",
            all_relevant_candidates_evaluated=False
        )
        self.assertTrue(telem.scan_process_completed)
        self.assertFalse(telem.market_evaluation_complete)
        self.assertEqual(telem.classification, ProductionClassification.PRODUCTION_FAILURE)

    def test_I_required_coverage_telemetry_contains_all_15_fields(self):
        """
        I. Verify that every production-style scan result exposes all 15 required coverage fields.
        """
        res = self.engine.evaluate_live_pipeline(
            portfolio_capital_gbp=10000.0,
            available_cash_gbp=10000.0,
            market_snapshots=[]
        )
        required_keys = [
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
            "positive_edge_candidate_count",
            "ai_evaluated_count",
            "final_approval_count",
            "orders_submitted_count"
        ]
        for k in required_keys:
            with self.subTest(key=k):
                self.assertIn(k, res)

    def test_J_dashboard_state_never_shows_healthy_no_trade_when_incomplete(self):
        """
        J. The new dashboard must never show a green/healthy 'NO TRADE — SCAN COMPLETED SUCCESSFULLY'
        when market evaluation was incomplete.
        Must independently display:
        ENGINE_HEALTH = HEALTHY
        SCAN_PROCESS_STATUS = COMPLETED
        MARKET_EVALUATION_STATUS = INCOMPLETE
        TRADE_OUTCOME = NONE
        PRODUCTION_STATUS = FAILURE
        REASON = EXECUTION_GRADE_MARKET_DATA_MISSING
        """
        telem = production_telemetry_classifier.classify_run(
            discovered_count=17566,
            broker_tradable_known_count=17441,
            open_session_count=5288,
            current_execution_grade_quote_count=0,  # Missing data
            scan_process_completed=True,
            market_data_status="MISSING"
        )
        dashboard_status = production_telemetry_classifier.get_dashboard_status(telem)
        banner = dashboard_presenter.render_dashboard_banner(dashboard_status)

        # Assert independent fields
        self.assertEqual(dashboard_status.engine_health, "HEALTHY")
        self.assertEqual(dashboard_status.scan_process_status, "COMPLETED")
        self.assertEqual(dashboard_status.market_evaluation_status, "INCOMPLETE")
        self.assertEqual(dashboard_status.trade_outcome, "NONE")
        self.assertEqual(dashboard_status.production_status, "FAILURE")
        self.assertIn("EXECUTION_GRADE_MARKET_DATA_MISSING", dashboard_status.production_failure_reason)

        # Prohibit dangerous legacy banner
        self.assertNotIn("NO TRADE — SCAN COMPLETED SUCCESSFULLY", banner)
        self.assertIn("PRODUCTION_STATUS=FAILURE", banner)
        self.assertIn("MARKET_EVALUATION_STATUS=INCOMPLETE", banner)


if __name__ == "__main__":
    unittest.main()
