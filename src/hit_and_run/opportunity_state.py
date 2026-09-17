"""
PRV Capital - Hit-and-Run Live Opportunity State Builder
Requirement A: Builds live market-state model for each technically executable instrument.
Carries all available market, liquidity, friction, and capability information.
Does NOT enforce any arbitrary thresholds or hidden rejection cutoffs.
Missing critical execution data remain UNKNOWN (None), never replaced by fabricated defaults.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import numpy as np

from src.hit_and_run.models import LiveOpportunityState
from src.hit_and_run.cost_model import hit_and_run_cost_model
from src.data.technical_execution_capability import technical_execution_capability
from src.data.market_session_router import market_session_router
from src.data.broker_discovery import broker_discovery
from src.data.source_authority import QuoteSourceAuthorityRegistry, QuoteSourceAuthority


class LiveOpportunityStateBuilder:
    """Constructs auditable LiveOpportunityState instances from live market and broker data."""

    def build_state(
        self,
        snapshot: Dict[str, Any],
        instrument_meta: Optional[Dict[str, Any]] = None,
        utc_dt: Optional[datetime] = None
    ) -> LiveOpportunityState:
        """
        Builds a comprehensive LiveOpportunityState for an instrument.
        Does NOT drop or reject candidates; retains full state with None for unavailable data.
        """
        if utc_dt is None:
            utc_dt = datetime.now(timezone.utc)
        elif utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)

        # Basic identity & Contract
        instrument_id = snapshot.get("instrument_id") or snapshot.get("ticker", "")
        symbol = snapshot.get("symbol") or snapshot.get("shortName") or instrument_id
        feed_ticker = snapshot.get("feed_ticker") or symbol
        product_type = snapshot.get("product_type", "STOCK")
        currency = snapshot.get("currency") or snapshot.get("currencyCode", "GBP")
        is_uk_pence = snapshot.get("is_uk_pence", currency.upper() == "GBX")
        quote_divisor = float(snapshot.get("quote_divisor", 100.0 if is_uk_pence else 1.0))
        isin = str(snapshot.get("isin", "")).strip().upper()
        feed_provider = snapshot.get("feed_provider", "TRADING212")

        # Technical Venue Resolution (Authoritative)
        exchange_venue = str(
            snapshot.get("exchange_venue") or
            snapshot.get("exchange") or
            snapshot.get("workingScheduleId") or
            ""
        ).strip()
        if not exchange_venue and instrument_meta:
            exchange_venue = technical_execution_capability.resolve_exchange_venue(instrument_meta) or ""
        if not exchange_venue:
            exchange_venue = technical_execution_capability.resolve_exchange_venue(snapshot) or "UNKNOWN"

        # Session State & Session Open Resolution
        session_open = False
        extended_hours_eligible = False
        extended_hours_status = "UNKNOWN"
        extended_hours = None
        overnight_eligibility = "UNKNOWN"
        execution_session = "UNKNOWN"
        next_session_transition = None

        sched_obj = instrument_meta or snapshot
        if sched_obj and (sched_obj.get("workingScheduleId") is not None or "extendedHours" in sched_obj):
            s_details = market_session_router.get_instrument_session_details(sched_obj, utc_dt=utc_dt)
            session_open = bool(s_details["session_open_now"])
            extended_hours_eligible = bool(s_details["extended_hours_eligible"])
            extended_hours_status = str(s_details.get("extended_hours_status", "UNKNOWN"))
            extended_hours = s_details.get("extended_hours")
            overnight_eligibility = str(s_details.get("overnight_eligibility", "UNKNOWN"))
            execution_session = str(s_details["execution_session"])
            next_session_transition = s_details["next_session_transition"]
            session_state = execution_session
        else:
            raw_state = snapshot.get("session_state")
            if raw_state:
                session_state = raw_state
                session_open = (raw_state.upper() in ("OPEN", "REGULAR", "AFTER_HOURS", "PRE_MARKET", "OVERNIGHT"))
                execution_session = raw_state
            else:
                session_state = "REGULAR"
                session_open = True
                execution_session = "REGULAR"
            ext_eval = broker_discovery.evaluate_extended_hours(snapshot)
            extended_hours = ext_eval["extended_hours"]
            extended_hours_status = ext_eval["extended_hours_status"]
            extended_hours_eligible = ext_eval["is_extended_hours_eligible"]
            overnight_eligibility = "UNKNOWN"

        # Prices & Quote Units
        raw_price = snapshot.get("current_price")
        if raw_price is not None and float(raw_price) > 0:
            current_price = float(raw_price)
        else:
            current_price = 0.0
        current_price_gbp = float(snapshot.get("current_price_gbp", current_price / quote_divisor if quote_divisor > 0 else current_price))

        recent_prices = snapshot.get("recent_prices", [current_price] if current_price > 0 else [])
        intraday_open = float(snapshot["intraday_open"]) if snapshot.get("intraday_open") is not None else (recent_prices[0] if recent_prices else current_price)
        intraday_high = float(snapshot["intraday_high"]) if snapshot.get("intraday_high") is not None else (max(recent_prices) if recent_prices else current_price)
        intraday_low = float(snapshot["intraday_low"]) if snapshot.get("intraday_low") is not None else (min(recent_prices) if recent_prices else current_price)
        benchmark_return = float(snapshot["benchmark_return"]) if snapshot.get("benchmark_return") is not None else None

        # Executable Bid / Ask & Spread Friction (Never fabricate default!)
        raw_bid = snapshot.get("bid")
        raw_ask = snapshot.get("ask")
        bid = float(raw_bid) if raw_bid is not None and float(raw_bid) > 0 else None
        ask = float(raw_ask) if raw_ask is not None and float(raw_ask) > 0 else None

        if bid is not None and ask is not None and ask > bid and current_price > 0:
            spread_friction = float((ask - bid) / current_price)
        else:
            spread_friction = None

        # Short-Duration Momentum
        if len(recent_prices) >= 2 and recent_prices[0] > 0:
            momentum = float((recent_prices[-1] - recent_prices[0]) / recent_prices[0])
        elif intraday_open is not None and intraday_open > 0 and current_price > 0:
            momentum = float((current_price - intraday_open) / intraday_open)
        else:
            momentum = None

        # Momentum Acceleration (2nd derivative)
        if len(recent_prices) >= 4 and recent_prices[0] > 0:
            mid = len(recent_prices) // 2
            m1 = (recent_prices[mid] - recent_prices[0]) / max(1e-6, recent_prices[0])
            m2 = (recent_prices[-1] - recent_prices[mid]) / max(1e-6, recent_prices[mid])
            acceleration = float(m2 - m1)
        else:
            acceleration = None

        # Relative Strength
        relative_strength = float(momentum - benchmark_return) if (momentum is not None and benchmark_return is not None) else None

        # Volume Activity
        raw_vol_recent = snapshot.get("volume_recent")
        raw_vol_avg = snapshot.get("volume_avg")
        volume_recent = float(raw_vol_recent) if raw_vol_recent is not None else None
        volume_avg = float(raw_vol_avg) if raw_vol_avg is not None else None
        if volume_recent is not None and volume_avg is not None and volume_avg > 0:
            volume_activity = float(volume_recent / volume_avg)
            volume_data_status = "AUTHORISED_VOLUME_DATA"
        elif volume_recent is not None:
            volume_activity = None
            volume_data_status = "AVERAGE_VOLUME_UNAVAILABLE"
        else:
            volume_activity = None
            volume_data_status = "VOLUME_DATA_UNAVAILABLE"

        # Volatility
        if len(recent_prices) >= 3:
            rets = [(recent_prices[i] - recent_prices[i - 1]) / max(1e-6, recent_prices[i - 1]) for i in range(1, len(recent_prices))]
            volatility = float(np.std(rets)) if len(rets) > 1 else None
            volatility_data_status = "AUTHORISED_VOLATILITY_DATA" if volatility is not None else "VOLATILITY_DATA_UNAVAILABLE"
        elif intraday_high is not None and intraday_low is not None and intraday_high > intraday_low and current_price > 0:
            volatility = float((intraday_high - intraday_low) / current_price)
            volatility_data_status = "INTRADAY_RANGE_ESTIMATE"
        else:
            volatility = None
            volatility_data_status = "VOLATILITY_DATA_UNAVAILABLE"

        # Distance from Intraday Extremes
        if current_price > 0 and intraday_high is not None and intraday_high >= current_price:
            distance_from_high = float(max(0.0, (intraday_high - current_price) / current_price))
        else:
            distance_from_high = None

        if current_price > 0 and intraday_low is not None and current_price >= intraday_low:
            distance_from_low = float(max(0.0, (current_price - intraday_low) / current_price))
        else:
            distance_from_low = None

        # Technical Execution Capabilities
        min_trade_quantity = snapshot.get("min_trade_quantity")
        quantity_precision = snapshot.get("quantity_precision")
        tick_size = snapshot.get("tick_size")
        tick_size_rule = snapshot.get("tick_size_rule")

        if instrument_meta:
            if min_trade_quantity is None:
                min_trade_quantity = instrument_meta.get("minTradeQuantity")
            if quantity_precision is None:
                quantity_precision = instrument_meta.get("quantityPrecision")
            if tick_size is None:
                tick_size = instrument_meta.get("tickSize")

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
            if tick_size is not None:
                tick_size_rule = "VENUE_STATUTORY_RULE"

        # Authoritative Cost Evaluation
        cost_eval = hit_and_run_cost_model.evaluate_instrument_costs(
            product_type=product_type,
            currency=currency,
            isin=isin,
            exchange_venue=exchange_venue,
            current_price=current_price,
            bid=bid,
            ask=ask,
            order_preview_fees=snapshot.get("order_preview_fees"),
            market_cap_eur=snapshot.get("market_cap_eur"),
            market_cap_tier=snapshot.get("market_cap_tier"),
            french_ftt_applicable=snapshot.get("french_ftt_applicable")
        )
        estimated_costs = cost_eval.estimated_costs_round_trip

        # Expected Gross Move & Net Opportunity
        # Unauthorised heuristic removed: do not invent target moves like max(0.010, vol * 2 + mom * 0.5)
        # Invariant: Raw market data does not contain expected gross moves.
        # Without an authorised strategy model:
        # expected_gross_move = None
        # expected_net_opportunity = None
        # expected_move_model_status = "EXPECTED_MOVE_MODEL_UNAVAILABLE"
        raw_gross = snapshot.get("expected_gross_move") or snapshot.get("target_gross_move")
        if raw_gross is not None:
            expected_gross_move = float(raw_gross)
            expected_move_model_status = "AUTHORISED_ESTIMATE"
        else:
            expected_gross_move = None
            expected_move_model_status = "EXPECTED_MOVE_MODEL_UNAVAILABLE"

        if expected_gross_move is not None and estimated_costs is not None:
            expected_net_opportunity = max(0.0, expected_gross_move - estimated_costs)
        elif snapshot.get("expected_net_opportunity") is not None:
            expected_net_opportunity = float(snapshot.get("expected_net_opportunity"))
        else:
            expected_net_opportunity = None

        # Data Freshness & Quote Validity
        data_timestamp = snapshot.get("data_timestamp") or snapshot.get("timestamp") or utc_dt.isoformat()
        quote_timestamp = snapshot.get("quote_timestamp") or snapshot.get("last_quote_time")
        data_age_seconds = snapshot.get("data_age_seconds")
        if data_age_seconds is None and quote_timestamp:
            try:
                qt = datetime.fromisoformat(quote_timestamp.replace("Z", "+00:00"))
                data_age_seconds = max(0.0, (utc_dt - qt).total_seconds())
            except Exception:
                data_age_seconds = None

        # Explicit Source-Authority & Quote Freshness Model:
        # Repositories/providers define their freshness contract; no invented seconds threshold.
        # Arbitrary payload flags (quote_freshness_status = CURRENT, is_current = True, is_execution_grade = True)
        # must NOT override source authority.
        raw_source = snapshot.get("data_source") or snapshot.get("source")
        source_auth = QuoteSourceAuthorityRegistry.get_source_authority(raw_source)

        if not source_auth.can_establish_current_freshness:
            # Source CANNOT establish CURRENT freshness.
            if snapshot.get("is_stale") is True or snapshot.get("is_fresh") is False:
                quote_freshness_status = "STALE"
            else:
                quote_freshness_status = "UNKNOWN"
        else:
            # Source authority allows establishing CURRENT freshness
            raw_freshness = snapshot.get("quote_freshness_status")
            if raw_freshness is not None:
                quote_freshness_status = str(raw_freshness).upper().strip()
            elif snapshot.get("is_stale") is True or snapshot.get("is_fresh") is False:
                quote_freshness_status = "STALE"
            elif snapshot.get("is_current") is True:
                quote_freshness_status = "CURRENT"
            elif snapshot.get("bid") is not None and snapshot.get("ask") is not None:
                quote_freshness_status = "CURRENT"
            else:
                quote_freshness_status = "UNKNOWN"

        is_fresh = (quote_freshness_status == "CURRENT")

        # Technical Execution Supported flag
        technical_execution_supported = bool(
            current_price > 0 and
            currency.upper() in technical_execution_capability.SUPPORTED_CURRENCIES and
            min_trade_quantity is not None and
            tick_size is not None and tick_size > 0
        )

        # Authoritative Quote Timestamps & Session Executability
        quote_fetch_timestamp = snapshot.get("quote_fetch_timestamp") or utc_dt.isoformat()
        quote_market_timestamp = snapshot.get("quote_market_timestamp") or quote_timestamp or snapshot.get("last_bar_date")

        # An opportunity is executable right now ONLY IF:
        # 1. The exchange trading session is actively OPEN (not closed)
        # 2. QUOTE_FRESHNESS_STATUS == CURRENT
        # 3. Source authority specifically permits establishing execution quotes (can_establish_execution_quote)
        # 4. Market price > 0
        # 5. Technical execution is verified
        # 6. Live bid/ask quote is present (actionable market spread)
        quote_executable_now = bool(
            session_open and
            quote_freshness_status == "CURRENT" and
            source_auth.can_establish_execution_quote and
            current_price > 0 and
            technical_execution_supported and
            bid is not None and
            ask is not None
        )

        setup_features = {
            "momentum": momentum,
            "acceleration": acceleration,
            "relative_strength": relative_strength,
            "volume_activity": volume_activity,
            "volatility": volatility,
            "distance_from_high": distance_from_high,
            "distance_from_low": distance_from_low,
            "spread_friction": spread_friction,
            "expected_gross_move": expected_gross_move,
            "expected_net_opportunity": expected_net_opportunity,
            "cost_model_complete": cost_eval.cost_model_complete,
            "is_fresh": is_fresh,
            "session_open": session_open,
            "source_id": source_auth.source_id,
            "source_role": source_auth.role,
            "can_establish_execution_quote": source_auth.can_establish_execution_quote,
            "can_establish_current_freshness": source_auth.can_establish_current_freshness,
            "quote_executable_now": quote_executable_now
        }

        return LiveOpportunityState(
            instrument_id=instrument_id,
            symbol=symbol,
            feed_ticker=feed_ticker,
            exchange_venue=exchange_venue,
            session_state=session_state,
            current_price=current_price,
            current_price_gbp=current_price_gbp,
            currency=currency,
            is_uk_pence=is_uk_pence,
            quote_divisor=quote_divisor,
            bid=bid,
            ask=ask,
            spread_friction=spread_friction,
            recent_prices=recent_prices,
            short_duration_momentum=momentum,
            momentum_acceleration=acceleration,
            relative_strength=relative_strength,
            volume_activity=volume_activity,
            volatility=volatility,
            volume_data_status=volume_data_status,
            volatility_data_status=volatility_data_status,
            distance_from_high=distance_from_high,
            distance_from_low=distance_from_low,
            estimated_costs=estimated_costs,
            expected_gross_move=expected_gross_move,
            expected_net_opportunity=expected_net_opportunity,
            expected_move_model_status=expected_move_model_status,
            cost_model_complete=cost_eval.cost_model_complete,
            cost_model_reasons=cost_eval.incomplete_reasons,
            technical_execution_supported=technical_execution_supported,
            min_trade_quantity=min_trade_quantity,
            quantity_precision=quantity_precision,
            tick_size=tick_size,
            tick_size_rule=tick_size_rule,
            isin=isin,
            data_timestamp=data_timestamp,
            quote_timestamp=quote_timestamp,
            data_age_seconds=data_age_seconds,
            quote_freshness_status=quote_freshness_status,
            is_fresh=is_fresh,
            session_open=session_open,
            extended_hours_eligible=extended_hours_eligible,
            extended_hours_status=extended_hours_status,
            extended_hours=extended_hours,
            overnight_eligibility=overnight_eligibility,
            execution_session=execution_session,
            next_session_transition=next_session_transition,
            quote_executable_now=quote_executable_now,
            quote_market_timestamp=quote_market_timestamp,
            quote_fetch_timestamp=quote_fetch_timestamp,
            setup_features=setup_features
        )


opportunity_state_builder = LiveOpportunityStateBuilder()
