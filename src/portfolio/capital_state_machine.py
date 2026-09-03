"""
🏛️ PRV CAPITAL | CAPITAL PRESERVATION, DAILY BANKING & LOSS-RECOVERY STATE MACHINE
Authoritative multi-dimensional portfolio control layer.

Architecture:
1. THREE-LEDGER CAPITAL MODEL:
   - ACTIVE_TRADING_EQUITY  : Deployable operating equity (Reference Base: £50,000)
   - BANKED_PROFIT_RESERVE  : Realized gains swept outside deployable capital (Non-deployable)
   - CAPITAL_TRANSFERS      : User-approved capital top-ups (ISOLATED FROM TRADING P&L!)

2. INDEPENDENT STATE DIMENSIONS:
   - CAPITAL_STATE : NORMAL / RECOVERY / USER_TOPUP_PENDING
   - DAILY_STATE   : ACTIVE / TARGET_LOCK / LOSS_LOCK / EMERGENCY_LOCK
   - MARKET_STATE  : NORMAL / STRESS

3. CORRIDOR RISK POLICY:
   - +£250 Bankable Net Target : STOP NEW ENTRIES (TARGET_LOCK)
   - -£250 Daily MTM Loss Lock : STOP NEW ENTRIES (LOSS_LOCK, no recovery trading)
   - -£500 Emergency Loss Level: EMERGENCY_LOCK, cancel unfilled entries, allow risk-reducing exits only

4. DELTA MTM P&L ACCOUNTING:
   - Evaluated from immutable Start-of-Day (SOD) snapshot.
   - DAILY_MTM_PNL = Realized Net Today + Change in Unrealized P&L Today + FX/Fees

5. BANKABLE PROFIT INVARIANT:
   - Profit is ONLY bankable if active equity exceeds £50,000 base.
   - Closed profits with open losses that leave active equity < £50k are ZERO BANKABLE!
"""
import os
import json
import logging
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from src.config.settings import settings
from src.database.db import db

logger = logging.getLogger("capital_state_machine")


class CapitalState(str, Enum):
    NORMAL = "NORMAL"
    RECOVERY = "RECOVERY"
    USER_TOPUP_PENDING = "USER_TOPUP_PENDING"


class DailyState(str, Enum):
    ACTIVE = "ACTIVE"
    TARGET_LOCK = "TARGET_LOCK"
    LOSS_LOCK = "LOSS_LOCK"
    EMERGENCY_LOCK = "EMERGENCY_LOCK"


class MarketState(str, Enum):
    NORMAL = "NORMAL"
    STRESS = "STRESS"


class CapitalStateMachine:
    """
    Authoritative state machine governing capital allocation, recovery, banking,
    and loss-prevention circuit breakers across three independent dimensions.
    """
    def __init__(self):
        self.reference_base_capital: float = settings.REFERENCE_BASE_CAPITAL # £50,000
        self.max_normal_deployable: float = settings.MAX_NORMAL_DEPLOYABLE_CAPITAL # £50,000
        self.daily_bankable_target: float = settings.DAILY_BANKABLE_NET_TARGET # +£250
        self.daily_loss_lock_gbp: float = settings.DAILY_NEW_ENTRY_LOSS_LOCK # -£250
        self.daily_emergency_loss_gbp: float = settings.DAILY_EMERGENCY_LOSS_LEVEL # -£500
        self.reserve_location: str = settings.BANKED_PROFIT_RESERVE_LOCATION # RINGFENCED_INSIDE_BROKER
        
        # In-memory tracking
        self._topup_declined_sessions: set = set()
        self._capital_state: CapitalState = CapitalState.NORMAL
        self._daily_state: DailyState = DailyState.ACTIVE
        self._market_state: MarketState = MarketState.NORMAL

    def get_today_str(self) -> str:
        """Returns UTC date string (YYYY-MM-DD)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def evaluate_portfolio_states(
        self,
        current_broker_nav: float,
        current_unrealized_pnl: float,
        daily_realized_pnl: float,
        market_stress_active: bool = False,
        market_stress_reason: str = "",
        is_sod_or_eod_check: bool = False
    ) -> Dict[str, Any]:
        """
        Authoritative evaluation of the three independent state dimensions:
        CAPITAL_STATE, DAILY_STATE, and MARKET_STATE.
        """
        today_str = self.get_today_str()
        banked_reserve = db.get_vault_balance()
        total_transfers = db.get_total_capital_transfers()
        
        # 1. Unvaulted Active Equity
        unvaulted_equity = max(0.0, current_broker_nav - banked_reserve)
        
        # 2. Start-of-Day Snapshot & Delta-Based Daily MTM P&L
        sod_snap = db.get_or_create_sod_snapshot(
            date_str=today_str,
            current_active_equity=unvaulted_equity,
            current_broker_nav=current_broker_nav,
            current_vault_balance=banked_reserve,
            current_unrealized_pnl=current_unrealized_pnl
        )
        sod_active_equity = float(sod_snap["start_active_equity"])
        sod_unrealized_pnl = float(sod_snap.get("start_unrealized_pnl", 0.0))
        
        # Delta MTM P&L Calculation:
        # Change in Unrealized Today = Current Unrealized - SOD Unrealized
        change_in_unrealized_today = round(current_unrealized_pnl - sod_unrealized_pnl, 2)
        daily_mtm_pnl = round(daily_realized_pnl + change_in_unrealized_today, 2)

        # 3. Capital State & Deficit
        if unvaulted_equity < self.reference_base_capital:
            active_trading_equity = round(unvaulted_equity, 2)
            base_deficit = round(self.reference_base_capital - active_trading_equity, 2)
            in_deficit = True
        else:
            active_trading_equity = round(min(self.max_normal_deployable, unvaulted_equity), 2)
            base_deficit = 0.0
            in_deficit = False

        # 4. Bankable Profit Today (Target must mean Bankable Net Profit!)
        # Bankable profit cannot exceed amount by which active equity exceeds £50,000 base
        excess_above_base = max(0.0, unvaulted_equity - self.reference_base_capital)
        bankable_profit_today = round(min(max(0.0, daily_realized_pnl), excess_above_base), 2)

        # 5. Dimension 1: CAPITAL_STATE Evaluation
        # Only prompt at SOD/EOD check or if manual trigger, NOT on transient intraday tick fluctuation
        topup_available = (in_deficit and banked_reserve > 0.0)
        proposed_topup = round(min(base_deficit, banked_reserve), 2) if topup_available else 0.0
        topup_permission_required = False

        if topup_available and is_sod_or_eod_check:
            if today_str not in self._topup_declined_sessions:
                topup_permission_required = True

        if topup_permission_required:
            cap_state = CapitalState.USER_TOPUP_PENDING
            cap_reason = f"Capital Deficit (£{base_deficit:.2f}) with available reserve (£{banked_reserve:.2f}). User top-up permission requested."
        elif in_deficit:
            cap_state = CapitalState.RECOVERY
            cap_reason = f"RECOVERY MODE: Active equity (£{active_trading_equity:.2f}) below £50,000 base (Deficit: £{base_deficit:.2f}). No banking until base restored."
        else:
            cap_state = CapitalState.NORMAL
            cap_reason = f"NORMAL MODE: Active equity (£{active_trading_equity:.2f}) at or above £50,000 base."

        # 6. Dimension 2: DAILY_STATE Evaluation
        # Corridor Policy:
        # DAILY_MTM_PNL <= -£500 -> EMERGENCY_LOCK
        # DAILY_MTM_PNL <= -£250 -> LOSS_LOCK (No trading, no sizing halving)
        # BANKABLE_NET_PROFIT_TODAY >= £250 -> TARGET_LOCK
        # Otherwise -> ACTIVE
        if daily_mtm_pnl <= -self.daily_emergency_loss_gbp:
            daily_st = DailyState.EMERGENCY_LOCK
            daily_reason = f"EMERGENCY LOCK: Daily MTM P&L (£{daily_mtm_pnl:+.2f}) hit emergency threshold (-£{self.daily_emergency_loss_gbp:.2f}). Unfilled entries cancelled."
            cancel_unfilled = True
        elif daily_mtm_pnl <= -self.daily_loss_lock_gbp:
            daily_st = DailyState.LOSS_LOCK
            daily_reason = f"DAILY LOSS LOCK: Daily MTM P&L (£{daily_mtm_pnl:+.2f}) hit daily loss stop (-£{self.daily_loss_lock_gbp:.2f}). New entries locked."
            cancel_unfilled = False
        elif bankable_profit_today >= self.daily_bankable_target:
            daily_st = DailyState.TARGET_LOCK
            daily_reason = f"TARGET LOCK: Bankable profit (£{bankable_profit_today:.2f}) reached £250 objective. Daily gains locked."
            cancel_unfilled = False
        else:
            daily_st = DailyState.ACTIVE
            daily_reason = f"ACTIVE: Daily MTM P&L: £{daily_mtm_pnl:+.2f} | Bankable today: £{bankable_profit_today:.2f} / £{self.daily_bankable_target:.2f}."
            cancel_unfilled = False

        # 7. Dimension 3: MARKET_STATE Evaluation
        if market_stress_active:
            mkt_st = MarketState.STRESS
            mkt_reason = f"MARKET STRESS: {market_stress_reason}. Discretionary longs blocked."
        else:
            mkt_st = MarketState.NORMAL
            mkt_reason = "MARKET NORMAL: Volatility and spreads within institutional parameters."

        # 8. Composite Entry Permission Gate (AND-combination of all risk dimensions)
        # Sizing multiplier: In RECOVERY, strictly <= 1.0 (scales with equity, never inflated)
        if daily_st != DailyState.ACTIVE or mkt_st != MarketState.NORMAL or cap_state == CapitalState.USER_TOPUP_PENDING:
            new_entries_allowed = False
            sizing_multiplier = 0.0
        else:
            new_entries_allowed = True
            if cap_state == CapitalState.RECOVERY:
                sizing_multiplier = round(min(1.0, active_trading_equity / self.reference_base_capital), 4)
            else:
                sizing_multiplier = 1.0

        # Persist transitions if changed
        if (cap_state != self._capital_state or daily_st != self._daily_state or mkt_st != self._market_state):
            trigger = f"[{cap_state.value}|{daily_st.value}|{mkt_st.value}] - {daily_reason}"
            db.record_state_transition(
                previous_state=f"{self._capital_state.value}|{self._daily_state.value}|{self._market_state.value}",
                new_state=f"{cap_state.value}|{daily_st.value}|{mkt_st.value}",
                active_equity=active_trading_equity,
                deficit=base_deficit,
                vault_balance=banked_reserve,
                trigger_reason=trigger
            )
            self._capital_state = cap_state
            self._daily_state = daily_st
            self._market_state = mkt_st

        # Target progress based on BANKABLE net profit
        target_progress_pct = round((bankable_profit_today / max(0.01, self.daily_bankable_target)) * 100.0, 2)
        net_strategy_profit = db.get_net_strategy_profit()

        return {
            "capital_state": cap_state.value,
            "daily_state": daily_st.value,
            "market_state": mkt_st.value,
            "current_state": cap_state.value, # Compatibility key
            "capital_reason": cap_reason,
            "daily_reason": daily_reason,
            "market_reason": mkt_reason,
            "state_reason": f"[{cap_state.value}|{daily_st.value}|{mkt_st.value}] {daily_reason}",
            "reference_base_capital_gbp": self.reference_base_capital,
            "max_normal_deployable_gbp": self.max_normal_deployable,
            "active_trading_equity_gbp": active_trading_equity,
            "base_capital_deficit_gbp": base_deficit,
            "in_recovery_mode": in_deficit,
            "banked_profit_reserve_gbp": round(banked_reserve, 2),
            "banked_profit_reserve_location": self.reserve_location,
            "total_capital_transfers_gbp": round(total_transfers, 2),
            "net_strategy_profit_gbp": net_strategy_profit,
            "sod_active_equity_gbp": sod_active_equity,
            "sod_unrealized_pnl_gbp": sod_unrealized_pnl,
            "change_in_unrealized_today_gbp": change_in_unrealized_today,
            "daily_realized_pnl_gbp": round(daily_realized_pnl, 2),
            "daily_unrealized_pnl_gbp": round(current_unrealized_pnl, 2),
            "daily_mtm_pnl_gbp": daily_mtm_pnl,
            "bankable_profit_today_gbp": bankable_profit_today,
            "daily_net_profit_objective_gbp": self.daily_bankable_target,
            "daily_target_progress_pct": target_progress_pct,
            "daily_target_achieved": (daily_st == DailyState.TARGET_LOCK),
            "daily_loss_lock_breached": (daily_st in (DailyState.LOSS_LOCK, DailyState.EMERGENCY_LOCK)),
            "emergency_risk_mode": (daily_st == DailyState.EMERGENCY_LOCK),
            "cancel_unfilled_entry_orders": cancel_unfilled,
            "new_discretionary_entries_allowed": new_entries_allowed,
            "sizing_multiplier": sizing_multiplier,
            "topup_permission_required": topup_permission_required,
            "proposed_topup_amount_gbp": proposed_topup,
            "anti_gambling_safeguards": {
                "loss_does_not_increase_risk": True,
                "martingale_prohibited": True,
                "averaging_down_prohibited": True,
                "force_trade_to_reach_daily_target": False
            }
        }

    def process_trade_close(
        self,
        trade_id: str,
        symbol: str,
        net_realized_pnl: float,
        current_active_equity: float
    ) -> Dict[str, Any]:
        """
        Processes closed trade:
        - Profit is ONLY bankable if active equity exceeds £50,000 base.
        - In RECOVERY: BANKABLE_PROFIT = £0. Gains reduce deficit inside active equity.
        - Crossing Boundary: Exactly £50k is restored as active base, and ONLY excess is banked.
        """
        banked_amount = 0.0
        new_active_equity = round(current_active_equity + net_realized_pnl, 2)
        was_in_deficit = (current_active_equity < self.reference_base_capital)

        if net_realized_pnl > 0:
            if was_in_deficit:
                if new_active_equity > self.reference_base_capital:
                    # Crossed deficit boundary
                    banked_amount = round(new_active_equity - self.reference_base_capital, 2)
                    new_active_equity = self.reference_base_capital
                    notes = f"Restored £50,000 base from recovery. Excess £{banked_amount:.2f} banked."
                else:
                    # Still in deficit or exactly £50k: ZERO BANKED
                    banked_amount = 0.0
                    notes = f"Recovery trade (+£{net_realized_pnl:.2f}). Zero banked. Remaining deficit £{max(0.0, self.reference_base_capital - new_active_equity):.2f}."
            else:
                # Normal mode: All net profit is bankable
                banked_amount = round(net_realized_pnl, 2)
                new_active_equity = self.reference_base_capital
                notes = f"Normal mode net profit banked (£{banked_amount:+.2f}). Ring-fenced."

            if banked_amount > 0:
                db.deposit_profit_vault(
                    trade_id=trade_id,
                    symbol=symbol,
                    realized_profit=banked_amount,
                    notes=notes
                )

        vault_total = db.get_vault_balance()
        return {
            "trade_id": trade_id,
            "net_realized_pnl": net_realized_pnl,
            "banked_amount_gbp": banked_amount,
            "active_trading_equity_gbp": new_active_equity,
            "banked_profit_reserve_gbp": vault_total,
            "is_in_deficit": (new_active_equity < self.reference_base_capital)
        }

    def approve_topup(self, user_name: str = "PORTFOLIO_MANAGER") -> Dict[str, Any]:
        """
        Executes explicit user-approved capital transfer.
        CORRECT PARTIAL TOP-UP LOGIC:
        If active equity remains < £50,000, CAPITAL_STATE remains RECOVERY, never falsely NORMAL!
        """
        banked_reserve = db.get_vault_balance()
        snap = self.get_current_active_state()
        active_equity = snap["active_trading_equity_gbp"]
        deficit = snap["base_capital_deficit_gbp"]

        if deficit <= 0:
            return {"success": False, "message": "No capital deficit exists. Top-up not required."}
        if banked_reserve <= 0:
            return {"success": False, "message": "No banked profit reserve available for top-up."}

        transfer_amount = round(min(deficit, banked_reserve), 2)
        transfer_id = f"XFER_{int(datetime.now(timezone.utc).timestamp())}"

        # Deduct from vault
        new_vault = db.withdraw_profit_vault(
            amount=transfer_amount,
            notes=f"Approved capital transfer {transfer_id} to restore active trading equity."
        )

        new_active = round(active_equity + transfer_amount, 2)
        new_deficit = max(0.0, round(self.reference_base_capital - new_active, 2))

        # Partial top-up check: Only NORMAL if deficit is exactly 0; otherwise remains RECOVERY
        new_cap_state = CapitalState.NORMAL if new_deficit == 0 else CapitalState.RECOVERY

        # Record into capital_transfers ledger (NEVER counted as trading P&L!)
        db.record_capital_transfer(
            transfer_id=transfer_id,
            source=f"BANKED_PROFIT_RESERVE ({self.reserve_location})",
            destination="ACTIVE_TRADING_EQUITY",
            amount=transfer_amount,
            approved_by=user_name,
            active_equity_before=active_equity,
            active_equity_after=new_active,
            vault_before=banked_reserve,
            vault_after=new_vault,
            notes="User approved top-up transfer. Authoritative ledger reclassification."
        )

        db.record_state_transition(
            previous_state=CapitalState.USER_TOPUP_PENDING.value,
            new_state=new_cap_state.value,
            active_equity=new_active,
            deficit=new_deficit,
            vault_balance=new_vault,
            trigger_reason=f"User approved top-up of £{transfer_amount:.2f}. Deficit remaining: £{new_deficit:.2f}."
        )

        self._capital_state = new_cap_state
        return {
            "success": True,
            "transfer_id": transfer_id,
            "amount_gbp": transfer_amount,
            "active_equity_before_gbp": active_equity,
            "active_equity_after_gbp": new_active,
            "banked_reserve_before_gbp": banked_reserve,
            "banked_reserve_after_gbp": new_vault,
            "capital_state": new_cap_state.value,
            "base_deficit_remaining_gbp": new_deficit,
            "is_trading_pnl": False,
            "message": f"Transferred £{transfer_amount:.2f} to active equity. Capital State is now {new_cap_state.value}."
        }

    def decline_topup(self, user_name: str = "PORTFOLIO_MANAGER") -> Dict[str, Any]:
        """
        User declines banked reserve top-up. System continues patient recovery with remaining equity.
        """
        today_str = self.get_today_str()
        self._topup_declined_sessions.add(today_str)
        snap = self.get_current_active_state()
        new_state = CapitalState.RECOVERY
        
        db.record_state_transition(
            previous_state=CapitalState.USER_TOPUP_PENDING.value,
            new_state=new_state.value,
            active_equity=snap["active_trading_equity_gbp"],
            deficit=snap["base_capital_deficit_gbp"],
            vault_balance=snap["banked_profit_reserve_gbp"],
            trigger_reason="User declined top-up. Continuing patient recovery with remaining active equity."
        )
        self._capital_state = new_state
        return {
            "success": True,
            "message": "Top-up declined. System remains in RECOVERY trading remaining active equity.",
            "capital_state": new_state.value,
            "active_trading_equity_gbp": snap["active_trading_equity_gbp"],
            "base_capital_deficit_gbp": snap["base_capital_deficit_gbp"]
        }

    def get_current_active_state(self, is_sod_or_eod_check: bool = False) -> Dict[str, Any]:
        """Fetches authoritative snapshot and evaluates the three dimensions."""
        from src.portfolio.portfolio_snapshot import portfolio_snapshot
        snap = portfolio_snapshot.get_authoritative_snapshot()
        nav = snap["account_summary"]["total_nav"]
        unrealized = snap["account_summary"].get("total_unrealized_pnl_gbp", 0.0)

        # Closed trades today
        all_trades = db.get_trades(limit=500)
        today_str = self.get_today_str()
        today_realized = sum(
            float(t.get("realized_pnl", 0.0))
            for t in all_trades
            if str(t.get("timestamp", "")).startswith(today_str) and str(t.get("action", "")).upper() == "SELL"
        )

        from src.risk.market_stress_detector import market_stress_detector
        stress_active, stress_reason, _ = market_stress_detector.evaluate_market_stress()

        return self.evaluate_portfolio_states(
            current_broker_nav=nav,
            current_unrealized_pnl=unrealized,
            daily_realized_pnl=today_realized,
            market_stress_active=stress_active,
            market_stress_reason=stress_reason,
            is_sod_or_eod_check=is_sod_or_eod_check
        )


capital_state_machine = CapitalStateMachine()
