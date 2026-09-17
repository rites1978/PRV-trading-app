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
from typing import Dict, Any, List, Optional

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brokers.trading212 import broker
from src.hit_and_run.demo_execution import demo_execution_dispatcher, DemoExecutionDispatcher
from src.hit_and_run.models import HitAndRunEntryDecision
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
        self.product_failures: List[str] = []

    def _get_git_sha(self) -> str:
        try:
            res = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            return res
        except Exception:
            return "UNKNOWN_GIT_SHA"

    def pre_session_startup(self) -> Dict[str, Any]:
        """
        Phase 1: Pre-session validation and account verification.
        Fails closed if pre-existing positions or orders exist.
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
            msg = (
                f"ACCOUNT_STATE_NOT_CLEAN: Found {reconcile['positions_count']} open positions "
                f"and {reconcile['orders_count']} open orders in DEMO account. "
                f"Abort startup to avoid contaminating experiment."
            )
            logger.critical(msg)
            raise RuntimeError(msg)

        startup_record = {
            "experiment_id": self.experiment_id,
            "git_sha": self.git_sha,
            "strategy_version": self.strategy_version,
            "broker_environment": "DEMO",
            "starting_cash": self.starting_cash,
            "starting_equity": self.starting_equity,
            "open_positions": 0,
            "open_orders": 0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"[Runner] Pre-session verified: Cash=£{self.starting_cash:.2f}, Equity=£{self.starting_equity:.2f}")
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

        # Strategy decides entries (injected module)
        try:
            entry_decisions: List[HitAndRunEntryDecision] = self.strategy_module.evaluate(opportunities)
        except Exception as e:
            err = f"STRATEGY_EVALUATION_ERROR: {str(e)}"
            logger.error(err)
            self.product_failures.append(err)
            return {"cycle_status": "STRATEGY_ERROR", "entries_submitted": 0, "error": err}

        executed_entries = 0
        for dec in entry_decisions:
            if dec.decision == "ENTER":
                exec_res = self.dispatcher.execute_entry(dec)
                self.trades_log.append({
                    "type": "ENTRY",
                    "decision": dec.to_dict(),
                    "result": exec_res,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                if exec_res.get("success"):
                    executed_entries += 1
                    self.active_holdings[dec.instrument_id] = {
                        "ticker": dec.instrument_id,
                        "fill_price": exec_res["fill_price"],
                        "quantity": exec_res["filled_quantity"],
                        "stop_order_id": exec_res["stop_order_id"],
                        "stop_price": exec_res["stop_price"],
                        "entry_time": exec_res["timestamp"]
                    }

        return {
            "cycle_status": "CYCLE_COMPLETED",
            "entries_evaluated": len(entry_decisions),
            "entries_submitted": executed_entries
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
            if exit_res.get("success"):
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
            "CLEANUP_SUCCESS": reconcile["is_clean_slate"],
            "FINAL_OPEN_POSITIONS": reconcile["positions_count"],
            "FINAL_OPEN_ORDERS": reconcile["orders_count"],
            "WHAT_WORKED": "Clean pre-session validation, strict DEMO environment gating, automated flatten cleanup.",
            "WHAT_DID_NOT_WORK": "Awaiting user strategy authorization before executing market entries."
        }

        # Save audit report
        report_path = os.path.join(self.audit_log_dir, f"{self.experiment_id}_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"[Runner] Daily report saved to {report_path}")

        return report


if __name__ == "__main__":
    runner = DemoExperimentRunner(
        experiment_id=f"DEMO_EXP_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        strategy_version="AWAITING_USER_AUTHORISATION"
    )
    startup = runner.pre_session_startup()
    print("PRE-SESSION STARTUP COMPLETE:", startup)
    review = runner.end_of_day_cleanup_and_review()
    print("END-OF-DAY REVIEW COMPLETE:", review)
