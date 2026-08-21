from typing import Dict, Any, Tuple

class RiskManager:
    def __init__(
        self,
        min_portfolio_threshold: float = 40000.0,
        max_trade_amount: float = 500.0,
        max_open_positions: int = 5,
        default_stop_loss_pct: float = 0.03,  # 3% Stop Loss
        default_take_profit_pct: float = 0.06 # 6% Take Profit
    ):
        self.min_portfolio_threshold = min_portfolio_threshold
        self.max_trade_amount = max_trade_amount
        self.max_open_positions = max_open_positions
        self.default_stop_loss_pct = default_stop_loss_pct
        self.default_take_profit_pct = default_take_profit_pct

    def check_safeguards(self, total_value: float) -> Tuple[bool, str]:
        """Check the global kill switch / drawdown limit."""
        if total_value < self.min_portfolio_threshold:
            return False, f"⚠️ EMERGENCY KILL SWITCH: Portfolio £{total_value:.2f} is below limit of £{self.min_portfolio_threshold:.2f}."
        return True, "🟢 Account value is above safe drawdown limit."

    def validate_buy_order(
        self,
        total_value: float,
        available_cash: float,
        current_open_positions: int,
        estimated_cost: float,
        ticker: str,
        already_holding: bool
    ) -> Tuple[bool, str]:
        """Validate if a buy order satisfies risk and position limits."""
        # 1. Kill switch check
        safe, msg = self.check_safeguards(total_value)
        if not safe:
            return False, msg

        # 2. Already holding ticker
        if already_holding:
            return False, f"Hold position: Already have an open position in {ticker}."

        # 3. Open positions limit
        if current_open_positions >= self.max_open_positions:
            return False, f"Risk limit: Max concurrent positions ({self.max_open_positions}) reached."

        # 4. Cash check
        if estimated_cost > available_cash:
            return False, f"Insufficient cash: Required £{estimated_cost:.2f}, Available £{available_cash:.2f}."

        # 5. Max trade allocation
        if estimated_cost > self.max_trade_amount:
            return False, f"Trade cost £{estimated_cost:.2f} exceeds max trade allocation of £{self.max_trade_amount:.2f}."

        return True, "Risk validation passed."

    def calculate_quantity(self, stock_price: float, available_cash: float) -> float:
        """
        Calculate optimal order quantity based on stock price and risk budget.
        """
        if stock_price <= 0:
            return 0

        target_spend = min(self.max_trade_amount, available_cash * 0.95)
        if target_spend < stock_price:
            # Check fractional or min 1 share if budget allows
            return 1 if target_spend >= stock_price * 0.5 else 0

        # Calculate shares (rounded to integer or 2 decimal places)
        quantity = target_spend / stock_price
        if quantity >= 1:
            return round(quantity, 2)
        return round(quantity, 4)

    def evaluate_position_exit(
        self,
        average_price: float,
        current_price: float,
        stop_loss_pct: float = None,
        take_profit_pct: float = None
    ) -> Tuple[bool, str, float]:
        """
        Evaluate if an open position should be closed due to Stop Loss or Take Profit.
        """
        if average_price <= 0:
            return False, "Invalid entry price", 0.0

        sl = stop_loss_pct if stop_loss_pct is not None else self.default_stop_loss_pct
        tp = take_profit_pct if take_profit_pct is not None else self.default_take_profit_pct

        pnl_pct = (current_price - average_price) / average_price

        # Check Stop Loss
        if pnl_pct <= -sl:
            return True, f"🛑 Stop Loss Triggered: Loss is {pnl_pct * 100:.2f}% (Limit: -{sl * 100:.1f}%)", pnl_pct

        # Check Take Profit
        if pnl_pct >= tp:
            return True, f"🎯 Take Profit Triggered: Gain is +{pnl_pct * 100:.2f}% (Target: +{tp * 100:.1f}%)", pnl_pct

        return False, f"Holding: PnL is {pnl_pct * 100:+.2f}%", pnl_pct
