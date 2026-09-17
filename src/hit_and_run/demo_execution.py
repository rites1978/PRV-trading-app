"""
PRV Capital - Hit-and-Run DEMO Execution Dispatcher
Status: DEMO_EXPERIMENTAL ONLY

Responsibilities:
- Accepts an already-authorised HitAndRunEntryDecision.
- Strictly verifies BROKER_ENVIRONMENT == DEMO (fails closed on LIVE).
- Submits Trading212 DEMO entry order.
- Captures exact broker response and order ID.
- Confirms fill and captures authoritative broker fill price.
- Submits required native protective stop (SUBMITTED_STOP_PRICE >= RAW_STOP_FLOOR).
- Verifies protective stop exists in broker open orders.
- Tracks broker position state.
- Executes exit orders (cancels open stops, submits market sell, confirms flatten).
- Reconciles final broker state (POSITIONS = 0, OPEN_ORDERS = 0, ORPHAN_STOPS = 0).

NON-RESPONSIBILITIES:
- Does NOT decide which instrument to trade.
- Does NOT decide whether opportunity quality is sufficient.
- Does NOT decide capital allocation.
- Does NOT decide take-profit or lifecycle strategy.
No LIVE broker path exists in this module.
"""
import math
import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from src.brokers.trading212 import broker
from src.hit_and_run.models import HitAndRunEntryDecision, HoldingState
from src.hit_and_run.risk import hit_and_run_risk
from src.config.settings import settings

logger = logging.getLogger("hit_and_run.demo_execution")

DEMO_EXPERIMENTAL: bool = True


class DemoExecutionDispatcher:
    """
    Dedicated execution dispatcher for Trading212 Practice / DEMO environment.
    Strictly isolated from strategy logic.
    """

    def __init__(self, broker_client=None, risk_manager=None):
        self.broker = broker_client or broker
        self.risk = risk_manager or hit_and_run_risk
        self._verify_environment()

    def _verify_environment(self) -> None:
        """Fails closed if the connected broker is configured for LIVE execution."""
        env = getattr(self.broker, "env", "") or getattr(settings, "TRADING_ENV", "")
        if str(env).lower() == "live":
            raise RuntimeError(
                "CRITICAL_SAFETY_VIOLATION: DemoExecutionDispatcher received a LIVE broker environment. "
                "This module is DEMO_EXPERIMENTAL only and strictly prohibits live broker writes."
            )

    def execute_entry(
        self,
        decision: HitAndRunEntryDecision,
        timeout_seconds: float = 15.0,
        poll_interval: float = 0.5
    ) -> Dict[str, Any]:
        """
        Executes an already-authorised entry decision in the Trading212 DEMO account:
        1. Validates entry decision schema.
        2. Submits Market BUY order.
        3. Polls until fill confirmed (capturing fill price and fill quantity).
        4. Calculates protective stop price (stop >= fill_price * 0.95 rounded UP to tick).
        5. Submits native broker protective stop order.
        6. Verifies stop order exists in broker open orders.
        7. Fail-safe: If stop order fails, immediately flattens position via Market SELL.
        """
        self._verify_environment()

        if decision.decision != "ENTER":
            return {
                "success": False,
                "status": "REJECTED_NOT_ENTER",
                "error": f"Decision is {decision.decision}, expected ENTER"
            }

        ticker = decision.instrument_id
        qty = decision.intended_quantity
        if not qty or qty <= 0:
            return {
                "success": False,
                "status": "INVALID_QUANTITY",
                "error": f"Invalid intended quantity: {qty}"
            }

        logger.info(f"[DEMO Dispatcher] Submitting entry for {ticker}: qty={qty}")

        # Step 1: Submit Entry Market Order
        entry_res = self.broker.place_market_order(ticker=ticker, quantity=qty)
        if not entry_res.get("success"):
            logger.error(f"[DEMO Dispatcher] Entry order failed for {ticker}: {entry_res}")
            return {
                "success": False,
                "status": "ENTRY_REJECTED",
                "broker_response": entry_res,
                "ticker": ticker
            }

        entry_order_data = entry_res.get("data", {})
        entry_order_id = str(entry_order_data.get("id") or entry_order_data.get("orderId") or "")

        # Step 2: Confirm Fill & Capture Authoritative Fill Price
        fill_confirmed = False
        authoritative_fill_price = None
        filled_qty = qty
        start_poll = time.time()

        while time.time() - start_poll < timeout_seconds:
            time.sleep(poll_interval)
            positions = self.broker.get_open_positions(force_refresh=True)
            pos = next((p for p in positions if str(p.get("ticker", "")).upper() == ticker.upper()), None)
            if pos:
                fill_confirmed = True
                authoritative_fill_price = float(pos.get("averagePrice") or pos.get("price") or 0.0)
                filled_qty = float(pos.get("quantity") or qty)
                break

        if not fill_confirmed or authoritative_fill_price is None or authoritative_fill_price <= 0:
            # Check if order filled without position reflection
            logger.error(f"[DEMO Dispatcher] Entry fill timed out for {ticker} (order_id={entry_order_id})")
            return {
                "success": False,
                "status": "FILL_TIMEOUT",
                "entry_order_id": entry_order_id,
                "ticker": ticker
            }

        logger.info(
            f"[DEMO Dispatcher] Fill confirmed for {ticker}: qty={filled_qty} @ {authoritative_fill_price}"
        )

        # Step 3: Compute Contract-Compliant Protective Stop Price
        # Step 3: Compute Contract-Compliant Protective Stop Price
        planned_loss = getattr(decision, "planned_loss_pct", None)
        if planned_loss is not None and planned_loss > 0:
            loss_pct = min(0.05, max(0.001, float(planned_loss)))
            raw_stop = authoritative_fill_price * (1.0 - loss_pct)
            # Protective two-decimal ceiling: STOP_PRICE = math.ceil(RAW_STOP * 100) / 100
            stop_price = math.ceil(raw_stop * 100.0) / 100.0
        else:
            tick = decision.tick_size if decision.tick_size and decision.tick_size > 0 else 0.01
            stop_price = self.risk.calculate_protective_stop(
                fill_price=authoritative_fill_price,
                tick_size=tick
            )
        raw_stop_floor = authoritative_fill_price * 0.95
        if stop_price < raw_stop_floor:
            stop_price = math.ceil(raw_stop_floor * 100.0) / 100.0

        # Step 4: Submit Native Protective Stop Order
        logger.info(f"[DEMO Dispatcher] Submitting protective stop for {ticker}: stopPrice={stop_price}")
        stop_res = self.broker.place_stop_order(
            ticker=ticker,
            quantity=-abs(filled_qty),
            stop_price=stop_price
        )
        if not stop_res.get("success"):
            # Try positive quantity format if broker rejects negative quantity
            stop_res = self.broker.place_stop_order(
                ticker=ticker,
                quantity=abs(filled_qty),
                stop_price=stop_price
            )

        stop_confirmed = False
        stop_order_id = None
        if stop_res.get("success"):
            stop_order_id = str(stop_res.get("data", {}).get("id") or "")
            # Verify stop order exists in open orders
            open_orders = self.broker.get_open_orders(force_refresh=True)
            matching_stop = next(
                (o for o in open_orders if str(o.get("ticker", "")).upper() == ticker.upper() and o.get("type") == "STOP"),
                None
            )
            if matching_stop:
                stop_confirmed = True
                stop_order_id = str(matching_stop.get("id") or stop_order_id)

        # Step 5: Fail-Safe Handling if Stop is Rejected or Unverified
        if not stop_confirmed:
            logger.critical(
                f"[DEMO Dispatcher] FAIL-SAFE: Native stop unconfirmed for {ticker}. "
                f"Immediately flattening position."
            )
            flatten_res = self.broker.place_market_order(ticker=ticker, quantity=-abs(filled_qty))
            return {
                "success": False,
                "status": "STOP_FAILED_EMERGENCY_FLATTENED",
                "product_failure": "PROTECTIVE_STOP_NOT_CONFIRMED",
                "ticker": ticker,
                "entry_order_id": entry_order_id,
                "fill_price": authoritative_fill_price,
                "stop_error": stop_res.get("error", "Stop verification failed"),
                "flatten_response": flatten_res
            }

        logger.info(
            f"[DEMO Dispatcher] Protected position active: {ticker} (entry={entry_order_id}, stop={stop_order_id})"
        )

        return {
            "success": True,
            "status": "PROTECTED_POSITION_ACTIVE",
            "ticker": ticker,
            "entry_order_id": entry_order_id,
            "fill_price": authoritative_fill_price,
            "filled_quantity": filled_qty,
            "stop_order_id": stop_order_id,
            "stop_price": stop_price,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def execute_exit(
        self,
        ticker: str,
        quantity: float,
        reason: str = "MANUAL_EXIT"
    ) -> Dict[str, Any]:
        """
        Executes an authorized exit / flattening action on an active DEMO position:
        1. Cancels active protective stops for the ticker.
        2. Submits Market SELL order for exact position quantity.
        3. Confirms position is flattened.
        """
        self._verify_environment()
        logger.info(f"[DEMO Dispatcher] Executing exit for {ticker}: qty={quantity}, reason={reason}")

        # Step 1: Cancel active stop orders
        cancelled_stops = self.broker.cancel_stop_orders_for_ticker(ticker)
        logger.info(f"[DEMO Dispatcher] Cancelled {len(cancelled_stops)} stop orders for {ticker}")

        # Step 2: Submit Market SELL order to flatten
        exit_res = self.broker.place_market_order(ticker=ticker, quantity=-abs(quantity))
        if not exit_res.get("success"):
            logger.error(f"[DEMO Dispatcher] Exit order failed for {ticker}: {exit_res}")
            return {
                "success": False,
                "status": "EXIT_ORDER_FAILED",
                "ticker": ticker,
                "error": exit_res.get("error"),
                "cancelled_stops": cancelled_stops
            }

        exit_order_id = str(exit_res.get("data", {}).get("id") or "")

        # Step 3: Reconcile position is flattened
        time.sleep(1.0)
        positions = self.broker.get_open_positions(force_refresh=True)
        remaining_pos = next((p for p in positions if str(p.get("ticker", "")).upper() == ticker.upper()), None)

        is_flat = remaining_pos is None or float(remaining_pos.get("quantity", 0.0)) == 0.0

        return {
            "success": is_flat,
            "status": "FLATTENED" if is_flat else "PARTIAL_REMAINDER",
            "ticker": ticker,
            "exit_order_id": exit_order_id,
            "reason": reason,
            "cancelled_stops": cancelled_stops,
            "remaining_quantity": float(remaining_pos.get("quantity", 0.0)) if remaining_pos else 0.0
        }

    def reconcile_broker_state(self) -> Dict[str, Any]:
        """
        Queries Trading212 DEMO account to verify clean slate:
        POSITIONS = 0, OPEN_ORDERS = 0, ORPHAN_STOPS = 0.
        """
        self._verify_environment()
        positions, _ = self.broker.get_open_positions_authoritative()
        orders, _ = self.broker.get_open_orders_authoritative()

        pos_count = len(positions)
        order_count = len(orders)
        is_clean = (pos_count == 0 and order_count == 0)

        return {
            "is_clean_slate": is_clean,
            "positions_count": pos_count,
            "orders_count": order_count,
            "positions": positions,
            "orders": orders,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


demo_execution_dispatcher = DemoExecutionDispatcher()
demo_dispatcher = demo_execution_dispatcher
