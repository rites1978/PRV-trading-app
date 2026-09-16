"""
PRV Capital - Hit-and-Run Realised-Net Daily Banking Ledger
Authoritative tracking of daily profit banking:
1. Base target = £100 REALISED NET profit after all trading costs.
2. Net realised profit is BANKED when closed.
3. Unrealised gains NEVER count toward the £100 target or banked profit.
4. DO NOT stop trading merely because £100 has been reached; continue hunting valid opportunities.
5. Accurately tracks:
   - gross_realised_pnl
   - estimated/actual costs
   - net_realised_pnl
   - banked_net_profit_today
   - remaining_to_base_target
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("hit_and_run.banking")


class DailyBankingLedger:
    """
    Manages daily profit banking, cost reconciliation, and performance against the £100 base target.
    """

    def __init__(self, trading_date: Optional[str] = None, base_target_gbp: float = 100.0):
        self.trading_date = trading_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.base_target_gbp = float(base_target_gbp)
        self.closed_trades: List[Dict[str, Any]] = []

    def record_realised_trade(
        self,
        trade_id: str,
        ticker: str,
        gross_pnl_gbp: float,
        costs_gbp: float,
        exit_reason: str = "PROFIT_CAPTURE",
        entry_price: float = 0.0,
        exit_price: float = 0.0,
        quantity: float = 0.0,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Records a completed trade into the realised daily banking ledger.
        """
        net_pnl = round(gross_pnl_gbp - costs_gbp, 2)
        record = {
            "trade_id": trade_id,
            "ticker": ticker,
            "gross_pnl_gbp": round(float(gross_pnl_gbp), 2),
            "costs_gbp": round(float(costs_gbp), 2),
            "net_pnl_gbp": net_pnl,
            "exit_reason": exit_reason,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat()
        }
        self.closed_trades.append(record)

        logger.info(
            f"BankingLedger: Recorded closed trade {trade_id} ({ticker}): "
            f"Gross £{gross_pnl_gbp:+.2f}, Costs £{costs_gbp:.2f}, Net £{net_pnl:+.2f} ({exit_reason})"
        )
        return record

    def get_banking_summary(self, unrealised_pnl_gbp: float = 0.0) -> Dict[str, Any]:
        """
        Returns authoritative banking status.
        Unrealised gains are reported for telemetry only and NEVER count toward banked profit.
        """
        gross_realised = round(sum(t["gross_pnl_gbp"] for t in self.closed_trades), 2)
        trading_costs = round(sum(t["costs_gbp"] for t in self.closed_trades), 2)
        net_realised = round(gross_realised - trading_costs, 2)

        # Banked net profit today is the positive realised net P&L
        banked_profit = max(0.0, net_realised)

        # Remaining to base target
        remaining = max(0.0, round(self.base_target_gbp - net_realised, 2))
        target_achieved = bool(net_realised >= self.base_target_gbp)

        # Mandatory: Never stop trading solely because target was reached
        continue_trading = True

        return {
            "trading_date": self.trading_date,
            "base_target_gbp": self.base_target_gbp,
            "gross_realised_pnl": gross_realised,
            "trading_costs": trading_costs,
            "net_realised_pnl": net_realised,
            "banked_net_profit_today": banked_profit,
            "remaining_to_base_target": remaining,
            "base_target_achieved": target_achieved,
            "continue_trading": continue_trading,
            "total_closed_trades": len(self.closed_trades),
            "unrealised_pnl_gbp": round(float(unrealised_pnl_gbp), 2),
            "recent_trades": list(self.closed_trades[-10:])
        }

    def reset_daily_ledger(self, new_trading_date: str) -> None:
        """Resets ledger for a new trading session."""
        self.trading_date = new_trading_date
        self.closed_trades = []
        logger.info(f"BankingLedger: Reset for new trading date {new_trading_date}")


daily_banking_ledger = DailyBankingLedger()
