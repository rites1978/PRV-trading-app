"""
PRV Capital — Authoritative Broker Ledger Service
Reconstructs the ground-truth challenge ledger directly and exclusively
from the Trading212 Public API (orders, fills, portfolio, cash summary).
Never relies on synthetic report mockups or hardcoded assumptions.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, date, timezone
import logging
from src.brokers.trading212 import broker

logger = logging.getLogger("prv.broker_ledger")

CHALLENGE_START_DATE = date(2026, 9, 3)
CHALLENGE_START_NAV = 50000.00

class BrokerLedgerService:
    def __init__(self):
        self._cached_ledger: Optional[Dict[str, Any]] = None
        self._cached_time: float = 0.0

    def get_challenge_day(self) -> int:
        now_date = datetime.now(timezone.utc).date()
        delta = (now_date - CHALLENGE_START_DATE).days
        return max(1, delta + 1)

    def fetch_ground_truth_ledger(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Pull every broker fill, order, tax, fee, and position directly from Trading212.
        Reconciles cash, invested capital, unrealized P&L, realized P&L, SDRT, and FX fees.
        """
        import time
        now = time.time()
        if not force_refresh and self._cached_ledger and (now - self._cached_time) < 10.0:
            return dict(self._cached_ledger)

        # 1. Fetch live account summary (cash, invested, NAV, PPL, result)
        acc_summary = broker.get_account_summary(force_refresh=True)
        free_cash = round(float(acc_summary.get("free_cash", 0.0)), 2)
        invested = round(float(acc_summary.get("invested", 0.0)), 2)
        total_nav = round(float(acc_summary.get("total_value", 0.0)), 2)
        unrealized_ppl = round(float(acc_summary.get("ppl", 0.0)), 2)
        broker_result = round(float(acc_summary.get("result", 0.0)), 2)

        # 2. Fetch live open positions
        positions = broker.get_open_positions(force_refresh=True) or []

        # 3. Pull ALL historical orders with full pagination
        all_order_items = []
        path = "equity/history/orders?limit=50"
        while path:
            try:
                res = broker._request_with_retry("GET", path)
                if res.status_code != 200:
                    break
                d = res.json()
                items = d.get("items", [])
                all_order_items.extend(items)
                next_page = d.get("nextPagePath")
                path = next_page.replace("/api/v0/", "") if next_page else None
            except Exception as e:
                logger.error(f"Error paginating broker historical orders: {e}")
                break

        # 4. Parse filled transactions
        entries = []
        exits = []
        total_sdrt = 0.0
        total_fx = 0.0
        total_other_taxes = 0.0
        realized_pnl_by_ticker: Dict[str, float] = {}

        for item in all_order_items:
            order = item.get("order", {})
            fill = item.get("fill", {})
            if order.get("status") != "FILLED":
                continue

            order_id = str(order.get("id"))
            ticker = order.get("ticker", "UNKNOWN")
            side = order.get("side", "UNKNOWN")
            qty = float(fill.get("quantity", order.get("quantity", 0.0)))
            price = float(fill.get("price", 0.0))
            filled_at = fill.get("filledAt") or order.get("createdAt") or ""
            impact = fill.get("walletImpact", {}) or {}
            net_val = round(float(impact.get("netValue", 0.0)), 2)
            realized_pnl = impact.get("realisedProfitLoss")
            taxes = impact.get("taxes", []) or []

            order_sdrt = round(sum(abs(float(t.get("quantity", 0.0))) for t in taxes if t.get("name") == "STAMP_DUTY_RESERVE_TAX"), 2)
            order_fx = round(sum(abs(float(t.get("quantity", 0.0))) for t in taxes if t.get("name") == "CURRENCY_CONVERSION_FEE"), 2)
            order_other = round(sum(abs(float(t.get("quantity", 0.0))) for t in taxes if t.get("name") not in ("STAMP_DUTY_RESERVE_TAX", "CURRENCY_CONVERSION_FEE")), 2)

            total_sdrt += order_sdrt
            total_fx += order_fx
            total_other_taxes += order_other

            record = {
                "order_id": order_id,
                "ticker": ticker,
                "side": side,
                "quantity": abs(qty),
                "fill_price": price,
                "timestamp": filled_at,
                "net_value_gbp": net_val,
                "sdrt_gbp": order_sdrt,
                "fx_fee_gbp": order_fx,
                "other_cost_gbp": order_other,
                "realized_pnl_gbp": round(float(realized_pnl), 2) if realized_pnl is not None else None
            }

            if side == "BUY":
                entries.append(record)
            elif side == "SELL":
                exits.append(record)
                if realized_pnl is not None:
                    pnl_val = round(float(realized_pnl), 2)
                    realized_pnl_by_ticker[ticker] = round(realized_pnl_by_ticker.get(ticker, 0.0) + pnl_val, 2)

        # Sort chronologically
        entries.sort(key=lambda x: x["timestamp"])
        exits.sort(key=lambda x: x["timestamp"])

        total_sdrt = round(total_sdrt, 2)
        total_fx = round(total_fx, 2)
        total_other_taxes = round(total_other_taxes, 2)
        total_costs = round(total_sdrt + total_fx + total_other_taxes, 2)

        # Realized P&L: derived from actual filled exits
        derived_realized_pnl = round(sum(e["realized_pnl_gbp"] for e in exits if e["realized_pnl_gbp"] is not None), 2)

        # Invariant checks:
        nav_delta = round(total_nav - CHALLENGE_START_NAV, 2)
        accounted_delta = round(derived_realized_pnl + unrealized_ppl - total_costs, 2)
        variance = round(abs(nav_delta - accounted_delta), 4)

        ledger = {
            "challenge_start_date": CHALLENGE_START_DATE.isoformat(),
            "challenge_day": self.get_challenge_day(),
            "starting_nav_gbp": CHALLENGE_START_NAV,
            "broker_nav_gbp": total_nav,
            "cash_gbp": free_cash,
            "invested_value_gbp": invested,
            "broker_derived_unrealized_pnl_gbp": unrealized_ppl,
            "broker_derived_realized_pnl_gbp": derived_realized_pnl,
            "broker_result_gbp": broker_result,
            "sdrt_paid_gbp": total_sdrt,
            "fx_fees_paid_gbp": total_fx,
            "other_costs_paid_gbp": total_other_taxes,
            "broker_derived_total_costs_gbp": total_costs,
            "nav_delta_gbp": nav_delta,
            "accounted_delta_gbp": accounted_delta,
            "prv_ledger_variance_gbp": variance,
            "is_reconciled": bool(variance <= 0.01),
            "open_positions_count": len(positions),
            "open_positions": positions,
            "total_entries_count": len(entries),
            "total_exits_count": len(exits),
            "entries": entries,
            "exits": exits,
            "realized_pnl_by_ticker": realized_pnl_by_ticker,
            "sync_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        }

        self._cached_ledger = ledger
        self._cached_time = now
        return ledger

broker_ledger = BrokerLedgerService()
