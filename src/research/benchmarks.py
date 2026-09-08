"""
🏛️ PRV CAPITAL | BENCHMARK & CONTROL FRAMEWORK
Establishes mandatory simple baseline strategies evaluated under the identical
simulation clock, execution engine, and versioned cost schedules.

Invariants:
1. Any proposed alpha strategy MUST demonstrate statistically significant
   incremental value over these simple controls.
2. All benchmarks incur the exact same broker, tax, FX, and spread frictions.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
from src.research.cost_schedule import Jurisdiction, InstrumentClass
from src.research.execution_simulator import ExecutionSimulator, Order, OrderSide, OrderType
from src.research.portfolio_ledger import PortfolioLedger


@dataclass
class BenchmarkResult:
    benchmark_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_pnl_gbp: float
    total_friction_gbp: float
    net_pnl_gbp: float
    final_nav_gbp: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float


class BenchmarkEvaluator:
    """
    Evaluates standardized baseline controls against a set of bars.
    """
    def __init__(
        self,
        execution_sim: ExecutionSimulator,
        initial_capital_gbp: float = 50000.0
    ):
        self.sim = execution_sim
        self.initial_capital = initial_capital_gbp

    def run_cash_benchmark(self, timeline: List[pd.Timestamp]) -> BenchmarkResult:
        """Control 1: 100% Cash / No-Trade Baseline."""
        return BenchmarkResult(
            benchmark_name="CASH_BASELINE",
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate_pct=0.0,
            gross_pnl_gbp=0.0,
            total_friction_gbp=0.0,
            net_pnl_gbp=0.0,
            final_nav_gbp=self.initial_capital,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0
        )

    def run_passive_buy_and_hold(
        self,
        symbol: str,
        df: pd.DataFrame,
        jurisdiction: Jurisdiction = Jurisdiction.UK,
        instrument_class: InstrumentClass = InstrumentClass.ETF
    ) -> BenchmarkResult:
        """
        Control 2: Passive Buy-and-Hold ETF.
        Buys on bar 1, sells on the final bar.
        Incurs actual versioned entry and exit frictions.
        """
        if len(df) < 2:
            return self.run_cash_benchmark([])

        ledger = PortfolioLedger(self.initial_capital)
        entry_bar = df.iloc[0]
        entry_time = df.index[0]
        entry_price = float(entry_bar["Open"])

        # Size 95% of capital
        deploy_gbp = self.initial_capital * 0.95
        shares = round(deploy_gbp / entry_price, 4)

        # Open position using simulator
        buy_order = Order(
            order_id="BND_BUY_001",
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=shares,
            created_at=entry_time,
            jurisdiction=jurisdiction,
            instrument_class=instrument_class
        )
        fill_buy = self.sim.simulate_fill(buy_order, entry_bar, entry_time)
        if not fill_buy:
            return self.run_cash_benchmark([])

        ledger.open_position(
            timestamp=entry_time,
            symbol=symbol,
            jurisdiction=jurisdiction.value,
            instrument_class=instrument_class.value,
            shares=fill_buy.quantity,
            price_gbp=fill_buy.fill_price_gbp,
            itemized_entry_frictions=fill_buy.itemized_frictions
        )

        # Track daily equity for drawdown
        daily_navs = []
        for dt, bar in df.iterrows():
            p = float(bar["Close"])
            ledger.mark_to_market({symbol: p})
            daily_navs.append(ledger.get_portfolio_nav())

        # Exit on final bar
        exit_bar = df.iloc[-1]
        exit_time = df.index[-1]
        sell_order = Order(
            order_id="BND_SELL_001",
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=shares,
            created_at=exit_time,
            jurisdiction=jurisdiction,
            instrument_class=instrument_class
        )
        fill_sell = self.sim.simulate_fill(sell_order, exit_bar, exit_time)
        closed_trade = ledger.close_position(
            timestamp=exit_time,
            symbol=symbol,
            price_gbp=fill_sell.fill_price_gbp,
            itemized_exit_frictions=fill_sell.itemized_frictions,
            exit_reason="BENCHMARK_SIMULATION_END"
        )
        ledger.reconcile()

        final_nav = ledger.get_portfolio_nav()
        total_return_pct = round(((final_nav - self.initial_capital) / self.initial_capital) * 100, 2)

        # Drawdown calculation
        nav_series = pd.Series(daily_navs)
        peak = nav_series.cummax()
        dd = (nav_series - peak) / peak
        max_dd_pct = round(abs(float(dd.min())) * 100, 2)

        # Sharpe calculation
        returns = nav_series.pct_change().dropna()
        sharpe = round(float(np.sqrt(252) * returns.mean() / (returns.std() + 1e-8)), 2) if len(returns) > 1 else 0.0

        return BenchmarkResult(
            benchmark_name=f"PASSIVE_BUY_HOLD_{symbol}",
            total_trades=1,
            winning_trades=1 if closed_trade.net_pnl_gbp > 0 else 0,
            losing_trades=1 if closed_trade.net_pnl_gbp <= 0 else 0,
            win_rate_pct=100.0 if closed_trade.net_pnl_gbp > 0 else 0.0,
            gross_pnl_gbp=closed_trade.gross_pnl_gbp,
            total_friction_gbp=closed_trade.total_friction_gbp,
            net_pnl_gbp=closed_trade.net_pnl_gbp,
            final_nav_gbp=final_nav,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe
        )

    def run_simple_trend_control(
        self,
        symbol: str,
        df: pd.DataFrame,
        ma_period: int = 20,
        position_size_gbp: float = 25000.0,
        target_pct: float = 0.015,
        stop_pct: float = 0.010,
        jurisdiction: Jurisdiction = Jurisdiction.US,
        instrument_class: InstrumentClass = InstrumentClass.EQUITY
    ) -> BenchmarkResult:
        """
        Control 3: Simple 20-period Moving Average Breakout without AI.
        Long when Close crosses above MA20. Exits on target, stop, or Close < MA20.
        """
        if len(df) <= ma_period + 2:
            return self.run_cash_benchmark([])

        ledger = PortfolioLedger(self.initial_capital)
        df = df.copy()
        df["MA"] = df["Close"].rolling(ma_period).mean()

        in_position = False
        target_p = 0.0
        stop_p = 0.0
        shares = 0.0

        daily_navs = []

        for i in range(ma_period + 1, len(df)):
            prev_bar = df.iloc[i - 1]
            curr_bar = df.iloc[i]
            curr_time = df.index[i]
            close_p = float(curr_bar["Close"])
            high_p = float(curr_bar["High"])
            low_p = float(curr_bar["Low"])

            if in_position:
                ledger.mark_to_market({symbol: close_p})
                daily_navs.append(ledger.get_portfolio_nav())

                # Check exit
                exit_reason = None
                exit_price = close_p
                if high_p >= target_p:
                    exit_reason = "TARGET"
                    exit_price = target_p
                elif low_p <= stop_p:
                    exit_reason = "STOP"
                    exit_price = stop_p
                elif close_p < float(curr_bar["MA"]):
                    exit_reason = "MA_CROSS_EXIT"
                    exit_price = close_p

                if exit_reason:
                    sell_order = Order(
                        order_id=f"CTRL_SELL_{len(ledger.closed_trades)+1}",
                        symbol=symbol,
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        quantity=shares,
                        created_at=curr_time,
                        jurisdiction=jurisdiction,
                        instrument_class=instrument_class
                    )
                    fill_sell = self.sim.simulate_fill(sell_order, curr_bar, curr_time)
                    ledger.close_position(
                        timestamp=curr_time,
                        symbol=symbol,
                        price_gbp=fill_sell.fill_price_gbp,
                        itemized_exit_frictions=fill_sell.itemized_frictions,
                        exit_reason=exit_reason
                    )
                    in_position = False

            else:
                daily_navs.append(ledger.get_portfolio_nav())
                # Check entry: Close crosses above MA
                if float(prev_bar["Close"]) <= float(prev_bar["MA"]) and float(curr_bar["Close"]) > float(curr_bar["MA"]):
                    # Enter on next bar
                    shares = round(position_size_gbp / close_p, 4)
                    buy_order = Order(
                        order_id=f"CTRL_BUY_{len(ledger.closed_trades)+1}",
                        symbol=symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=shares,
                        created_at=curr_time,
                        jurisdiction=jurisdiction,
                        instrument_class=instrument_class
                    )
                    fill_buy = self.sim.simulate_fill(buy_order, curr_bar, curr_time)
                    if fill_buy and fill_buy.notional_gbp <= ledger.cash_gbp:
                        ledger.open_position(
                            timestamp=curr_time,
                            symbol=symbol,
                            jurisdiction=jurisdiction.value,
                            instrument_class=instrument_class.value,
                            shares=fill_buy.quantity,
                            price_gbp=fill_buy.fill_price_gbp,
                            itemized_entry_frictions=fill_buy.itemized_frictions
                        )
                        in_position = True
                        target_p = close_p * (1.0 + target_pct)
                        stop_p = close_p * (1.0 - stop_pct)

        # Close any lingering position at end
        if in_position:
            last_bar = df.iloc[-1]
            last_time = df.index[-1]
            sell_order = Order(
                order_id=f"CTRL_SELL_{len(ledger.closed_trades)+1}",
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=shares,
                created_at=last_time,
                jurisdiction=jurisdiction,
                instrument_class=instrument_class
            )
            fill_sell = self.sim.simulate_fill(sell_order, last_bar, last_time)
            ledger.close_position(
                timestamp=last_time,
                symbol=symbol,
                price_gbp=fill_sell.fill_price_gbp,
                itemized_exit_frictions=fill_sell.itemized_frictions,
                exit_reason="SIMULATION_END"
            )

        ledger.reconcile()

        trades = ledger.closed_trades
        wins = [t for t in trades if t.net_pnl_gbp > 0]
        losses = [t for t in trades if t.net_pnl_gbp <= 0]
        gross_pnl = sum(t.gross_pnl_gbp for t in trades)
        total_friction = sum(t.total_friction_gbp for t in trades)
        net_pnl = sum(t.net_pnl_gbp for t in trades)
        final_nav = ledger.get_portfolio_nav()
        total_return_pct = round(((final_nav - self.initial_capital) / self.initial_capital) * 100, 2)

        nav_series = pd.Series(daily_navs)
        peak = nav_series.cummax()
        dd = (nav_series - peak) / (peak + 1e-8)
        max_dd_pct = round(abs(float(dd.min())) * 100, 2)

        returns = nav_series.pct_change().dropna()
        sharpe = round(float(np.sqrt(252) * returns.mean() / (returns.std() + 1e-8)), 2) if len(returns) > 1 else 0.0

        return BenchmarkResult(
            benchmark_name=f"SIMPLE_TREND_MA{ma_period}_{symbol}",
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=round((len(wins) / len(trades)) * 100, 1) if trades else 0.0,
            gross_pnl_gbp=round(gross_pnl, 2),
            total_friction_gbp=round(total_friction, 2),
            net_pnl_gbp=round(net_pnl, 2),
            final_nav_gbp=final_nav,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe
        )
