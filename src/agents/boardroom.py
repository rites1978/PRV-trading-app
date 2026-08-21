from typing import Dict, Any, Tuple
from src.database.db import db

class BoardroomDeliberation:
    """
    Multi-Agent Quantitative Boardroom Consensus:
    - Trend Agent: Evaluates structural market direction.
    - Momentum Agent: Evaluates velocity and acceleration.
    - Volatility Agent: Evaluates price dispersion and stop boundaries.
    - Liquidity & Cost Agent: Evaluates transaction friction and execution viability.
    - Risk Director Agent: Has absolute veto on portfolio safety and drawdown limits.
    """
    def __init__(self):
        pass

    def convene_boardroom(
        self,
        symbol: str,
        factors: Dict[str, float],
        composite_confidence: float,
        market_regime: str,
        risk_approved: bool,
        cost_approved: bool
    ) -> Tuple[bool, Dict[str, Any]]:
        # 1. Trend Agent Vote
        trend_vote = "BUY" if factors["trend_strength"] >= 75.0 else ("SELL" if factors["trend_strength"] <= 35.0 else "HOLD")
        
        # 2. Momentum Agent Vote
        momentum_vote = "BUY" if factors["momentum"] >= 70.0 and factors["relative_strength"] >= 70.0 else ("SELL" if factors["momentum"] <= 35.0 else "HOLD")
        
        # 3. Volatility Agent Vote
        volatility_vote = "BUY" if factors["volatility_condition"] >= 65.0 else "HOLD"
        
        # 4. Liquidity & Cost Agent Vote
        liquidity_vote = "BUY" if cost_approved and factors["trading_cost_impact"] >= 60.0 else "HOLD"
        
        # 5. Risk Director Agent Vote (Holds Veto Power)
        risk_vote = "BUY" if risk_approved else "VETO"

        # Quorum Check: Requires Composite > 80, Risk Approval, Cost Approval, and Quorum of Votes
        approved = bool(
            composite_confidence >= 80.0 and
            risk_approved and
            cost_approved and
            risk_vote == "BUY" and
            (trend_vote == "BUY" or momentum_vote == "BUY")
        )

        reasoning = (
            f"Boardroom Consensus: {'APPROVED' if approved else 'REJECTED'}. "
            f"Confidence: {composite_confidence}%. Regime: {market_regime}. "
            f"Votes -> Trend: {trend_vote}, Momentum: {momentum_vote}, "
            f"Volatility: {volatility_vote}, Liquidity: {liquidity_vote}, Risk: {risk_vote}."
        )

        decision_data = {
            "symbol": symbol,
            "overall_confidence": composite_confidence,
            "market_regime": market_regime,
            "trend_agent_vote": trend_vote,
            "momentum_agent_vote": momentum_vote,
            "volatility_agent_vote": volatility_vote,
            "liquidity_agent_vote": liquidity_vote,
            "risk_agent_vote": risk_vote,
            "approved": approved,
            "reasoning": reasoning
        }

        # Store to database
        try:
            db.record_boardroom_decision(decision_data)
        except Exception:
            pass

        return approved, decision_data

boardroom = BoardroomDeliberation()
