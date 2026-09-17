"""
PRV Capital - Hit-and-Run Production Failure & Outcome Telemetry
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Non-Negotiable No-Trade Acceptance Gate:
1. NO_VALID_EDGE may be emitted ONLY when ALL relevant prerequisites are proven:
   - UNIVERSE_DISCOVERY_STATUS = COMPLETE
   - BROKER_TRADABILITY_STATUS = RESOLVED_FOR_EVALUATED_SET
   - SESSION_STATUS = RESOLVED
   - MARKET_DATA_STATUS = CURRENT_AND_EXECUTION_GRADE
   - QUOTE_STATUS = EXECUTABLE
   - BID_ASK_STATUS = KNOWN
   - COST_STATUS = COMPLETE
   - TECHNICAL_EXECUTION_STATUS = PROVEN
   - EXPECTED_MOVE_DECISION_STATUS = AVAILABLE
   - AI_ALLOCATION_DECISION_STATUS = AVAILABLE
   - STRATEGY_ANALYSIS_STATUS = COMPLETE
   - ALL RELEVANT OPEN / EXECUTABLE CANDIDATES WERE ACTUALLY EVALUATED
   and no candidate has positive expected net edge after costs.

2. Product failure must NEVER become NO_VALID_EDGE.
   Missing prerequisites yield PRODUCTION_FAILURE with an exact reason:
   - PRODUCTION_FAILURE: EXECUTION_GRADE_MARKET_DATA_MISSING
   - PRODUCTION_FAILURE: UNIVERSE_COVERAGE_INCOMPLETE
   - PRODUCTION_FAILURE: EXECUTION_CAPABILITY_INCOMPLETE
   - PRODUCTION_FAILURE: QUOTE_DATA_INCOMPLETE
   - PRODUCTION_FAILURE: COST_MODEL_UNKNOWN
   - PRODUCTION_FAILURE: EXPECTED_MOVE_MODEL_UNAVAILABLE
   - PRODUCTION_FAILURE: AI_ALLOCATION_PROVIDER_UNAVAILABLE
   - PRODUCTION_FAILURE: LIFECYCLE_DECISION_MODEL_UNAVAILABLE
   - PRODUCTION_FAILURE: SESSION_METADATA_UNRESOLVED

3. SCAN_PROCESS_COMPLETED != MARKET_EVALUATION_COMPLETE != NO_VALID_EDGE.
   These are independent states.

4. 6-symbol test subset labelled TEST_SUBSET MUST NOT produce NO_VALID_EDGE for the global product.

5. Strategy failure (trading loss after valid execution) vs product failure:
   Trading loss remains STRATEGY_OUTCOME / TRADING_LOSS, never product failure.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.hit_and_run.models import (
    ProductionClassification,
    ProductionTelemetry,
    DashboardScanStatus,
)


class ProductionFailureClassifier:
    """
    Classifies engine runtime results into explicit outcomes and enforces the
    Non-Negotiable No-Trade Acceptance Gate.
    """

    @classmethod
    def classify_run(
        cls,
        discovered_count: Any = 0,
        technically_executable_count: Any = 0,
        open_session_count: Any = 0,
        fresh_quote_count: Any = 0,
        opportunity_count: Any = 0,
        qualified_count: Any = 0,
        active_holdings_count: int = 0,
        banked_net_profit_today_gbp: float = 0.0,
        remaining_to_100_base_target_gbp: float = 100.0,
        system_errors: Optional[List[str]] = None,
        lifecycle_running: bool = True,
        order_lifecycle_consistent: bool = True,
        metadata_defect: bool = False,
        details: Optional[Dict[str, Any]] = None,
        # Extended Scan Coverage Telemetry (Section 5)
        broker_tradable_known_count: Any = "UNKNOWN",
        broker_tradability_unknown_count: Any = "UNKNOWN",
        market_data_requested_count: Any = "UNKNOWN",
        market_data_success_count: Any = "UNKNOWN",
        market_data_failure_count: Any = "UNKNOWN",
        current_execution_grade_quote_count: Any = "UNKNOWN",
        cost_complete_count: Any = "UNKNOWN",
        strategy_analysed_count: Any = "UNKNOWN",
        positive_edge_candidate_count: Any = "UNKNOWN",
        ai_evaluated_count: Any = "UNKNOWN",
        final_approval_count: Any = "UNKNOWN",
        orders_submitted_count: Any = "UNKNOWN",
        # Process & Scope parameters (Section 1, 3, 4)
        scan_process_completed: bool = True,
        scan_universe_type: str = "FULL_UNIVERSE",  # "FULL_UNIVERSE" or "TEST_SUBSET"
        all_relevant_candidates_evaluated: bool = False,
        # Explicit status overrides if caller evaluated them
        universe_discovery_status: Optional[str] = None,
        broker_tradability_status: Optional[str] = None,
        session_status: Optional[str] = None,
        market_data_status: Optional[str] = None,
        quote_status: Optional[str] = None,
        bid_ask_status: Optional[str] = None,
        cost_status: Optional[str] = None,
        technical_execution_status: Optional[str] = None,
        expected_move_decision_status: Optional[str] = None,
        ai_allocation_decision_status: Optional[str] = None,
        strategy_analysis_status: Optional[str] = None,
        broker_execution_error: Optional[str] = None,
    ) -> ProductionTelemetry:
        now_iso = datetime.now(timezone.utc).isoformat()
        failures: List[str] = list(system_errors or [])
        diag = dict(details or {})

        # Reconcile counts from details if caller passed them there
        if broker_tradable_known_count == "UNKNOWN" and "broker_tradable_known_count" in diag:
            broker_tradable_known_count = diag["broker_tradable_known_count"]
        elif broker_tradable_known_count == "UNKNOWN" and "tradable_count" in diag:
            broker_tradable_known_count = diag["tradable_count"]

        if broker_tradability_unknown_count == "UNKNOWN" and "broker_tradability_unknown_count" in diag:
            broker_tradability_unknown_count = diag["broker_tradability_unknown_count"]

        if market_data_requested_count == "UNKNOWN" and "market_data_requested_count" in diag:
            market_data_requested_count = diag["market_data_requested_count"]

        if market_data_success_count == "UNKNOWN" and "market_data_success_count" in diag:
            market_data_success_count = diag["market_data_success_count"]

        if market_data_failure_count == "UNKNOWN" and "market_data_failure_count" in diag:
            market_data_failure_count = diag["market_data_failure_count"]

        if current_execution_grade_quote_count == "UNKNOWN":
            current_execution_grade_quote_count = fresh_quote_count

        if current_execution_grade_quote_count == "UNKNOWN":
            current_execution_grade_quote_count = fresh_quote_count
        elif (fresh_quote_count == 0 or fresh_quote_count == "UNKNOWN") and isinstance(current_execution_grade_quote_count, int):
            fresh_quote_count = current_execution_grade_quote_count

        if market_data_success_count == "UNKNOWN":
            market_data_success_count = current_execution_grade_quote_count if isinstance(current_execution_grade_quote_count, int) else open_session_count

        if cost_complete_count == "UNKNOWN" and "cost_complete_count" in diag:
            cost_complete_count = diag["cost_complete_count"]
        elif cost_complete_count == "UNKNOWN" and isinstance(current_execution_grade_quote_count, int) and current_execution_grade_quote_count > 0:
            cost_complete_count = current_execution_grade_quote_count

        if strategy_analysed_count == "UNKNOWN":
            strategy_analysed_count = opportunity_count if opportunity_count != 0 else (current_execution_grade_quote_count if isinstance(current_execution_grade_quote_count, int) else 0)

        if positive_edge_candidate_count == "UNKNOWN":
            positive_edge_candidate_count = qualified_count

        if ai_evaluated_count == "UNKNOWN":
            ai_evaluated_count = diag.get("ai_evaluated_count", 0)

        if final_approval_count == "UNKNOWN":
            final_approval_count = diag.get("final_approval_count", 0)

        if orders_submitted_count == "UNKNOWN":
            orders_submitted_count = diag.get("orders_submitted_count", 0)

        # -------------------------------------------------------------
        # 1. SCOPE CHECK (Section 4 & Acceptance Test A)
        # -------------------------------------------------------------
        # A test subset MUST NOT produce NO_VALID_EDGE for the global product.
        is_test_subset = (scan_universe_type == "TEST_SUBSET")
        if is_test_subset:
            # If no trades executed on test subset, cannot claim market has no edge
            if orders_submitted_count in ("UNKNOWN", 0) and active_holdings_count == 0 and banked_net_profit_today_gbp == 0.0:
                failures.append(
                    "PRODUCTION_FAILURE: UNIVERSE_COVERAGE_INCOMPLETE "
                    "(Test subset evaluated; cannot declare NO_VALID_EDGE for global product)"
                )

        # -------------------------------------------------------------
        # 2. PREREQUISITE EVALUATIONS (Section 1 & 2)
        # -------------------------------------------------------------
        # A. Universe Discovery
        if universe_discovery_status is None:
            if discovered_count in ("UNKNOWN", 0):
                universe_discovery_status = "INCOMPLETE"
                failures.append("PRODUCTION_FAILURE: UNIVERSE_COVERAGE_INCOMPLETE (0 discovered instruments)")
            else:
                universe_discovery_status = "COMPLETE"
        elif universe_discovery_status != "COMPLETE":
            failures.append("PRODUCTION_FAILURE: UNIVERSE_COVERAGE_INCOMPLETE")

        # B. Broker Tradability
        if broker_tradability_status is None:
            if broker_tradability_unknown_count not in ("UNKNOWN", 0) and broker_tradable_known_count in ("UNKNOWN", 0):
                broker_tradability_status = "UNRESOLVED"
                failures.append("PRODUCTION_FAILURE: BROKER_TRADABILITY_UNRESOLVED")
            else:
                broker_tradability_status = "RESOLVED_FOR_EVALUATED_SET"
        elif broker_tradability_status != "RESOLVED_FOR_EVALUATED_SET":
            failures.append("PRODUCTION_FAILURE: BROKER_TRADABILITY_UNRESOLVED")

        # C. Session Metadata
        if session_status is None:
            if metadata_defect:
                session_status = "METADATA_UNRESOLVED"
                failures.append("PRODUCTION_FAILURE: SESSION_METADATA_UNRESOLVED")
            else:
                session_status = "RESOLVED"
        elif session_status != "RESOLVED":
            failures.append("PRODUCTION_FAILURE: SESSION_METADATA_UNRESOLVED")

        # D. Market Data Status (Section 2B & 3)
        if market_data_status is None:
            if open_session_count not in ("UNKNOWN", 0):
                has_quotes = (
                    (isinstance(current_execution_grade_quote_count, int) and current_execution_grade_quote_count > 0) or
                    (isinstance(fresh_quote_count, int) and fresh_quote_count > 0)
                )
                if not has_quotes or market_data_success_count == 0:
                    market_data_status = "MISSING"
                    failures.append("PRODUCTION_FAILURE: EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING")
                else:
                    market_data_status = "CURRENT_AND_EXECUTION_GRADE"
            else:
                market_data_status = "CURRENT_AND_EXECUTION_GRADE"
        elif market_data_status != "CURRENT_AND_EXECUTION_GRADE":
            failures.append("PRODUCTION_FAILURE: EXECUTION_GRADE_MARKET_DATA_SOURCE_MISSING")

        # E. Quote Status & Bid-Ask Status (Section 2D & 3)
        if quote_status is None:
            if open_session_count not in ("UNKNOWN", 0) and current_execution_grade_quote_count in ("UNKNOWN", 0):
                quote_status = "INCOMPLETE"
                bid_ask_status = bid_ask_status or "UNKNOWN"
                failures.append("PRODUCTION_FAILURE: QUOTE_DATA_INCOMPLETE")
            else:
                quote_status = "EXECUTABLE"
                bid_ask_status = bid_ask_status or "KNOWN"
        elif quote_status != "EXECUTABLE":
            failures.append("PRODUCTION_FAILURE: QUOTE_DATA_INCOMPLETE")

        if bid_ask_status is None:
            bid_ask_status = "KNOWN" if quote_status == "EXECUTABLE" else "UNKNOWN"
        elif bid_ask_status != "KNOWN":
            failures.append("PRODUCTION_FAILURE: QUOTE_DATA_INCOMPLETE (Bid/Ask unknown)")

        # F. Cost Status (Section 2E & 3)
        if cost_status is None:
            if open_session_count not in ("UNKNOWN", 0) and cost_complete_count in ("UNKNOWN", 0):
                cost_status = "UNKNOWN"
                failures.append("PRODUCTION_FAILURE: COST_MODEL_UNKNOWN")
            else:
                cost_status = "COMPLETE"
        elif cost_status != "COMPLETE":
            failures.append("PRODUCTION_FAILURE: COST_MODEL_UNKNOWN")

        # G. Technical Execution Capability (Section 2C & 3)
        if technical_execution_status is None:
            if technically_executable_count in ("UNKNOWN", 0):
                technical_execution_status = "INCOMPLETE"
                failures.append("PRODUCTION_FAILURE: EXECUTION_CAPABILITY_COVERAGE_INCOMPLETE")
            else:
                technical_execution_status = "PROVEN"
        elif technical_execution_status != "PROVEN":
            failures.append("PRODUCTION_FAILURE: EXECUTION_CAPABILITY_COVERAGE_INCOMPLETE")

        # H. Expected Move Decision Model (Section 2F & 3)
        if expected_move_decision_status is None:
            if diag.get("expected_move_model_available") is False or diag.get("expected_move_model_status") == "EXPECTED_MOVE_MODEL_UNAVAILABLE":
                expected_move_decision_status = "UNAVAILABLE"
                failures.append("PRODUCTION_FAILURE: EXPECTED_MOVE_MODEL_UNAVAILABLE")
            else:
                expected_move_decision_status = "AVAILABLE"
        elif expected_move_decision_status != "AVAILABLE":
            failures.append("PRODUCTION_FAILURE: EXPECTED_MOVE_MODEL_UNAVAILABLE")

        # I. AI Allocation Provider (Section 2G)
        if ai_allocation_decision_status is None:
            ai_stat = diag.get("ai_allocation_status", "")
            if diag.get("ai_allocation_provider_available") is False or ai_stat in ("NO_AI_DECISION", "PROVIDER_UNAVAILABLE", "UNAVAILABLE"):
                ai_allocation_decision_status = "UNAVAILABLE"
                failures.append("PRODUCTION_FAILURE: AI_ALLOCATION_PROVIDER_UNAVAILABLE")
            else:
                ai_allocation_decision_status = "AVAILABLE"
        elif ai_allocation_decision_status != "AVAILABLE":
            failures.append("PRODUCTION_FAILURE: AI_ALLOCATION_PROVIDER_UNAVAILABLE")

        # J. Strategy Analysis Status
        if strategy_analysis_status is None:
            if diag.get("strategy_analysis_status") == "UNAVAILABLE":
                strategy_analysis_status = "UNAVAILABLE"
                failures.append("PRODUCTION_FAILURE: STRATEGY_DECISION_UNAVAILABLE")
            else:
                strategy_analysis_status = "COMPLETE"
        elif strategy_analysis_status != "COMPLETE":
            failures.append("PRODUCTION_FAILURE: STRATEGY_DECISION_UNAVAILABLE")

        # K. Lifecycle Manager Status
        if not lifecycle_running and active_holdings_count > 0:
            failures.append("PRODUCTION_FAILURE: LIFECYCLE_DECISION_MODEL_UNAVAILABLE")

        # L. Order Lifecycle State
        if not order_lifecycle_consistent:
            failures.append("PRODUCTION_FAILURE: Order lifecycle state is inconsistent with broker truth.")

        # M. Broker Execution Failure
        if broker_execution_error:
            failures.append(f"BROKER_EXECUTION_FAILURE: {broker_execution_error}")

        # Deduplicate failures preserving order
        seen_failures = set()
        unique_failures = []
        for f in failures:
            if f not in seen_failures:
                seen_failures.add(f)
                unique_failures.append(f)
        failures = unique_failures

        primary_failure_reason = failures[0] if failures else None

        # -------------------------------------------------------------
        # 3. OUTCOME CLASSIFICATION (Section 1, 6, 8)
        # -------------------------------------------------------------
        # Allowed high-level outcomes:
        # TRADE_EXECUTED, NO_VALID_EDGE, PRODUCTION_FAILURE,
        # BROKER_EXECUTION_FAILURE, STRATEGY_DECISION_UNAVAILABLE,
        # STRATEGY_OUTCOME, TRADING_LOSS

        has_broker_exec_err = any(f.startswith("BROKER_EXECUTION_FAILURE") for f in failures)
        has_strategy_unavailable = (strategy_analysis_status == "UNAVAILABLE")

        # Case 1: Active broker execution failure
        if has_broker_exec_err:
            classification = ProductionClassification.BROKER_EXECUTION_FAILURE
            market_evaluation_complete = False
            no_valid_edge_prerequisites_proven = False
            broker_failures = [f for f in failures if f.startswith("BROKER_EXECUTION_FAILURE")]
            if broker_failures:
                primary_failure_reason = broker_failures[0]

        # Case 2: Orders submitted in this cycle
        elif orders_submitted_count not in ("UNKNOWN", 0) and orders_submitted_count > 0:
            classification = ProductionClassification.TRADE_EXECUTED
            market_evaluation_complete = True
            no_valid_edge_prerequisites_proven = False

        # Case 3: Active holdings exist (currently in trade)
        elif active_holdings_count > 0:
            classification = ProductionClassification.STRATEGY_OUTCOME
            market_evaluation_complete = True
            no_valid_edge_prerequisites_proven = False

        # Case 4: Closed trade P&L exists today
        elif banked_net_profit_today_gbp != 0.0 or diag.get("closed_trades_count", 0) > 0:
            if banked_net_profit_today_gbp < 0.0 or diag.get("had_trading_loss", False):
                classification = ProductionClassification.TRADING_LOSS
            else:
                classification = ProductionClassification.STRATEGY_OUTCOME
            market_evaluation_complete = True
            no_valid_edge_prerequisites_proven = False

        # Case 5: Zero orders, zero active holdings -> strictly evaluate NO_VALID_EDGE Prerequisites
        else:
            all_prereqs_proven = (
                not is_test_subset and
                universe_discovery_status == "COMPLETE" and
                broker_tradability_status == "RESOLVED_FOR_EVALUATED_SET" and
                session_status == "RESOLVED" and
                market_data_status == "CURRENT_AND_EXECUTION_GRADE" and
                quote_status == "EXECUTABLE" and
                bid_ask_status == "KNOWN" and
                cost_status == "COMPLETE" and
                technical_execution_status == "PROVEN" and
                expected_move_decision_status == "AVAILABLE" and
                ai_allocation_decision_status == "AVAILABLE" and
                strategy_analysis_status == "COMPLETE" and
                all_relevant_candidates_evaluated is True and
                len(failures) == 0
            )

            if all_prereqs_proven:
                classification = ProductionClassification.NO_VALID_EDGE
                no_valid_edge_prerequisites_proven = True
                market_evaluation_complete = True
                primary_failure_reason = None
            else:
                if has_strategy_unavailable:
                    classification = ProductionClassification.STRATEGY_DECISION_UNAVAILABLE
                else:
                    classification = ProductionClassification.PRODUCTION_FAILURE
                no_valid_edge_prerequisites_proven = False
                market_evaluation_complete = False
                if not failures:
                    failures.append("PRODUCTION_FAILURE: UNVERIFIED_PREREQUISITES")
                    primary_failure_reason = failures[0]

        base_achieved = banked_net_profit_today_gbp >= 100.0

        # Determine independent scan outcome fields (Section 1)
        scan_process_status = "COMPLETED" if scan_process_completed else "FAILED"
        market_evaluation_status = "COMPLETE" if market_evaluation_complete else "INCOMPLETE"

        if classification == ProductionClassification.TRADE_EXECUTED or (isinstance(orders_submitted_count, int) and orders_submitted_count > 0):
            trade_outcome = "TRADE_EXECUTED"
        elif classification == ProductionClassification.NO_VALID_EDGE:
            trade_outcome = "NO_VALID_EDGE"
        elif active_holdings_count > 0:
            trade_outcome = "HOLDING_ACTIVE"
        else:
            trade_outcome = "NONE"

        # Extract clean canonical production failure reason
        production_failure_reason = None
        if len(failures) > 0 and classification not in (
            ProductionClassification.TRADE_EXECUTED,
            ProductionClassification.STRATEGY_OUTCOME,
            ProductionClassification.TRADING_LOSS
        ):
            if classification == ProductionClassification.BROKER_EXECUTION_FAILURE:
                raw_f = next((f for f in failures if f.startswith("BROKER_EXECUTION_FAILURE")), failures[0])
            else:
                raw_f = failures[0]
            if raw_f.startswith("PRODUCTION_FAILURE: "):
                production_failure_reason = raw_f.replace("PRODUCTION_FAILURE: ", "").strip()
            elif raw_f.startswith("BROKER_EXECUTION_FAILURE"):
                production_failure_reason = "BROKER_EXECUTION_FAILURE"
            else:
                production_failure_reason = raw_f
            if "(" in production_failure_reason:
                production_failure_reason = production_failure_reason.split("(")[0].strip()

        test_subset = (scan_universe_type == "TEST_SUBSET")

        return ProductionTelemetry(
            timestamp=now_iso,
            classification=classification,
            discovered_count=discovered_count,
            broker_tradable_known_count=broker_tradable_known_count,
            broker_tradability_unknown_count=broker_tradability_unknown_count,
            open_session_count=open_session_count,
            market_data_requested_count=market_data_requested_count,
            market_data_success_count=market_data_success_count,
            market_data_failure_count=market_data_failure_count,
            current_execution_grade_quote_count=current_execution_grade_quote_count,
            technically_executable_count=technically_executable_count,
            cost_complete_count=cost_complete_count,
            strategy_analysed_count=strategy_analysed_count,
            positive_edge_candidate_count=positive_edge_candidate_count,
            ai_evaluated_count=ai_evaluated_count,
            final_approval_count=final_approval_count,
            orders_submitted_count=orders_submitted_count,
            scan_process_completed=scan_process_completed,
            market_evaluation_complete=market_evaluation_complete,
            no_valid_edge_prerequisites_proven=no_valid_edge_prerequisites_proven,
            scan_universe_type=scan_universe_type,
            test_subset=test_subset,
            scan_process_status=scan_process_status,
            market_evaluation_status=market_evaluation_status,
            trade_outcome=trade_outcome,
            production_failure_reason=production_failure_reason,
            universe_discovery_status=universe_discovery_status,
            broker_tradability_status=broker_tradability_status,
            session_status=session_status,
            market_data_status=market_data_status,
            quote_status=quote_status,
            bid_ask_status=bid_ask_status,
            cost_status=cost_status,
            technical_execution_status=technical_execution_status,
            expected_move_decision_status=expected_move_decision_status,
            ai_allocation_decision_status=ai_allocation_decision_status,
            strategy_analysis_status=strategy_analysis_status,
            active_holdings_count=active_holdings_count,
            banked_net_profit_today_gbp=round(banked_net_profit_today_gbp, 2),
            remaining_to_100_base_target_gbp=round(remaining_to_100_base_target_gbp, 2),
            base_target_achieved=base_achieved,
            continue_trading=True,
            failures_found=failures,
            primary_failure_reason=primary_failure_reason,
            details=diag,
            fresh_quote_count=current_execution_grade_quote_count if isinstance(current_execution_grade_quote_count, int) else 0,
            opportunity_count=strategy_analysed_count if isinstance(strategy_analysed_count, int) else 0,
            qualified_count=positive_edge_candidate_count if isinstance(positive_edge_candidate_count, int) else 0
        )

    @classmethod
    def get_dashboard_status(cls, telemetry: ProductionTelemetry) -> DashboardScanStatus:
        """
        Derives independent dashboard status fields to prevent healthy infrastructure
        from being mistaken for successful trading capability (Section 8 & 10).
        """
        # Engine Health: Daemon heartbeat
        engine_health = "HEALTHY" if telemetry.scan_process_completed else "UNHEALTHY"

        # Scan Process Status: Did the process run?
        scan_process_status = telemetry.scan_process_status

        # Market Evaluation Status: Was the relevant market evaluated?
        market_evaluation_status = telemetry.market_evaluation_status

        # Trade Outcome
        trade_outcome = telemetry.trade_outcome

        # Production Status
        if telemetry.classification in (
            ProductionClassification.TRADE_EXECUTED,
            ProductionClassification.STRATEGY_OUTCOME,
            ProductionClassification.TRADING_LOSS,
            ProductionClassification.NO_VALID_EDGE
        ) and len(telemetry.failures_found) == 0:
            production_status = "OK"
            failure_reason = None
        else:
            production_status = "FAILURE"
            failure_reason = telemetry.production_failure_reason or telemetry.primary_failure_reason or (telemetry.failures_found[0] if telemetry.failures_found else "UNRESOLVED_FAILURE")

        return DashboardScanStatus(
            engine_health=engine_health,
            scan_process_status=scan_process_status,
            market_evaluation_status=market_evaluation_status,
            trade_outcome=trade_outcome,
            production_status=production_status,
            production_failure_reason=failure_reason,
            no_valid_edge_prerequisites_proven=telemetry.no_valid_edge_prerequisites_proven,
            scan_universe_type=telemetry.scan_universe_type,
            test_subset=telemetry.test_subset
        )


production_telemetry_classifier = ProductionFailureClassifier()
