"""
🏛️ PRV CAPITAL | REALISTIC EXECUTION & FILL SIMULATOR
Institutional execution modeling with next-bar fills and versioned cost integration.

Invariants:
1. Zero look-ahead fills: Market orders placed on bar t execute on bar t+1 OPEN.
2. Limit orders fill strictly if bar price reaches the limit boundary.
3. Stop losses model gap slippage when bar opens below the stop.
4. All transactions incur explicit versioned costs (FX, SDRT, PTM, SEC, FINRA, Spread, Slippage).
"""
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Dict, Optional, Tuple, Any
import pandas as pd
import logging
from src.research.cost_schedule import (
    CostScheduleRepository,
    Jurisdiction,
    InstrumentClass,
    FeeType
)

logger = logging.getLogger(__name__)


class OrderType(str, Enum):
    MARKET = "MARKET"                 # Fills on next available bar Open
    LIMIT = "LIMIT"                   # Fills if price touches limit price
    STOP_LOSS = "STOP_LOSS"           # Triggers if price breaches stop level


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    created_at: pd.Timestamp
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    jurisdiction: Jurisdiction = Jurisdiction.US
    instrument_class: InstrumentClass = InstrumentClass.EQUITY
    timeframe: str = "1m"
    status: str = "PENDING"           # PENDING, FILLED, CANCELLED, EXPIRED


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    fill_time: pd.Timestamp
    fill_price_gbp: float             # Execution price in GBP
    quantity: float
    notional_gbp: float
    itemized_frictions: Dict[str, float]
    total_friction_gbp: float
    slippage_bps_applied: float


class ExecutionSimulator:
    """
    Simulates realistic broker fills and calculates exact point-in-time frictions.
    """
    def __init__(self, cost_repo: Optional[CostScheduleRepository] = None):
        self.cost_repo = cost_repo or CostScheduleRepository()

    def simulate_fill(
        self,
        order: Order,
        execution_bar: pd.Series,
        bar_timestamp: pd.Timestamp,
        gbpusd_rate: float = 1.30,
        participation_rate_cap: float = 0.05
    ) -> Optional[Fill]:
        """
        Evaluates whether an order fills against execution_bar (bar t+1).
        Returns a Fill object if executed, or None if conditions not met.
        """
        trade_date = pd.to_datetime(bar_timestamp).date()
        open_p = float(execution_bar["Open"])
        high_p = float(execution_bar["High"])
        low_p = float(execution_bar["Low"])
        close_p = float(execution_bar["Close"])
        volume = float(execution_bar.get("Volume", 1e6))

        # Base price in instrument currency
        raw_fill_price = 0.0
        slippage_bps = 2.0 if order.jurisdiction == Jurisdiction.US else 3.0

        if order.order_type == OrderType.MARKET:
            # Fills on bar Open
            raw_fill_price = open_p

        elif order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY:
                if low_p <= order.limit_price:
                    # Fills at the limit price or open (whichever is better)
                    raw_fill_price = min(open_p, order.limit_price)
                else:
                    return None  # Limit price not reached
            else:  # SELL
                if high_p >= order.limit_price:
                    raw_fill_price = max(open_p, order.limit_price)
                else:
                    return None

        elif order.order_type == OrderType.STOP_LOSS:
            if order.side == OrderSide.SELL:
                if low_p <= order.stop_price:
                    # If open gapped below stop price, fill at open (gap slip)
                    if open_p < order.stop_price:
                        raw_fill_price = open_p
                        slippage_bps += 5.0  # Additional gap slippage penalty
                    else:
                        raw_fill_price = order.stop_price
                else:
                    return None  # Stop not triggered
            else:
                return None

        # Convert price to GBP if US asset
        if order.jurisdiction == Jurisdiction.US:
            fill_price_gbp = round(raw_fill_price / gbpusd_rate, 4)
        else:
            fill_price_gbp = round(raw_fill_price, 4)

        notional_gbp = round(order.quantity * fill_price_gbp, 2)

        # Query versioned cost engine
        if order.side == OrderSide.BUY:
            costs = self.cost_repo.calculate_trade_costs(
                trade_date=trade_date,
                jurisdiction=order.jurisdiction,
                instrument_class=order.instrument_class,
                buy_notional_gbp=notional_gbp,
                sell_notional_gbp=0.0,
                shares=order.quantity,
                gbpusd_rate=gbpusd_rate,
                slippage_bps_override=slippage_bps
            )
            # Only keep entry leg costs
            itemized = {
                "buy_fx_gbp": costs["buy_fx_gbp"],
                "sdrt_gbp": costs["sdrt_gbp"],
                "ptm_levy_gbp": costs["ptm_levy_gbp"] / 2.0 if costs["ptm_levy_gbp"] > 0 else 0.0,
                "buy_spread_gbp": costs["buy_spread_gbp"],
                "buy_slippage_gbp": costs["buy_slippage_gbp"]
            }
            total_entry_friction = round(sum(itemized.values()), 4)
            order.status = "FILLED"
            return Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                fill_time=bar_timestamp,
                fill_price_gbp=fill_price_gbp,
                quantity=order.quantity,
                notional_gbp=notional_gbp,
                itemized_frictions=itemized,
                total_friction_gbp=total_entry_friction,
                slippage_bps_applied=slippage_bps
            )

        else:  # SELL
            costs = self.cost_repo.calculate_trade_costs(
                trade_date=trade_date,
                jurisdiction=order.jurisdiction,
                instrument_class=order.instrument_class,
                buy_notional_gbp=0.0,
                sell_notional_gbp=notional_gbp,
                shares=order.quantity,
                gbpusd_rate=gbpusd_rate,
                slippage_bps_override=slippage_bps
            )
            # Only keep exit leg costs
            itemized = {
                "sell_fx_gbp": costs["sell_fx_gbp"],
                "sec_fee_gbp": costs["sec_fee_gbp"],
                "finra_taf_gbp": costs["finra_taf_gbp"],
                "ptm_levy_gbp": costs["ptm_levy_gbp"] / 2.0 if costs["ptm_levy_gbp"] > 0 else 0.0,
                "sell_spread_gbp": costs["sell_spread_gbp"],
                "sell_slippage_gbp": costs["sell_slippage_gbp"]
            }
            total_exit_friction = round(sum(itemized.values()), 4)
            order.status = "FILLED"
            return Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                fill_time=bar_timestamp,
                fill_price_gbp=fill_price_gbp,
                quantity=order.quantity,
                notional_gbp=notional_gbp,
                itemized_frictions=itemized,
                total_friction_gbp=total_exit_friction,
                slippage_bps_applied=slippage_bps
            )
