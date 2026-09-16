"""
PRV Capital - Hit-and-Run Production Failure & Outcome Telemetry
Requirement H: Explicit telemetry distinguishing:
- PRODUCTION_FAILURE (system failure: unscanned universe, stale data, crashes, implementation defects)
- STRATEGY_OUTCOME (system works as designed, trades taken, negative or positive realised P&L)
- NO_VALID_EDGE (universe evaluated, no positive executable edge exists after all costs)
Never uses generic "engine healthy" as a substitute.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.hit_and_run.models import ProductionClassification, ProductionTelemetry


class ProductionFailureClassifier:
    """Classifies engine runtime results into Production Failure, Strategy Outcome, or No Valid Edge."""

    @classmethod
    def classify_run(
        cls,
        discovered_count: int,
        technically_executable_count: int,
        open_session_count: int,
        fresh_quote_count: int,
        opportunity_count: int,
        qualified_count: int,
        active_holdings_count: int,
        banked_net_profit_today_gbp: float,
        remaining_to_100_base_target_gbp: float,
        system_errors: Optional[List[str]] = None,
        lifecycle_running: bool = True,
        order_lifecycle_consistent: bool = True,
        metadata_defect: bool = False,
        details: Optional[Dict[str, Any]] = None
    ) -> ProductionTelemetry:
        now_iso = datetime.now(timezone.utc).isoformat()
        failures: List[str] = list(system_errors or [])
        diag = dict(details or {})

        # -------------------------------------------------------------
        # 1. PRODUCTION_FAILURE Checks
        # -------------------------------------------------------------
        if discovered_count == 0:
            failures.append("PRODUCTION_FAILURE: Broker universe was not scanned (0 discovered instruments).")

        if open_session_count > 0 and fresh_quote_count == 0 and discovered_count > 0:
            failures.append("PRODUCTION_FAILURE: Open sessions exist but market data is completely stale or unavailable.")

        if not lifecycle_running and active_holdings_count > 0:
            failures.append("PRODUCTION_FAILURE: Position lifecycle manager is not running while active holdings exist.")

        if not order_lifecycle_consistent:
            failures.append("PRODUCTION_FAILURE: Order lifecycle state is inconsistent with broker truth.")

        if metadata_defect:
            failures.append("PRODUCTION_FAILURE: Valid broker metadata missing because of implementation defect.")

        # If any production failure conditions are met
        if failures:
            classification = ProductionClassification.PRODUCTION_FAILURE
        # -------------------------------------------------------------
        # 2. STRATEGY_OUTCOME Checks
        # -------------------------------------------------------------
        # System operated as designed, traded, active holdings exist or realised P&L recorded
        elif active_holdings_count > 0 or banked_net_profit_today_gbp != 0.0 or diag.get("closed_trades_count", 0) > 0:
            classification = ProductionClassification.STRATEGY_OUTCOME
        # -------------------------------------------------------------
        # 3. NO_VALID_EDGE Checks
        # -------------------------------------------------------------
        # Full relevant universe successfully scanned and evaluated, but no positive edge after costs
        elif qualified_count == 0 or opportunity_count == 0:
            classification = ProductionClassification.NO_VALID_EDGE
        else:
            classification = ProductionClassification.STRATEGY_OUTCOME

        base_achieved = banked_net_profit_today_gbp >= 100.0

        return ProductionTelemetry(
            timestamp=now_iso,
            classification=classification,
            discovered_count=discovered_count,
            technically_executable_count=technically_executable_count,
            open_session_count=open_session_count,
            fresh_quote_count=fresh_quote_count,
            opportunity_count=opportunity_count,
            qualified_count=qualified_count,
            active_holdings_count=active_holdings_count,
            banked_net_profit_today_gbp=round(banked_net_profit_today_gbp, 2),
            remaining_to_100_base_target_gbp=round(remaining_to_100_base_target_gbp, 2),
            base_target_achieved=base_achieved,
            continue_trading=True,  # Always true per Authoritative Objective
            failures_found=failures,
            details=diag
        )


production_telemetry_classifier = ProductionFailureClassifier()
