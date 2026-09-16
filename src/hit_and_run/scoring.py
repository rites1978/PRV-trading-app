"""
PRV Capital - Hit-and-Run Short-Term Opportunity Scoring Engine
Auditable multi-factor quantitative ranking model for short-duration opportunities.
Considers:
1. Live momentum
2. Acceleration / momentum change
3. Relative strength
4. Liquidity
5. Spread / execution friction
6. Volatility
7. Volume / activity
8. Distance from intraday extremes
9. Market / session state
10. Estimated round-trip costs
11. Expected net reward versus downside
Strictly caps downside risk at 5.0% and rejects negative expected net edge.
"""
import numpy as np
from typing import Dict, Any, List, Optional
from src.hit_and_run.models import OpportunityCandidate


class HitAndRunOpportunityScorer:
    """
    Evaluates, scores, and ranks short-duration trading opportunities across the global universe.
    """

    MIN_QUALIFICATION_SCORE: float = 60.0
    MIN_RISK_REWARD_RATIO: float = 1.2
    MAX_SPREAD_FRICTION: float = 0.015  # 1.5% max spread
    MAX_HOLDING_LOSS_PCT: float = 0.05   # Strict 5.0% max loss invariant

    def evaluate_opportunity(self, snapshot: Dict[str, Any]) -> OpportunityCandidate:
        """
        Evaluates a market data snapshot and returns a fully quantified OpportunityCandidate.
        """
        instrument_id = snapshot.get("instrument_id", "")
        symbol = snapshot.get("symbol", instrument_id)
        feed_ticker = snapshot.get("feed_ticker", symbol)
        product_type = snapshot.get("product_type", "STOCK")
        currency = snapshot.get("currency", "GBP")
        is_uk_pence = snapshot.get("is_uk_pence", False)
        quote_divisor = snapshot.get("quote_divisor", 100.0 if is_uk_pence else 1.0)

        current_price = float(snapshot.get("current_price", 0.0))
        current_price_gbp = float(snapshot.get("current_price_gbp", current_price / quote_divisor))

        if current_price <= 0.0 or current_price_gbp <= 0.0:
            raise ValueError(f"Invalid non-positive price for {symbol}: price={current_price}, gbp={current_price_gbp}")

        recent_prices = snapshot.get("recent_prices", [current_price])
        intraday_open = float(snapshot.get("intraday_open", recent_prices[0]))
        intraday_high = float(snapshot.get("intraday_high", max(recent_prices)))
        intraday_low = float(snapshot.get("intraday_low", min(recent_prices)))
        benchmark_return = float(snapshot.get("benchmark_return", 0.0))

        # 1. Live Momentum
        if len(recent_prices) >= 2:
            momentum = float((recent_prices[-1] - recent_prices[0]) / max(1e-6, recent_prices[0]))
        else:
            momentum = float((current_price - intraday_open) / max(1e-6, intraday_open))

        # 2. Acceleration (Momentum Change / 2nd Derivative)
        if len(recent_prices) >= 4:
            mid = len(recent_prices) // 2
            m1 = (recent_prices[mid] - recent_prices[0]) / max(1e-6, recent_prices[0])
            m2 = (recent_prices[-1] - recent_prices[mid]) / max(1e-6, recent_prices[mid])
            acceleration = float(m2 - m1)
        else:
            acceleration = 0.0

        # 3. Relative Strength
        relative_strength = float(momentum - benchmark_return)

        # 4. Liquidity
        volume_recent = float(snapshot.get("volume_recent", 100000.0))
        volume_avg = float(snapshot.get("volume_avg", max(1.0, volume_recent)))
        liquidity = float(volume_recent * current_price_gbp)

        # 5. Spread Friction
        bid = float(snapshot.get("bid", current_price * 0.9995))
        ask = float(snapshot.get("ask", current_price * 1.0005))
        if ask > bid and current_price > 0:
            spread_friction = float((ask - bid) / current_price)
        else:
            spread_friction = 0.0010  # 10 bps default

        # 6. Volatility
        if len(recent_prices) >= 3:
            rets = pd_pct_changes(recent_prices)
            volatility = float(np.std(rets)) if len(rets) > 1 else 0.015
        else:
            volatility = float((intraday_high - intraday_low) / max(1e-6, current_price))
        volatility = max(0.005, volatility)

        # 7. Volume Activity
        volume_activity = float(volume_recent / max(1.0, volume_avg))

        # 8. Distance from Intraday Extremes
        distance_from_high = float(max(0.0, (intraday_high - current_price) / max(1e-6, current_price)))
        distance_from_low = float(max(0.0, (current_price - intraday_low) / max(1e-6, current_price)))

        # 9. Estimated Round-Trip Trading Costs
        fx_fee = 0.0015 if currency not in ("GBP", "GBX") else 0.0
        stamp_duty = 0.0050 if (is_uk_pence and product_type == "STOCK") else 0.0
        # Round trip costs = 2 * FX fee + spread friction + stamp duty
        estimated_costs = float((fx_fee * 2.0) + spread_friction + stamp_duty)

        # 10. Downside Risk (Strictly capped at 5.0% max loss invariant)
        technical_downside = max(0.010, volatility * 1.5)
        downside_risk = float(min(self.MAX_HOLDING_LOSS_PCT, technical_downside))

        # 11. Expected Net Reward
        # Target move based on momentum continuation + volatility impulse
        target_gross_move = max(0.015, (volatility * 2.0) + max(0.0, momentum * 0.5))
        expected_net_reward = float(max(0.0, target_gross_move - estimated_costs))

        # 12. Risk-Reward Ratio
        risk_reward_ratio = float(expected_net_reward / max(1e-4, downside_risk))

        # 13. Multi-Factor Opportunity Conviction Score (0 - 100)
        # Factor A: Momentum (0 - 25 pts)
        score_momentum = min(25.0, max(0.0, momentum * 500.0))

        # Factor B: Acceleration (0 - 20 pts)
        score_acceleration = min(20.0, max(0.0, acceleration * 1000.0))

        # Factor C: Volume Surge & Liquidity (0 - 20 pts)
        score_volume = min(20.0, max(0.0, (volume_activity - 0.5) * 15.0))

        # Factor D: Spread & Friction Efficiency (0 - 15 pts)
        score_friction = max(0.0, 15.0 - (spread_friction * 800.0))

        # Factor E: Asymmetric Risk/Reward (0 - 20 pts)
        score_rr = min(20.0, max(0.0, (risk_reward_ratio - 1.0) * 10.0))

        composite_score = round(float(score_momentum + score_acceleration + score_volume + score_friction + score_rr), 2)
        composite_score = max(0.0, min(100.0, composite_score))

        # 14. Qualification Audit
        qualification_reasons = []
        is_qualified = True

        session_state = snapshot.get("session_state", "REGULAR")
        if session_state not in ("REGULAR", "OPEN"):
            is_qualified = False
            qualification_reasons.append(f"Session state '{session_state}' is not active regular market")

        if momentum <= 0.0:
            is_qualified = False
            qualification_reasons.append(f"Non-positive momentum ({momentum:.4f})")

        if spread_friction > self.MAX_SPREAD_FRICTION:
            is_qualified = False
            qualification_reasons.append(f"Excessive spread friction ({spread_friction:.2%}) exceeds {self.MAX_SPREAD_FRICTION:.2%}")

        if expected_net_reward <= estimated_costs:
            is_qualified = False
            qualification_reasons.append(f"Insufficient net edge: net reward {expected_net_reward:.2%} <= costs {estimated_costs:.2%}")

        if risk_reward_ratio < self.MIN_RISK_REWARD_RATIO:
            is_qualified = False
            qualification_reasons.append(f"Risk-reward ratio {risk_reward_ratio:.2f}x below minimum {self.MIN_RISK_REWARD_RATIO:.2f}x")

        if composite_score < self.MIN_QUALIFICATION_SCORE:
            is_qualified = False
            qualification_reasons.append(f"Opportunity score {composite_score:.1f} below threshold {self.MIN_QUALIFICATION_SCORE:.1f}")

        # Construct Entry Thesis
        if is_qualified:
            entry_thesis = (
                f"Hit-and-Run Breakout for {symbol}: Momentum {momentum:+.2%}, "
                f"Accel {acceleration:+.2%}, VolRatio {volume_activity:.2f}x, "
                f"NetReward {expected_net_reward:+.2%} vs Risk {downside_risk:.2%} (R/R {risk_reward_ratio:.2f}x). "
                f"Conviction Score: {composite_score}/100."
            )
        else:
            entry_thesis = f"Disqualified: {'; '.join(qualification_reasons)}"

        return OpportunityCandidate(
            instrument_id=instrument_id,
            symbol=symbol,
            feed_ticker=feed_ticker,
            product_type=product_type,
            currency=currency,
            is_uk_pence=is_uk_pence,
            quote_divisor=quote_divisor,
            current_price=current_price,
            current_price_gbp=current_price_gbp,
            momentum=round(momentum, 5),
            acceleration=round(acceleration, 5),
            relative_strength=round(relative_strength, 5),
            liquidity=round(liquidity, 2),
            spread_friction=round(spread_friction, 5),
            volatility=round(volatility, 5),
            volume_activity=round(volume_activity, 2),
            distance_from_high=round(distance_from_high, 5),
            distance_from_low=round(distance_from_low, 5),
            estimated_costs=round(estimated_costs, 5),
            expected_net_reward=round(expected_net_reward, 5),
            downside_risk=round(downside_risk, 5),
            risk_reward_ratio=round(risk_reward_ratio, 2),
            opportunity_score=composite_score,
            entry_thesis=entry_thesis,
            technical_execution_supported=True,
            strategy_qualified=is_qualified,
            qualification_reasons=qualification_reasons,
            market_session=session_state
        )

    def rank_opportunities(self, snapshots: List[Dict[str, Any]]) -> List[OpportunityCandidate]:
        """Evaluates and ranks a batch of candidates strictly by conviction score descending."""
        candidates = [self.evaluate_opportunity(s) for s in snapshots]
        candidates.sort(key=lambda c: c.opportunity_score, reverse=True)
        return candidates


def pd_pct_changes(prices: List[float]) -> List[float]:
    """Helper to compute return percentages across a price list."""
    if len(prices) < 2:
        return [0.0]
    return [(prices[i] - prices[i - 1]) / max(1e-6, prices[i - 1]) for i in range(1, len(prices))]


hit_and_run_scorer = HitAndRunOpportunityScorer()
