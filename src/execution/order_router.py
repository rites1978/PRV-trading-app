from typing import Dict, Any, Tuple
from datetime import datetime
from src.config.settings import settings
from src.brokers.trading212 import broker
from src.database.db import db
from src.monitoring.evidence_recorder import evidence_recorder

class OrderRouter:
    """
    PRV Capital Strict Execution Order Router:
    Enforces all Trade Approval Rules before routing orders to broker.
    Logs every decision and outcome to Audit Trail.
    """
    def __init__(self):
        pass

    def route_entry_order(
        self,
        symbol: str,
        t212_ticker: str,
        quantity: float,
        price: float,
        sector: str,
        confidence_score: float,
        reward_risk_ratio: float,
        market_regime: str,
        agent_votes: Dict[str, str],
        risk_approved: bool,
        cost_evaluation: Dict[str, Any],
        is_paper: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates all constraints and executes order.
        """
        total_cost = quantity * price
        
        # 1. Verification of Mandatory Pre-Conditions
        if confidence_score < settings.MIN_CONFIDENCE_THRESHOLD:
            reason = f"HOLD CASH: Confidence score {confidence_score} below mandatory threshold ({settings.MIN_CONFIDENCE_THRESHOLD})."
            self._log_audit("HOLD_CASH", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, quantity, "REJECTED_CONFIDENCE")
            return False, reason, {}

        if not risk_approved:
            reason = "HOLD CASH: Risk Engine vetoed execution."
            self._log_audit("HOLD_CASH", symbol, market_regime, agent_votes, confidence_score, reason, False, quantity, "VETO_RISK")
            return False, reason, {}

        min_net_rr = getattr(settings, "MIN_NET_REWARD_RISK_RATIO", 2.50)
        if reward_risk_ratio < min_net_rr:
            reason = f"HOLD CASH: Net Reward/Risk ratio {reward_risk_ratio:.2f} < {min_net_rr:.2f}."
            self._log_audit("HOLD_CASH", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, quantity, "REJECTED_RR")
            return False, reason, {}

        if not cost_evaluation.get("approved", False):
            reason = f"HOLD CASH: Cost evaluation rejected: {cost_evaluation.get('reason')}."
            self._log_audit("HOLD_CASH", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, quantity, "REJECTED_COST")
            return False, reason, {}

        if quantity <= 0:
            reason = "HOLD CASH: Calculated unit quantity is 0."
            self._log_audit("HOLD_CASH", symbol, market_regime, agent_votes, confidence_score, reason, risk_approved, 0, "INVALID_QUANTITY")
            return False, reason, {}

        # 2. Execution Routing
        trade_id = f"PRV_{int(datetime.now().timestamp())}_{symbol}"
        trade_reason = f"Confidence: {confidence_score}% | R:R: {reward_risk_ratio:.2f} | Regime: {market_regime}"
        
        friction = cost_evaluation.get("friction_breakdown", {})
        spread_cost = friction.get("spread_cost", 0.0)
        slippage_cost = friction.get("slippage_cost", 0.0)
        fx_cost = friction.get("fx_cost", 0.0)

        if not is_paper:
            res = broker.place_market_order(t212_ticker, quantity)
            if res.get("success"):
                broker_order_id = res["data"].get("id", trade_id)
                db.record_trade({
                    "trade_id": str(broker_order_id),
                    "symbol": symbol,
                    "action": "BUY",
                    "quantity": quantity,
                    "price": price,
                    "total_cost": total_cost,
                    "spread_cost": spread_cost,
                    "slippage_cost": slippage_cost,
                    "fx_cost": fx_cost,
                    "net_cost": total_cost + spread_cost + slippage_cost + fx_cost,
                    "confidence_score": confidence_score,
                    "reward_risk_ratio": reward_risk_ratio,
                    "trade_reason": trade_reason,
                    "mode": "LIVE"
                })
                
                evidence_recorder.record_trade_ledger({
                    "trade_id": str(broker_order_id),
                    "symbol": symbol,
                    "t212_ticker": t212_ticker,
                    "action": "BUY",
                    "quantity": quantity,
                    "entry_price": price,
                    "position_cost": total_cost,
                    "stop_loss_price": price * (1.0 - settings.DEFAULT_STOP_LOSS_PCT),
                    "take_profit_price": price * (1.0 + settings.DEFAULT_TAKE_PROFIT_PCT),
                    "spread_cost": spread_cost,
                    "slippage_cost": slippage_cost,
                    "fx_cost": fx_cost,
                    "total_friction": spread_cost + slippage_cost + fx_cost,
                    "mode": "LIVE"
                })
                
                self._log_audit("BUY_EXECUTION", symbol, market_regime, agent_votes, confidence_score, trade_reason, True, quantity, "FILLED_LIVE")
                return True, f"✅ Live Buy Order Executed: {quantity} shares of {symbol} at £{price:.2f}", res["data"]
            else:
                err_msg = res.get("error", "Unknown broker error")
                self._log_audit("EXECUTION_FAILED", symbol, market_regime, agent_votes, confidence_score, err_msg, True, quantity, "BROKER_ERROR")
                return False, f"❌ Broker order rejected: {err_msg}", {}
        else:
            # Paper Mode Execution
            db.record_trade({
                "trade_id": trade_id,
                "symbol": symbol,
                "action": "BUY",
                "quantity": quantity,
                "price": price,
                "total_cost": total_cost,
                "spread_cost": spread_cost,
                "slippage_cost": slippage_cost,
                "fx_cost": fx_cost,
                "net_cost": total_cost + spread_cost + slippage_cost + fx_cost,
                "confidence_score": confidence_score,
                "reward_risk_ratio": reward_risk_ratio,
                "trade_reason": trade_reason,
                "mode": "PAPER"
            })
            evidence_recorder.record_trade_ledger({
                "trade_id": trade_id,
                "symbol": symbol,
                "t212_ticker": t212_ticker,
                "action": "BUY",
                "quantity": quantity,
                "entry_price": price,
                "position_cost": total_cost,
                "stop_loss_price": price * (1.0 - settings.DEFAULT_STOP_LOSS_PCT),
                "take_profit_price": price * (1.0 + settings.DEFAULT_TAKE_PROFIT_PCT),
                "spread_cost": spread_cost,
                "slippage_cost": slippage_cost,
                "fx_cost": fx_cost,
                "total_friction": spread_cost + slippage_cost + fx_cost,
                "mode": "PAPER"
            })
            self._log_audit("BUY_EXECUTION", symbol, market_regime, agent_votes, confidence_score, trade_reason, True, quantity, "FILLED_PAPER")
            return True, f"🧪 [PAPER BUY] Simulated {quantity} shares of {symbol} at £{price:.2f}", {"id": trade_id}

    def route_exit_order(
        self,
        symbol: str,
        t212_ticker: str,
        quantity: float,
        current_price: float,
        entry_price: float,
        exit_reason: str,
        is_paper: bool = False
    ) -> Tuple[bool, str, float]:
        """
        Executes position close (Stop-Loss or Take-Profit) and returns realized PnL.
        """
        nominal_exit = quantity * current_price
        nominal_entry = quantity * entry_price
        realized_pnl = nominal_exit - nominal_entry
        trade_id = f"PRV_EXIT_{int(datetime.now().timestamp())}_{symbol}"

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
                    "realized_pnl": realized_pnl,
                    "confidence_score": 100.0,
                    "reward_risk_ratio": 0.0,
                    "trade_reason": exit_reason,
                    "mode": "LIVE"
                })
                evidence_recorder.record_trade_ledger({
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "t212_ticker": t212_ticker,
                    "action": "SELL",
                    "quantity": quantity,
                    "entry_price": entry_price,
                    "exit_price": current_price,
                    "position_cost": nominal_entry,
                    "gross_pnl": realized_pnl,
                    "net_pnl": realized_pnl,
                    "net_return_pct": (realized_pnl / max(1.0, nominal_entry)) * 100.0,
                    "exit_reason": exit_reason,
                    "mode": "LIVE"
                })
                self._log_audit("SELL_EXECUTION", symbol, "N/A", {}, 100.0, exit_reason, True, quantity, f"FILLED_LIVE_PNL_{realized_pnl:+.2f}")
                return True, f"✅ Live Exit Executed for {symbol}: {exit_reason} (Realized PnL: £{realized_pnl:+.2f})", realized_pnl
            else:
                return False, f"❌ Failed to exit {symbol}: {res.get('error')}", 0.0
        else:
            db.record_trade({
                "trade_id": trade_id,
                "symbol": symbol,
                "action": "SELL",
                "quantity": quantity,
                "price": current_price,
                "total_cost": nominal_exit,
                "realized_pnl": realized_pnl,
                "confidence_score": 100.0,
                "reward_risk_ratio": 0.0,
                "trade_reason": exit_reason,
                "mode": "PAPER"
            })
            evidence_recorder.record_trade_ledger({
                "trade_id": trade_id,
                "symbol": symbol,
                "t212_ticker": t212_ticker,
                "action": "SELL",
                "quantity": quantity,
                "entry_price": entry_price,
                "exit_price": current_price,
                "position_cost": nominal_entry,
                "gross_pnl": realized_pnl,
                "net_pnl": realized_pnl,
                "net_return_pct": (realized_pnl / max(1.0, nominal_entry)) * 100.0,
                "exit_reason": exit_reason,
                "mode": "PAPER"
            })
            self._log_audit("SELL_EXECUTION", symbol, "N/A", {}, 100.0, exit_reason, True, quantity, f"FILLED_PAPER_PNL_{realized_pnl:+.2f}")
            return True, f"🧪 [PAPER EXIT] Simulated Exit for {symbol}: {exit_reason} (PnL: £{realized_pnl:+.2f})", realized_pnl

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
