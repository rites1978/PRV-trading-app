from typing import Dict, Any, Tuple
from src.config.settings import settings
from src.database.db import db

class BoardroomDeliberation:
    """
    Phase 5 Multi-Agent Quantitative Boardroom:
    1. Technical Engine generates entry signal (Buy/No-Buy) based on trend, RSI, momentum, volatility.
    2. Fundamentals, Sector Strength & News Sentiment do NOT reject trades; they output sizing multipliers.
    3. Risk Director holds safety and drawdown limits veto.
    """
    def __init__(self):
        pass

    def convene_boardroom(
        self,
        symbol: str,
        factors: Dict[str, float],
        technical_confidence: float,
        market_regime: str,
        risk_approved: bool,
        cost_approved: bool
    ) -> Tuple[bool, Dict[str, Any]]:
        try:
            # 1. Trend Agent Vote
            trend_vote = "BUY" if factors.get("trend_strength", 50.0) >= 60.0 else ("SELL" if factors.get("trend_strength", 50.0) <= 35.0 else "HOLD")
            
            # 2. Momentum Agent Vote
            momentum_vote = "BUY" if factors.get("momentum", 50.0) >= 55.0 or factors.get("relative_strength", 50.0) >= 55.0 else ("SELL" if factors.get("momentum", 50.0) <= 35.0 else "HOLD")
            
            # 3. Volatility Agent Vote
            volatility_vote = "BUY" if factors.get("volatility_condition", 50.0) >= 50.0 else "HOLD"
            
            # 4. Liquidity & Cost Agent Vote
            liquidity_vote = "BUY" if cost_approved else "HOLD"
            
            # 5. Risk Director Agent Vote (Holds Veto Power)
            risk_vote = "BUY" if risk_approved else "VETO"

            # Technical Entry Quorum (Preserves 100% of positive technical edge)
            approved = bool(
                technical_confidence >= settings.MIN_CONFIDENCE_THRESHOLD and
                risk_approved and
                cost_approved and
                risk_vote == "BUY" and
                (trend_vote == "BUY" or momentum_vote == "BUY" or volatility_vote == "BUY")
            )
        except Exception as e:
            # Phase 16: Malformed inputs must fail closed -> HOLD CASH
            return False, {
                "symbol": symbol,
                "approved": False,
                "reasoning": f"FAIL_SAFE_HOLD_CASH: Deliberation error: {type(e).__name__}: {str(e)}",
                "risk_agent_vote": "VETO"
            }

        reasoning = (
            f"Boardroom Consensus: {'APPROVED' if approved else 'REJECTED'}. "
            f"Technical Score: {technical_confidence}%. Regime: {market_regime}. "
            f"Votes -> Trend: {trend_vote}, Momentum: {momentum_vote}, "
            f"Volatility: {volatility_vote}, Liquidity: {liquidity_vote}, Risk: {risk_vote}."
        )

        decision_data = {
            "symbol": symbol,
            "overall_confidence": technical_confidence,
            "market_regime": market_regime,
            "trend_agent_vote": trend_vote,
            "momentum_agent_vote": momentum_vote,
            "volatility_agent_vote": volatility_vote,
            "liquidity_agent_vote": liquidity_vote,
            "risk_agent_vote": risk_vote,
            "approved": approved,
            "reasoning": reasoning
        }

        try:
            db.record_boardroom_decision(decision_data)
        except Exception:
            pass

        return approved, decision_data

boardroom = BoardroomDeliberation()
