"""
🏛️ PRV CAPITAL | AUTHORITATIVE HISTORICAL SIMULATION & RESEARCH HARNESS
Institutional-grade, point-in-time backtesting engine with realistic broker execution:
- 0.50% UK SDRT on UK equity purchases
- 0.15% FX conversion fee on non-GBP trades
- Asset-specific bid/ask spreads (LSE 8 bps, US 4 bps)
- Execution slippage (3 bps)
- True portfolio cash accounting (£50,000 base)
- Position sizing & maximum concurrent position constraints
- Zero synthetic statistics: All metrics derive strictly from simulated transaction ledgers.
"""
import math
import numpy as np
import pandas as pd
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple, Callable


class BacktestFrictions:
    """Explicit transaction cost and friction parameters."""
    def __init__(
        self,
        uk_sdrt_pct: float = 0.50,      # 0.50% UK SDRT
        fx_fee_pct: float = 0.15,       # 0.15% Trading212 FX fee on foreign trades
        uk_spread_bps: float = 8.0,     # 8 bps LSE average bid/ask spread
        us_spread_bps: float = 4.0,     # 4 bps US average bid/ask spread
        slippage_bps: float = 3.0,      # 3 bps market impact / execution slippage
        cost_multiplier: float = 1.0    # Sensitivity multiplier (e.g. 1.25 for +25%, 1.50 for +50%)
    ):
        self.uk_sdrt_pct = uk_sdrt_pct * cost_multiplier
        self.fx_fee_pct = fx_fee_pct * cost_multiplier
        self.uk_spread_bps = uk_spread_bps * cost_multiplier
        self.us_spread_bps = us_spread_bps * cost_multiplier
        self.slippage_bps = slippage_bps * cost_multiplier


class SimulatedTrade:
    """Individual trade record within the transaction ledger."""
    def __init__(
        self,
        symbol: str,
        yf_ticker: str,
        country: str,
        entry_date: pd.Timestamp,
        entry_price: float,
        quantity: float,
        entry_notional: float,
        sdrt_fee: float,
        entry_fx_fee: float,
        entry_spread_cost: float,
        entry_slippage_cost: float,
        stop_price: float = 0.0,
        target_price: float = 0.0
    ):
        self.symbol = symbol
        self.yf_ticker = yf_ticker
        self.country = country
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.quantity = quantity
        self.entry_notional = entry_notional
        self.sdrt_fee = sdrt_fee
        self.entry_fx_fee = entry_fx_fee
        self.entry_spread_cost = entry_spread_cost
        self.entry_slippage_cost = entry_slippage_cost
        self.stop_price = stop_price
        self.target_price = target_price
        
        # Exit fields
        self.exit_date: Optional[pd.Timestamp] = None
        self.exit_price: float = 0.0
        self.exit_notional: float = 0.0
        self.exit_fx_fee: float = 0.0
        self.exit_spread_cost: float = 0.0
        self.exit_slippage_cost: float = 0.0
        self.gross_pnl: float = 0.0
        self.total_friction: float = 0.0
        self.net_pnl: float = 0.0
        self.exit_reason: str = ""
        self.holding_days: int = 0
        self.peak_price: float = entry_price

    def close(
        self,
        exit_date: pd.Timestamp,
        exit_price: float,
        exit_reason: str,
        frictions: BacktestFrictions
    ):
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.exit_notional = round(self.quantity * exit_price, 2)
        
        is_uk = (self.country.upper() == "UK")
        spread_bps = frictions.uk_spread_bps if is_uk else frictions.us_spread_bps
        
        self.exit_spread_cost = round(self.exit_notional * (spread_bps / 10000.0) / 2.0, 2)
        self.exit_slippage_cost = round(self.exit_notional * (frictions.slippage_bps / 10000.0), 2)
        self.exit_fx_fee = round(self.exit_notional * (frictions.fx_fee_pct / 100.0), 2) if not is_uk else 0.0
        
        self.gross_pnl = round(self.exit_notional - self.entry_notional, 2)
        self.total_friction = round(
            self.sdrt_fee + self.entry_fx_fee + self.entry_spread_cost + self.entry_slippage_cost +
            self.exit_fx_fee + self.exit_spread_cost + self.exit_slippage_cost,
            2
        )
        self.net_pnl = round(self.gross_pnl - self.total_friction, 2)
        self.exit_reason = exit_reason
        self.holding_days = max(1, (exit_date - self.entry_date).days)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "country": self.country,
            "entry_date": str(self.entry_date)[:10],
            "exit_date": str(self.exit_date)[:10] if self.exit_date else "",
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "entry_notional": self.entry_notional,
            "exit_notional": self.exit_notional,
            "gross_pnl": self.gross_pnl,
            "sdrt_fee": self.sdrt_fee,
            "fx_fee": round(self.entry_fx_fee + self.exit_fx_fee, 2),
            "spread_slippage_cost": round(self.entry_spread_cost + self.entry_slippage_cost + self.exit_spread_cost + self.exit_slippage_cost, 2),
            "total_friction": self.total_friction,
            "net_pnl": self.net_pnl,
            "net_return_pct": round((self.net_pnl / max(1.0, self.entry_notional)) * 100.0, 3),
            "holding_days": self.holding_days,
            "exit_reason": self.exit_reason
        }


class BacktestEngine:
    """Authoritative historical simulation engine."""
    def __init__(
        self,
        starting_nav: float = 50000.00,
        max_positions: int = 15,
        min_cash_buffer_pct: float = 0.05,
        frictions: Optional[BacktestFrictions] = None,
        execution_lag_days: int = 0
    ):
        self.starting_nav = starting_nav
        self.max_positions = max_positions
        self.min_cash_buffer_pct = min_cash_buffer_pct
        self.frictions = frictions or BacktestFrictions()
        self.execution_lag_days = execution_lag_days

    def run_simulation(
        self,
        bars_data: Dict[str, pd.DataFrame],
        strategy_logic_fn: Callable,
        start_date: str,
        end_date: str,
        benchmark_bars: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """
        Executes an authoritative chronological portfolio simulation.
        Step-by-step:
        1. Form aligned calendar across all active instruments.
        2. On each date:
           a. Mark open positions to market, check stops/targets/exits.
           b. Generate candidate signals from strategy_logic_fn.
           c. Apply execution lag (if configured).
           d. Execute entries subject to cash buffer and max positions.
           e. Record daily portfolio NAV, cash, invested, and closed transactions.
        """
        # 1. Build common trading calendar
        all_dates = set()
        for df in bars_data.values():
            if not df.empty:
                idx = df.loc[start_date:end_date].index
                all_dates.update(idx)
        
        calendar = sorted(list(all_dates))
        if not calendar:
            return {"error": "Empty trading calendar for date range"}

        cash = self.starting_nav
        open_trades: Dict[str, SimulatedTrade] = {}
        closed_trades: List[SimulatedTrade] = []
        daily_nav_history: List[Dict[str, Any]] = []
        pending_orders: List[Dict[str, Any]] = []

        total_sdrt_paid = 0.0
        total_fx_paid = 0.0
        total_spread_slippage = 0.0
        total_turnover = 0.0

        for current_idx, current_dt in enumerate(calendar):
            current_date_str = str(current_dt)[:10]

            # 2a. Execute any pending orders from lag
            remaining_pending = []
            for order in pending_orders:
                if order["execute_on_idx"] <= current_idx:
                    sym = order["symbol"]
                    yf_tick = order["yf_ticker"]
                    df = bars_data.get(yf_tick)
                    if df is not None and current_dt in df.index:
                        # Enter at open or close of current bar
                        bar = df.loc[current_dt]
                        open_p = float(bar.get("Open", bar.get("Close")))
                        if open_p > 0 and sym not in open_trades and len(open_trades) < self.max_positions:
                            # Sizing check
                            alloc_target = min(order["target_capital"], cash - (self.starting_nav * self.min_cash_buffer_pct))
                            if alloc_target >= 100.0:
                                is_uk = (order["country"].upper() == "UK")
                                spread_bps = self.frictions.uk_spread_bps if is_uk else self.frictions.us_spread_bps
                                
                                # Buying friction
                                sdrt = round(alloc_target * (self.frictions.uk_sdrt_pct / 100.0), 2) if is_uk else 0.0
                                fx_fee = round(alloc_target * (self.frictions.fx_fee_pct / 100.0), 2) if not is_uk else 0.0
                                spread_cost = round(alloc_target * (spread_bps / 10000.0) / 2.0, 2)
                                slippage = round(alloc_target * (self.frictions.slippage_bps / 10000.0), 2)
                                
                                total_entry_fric = sdrt + fx_fee + spread_cost + slippage
                                net_alloc = alloc_target - total_entry_fric
                                qty = net_alloc / open_p
                                
                                trade = SimulatedTrade(
                                    symbol=sym,
                                    yf_ticker=yf_tick,
                                    country=order["country"],
                                    entry_date=current_dt,
                                    entry_price=open_p,
                                    quantity=qty,
                                    entry_notional=round(net_alloc, 2),
                                    sdrt_fee=sdrt,
                                    entry_fx_fee=fx_fee,
                                    entry_spread_cost=spread_cost,
                                    entry_slippage_cost=slippage,
                                    stop_price=order.get("stop_price", 0.0),
                                    target_price=order.get("target_price", 0.0)
                                )
                                open_trades[sym] = trade
                                cash -= alloc_target
                                total_sdrt_paid += sdrt
                                total_fx_paid += fx_fee
                                total_spread_slippage += (spread_cost + slippage)
                                total_turnover += alloc_target
                else:
                    remaining_pending.append(order)
            pending_orders = remaining_pending

            # 2b. Mark positions to market and evaluate exits
            trades_to_close = []
            for sym, trade in open_trades.items():
                df = bars_data.get(trade.yf_ticker)
                if df is None or current_dt not in df.index:
                    continue
                bar = df.loc[current_dt]
                high_p = float(bar.get("High", bar.get("Close")))
                low_p = float(bar.get("Low", bar.get("Close")))
                close_p = float(bar.get("Close"))

                if high_p > trade.peak_price:
                    trade.peak_price = high_p

                # Check strategy-specific exit conditions
                should_exit, exit_price, exit_reason = strategy_logic_fn(
                    mode="EVAL_EXIT",
                    trade=trade,
                    current_bar=bar,
                    current_dt=current_dt,
                    current_idx=current_idx
                )

                if should_exit:
                    trades_to_close.append((sym, exit_price, exit_reason))

            for sym, exit_p, exit_reason in trades_to_close:
                trade = open_trades.pop(sym)
                trade.close(current_dt, exit_p, exit_reason, self.frictions)
                closed_trades.append(trade)
                
                # Cash proceeds returned to portfolio
                proceeds = trade.exit_notional - (trade.exit_spread_cost + trade.exit_slippage_cost + trade.exit_fx_fee)
                cash += proceeds
                total_fx_paid += trade.exit_fx_fee
                total_spread_slippage += (trade.exit_spread_cost + trade.exit_slippage_cost)
                total_turnover += trade.exit_notional

            # 2c. Strategy signal generation for new entries
            available_slots = self.max_positions - len(open_trades) - len(pending_orders)
            min_cash_req = self.starting_nav * self.min_cash_buffer_pct
            free_cash_for_trades = max(0.0, cash - min_cash_req)

            if available_slots > 0 and free_cash_for_trades >= 500.0:
                signals = strategy_logic_fn(
                    mode="GENERATE_SIGNALS",
                    current_dt=current_dt,
                    current_idx=current_idx,
                    available_slots=available_slots,
                    existing_symbols=set(open_trades.keys()).union({o["symbol"] for o in pending_orders}),
                    bars_data=bars_data
                )

                for sig in signals[:available_slots]:
                    alloc_per_trade = min(free_cash_for_trades / available_slots, sig.get("target_capital", free_cash_for_trades / available_slots))
                    if alloc_per_trade >= 500.0:
                        pending_orders.append({
                            "symbol": sig["symbol"],
                            "yf_ticker": sig["yf_ticker"],
                            "country": sig["country"],
                            "target_capital": alloc_per_trade,
                            "stop_price": sig.get("stop_price", 0.0),
                            "target_price": sig.get("target_price", 0.0),
                            "execute_on_idx": current_idx + self.execution_lag_days + 1
                        })
                        free_cash_for_trades -= alloc_per_trade

            # 2d. End-of-day NAV valuation
            invested_val = 0.0
            for sym, trade in open_trades.items():
                df = bars_data.get(trade.yf_ticker)
                if df is not None and current_dt in df.index:
                    p = float(df.loc[current_dt].get("Close"))
                    invested_val += trade.quantity * p
                else:
                    invested_val += trade.entry_notional

            eod_nav = round(cash + invested_val, 2)
            daily_nav_history.append({
                "date": current_date_str,
                "nav": eod_nav,
                "cash": round(cash, 2),
                "invested": round(invested_val, 2),
                "open_positions_count": len(open_trades)
            })

        # Close any remaining open positions at final calendar date
        final_dt = calendar[-1]
        for sym, trade in list(open_trades.items()):
            df = bars_data.get(trade.yf_ticker)
            final_p = float(df.loc[final_dt].get("Close")) if (df is not None and final_dt in df.index) else trade.entry_price
            trade.close(final_dt, final_p, "END_OF_TEST_PERIOD", self.frictions)
            closed_trades.append(trade)

        # 3. Compute Authoritative Performance Metrics strictly from Transaction Ledger and NAV curve
        metrics = self._calculate_ledger_metrics(
            starting_nav=self.starting_nav,
            daily_nav_history=daily_nav_history,
            closed_trades=closed_trades,
            total_sdrt=total_sdrt_paid,
            total_fx=total_fx_paid,
            total_spread_slippage=total_spread_slippage,
            total_turnover=total_turnover,
            benchmark_bars=benchmark_bars,
            start_date=start_date,
            end_date=end_date
        )

        return {
            "metrics": metrics,
            "daily_nav": daily_nav_history,
            "closed_trades": [t.to_dict() for t in closed_trades]
        }

    def _calculate_ledger_metrics(
        self,
        starting_nav: float,
        daily_nav_history: List[Dict[str, Any]],
        closed_trades: List[SimulatedTrade],
        total_sdrt: float,
        total_fx: float,
        total_spread_slippage: float,
        total_turnover: float,
        benchmark_bars: Optional[pd.DataFrame],
        start_date: str,
        end_date: str
    ) -> Dict[str, Any]:
        """Strict mathematical ledger-derived performance reporting."""
        if not daily_nav_history:
            return {"error": "No daily NAV history recorded"}

        nav_df = pd.DataFrame(daily_nav_history)
        nav_df["date"] = pd.to_datetime(nav_df["date"])
        nav_df.set_index("date", inplace=True)
        
        ending_nav = float(nav_df["nav"].iloc[-1])
        total_return_pct = round(((ending_nav - starting_nav) / starting_nav) * 100.0, 2)
        
        # Days and Years
        total_days = max(1, (nav_df.index[-1] - nav_df.index[0]).days)
        years = max(0.08, total_days / 365.25)
        cagr = round((((ending_nav / starting_nav) ** (1.0 / years)) - 1.0) * 100.0, 2) if ending_nav > 0 else -100.0

        # Maximum Drawdown
        nav_df["peak"] = nav_df["nav"].cummax()
        nav_df["drawdown"] = (nav_df["nav"] - nav_df["peak"]) / nav_df["peak"]
        max_drawdown_pct = round(abs(float(nav_df["drawdown"].min())) * 100.0, 2)

        # Daily returns for Sharpe and Sortino
        nav_df["daily_ret"] = nav_df["nav"].pct_change().fillna(0.0)
        daily_ret = nav_df["daily_ret"]
        mean_ret = float(daily_ret.mean())
        std_ret = float(daily_ret.std())
        
        sharpe = round((mean_ret / max(1e-6, std_ret)) * math.sqrt(252), 2) if std_ret > 0 else 0.0
        
        downside_ret = daily_ret[daily_ret < 0]
        downside_std = float(downside_ret.std()) if len(downside_ret) > 0 else 0.0
        sortino = round((mean_ret / max(1e-6, downside_std)) * math.sqrt(252), 2) if downside_std > 0 else 0.0

        # Benchmark return & alpha
        bench_return_pct = 0.0
        if benchmark_bars is not None and not benchmark_bars.empty:
            try:
                b_slice = benchmark_bars.loc[start_date:end_date]
                if len(b_slice) >= 2:
                    b_start = float(b_slice["Close"].iloc[0])
                    b_end = float(b_slice["Close"].iloc[-1])
                    bench_return_pct = round(((b_end - b_start) / b_start) * 100.0, 2)
            except Exception:
                pass
        alpha = round(total_return_pct - bench_return_pct, 2)

        # Trade stats from closed trades
        trade_count = len(closed_trades)
        net_pnls = [t.net_pnl for t in closed_trades]
        winners = [p for p in net_pnls if p > 0]
        losers = [p for p in net_pnls if p <= 0]
        
        win_count = len(winners)
        loss_count = len(losers)
        win_rate = round((win_count / max(1, trade_count)) * 100.0, 2)
        
        avg_winner = round(float(np.mean(winners)), 2) if winners else 0.0
        avg_loser = round(float(np.mean(losers)), 2) if losers else 0.0
        net_expectancy = round(float(np.mean(net_pnls)), 2) if net_pnls else 0.0
        
        gross_profit = sum(winners)
        gross_loss = abs(sum(losers))
        profit_factor = round(gross_profit / max(0.01, gross_loss), 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 0.0)

        # Holding period & Capital utilization
        holding_periods = [t.holding_days for t in closed_trades]
        avg_holding_period = round(float(np.mean(holding_periods)), 1) if holding_periods else 0.0
        capital_utilization = round(float((nav_df["invested"] / nav_df["nav"]).mean()) * 100.0, 2)

        # Monthly & Yearly returns
        monthly_ret = nav_df["nav"].resample("ME").last().pct_change().dropna()
        worst_month = round(float(monthly_ret.min()) * 100.0, 2) if not monthly_ret.empty else 0.0
        
        yearly_ret = nav_df["nav"].resample("YE").last().pct_change().dropna()
        worst_year = round(float(yearly_ret.min()) * 100.0, 2) if not yearly_ret.empty else 0.0
        positive_years = int((yearly_ret > 0).sum()) if not yearly_ret.empty else (1 if total_return_pct > 0 else 0)
        total_years = max(1, len(yearly_ret))

        return {
            "starting_nav": starting_nav,
            "ending_nav": ending_nav,
            "CAGR": cagr,
            "total_return_pct": total_return_pct,
            "benchmark_return_pct": bench_return_pct,
            "alpha": alpha,
            "maximum_drawdown_pct": max_drawdown_pct,
            "Sharpe": sharpe,
            "Sortino": sortino,
            "profit_factor": profit_factor,
            "trade_count": trade_count,
            "win_rate_pct": win_rate,
            "avg_winner_gbp": avg_winner,
            "avg_loser_gbp": avg_loser,
            "net_expectancy_gbp": net_expectancy,
            "turnover_gbp": round(total_turnover, 2),
            "total_sdrt_gbp": round(total_sdrt, 2),
            "total_fx_gbp": round(total_fx, 2),
            "total_spread_slippage_gbp": round(total_spread_slippage, 2),
            "average_holding_period_days": avg_holding_period,
            "capital_utilisation_pct": capital_utilization,
            "worst_month_pct": worst_month,
            "worst_year_pct": worst_year,
            "positive_years_ratio": f"{positive_years}/{total_years}"
        }
