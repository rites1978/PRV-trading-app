import time
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd

from src.config.settings import settings
from src.database.db import db
from src.brokers.trading212 import broker
from src.data.universe import universe_manager
from src.data.market_data import market_data
from src.portfolio.capital_manager import capital_manager
from src.portfolio.portfolio_constructor import portfolio_constructor
from src.portfolio.dust_cleaner import dust_cleaner
from src.risk.risk_engine import risk_engine
from src.execution.cost_model import cost_model
from src.ai.scoring_engine import ai_scoring
from src.agents.boardroom import boardroom
from src.execution.order_router import order_router
from telegram_notifier import TelegramNotifier

class PRVQuantEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(PRVQuantEngine, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.is_running: bool = False
        self.paper_mode: bool = (settings.TRADING_ENV == "demo")
        self.scan_interval: int = settings.SCAN_INTERVAL_SECONDS
        self.notifier = TelegramNotifier()
        
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._initialized = True

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self.notifier.notify_alert(
            "PRV QUANT ENGINE STARTED",
            f"Autonomous execution engine active in {'PAPER' if self.paper_mode else 'LIVE'} mode."
        )
        self._thread = threading.Thread(target=self._execution_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()
        self.notifier.notify_alert("PRV QUANT ENGINE STOPPED", "Autonomous trading halted.")

    def run_cycle(self) -> Dict[str, Any]:
        """
        Execute one complete quantitative trading and capital deployment cycle
        using ATR-adjusted sizing, correlation awareness, and exposure-based risk controls.
        """
        # 1. Fetch Live Account Summary
        account = broker.get_account_summary()
        if not account.get("success"):
            return {"success": False, "error": account.get("error")}

        total_nav = account["total_value"]
        available_cash = account["available_cash"]
        invested = account["invested"]

        # 2. Risk Circuit Breaker Check (5% daily drawdown limit)
        safe, circuit_msg = risk_engine.check_circuit_breaker(total_nav)
        if not safe:
            self.notifier.notify_alert("CIRCUIT BREAKER TRIGGERED", circuit_msg)
            return {"success": False, "circuit_breaker": True, "message": circuit_msg}

        # 3. Capital State Assessment
        capital_state = capital_manager.get_capital_state(total_nav, invested, available_cash)
        core_capital = capital_state["core_capital"]
        active_capital = capital_state["active_capital"]
        exposure_pct = capital_state["capital_utilization_pct"]

        # 4. Market Regime Assessment
        sp500_snapshot = market_data.get_market_snapshot("^GSPC")
        sp500_trend_score = 80.0 if (sp500_snapshot.get("success") and sp500_snapshot["indicators"]["sma_20"] > sp500_snapshot["indicators"]["sma_50"]) else 50.0
        
        market_regime, target_deployment_pct = capital_manager.determine_market_regime(
            market_breadth_score=75.0,
            sp500_trend_score=sp500_trend_score
        )
        
        remaining_allowance, _ = capital_manager.calculate_deployment_allowance(
            core_capital, active_capital, market_regime
        )

        # 5. Monitor and Manage Open Positions (Stop-Loss & Take-Profit)
        open_positions = broker.get_open_positions()
        holding_map = {p.get("ticker"): p for p in open_positions}
        closed_trades = []
        active_positions_dfs = {}

        for pos in open_positions:
            t212_ticker = pos.get("ticker")
            qty = float(pos.get("quantity", 0))
            avg_price = float(pos.get("averagePrice", 0))
            cur_price = float(pos.get("currentPrice", 0))
            
            if avg_price <= 0 or qty <= 0:
                continue

            pnl_pct = (cur_price - avg_price) / avg_price
            
            # Stop-Loss Check (-2.5%)
            if pnl_pct <= -settings.DEFAULT_STOP_LOSS_PCT:
                exit_msg = f"Stop Loss triggered: {pnl_pct * 100:.2f}% (Limit: -{settings.DEFAULT_STOP_LOSS_PCT * 100:.1f}%)"
                success, msg, realized_pnl = order_router.route_exit_order(
                    symbol=t212_ticker,
                    t212_ticker=t212_ticker,
                    quantity=qty,
                    current_price=cur_price,
                    entry_price=avg_price,
                    exit_reason=exit_msg,
                    is_paper=self.paper_mode
                )
                if success:
                    capital_manager.process_realized_trade(f"EXIT_{t212_ticker}", t212_ticker, realized_pnl)
                    self.notifier.notify_trade("SELL", t212_ticker, qty, cur_price, exit_msg, is_paper=self.paper_mode)
                    closed_trades.append(t212_ticker)

            # Take-Profit Check (+7.5%)
            elif pnl_pct >= settings.DEFAULT_TAKE_PROFIT_PCT:
                exit_msg = f"Take Profit triggered: {pnl_pct * 100:+.2f}% (Target: +{settings.DEFAULT_TAKE_PROFIT_PCT * 100:.1f}%)"
                success, msg, realized_pnl = order_router.route_exit_order(
                    symbol=t212_ticker,
                    t212_ticker=t212_ticker,
                    quantity=qty,
                    current_price=cur_price,
                    entry_price=avg_price,
                    exit_reason=exit_msg,
                    is_paper=self.paper_mode
                )
                if success:
                    capital_manager.process_realized_trade(f"EXIT_{t212_ticker}", t212_ticker, realized_pnl)
                    self.notifier.notify_trade("SELL", t212_ticker, qty, cur_price, f"{exit_msg} | Vaulted: £{realized_pnl:+.2f}", is_paper=self.paper_mode)
                    closed_trades.append(t212_ticker)

        # 6. Quantitative Universe Scanning & ATR-Adjusted Portfolio Construction
        universe = universe_manager.get_all()
        candidates = []

        for item in universe:
            symbol = item["symbol"]
            yf_ticker = item["yf_ticker"]
            t212_ticker = item["t212_ticker"]
            sector = item["sector"]
            is_foreign = (item["currency"] != "GBP")
            is_uk = (item["country"] == "UK")
            is_uk_pence = item.get("is_uk_pence", False)

            # Existing holding valuation
            existing_pos = holding_map.get(t212_ticker)
            current_holding_val = 0.0
            if existing_pos and t212_ticker not in closed_trades:
                current_holding_val = float(existing_pos.get("quantity", 0)) * float(existing_pos.get("currentPrice", 0))

            snapshot = market_data.get_market_snapshot(yf_ticker, is_uk_pence=is_uk_pence)
            if not snapshot.get("success"):
                continue

            price = snapshot["current_price"]
            atr = snapshot["indicators"]["atr"]
            df_asset = snapshot["dataframe"]

            # Institutional Sizing: ATR-Adjusted + Volatility Scaled + Correlation Aware
            units, nominal_cost, sizing_meta = portfolio_constructor.calculate_optimal_position_size(
                symbol=symbol,
                price=price,
                atr=atr,
                df=df_asset,
                core_capital=core_capital,
                available_cash=available_cash,
                remaining_capacity=remaining_allowance,
                current_holding_val=current_holding_val,
                active_positions_dfs=active_positions_dfs
            )

            if units <= 0 or nominal_cost < 50.0:
                continue

            stop_loss_price = price * (1.0 - settings.DEFAULT_STOP_LOSS_PCT)
            target_price = price * (1.0 + settings.DEFAULT_TAKE_PROFIT_PCT)
            
            # Spread-Aware Cost Model Evaluation
            cost_eval_ok, cost_eval = cost_model.evaluate_net_edge(
                entry_price=price,
                target_price=target_price,
                stop_loss_price=stop_loss_price,
                nominal_value=nominal_cost,
                is_foreign_currency=is_foreign,
                is_uk=is_uk
            )
            
            friction_pct = cost_eval.get("friction_breakdown", {}).get("friction_pct", 0.10)

            # 8-Factor Quantitative Confidence Score
            confidence_score, factor_breakdown = ai_scoring.compute_composite_confidence(
                symbol=symbol,
                snapshot=snapshot,
                market_regime=market_regime,
                portfolio_exposure_pct=exposure_pct,
                cost_friction_pct=friction_pct
            )

            # Exposure-Based Risk Validation (No ticker count limit)
            risk_approved, risk_reason = risk_engine.validate_exposure_order(
                symbol=symbol,
                t212_ticker=t212_ticker,
                sector=sector,
                order_cost=nominal_cost,
                core_capital=core_capital,
                available_cash=available_cash,
                current_positions=open_positions,
                remaining_regime_allowance=remaining_allowance
            )

            # Boardroom Quorum Deliberation
            approved_by_boardroom, decision_data = boardroom.convene_boardroom(
                symbol=symbol,
                factors=factor_breakdown,
                composite_confidence=confidence_score,
                market_regime=market_regime,
                risk_approved=risk_approved,
                cost_approved=cost_eval_ok
            )

            candidates.append({
                "symbol": symbol,
                "t212_ticker": t212_ticker,
                "sector": sector,
                "confidence": confidence_score,
                "reward_risk": cost_eval.get("net_reward_risk", 3.0),
                "price": price,
                "units": units,
                "cost": nominal_cost,
                "approved": approved_by_boardroom,
                "decision_data": decision_data,
                "cost_eval": cost_eval,
                "risk_approved": risk_approved,
                "sizing_meta": sizing_meta
            })

        # 7. Sort by highest confidence and systematically deploy capital
        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        executed_trades = []

        for cand in candidates:
            if remaining_allowance <= 500.0 or available_cash <= 2500.0:
                break

            if cand["approved"] and cand["units"] > 0:
                agent_votes = {
                    "trend": cand["decision_data"]["trend_agent_vote"],
                    "momentum": cand["decision_data"]["momentum_agent_vote"],
                    "volatility": cand["decision_data"]["volatility_agent_vote"],
                    "liquidity": cand["decision_data"]["liquidity_agent_vote"],
                    "risk": cand["decision_data"]["risk_agent_vote"]
                }
                
                success, route_msg, trade_res = order_router.route_entry_order(
                    symbol=cand["symbol"],
                    t212_ticker=cand["t212_ticker"],
                    quantity=cand["units"],
                    price=cand["price"],
                    sector=cand["sector"],
                    confidence_score=cand["confidence"],
                    reward_risk_ratio=cand["reward_risk"],
                    market_regime=market_regime,
                    agent_votes=agent_votes,
                    risk_approved=cand["risk_approved"],
                    cost_evaluation=cand["cost_eval"],
                    is_paper=self.paper_mode
                )
                
                if success:
                    executed_trades.append(cand["symbol"])
                    self.notifier.notify_trade("BUY", cand["symbol"], cand["units"], cand["price"], route_msg, is_paper=self.paper_mode)
                    available_cash -= cand["cost"]
                    remaining_allowance -= cand["cost"]

        # Generate Detailed Idle Cash Accounting
        idle_cash_audit = capital_manager.generate_idle_cash_audit(
            core_capital=core_capital,
            available_cash=available_cash,
            active_capital=active_capital,
            market_regime=market_regime,
            rejected_candidates=candidates
        )

        return {
            "success": True,
            "capital_state": capital_state,
            "market_regime": market_regime,
            "target_deployment_pct": target_deployment_pct,
            "scanned_count": len(universe),
            "executed_trades": executed_trades,
            "candidates_count": len(candidates),
            "idle_cash_audit": idle_cash_audit,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def _execution_loop(self):
        while not self._stop_event.is_set():
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[QuantEngine Loop Error] {e}")
                
            for _ in range(self.scan_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

quant_engine = PRVQuantEngine()
