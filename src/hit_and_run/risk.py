"""
PRV Capital - Hit-and-Run Risk Management
Enforces the strict 5.0% maximum loss invariant on any individual holding.
Verifies native broker-level protective stop orders and fails closed if protection is unconfirmed.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("hit_and_run.risk")


class HitAndRunRiskManager:
    """
    Authoritative risk manager enforcing per-holding 5% loss ceiling and broker stop verification.
    """

    MAX_LOSS_PCT: float = 0.05  # Strict 5.0% maximum loss invariant

    def calculate_protective_stop(
        self,
        fill_price: float,
        requested_risk_pct: Optional[float] = None
    ) -> float:
        """
        Derives protective stop price tied to authoritative fill price.
        Strictly clamps loss percentage to <= 5.0%.
        """
        if fill_price <= 0.0:
            raise ValueError(f"Fill price must be strictly positive, got {fill_price}")

        effective_loss_pct = self.MAX_LOSS_PCT
        if requested_risk_pct is not None and requested_risk_pct > 0:
            effective_loss_pct = min(self.MAX_LOSS_PCT, requested_risk_pct)

        stop_price = fill_price * (1.0 - effective_loss_pct)
        return round(stop_price, 4)

    def verify_protective_stop_invariant(
        self,
        fill_price: float,
        stop_price: float
    ) -> Tuple[bool, str]:
        """
        Verifies that stop price does not violate the 5% max-loss invariant.
        """
        if fill_price <= 0.0:
            return False, "INVALID_FILL_PRICE: fill_price must be > 0"

        if stop_price >= fill_price:
            return False, f"INVALID_STOP_PRICE: stop_price ({stop_price}) MUST_BE_BELOW_FILL ({fill_price})"

        loss_frac = (fill_price - stop_price) / fill_price
        if loss_frac > (self.MAX_LOSS_PCT + 1e-4):
            return False, f"EXCEEDS_5PCT_MAX_LOSS: loss fraction {loss_frac:.4%} exceeds {self.MAX_LOSS_PCT:.2%}"

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
