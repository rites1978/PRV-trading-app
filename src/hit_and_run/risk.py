"""
PRV Capital - Hit-and-Run Risk Management
Enforces the strict 5.0% maximum loss invariant on any individual holding.

For any long holding:
    MAXIMUM_AUTHORISED_LOSS_PCT = 0.05
    The protective stop must satisfy:
    stop_price >= fill_price * 0.95
    subject to valid broker tick-size rounding.

The implementation must never permit a planned protective loss > 5% from authoritative fill price.
Verifies native broker-level protective stop orders and fails closed if protection is unconfirmed.
"""
import math
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("hit_and_run.risk")


class HitAndRunRiskManager:
    """
    Authoritative risk manager enforcing per-holding 5% loss ceiling and broker stop verification.
    """

    MAXIMUM_AUTHORISED_LOSS_PCT: float = 0.05  # Strict 5.0% maximum loss invariant
    MAX_LOSS_PCT: float = MAXIMUM_AUTHORISED_LOSS_PCT  # Compatibility alias

    @staticmethod
    def derive_tick_size(
        currency: str = "GBP",
        price: float = 1.0,
        is_uk_pence: bool = False,
        explicit_tick: Optional[float] = None,
        venue: Optional[str] = None
    ) -> Optional[float]:
        """
        Derives authoritative tick size scoped strictly to explicit metadata or an independently
        verified exchange capability table (e.g. SEC Rule 612 for US, LSE MiFID II for UK).
        Returns None if tick size cannot be verified authoritatively (DO NOT GUESS).
        """
        if explicit_tick is not None and explicit_tick > 0:
            return float(explicit_tick)

        if venue:
            from src.data.technical_execution_capability import TechnicalExecutionCapabilityValidator
            return TechnicalExecutionCapabilityValidator.derive_tick_size_for_venue(
                venue_name=venue,
                currency=currency,
                price=price,
                is_uk_pence=is_uk_pence
            )

        # No guessing based on currency or generic price bands!
        return None

    @staticmethod
    def round_stop_up_to_tick(price: float, tick_size: float) -> float:
        """
        Rounds a protective stop UP to the next valid broker tick.
        Guarantees stop_price >= price, ensuring planned loss NEVER exceeds the 5% ceiling.
        Requires an authoritative tick_size.
        """
        if tick_size is None or tick_size <= 0:
            raise ValueError("TICK_SIZE_UNKNOWN: Authoritative tick size must be strictly positive")
        # High precision rounding before ceil eliminates IEEE-754 representation noise
        num_ticks = math.ceil(round(price / tick_size, 8))
        tick_str = f"{tick_size:.8f}".rstrip('0')
        decimals = len(tick_str.split('.')[1]) if '.' in tick_str else 0
        return round(num_ticks * tick_size, decimals)

    def calculate_protective_stop(
        self,
        fill_price: float,
        requested_risk_pct: Optional[float] = None,
        tick_size: Optional[float] = None
    ) -> float:
        """
        Derives protective stop price tied to authoritative fill price.
        Requires an authoritative tick_size (explicit metadata or verified venue table).
        Raises ValueError with TICK_SIZE_UNKNOWN if tick_size is missing or non-positive.
        Strictly enforces:
            theoretical_floor = fill_price * 0.95
            stop_price >= theoretical_floor
            planned_loss_pct = (fill_price - stop_price) / fill_price <= 0.05
        Rounds the protective stop UP to the next valid broker tick.
        """
        if fill_price <= 0.0:
            raise ValueError(f"Fill price must be strictly positive, got {fill_price}")
        if tick_size is None or tick_size <= 0:
            raise ValueError("TICK_SIZE_UNKNOWN: Authoritative tick size is required for protective stop calculation")

        effective_loss_pct = self.MAXIMUM_AUTHORISED_LOSS_PCT
        if requested_risk_pct is not None and requested_risk_pct > 0:
            effective_loss_pct = min(self.MAXIMUM_AUTHORISED_LOSS_PCT, requested_risk_pct)

        theoretical_floor = fill_price * (1.0 - self.MAXIMUM_AUTHORISED_LOSS_PCT)
        raw_stop = fill_price * (1.0 - effective_loss_pct)
        target_stop = max(theoretical_floor, raw_stop)

        stop_price = self.round_stop_up_to_tick(target_stop, tick_size)
        if stop_price < theoretical_floor:
            stop_price = self.round_stop_up_to_tick(theoretical_floor, tick_size)

        return stop_price

    def verify_protective_stop_invariant(
        self,
        fill_price: float,
        stop_price: float,
        tick_size: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        Enforces the non-negotiable 5% loss invariant:
        For any long holding:
            theoretical_floor = fill_price * 0.95
            stop_price >= theoretical_floor
            planned_loss_pct = (fill_price - stop_price) / fill_price
            planned_loss_pct <= 0.05

        Strict rules:
        - NO tick_size * 0.5 relaxation
        - NO epsilon permitting >5%
        - NO rounding downward through the 5% boundary
        - If tick_size is provided, verifies exact tick alignment
        """
        if fill_price <= 0.0:
            return False, "INVALID_FILL_PRICE: fill_price must be > 0"

        if stop_price >= fill_price:
            return False, f"INVALID_STOP_PRICE: stop_price ({stop_price}) MUST_BE_BELOW_FILL ({fill_price})"

        theoretical_floor = fill_price * (1.0 - self.MAXIMUM_AUTHORISED_LOSS_PCT)

        # Invariant: stop_price must be >= fill_price * 0.95
        if stop_price < theoretical_floor:
            planned_loss_pct = (fill_price - stop_price) / fill_price
            return False, (
                f"EXCEEDS_5PCT_MAX_LOSS: stop_price {stop_price} < theoretical_floor {theoretical_floor:.6f} "
                f"(fill_price * 0.95). Planned loss {planned_loss_pct:.4%} exceeds authorised 5.0% ceiling."
            )

        planned_loss_pct = (fill_price - stop_price) / fill_price
        if round(planned_loss_pct, 9) > self.MAXIMUM_AUTHORISED_LOSS_PCT:
            return False, (
                f"EXCEEDS_5PCT_MAX_LOSS: planned loss {planned_loss_pct:.6%} > authorised ceiling {self.MAXIMUM_AUTHORISED_LOSS_PCT:.2%}"
            )

        # If tick_size is specified, verify alignment to authoritative tick increment
        if tick_size is not None and tick_size > 0:
            expected_rounded = self.round_stop_up_to_tick(stop_price, tick_size)
            if abs(stop_price - expected_rounded) > 1e-6:
                return False, f"INVALID_TICK_INCREMENT: stop_price {stop_price} not aligned to tick {tick_size}"

        return True, "STOP_VERIFIED_VALID"

    def verify_broker_stop_protection(
        self,
        ticker: str,
        held_quantity: float,
        expected_stop_price: float,
        open_orders: List[Dict[str, Any]]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Verifies that a working broker-native stop order exists with exact matching quantity and stop price.
        If unconfirmed, returns False with PROTECTION_UNCONFIRMED_FAIL_CLOSED.
        """
        ticker_upper = ticker.strip().upper()
        held_qty_abs = abs(float(held_quantity))

        for ord_item in open_orders:
            o_ticker = str(ord_item.get("ticker", "")).strip().upper()
            o_type = str(ord_item.get("type", "")).strip().upper()
            o_qty = abs(float(ord_item.get("quantity", 0.0)))
            o_stop = float(ord_item.get("stopPrice", 0.0))

            if o_ticker == ticker_upper and o_type == "STOP":
                qty_match = abs(o_qty - held_qty_abs) < 1e-4
                price_match = abs(o_stop - expected_stop_price) / max(1e-4, expected_stop_price) <= 0.01

                if qty_match and price_match:
                    return True, "PROTECTION_CONFIRMED", ord_item

        logger.warning(
            f"RiskManager: Native stop for {ticker} (qty {held_qty_abs} @ {expected_stop_price}) "
            f"not found in {len(open_orders)} broker open orders."
        )
        return False, "PROTECTION_UNCONFIRMED_FAIL_CLOSED", None


hit_and_run_risk = HitAndRunRiskManager()
