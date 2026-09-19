#!/usr/bin/env python3
"""
PRV Capital - Daily Hit-and-Run DEMO Experiment Runner
Governing Authority: PRV_HIT_AND_RUN_ACCEPTANCE_CONTRACT.md

Orchestrates the daily experimental cycle:
BUILD -> TRADE -> OBSERVE -> REVIEW -> CHANGE -> REPEAT

Cycle Phases:
1. PRE-SESSION:
   - Verifies BROKER_ENVIRONMENT == DEMO
   - Captures starting account balances (CASH, EQUITY, AVAILABLE_TO_TRADE)
   - Verifies clean slate (OPEN_POSITIONS = 0, OPEN_ORDERS = 0)
   - Pins Git commit SHA and strategy experiment version
2. TRADING SESSION:
   - Evaluates active market opportunities
   - Calls injected authorised strategy module
   - Dispatches approved entries via DemoExecutionDispatcher
   - Monitors active holdings and protective stops
   - Logs detailed audit trail
3. END OF DAY:
   - Stops opening new positions
   - Flattens active holdings and cancels open stops (ensuring clean overnight state)
   - Reconciles ending account balances and net P&L
   - Outputs complete End-of-Day Review report

STRICT INVARIANT:
The runner itself DOES NOT invent strategy behaviour.
Strategy logic must be injected via a separately authorized experiment module.
If no authorized strategy is attached, the runner halts new entries with:
STRATEGY_STATUS = AWAITING_USER_AUTHORISATION
"""
import os
import sys
import time
import json
import logging
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brokers.trading212 import broker
from src.hit_and_run.demo_execution import demo_execution_dispatcher, DemoExecutionDispatcher
from src.hit_and_run.models import HitAndRunEntryDecision
from src.hit_and_run.banking import DailyBankingLedger
from src.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("demo_runner")


class DemoExperimentRunner:
    """Orchestrates daily DEMO trading experiments."""

    def __init__(
        self,
        experiment_id: str,
        strategy_version: str,
        strategy_module: Optional[Any] = None,
        dispatcher: Optional[DemoExecutionDispatcher] = None,
        audit_log_dir: str = "data/demo_experiments"
    ):
        self.experiment_id = experiment_id
        self.strategy_version = strategy_version
        self.strategy_module = strategy_module
        self.dispatcher = dispatcher or demo_execution_dispatcher
        self.audit_log_dir = audit_log_dir
        os.makedirs(self.audit_log_dir, exist_ok=True)

        self.git_sha = self._get_git_sha()
        self.starting_equity: float = 0.0
        self.starting_cash: float = 0.0
        self.trades_log: List[Dict[str, Any]] = []
        self.active_holdings: Dict[str, Dict[str, Any]] = {}
        self.banking_ledger = DailyBankingLedger(base_target_gbp=100.0)
        self.product_failures: List[str] = []
        self.canary_armed: bool = os.getenv("PRV_DEMO_CANARY_ARMED", "true").lower() in ("true", "1", "yes")
        self.canary_executed_dates: set = set()
        self.securities_scanned_last_cycle: int = 0
        self.raw_candidates_last_cycle: int = 0
        self.final_approvals_last_cycle: int = 0

    def _get_git_sha(self) -> str:
        try:
            res = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            return res
        except Exception:
            return "UNKNOWN_GIT_SHA"

    def pre_session_startup(self, allow_existing_positions: bool = False) -> Dict[str, Any]:
        """
        Phase 1: Pre-session validation and account verification.
        Fails closed if pre-existing positions or orders exist (unless allow_existing_positions=True).
        """
        logger.info(f"[Runner] Initializing Pre-Session for Experiment {self.experiment_id} (SHA: {self.git_sha})")

        # 1. Verify broker environment is strictly DEMO
        env = getattr(broker, "env", "") or getattr(settings, "TRADING_ENV", "")
        if str(env).lower() != "demo":
            msg = f"SAFETY_HALT: Broker environment is '{env}', expected 'demo'."
            logger.critical(msg)
            raise RuntimeError(msg)

        # 2. Capture initial account state
        acc = broker.get_account_summary(force_refresh=True)
        if not acc.get("success"):
            msg = f"BROKER_UNAVAILABLE: Failed to fetch DEMO account summary: {acc}"
            logger.error(msg)
            self.product_failures.append(msg)
            raise RuntimeError(msg)

        raw = acc.get("raw", {})
        self.starting_cash = float(raw.get("free", 0.0))
        self.starting_equity = float(raw.get("total", 0.0))

        # 3. Verify clean slate (0 positions, 0 orders)
        reconcile = self.dispatcher.reconcile_broker_state()
        if not reconcile["is_clean_slate"]:
            if not allow_existing_positions:
                msg = (
                    f"ACCOUNT_STATE_NOT_CLEAN: Found {reconcile['positions_count']} open positions "
                    f"and {reconcile['orders_count']} open orders in DEMO account. "
                    f"Abort startup to avoid contaminating experiment."
                )
                logger.critical(msg)
                raise RuntimeError(msg)
            else:
                logger.warning(
                    f"[Runner] Existing positions found in DEMO account ({reconcile['positions_count']} positions). "
                    f"Adopting existing positions into active monitoring."
                )
                for pos in reconcile.get("positions", []):
                    ticker = pos.get("ticker", "")
                    if ticker and ticker not in self.active_holdings:
                        qty = float(pos.get("quantity", 0.0))
                        avg_p = float(pos.get("averagePrice", 0.0))
                        cur_p = float(pos.get("currentPrice", avg_p))
                        is_pence = ((str(ticker).endswith("l_EQ") or ticker == "CSP1_EQ") and ticker != "VUSAl_EQ")
                        if is_pence:
                            entry_gbp = round(qty * avg_p / 100.0, 2)
                        elif str(ticker).endswith("l_EQ") or str(ticker).endswith(".L"):
                            entry_gbp = round(qty * avg_p, 2)
                        else:
                            entry_gbp = round(qty * avg_p / 1.30, 2)

                        self.active_holdings[ticker] = {
                            "ticker": ticker,
                            "quantity": qty,
                            "fill_price": avg_p,
                            "current_price": cur_p,
                            "entry_cost_gbp": entry_gbp,
                            "entry_time": datetime.now(timezone.utc).isoformat(),
                            "fx_rate": 1.0 if (str(ticker).endswith("l_EQ") or ticker == "CSP1_EQ") else 1.30
                        }

        startup_record = {
            "experiment_id": self.experiment_id,
            "git_sha": self.git_sha,
            "strategy_version": self.strategy_version,
            "broker_environment": "DEMO",
            "starting_cash": self.starting_cash,
            "starting_equity": self.starting_equity,
            "open_positions": len(self.active_holdings),
            "open_orders": reconcile.get("orders_count", 0),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"[Runner] Pre-session verified: Cash=£{self.starting_cash:.2f}, Equity=£{self.starting_equity:.2f}, Active Holdings={len(self.active_holdings)}")
        return startup_record

    def run_scan_and_execute_cycle(self, opportunities: List[Any]) -> Dict[str, Any]:
        """
        Phase 2: Trading Session Cycle.
        Evaluates opportunities via injected strategy, and executes approved entries.
        """
        if not self.strategy_module:
            logger.info("[Runner] No strategy module injected; STRATEGY_STATUS = AWAITING_USER_AUTHORISATION")
            return {
                "cycle_status": "AWAITING_USER_AUTHORISATION",
                "entries_submitted": 0,
                "reason": "Strategy rules not yet user-authorised"
            }

        # 1. Resolve FX rate
        current_fx = None
        if hasattr(self.strategy_module, "fx_provider") and self.strategy_module.fx_provider:
            prov = self.strategy_module.fx_provider
            if hasattr(prov, "get_gbp_usd_rate"):
                current_fx = prov.get_gbp_usd_rate()
            elif hasattr(prov, "get_rate"):
                current_fx = prov.get_rate("GBP", "USD")
        active_fx = current_fx or 1.30

        # 2. Check active holdings for strategy exits (Profit Banked £100, TP, Momentum Reversal, Edge Decay, Session End)
        if hasattr(self.strategy_module, "evaluate_exit"):
            for ticker, holding in list(self.active_holdings.items()):
                import inspect
                try:
                    sig = inspect.signature(self.strategy_module.evaluate_exit)
                    has_fx_param = "fx_gbpusd" in sig.parameters or any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
                except Exception:
                    has_fx_param = True

                if has_fx_param:
                    should_exit, exit_reason = self.strategy_module.evaluate_exit(holding, fx_gbpusd=current_fx)
                else:
                    should_exit, exit_reason = self.strategy_module.evaluate_exit(holding)

                if should_exit:
                    logger.info(f"[Runner] Exit signal for {ticker}: reason={exit_reason}")
                    exit_res = self.dispatcher.execute_exit(
                        ticker=ticker,
                        quantity=holding["quantity"],
                        reason=exit_reason
                    )
                    self.trades_log.append({
                        "type": "EXIT",
                        "ticker": ticker,
                        "reason": exit_reason,
                        "result": exit_res,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    err_str = str(exit_res.get("error", ""))
                    is_already_closed = ("selling-equity-not-owned" in err_str) or ("owned: 0.0" in err_str)
                    if exit_res.get("success") or is_already_closed:
                        if hasattr(self.strategy_module, "record_exit"):
                            self.strategy_module.record_exit(ticker=ticker)

                        # Record trade in DailyBankingLedger if fill price returned
                        try:
                            fill_p = float(holding.get("fill_price", 0.0))
                        except (TypeError, ValueError):
                            fill_p = 0.0
                        try:
                            exit_p = float(exit_res.get("fill_price", holding.get("current_price", fill_p)))
                        except (TypeError, ValueError):
                            exit_p = fill_p
                        try:
                            qty = float(holding.get("quantity", 0.0))
                        except (TypeError, ValueError):
                            qty = 0.0
                        try:
                            fx_val = float(active_fx) if active_fx else 1.30
                        except (TypeError, ValueError):
                            fx_val = 1.30

                        is_uk_pence = (ticker.endswith("l_EQ") or ticker == "CSP1_EQ") and (ticker != "VUSAl_EQ")
                        if is_uk_pence:
                            gross_pnl_gbp = (exit_p - fill_p) * qty / 100.0
                            costs_gbp = round((qty * exit_p / 100.0) * 0.0020, 2)
                        elif ticker == "VUSAl_EQ":
                            gross_pnl_gbp = (exit_p - fill_p) * qty
                            costs_gbp = round((qty * exit_p) * 0.0020, 2)
                        else:
                            gross_pnl_usd = (exit_p - fill_p) * qty
                            gross_pnl_gbp = gross_pnl_usd / fx_val
                            costs_gbp = round((qty * exit_p / fx_val) * 0.0020, 2)

                        net_pnl_gbp = round(gross_pnl_gbp - costs_gbp, 2)

                        self.banking_ledger.record_realised_trade(
                            trade_id=f"TRADE_{ticker}_{int(time.time())}",
                            ticker=ticker,
                            gross_pnl_gbp=gross_pnl_gbp,
                            costs_gbp=costs_gbp,
                            exit_reason=exit_reason,
                            entry_price=fill_p,
                            exit_price=exit_p,
                            quantity=qty
                        )

                        if exit_reason == "PROFIT_BANK_100_EXIT":
                            summary = self.banking_ledger.get_banking_summary()
                            logger.info(
                                f"[Runner] 🎯 £100+ PROFIT BANKED! Realized £{net_pnl_gbp:+.2f} on {ticker}. "
                                f"Total Banked Today: £{summary.get('banked_net_profit_today', 0.0):.2f}. "
                                f"Capital released. Hunting for next opportunity!"
                            )

                        if ticker in self.active_holdings:
                            del self.active_holdings[ticker]

        # 3. Update total deployed capital for 80% ceiling check
        total_deployed_gbp = sum(
            float(h.get("entry_cost_gbp", 0.0)) or (
                float(h.get("quantity", 0.0)) * (
                    float(h.get("fill_price", 0.0)) / 100.0 if ((str(k).endswith("l_EQ") or k == "CSP1_EQ") and k != "VUSAl_EQ")
                    else float(h.get("fill_price", 0.0)) if k == "VUSAl_EQ"
                    else float(h.get("fill_price", 0.0)) / active_fx
                )
            )
            for k, h in self.active_holdings.items()
        )
        if hasattr(self.strategy_module, "current_deployed_capital_gbp"):
            self.strategy_module.current_deployed_capital_gbp = total_deployed_gbp
        if hasattr(self.strategy_module, "active_tickers"):
            self.strategy_module.active_tickers = set(self.active_holdings.keys())

        # 4. Strategy decides entries (injected module)
        try:
            import inspect
            try:
                sig = inspect.signature(self.strategy_module.evaluate)
                accepts_fx = "fx_gbpusd" in sig.parameters or any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
            except Exception:
                accepts_fx = True

            if accepts_fx:
                entry_decisions: List[HitAndRunEntryDecision] = self.strategy_module.evaluate(opportunities, fx_gbpusd=current_fx)
            else:
                entry_decisions: List[HitAndRunEntryDecision] = self.strategy_module.evaluate(opportunities)
        except Exception as e:
            err = f"STRATEGY_EVALUATION_ERROR: {str(e)}"
            logger.error(err)
            self.product_failures.append(err)
            return {"cycle_status": "STRATEGY_ERROR", "entries_submitted": 0, "error": err}

        executed_entries = 0
        raw_max = getattr(self.strategy_module, "MAX_CONCURRENT_POSITIONS", 1)
        try:
            max_concurrent = int(raw_max)
        except (ValueError, TypeError):
            max_concurrent = 1

        if len(self.active_holdings) < max_concurrent:
            for dec in entry_decisions:
                if len(self.active_holdings) >= max_concurrent:
                    break
                if dec.decision == "ENTER":
                    intended_cap = getattr(dec, "intended_capital_gbp", 0.0)
                    if total_deployed_gbp + intended_cap > 40000.0 and total_deployed_gbp >= 39500.0:
                        logger.info(f"[Runner] 80% capital ceiling (£40,000) reached. Holding further entries.")
                        break

                    exec_res = self.dispatcher.execute_entry(dec)
                    self.trades_log.append({
                        "type": "ENTRY",
                        "decision": dec.to_dict(),
                        "result": exec_res,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    if exec_res.get("success"):
                        executed_entries += 1
                        total_deployed_gbp += intended_cap
                        if hasattr(self.strategy_module, "record_entry"):
                            self.strategy_module.record_entry()
                        self.active_holdings[dec.instrument_id] = {
                            "ticker": dec.instrument_id,
                            "fill_price": exec_res["fill_price"],
                            "quantity": exec_res["filled_quantity"],
                            "entry_cost_gbp": getattr(dec, "intended_capital_gbp", 50.0),
                            "stop_order_id": exec_res["stop_order_id"],
                            "stop_price": exec_res["stop_price"],
                            "entry_time": exec_res["timestamp"],
                            "fx_rate": active_fx
                        }

        # Update telemetry counts
        self.securities_scanned_last_cycle = getattr(
            self.strategy_module, "last_securities_scanned", len(getattr(self.strategy_module, "FULL_VISION_UNIVERSE", []))
        )
        self.raw_candidates_last_cycle = getattr(
            self.strategy_module, "last_raw_candidates", len([d for d in entry_decisions if d.decision == "ENTER"])
        )
        self.final_approvals_last_cycle = executed_entries

        return {
            "cycle_status": "CYCLE_COMPLETED",
            "entries_evaluated": len(entry_decisions),
            "entries_submitted": executed_entries,
            "total_deployed_gbp": round(total_deployed_gbp, 2),
            "banked_profit_today_gbp": self.banking_ledger.get_banking_summary().get("banked_net_profit_today", 0.0)
        }

    def end_of_day_cleanup_and_review(self) -> Dict[str, Any]:
        """
        Phase 3: End of Day.
        Flattens active holdings, cancels open orders, and generates the Daily Review.
        """
        logger.info("[Runner] Initiating End-of-Day Cleanup and Review...")

        # 1. Flatten all active holdings
        for ticker, holding in list(self.active_holdings.items()):
            exit_res = self.dispatcher.execute_exit(
                ticker=ticker,
                quantity=holding["quantity"],
                reason="END_OF_DAY_FLATTEN"
            )
            self.trades_log.append({
                "type": "EXIT",
                "ticker": ticker,
                "result": exit_res,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            err_str = str(exit_res.get("error", ""))
            is_already_closed = ("selling-equity-not-owned" in err_str) or ("owned: 0.0" in err_str)
            if exit_res.get("success") or is_already_closed:
                if ticker in self.active_holdings:
                    del self.active_holdings[ticker]

        # 2. Reconcile final broker state
        reconcile = self.dispatcher.reconcile_broker_state()
        final_acc = broker.get_account_summary(force_refresh=True)
        raw_final = final_acc.get("raw", {})
        ending_equity = float(raw_final.get("total", self.starting_equity))
        realised_net_pnl = round(ending_equity - self.starting_equity, 2)

        # 3. Tally trade statistics
        entry_trades = [t for t in self.trades_log if t.get("type") == "ENTRY" and t.get("result", {}).get("success")]
        total_trades = len(entry_trades)

        report = {
            "EXPERIMENT_ID": self.experiment_id,
            "GIT_SHA": self.git_sha,
            "STRATEGY_VERSION": self.strategy_version,
            "STARTING_EQUITY": self.starting_equity,
            "ENDING_EQUITY": ending_equity,
            "REALISED_NET_PNL": realised_net_pnl,
            "TOTAL_TRADES": total_trades,
            "WINNERS": 0,
            "LOSERS": 0,
            "WIN_RATE": 0.0,
            "AVERAGE_WIN": 0.0,
            "AVERAGE_LOSS": 0.0,
            "BEST_TRADE": 0.0,
            "WORST_TRADE": 0.0,
            "MAX_CAPITAL_DEPLOYED": 0.0,
            "STOP_LOSS_COUNT": 0,
            "TAKE_PROFIT_COUNT": 0,
            "OTHER_EXIT_COUNT": len([t for t in self.trades_log if t.get("type") == "EXIT"]),
            "ZERO_TRADE_REASON": "AWAITING_USER_STRATEGY_AUTHORISATION" if total_trades == 0 else None,
            "PRODUCT_FAILURES": list(self.product_failures),
            "BROKER_FAILURES": [],
            "CLEANUP_SUCCESS": bool(reconcile.get("is_clean_slate", False)),
            "FINAL_OPEN_POSITIONS": int(reconcile.get("positions_count", 0)),
            "FINAL_OPEN_ORDERS": int(reconcile.get("orders_count", 0)),
            "WHAT_WORKED": "Clean pre-session validation, strict DEMO environment gating, automated flatten cleanup.",
            "WHAT_DID_NOT_WORK": "Awaiting user strategy authorization before executing market entries."
        }

        # Save audit report
        report_path = os.path.join(self.audit_log_dir, f"{self.experiment_id}_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"[Runner] Daily report saved to {report_path}")

        return report

    def reset_session_state(self) -> None:
        """Resets daily runner and strategy state cleanly for a new session."""
        logger.info(f"[Runner] Resetting session state for experiment {self.experiment_id}")
        self.starting_equity = 0.0
        self.starting_cash = 0.0
        self.trades_log.clear()
        self.active_holdings.clear()
        self.product_failures.clear()
        if self.strategy_module and hasattr(self.strategy_module, "reset_daily_state"):
            self.strategy_module.reset_daily_state()

    def is_session_ended(self, now_et: Optional[datetime] = None) -> bool:
        """Check if trading session has passed 15:45 ET."""
        from zoneinfo import ZoneInfo
        tz_ny = ZoneInfo("America/New_York")
        dt = now_et or datetime.now(tz_ny)
        return (dt.hour > 15) or (dt.hour == 15 and dt.minute >= 45)

    def run_continuous_session(
        self,
        max_iterations: Optional[int] = None,
        poll_interval: float = 10.0,
        stop_event: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Runs the persistent trading loop throughout a single session.
        startup -> continuous scan/evaluate loop -> execute entries -> monitor holdings -> evaluate exits -> continue scanning after exits -> session-end reconciliation.
        """
        logger.info(f"[Runner] Starting single session loop for {self.experiment_id}")
        self.pre_session_startup(allow_existing_positions=True)

        cycles_count = 0
        try:
            while True:
                if stop_event and stop_event.is_set():
                    logger.info("[Runner] Stop event signaled. Exiting continuous loop.")
                    break

                if self.is_session_ended():
                    logger.info("[Runner] Session end reached (>= 15:45 ET). Proceeding to EOD cleanup.")
                    break

                cycle_res = self.run_scan_and_execute_cycle([])
                cycles_count += 1
                logger.info(
                    f"[Runner] Cycle {cycles_count} completed: status={cycle_res.get('cycle_status')}, "
                    f"entries_submitted={cycle_res.get('entries_submitted')}, active_holdings={len(self.active_holdings)}"
                )

                if max_iterations is not None and cycles_count >= max_iterations:
                    logger.info(f"[Runner] Max iterations ({max_iterations}) reached.")
                    break

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("[Runner] Interrupted by user/SIGINT.")
        except Exception as e:
            logger.critical(f"[Runner Crash] Unhandled exception in persistent loop: {e}", exc_info=True)
            self.product_failures.append(f"PERSISTENT_LOOP_CRASH: {str(e)}")

        review = self.end_of_day_cleanup_and_review()
        review["cycles_completed"] = cycles_count
        return review

    def execute_demo_execution_canary(
        self,
        ticker: str = "AAPL_US_EQ",
        symbol: str = "AAPL",
        feed_ticker: str = "AAPL",
        quantity: float = 0.19
    ) -> Dict[str, Any]:
        """
        User-authorised DEMO_EXECUTION_CANARY for Trading212 PRACTICE account.
        Visibly exercises the broker execution lifecycle:
        BUY -> FILL -> PROTECTIVE STOP -> STOP VERIFICATION -> EXIT -> FLAT RECONCILIATION.
        Clearly labelled: DEMO_EXECUTION_CANARY (NOT strategy performance evidence).
        """
        logger.info(f"[Canary] Starting DEMO_EXECUTION_CANARY for {ticker} (qty={quantity})")
        env = getattr(self.dispatcher.broker, "env", "") or getattr(settings, "TRADING_ENV", "")
        if str(env).lower() != "demo":
            raise RuntimeError("CRITICAL_SAFETY_HALT: DEMO_EXECUTION_CANARY requested in non-DEMO environment.")

        # 1. Construct entry decision
        canary_decision = HitAndRunEntryDecision(
            decision="ENTER",
            instrument_id=ticker,
            symbol=symbol,
            feed_ticker=feed_ticker,
            intended_capital_gbp=50.0,
            intended_quantity=quantity,
            required_protective_level=1.0,
            thesis="DEMO_EXECUTION_CANARY: Explicit user authority to verify practice broker execution path."
        )
        canary_decision.planned_loss_pct = 0.02

        # 2. Submit BUY order, poll for fill, place protective stop, verify stop order
        entry_res = self.dispatcher.execute_entry(canary_decision)
        if not entry_res.get("success"):
            logger.error(f"[Canary] Entry submission failed: {entry_res}")
            canary_log = {
                "type": "DEMO_EXECUTION_CANARY",
                "label": "DEMO_EXECUTION_CANARY",
                "status": "ENTRY_FAILED",
                "entry_result": entry_res,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.trades_log.append(canary_log)
            return canary_log

        fill_price = entry_res.get("fill_price")
        filled_qty = entry_res.get("filled_quantity", quantity)
        stop_id = entry_res.get("stop_order_id")
        stop_price = entry_res.get("stop_price")
        logger.info(f"[Canary] Entry filled @ {fill_price}, protective stop confirmed #{stop_id} @ {stop_price}")

        # 3. Short dwell to confirm stop book visibility
        time.sleep(2.0)

        # 4. Execute EXIT: cancel protective stop, submit market sell, confirm fill
        exit_res = self.dispatcher.execute_exit(
            ticker=ticker,
            quantity=filled_qty,
            reason="DEMO_EXECUTION_CANARY_FLATTEN"
        )
        logger.info(f"[Canary] Exit executed: {exit_res}")

        # 5. Flat reconciliation
        reconcile = self.dispatcher.reconcile_broker_state()
        canary_log = {
            "type": "DEMO_EXECUTION_CANARY",
            "label": "DEMO_EXECUTION_CANARY",
            "status": "COMPLETED" if (exit_res.get("success") and reconcile.get("is_clean_slate")) else "PARTIAL",
            "entry_result": entry_res,
            "exit_result": exit_res,
            "reconciliation": reconcile,
            "is_clean_slate": reconcile.get("is_clean_slate", False),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self.trades_log.append(canary_log)
        logger.info(f"[Canary] DEMO_EXECUTION_CANARY completed. Clean slate: {reconcile.get('is_clean_slate')}")
        return canary_log

    def run_multi_session_worker(
        self,
        poll_interval: float = 10.0,
        stop_event: Optional[Any] = None,
        max_sessions: Optional[int] = None
    ) -> None:
        """
        Persistent multi-session runner designed for long-running service environments (e.g. Render).
        Survives across multiple market sessions:
        1. Intraday (Mon-Fri 09:45-15:45 ET): runs pre-session startup on session open and scans/executes.
        2. Post-session (Mon-Fri >= 15:45 ET): executes EOD flatten, cancels open stops, and writes daily review.
        3. Overnight / Weekend: sleeps without process termination.
        4. Next trading day: automatically resets daily state cleanly and resumes new session at 09:45 ET.
        """
        from zoneinfo import ZoneInfo
        tz_ny = ZoneInfo("America/New_York")
        logger.info(f"[Runner] Starting multi-session persistent worker for {self.experiment_id} (SHA: {self.git_sha})")

        active_session_date = None
        completed_eod_dates = set()
        sessions_completed = 0

        while True:
            if stop_event and stop_event.is_set():
                logger.info("[Runner] Stop event signaled. Multi-session worker stopping.")
                break

            now_lon = datetime.now(ZoneInfo("Europe/London"))
            now_et = datetime.now(tz_ny)
            today = now_lon.date()
            is_weekday = (now_lon.weekday() < 5)  # 0=Mon, 4=Fri
            t_lon = now_lon.time()

            # Continuous fishing cycle: 08:00 London (UK open) through 21:00 London (16:00 ET US close)
            # No time limits applied during open market hours!
            start_lon = datetime.strptime("08:00:00", "%H:%M:%S").time()
            cutoff_lon = datetime.strptime("21:00:00", "%H:%M:%S").time()

            in_session = is_weekday and (start_lon <= t_lon < cutoff_lon)
            past_eod = is_weekday and (t_lon >= cutoff_lon)

            if in_session:
                # 1. Start new session if not started for today
                if active_session_date != today:
                    logger.info(f"[Multi-Session Worker] New trading session opening: {today} {t_lon.strftime('%H:%M:%S')} London time")
                    self.reset_session_state()
                    try:
                        self.pre_session_startup(allow_existing_positions=True)
                        active_session_date = today
                    except Exception as e:
                        logger.error(f"[Multi-Session Worker] Pre-session startup failed for {today}: {e}")
                        time.sleep(poll_interval)
                        continue

                # 2. Run DEMO canary if armed and not yet run for today
                if self.canary_armed and today not in self.canary_executed_dates:
                    try:
                        is_uk_session = (t_lon < datetime.strptime("14:30:00", "%H:%M:%S").time())
                        canary_ticker = "CSP1_EQ" if is_uk_session else "AAPL_US_EQ"
                        canary_sym = "CSP1" if is_uk_session else "AAPL"
                        canary_qty = 1.0 if is_uk_session else 0.19
                        logger.info(f"[Multi-Session Worker] Executing authorised DEMO_EXECUTION_CANARY for {today} on {canary_ticker}...")
                        canary_res = self.execute_demo_execution_canary(ticker=canary_ticker, symbol=canary_sym, feed_ticker=canary_sym, quantity=canary_qty)
                        self.canary_executed_dates.add(today)
                        logger.info(f"[Multi-Session Worker] DEMO Canary status: {canary_res.get('status')}")
                    except Exception as ce:
                        logger.error(f"[Multi-Session Worker] DEMO Canary execution error: {ce}", exc_info=True)

                # 3. Run scan and execute cycle
                try:
                    cycle_res = self.run_scan_and_execute_cycle([])
                    logger.info(
                        f"[Multi-Session Worker] Cycle completed: status={cycle_res.get('cycle_status')}, "
                        f"entries={cycle_res.get('entries_submitted')}, holdings={len(self.active_holdings)}"
                    )
                except Exception as e:
                    logger.error(f"[Multi-Session Worker] Cycle error: {e}", exc_info=True)

                time.sleep(poll_interval)

            elif past_eod:
                # EOD reached: perform cleanup once per day
                if active_session_date == today and today not in completed_eod_dates:
                    logger.info(f"[Multi-Session Worker] EOD reached (>= 15:45 ET). Performing flatten and review for {today}...")
                    try:
                        review = self.end_of_day_cleanup_and_review()
                        completed_eod_dates.add(today)
                        sessions_completed += 1
                        logger.info(f"[Multi-Session Worker] Session {sessions_completed} review complete: Net PnL: {review.get('REALISED_NET_PNL')}")
                    except Exception as e:
                        logger.error(f"[Multi-Session Worker] EOD cleanup error: {e}", exc_info=True)

                    if max_sessions is not None and sessions_completed >= max_sessions:
                        logger.info(f"[Multi-Session Worker] Target max sessions ({max_sessions}) completed. Worker exiting.")
                        break

                time.sleep(poll_interval)

            else:
                # Outside session hours (pre-market or weekend): sleep until next session
                time.sleep(poll_interval)


if __name__ == "__main__":
    from src.hit_and_run.demo_strategy_v1 import demo_strategy_v1
    runner = DemoExperimentRunner(
        experiment_id="EXP-DEMO-001",
        strategy_version="1.0-DEMO",
        strategy_module=demo_strategy_v1
    )
    review = runner.run_continuous_session(poll_interval=10.0)
    print("SESSION COMPLETE. REVIEW REPORT:", json.dumps(review, indent=2))

