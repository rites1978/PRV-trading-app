"""
PRV Capital - Hit-and-Run Independent Dashboard View & Outcome Presenter
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md (Section 10)

Enforces:
The new dashboard must never show a green/healthy:
"NO TRADE — SCAN COMPLETED SUCCESSFULLY"
when market evaluation was incomplete.

Displays independently:
- ENGINE_HEALTH
- SCAN_PROCESS_STATUS
- MARKET_EVALUATION_STATUS
- TRADE_OUTCOME
- PRODUCTION_STATUS
- PRODUCTION_FAILURE_REASON
"""
from typing import Dict, Any, Optional
from src.hit_and_run.models import DashboardScanStatus


class HitAndRunDashboardPresenter:
    """Independent dashboard view presenter for Hit-and-Run scanning."""

    @staticmethod
    def render_dashboard_banner(status: DashboardScanStatus) -> str:
        """
        Renders an explicit textual or badge representation of the scan outcome.
        PROHIBITS ambiguous 'NO TRADE — SCAN COMPLETED SUCCESSFULLY' when evaluation was incomplete.
        """
        if status.market_evaluation_status == "INCOMPLETE":
            # Must show failure reason, NEVER ambiguous 'no trade'
            reason = status.production_failure_reason or "UNRESOLVED_FAILURE"
            return (
                f"ENGINE_HEALTH={status.engine_health} | "
                f"SCAN_PROCESS_STATUS={status.scan_process_status} | "
                f"MARKET_EVALUATION_STATUS=INCOMPLETE | "
                f"TRADE_OUTCOME={status.trade_outcome} | "
                f"PRODUCTION_STATUS=FAILURE | "
                f"REASON={reason}"
            )

        if status.trade_outcome == "TRADE_EXECUTED":
            return (
                f"ENGINE_HEALTH={status.engine_health} | "
                f"SCAN_PROCESS_STATUS={status.scan_process_status} | "
                f"MARKET_EVALUATION_STATUS=COMPLETE | "
                f"TRADE_OUTCOME=TRADE_EXECUTED | "
                f"PRODUCTION_STATUS=OK"
            )

        if status.trade_outcome == "NO_VALID_EDGE":
            if status.no_valid_edge_prerequisites_proven:
                return (
                    f"ENGINE_HEALTH={status.engine_health} | "
                    f"SCAN_PROCESS_STATUS={status.scan_process_status} | "
                    f"MARKET_EVALUATION_STATUS=COMPLETE | "
                    f"TRADE_OUTCOME=NO_VALID_EDGE | "
                    f"PRODUCTION_STATUS=OK (PREREQUISITES_PROVEN)"
                )
            else:
                return (
                    f"ENGINE_HEALTH={status.engine_health} | "
                    f"SCAN_PROCESS_STATUS={status.scan_process_status} | "
                    f"MARKET_EVALUATION_STATUS=INCOMPLETE | "
                    f"TRADE_OUTCOME=NONE | "
                    f"PRODUCTION_STATUS=FAILURE | "
                    f"REASON=UNVERIFIED_PREREQUISITES"
                )

        return (
            f"ENGINE_HEALTH={status.engine_health} | "
            f"SCAN_PROCESS_STATUS={status.scan_process_status} | "
            f"MARKET_EVALUATION_STATUS={status.market_evaluation_status} | "
            f"TRADE_OUTCOME={status.trade_outcome} | "
            f"PRODUCTION_STATUS={status.production_status}"
        )

    @staticmethod
    def format_dashboard_view(status: DashboardScanStatus) -> Dict[str, Any]:
        """Returns the structured dictionary required for dashboard UI components."""
        return {
            "ENGINE_HEALTH": status.engine_health,
            "SCAN_PROCESS_STATUS": status.scan_process_status,
            "MARKET_EVALUATION_STATUS": status.market_evaluation_status,
            "TRADE_OUTCOME": status.trade_outcome,
            "PRODUCTION_STATUS": status.production_status,
            "PRODUCTION_FAILURE_REASON": status.production_failure_reason,
            "NO_VALID_EDGE_PREREQUISITES_PROVEN": status.no_valid_edge_prerequisites_proven,
            "SCAN_UNIVERSE_TYPE": status.scan_universe_type,
            "BANNER_TEXT": HitAndRunDashboardPresenter.render_dashboard_banner(status)
        }


dashboard_presenter = HitAndRunDashboardPresenter()
