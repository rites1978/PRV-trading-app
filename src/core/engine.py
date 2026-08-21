import time
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.config.settings import settings
from src.database.db import db
from src.brokers.trading212 import broker
from src.data.universe import universe_manager
from src.data.market_data import market_data
from src.portfolio.capital_manager import capital_manager
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
        Execute one complete quantitative trading and portfolio rebalance cycle.
        """
        # 1. Fetch Live Account Metrics
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
        vault_balance = capital_state["profit_vault_balance"]
        exposure_pct = capital_state["capital_utilization_pct"]

        # 4. Market Regime Assessment (using S&P benchmark snapshot)
        sp500_snapshot = market_data.get_market_snapshot("^GSPC")
        sp500_trend_score = 80.0 if (sp500_snapshot.get("success") and sp500_snapshot["indicators"]["sma_20"] > sp500_snapshot["indicators"]["sma_50"]) else 45.0
        
        # Calculate dynamic deployment capacity
        market_regime, target_deployment_pct = capital_manager.determine_market_regime(
            market_breadth_score=70.0,
            sp500_trend_score=sp500_trend_score
        )
        
        remaining_allowance, _ = capital_manager.calculate_deployment_allowance(
            core_capital, active_capital, market_regime
        )

        # 5. Monitor and Manage Open Positions (Stop-Loss & Take-Profit)
        open_positions = broker.get_open_positions()
        holding_map = {p.get("ticker"): p for p in open_positions}
        closed_trades = []

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
                    # Automatically lock realized gain in Profit Vault
                    vault_res = capital_manager.process_realized_trade(f"EXIT_{t212_ticker}", t212_ticker, realized_pnl)
                    self.notifier.notify_trade("SELL", t212_ticker, qty, cur_price, f"{exit_msg} | Vaulted: £{realized_pnl:+.2f}", is_paper=self.paper_mode)
                    closed_trades.append(t212_ticker)

        # 6. Scan Institutional Universe for High-Edge Opportunities
        universe = universe_manager.get_all()
        scanned_candidates = []
        executed_trades = []

        for item in universe:
            symbol = item["symbol"]
            yf_ticker = item["yf_ticker"]
            t212_ticker = item["t212_ticker"]
            sector = item["sector"]
            is_foreign = (item["currency"] != "GBP")
            is_uk = (item["country"] == "UK")
            is_uk_pence = item.get("is_uk_pence", False)

            # Skip if already holding
            if t212_ticker in holding_map and t212_ticker not in closed_trades:
                continue

            snapshot = market_data.get_market_snapshot(yf_ticker, is_uk_pence=is_uk_pence)
            if not snapshot.get("success"):
                continue

            price = snapshot["current_price"]
            
            # Target 3:1 R:R Price Targets
            stop_loss_price = price * (1.0 - settings.DEFAULT_STOP_LOSS_PCT)
            target_price = price * (1.0 + settings.DEFAULT_TAKE_PROFIT_PCT)
            
            # Sizing calculation
            units = risk_engine.calculate_position_units(price, core_capital, available_cash, remaining_allowance)
            nominal_cost = units * price
            
            # Cost Model Evaluation
            cost_eval_ok, cost_eval = cost_model.evaluate_net_edge(
                entry_price=price,
                target_price=target_price,
                stop_loss_price=stop_loss_price,
                nominal_value=nominal_cost,
                is_foreign_currency=is_foreign,
                is_uk=is_uk
            )
            
            friction_pct = cost_eval.get("friction_breakdown", {}).get("friction_pct", 0.10)

            # 8-Factor Quantitative AI Confidence Score
            confidence_score, factor_breakdown = ai_scoring.compute_composite_confidence(
                symbol=symbol,
                snapshot=snapshot,
                market_regime=market_regime,
                portfolio_exposure_pct=exposure_pct,
                cost_friction_pct=friction_pct
            )

            # Risk Engine Pre-Approval
            risk_approved, risk_reason = risk_engine.validate_new_order(
                symbol=symbol,
                sector=sector,
                order_cost=nominal_cost,
                core_capital=core_capital,
                available_cash=available_cash,
                current_positions=open_positions,
                remaining_regime_allowance=remaining_allowance
            )

            # Boardroom Deliberation & Voting
            approved_by_boardroom, decision_data = boardroom.convene_boardroom(
                symbol=symbol,
                factors=factor_breakdown,
                composite_confidence=confidence_score,
                market_regime=market_regime,
                risk_approved=risk_approved,
                cost_approved=cost_eval_ok
            )

            candidate_record = {
                "symbol": symbol,
                "t212_ticker": t212_ticker,
                "confidence": confidence_score,
                "reward_risk": cost_eval.get("net_reward_risk", 0.0),
                "price": price,
                "units": units,
                "cost": nominal_cost,
                "approved": approved_by_boardroom
            }
            scanned_candidates.append(candidate_record)

            # Route Order if Approved
            if approved_by_boardroom and units > 0:
                agent_votes = {
                    "trend": decision_data["trend_agent_vote"],
                    "momentum": decision_data["momentum_agent_vote"],
                    "volatility": decision_data["volatility_agent_vote"],
                    "liquidity": decision_data["liquidity_agent_vote"],
                    "risk": decision_data["risk_agent_vote"]
                }
                
                success, route_msg, trade_res = order_router.route_entry_order(
                    symbol=symbol,
                    t212_ticker=t212_ticker,
                    quantity=units,
                    price=price,
                    sector=sector,
                    confidence_score=confidence_score,
                    reward_risk_ratio=cost_eval.get("net_reward_risk", 3.0),
                    market_regime=market_regime,
                    agent_votes=agent_votes,
                    risk_approved=risk_approved,
                    cost_evaluation=cost_eval,
                    is_paper=self.paper_mode
                )
                
                if success:
                    executed_trades.append(symbol)
                    self.notifier.notify_trade("BUY", symbol, units, price, route_msg, is_paper=self.paper_mode)
                    available_cash -= nominal_cost
                    remaining_allowance -= nominal_cost

        return {
            "success": True,
            "capital_state": capital_state,
            "market_regime": market_regime,
            "target_deployment_pct": target_deployment_pct,
            "scanned_count": len(universe),
            "candidates": scanned_candidates,
            "executed_trades": executed_trades,
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
