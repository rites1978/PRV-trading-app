"""
🏛️ PRV CAPITAL | CAPITAL PRESERVATION, DAILY BANKING & LOSS-RECOVERY STATE MACHINE
Maintains institutional three-ledger capital accounting, patient deficit recovery,
non-deployable profit banking, user-permissioned top-ups, daily loss protection,
and anti-martingale safeguards.

Three Separate Isolated Ledgers:
1. ACTIVE_TRADING_EQUITY  : Current deployable active bankroll (capped at £50,000 normal base)
2. BANKED_PROFIT_RESERVE  : Realized profits swept outside deployable capital (non-deployable)
3. CAPITAL_TRANSFERS      : Explicitly approved capital restorations (NEVER counted as trading P&L)

Operating States:
- NORMAL              : Active equity >= £50k, operating base £50k, normal gating.
- TARGET_ACHIEVED     : Daily net profit >= £250, new discretionary entries locked.
- RECOVERY            : Active equity < £50k, zero profit banking until £50k restored, patient multi-day recovery.
- DAILY_LOSS_LOCK     : Hard daily loss limit touched (realized + unrealized), entries halted.
- MARKET_STRESS       : Severe market crash / stress conditions, new long entries disabled.
- USER_TOPUP_PENDING  : Deficit exists and banked reserve available; awaiting user decision.
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
    TARGET_ACHIEVED = "TARGET_ACHIEVED"
    RECOVERY = "RECOVERY"
    DAILY_LOSS_LOCK = "DAILY_LOSS_LOCK"
    MARKET_STRESS = "MARKET_STRESS"
    USER_TOPUP_PENDING = "USER_TOPUP_PENDING"


class CapitalStateMachine:
    """
    Authoritative state machine governing capital allocation, recovery, banking,
    and loss-prevention circuit breakers.
    """
    def __init__(self):
        self.reference_base_capital: float = settings.REFERENCE_BASE_CAPITAL
        self.max_normal_deployable: float = settings.MAX_NORMAL_DEPLOYABLE_CAPITAL
        self.daily_net_profit_target: float = settings.DAILY_NET_PROFIT_OBJECTIVE
        self.daily_soft_loss_limit_gbp: float = settings.DAILY_SOFT_LOSS_LIMIT_GBP
        self.daily_hard_loss_limit_gbp: float = settings.DAILY_HARD_LOSS_LIMIT_GBP
        
        # In-memory tracking for decline state during active session
        self._topup_declined_sessions: set = set()
        self._current_state: CapitalState = CapitalState.NORMAL
        self._last_state_reason: str = "System initialized."

    def get_today_str(self) -> str:
        """Returns UTC date string (YYYY-MM-DD)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def evaluate_capital_state(
        self,
        current_broker_nav: float,
        daily_realized_pnl: float,
        daily_unrealized_pnl: float,
        market_stress_active: bool = False,
        market_stress_reason: str = ""
    ) -> Dict[str, Any]:
        """
        Authoritative evaluation of the three-ledger capital state and transitions.
        
        Balances:
        - REFERENCE_BASE_CAPITAL = £50,000
        - BANKED_PROFIT_RESERVE  = Total in profit vault
        - ACTIVE_TRADING_EQUITY  = Broker NAV - Banked Profit Reserve + (Total Capital Transfers into active)
          (bounded normally at £50,000)
        """
        today_str = self.get_today_str()
        banked_reserve = db.get_vault_balance()
        total_transfers = db.get_total_capital_transfers()
        
        # Active trading equity: Unvaulted capital currently in account
        unvaulted_equity = max(0.0, current_broker_nav - banked_reserve)
        
        # Deficit calculation against £50,000 reference base
        if unvaulted_equity < self.reference_base_capital:
            active_trading_equity = round(unvaulted_equity, 2)
            base_deficit = round(self.reference_base_capital - active_trading_equity, 2)
            in_deficit = True
        else:
            # In normal mode, active deployable base is capped at £50,000
            active_trading_equity = round(min(self.max_normal_deployable, unvaulted_equity), 2)
            base_deficit = 0.0
            in_deficit = False

        # Daily loss evaluation uses: REALIZED + UNREALIZED net P&L
        daily_total_net_pnl = round(daily_realized_pnl + daily_unrealized_pnl, 2)
        
        # Circuit breaker evaluations
        hard_loss_breached = (daily_total_net_pnl <= -self.daily_hard_loss_limit_gbp)
        soft_loss_breached = (daily_total_net_pnl <= -self.daily_soft_loss_limit_gbp)
        target_achieved = (daily_realized_pnl >= self.daily_net_profit_target)

        # Top-up permission requirement check
        topup_available = (in_deficit and banked_reserve > 0.0)
        topup_permission_required = False
        proposed_topup = 0.0

        if topup_available:
            proposed_topup = round(min(base_deficit, banked_reserve), 2)
            # If not explicitly declined in this session
            if today_str not in self._topup_declined_sessions:
                topup_permission_required = True

        # State Determination Hierarchy (Strict Priority):
        # 1. DAILY_LOSS_LOCK (Preserve capital on hard loss breach)
        # 2. MARKET_STRESS (Preserve capital on macro crash)
        # 3. TARGET_ACHIEVED (Lock profit once £250 banked today)
        # 4. USER_TOPUP_PENDING (Deficit exists and reserve available for prompt)
        # 5. RECOVERY (Operating in deficit without active top-up prompt)
        # 6. NORMAL (Base >= £50k, normal trading)
        previous_state = self._current_state
        new_state = CapitalState.NORMAL
        reason = "Normal operating state: equity at or above £50,000 base."

        if hard_loss_breached:
            new_state = CapitalState.DAILY_LOSS_LOCK
            reason = (f"HARD DAILY LOSS LOCK: Realized + Unrealized net P&L (£{daily_total_net_pnl:+.2f}) "
                      f"breached hard limit (£{self.daily_hard_loss_limit_gbp:.2f}). New entries paused.")
        elif market_stress_active:
            new_state = CapitalState.MARKET_STRESS
            reason = f"MARKET STRESS MODE ACTIVE: {market_stress_reason}. Discretionary longs blocked."
        elif target_achieved:
            new_state = CapitalState.TARGET_ACHIEVED
            reason = (f"DAILY TARGET ACHIEVED: Net realized profit (+£{daily_realized_pnl:.2f}) "
                      f"reached objective (£{self.daily_net_profit_target:.2f}). Discretionary risk halted.")
        elif topup_permission_required:
            new_state = CapitalState.USER_TOPUP_PENDING
            reason = (f"BASE CAPITAL DEFICIT (£{base_deficit:.2f}): Banked reserve available (£{banked_reserve:.2f}). "
                      f"Top-up of £{proposed_topup:.2f} requires user permission.")
        elif in_deficit:
            new_state = CapitalState.RECOVERY
            reason = (f"RECOVERY MODE: Active equity (£{active_trading_equity:.2f}) is below £50,000 base "
                      f"(Deficit: £{base_deficit:.2f}). Zero banking allowed until base is fully restored.")
        else:
            new_state = CapitalState.NORMAL
            reason = f"NORMAL MODE: Active deployable bankroll £{active_trading_equity:.2f} / £{self.reference_base_capital:.2f}."

        # Persist transition if state changed
        if new_state != previous_state:
            db.record_state_transition(
                previous_state=str(previous_state.value if hasattr(previous_state, 'value') else previous_state),
                new_state=str(new_state.value),
                active_equity=active_trading_equity,
                deficit=base_deficit,
                vault_balance=banked_reserve,
                trigger_reason=reason
            )
            self._current_state = new_state
            self._last_state_reason = reason

        # Sizing & Entry Permissions
        if new_state in (CapitalState.DAILY_LOSS_LOCK, CapitalState.MARKET_STRESS, CapitalState.TARGET_ACHIEVED):
            new_entries_allowed = False
            sizing_multiplier = 0.0
        elif new_state == CapitalState.RECOVERY:
            new_entries_allowed = True
            # Anti-gambling invariant: Loss never increases risk.
            # Sizing multiplier scales down strictly proportional to remaining active equity
            sizing_multiplier = round(min(1.0, active_trading_equity / self.reference_base_capital), 4)
        elif new_state == CapitalState.NORMAL and soft_loss_breached:
            new_entries_allowed = True
            # Soft loss limit breached: Halve new position sizing and demand highest quality
            sizing_multiplier = 0.50
        else:
            new_entries_allowed = True
            sizing_multiplier = 1.0

        net_strategy_profit = db.get_net_strategy_profit()

        return {
            "current_state": new_state.value,
            "previous_state": previous_state.value if hasattr(previous_state, 'value') else str(previous_state),
            "state_reason": reason,
            "reference_base_capital_gbp": self.reference_base_capital,
            "max_normal_deployable_gbp": self.max_normal_deployable,
            "active_trading_equity_gbp": active_trading_equity,
            "base_capital_deficit_gbp": base_deficit,
            "in_recovery_mode": in_deficit,
            "banked_profit_reserve_gbp": round(banked_reserve, 2),
            "total_capital_transfers_gbp": round(total_transfers, 2),
            "net_strategy_profit_gbp": net_strategy_profit,
            "daily_net_realized_pnl_gbp": round(daily_realized_pnl, 2),
            "daily_net_unrealized_pnl_gbp": round(daily_unrealized_pnl, 2),
            "daily_total_net_pnl_gbp": daily_total_net_pnl,
            "daily_net_profit_objective_gbp": self.daily_net_profit_target,
            "daily_target_achieved": target_achieved,
            "soft_loss_limit_breached": soft_loss_breached,
            "hard_loss_limit_breached": hard_loss_breached,
            "new_discretionary_entries_allowed": new_entries_allowed,
            "sizing_multiplier": sizing_multiplier,
            "topup_permission_required": topup_permission_required,
            "proposed_topup_amount_gbp": proposed_topup,
            "automatic_bank_reserve_redeployment": False,
            "recovery_deadline": "NONE (Patient multi-day recovery without target chasing)",
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
        Processes closed trade under Capital State Machine invariants:
        - In RECOVERY: BANKABLE_PROFIT = £0. Gains reduce deficit inside active equity.
        - In NORMAL: If active equity is >= £50k, all realized net gain is banked to reserve.
        - Crossing Boundary: If equity crosses from < £50k to > £50k:
          Exactly £50k is restored as active operating base, and ONLY the excess is banked.
        """
        banked_amount = 0.0
        new_active_equity = round(current_active_equity + net_realized_pnl, 2)
        
        # Was the account in deficit before this trade?
        was_in_deficit = (current_active_equity < self.reference_base_capital)
        
        if net_realized_pnl > 0:
            if was_in_deficit:
                if new_active_equity > self.reference_base_capital:
                    # Restored deficit and produced excess above £50,000
                    restored_deficit = self.reference_base_capital - current_active_equity
                    banked_amount = round(new_active_equity - self.reference_base_capital, 2)
                    new_active_equity = self.reference_base_capital
                    notes = f"Restored £50,000 base from recovery. Excess £{banked_amount:.2f} banked."
                else:
                    # Still in deficit or exactly reached £50k: zero banked!
                    banked_amount = 0.0
                    notes = f"Recovery trade (+£{net_realized_pnl:.2f}). Zero banked. Remaining deficit £{max(0.0, self.reference_base_capital - new_active_equity):.2f}."
            else:
                # Normal mode: All net profit is bankable
                banked_amount = round(net_realized_pnl, 2)
                new_active_equity = self.reference_base_capital
                notes = f"Normal mode net profit banked (£{banked_amount:+.2f}). Non-deployable."

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
        Executes explicit user-approved capital transfer from Banked Reserve into Active Trading Equity.
        CRITICAL: Never recorded as trading profit or P&L!
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

        # Record into capital_transfers ledger (ISOLATED FROM TRADING P&L)
        db.record_capital_transfer(
            transfer_id=transfer_id,
            source="BANKED_PROFIT_RESERVE",
            destination="ACTIVE_TRADING_EQUITY",
            amount=transfer_amount,
            approved_by=user_name,
            active_equity_before=active_equity,
            active_equity_after=new_active,
            vault_before=banked_reserve,
            vault_after=new_vault,
            notes=f"User approved top-up to restore active capital toward £50,000 base."
        )

        # Record state transition
        new_deficit = max(0.0, self.reference_base_capital - new_active)
        new_state = CapitalState.NORMAL if new_deficit == 0 else CapitalState.RECOVERY
        db.record_state_transition(
            previous_state=CapitalState.USER_TOPUP_PENDING.value,
            new_state=new_state.value,
            active_equity=new_active,
            deficit=new_deficit,
            vault_balance=new_vault,
            trigger_reason=f"User approved capital transfer of £{transfer_amount:.2f}."
        )

        self._current_state = new_state
        return {
            "success": True,
            "transfer_id": transfer_id,
            "amount_gbp": transfer_amount,
            "active_equity_before_gbp": active_equity,
            "active_equity_after_gbp": new_active,
            "banked_reserve_before_gbp": banked_reserve,
            "banked_reserve_after_gbp": new_vault,
            "new_state": new_state.value,
            "is_trading_pnl": False,
            "message": f"Successfully transferred £{transfer_amount:.2f} from Banked Reserve to Active Trading Equity."
        }

    def decline_topup(self, user_name: str = "PORTFOLIO_MANAGER") -> Dict[str, Any]:
        """
        User explicitly declines to use banked reserves.
        The system remains in RECOVERY mode and continues operating from the reduced active equity.
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
            trigger_reason="User declined banked reserve top-up. Operating patient recovery from remaining equity."
        )
        self._current_state = new_state
        return {
            "success": True,
            "message": "Top-up declined. System remains in RECOVERY mode trading remaining active equity.",
            "new_state": new_state.value,
            "active_trading_equity_gbp": snap["active_trading_equity_gbp"],
            "base_capital_deficit_gbp": snap["base_capital_deficit_gbp"]
        }

    def get_current_active_state(self) -> Dict[str, Any]:
        """Convenience method fetching authoritative snapshot and returning state machine output."""
        from src.portfolio.portfolio_snapshot import portfolio_snapshot
        snap = portfolio_snapshot.get_authoritative_snapshot()
        nav = snap["account_summary"]["total_nav"]
        
        # Realized today and unrealized today from snapshot / trades
        all_trades = db.get_trades(limit=500)
        today_str = self.get_today_str()
        today_realized = sum(
            float(t.get("realized_pnl", 0.0))
            for t in all_trades
            if str(t.get("timestamp", "")).startswith(today_str) and str(t.get("action", "")).upper() == "SELL"
        )
        today_unrealized = snap["account_summary"].get("total_unrealized_pnl_gbp", 0.0)

        # Check market stress conditions
        from src.risk.market_stress_detector import market_stress_detector
        stress_active, stress_reason, _ = market_stress_detector.evaluate_market_stress()

        return self.evaluate_capital_state(
            current_broker_nav=nav,
            daily_realized_pnl=today_realized,
            daily_unrealized_pnl=today_unrealized,
            market_stress_active=stress_active,
            market_stress_reason=stress_reason
        )


capital_state_machine = CapitalStateMachine()
