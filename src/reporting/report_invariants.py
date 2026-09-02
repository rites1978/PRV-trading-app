"""
🏛️ PRV CAPITAL | REPORT INVARIANT ENFORCEMENT GUARD
Guarantees 100% data provenance, single-snapshot integrity, and clean-slate challenge adherence.

MANDATORY INVARIANTS (If ANY fails -> REPORT_STATUS = FAILED_RECONCILIATION):
1. position_count == broker_position_count
2. sum(displayed_position_values) == invested_value (tolerance: £0.00)
3. sum(displayed_unrealized_pnl) == portfolio_unrealized_pnl (tolerance: £0.00)
4. cash + invested_value == NAV (tolerance: £0.00)
5. NAV - £50,000.00 == challenge_account_pnl (tolerance: £0.00)
6. pnl_bridge_variance == £0.00
7. all sections/pages share the exact same snapshot_id
8. all_report_tickers subset_of (current_holdings | explicit_watchlist)
9. every attribution_trade_id belongs_to challenge_id
"""
from typing import Dict, Any, List, Set, Tuple
from src.config.settings import settings


class ReportInvariantGuard:
    CHALLENGE_ID = "CHALLENGE_20260902_50K_RESET"
    EXPECTED_START_NAV = 50000.00
    CHALLENGE_START_TIMESTAMP = "2026-09-02 00:27:00 UTC"

    def validate_report_invariants(
        self,
        snapshot: Dict[str, Any],
        report_sections: Dict[str, Any],
        explicit_watchlist_tickers: Set[str]
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        failures: List[str] = []
        checks_passed = 0

        acc = snapshot.get("account_summary", {})
        positions = snapshot.get("positions", [])
        snap_id = snapshot.get("snapshot_id", "")

        # Invariant 1: position_count == broker_position_count
        broker_count = len(positions)
        reported_count = acc.get("active_holdings_count", 0)
        if broker_count != reported_count:
            failures.append(f"INV-R1: Position count mismatch: snapshot positions ({broker_count}) != reported active count ({reported_count})")
        else:
            checks_passed += 1

        # Invariant 2: sum(position_market_values) == invested_value (£0.00 tolerance)
        calc_invested = round(sum(float(p.get("market_value_gbp", 0.0)) for p in positions), 2)
        reported_invested = round(float(acc.get("invested_capital", 0.0)), 2)
        invested_diff = round(abs(calc_invested - reported_invested), 2)
        if invested_diff > 0.001:
            failures.append(f"INV-R2: Sum of position market values (£{calc_invested:,.2f}) differs from invested capital (£{reported_invested:,.2f}) by £{invested_diff:.2f}")
        else:
            checks_passed += 1

        # Invariant 3: sum(displayed_unrealized_pnl) == portfolio_unrealized_pnl (£0.00 tolerance)
        calc_unrealized = round(sum(float(p.get("unrealized_pnl_gbp", 0.0)) for p in positions), 2)
        reported_unrealized = round(float(acc.get("total_unrealized_pnl_gbp", 0.0)), 2)
        unrealized_diff = round(abs(calc_unrealized - reported_unrealized), 2)
        if unrealized_diff > 0.001:
            failures.append(f"INV-R3: Sum of position unrealized P&L (£{calc_unrealized:,.2f}) differs from reported portfolio unrealized P&L (£{reported_unrealized:,.2f}) by £{unrealized_diff:.2f}")
        else:
            checks_passed += 1

        # Invariant 4: cash + invested_value == NAV (£0.00 tolerance)
        reported_cash = round(float(acc.get("free_cash", 0.0)), 2)
        reported_nav = round(float(acc.get("total_nav", 0.0)), 2)
        balance_sum = round(reported_cash + reported_invested, 2)
        nav_diff = round(abs(balance_sum - reported_nav), 2)
        if nav_diff > 0.001:
            failures.append(f"INV-R4: Balance sheet mismatch: cash (£{reported_cash:,.2f}) + invested (£{reported_invested:,.2f}) = £{balance_sum:,.2f} != NAV (£{reported_nav:,.2f}) (diff: £{nav_diff:.2f})")
        else:
            checks_passed += 1

        # Invariant 5: NAV - £50,000 == challenge_account_pnl (£0.00 tolerance)
        reported_delta_nav = round(float(acc.get("all_time_pnl_gbp", 0.0)), 2)
        expected_delta_nav = round(reported_nav - self.EXPECTED_START_NAV, 2)
        delta_diff = round(abs(reported_delta_nav - expected_delta_nav), 2)
        if delta_diff > 0.001:
            failures.append(f"INV-R5: NAV Delta mismatch: reported (£{reported_delta_nav:,.2f}) != calculated (£{expected_delta_nav:,.2f})")
        else:
            checks_passed += 1

        # Invariant 6: pnl_bridge_variance == £0.00
        bridge_data = snapshot.get("invariants_audit", {}).get("inv6_pnl_continuity_bridge", {})
        bridge_variance = float(bridge_data.get("variance_gbp", 0.0))
        if bridge_variance > 0.001:
            failures.append(f"INV-R6: P&L Bridge Variance (£{bridge_variance:.2f}) != £0.00")
        else:
            checks_passed += 1

        # Invariant 7: all pages share same snapshot_id
        section_snap_ids = report_sections.get("section_snapshot_ids", [])
        mismatched_snaps = [s for s in section_snap_ids if s != snap_id]
        if mismatched_snaps:
            failures.append(f"INV-R7: Snapshot ID mismatch across pages: expected '{snap_id}', found {mismatched_snaps}")
        else:
            checks_passed += 1

        # Invariant 8: all_report_tickers subset_of (current_holdings | explicit_watchlist)
        current_holding_syms = {p.get("symbol", "").upper() for p in positions}
        allowed_tickers = current_holding_syms.union({t.upper() for t in explicit_watchlist_tickers})
        
        reported_tickers: Set[str] = set()
        for sec_name, sec_tickers in report_sections.get("section_tickers", {}).items():
            for sym in sec_tickers:
                clean = sym.upper().replace("L_EQ", "").replace("_US_EQ", "").replace(".L", "")
                reported_tickers.add(clean)
                if clean not in allowed_tickers:
                    failures.append(f"INV-R8: Stale / unowned ticker '{clean}' found in section '{sec_name}'. Must be active holding or explicit watchlist.")
        if not any("INV-R8" in f for f in failures):
            checks_passed += 1

        # Invariant 9: every attribution_trade_id belongs_to challenge_id
        for att in report_sections.get("attributions", []):
            cid = att.get("challenge_id", "")
            if cid != self.CHALLENGE_ID:
                failures.append(f"INV-R9: Attribution trade '{att.get('trade_id')}' belongs to '{cid}' instead of '{self.CHALLENGE_ID}'")
        if not any("INV-R9" in f for f in failures):
            checks_passed += 1

        all_passed = (len(failures) == 0)
        telemetry = {
            "status": "VERIFIED" if all_passed else "FAILED_RECONCILIATION",
            "checks_passed": checks_passed,
            "checks_total": 9,
            "failures": failures,
            "snapshot_id": snap_id,
            "challenge_id": self.CHALLENGE_ID,
            "reconciled_invested_gbp": calc_invested,
            "reconciled_cash_gbp": reported_cash,
            "reconciled_nav_gbp": reported_nav,
            "reconciled_unrealized_gbp": calc_unrealized,
            "reconciled_delta_nav_gbp": expected_delta_nav,
            "bridge_variance_gbp": bridge_variance
        }

        return all_passed, failures, telemetry


report_invariant_guard = ReportInvariantGuard()
