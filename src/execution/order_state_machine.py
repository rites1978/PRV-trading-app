"""
🏛️ PRV CAPITAL | AUTHORITATIVE ORDER STATE MACHINE & ATOMIC PORTFOLIO RESERVATION
Enforces:
1. Strict Order Lifecycle State Machine with audit trail
2. Idempotency keys and client order IDs to prevent duplicate executions
3. Thread-safe atomic reservations for Cash, Sector Exposure, and Position Limits
"""
import uuid
import hashlib
import threading
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from src.config.settings import settings


class InvalidStateTransitionError(RuntimeError):
    """Raised when an order attempts an illegal state transition."""
    pass


class OrderState(str, Enum):
    SIGNAL_CREATED = "SIGNAL_CREATED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"
    SIGNAL_APPROVED = "SIGNAL_APPROVED"
    PENDING_MARKET_OPEN = "PENDING_MARKET_OPEN"
    ORDER_READY = "ORDER_READY"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    EXIT_PENDING = "EXIT_PENDING"
    EXIT_SUBMITTED = "EXIT_SUBMITTED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


# Valid state transitions lookup
VALID_TRANSITIONS: Dict[OrderState, List[OrderState]] = {
    OrderState.SIGNAL_CREATED: [OrderState.SIGNAL_APPROVED, OrderState.SIGNAL_REJECTED],
    OrderState.SIGNAL_REJECTED: [],
    OrderState.SIGNAL_APPROVED: [OrderState.PENDING_MARKET_OPEN, OrderState.ORDER_READY, OrderState.FAILED, OrderState.SIGNAL_REJECTED],
    OrderState.PENDING_MARKET_OPEN: [OrderState.ORDER_READY, OrderState.CANCELLED, OrderState.SIGNAL_REJECTED],
    OrderState.ORDER_READY: [OrderState.ORDER_SUBMITTED, OrderState.FAILED, OrderState.CANCELLED],
    OrderState.ORDER_SUBMITTED: [OrderState.ACKNOWLEDGED, OrderState.FILLED, OrderState.PARTIAL_FILL, OrderState.FAILED, OrderState.CANCEL_PENDING],
    OrderState.ACKNOWLEDGED: [OrderState.PARTIAL_FILL, OrderState.FILLED, OrderState.CANCEL_PENDING, OrderState.FAILED],
    OrderState.PARTIAL_FILL: [OrderState.FILLED, OrderState.CANCEL_PENDING, OrderState.FAILED],
    OrderState.FILLED: [OrderState.EXIT_PENDING],
    OrderState.CANCEL_PENDING: [OrderState.CANCELLED, OrderState.FILLED, OrderState.PARTIAL_FILL],
    OrderState.CANCELLED: [],
    OrderState.EXIT_PENDING: [OrderState.EXIT_SUBMITTED, OrderState.FAILED],
    OrderState.EXIT_SUBMITTED: [OrderState.CLOSED, OrderState.FAILED],
    OrderState.CLOSED: [],
    OrderState.FAILED: []
}


class ManagedOrder:
    """
    Stateful order entity with complete transition audit trail and idempotency guarantees.
    """
    def __init__(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        client_order_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        t212_ticker: Optional[str] = None,
        limit_price: Optional[float] = None,
        target_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        exchange: Optional[str] = None,
        is_uk: bool = False
    ):
        now_str = datetime.now(timezone.utc).isoformat()
        self.client_order_id = client_order_id or f"PRV_ORD_{int(datetime.now(timezone.utc).timestamp()*1000)}_{symbol}_{uuid.uuid4().hex[:6]}"
        self.symbol = symbol.upper()
        self.side = side.upper()
        self.quantity = float(quantity)
        self.price = float(price)
        self.t212_ticker = t212_ticker or (f"{self.symbol}l_EQ" if is_uk else f"{self.symbol}_US_EQ")
        self.limit_price = float(limit_price) if limit_price is not None else float(price)
        self.target_price = float(target_price) if target_price is not None else 0.0
        self.stop_loss_price = float(stop_loss_price) if stop_loss_price is not None else 0.0
        self.exchange = exchange or ("LSE" if is_uk else "NYSE/NASDAQ")
        self.is_uk = is_uk
        self.broker_order_id: Optional[str] = None
        self.fill_quantity: float = 0.0
        self.fill_price: float = 0.0
        self.state: OrderState = OrderState.SIGNAL_CREATED
        self.retry_count: int = 0
        self.last_broker_status: str = "INITIALIZED"
        self.created_at: str = now_str
        self.updated_at: str = now_str
        self.reserved_cash_gbp: float = 0.0

        if idempotency_key:
            self.idempotency_key = idempotency_key
        else:
            time_bucket = now_str[:16] # 1-minute bucket for deduplication
            key_raw = f"{self.symbol}_{self.side}_{self.quantity:.4f}_{self.price:.4f}_{time_bucket}"
            self.idempotency_key = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()

        self.history: List[Dict[str, Any]] = [
            {
                "from_state": None,
                "to_state": OrderState.SIGNAL_CREATED.value,
                "timestamp": now_str,
                "reason": "Order entity created"
            }
        ]

    def transition_to(self, new_state: OrderState, reason: str = "") -> None:
        """Atomically transition order state while validating lifecycle invariants."""
        if new_state not in VALID_TRANSITIONS.get(self.state, []):
            raise InvalidStateTransitionError(
                f"Illegal transition from {self.state.value} to {new_state.value} for order {self.client_order_id}"
            )
        now_str = datetime.now(timezone.utc).isoformat()
        self.history.append({
            "from_state": self.state.value,
            "to_state": new_state.value,
            "timestamp": now_str,
            "reason": reason
        })
        self.state = new_state
        self.updated_at = now_str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "idempotency_key": self.idempotency_key,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "fill_quantity": self.fill_quantity,
            "fill_price": self.fill_price,
            "state": self.state.value,
            "retry_count": self.retry_count,
            "last_broker_status": self.last_broker_status,
            "reserved_cash_gbp": self.reserved_cash_gbp,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": list(self.history)
        }


class PortfolioReservationManager:
    """
    Thread-safe atomic reservation engine preventing cash and capacity race conditions.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(PortfolioReservationManager, cls).__new__(cls)
                cls._instance._reservations: Dict[str, Dict[str, Any]] = {}
                cls._instance._active_idempotency_keys: Dict[str, str] = {}
            return cls._instance

    def reserve(
        self,
        order: ManagedOrder,
        sector: str,
        expected_consideration_gbp: Optional[float] = None,
        fee_buffer_gbp: Optional[float] = None,
        current_broker_free_cash_gbp: Optional[float] = None,
        min_cash_reserve_gbp: Optional[float] = None,
        sector_current_exposure_gbp: Optional[float] = None,
        max_sector_budget_gbp: Optional[float] = None,
        current_position_count: Optional[int] = None,
        max_positions_limit: Optional[int] = None,
        existing_held_tickers: Optional[List[str]] = None,
        **kwargs
    ) -> Tuple[bool, str]:
        """
        Attempts atomic reservation for consideration + tax/fx buffer before order submission.
        """
        # Support kwargs extraction
        if current_broker_free_cash_gbp is None:
            current_broker_free_cash_gbp = float(kwargs.get("free_cash", 50000.0))
        if total_nav := kwargs.get("total_nav"):
            if min_cash_reserve_gbp is None:
                cash_pct = settings.REQUIRED_CASH_RESERVE_PCT if settings.REQUIRED_CASH_RESERVE_PCT <= 1.0 else (settings.REQUIRED_CASH_RESERVE_PCT / 100.0)
                min_cash_reserve_gbp = float(total_nav) * cash_pct
            if max_sector_budget_gbp is None:
                sector_pct = settings.MAX_SECTOR_EXPOSURE_PCT if settings.MAX_SECTOR_EXPOSURE_PCT <= 1.0 else (settings.MAX_SECTOR_EXPOSURE_PCT / 100.0)
                max_sector_budget_gbp = float(total_nav) * sector_pct
        min_cash_reserve_gbp = min_cash_reserve_gbp or 22500.0
        max_sector_budget_gbp = max_sector_budget_gbp or 15000.0

        if positions := kwargs.get("positions"):
            if current_position_count is None:
                current_position_count = len(positions)
            if sector_current_exposure_gbp is None:
                sector_current_exposure_gbp = sum(float(p.get("market_value_gbp", 0.0)) for p in positions if str(p.get("sector", "")).upper() == sector.upper())
            if existing_held_tickers is None:
                existing_held_tickers = [str(p.get("symbol", "")).upper() for p in positions]

        current_position_count = current_position_count or 0
        sector_current_exposure_gbp = sector_current_exposure_gbp or 0.0
        max_positions_limit = max_positions_limit or getattr(settings, "MAX_CONCURRENT_POSITIONS", 15)
        existing_held_tickers = existing_held_tickers or []
        expected_consideration_gbp = expected_consideration_gbp if expected_consideration_gbp is not None else (order.quantity * order.price)
        fee_buffer_gbp = fee_buffer_gbp if fee_buffer_gbp is not None else 15.0

        with self._lock:
            # 1. Idempotency Check: Prevent duplicate order attempts
            if order.idempotency_key in self._active_idempotency_keys:
                prior_id = self._active_idempotency_keys[order.idempotency_key]
                return False, f"IDEMPOTENCY_REJECTION: Identical order {prior_id} already active."

            # 2. Duplicate Ticker Check: No multiple active orders/positions for same symbol
            sym = order.symbol.upper()
            if sym in existing_held_tickers:
                return False, f"HOLD_CASH: Position for {sym} already exists in portfolio."

            for res in self._reservations.values():
                if res["symbol"] == sym:
                    return False, f"HOLD_CASH: Active reservation already pending for {sym} ({res['client_order_id']})."

            # 3. Position Count Limit Check
            total_active_positions = current_position_count + len(self._reservations)
            if total_active_positions >= max_positions_limit:
                return False, f"HOLD_CASH: Max positions limit ({max_positions_limit}) reached."

            # 4. Atomic Cash Floor Check
            total_required = round(expected_consideration_gbp + fee_buffer_gbp, 2)
            currently_reserved_cash = sum(r["amount_gbp"] for r in self._reservations.values())
            effective_unreserved_cash = current_broker_free_cash_gbp - currently_reserved_cash

            if effective_unreserved_cash - total_required < min_cash_reserve_gbp:
                avail_disp = max(0.0, effective_unreserved_cash - min_cash_reserve_gbp)
                return False, f"HOLD_CAPITAL_PRESERVATION_CASH: Required £{total_required:,.2f} exceeds unreserved deployable cash £{avail_disp:,.2f} (protecting £{min_cash_reserve_gbp:,.2f} floor)."

            # 5. Sector Exposure Limit Check
            currently_reserved_sector = sum(
                r["amount_gbp"] for r in self._reservations.values() if r["sector"].upper() == sector.upper()
            )
            total_projected_sector = sector_current_exposure_gbp + currently_reserved_sector + total_required
            if total_projected_sector > max_sector_budget_gbp:
                return False, f"HOLD_CASH: Sector {sector} projected exposure £{total_projected_sector:,.2f} exceeds budget £{max_sector_budget_gbp:,.2f}."

            # All checks passed: Record atomic reservation
            order.reserved_cash_gbp = total_required
            self._reservations[order.client_order_id] = {
                "client_order_id": order.client_order_id,
                "symbol": sym,
                "sector": sector,
                "amount_gbp": total_required,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self._active_idempotency_keys[order.idempotency_key] = order.client_order_id
            return True, f"RESERVATION_APPROVED: £{total_required:,.2f} reserved."

    def release(self, client_order_id: str) -> None:
        """Releases cash and capacity reservations immediately upon cancellation or failure."""
        with self._lock:
            if client_order_id in self._reservations:
                del self._reservations[client_order_id]
            # Clean matching idempotency key
            keys_to_remove = [k for k, v in self._active_idempotency_keys.items() if v == client_order_id]
            for k in keys_to_remove:
                del self._active_idempotency_keys[k]

    def get_total_reserved_cash(self) -> float:
        with self._lock:
            return round(sum(r["amount_gbp"] for r in self._reservations.values()), 2)

    def get_active_reservations(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._reservations.values())

    def reset(self) -> None:
        """Clear all active reservations (for testing / session re-initialization)."""
        with self._lock:
            self._reservations.clear()
            self._active_idempotency_keys.clear()


portfolio_reservations = PortfolioReservationManager()
