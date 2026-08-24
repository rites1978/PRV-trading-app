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
from src.risk.event_risk import event_risk_engine
from src.research.alpha_engine import alpha_engine
from src.ai.scoring_engine import ai_scoring
from src.execution.cost_model import cost_model
from src.agents.boardroom import boardroom
from src.execution.order_router import order_router
from src.data.market_hours import market_hours
from src.monitoring.evidence_recorder import evidence_recorder
from src.compliance.integrity_guard import integrity_guard
from src.analytics.attribution_service import attribution_service
from src.analytics.trajectory_service import trajectory_service
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
        
        # Position Tracking State (Peak Price & High Watermark)
        self.position_peaks: Dict[str, float] = {}
        
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
        Execute Phase 6 Return-Optimized quantitative cycle:
        1. Technical Engine generates entry signal (Buy/No-Buy).
        2. Dynamic Multi-Factor Sizing (3% - 8%).
        3. Asymmetric ATR Trailing Stop (2.5x ATR) + Breakeven Ratchet after +3.0%.
        4. Progressive De-Risking Controls (Tier 1 @ 3%, Tier 2 @ 5%).
        """
        # 1. Fetch Live Account Summary
        account = broker.get_account_summary()
        if not account.get("success"):
            return {"success": False, "error": account.get("error")}

        total_nav = account["total_value"]
        available_cash = account["available_cash"]
        invested = account["invested"]
        open_positions = broker.get_open_positions()

        # 2. Progressive Circuit Breaker & Active De-Risking Check (Tier 1 @ 3%, Tier 2 @ 5%)
        safe, circuit_msg, derisked = risk_engine.evaluate_active_derisking(
            current_nav=total_nav,
            open_positions=open_positions,
            is_paper=self.paper_mode
        )
        daily_drawdown = max(0.0, (risk_engine.day_start_nav - total_nav) / max(1.0, risk_engine.day_start_nav)) if risk_engine.day_start_nav > 0 else 0.0
        if not safe:
            self.notifier.notify_alert("CRITICAL CIRCUIT BREAKER TRIPPED", f"{circuit_msg} | Derisked: {derisked}")
            return {"success": False, "circuit_breaker": True, "message": circuit_msg, "derisked": derisked}

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

        # 5. Monitor and Manage Open Positions with ATR Trailing Stop & Breakeven Ratchet
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

            # Update High Watermark Peak Price
            if t212_ticker not in self.position_peaks or cur_price > self.position_peaks[t212_ticker]:
                self.position_peaks[t212_ticker] = cur_price

            peak_p = self.position_peaks[t212_ticker]
            pnl_pct = (cur_price - avg_price) / avg_price
            peak_gain_pct = (peak_p - avg_price) / avg_price

            # Fetch ATR for Trailing Stop
            yf_ticker = t212_ticker.replace("_US_EQ", "").replace("_EQ", "").replace("l", ".L")
            snap = market_data.get_market_snapshot(yf_ticker)
            # Phase 38 Protocol: Fixed -2.5% for Trades 1-50; Dynamic 2.5x ATR for Trades 51+
            total_historical_trades = len(db.get_trades(limit=500))
            if total_historical_trades < 50:
                base_stop_pct = -settings.DEFAULT_STOP_LOSS_PCT  # Baseline -2.5% (Stage 1 Benchmark)
            else:
                # Dynamic 2.5x ATR Stop Loss (Out-of-sample forward test on £5,000 account)
                base_stop_pct = -min(0.065, max(0.025, (2.5 * atr) / avg_price))

            # Exit Rule 1: Breakeven Stop Ratchet after +3.0% Peak Gain
            effective_stop_pct = base_stop_pct
            if peak_gain_pct >= 0.030:
                effective_stop_pct = 0.001  # Breakeven (+0.1% covering friction)

            # Exit Rule 2: ATR Trailing Stop (2.5x ATR from Peak once in profit)
            atr_trailing_triggered = False
            if peak_gain_pct >= 0.030 and peak_p > 0:
                trail_distance_pct = (2.5 * atr) / peak_p
                pullback_from_peak = (peak_p - cur_price) / peak_p
                if pullback_from_peak >= trail_distance_pct and pnl_pct > 0.01:
                    atr_trailing_triggered = True

            # Trigger Stop-Loss / Breakeven Stop
            if pnl_pct <= effective_stop_pct:
                stop_label = "Breakeven Stop (+0.1%)" if effective_stop_pct > 0 else f"Stop Loss ({pnl_pct * 100:.2f}%)"
                exit_msg = f"{stop_label} triggered: {pnl_pct * 100:.2f}%"
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
                    self.notifier.notify_trade("SELL", t212_ticker, qty, cur_price, exit_msg, is_paper=self.paper_mode, pnl_pct=pnl_pct * 100.0, pnl_gbp=realized_pnl)
                    closed_trades.append(t212_ticker)
                    if t212_ticker in self.position_peaks:
                        del self.position_peaks[t212_ticker]
                    # Post-trade attribution & trajectory capture
                    try:
                        latest_trades = db.get_trades(limit=1)
                        t_id = latest_trades[0]["id"] if latest_trades else 1
                        attribution_service.classify_trade_outcome(
                            trade_id=t_id,
                            trade_data={"symbol": yf_ticker, "realized_pnl": realized_pnl, "realized_pnl_pct": pnl_pct * 100.0, "exit_reason": exit_msg},
                            telemetry={"pre_entry_latency_days": 0.0, "post_exit_mfe_20d_pct": 0.0, "entry_atr14": atr}
                        )
                        trajectory_service.record_trajectory(
                            trade_id=t_id,
                            symbol=yf_ticker,
                            entry_timestamp=datetime.now(timezone.utc).isoformat(),
                            exit_timestamp=datetime.now(timezone.utc).isoformat(),
                            entry_price=avg_price,
                            exit_price=cur_price,
                            entry_atr=atr,
                            duration_hours=24.0,
                            in_trade_mfe_pct=peak_gain_pct * 100.0,
                            in_trade_mae_pct=pnl_pct * 100.0
                        )
                    except Exception:
                        pass

            # Trigger ATR Trailing Stop
            elif atr_trailing_triggered:
                exit_msg = f"ATR Trailing Stop triggered at +{pnl_pct * 100:.2f}% (Peak was +{peak_gain_pct * 100:.2f}%)"
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
                    self.notifier.notify_trade("SELL", t212_ticker, qty, cur_price, f"{exit_msg} | Vaulted: £{realized_pnl:+.2f}", is_paper=self.paper_mode, pnl_pct=pnl_pct * 100.0, pnl_gbp=realized_pnl)
                    closed_trades.append(t212_ticker)
                    if t212_ticker in self.position_peaks:
                        del self.position_peaks[t212_ticker]
                    try:
                        latest_trades = db.get_trades(limit=1)
                        t_id = latest_trades[0]["id"] if latest_trades else 1
                        attribution_service.classify_trade_outcome(
                            trade_id=t_id,
                            trade_data={"symbol": yf_ticker, "realized_pnl": realized_pnl, "realized_pnl_pct": pnl_pct * 100.0, "exit_reason": exit_msg},
                            telemetry={"pre_entry_latency_days": 0.0, "post_exit_mfe_20d_pct": 0.0, "entry_atr14": atr}
                        )
                    except Exception:
                        pass

        # 6. Quantitative Universe Scanning & Dynamic Sizing (3% - 8%)
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

            # Market Hours Gate: Only scan assets when their domestic exchange is active
            if not market_hours.is_asset_market_open(item.get("country", "US")):
                continue

            # Event Risk Blackout Gate
            event_safe, event_reason, event_meta = event_risk_engine.evaluate_event_blackout(symbol, yf_ticker)
            if not event_safe:
                continue

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

            # Multi-Factor Sizing Multiplier (3% - 8%)
            composite_alpha_score, alpha_breakdown = alpha_engine.compute_institutional_alpha(
                symbol=symbol,
                yf_ticker=yf_ticker,
                sector=sector,
                snapshot=snapshot,
                market_regime=market_regime,
                portfolio_exposure_pct=exposure_pct,
                cost_friction_pct=0.10
            )

            units, nominal_cost, sizing_meta = portfolio_constructor.calculate_optimal_position_size(
                symbol=symbol,
                price=price,
                atr=atr,
                df=df_asset,
                core_capital=core_capital,
                available_cash=available_cash,
                remaining_capacity=remaining_allowance,
                alpha_score=composite_alpha_score,
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

            # Technical Entry Scoring
            tech_confidence, tech_factors = ai_scoring.compute_composite_confidence(
                symbol=symbol,
                snapshot=snapshot,
                market_regime=market_regime,
                portfolio_exposure_pct=exposure_pct,
                cost_friction_pct=cost_eval.get("friction_breakdown", {}).get("friction_pct", 0.10)
            )

            # Exposure-Based Risk Validation
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

            # Automated Pre-Trade Compliance & Integrity Guard
            comp_ok, comp_reason, _ = integrity_guard.validate_pre_flight_compliance(
                symbol=symbol,
                t212_ticker=t212_ticker,
                order_cost_gbp=nominal_cost,
                current_nav_gbp=core_capital,
                current_drawdown_pct=daily_drawdown * 100.0
            )
            if not comp_ok:
                risk_approved = False
                risk_reason = comp_reason

            # Boardroom Deliberation (Technical Entry Signal)
            approved_by_boardroom, decision_data = boardroom.convene_boardroom(
                symbol=symbol,
                factors=tech_factors,
                technical_confidence=tech_confidence,
                market_regime=market_regime,
                risk_approved=risk_approved,
                cost_approved=cost_eval_ok
            )

            # Permanent Evidence Recording for Signal
            evidence_recorder.record_signal({
                "symbol": symbol,
                "market_regime": market_regime,
                "technical_score": tech_confidence,
                "fundamental_score": alpha_breakdown.get("fundamental_score", 50.0),
                "sector_score": alpha_breakdown.get("sector_alpha_score", 50.0),
                "sentiment_score": alpha_breakdown.get("sentiment_score", 50.0),
                "composite_alpha": composite_alpha_score,
                "target_position_pct": sizing_meta.get("target_pct", 5.0),
                "reward_risk_ratio": cost_eval.get("net_reward_risk", 3.0),
                "status": "APPROVED" if approved_by_boardroom else "REJECTED",
                "rejection_reason": decision_data.get("reasoning", "") if not approved_by_boardroom else "Quorum Approved",
                "boardroom_votes": decision_data
            })

            candidates.append({
                "symbol": symbol,
                "t212_ticker": t212_ticker,
                "sector": sector,
                "confidence": tech_confidence,
                "alpha_score": composite_alpha_score,
                "reward_risk": cost_eval.get("net_reward_risk", 3.0),
                "price": price,
                "units": units,
                "cost": nominal_cost,
                "approved": approved_by_boardroom,
                "decision_data": decision_data,
                "cost_eval": cost_eval,
                "risk_approved": risk_approved,
                "sizing_meta": sizing_meta,
                "alpha_breakdown": alpha_breakdown
            })

        # 7. Sort by highest confidence and deploy capital
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
                    self.position_peaks[cand["t212_ticker"]] = cand["price"]
                    self.notifier.notify_trade("BUY", cand["symbol"], cand["units"], cand["price"], route_msg, is_paper=self.paper_mode)
                    available_cash -= cand["cost"]
                    remaining_allowance -= cand["cost"]

        # Generate Idle Cash Breakdown
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
        last_open_state = None
        while not self._stop_event.is_set():
            try:
                m_status = market_hours.get_market_status()
                is_open = m_status.get("any_market_open", False)
                
                # Session transition alerts
                if last_open_state is not None:
                    if not last_open_state and is_open:
                        self.notifier.notify_market_open(active_universe_count=len(universe_manager.get_all()))
                    elif last_open_state and not is_open:
                        try:
                            from src.reporting.daily_executive_report import daily_report_service
                            daily_report_service.dispatch_daily_report()
                        except Exception as report_err:
                            print(f"[Daily Report Dispatch Error] {report_err}")
                last_open_state = is_open

                if is_open:
                    self.run_cycle()
                else:
                    # Markets closed - idle quietly
                    pass
            except Exception as e:
                print(f"[QuantEngine Loop Error] {e}")
                
            for _ in range(self.scan_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

quant_engine = PRVQuantEngine()
