"""
🏛️ PRV CAPITAL | DAILY NET PROFIT OBJECTIVE & ANTI-OVERTRADING MANDATE SERVICE
Maintains institutional daily profit accounting, anti-overtrading enforcement, capital banking,
profit locking, downside loss limits, and 30-day challenge performance metrics.

Mandate Principles:
1. Base Trading Capital: £50,000 (Max Deployable Trading Capital: £50,000)
2. Daily Net Profit Objective: £250 (0.50% Net Return after all buying/selling costs, taxes, FX, friction)
3. Banked Profit is NON-DEPLOYABLE (ring-fenced outside active trading bankroll, zero compounding)
4. Anti-Overtrading: FORCE_TRADE_TO_REACH_DAILY_TARGET = False. If no qualifying setup -> HOLD CASH.
5. Cost-First Entry Gate: Cost-to-profit <= 30% (preferred <= 25%), Net R:R >= 2.0x, Net profit > 0.
6. Daily Profit Lock: Once daily net realized profit >= £250, new discretionary entries are halted.
7. Daily Downside Control: Centrally configured loss limit (£500 / 1.0%), halts discretionary entries.
8. Priority Order:
   1. Preserve the £50,000 Base
   2. Avoid low-quality / high-cost trades
   3. Take only positive-net-expectancy setups
   4. Seek £250 net realized profit per day
   5. Stop taking unnecessary new risk after £250 is banked
"""
import os
import time
import json
import statistics
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from src.config.settings import settings
from src.database.db import db


class DailyObjectiveService:
    """
    Central operating service enforcing PRV Capital's Daily Net Profit Objective and Anti-Overtrading Mandate.
    """
    def __init__(self):
        self.base_trading_capital: float = settings.BASE_TRADING_CAPITAL
        self.max_deployable_capital: float = settings.MAX_DEPLOYABLE_TRADING_CAPITAL
        self.daily_net_profit_target: float = getattr(settings, "DAILY_BANKABLE_NET_TARGET", 250.0)
        self.daily_bankable_target: float = getattr(settings, "DAILY_BANKABLE_NET_TARGET", 250.0)
        self.daily_loss_lock_gbp: float = getattr(settings, "DAILY_NEW_ENTRY_LOSS_LOCK", 250.0)
        self.daily_emergency_loss_gbp: float = getattr(settings, "DAILY_EMERGENCY_LOSS_LEVEL", 500.0)
        self.daily_net_return_target_pct: float = settings.DAILY_NET_RETURN_OBJECTIVE_PCT
        self.banked_profit_is_non_deployable: bool = settings.BANKED_PROFIT_IS_NON_DEPLOYABLE
        self.force_trade_to_reach_daily_target: bool = settings.FORCE_TRADE_TO_REACH_DAILY_TARGET
        self.daily_max_net_loss_pct: float = settings.DAILY_MAX_NET_LOSS_PCT
        self.daily_max_net_loss_gbp: float = self.daily_emergency_loss_gbp
        self.daily_soft_loss_limit_gbp: float = self.daily_loss_lock_gbp
        self.daily_hard_loss_limit_gbp: float = self.daily_emergency_loss_gbp
        self._cached_daily_status: Optional[Dict[str, Any]] = None
        self._cached_status_time: float = 0.0
        self._cache_ttl_seconds: float = 30.0

        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Creates table for daily objective and banking ledger if not present."""
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS daily_objective_ledger (
                        date TEXT PRIMARY KEY,
                        gross_realized_pnl REAL NOT NULL DEFAULT 0.0,
                        total_costs REAL NOT NULL DEFAULT 0.0,
                        net_realized_pnl REAL NOT NULL DEFAULT 0.0,
                        target_achieved INTEGER NOT NULL DEFAULT 0,
                        banked_profit_today REAL NOT NULL DEFAULT 0.0,
                        cumulative_banked_profit REAL NOT NULL DEFAULT 0.0,
                        active_trading_bankroll REAL NOT NULL DEFAULT 50000.0,
                        turnover REAL NOT NULL DEFAULT 0.0,
                        entries_today INTEGER NOT NULL DEFAULT 0,
                        exits_today INTEGER NOT NULL DEFAULT 0,
                        downside_breached INTEGER NOT NULL DEFAULT 0,
                        notes TEXT
                    )
                """)
                conn.commit()
        except Exception:
            pass

    def get_today_str(self) -> str:
        """Returns today's date in UTC (YYYY-MM-DD)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_daily_status(self, target_date: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Computes the complete daily profit accounting, target progress, banking status,
        and entry permissions for the specified date (defaults to UTC today).
        """
        now_t = time.time()
        if not force_refresh and target_date is None and self._cached_daily_status is not None and (now_t - self._cached_status_time) < self._cache_ttl_seconds:
            return self._cached_daily_status

        today_str = target_date or self.get_today_str()
        
        # 1. Fetch all closed trades and order records for today from database
        all_trades = db.get_trades(limit=1000)
        today_trades = [
            t for t in all_trades
            if str(t.get("timestamp", "")).startswith(today_str)
        ]

        # Decompose gross realized P&L, fees, and costs
        # Only closed / exited trades count toward realized profit
        daily_gross_realized = 0.0
        daily_total_costs = 0.0
        daily_net_realized = 0.0
        turnover = 0.0
        entries_today = 0
        exits_today = 0

        for t in today_trades:
            action = str(t.get("action", "")).upper()
            qty = float(t.get("quantity", 0.0))
            price = float(t.get("price", 0.0))
            trade_val = abs(qty * price)
            turnover += trade_val

            if action == "BUY":
                entries_today += 1
            elif action == "SELL":
                exits_today += 1
                net_pnl = float(t.get("realized_pnl", 0.0))
                # Attribution cost decomposition if available
                costs = float(t.get("total_transaction_costs", t.get("commission", 0.0)))
                gross_pnl = net_pnl + costs if costs > 0 else net_pnl
                
                daily_gross_realized += gross_pnl
                daily_total_costs += costs
                daily_net_realized += net_pnl

        daily_gross_realized = round(daily_gross_realized, 2)
        daily_total_costs = round(daily_total_costs, 2)
        daily_net_realized = round(daily_net_realized, 2)
        turnover = round(turnover, 2)

        # 2. Query cumulative banked profit and capital state
        from src.portfolio.capital_state_machine import capital_state_machine
        from src.portfolio.portfolio_snapshot import portfolio_snapshot
        
        snap = portfolio_snapshot.get_authoritative_snapshot()
        nav = snap["account_summary"]["total_nav"]
        unrealized = snap["account_summary"].get("total_unrealized_pnl_gbp", 0.0)

        # Check market stress conditions
        from src.risk.market_stress_detector import market_stress_detector
        stress_active, stress_reason, _ = market_stress_detector.evaluate_market_stress()

        c_state = capital_state_machine.evaluate_portfolio_states(
            current_broker_nav=nav,
            current_unrealized_pnl=unrealized,
            daily_realized_pnl=daily_net_realized,
            market_stress_active=stress_active,
            market_stress_reason=stress_reason,
            is_sod_or_eod_check=False
        )

        bankable_today = c_state["bankable_profit_today_gbp"]
        target_progress_pct = c_state["daily_target_progress_pct"]
        target_achieved = c_state["daily_target_achieved"]
        loss_lock_breached = c_state["daily_loss_lock_breached"]
        emergency_mode = c_state["emergency_risk_mode"]
        new_entries_allowed = c_state["new_discretionary_entries_allowed"]
        gate_reason = c_state["state_reason"]

        # Net Profit per £1 Trading Cost
        profit_per_pound_cost = round(daily_net_realized / max(0.01, daily_total_costs), 2) if daily_total_costs > 0 else (daily_net_realized if daily_net_realized > 0 else 0.0)

        return {
            "date": today_str,
            "reference_base_capital_gbp": c_state["reference_base_capital_gbp"],
            "base_trading_capital_gbp": self.base_trading_capital,
            "max_deployable_trading_capital_gbp": self.max_deployable_capital,
            "max_normal_deployable_gbp": c_state["max_normal_deployable_gbp"],
            "active_trading_equity_gbp": c_state["active_trading_equity_gbp"],
            "deployable_bankroll_gbp": c_state["active_trading_equity_gbp"],
            "base_capital_deficit_gbp": c_state["base_capital_deficit_gbp"],
            "in_recovery_mode": c_state["in_recovery_mode"],
            "capital_state": c_state["capital_state"],
            "daily_state": c_state["daily_state"],
            "market_state": c_state["market_state"],
            "current_capital_state": c_state["capital_state"],
            "banked_profit_reserve_gbp": c_state["banked_profit_reserve_gbp"],
            "cumulative_banked_profit_gbp": c_state["banked_profit_reserve_gbp"],
            "banked_profit_reserve_location": c_state["banked_profit_reserve_location"],
            "total_capital_transfers_gbp": c_state["total_capital_transfers_gbp"],
            "net_strategy_profit_gbp": c_state["net_strategy_profit_gbp"],
            "banked_profit_is_non_deployable": self.banked_profit_is_non_deployable,
            "automatic_bank_reserve_redeployment": False,
            "topup_permission_required": c_state["topup_permission_required"],
            "proposed_topup_amount_gbp": c_state["proposed_topup_amount_gbp"],
            "daily_net_profit_objective_gbp": self.daily_net_profit_target,
            "daily_bankable_target_gbp": self.daily_bankable_target,
            "daily_net_return_objective_pct": self.daily_net_return_target_pct,
            "force_trade_to_reach_daily_target": self.force_trade_to_reach_daily_target,
            "daily_gross_realized_pnl_gbp": daily_gross_realized,
            "daily_total_costs_gbp": daily_total_costs,
            "daily_net_realized_pnl_gbp": daily_net_realized,
            "daily_net_unrealized_pnl_gbp": c_state["daily_unrealized_pnl_gbp"],
            "change_in_unrealized_today_gbp": c_state["change_in_unrealized_today_gbp"],
            "daily_mtm_pnl_gbp": c_state["daily_mtm_pnl_gbp"],
            "daily_total_net_pnl_gbp": c_state["daily_mtm_pnl_gbp"],
            "bankable_profit_today_gbp": bankable_today,
            "daily_target_progress_pct": target_progress_pct,
            "daily_target_achieved": target_achieved,
            "daily_loss_lock_gbp": self.daily_loss_lock_gbp,
            "daily_emergency_loss_gbp": self.daily_emergency_loss_gbp,
            "daily_soft_loss_limit_gbp": self.daily_soft_loss_limit_gbp,
            "daily_hard_loss_limit_gbp": self.daily_hard_loss_limit_gbp,
            "daily_loss_lock_breached": loss_lock_breached,
            "emergency_risk_mode": emergency_mode,
            "cancel_unfilled_entry_orders": c_state["cancel_unfilled_entry_orders"],
            "daily_downside_breached": loss_lock_breached,
            "new_discretionary_entries_allowed": new_entries_allowed,
            "sizing_multiplier": c_state["sizing_multiplier"],
            "gate_reason": gate_reason,
            "turnover_gbp": turnover,
            "entries_today": entries_today,
            "exits_today": exits_today,
            "net_profit_per_pound_cost": profit_per_pound_cost,
            "anti_gambling_safeguards": c_state["anti_gambling_safeguards"]
        }

        if target_date is None:
            self._cached_daily_status = status_payload
            self._cached_status_time = time.time()

        return status_payload

    def are_new_discretionary_entries_allowed(self) -> Tuple[bool, str]:
        """
        Check if new discretionary buying is permitted under daily target lock, downside limit, or market stress.
        Risk exits, stop loss triggers, and capital preservation exits are ALWAYS permitted.
        """
        status = self.get_daily_status()
        return status["new_discretionary_entries_allowed"], status["gate_reason"]

    def process_trade_close(
        self,
        trade_id: str,
        symbol: str,
        net_realized_pnl: float,
        gross_realized_pnl: float = 0.0,
        total_costs: float = 0.0
    ) -> Dict[str, Any]:
        """
        Processes a trade close through CapitalStateMachine:
        - In RECOVERY: BANKABLE_PROFIT = £0. Gains reduce deficit inside active equity.
        - In NORMAL: Profit above £50,000 reference base is banked to reserve.
        """
        from src.portfolio.capital_state_machine import capital_state_machine
        from src.portfolio.portfolio_snapshot import portfolio_snapshot
        
        snap = portfolio_snapshot.get_authoritative_snapshot()
        nav = snap["account_summary"]["total_nav"]
        banked_before = db.get_vault_balance()
        current_active = max(0.0, nav - banked_before)

        c_res = capital_state_machine.process_trade_close(
            trade_id=trade_id,
            symbol=symbol,
            net_realized_pnl=net_realized_pnl,
            current_active_equity=current_active
        )
        
        status = self.get_daily_status()
        return {
            "vaulted": (c_res["banked_amount_gbp"] > 0),
            "banked_amount_gbp": c_res["banked_amount_gbp"],
            "cumulative_banked_profit_gbp": c_res["banked_profit_reserve_gbp"],
            "active_trading_equity_gbp": c_res["active_trading_equity_gbp"],
            "daily_net_realized_pnl_gbp": status["daily_net_realized_pnl_gbp"],
            "daily_target_achieved": status["daily_target_achieved"],
            "current_capital_state": status["current_capital_state"],
            "in_recovery_mode": status["in_recovery_mode"],
            "new_discretionary_entries_allowed": status["new_discretionary_entries_allowed"]
        }

    def compute_30day_challenge_evaluation(self) -> Dict[str, Any]:
        """
        Computes the complete institutional 12-metric Performance Evaluation for the 30-day challenge:
        1. total banked net profit
        2. average daily net profit
        3. median daily net profit
        4. number of days >= £250
        5. profitable day %
        6. no-trade day count
        7. worst day
        8. maximum drawdown
        9. net expectancy per trade
        10. profit factor
        11. total trading costs
        12. net profit per £1 of cost
        """
        all_trades = db.get_trades(limit=2000)
        daily_trade_pnl: Dict[str, float] = {}
        daily_trade_costs: Dict[str, float] = {}

        total_trade_costs = 0.0
        trade_pnls: List[float] = []

        for t in all_trades:
            ts = str(t.get("timestamp", ""))[:10]
            action = str(t.get("action", "")).upper()
            cost = float(t.get("total_transaction_costs", t.get("commission", 0.0)))
            total_trade_costs += cost

            if action == "SELL":
                pnl = float(t.get("realized_pnl", 0.0))
                trade_pnls.append(pnl)
                daily_trade_pnl[ts] = daily_trade_pnl.get(ts, 0.0) + pnl
                daily_trade_costs[ts] = daily_trade_costs.get(ts, 0.0) + cost

        daily_pnls: List[float] = list(daily_trade_pnl.values())
        total_banked_profit = db.get_vault_balance()

        total_days_evaluated = max(1, len(daily_pnls))
        avg_daily_net = round(statistics.mean(daily_pnls), 2) if daily_pnls else 0.0
        median_daily_net = round(statistics.median(daily_pnls), 2) if daily_pnls else 0.0
        days_target_met = sum(1 for p in daily_pnls if p >= self.daily_net_profit_target)
        profitable_days = sum(1 for p in daily_pnls if p > 0.0)
        profitable_day_pct = round((profitable_days / total_days_evaluated) * 100.0, 2)
        no_trade_day_count = sum(1 for p in daily_pnls if p == 0.0)
        worst_day = round(min(daily_pnls), 2) if daily_pnls else 0.0

        peak = self.base_trading_capital
        max_dd_pct = 0.0
        running_equity = self.base_trading_capital
        for p in daily_pnls:
            running_equity += p
            if running_equity > peak:
                peak = running_equity
            dd = (peak - running_equity) / peak * 100.0
            if dd > max_dd_pct:
                max_dd_pct = dd
        max_dd_pct = round(max_dd_pct, 2)

        winning_trades = [p for p in trade_pnls if p > 0]
        losing_trades = [p for p in trade_pnls if p < 0]
        gross_wins = sum(winning_trades)
        gross_losses = abs(sum(losing_trades))

        profit_factor = round(gross_wins / max(0.01, gross_losses), 2) if gross_losses > 0 else (round(gross_wins, 2) if gross_wins > 0 else 1.0)
        net_expectancy = round(statistics.mean(trade_pnls), 2) if trade_pnls else 0.0

        total_trade_costs = round(total_trade_costs, 2)
        total_net_profit = round(sum(trade_pnls), 2)
        profit_per_cost = round(total_net_profit / max(0.01, total_trade_costs), 2) if total_trade_costs > 0 else (total_net_profit if total_net_profit > 0 else 0.0)

        return {
            "total_banked_net_profit_gbp": round(total_banked_profit, 2),
            "average_daily_net_profit_gbp": avg_daily_net,
            "median_daily_net_profit_gbp": median_daily_net,
            "number_of_days_target_met": days_target_met,
            "profitable_day_pct": profitable_day_pct,
            "no_trade_day_count": no_trade_day_count,
            "worst_day_gbp": worst_day,
            "maximum_drawdown_pct": max_dd_pct,
            "net_expectancy_per_trade_gbp": net_expectancy,
            "profit_factor": profit_factor,
            "total_trading_costs_gbp": total_trade_costs,
            "net_profit_per_pound_cost": profit_per_cost,
            "total_evaluated_days": total_days_evaluated,
            "challenge_target_daily_gbp": self.daily_net_profit_target
        }


daily_objective_service = DailyObjectiveService()
