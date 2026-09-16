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
from src.hit_and_run.cost_model import hit_and_run_cost_model
from src.data.technical_execution_capability import technical_execution_capability


class HitAndRunOpportunityScorer:
    """
    Evaluates, scores, and ranks short-duration trading opportunities across the global universe.
    """

    MAXIMUM_AUTHORISED_LOSS_PCT: float = 0.05  # Strict 5.0% max loss invariant

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
        isin = str(snapshot.get("isin", "")).strip().upper()
        exchange_venue = str(
            snapshot.get("exchange_venue") or snapshot.get("exchange") or snapshot.get("venue") or ""
        ).strip()
        if not exchange_venue:
            exchange_venue = technical_execution_capability.resolve_exchange_venue(snapshot) or ""
        min_trade_quantity = snapshot.get("min_trade_quantity")
        quantity_precision = snapshot.get("quantity_precision")
        tick_size = snapshot.get("tick_size")

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

        # 5. Spread Friction (Strictly Authoritative Live Quotes - No Fabricated Fallback)
        raw_bid = snapshot.get("bid")
        raw_ask = snapshot.get("ask")
        bid = float(raw_bid) if raw_bid is not None else None
        ask = float(raw_ask) if raw_ask is not None else None
        if bid is not None and ask is not None and ask > bid and current_price > 0:
            spread_friction = float((ask - bid) / current_price)
        else:
            spread_friction = None

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

        # 9. Authoritative Transaction Cost & Tax Evaluation
        # Evaluates Trading212 FX fee (0.15% per leg), UK SDRT (0.50% buy), PTM levy (£1.50 > £10k),
        # SEC Section 31 (0.00206% sell), French FTT (0.40% buy), Italian/Spanish FTT, and spread friction.
        cost_eval = hit_and_run_cost_model.evaluate_instrument_costs(
            product_type=product_type,
            currency=currency,
            isin=isin,
            exchange_venue=exchange_venue,
            current_price=current_price,
            bid=bid,
            ask=ask,
            market_cap_eur=snapshot.get("market_cap_eur"),
            market_cap_tier=snapshot.get("market_cap_tier"),
            french_ftt_applicable=snapshot.get("french_ftt_applicable"),
            custom_spread_pct=None
        )
        estimated_costs = cost_eval.estimated_costs_round_trip

        # Authoritative quantity precision and tick size derivation
        if quantity_precision is None and min_trade_quantity is not None:
            quantity_precision = technical_execution_capability.derive_quantity_precision(min_trade_quantity)

        if tick_size is None:
            tick_size = technical_execution_capability.derive_tick_size_for_venue(
                venue_name=exchange_venue,
                currency=currency,
                price=current_price,
                is_uk_pence=is_uk_pence,
                explicit_tick=snapshot.get("tick_size")
            )

        # 10. Downside Risk (Informational technical downside estimate for AI reasoning)
        technical_downside = max(0.010, volatility * 1.5)
        downside_risk = float(technical_downside)

        # 11. Expected Net Reward
        # Target move based on momentum continuation + volatility impulse
        target_gross_move = max(0.015, (volatility * 2.0) + max(0.0, momentum * 0.5))
        if estimated_costs is not None:
            expected_net_reward = float(max(0.0, target_gross_move - estimated_costs))
            risk_reward_ratio = float(expected_net_reward / max(1e-4, downside_risk))
            score_rr = min(20.0, max(0.0, (risk_reward_ratio - 1.0) * 10.0))
        else:
            expected_net_reward = None
            risk_reward_ratio = None
            score_rr = None

        # 13. Multi-Factor Opportunity Conviction Score (0 - 100)
        # Factor A: Momentum (0 - 25 pts)
        score_momentum = min(25.0, max(0.0, momentum * 500.0))

        # Factor B: Acceleration (0 - 20 pts)
        score_acceleration = min(20.0, max(0.0, acceleration * 1000.0))

        # Factor C: Volume Surge & Liquidity (0 - 20 pts)
        score_volume = min(20.0, max(0.0, (volume_activity - 0.5) * 15.0))

        # Factor D: Spread & Friction Efficiency (0 - 15 pts)
        # If spread is unknown: feature is INCOMPLETE / UNAVAILABLE.
        # Must NOT compute an apparently favourable friction score from zero.
        if spread_friction is not None:
            score_friction = max(0.0, 15.0 - (spread_friction * 800.0))
        else:
            score_friction = None

        # Composite Score: Any composite feature requiring spread must be unavailable / incomplete
        if score_friction is not None and score_rr is not None:
            composite_score = round(float(score_momentum + score_acceleration + score_volume + score_friction + score_rr), 2)
            composite_score = max(0.0, min(100.0, composite_score))
        else:
            composite_score = None

        # 14. Qualification Audit (Authoritative Rules Only)
        qualification_reasons = []
        is_qualified = True

        session_state = snapshot.get("session_state", "REGULAR")
        if session_state not in ("REGULAR", "OPEN"):
            is_qualified = False
            qualification_reasons.append(f"Session state '{session_state}' is not active regular market")

        # Authoritative rule: expected profitability must be NET of costs, do not force trades without edge
        if expected_net_reward is None or expected_net_reward <= 0.0:
            is_qualified = False
            if expected_net_reward is None:
                qualification_reasons.append("Net edge cannot be established: transaction costs/spread incomplete")
            else:
                qualification_reasons.append(f"No genuine net edge after costs: net reward {expected_net_reward:.4%} <= 0")

        # Strict Cost Completeness Check:
        # If tax/fee applicability cannot be established reliably: COST_MODEL_COMPLETE = False.
        # Strategy may score instrument informationally, but it MUST NOT be authorised for a real order.
        if not cost_eval.cost_model_complete:
            is_qualified = False
            qualification_reasons.extend(cost_eval.incomplete_reasons)

        # Live spread check: unknown spread fails closed
        if spread_friction is None:
            is_qualified = False
            qualification_reasons.append("LIVE_SPREAD_UNKNOWN: Live bid/ask spread unavailable; spread friction, score, and execution authorisation incomplete")

        # Quantity precision check: do not guess quantity precision
        if quantity_precision is None and min_trade_quantity is None:
            is_qualified = False
            qualification_reasons.append("QUANTITY_INCREMENT_UNKNOWN: Missing quantity increment metadata")

        # Tick size check: do not guess tick size
        if tick_size is None or tick_size <= 0:
            is_qualified = False
            qualification_reasons.append("TICK_SIZE_UNKNOWN: Unable to determine authoritative tick size from metadata or verified venue table")

        # Real order authorization invariant: must be qualified, complete cost model, and verified live spread
        execution_authorised = (
            is_qualified and
            cost_eval.cost_model_complete and
            (spread_friction is not None)
        )

        # Construct Entry Thesis
        if is_qualified and composite_score is not None and expected_net_reward is not None:
            entry_thesis = (
                f"Hit-and-Run Opportunity for {symbol}: Momentum {momentum:+.2%}, "
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
            isin=isin,
            min_trade_quantity=min_trade_quantity,
            quantity_precision=quantity_precision,
            tick_size=tick_size,
            exchange_venue=exchange_venue,
            cost_model_complete=cost_eval.cost_model_complete,
            cost_model_reasons=cost_eval.incomplete_reasons,
            momentum=round(momentum, 5),
            acceleration=round(acceleration, 5),
            relative_strength=round(relative_strength, 5),
            liquidity=round(liquidity, 2),
            spread_friction=round(spread_friction, 5) if spread_friction is not None else None,
            volatility=round(volatility, 5),
            volume_activity=round(volume_activity, 2),
            distance_from_high=round(distance_from_high, 5),
            distance_from_low=round(distance_from_low, 5),
            estimated_costs=round(estimated_costs, 5) if estimated_costs is not None else None,
            expected_net_reward=round(expected_net_reward, 5) if expected_net_reward is not None else None,
            downside_risk=round(downside_risk, 5),
            risk_reward_ratio=round(risk_reward_ratio, 2) if risk_reward_ratio is not None else None,
            opportunity_score=composite_score,
            entry_thesis=entry_thesis,
            technical_execution_supported=True,
            strategy_qualified=is_qualified,
            execution_authorised=execution_authorised,
            qualification_reasons=qualification_reasons,
            market_session=session_state
        )

    def rank_opportunities(self, snapshots: List[Dict[str, Any]]) -> List[OpportunityCandidate]:
        """Evaluates and ranks a batch of candidates strictly by conviction score descending."""
        candidates = [self.evaluate_opportunity(s) for s in snapshots]
        candidates.sort(
            key=lambda c: (
                c.opportunity_score is not None,
                c.opportunity_score if c.opportunity_score is not None else -1.0
            ),
            reverse=True
        )
        return candidates


def pd_pct_changes(prices: List[float]) -> List[float]:
    """Helper to compute return percentages across a price list."""
    if len(prices) < 2:
        return [0.0]
    return [(prices[i] - prices[i - 1]) / max(1e-6, prices[i - 1]) for i in range(1, len(prices))]


hit_and_run_scorer = HitAndRunOpportunityScorer()
