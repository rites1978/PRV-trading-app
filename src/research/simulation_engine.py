"""
🏛️ PRV CAPITAL | MASTER HISTORICAL RESEARCH SIMULATION ENGINE
Deterministic, point-in-time institutional simulation laboratory.

Core Architecture:
- Strict monotonic chronological replay (ReplayClock)
- Zero look-ahead information firewall (PointInTimeBoundary)
- Official versioned transaction costs (CostScheduleRepository)
- Realistic next-bar fill simulator (ExecutionSimulator)
- Strict double-entry cash and position accounting (PortfolioLedger)
- Cryptographic out-of-sample isolation (OOSSealer)
- Zero connection to live / practice broker endpoints
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Any, Callable
import pandas as pd
import numpy as np
import logging

from src.research.clock import ReplayClock
from src.research.pit_boundary import PointInTimeBoundary, LookAheadViolationError
from src.research.cost_schedule import CostScheduleRepository, Jurisdiction, InstrumentClass
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType, Fill
from src.research.portfolio_ledger import PortfolioLedger, ClosedTrade, LedgerDiscrepancyError
from src.research.oos_sealer import OOSSealer

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    simulation_id: str
    strategy_name: str
    start_date: str
    end_date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_pnl_gbp: float
    total_friction_gbp: float
    net_pnl_gbp: float
    initial_capital_gbp: float
    final_nav_gbp: float
    total_return_pct: float
    max_drawdown_gbp: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    closed_trades: List[ClosedTrade]
    ledger_hash: str                  # SHA-256 hash for byte-for-byte reproducibility
    reconciliation_verified: bool
    lookahead_audit_passed: bool


class SimulationEngine:
    """
    Authoritative simulation harness executing deterministic backtests.
    """
    def __init__(
        self,
        initial_capital_gbp: float = 50000.0,
        cost_repo: Optional[CostScheduleRepository] = None
    ):
        self.initial_capital_gbp = initial_capital_gbp
        self.cost_repo = cost_repo or CostScheduleRepository()
        self.execution_sim = ExecutionSimulator(self.cost_repo)
        self.pit_boundary = PointInTimeBoundary()
        self.oos_sealer = OOSSealer()

    def run_strategy(
        self,
        strategy_name: str,
        timeline: List[pd.Timestamp],
        universe_symbols: List[str],
        strategy_decision_callback: Callable[[pd.Timestamp, PointInTimeBoundary, PortfolioLedger, ExecutionSimulator], None],
        symbol_bars_map: Dict[str, pd.DataFrame]
    ) -> SimulationResult:
        """
        Executes a deterministic simulation step-by-step through timeline.
        Enforces strict point-in-time boundaries and double-entry ledger reconciliation.
        """
        # Register all market data with the PIT boundary
        for sym, df in symbol_bars_map.items():
            self.pit_boundary.register_market_data(sym, df)

        clock = ReplayClock(timeline)
        ledger = PortfolioLedger(self.initial_capital_gbp, start_timestamp=timeline[0])

        daily_nav_history = []
        lookahead_audit_passed = True

        while not clock.is_completed:
            current_t = clock.current_time

            # Update mark-to-market prices for open positions at current_time
            current_prices = {}
            for sym in ledger.positions.keys():
                bar = self.pit_boundary.get_latest_bar(sym, current_t)
                if bar is not None:
                    current_prices[sym] = float(bar["Close"])
            ledger.mark_to_market(current_prices)
            daily_nav_history.append(ledger.get_portfolio_nav())

            # Strategy receives current_time and queries through pit_boundary
            try:
                strategy_decision_callback(current_t, self.pit_boundary, ledger, self.execution_sim)
            except LookAheadViolationError as e:
                logger.error(f"Lookahead violation detected: {e}")
                lookahead_audit_passed = False
                raise

            clock.advance()

        # Final reconciliation check
        ledger.reconcile()

        trades = ledger.closed_trades
        wins = [t for t in trades if t.net_pnl_gbp > 0]
        losses = [t for t in trades if t.net_pnl_gbp <= 0]
        gross_pnl = sum(t.gross_pnl_gbp for t in trades)
        total_friction = sum(t.total_friction_gbp for t in trades)
        net_pnl = sum(t.net_pnl_gbp for t in trades)
        final_nav = ledger.get_portfolio_nav()
        total_return_pct = round(((final_nav - self.initial_capital_gbp) / self.initial_capital_gbp) * 100, 2)

        # Drawdown
        nav_series = pd.Series(daily_nav_history)
        peak = nav_series.cummax()
        dd = (nav_series - peak) / (peak + 1e-8)
        max_dd_pct = round(abs(float(dd.min())) * 100, 2)
        max_dd_gbp = round(abs(float((nav_series - peak).min())), 2)

        # Sharpe
        returns = nav_series.pct_change().dropna()
        sharpe = round(float(np.sqrt(252) * returns.mean() / (returns.std() + 1e-8)), 2) if len(returns) > 1 else 0.0

        # Profit Factor
        total_gains = sum(t.net_pnl_gbp for t in wins)
        total_losses_abs = abs(sum(t.net_pnl_gbp for t in losses))
        profit_factor = round(total_gains / total_losses_abs, 2) if total_losses_abs > 0 else (99.0 if total_gains > 0 else 0.0)

        # Compute deterministic hash of the transaction ledger
        hasher = hashlib.sha256()
        for e in ledger.ledger_entries:
            hasher.update(f"{e.entry_id}_{e.timestamp}_{e.entry_type}_{e.symbol}_{e.debit_gbp}_{e.credit_gbp}_{e.cash_balance_after}".encode("utf-8"))
        ledger_hash = hasher.hexdigest()

        return SimulationResult(
            simulation_id=f"SIM_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{strategy_name}",
            strategy_name=strategy_name,
            start_date=str(timeline[0])[:10],
            end_date=str(timeline[-1])[:10],
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=round((len(wins) / len(trades)) * 100, 1) if trades else 0.0,
            gross_pnl_gbp=round(gross_pnl, 2),
            total_friction_gbp=round(total_friction, 2),
            net_pnl_gbp=round(net_pnl, 2),
            initial_capital_gbp=self.initial_capital_gbp,
            final_nav_gbp=final_nav,
            total_return_pct=total_return_pct,
            max_drawdown_gbp=max_dd_gbp,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            closed_trades=trades,
            ledger_hash=ledger_hash,
            reconciliation_verified=True,
            lookahead_audit_passed=lookahead_audit_passed
        )
