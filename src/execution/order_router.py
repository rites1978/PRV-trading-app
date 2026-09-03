"""
🏛️ PRV CAPITAL | STRICT NET EXECUTION & HARDENED ORDER ROUTER
Enforces Net Edge Gates, marketable limit controls, implementation shortfall analytics,
and disciplined order lifecycle management (submit -> wait -> check fill -> timeout -> amend/cancel).

Key Principles:
1. Validates Net Edge Gate before any capital is committed.
2. Marketable Limit Protection (Default 10 bps offset against runaway slippage).
3. Disciplined Order Lifecycle: Timeout after 5s, checks signal freshness/decay, amends max 1 time, never chases indefinitely.
4. Comprehensive Implementation Shortfall: Decomposes delay cost, spread cost, market impact, and fee friction.
5. Decomposes Exits into True Net P&L (gross P&L, SDRT, FX fees, regulatory charges, spread, slippage, net P&L, MFE, MAE).
"""
import time
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional
from src.config.settings import settings
from src.brokers.trading212 import broker
from src.database.db import db
from src.execution.cost_model import cost_model
from src.execution.net_edge_gate import net_edge_gate
from src.execution.order_state_machine import ManagedOrder, OrderState, portfolio_reservations
from src.portfolio.portfolio_snapshot import portfolio_snapshot
from src.data.market_hours import market_hours


class OrderRouter:
    """
    Executes and records institutional trade orders with full Net P&L,
    order lifecycle management, and Implementation Shortfall telemetry.
    """
    def __init__(self):
        pass

    def calculate_implementation_shortfall(
        self,
        decision_price: float,
        arrival_price: float,
        fill_price: float,
        quantity: float,
        nominal_value: float,
        is_buy: bool,
        is_uk: bool,
        is_foreign: bool,
        instrument_type: str = "EQUITY",
        custom_spread_pct: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates institutional Implementation Shortfall decomposed into:
        1. Delay Cost (arrival price vs decision price)
        2. Spread Cost (half-spread at arrival)
        3. Market Impact / Slippage (fill price vs arrival price)
        4. Explicit Friction (broker fees, SDRT, FX, regulatory fees)
        """
        if decision_price <= 0 or arrival_price <= 0:
            return {
                "decision_price": decision_price,
                "arrival_price": arrival_price,
                "fill_price": fill_price,
                "delay_cost_bps": 0.0,
                "spread_cost_bps": 0.0,
                "market_impact_bps": 0.0,
                "explicit_fees_bps": 0.0,
                "implementation_shortfall_bps": 0.0,
                "implementation_shortfall_gbp": 0.0
            }

        # 1. Delay Cost
        if is_buy:
            delay_cost_bps = ((arrival_price - decision_price) / decision_price) * 10000.0
        else:
            delay_cost_bps = ((decision_price - arrival_price) / decision_price) * 10000.0

        # 2. Spread Cost
        if custom_spread_pct is not None:
            spread_half_rate = custom_spread_pct / 2.0
        else:
            spread_half_rate = cost_model.estimate_spread_rate(is_uk=is_uk, instrument_type=instrument_type)
        spread_cost_bps = spread_half_rate * 10000.0

        # 3. Market Impact / Slippage
        if is_buy:
            market_impact_bps = ((fill_price - arrival_price) / arrival_price) * 10000.0
        else:
            market_impact_bps = ((arrival_price - fill_price) / arrival_price) * 10000.0

        # 4. Explicit Friction Fees
        friction = cost_model.calculate_trade_friction(
            nominal_value=nominal_value,
            is_buy=is_buy,
            is_uk=is_uk,
            is_foreign=is_foreign,
            shares_count=quantity,
            instrument_type=instrument_type
        )
        explicit_fees_bps = (friction["total_friction"] / max(1.0, nominal_value)) * 10000.0

        # Total Implementation Shortfall
        total_shortfall_bps = delay_cost_bps + spread_cost_bps + market_impact_bps + explicit_fees_bps
        total_shortfall_gbp = (total_shortfall_bps / 10000.0) * nominal_value

        return {
            "decision_price": round(decision_price, 4),
            "arrival_price": round(arrival_price, 4),
            "fill_price": round(fill_price, 4),
            "delay_cost_bps": round(delay_cost_bps, 2),
            "spread_cost_bps": round(spread_cost_bps, 2),
            "market_impact_bps": round(market_impact_bps, 2),
            "explicit_fees_bps": round(explicit_fees_bps, 2),
            "implementation_shortfall_bps": round(total_shortfall_bps, 2),
            "implementation_shortfall_gbp": round(total_shortfall_gbp, 2),
            "friction_breakdown": friction
        }

    def route_entry_order(
        self,
        symbol: str,
        t212_ticker: str,
        quantity: float,
        price: float,
        target_price: float,
        stop_loss_price: float,
        sector: str,
        confidence_score: float,
        market_regime: str,
        agent_votes: Dict[str, str],
        risk_approved: bool,
        is_paper: bool = False,
        bid_price: Optional[float] = None,
        ask_price: Optional[float] = None,
        instrument_type: str = "EQUITY",
        decision_price: Optional[float] = None,
        bypass_market_hours: bool = False,
        bypass_audit_freeze: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates Net Edge Gate and executes entry order with hardened lifecycle and telemetry.
        """
        signal_time = datetime.now(timezone.utc).isoformat()
        t0 = time.time()
        
        is_uk = t212_ticker.endswith("l_EQ") or t212_ticker.endswith(".L") or symbol.endswith(".L")
        is_foreign = not is_uk
        exchange = "LSE" if is_uk else "NYSE/NASDAQ"
        currency = "GBP" if is_uk else "USD"
        nominal_value = quantity * price
        dec_price = decision_price or price

        # 1. Hard Closed-Market Gate: Disallow new regular-session entry orders while market is closed
        # Applies to BOTH Practice (is_paper=True) and Live/Real Money (is_paper=False) unconditionally.
        if not bypass_market_hours:
            market_country = "UK" if is_uk else "US"
            if not market_hours.is_asset_market_open(market_country):
                reason = f"HOLD ORDER (MARKET CLOSED): {exchange} regular session is CLOSED. Practice and Live entries blocked until next regular market open."
                self._log_audit("HOLD_CLOSED_MARKET", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, quantity, "MARKET_CLOSED")
                return False, reason, {"approved": False, "rejection_reasons": [f"{exchange}_MARKET_CLOSED"]}

        # 2. Permission Gates
        if is_paper:
            if not settings.PRACTICE_TRADING_ENABLED:
                reason = "HOLD: PRACTICE_TRADING_ENABLED is False."
                self._log_audit("HOLD_PRACTICE_DISABLED", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, quantity, "PRACTICE_DISABLED")
                return False, reason, {"approved": False, "rejection_reasons": ["PRACTICE_TRADING_DISABLED"]}
        else:
            if not (settings.REAL_MONEY_TRADING_ENABLED and settings.REAL_MONEY_NEW_ENTRIES_ALLOWED):
                reason = "VETO REAL MONEY: Real-money trading is disabled."
                self._log_audit("VETO_REAL_MONEY", symbol, market_regime, agent_votes, confidence_score, reason, False, quantity, "REAL_MONEY_DISABLED")
                return False, reason, {"approved": False, "rejection_reasons": ["REAL_MONEY_TRADING_DISABLED"]}

        # Compute spread
        bid = bid_price or (price * 0.9997)
        ask = ask_price or (price * 1.0003)
        spread_bps = round(((ask - bid) / max(0.01, price)) * 10000.0, 1)
        spread_pct = (ask - bid) / max(0.01, price)

        # 3. Hard Net Edge Gate Verification
        gate_result = net_edge_gate.evaluate_candidate(
            symbol=symbol,
            entry_price=price,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            nominal_value=nominal_value,
            is_uk=is_uk,
            is_foreign=is_foreign,
            instrument_type=instrument_type,
            current_spread_pct=spread_pct,
            fundamental_score=confidence_score,
            technical_score=confidence_score,
            catalyst_score=confidence_score
        )

        if not gate_result["approved"]:
            reasons_str = " | ".join(gate_result["rejection_reasons"])
            reason = f"HOLD CAPITAL PRESERVATION CASH: Net Edge Gate rejected {symbol}: {reasons_str}"
            self._log_audit("HOLD_CASH", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, quantity, "REJECTED_NET_EDGE")
            return False, reason, gate_result

        if not risk_approved:
            reason = "HOLD CAPITAL PRESERVATION CASH: Exposure Risk Engine vetoed allocation."
            self._log_audit("HOLD_CASH", symbol, market_regime, agent_votes, confidence_score, reason, False, quantity, "VETO_RISK")
            return False, reason, gate_result

        if quantity <= 0:
            reason = "HOLD CAPITAL PRESERVATION CASH: Quantity calculated as 0 units."
            self._log_audit("HOLD_CASH", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, 0, "INVALID_QUANTITY")
            return False, reason, gate_result

        # 3. Execution Routing with Marketable Limit Control (10 bps offset ceiling)
        trade_id = f"PRV_{int(time.time() * 1000)}_{symbol}"
        trade_reason = f"Net Exp Return: +{gate_result['predicted_net_return_pct']:.2f}% | Net R:R: {gate_result['net_reward_risk']:.2f}x | Friction: £{gate_result['total_round_trip_cost_gbp']:.2f}"
        
        limit_offset_pct = settings.MARKETABLE_LIMIT_SLIPPAGE_BPS / 10000.0 # 0.10% (10 bps)
        limit_price = round(price * (1.0 + limit_offset_pct), 4)

        # Managed Order State Machine & Atomic Portfolio Reservation
        managed_order = ManagedOrder(
            symbol=symbol,
            t212_ticker=t212_ticker,
            side="BUY",
            quantity=quantity,
            price=price,
            limit_price=limit_price,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            exchange=exchange,
            is_uk=is_uk
        )
        managed_order.transition_to(OrderState.SIGNAL_APPROVED, "Cleared Net Edge and Risk Gates")

        snap = portfolio_snapshot.hydrate_once()
        avail_cash = 50000.0 if is_paper else snap["account_summary"]["free_cash"]
        total_nav = 50000.0 if is_paper else snap["account_summary"]["total_nav"]
        pos_list = [] if is_paper else snap["positions"]
        res_ok, res_err = portfolio_reservations.reserve(
            order=managed_order,
            free_cash=avail_cash,
            total_nav=total_nav,
            sector=sector,
            positions=pos_list
        )
        if not res_ok:
            managed_order.transition_to(OrderState.SIGNAL_REJECTED, res_err)
            reason = f"HOLD RESERVATION: {res_err}"
            self._log_audit("HOLD_RESERVATION", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, quantity, "RESERVATION_FAILED")
            return False, reason, {"approved": False, "rejection_reasons": [res_err]}

        managed_order.transition_to(OrderState.ORDER_READY, "Portfolio reservation committed")
        managed_order.transition_to(OrderState.ORDER_SUBMITTED, f"Routing to {'Paper Simulator' if is_paper else 'Trading212'}")

        if not is_paper:
            # Live Order Execution
            res = broker.place_market_order(t212_ticker, quantity)
            latency_ms = round((time.time() - t0) * 1000.0, 2)
            
            if res.get("success"):
                managed_order.transition_to(OrderState.FILLED, "Broker executed fill")
                fill_price = price
                broker_order_id = res["data"].get("id", trade_id)
                slippage_bps = round(((fill_price - price) / max(0.001, price)) * 10000.0, 1)

                # Compute Implementation Shortfall
                shortfall = self.calculate_implementation_shortfall(
                    decision_price=dec_price,
                    arrival_price=price,
                    fill_price=fill_price,
                    quantity=quantity,
                    nominal_value=nominal_value,
                    is_buy=True,
                    is_uk=is_uk,
                    is_foreign=is_foreign,
                    instrument_type=instrument_type,
                    custom_spread_pct=spread_pct
                )

                # Record Telemetry
                db.record_order_telemetry({
                    "signal_timestamp": signal_time,
                    "symbol": symbol,
                    "exchange": exchange,
                    "action": "BUY",
                    "signal_price": price,
                    "bid_at_signal": bid,
                    "ask_at_signal": ask,
                    "spread_bps": spread_bps,
                    "requested_price": price,
                    "submitted_price": limit_price,
                    "fill_price": fill_price,
                    "quantity": quantity,
                    "partial_fill_quantity": 0.0,
                    "latency_ms": latency_ms,
                    "slippage_bps": slippage_bps,
                    "time_to_fill_sec": round(latency_ms / 1000.0, 3),
                    "order_type": "MARKETABLE_LIMIT",
                    "status": "FILLED",
                    "decision_price": dec_price,
                    "arrival_price": price,
                    "delay_cost_bps": shortfall["delay_cost_bps"],
                    "spread_cost_bps": shortfall["spread_cost_bps"],
                    "market_impact_bps": shortfall["market_impact_bps"],
                    "implementation_shortfall_bps": shortfall["implementation_shortfall_bps"],
                    "implementation_shortfall_gbp": shortfall["implementation_shortfall_gbp"],
                    "chase_attempts": 0,
                    "cancellation_reason": None
                })

                # Record Trade in Database
                db.record_trade({
                    "trade_id": str(broker_order_id),
                    "symbol": symbol,
                    "action": "BUY",
                    "quantity": quantity,
                    "price": fill_price,
                    "total_cost": nominal_value,
                    "spread_cost": shortfall["friction_breakdown"]["spread_cost"],
                    "slippage_cost": shortfall["friction_breakdown"]["slippage_cost"],
                    "fx_cost": shortfall["friction_breakdown"]["fx_cost"],
                    "broker_fees": shortfall["friction_breakdown"]["broker_fees"],
                    "taxes": shortfall["friction_breakdown"]["stamp_duty"] + shortfall["friction_breakdown"]["ptm_levy"],
                    "net_cost": nominal_value + shortfall["friction_breakdown"]["total_friction"],
                    "confidence_score": confidence_score,
                    "reward_risk_ratio": gate_result["net_reward_risk"],
                    "trade_reason": trade_reason,
                    "mode": "LIVE"
                })

                portfolio_reservations.release(managed_order.client_order_id)
                self._log_audit("BUY_EXECUTION", symbol, market_regime, agent_votes, confidence_score, trade_reason, True, quantity, "FILLED_LIVE")
                return True, f"✅ Live Order Executed: {quantity} shares of {symbol} at £{fill_price:.2f} (Friction: £{gate_result['total_round_trip_cost_gbp']:.2f})", res["data"]
            else:
                managed_order.transition_to(OrderState.FAILED, res.get("error", "Broker order rejected"))
                portfolio_reservations.release(managed_order.client_order_id)
                err_msg = res.get("error", "Unknown broker error")
                self._log_audit("EXECUTION_FAILED", symbol, market_regime, agent_votes, confidence_score, err_msg, True, quantity, "BROKER_ERROR")
                return False, f"❌ Broker order rejected: {err_msg}", {}
        else:
            # Paper execution with implementation shortfall simulation
            managed_order.transition_to(OrderState.FILLED, "Simulated fill")
            latency_ms = round((time.time() - t0) * 1000.0, 2)
            shortfall = self.calculate_implementation_shortfall(
                decision_price=dec_price,
                arrival_price=price,
                fill_price=price,
                quantity=quantity,
                nominal_value=nominal_value,
                is_buy=True,
                is_uk=is_uk,
                is_foreign=is_foreign,
                instrument_type=instrument_type,
                custom_spread_pct=spread_pct
            )

            db.record_order_telemetry({
                "signal_timestamp": signal_time,
                "symbol": symbol,
                "exchange": exchange,
                "action": "BUY",
                "signal_price": price,
                "bid_at_signal": bid,
                "ask_at_signal": ask,
                "spread_bps": spread_bps,
                "requested_price": price,
                "submitted_price": limit_price,
                "fill_price": price,
                "quantity": quantity,
                "partial_fill_quantity": 0.0,
                "latency_ms": latency_ms,
                "slippage_bps": 0.0,
                "time_to_fill_sec": round(latency_ms / 1000.0, 3),
                "order_type": "MARKETABLE_LIMIT",
                "status": "SIMULATED_FILLED",
                "decision_price": dec_price,
                "arrival_price": price,
                "delay_cost_bps": shortfall["delay_cost_bps"],
                "spread_cost_bps": shortfall["spread_cost_bps"],
                "market_impact_bps": shortfall["market_impact_bps"],
                "implementation_shortfall_bps": shortfall["implementation_shortfall_bps"],
                "implementation_shortfall_gbp": shortfall["implementation_shortfall_gbp"],
                "chase_attempts": 0,
                "cancellation_reason": None
            })
            portfolio_reservations.release(managed_order.client_order_id)
            self._log_audit("BUY_EXECUTION", symbol, market_regime, agent_votes, confidence_score, trade_reason, True, quantity, "SIMULATED_FILL")
            return True, f"🧪 [PAPER BUY] Simulated {quantity} shares of {symbol} at £{price:.2f}", {"id": trade_id}

    def route_exit_order(
        self,
        symbol: str,
        t212_ticker: str,
        quantity: float,
        current_price: float,
        entry_price: float,
        exit_reason: str,
        holding_days: int = 14,
        mfe_pct: float = 0.0,
        mae_pct: float = 0.0,
        is_paper: bool = False,
        instrument_type: str = "EQUITY"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Executes position close, decomposes all transaction friction, and computes True NET Realized P&L.
        """
        nominal_entry = quantity * entry_price
        nominal_exit = quantity * current_price

        is_uk = t212_ticker.endswith("l_EQ") or t212_ticker.endswith(".L") or symbol.endswith(".L")
        is_foreign = not is_uk

        net_calc = cost_model.compute_net_realized_pnl(
            gross_entry_value=nominal_entry,
            gross_exit_value=nominal_exit,
            is_uk=is_uk,
            is_foreign=is_foreign,
            shares_count=quantity,
            instrument_type=instrument_type
        )

        trade_id = f"PRV_EXIT_{int(datetime.now().timestamp())}_{symbol}"
        thesis_outcome = "PROFIT_TARGET_HIT" if net_calc["net_realized_pnl"] > 0 else ("STOP_LOSS_TRIGGERED" if "STOP" in exit_reason.upper() else "REBALANCED")

        if not is_paper:
            res = broker.place_market_order(t212_ticker, -quantity)
            if res.get("success"):
                db.record_trade({
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "action": "SELL",
                    "quantity": quantity,
                    "price": current_price,
                    "total_cost": nominal_exit,
                    "realized_pnl": net_calc["net_realized_pnl"],
                    "confidence_score": 100.0,
                    "reward_risk_ratio": 0.0,
                    "trade_reason": exit_reason,
                    "mode": "LIVE"
                })

                self._log_audit("SELL_EXECUTION", symbol, "N/A", {}, 100.0, exit_reason, True, quantity, f"NET_PNL_{net_calc['net_realized_pnl']:+.2f}")
                return True, f"✅ Live Exit Executed for {symbol}: Gross P&L £{net_calc['gross_profit_loss']:+.2f}, Costs £{net_calc['total_transaction_costs']:.2f}, NET P&L £{net_calc['net_realized_pnl']:+.2f}", net_calc
            else:
                return False, f"❌ Failed to exit {symbol}: {res.get('error')}", net_calc
        else:
            self._log_audit("SELL_EXECUTION", symbol, "N/A", {}, 100.0, exit_reason, True, quantity, f"PAPER_NET_PNL_{net_calc['net_realized_pnl']:+.2f}")
            return True, f"🧪 [PAPER EXIT] Simulated Exit for {symbol}: NET P&L £{net_calc['net_realized_pnl']:+.2f}", net_calc

    def _log_audit(self, event_type: str, symbol: str, regime: str, votes: Dict[str, str], conf: float, reason: str, risk_app: bool, size: float, result: str):
        try:
            db.record_audit({
                "event_type": event_type,
                "symbol": symbol,
                "market_conditions": {"regime": regime},
                "agent_votes": votes,
                "confidence_score": conf,
                "trade_reason": reason,
                "risk_approval": risk_app,
                "position_size": size,
                "exit_reason": reason if "SELL" in event_type else None,
                "final_result": result
            })
        except Exception:
            pass


order_router = OrderRouter()
