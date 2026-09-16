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

        # 1. Downside Estimate (Strictly capped at 5.0% max loss invariant)
        vol = state.volatility if state.volatility is not None else 0.015
        downside_est = min(self.MAXIMUM_AUTHORISED_LOSS_PCT, max(0.010, vol * 1.5))

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

        if not state.is_fresh:
            data_quality_issues.append("STALE_DATA")
            contrary_evidence.append(f"DATA_STALE: Age {state.data_age_seconds:.0f}s exceeds freshness window")
        else:
            supporting_evidence.append("Market snapshot fresh")

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
                supporting_evidence.append(f"Expected net reward after costs: {net_opp:+.2%} (downside risk {downside_est:.2%})")
            else:
                contrary_evidence.append(f"Expected net reward non-positive: {net_opp:+.2%} consumed by costs")

        # 5. Opportunity Score Calculation (Strictly None if required data are incomplete)
        # Never fabricate an opportunity score if required data are incomplete
        opportunity_score: Optional[float] = None
        if data_quality_state == "COMPLETE" and state.spread_friction is not None and net_opp is not None and net_opp > 0:
            # Score components (0 - 100):
            # 1. Momentum score: 0 - 25 pts
            s_mom = min(25.0, max(0.0, (mom or 0.0) * 500.0))
            # 2. Acceleration score: 0 - 20 pts
            s_acc = min(20.0, max(0.0, (acc or 0.0) * 1000.0))
            # 3. Volume & Activity: 0 - 20 pts
            s_vol = min(20.0, max(0.0, ((vol_act or 1.0) - 0.5) * 15.0))
            # 4. Spread friction efficiency: 0 - 15 pts
            s_spread = max(0.0, 15.0 - (state.spread_friction * 800.0))
            # 5. Reward / Downside: 0 - 20 pts
            rr = net_opp / max(1e-4, downside_est)
            s_rr = min(20.0, max(0.0, (rr - 1.0) * 10.0))

            raw_score = round(float(s_mom + s_acc + s_vol + s_spread + s_rr), 2)
            opportunity_score = max(0.0, min(100.0, raw_score))

            conviction_evidence = {
                "momentum_score": round(s_mom, 2),
                "acceleration_score": round(s_acc, 2),
                "volume_score": round(s_vol, 2),
                "spread_efficiency_score": round(s_spread, 2),
                "reward_risk_score": round(s_rr, 2),
                "composite_score": opportunity_score,
                "detected_setups": detected_setups
            }
        else:
            opportunity_score = None
            conviction_evidence = {
                "detected_setups": detected_setups,
                "data_quality_issues": data_quality_issues,
                "score_status": "SCORE_UNAVAILABLE_DUE_TO_INCOMPLETE_DATA"
            }

        # 6. Opportunity Thesis Synthesis
        if opportunity_score is not None:
            thesis = (
                f"Hit-and-Run [{primary_setup}] setup for {state.symbol}: "
                f"NetReward {net_opp:+.2%} vs Downside {downside_est:.2%}. "
                f"Conviction: {opportunity_score:.1f}/100. "
                f"Key drivers: {'; '.join(supporting_evidence[:3])}."
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
            data_quality_state=data_quality_state,
            conviction_evidence=conviction_evidence,
            opportunity_score=opportunity_score
        )

    def analyze_batch(self, states: List[LiveOpportunityState]) -> List[OpportunityAnalysisResult]:
        """Analyzes a collection of states and returns results sorted by conviction score descending."""
        results = [self.analyze_opportunity(s) for s in states]
        results.sort(
            key=lambda r: (
                r.opportunity_score is not None,
                r.opportunity_score if r.opportunity_score is not None else -1.0,
                r.expected_net_opportunity if r.expected_net_opportunity is not None else -1.0
            ),
            reverse=True
        )
        return results


opportunity_analyzer = HitAndRunOpportunityAnalyzer()
