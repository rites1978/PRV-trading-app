import os
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd

logger = logging.getLogger("quant_engine")

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
        self.is_simulation: bool = (settings.ACCOUNT_MODE.upper() in ("SIMULATION", "INTERNAL_SIMULATION"))
        self.paper_mode: bool = self.is_simulation
        self.scan_interval: int = settings.SCAN_INTERVAL_SECONDS
        self.notifier = TelegramNotifier()
        
        # Position Tracking State (Peak Price & High Watermark)
        self.position_peaks: Dict[str, float] = {}
        
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_heartbeat_timestamp: str = datetime.now(timezone.utc).isoformat()
        self.last_heartbeat_time: float = time.time()
        self.last_cycle_time: float = time.time()
        self.missed_cycle_count: int = 0
        self.execution_health: str = "HEALTHY"

        # ⚙️ Execution Monitor Observability Telemetry
        self.last_scan_started_timestamp: Optional[str] = None
        self.last_scan_completed_timestamp: Optional[str] = None
        self.next_scan_timestamp: Optional[str] = None
        self.next_scan_time: Optional[float] = None
        self.scan_cycles_today: int = 0
        self.current_scan_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.securities_scanned_last_cycle: int = 0
        self.raw_candidates_last_cycle: int = 0
        self.final_approvals_last_cycle: int = 0
        self.orders_submitted_today: int = 0

        # Granular Order Lifecycle Counters
        self.signals_approved_today: int = 0
        self.dispatch_attempts_today: int = 0
        self.broker_orders_accepted_today: int = 0
        self.broker_fills_today: int = 0
        self.broker_rejections_today: int = 0

        self.last_decision: str = "AWAITING_FIRST_SCAN"
        self.last_no_trade_reason: str = "Engine initialized; awaiting first scheduled scan cycle."
        self.rejection_breakdown: Dict[str, int] = {
            "failed_net_rr": 0,
            "failed_technical_gate": 0,
            "failed_cost_gate": 0,
            "failed_risk_gate": 0,
            "failed_compliance": 0
        }
        self.top_rejected_candidates: List[Dict[str, Any]] = []
        self.last_execution_error: Optional[str] = None
        self._stale_heartbeat_alerted: bool = False
        self._initialized = True

    def _is_symbol_active_or_pending(self, t212_ticker: str) -> bool:
        """
        Prevents duplicate entries across scan cycles.
        Checks if symbol already exists as an open position, pending broker order, or in-flight reservation.
        """
        sym = t212_ticker.replace("_US_EQ", "").replace("_EQ", "").replace("l", ".L").upper()
        ticker_clean = t212_ticker.upper()

        # 1. Check open broker positions
        try:
            open_pos = broker.get_open_positions(force_refresh=False) or []
            for p in open_pos:
                p_tick = str(p.get("ticker", "")).upper()
                p_sym = str(p.get("symbol", "")).upper()
                if p_tick == ticker_clean or p_sym == sym:
                    return True
        except Exception:
            pass

        # 2. Check pending broker orders
        try:
            open_ord = broker.get_open_orders(force_refresh=False) or []
            for o in open_ord:
                o_tick = str(o.get("ticker", "")).upper()
                o_sym = str(o.get("symbol", "")).upper()
                if o_tick == ticker_clean or o_sym == sym:
                    return True
        except Exception:
            pass

        # 3. Check in-flight portfolio reservations
        try:
            from src.execution.order_state_machine import PortfolioReservationManager
            reservations = PortfolioReservationManager()._reservations
            for res in reservations.values():
                if res.get("symbol", "").upper() == sym:
                    return True
        except Exception:
            pass

        return False

    def start(self):
        if self.is_running:
            return
        from src.core.single_instance_lock import single_instance_lock
        if not single_instance_lock.acquire():
            err_msg = "CRITICAL: Single-instance violation! Another PRV trading engine process is already running."
            logger.error(err_msg)
            raise RuntimeError(err_msg)
        self.is_running = True
        self._stop_event.clear()
        self.last_heartbeat_time = time.time()
        self.last_heartbeat_timestamp = datetime.now(timezone.utc).isoformat()
        self.last_cycle_time = time.time()
        self.execution_health = "HEALTHY"
        self.last_execution_error = None
        self._recover_positions_on_restart()
        self.notifier.notify_alert(
            "PRV QUANT ENGINE STARTED",
            f"Autonomous execution engine active in {'PAPER' if self.paper_mode else 'LIVE'} mode."
        )
        self._thread = threading.Thread(target=self._execution_loop, daemon=True)
        self._thread.start()

    def _recover_positions_on_restart(self):
        """Hydrate open positions on restart and restore persisted high-watermark state."""
        try:
            positions = broker.get_open_positions(force_refresh=True) or []
            for p in positions:
                t212_ticker = p.get("ticker", "")
                avg_p = float(p.get("averagePrice", 0.0))
                cur_p = float(p.get("currentPrice", avg_p))
                if t212_ticker:
                    stored_wm = db.get_position_watermark(t212_ticker)
                    if stored_wm and float(stored_wm.get("peak_price", 0.0)) > 0:
                        self.position_peaks[t212_ticker] = max(cur_p, float(stored_wm["peak_price"]))
                    else:
                        self.position_peaks[t212_ticker] = max(cur_p, avg_p)
                        db.save_position_watermark(t212_ticker, peak_price=self.position_peaks[t212_ticker])
        except Exception as e:
            logger.warning(f"Error recovering positions on restart: {e}")

    def get_execution_monitor_telemetry(self) -> Dict[str, Any]:
        """Produce comprehensive live telemetry for dashboard Execution Monitor panel."""
        now_time = time.time()
        now_dt = datetime.now(timezone.utc)
        today_str = now_dt.strftime("%Y-%m-%d")
        if self.current_scan_date != today_str:
            self.scan_cycles_today = 0
            self.orders_submitted_today = 0
            self.current_scan_date = today_str

        heartbeat_age_sec = round(max(0.0, now_time - self.last_heartbeat_time), 1) if self.last_heartbeat_time > 0 else 999.0

        if self.is_running:
            if self.next_scan_time and self.next_scan_time > now_time:
                remaining_sec = int(self.next_scan_time - now_time)
                mins = remaining_sec // 60
                secs = remaining_sec % 60
                next_scan_eta = f"in {mins}m {secs:02d}s"
            else:
                next_scan_eta = "Due imminent"
        else:
            next_scan_eta = "Engine Stopped"

        # Check for watchdog heartbeat alert
        if self.is_running and heartbeat_age_sec > (self.scan_interval * 2) and not self._stale_heartbeat_alerted:
            self._stale_heartbeat_alerted = True
            try:
                self.notifier.notify_alert("PRV HEARTBEAT STALE", f"Heartbeat age is {heartbeat_age_sec:.0f}s (> {self.scan_interval * 2}s threshold)")
            except Exception:
                pass
        elif heartbeat_age_sec <= 60.0:
            self._stale_heartbeat_alerted = False

        if not self.is_running:
            status_color = "RED"
            status_text = "ENGINE STOPPED"
            status_message = "Autonomous execution engine is stopped. Background scanning loop inactive."
        elif self.last_execution_error:
            status_color = "RED"
            status_text = "EXECUTION PIPELINE FAILURE"
            status_message = f"Loop Exception: {self.last_execution_error}"
        elif heartbeat_age_sec > 180.0:
            status_color = "RED"
            status_text = "HEARTBEAT DEAD"
            status_message = f"Heartbeat expired ({heartbeat_age_sec:.0f}s old). Execution thread stalled."
        elif heartbeat_age_sec > 60.0:
            status_color = "AMBER"
            status_text = "HEARTBEAT / SCAN OVERDUE"
            status_message = f"Heartbeat delayed ({heartbeat_age_sec:.0f}s old). Awaiting loop cycle completion."
        else:
            status_color = "GREEN"
            status_text = "ENGINE HEALTHY"
            status_message = "Autonomous scanning daemon active and responsive."

        return {
            "engine_running": self.is_running,
            "status_color": status_color,
            "status_text": status_text,
            "status_message": status_message,
            "engine_heartbeat": self.last_heartbeat_timestamp,
            "heartbeat_age_sec": heartbeat_age_sec,
            "last_scan_started": self.last_scan_started_timestamp or "N/A",
            "last_scan_completed": self.last_scan_completed_timestamp or "N/A",
            "next_scan": self.next_scan_timestamp or "N/A",
            "next_scan_eta": next_scan_eta,
            "scan_cycles_today": self.scan_cycles_today,
            "securities_scanned_last_cycle": self.securities_scanned_last_cycle,
            "raw_candidates_last_cycle": self.raw_candidates_last_cycle,
            "final_approvals_last_cycle": self.final_approvals_last_cycle,
            "orders_submitted_today": self.broker_orders_accepted_today,
            "signals_approved_today": self.signals_approved_today,
            "dispatch_attempts_today": self.dispatch_attempts_today,
            "broker_orders_accepted_today": self.broker_orders_accepted_today,
            "broker_fills_today": self.broker_fills_today,
            "broker_rejections_today": self.broker_rejections_today,
            "last_decision": self.last_decision,
            "last_no_trade_reason": self.last_no_trade_reason,
            "rejection_breakdown": self.rejection_breakdown,
            "top_rejected_candidates": self.top_rejected_candidates[:5],
            "last_execution_error": self.last_execution_error
        }

    def get_watchdog_status(self) -> Dict[str, Any]:
        """Watchdog health, heartbeat, and restart recovery status."""
        elapsed = time.time() - getattr(self, "last_cycle_time", time.time())
        is_stale = elapsed > (settings.SCAN_INTERVAL_SECONDS * 4)
        health = "DEGRADED" if is_stale else "HEALTHY"
        return {
            "execution_health": health,
            "last_heartbeat_timestamp": getattr(self, "last_heartbeat_timestamp", "N/A"),
            "seconds_since_last_cycle": round(elapsed, 1),
            "stale_cycle_alert": is_stale,
            "broker_connectivity": broker.is_authenticated(),
            "restart_recovery_ready": True,
            "protection_resilience": "PROCESS_DEPENDENT (PRV DAEMON MONITORED)"
        }

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()
        self.last_heartbeat_time = time.time()
        self.last_heartbeat_timestamp = datetime.now(timezone.utc).isoformat()
        from src.core.single_instance_lock import single_instance_lock
        single_instance_lock.release()
        try:
            self.notifier.notify_alert("PRV QUANT ENGINE STOPPED", "Autonomous trading halted.")
        except Exception:
            pass

    def monitor_open_positions(self, open_positions: Optional[List[Dict[str, Any]]] = None) -> Tuple[List[str], Dict[str, Any]]:
        """
        Lightweight continuous position & risk management watchdog:
        - Tracks peak high-watermark prices.
        - Calculates certified stop-loss and ATR trailing stops.
        - Ratchets stop to breakeven (+0.1%) after +3.0% peak gain.
        - Synchronizes broker-native protective stop orders at Trading212.
        - Triggers market exits on stop loss or trailing stop violations.
        """
        closed_trades = []
        active_positions_returns = {}
        
        # Orphan Stop Reconciliation Watchdog
        if not self.paper_mode and settings.ACCOUNT_MODE in ("PRACTICE", "LIVE"):
            try:
                broker.reconcile_orphan_stops()
            except Exception as e:
                logger.warning(f"Error during orphan stop watchdog: {e}")

        from src.strategies.registry import strategy_registry
        from src.strategies.v2_rotation import strategy_v2, PositionState
        active_strategy_id = strategy_registry.get_active_execution_strategy_id()

        if open_positions is None:
            open_positions = broker.get_open_positions(force_refresh=False) or []

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

            # Fetch compact scalar ATR for Trailing Stop
            yf_ticker = t212_ticker.replace("_US_EQ", "").replace("_EQ", "").replace("l", ".L")
            snap = market_data.get_market_snapshot(yf_ticker)
            atr = snap["indicators"]["atr"] if (snap.get("success") and "atr" in snap.get("indicators", {})) else (avg_price * 0.02)
            active_positions_returns[yf_ticker] = snap.get("recent_returns", [])

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STRATEGY EXECUTION ROUTING: V2 ROTATION VS V1 BENCHMARK
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if str(active_strategy_id).upper() in ("V2", "ETF_V1", "PRV_HIT_AND_RUN_ETF_V1"):
                is_uk = t212_ticker.endswith("l_EQ") or ".L" in yf_ticker
                # In Trading212, UK LSE equities are quoted in pence (GBX).
                # Normalize prices to GBP for internal capital accounting and order routing.
                avg_price_gbp = (avg_price / 100.0) if is_uk else avg_price
                cur_price_gbp = (cur_price / 100.0) if is_uk else cur_price
                peak_p_gbp = (peak_p / 100.0) if is_uk else peak_p

                deployed_capital = round(qty * avg_price_gbp, 2)
                current_value = round(qty * cur_price_gbp, 2)
                entry_friction = strategy_v2.compute_entry_friction(
                    nominal_capital=deployed_capital,
                    is_uk=is_uk,
                    is_foreign=(not is_uk),
                    shares_count=qty
                )
                entry_costs = entry_friction["total_entry_friction"]
                net_eval = strategy_v2.calculate_estimated_net_liquidation_pnl(
                    current_value=current_value,
                    true_entry_capital=deployed_capital,
                    entry_costs=entry_costs,
                    ticker=t212_ticker,
                    is_uk=is_uk,
                    is_foreign=(not is_uk),
                    shares_count=qty
                )
                estimated_net_pnl = net_eval["estimated_net_pnl"]

                peak_val = round(qty * peak_p_gbp, 2)
                peak_eval = strategy_v2.calculate_estimated_net_liquidation_pnl(
                    current_value=peak_val,
                    true_entry_capital=deployed_capital,
                    entry_costs=entry_costs,
                    ticker=t212_ticker,
                    is_uk=is_uk,
                    is_foreign=(not is_uk),
                    shares_count=qty
                )
                peak_net_pnl = peak_eval["estimated_net_pnl"]

                min_target = strategy_v2.calculate_min_net_profit_target(deployed_capital)
                current_state = PositionState.PROFIT_PROTECTED if peak_net_pnl >= min_target else PositionState.OPEN
                trend_score = 70.0
                if snap.get("success") and "rsi" in snap.get("indicators", {}):
                    trend_score = float(snap["indicators"]["rsi"])

                lifecycle = strategy_v2.evaluate_position_lifecycle(
                    current_state=current_state,
                    capital_deployed=deployed_capital,
                    estimated_net_pnl=estimated_net_pnl,
                    peak_net_pnl=peak_net_pnl,
                    trend_score=trend_score
                )

                # Persist watermark state to database
                state_label = lifecycle["new_state"].value if hasattr(lifecycle["new_state"], "value") else str(lifecycle["new_state"])
                db.save_position_watermark(t212_ticker, peak_price=peak_p, peak_pnl_pct=peak_gain_pct, peak_net_pnl=peak_net_pnl, state=state_label)

                # Compute desired broker stop price in GBP, then scale to native broker currency (GBX pence if UK)
                if lifecycle["new_state"] == PositionState.PROFIT_PROTECTED:
                    exit_costs = net_eval["estimated_exit_costs"]["total_exit_costs"]
                    required_val = deployed_capital + entry_costs + exit_costs + lifecycle["protected_floor_gbp"]
                    desired_broker_stop_gbp = required_val / qty
                else:
                    max_loss = strategy_v2.calculate_max_intended_loss(deployed_capital)
                    desired_broker_stop_gbp = (deployed_capital - max_loss) / qty

                desired_broker_stop = round((desired_broker_stop_gbp * 100.0) if is_uk else desired_broker_stop_gbp, 2)

                if not self.paper_mode and settings.ACCOUNT_MODE in ("PRACTICE", "LIVE"):
                    try:
                        broker.sync_broker_stop_order(t212_ticker, qty, desired_broker_stop, time_validity="GOOD_TILL_CANCEL")
                    except Exception as stop_sync_err:
                        logger.warning(f"Error syncing broker stop for {t212_ticker}: {stop_sync_err}")

                if lifecycle["should_exit"]:
                    exit_msg = f"V2 {lifecycle['action']}: {lifecycle['reason']}"
                    success, msg, trade_res = order_router.route_exit_order(
                        symbol=t212_ticker,
                        t212_ticker=t212_ticker,
                        quantity=qty,
                        current_price=cur_price_gbp,
                        entry_price=avg_price_gbp,
                        exit_reason=exit_msg,
                        is_paper=self.paper_mode
                    )
                    if success:
                        trade_id = trade_res.get("trade_id", f"PRV_EXIT_{t212_ticker}") if isinstance(trade_res, dict) else f"PRV_EXIT_{t212_ticker}"
                        net_pnl = trade_res.get("net_realized_pnl", estimated_net_pnl) if isinstance(trade_res, dict) else float(trade_res or estimated_net_pnl)
                        gross_pnl = trade_res.get("gross_profit_loss", net_eval["gross_pnl"]) if isinstance(trade_res, dict) else net_eval["gross_pnl"]
                        total_costs = trade_res.get("total_transaction_costs", net_eval["total_friction"]) if isinstance(trade_res, dict) else net_eval["total_friction"]

                        capital_manager.process_realized_trade(trade_id, t212_ticker, net_pnl)

                        strategy_v2.record_rotation(
                            rotation_id=trade_id,
                            ticker=t212_ticker,
                            deployed_capital=deployed_capital,
                            entry_broker_ids=[],
                            exit_broker_ids=[],
                            gross_pnl=gross_pnl,
                            sdrt=entry_friction.get("sdrt", 0.0),
                            fx=entry_friction.get("fx_fee", 0.0),
                            regulatory_fees=0.0,
                            other_costs=round(max(0.0, total_costs - entry_friction.get("sdrt", 0.0) - entry_friction.get("fx_fee", 0.0)), 2),
                            realised_net_pnl=net_pnl,
                            strategy_id="V2",
                            rotation_type="STRATEGY_ROTATION"
                        )

                        self.notifier.notify_trade("SELL", t212_ticker, qty, cur_price_gbp, exit_msg, is_paper=self.paper_mode, pnl_pct=(net_pnl / max(1.0, deployed_capital)) * 100.0, pnl_gbp=net_pnl)
                        closed_trades.append(t212_ticker)
                        if t212_ticker in self.position_peaks:
                            del self.position_peaks[t212_ticker]
                        db.clear_position_watermark(t212_ticker)

                        if "STOP" in exit_msg.upper() or net_pnl < 0:
                            db.add_symbol_cooldown(symbol=yf_ticker, t212_ticker=t212_ticker, trade_id=0, duration_days=10, reason=exit_msg)

                        try:
                            latest_trades = db.get_trades(limit=1)
                            t_id = latest_trades[0]["id"] if latest_trades else 1
                            attribution_service.classify_trade_outcome(
                                trade_id=t_id,
                                trade_data={"symbol": yf_ticker, "realized_pnl": net_pnl, "realized_pnl_pct": (net_pnl / max(1.0, deployed_capital)) * 100.0, "exit_reason": exit_msg},
                                telemetry={"pre_entry_latency_days": 0.0, "post_exit_mfe_20d_pct": 0.0, "entry_atr14": atr}
                            )
                            trajectory_service.record_trajectory(
                                trade_id=t_id,
                                symbol=yf_ticker,
                                entry_timestamp=datetime.now(timezone.utc).isoformat(),
                                exit_timestamp=datetime.now(timezone.utc).isoformat(),
                                entry_price=avg_price_gbp,
                                exit_price=cur_price_gbp,
                                entry_atr=atr,
                                duration_hours=24.0,
                                in_trade_mfe_pct=peak_gain_pct * 100.0,
                                in_trade_mae_pct=pnl_pct * 100.0
                            )
                        except Exception:
                            pass

            else:
                # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                # LEGACY V1 SWING STRATEGY (UNCHANGED BENCHMARK)
                # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                total_historical_trades = len(db.get_trades(limit=500))
                if total_historical_trades < 50:
                    base_stop_pct = -settings.DEFAULT_STOP_LOSS_PCT  # Baseline -2.5% (Stage 1 Benchmark)
                else:
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

                # Synchronize broker-native protective stop order (crash-resistant floor)
                desired_broker_stop = round(avg_price * (1.0 + effective_stop_pct), 2)
                if not self.paper_mode and settings.ACCOUNT_MODE in ("PRACTICE", "LIVE"):
                    try:
                        broker.sync_broker_stop_order(t212_ticker, qty, desired_broker_stop, time_validity="DAY")
                    except Exception as stop_sync_err:
                        logger.warning(f"Error syncing broker stop for {t212_ticker}: {stop_sync_err}")

                # Trigger Stop-Loss / Breakeven Stop
                if pnl_pct <= effective_stop_pct:
                    stop_label = "Breakeven Stop (+0.1%)" if effective_stop_pct > 0 else f"Stop Loss ({pnl_pct * 100:.2f}%)"
                    exit_msg = f"{stop_label} triggered: {pnl_pct * 100:.2f}%"
                    success, msg, trade_res = order_router.route_exit_order(
                        symbol=t212_ticker,
                        t212_ticker=t212_ticker,
                        quantity=qty,
                        current_price=cur_price,
                        entry_price=avg_price,
                        exit_reason=exit_msg,
                        is_paper=self.paper_mode
                    )
                    if success:
                        trade_id = trade_res.get("trade_id", f"EXIT_{t212_ticker}") if isinstance(trade_res, dict) else f"EXIT_{t212_ticker}"
                        realized_pnl = trade_res.get("net_realized_pnl", 0.0) if isinstance(trade_res, dict) else float(trade_res or 0.0)
                        capital_manager.process_realized_trade(trade_id, t212_ticker, realized_pnl)
                        self.notifier.notify_trade("SELL", t212_ticker, qty, cur_price, exit_msg, is_paper=self.paper_mode, pnl_pct=pnl_pct * 100.0, pnl_gbp=realized_pnl)
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
                    success, msg, trade_res = order_router.route_exit_order(
                        symbol=t212_ticker,
                        t212_ticker=t212_ticker,
                        quantity=qty,
                        current_price=cur_price,
                        entry_price=avg_price,
                        exit_reason=exit_msg,
                        is_paper=self.paper_mode
                    )
                    if success:
                        trade_id = trade_res.get("trade_id", f"EXIT_{t212_ticker}") if isinstance(trade_res, dict) else f"EXIT_{t212_ticker}"
                        realized_pnl = trade_res.get("net_realized_pnl", 0.0) if isinstance(trade_res, dict) else float(trade_res or 0.0)
                        capital_manager.process_realized_trade(trade_id, t212_ticker, realized_pnl)
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

        return closed_trades, active_positions_returns

    def run_cycle(self) -> Dict[str, Any]:
        """
        Execute Phase 6 Return-Optimized quantitative cycle:
        1. Technical Engine generates entry signal (Buy/No-Buy).
        2. Dynamic Multi-Factor Sizing (3% - 8%).
        3. Asymmetric ATR Trailing Stop (2.5x ATR) + Breakeven Ratchet after +3.0%.
        4. Progressive De-Risking Controls (Tier 1 @ 3%, Tier 2 @ 5%).
        """
        self.last_cycle_time = time.time()
        self.last_heartbeat_time = time.time()
        self.last_heartbeat_timestamp = datetime.now(timezone.utc).isoformat()
        self.last_scan_started_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.execution_health = "HEALTHY"
        self.last_execution_error = None

        # 0. PERMANENT PRODUCTION INVARIANTS
        from src.strategies.registry import strategy_registry
        active_strategy_id = strategy_registry.get_active_execution_strategy_id()
        ratified_strategy_id = getattr(settings, "RATIFIED_STRATEGY_ID", "PRV_HIT_AND_RUN_ETF_V1")
        if str(active_strategy_id).upper() != str(ratified_strategy_id).upper():
            msg = f"INVARIANT_VIOLATION: Running strategy '{active_strategy_id}' != Ratified strategy '{ratified_strategy_id}'. Engine refuses to trade."
            logger.critical(msg)
            self.last_decision = f"HALT: {msg}"
            self.last_execution_error = msg
            return {"success": False, "halt": True, "error": msg}

        ratified_sha = getattr(settings, "RATIFIED_COMMIT_SHA", "auto")
        running_sha = os.getenv("RENDER_GIT_COMMIT", "")
        if not running_sha:
            try:
                import subprocess
                running_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
            except Exception:
                running_sha = "UNKNOWN"
        if ratified_sha not in ("auto", "", "UNKNOWN") and running_sha not in ("UNKNOWN", ""):
            if not running_sha.startswith(ratified_sha) and not ratified_sha.startswith(running_sha):
                msg = f"INVARIANT_VIOLATION: Running commit '{running_sha[:7]}' != Ratified commit '{ratified_sha[:7]}'. Engine refuses to trade."
                logger.critical(msg)
                self.last_decision = f"HALT: {msg}"
                self.last_execution_error = msg
                return {"success": False, "halt": True, "error": msg}

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
        
        from src.strategies.registry import strategy_registry
        active_strategy_id = strategy_registry.get_active_execution_strategy_id()

        market_regime, target_deployment_pct = capital_manager.determine_market_regime(
            market_breadth_score=75.0,
            sp500_trend_score=sp500_trend_score
        )
        
        remaining_allowance, _ = capital_manager.calculate_deployment_allowance(
            core_capital, active_capital, market_regime, strategy_id=active_strategy_id
        )

        # 5. Monitor and Manage Open Positions with ATR Trailing Stop & Breakeven Ratchet
        holding_map = {p.get("ticker"): p for p in open_positions}
        closed_trades, active_positions_dfs = self.monitor_open_positions(open_positions)

        # 6. Quantitative Universe Scanning & Dynamic Sizing (3% - 8%)
        # Fail-closed: Only scan securities with verified broker-native identifiers
        universe = universe_manager.validate_universe_fail_closed()

        def _evaluate_single_candidate(item):
            symbol = item.get("symbol", "UNKNOWN")
            self.last_heartbeat_time = time.time()
            self.last_heartbeat_timestamp = datetime.now(timezone.utc).isoformat()
            try:
                yf_ticker = item["yf_ticker"]
                t212_ticker = item["t212_ticker"]
                sector = item["sector"]
                is_foreign = (item["currency"] != "GBP")
                is_uk = (item["country"] == "UK")
                is_uk_pence = item.get("is_uk_pence", False)

                # Market Hours Gate: Only scan assets when their domestic exchange is active
                if not market_hours.is_asset_market_open(item.get("country", "US")):
                    return None

                # Event Risk Blackout Gate
                event_safe, event_reason, event_meta = event_risk_engine.evaluate_event_blackout(symbol, yf_ticker)
                if not event_safe:
                    return None

                # Deduplication Gate: Exclude already held, ordered, or reserved symbols
                if self._is_symbol_active_or_pending(t212_ticker):
                    return None

                existing_pos = holding_map.get(t212_ticker)
                current_holding_val = 0.0
                if existing_pos and t212_ticker not in closed_trades:
                    current_holding_val = float(existing_pos.get("quantity", 0)) * float(existing_pos.get("currentPrice", 0))

                snapshot = market_data.get_market_snapshot(yf_ticker, is_uk_pence=is_uk_pence)
                if not snapshot.get("success"):
                    return None

                price = snapshot["current_price"]
                atr = snapshot["indicators"]["atr"]
                ann_vol = snapshot.get("indicators", {}).get("annualized_vol", 0.20)

                # Multi-Factor Sizing Multiplier (3% - 8%)
                composite_alpha_score, alpha_breakdown = alpha_engine.compute_institutional_alpha(
                    symbol=symbol,
                    yf_ticker=yf_ticker,
                    sector=sector,
                    snapshot=snapshot,
                    market_regime=market_regime,
                    portfolio_exposure_pct=exposure_pct,
                    cost_friction_pct=0.10,
                    strategy_id=active_strategy_id
                )

                units, nominal_cost, sizing_meta = portfolio_constructor.calculate_optimal_position_size(
                    symbol=symbol,
                    price=price,
                    atr=atr,
                    df=ann_vol,
                    core_capital=core_capital,
                    available_cash=available_cash,
                    remaining_capacity=remaining_allowance,
                    alpha_score=composite_alpha_score,
                    current_holding_val=current_holding_val,
                    active_positions_dfs=active_positions_dfs
                )

                if str(active_strategy_id).upper() in ("ETF_V1", "PRV_HIT_AND_RUN_ETF_V1"):
                    if len(open_positions) >= 1:
                        return None
                    nominal_cost = min(35000.0, available_cash)
                    units = max(1, int(nominal_cost / price)) if price > 0 else 0
                    nominal_cost = round(units * price, 2)
                    stop_loss_price = round(price * (1.0 - 0.008), 4)
                    target_price = round(price * (1.0 + 0.008), 4)
                else:
                    if units <= 0 or nominal_cost < 50.0:
                        return None
                    stop_loss_price = price * (1.0 - settings.DEFAULT_STOP_LOSS_PCT)
                    target_price = price * (1.0 + settings.DEFAULT_TAKE_PROFIT_PCT)
                
                # Spread-Aware Cost Model Evaluation
                cost_eval_ok, cost_eval = cost_model.evaluate_net_edge(
                    entry_price=price,
                    target_price=target_price,
                    stop_loss_price=stop_loss_price,
                    nominal_value=nominal_cost,
                    is_foreign=is_foreign,
                    is_uk=is_uk
                )

                # Technical Entry Scoring
                tech_confidence, tech_factors = ai_scoring.compute_composite_confidence(
                    symbol=symbol,
                    snapshot=snapshot,
                    market_regime=market_regime,
                    portfolio_exposure_pct=exposure_pct,
                    cost_friction_pct=cost_eval.get("friction_breakdown", {}).get("friction_pct", 0.10),
                    strategy_id=active_strategy_id
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

                return {
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
                }
            except Exception as e:
                # Candidate Loop Isolation: Log error and safely skip candidate without terminating the scan
                try:
                    db.record_audit_event(
                        event_type="CANDIDATE_SCAN_ISOLATION_ERROR",
                        symbol=symbol,
                        reason=f"Candidate isolation caught: {type(e).__name__}: {str(e)}",
                        details={"error": str(e), "symbol": symbol}
                    )
                except Exception:
                    pass
                return None

        import gc
        with ThreadPoolExecutor(max_workers=2) as executor:
            scanned_results = list(executor.map(_evaluate_single_candidate, universe))

        candidates = [c for c in scanned_results if c is not None]
        gc.collect()

        # 7. Sort by highest confidence and deploy capital
        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        executed_trades = []

        # Check practice vs real-money entry permissions
        entries_allowed = (
            (settings.ACCOUNT_MODE == "PRACTICE" and settings.PRACTICE_TRADING_ENABLED and settings.PRACTICE_NEW_ENTRIES_ALLOWED)
            or (settings.ACCOUNT_MODE == "LIVE" and settings.REAL_MONEY_TRADING_ENABLED and settings.REAL_MONEY_NEW_ENTRIES_ALLOWED)
        )
        if str(active_strategy_id).upper() == "V1":
            min_cash_floor = settings.STARTING_CAPITAL * (settings.REQUIRED_CASH_RESERVE_PCT / 100.0)
        else:
            # Strategy V2: Ratified Dynamic Deployment Policy (5% operational buffer, 0% fixed cash floor)
            min_cash_floor = settings.STARTING_CAPITAL * settings.MIN_CASH_BUFFER_PCT

        min_deployment_chunk = settings.STARTING_CAPITAL * (settings.MIN_POSITION_SIZE_PCT / 100.0)

        executed_trades = []
        accepted_orders = []
        rejected_orders = []

        if entries_allowed:
            for cand in candidates:
                if remaining_allowance < min_deployment_chunk or (available_cash - cand["cost"]) < min_cash_floor:
                    break

                if cand["approved"] and cand["units"] > 0:
                    agent_votes = {
                        "trend": cand["decision_data"]["trend_agent_vote"],
                        "momentum": cand["decision_data"]["momentum_agent_vote"],
                        "volatility": cand["decision_data"]["volatility_agent_vote"],
                        "liquidity": cand["decision_data"]["liquidity_agent_vote"],
                        "risk": cand["decision_data"]["risk_agent_vote"]
                    }
                    
                    target_price = round(cand["price"] * (1.0 + settings.DEFAULT_TAKE_PROFIT_PCT), 4)
                    stop_loss_price = round(cand["price"] * (1.0 - settings.DEFAULT_STOP_LOSS_PCT), 4)

                    self.dispatch_attempts_today += 1
                    success, route_msg, trade_res = order_router.route_entry_order(
                        symbol=cand["symbol"],
                        t212_ticker=cand["t212_ticker"],
                        quantity=cand["units"],
                        price=cand["price"],
                        target_price=target_price,
                        stop_loss_price=stop_loss_price,
                        sector=cand["sector"],
                        confidence_score=cand["confidence"],
                        market_regime=market_regime,
                        agent_votes=agent_votes,
                        risk_approved=cand["risk_approved"],
                        is_simulation=self.is_simulation,
                        strategy_id=active_strategy_id
                    )
                    
                    if success:
                        self.broker_orders_accepted_today += 1
                        order_status = str(trade_res.get("status", "")).upper()
                        if order_status == "FILLED":
                            self.broker_fills_today += 1
                            executed_trades.append(cand["symbol"])
                        else:
                            accepted_orders.append(cand["symbol"])

                        self.position_peaks[cand["t212_ticker"]] = cand["price"]
                        self.notifier.notify_trade(
                            "BUY", cand["symbol"], cand["units"], cand["price"],
                            route_msg, is_paper=self.is_simulation
                        )
                        available_cash -= cand["cost"]
                        remaining_allowance -= cand["cost"]
                    else:
                        self.broker_rejections_today += 1
                        rejected_orders.append(cand["symbol"])

        # Generate Idle Cash Breakdown
        idle_cash_audit = capital_manager.generate_idle_cash_audit(
            core_capital=core_capital,
            available_cash=available_cash,
            active_capital=active_capital,
            market_regime=market_regime,
            rejected_candidates=candidates,
            strategy_id=active_strategy_id
        )

        # ⚙️ Execution Monitor Telemetry Aggregation
        self.securities_scanned_last_cycle = len(universe)
        self.raw_candidates_last_cycle = len(candidates)
        
        rejections = {
            "failed_net_rr": 0,
            "failed_technical_gate": 0,
            "failed_cost_gate": 0,
            "failed_risk_gate": 0,
            "failed_compliance": 0
        }
        top_rejected = []
        approved_candidates = []

        for cand in candidates:
            if cand.get("approved") and cand.get("units", 0) > 0 and cand.get("risk_approved", True):
                approved_candidates.append(cand)
            else:
                reason = ""
                c_eval = cand.get("cost_eval", {})
                if not c_eval.get("approved", True):
                    rejections["failed_cost_gate"] += 1
                    reason = c_eval.get("rejection_reason", "Excess friction / low reward-risk")
                elif cand.get("reward_risk", 3.0) < 2.0:
                    rejections["failed_net_rr"] += 1
                    reason = f"Net R:R {cand.get('reward_risk', 0.0):.1f}x < 2.0x threshold"
                elif not cand.get("risk_approved", True):
                    rejections["failed_risk_gate"] += 1
                    reason = "Exposure limit or risk circuit veto"
                elif cand.get("confidence", 0.0) < 65.0:
                    rejections["failed_technical_gate"] += 1
                    reason = f"Technical confidence {cand.get('confidence', 0.0):.1f}% < 65%"
                else:
                    dec_data = cand.get("decision_data", {})
                    reason = dec_data.get("reasoning", "Boardroom quorum consensus rejected entry")
                    rejections["failed_technical_gate"] += 1

                top_rejected.append({
                    "symbol": cand.get("symbol", "N/A"),
                    "confidence": round(cand.get("confidence", 0.0), 1),
                    "net_rr": round(cand.get("reward_risk", 0.0), 2),
                    "price": cand.get("price", 0.0),
                    "reason": reason
                })

        self.rejection_breakdown = rejections
        self.top_rejected_candidates = top_rejected[:5]
        self.final_approvals_last_cycle = len(approved_candidates)
        self.signals_approved_today += len(approved_candidates)

        if len(executed_trades) > 0:
            self.last_decision = f"TRADES EXECUTED: {', '.join(executed_trades)}"
            self.last_no_trade_reason = f"{len(executed_trades)} broker fills confirmed."
        elif len(accepted_orders) > 0:
            self.last_decision = f"ORDERS ACCEPTED: {', '.join(accepted_orders)} (PENDING FILL)"
            self.last_no_trade_reason = f"{len(accepted_orders)} orders accepted by broker gateway."
        elif len(rejected_orders) > 0:
            self.last_decision = f"ORDERS REJECTED BY BROKER: {', '.join(rejected_orders)}"
            self.last_no_trade_reason = f"{len(rejected_orders)} order dispatches rejected by broker."
        elif len(candidates) == 0:
            self.last_decision = "NO CANDIDATES DETECTED"
            self.last_no_trade_reason = "Zero raw candidates passed initial universe screening."
        else:
            self.last_decision = "NO TRADE — SCAN COMPLETED SUCCESSFULLY"
            reasons_summary = []
            if rejections["failed_net_rr"] > 0:
                reasons_summary.append(f"{rejections['failed_net_rr']} failed net R:R")
            if rejections["failed_technical_gate"] > 0:
                reasons_summary.append(f"{rejections['failed_technical_gate']} failed technical gate")
            if rejections["failed_cost_gate"] > 0:
                reasons_summary.append(f"{rejections['failed_cost_gate']} failed cost gate")
            if rejections["failed_risk_gate"] > 0:
                reasons_summary.append(f"{rejections['failed_risk_gate']} failed risk gate")
            summary_text = ", ".join(reasons_summary) if reasons_summary else "all candidates below edge thresholds"
            self.last_no_trade_reason = f"{len(candidates)} candidates evaluated: {summary_text}."

        self.last_scan_completed_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.scan_cycles_today += 1
        self.next_scan_time = time.time() + self.scan_interval
        self.next_scan_timestamp = datetime.fromtimestamp(self.next_scan_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        return {
            "success": True,
            "capital_state": capital_state,
            "market_regime": market_regime,
            "target_deployment_pct": target_deployment_pct,
            "scanned_count": len(universe),
            "executed_trades": executed_trades,
            "candidates_count": len(candidates),
            "idle_cash_audit": idle_cash_audit,
            "execution_monitor": self.get_execution_monitor_telemetry(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def _execution_loop(self):
        last_open_state = None
        while not self._stop_event.is_set():
            try:
                self.last_heartbeat_time = time.time()
                self.last_heartbeat_timestamp = datetime.now(timezone.utc).isoformat()
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
                    self.next_scan_time = time.time() + self.scan_interval
                    self.next_scan_timestamp = datetime.fromtimestamp(self.next_scan_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                err_msg = f"{type(e).__name__}: {str(e)}"
                self.last_execution_error = err_msg
                print(f"[QuantEngine Loop Error] {e}")
                try:
                    self.notifier.notify_alert("PRV SCAN LOOP FAILURE", err_msg)
                except Exception:
                    pass
            finally:
                import gc
                gc.collect()
                
            sleep_ticks = self.scan_interval
            for tick in range(sleep_ticks):
                if self._stop_event.is_set():
                    break
                self.last_heartbeat_time = time.time()
                self.last_heartbeat_timestamp = datetime.now(timezone.utc).isoformat()
                
                # Continuous lightweight position & stop protection watchdog every 15 seconds
                if tick > 0 and tick % 15 == 0:
                    try:
                        self.monitor_open_positions()
                    except Exception as pos_err:
                        logger.warning(f"Position monitor watchdog error: {pos_err}")

                time.sleep(1)

quant_engine = PRVQuantEngine()
