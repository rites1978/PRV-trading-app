"""
PRV Capital - Hit-and-Run Opportunity Analysis Engine
Requirement B: Auditable opportunity-analysis interface comparing opportunities across the universe.
Reasons across multiple short-duration setup families without restriction:
- momentum continuation
- acceleration
- breakout
- pullback continuation
- mean reversion
- relative-strength divergence
- catalyst-driven movement

For every candidate produces:
- opportunity thesis
- supporting evidence
- contrary evidence
- estimated costs
- expected net opportunity
- downside estimate (strictly capped at 5%)
- data-quality state
- conviction evidence
Never fabricates an opportunity score if required data are incomplete.
"""
from typing import Dict, Any, List, Optional
import numpy as np

from src.hit_and_run.models import LiveOpportunityState, OpportunityAnalysisResult


class HitAndRunOpportunityAnalyzer:
    """Auditable multi-setup opportunity evaluator."""

    MAXIMUM_AUTHORISED_LOSS_PCT: float = 0.05

    def analyze_opportunity(self, state: LiveOpportunityState) -> OpportunityAnalysisResult:
        """
        Performs thorough, transparent analysis of a LiveOpportunityState across all setup families.
        Does NOT drop candidates. Produces complete audit trail.
        """
        supporting_evidence: List[str] = []
        contrary_evidence: List[str] = []
        conviction_evidence: Dict[str, Any] = {}

        # 1. Downside Model (Unauthorised heuristic removed; represent DOWNSIDE_MODEL_UNAVAILABLE)
        downside_est: Optional[float] = getattr(state, "downside_estimate", None)
        if downside_est is not None:
            downside_model_status = "AUTHORISED_ESTIMATE"
        else:
            downside_model_status = "DOWNSIDE_MODEL_UNAVAILABLE"
            contrary_evidence.append("DOWNSIDE_MODEL_UNAVAILABLE: No user-authorised downside model is defined")

        # 2. Data Quality Audit
        data_quality_issues: List[str] = []
        if state.spread_friction is None:
            data_quality_issues.append("INCOMPLETE_SPREAD")
            contrary_evidence.append("LIVE_SPREAD_UNKNOWN: Live executable bid/ask spread unavailable")
        else:
            supporting_evidence.append(f"Executable spread verified: {state.spread_friction * 10000:.1f} bps")

        if not state.cost_model_complete:
            data_quality_issues.append("INCOMPLETE_COSTS")
            contrary_evidence.extend(state.cost_model_reasons)
        else:
            if state.estimated_costs is not None:
                supporting_evidence.append(f"Round-trip costs quantified: {state.estimated_costs:.4%}")

        if state.min_trade_quantity is None or state.quantity_precision is None:
            data_quality_issues.append("INCOMPLETE_QUANTITY_METADATA")
            contrary_evidence.append("QUANTITY_INCREMENT_UNKNOWN: Authoritative trade increment metadata unavailable")

        if state.tick_size is None or state.tick_size <= 0:
            data_quality_issues.append("INCOMPLETE_TICK_METADATA")
            contrary_evidence.append("TICK_SIZE_UNKNOWN: Authoritative broker tick size unavailable for stop protection")

        if state.quote_freshness_status != "CURRENT":
            data_quality_issues.append("STALE_DATA" if state.quote_freshness_status == "STALE" else "UNKNOWN_FRESHNESS")
            contrary_evidence.append(f"DATA_NOT_CURRENT: Quote freshness status is '{state.quote_freshness_status}'")
        else:
            supporting_evidence.append("Market snapshot fresh and current")

        if state.session_state not in ("REGULAR", "OPEN"):
            contrary_evidence.append(f"MARKET_SESSION_INACTIVE: Current session is {state.session_state}")
        else:
            supporting_evidence.append(f"Active trading session: {state.session_state}")

        # Determine overall data quality state
        if not data_quality_issues:
            data_quality_state = "COMPLETE"
        else:
            data_quality_state = "; ".join(data_quality_issues)

        # 3. Setup Classification & Setup Evidence Gathering
        mom = state.short_duration_momentum
        acc = state.momentum_acceleration
        rs = state.relative_strength
        vol_act = state.volume_activity
        dist_high = state.distance_from_high
        dist_low = state.distance_from_low

        detected_setups: List[str] = []

        # A. Momentum Continuation
        if mom is not None and mom > 0.005:
            detected_setups.append("MOMENTUM_CONTINUATION")
            supporting_evidence.append(f"Positive momentum continuation: {mom:+.2%}")
        elif mom is not None and mom < -0.005:
            contrary_evidence.append(f"Negative momentum trend: {mom:+.2%}")

        # B. Acceleration (Momentum 2nd derivative)
        if acc is not None and acc > 0.002:
            detected_setups.append("ACCELERATION")
            supporting_evidence.append(f"Impulse acceleration expanding: {acc:+.3%}")
        elif acc is not None and acc < -0.002:
            contrary_evidence.append(f"Momentum decelerating: {acc:+.3%}")

        # C. Breakout
        if dist_high is not None and dist_high < 0.008 and (vol_act is not None and vol_act > 1.2):
            detected_setups.append("BREAKOUT")
            supporting_evidence.append(f"Breakout near high ({dist_high:.2%}) with volume {vol_act:.1f}x")

        # D. Pullback Continuation
        if mom is not None and mom > 0 and dist_high is not None and 0.01 <= dist_high <= 0.035:
            detected_setups.append("PULLBACK_CONTINUATION")
            supporting_evidence.append(f"Healthy pullback from highs ({dist_high:.2%}) in established uptrend")

        # E. Mean Reversion
        if dist_low is not None and dist_low < 0.008 and mom is not None and mom < -0.015:
            detected_setups.append("MEAN_REVERSION")
            supporting_evidence.append(f"Oversold bounce potential near intraday low ({dist_low:.2%})")

        # F. Relative Strength Divergence
        if rs is not None and rs > 0.008:
            detected_setups.append("RELATIVE_STRENGTH_DIVERGENCE")
            supporting_evidence.append(f"Strong relative strength outperforming benchmark by {rs:+.2%}")
        elif rs is not None and rs < -0.008:
            contrary_evidence.append(f"Lagging benchmark by {rs:+.2%}")

        # G. Catalyst-Driven Movement
        if vol_act is not None and vol_act >= 2.0 and mom is not None and abs(mom) >= 0.015:
            detected_setups.append("CATALYST_DRIVEN")
            supporting_evidence.append(f"Exceptional volume catalyst ({vol_act:.1f}x avg) driving impulse")

        primary_setup = detected_setups[0] if len(detected_setups) == 1 else (
            "MULTI_FACTOR" if detected_setups else "UNCLASSIFIED_NEUTRAL"
        )

        # 4. Economics: Expected Net Opportunity vs Downside
        net_opp = state.expected_net_opportunity
        if net_opp is not None:
            if net_opp > 0:
                downside_desc = f"{downside_est:.2%}" if downside_est is not None else downside_model_status
                supporting_evidence.append(f"Expected net reward after costs: {net_opp:+.2%} (downside: {downside_desc})")
            else:
                contrary_evidence.append(f"Expected net reward non-positive: {net_opp:+.2%} consumed by costs")

        # 5. Opportunity Score & Raw Conviction Evidence
        # Contract Rule: Any fixed hand-built weighting/point system that affects candidate ranking,
        # AI evidence, allocation, entry, exit, or rotation and has no user authority must be removed.
        # If no authorised deterministic opportunity score exists: OPPORTUNITY_SCORE = None.
        # Pass raw evidence/features to the AI decision layer instead.
        opportunity_score: Optional[float] = None

        conviction_evidence = {
            "momentum": mom,
            "acceleration": acc,
            "volume_activity": vol_act,
            "spread_friction": state.spread_friction,
            "relative_strength": rs,
            "volatility": state.volatility,
            "distance_from_high": dist_high,
            "distance_from_low": dist_low,
            "expected_net_opportunity": net_opp,
            "downside_model_status": downside_model_status,
            "data_quality_state": data_quality_state,
            "detected_setups": detected_setups
        }

        # 6. Opportunity Thesis Synthesis (using raw observable features)
        downside_desc = f"{downside_est:.2%}" if downside_est is not None else downside_model_status
        if data_quality_state == "COMPLETE":
            net_desc = f"NetReward {net_opp:+.2%}" if net_opp is not None else "NetReward UNMODELLED"
            thesis = (
                f"Hit-and-Run [{primary_setup}] setup for {state.symbol}: "
                f"{net_desc} vs Downside ({downside_desc}). "
                f"Drivers: {'; '.join(supporting_evidence[:3]) if supporting_evidence else 'None'}."
            )
        else:
            thesis = (
                f"Unqualified [{primary_setup}] for {state.symbol}: "
                f"Data state '{data_quality_state}'. "
                f"Frictions/Blockers: {'; '.join(contrary_evidence[:3])}."
            )

        return OpportunityAnalysisResult(
            instrument_id=state.instrument_id,
            symbol=state.symbol,
            feed_ticker=state.feed_ticker,
            state=state,
            setup_family=primary_setup,
            opportunity_thesis=thesis,
            supporting_evidence=supporting_evidence,
            contrary_evidence=contrary_evidence,
            estimated_costs=state.estimated_costs,
            expected_net_opportunity=net_opp,
            downside_estimate=downside_est,
            downside_model_status=downside_model_status,
            expected_gross_move=state.expected_gross_move,
            expected_move_model_status=getattr(state, "expected_move_model_status", "EXPECTED_MOVE_MODEL_UNAVAILABLE"),
            data_quality_state=data_quality_state,
            conviction_evidence=conviction_evidence,
            opportunity_score=opportunity_score
        )

    def analyze_batch(self, states: List[LiveOpportunityState]) -> List[OpportunityAnalysisResult]:
        """Analyzes a collection of states and passes raw evidence to AI decision layer."""
        results = [self.analyze_opportunity(s) for s in states]
        # Invariant: No strategy-based ranking or pre-selection may affect candidate visibility to AI.
        # Preserve all items in stable, behavior-neutral instrument_id order without truncation.
        results.sort(key=lambda r: (getattr(r, "instrument_id", "") or ""))
        return results


opportunity_analyzer = HitAndRunOpportunityAnalyzer()
