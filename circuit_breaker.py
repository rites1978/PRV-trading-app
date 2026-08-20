import os
from alert_system import AlertSystem

class CircuitBreaker:
    def __init__(self, max_daily_drawdown_pct=0.025):
        self.max_drawdown = max_daily_drawdown_pct
        self.alert = AlertSystem()
        self.is_tripped = False

    def check_portfolio_health(self, starting_nav, current_nav):
        """
        Evaluates portfolio NAV drop. Trips circuit breaker if drawdown exceeds threshold.
        """
        if starting_nav <= 0:
            return False

        drawdown = (starting_nav - current_nav) / starting_nav
        
        if drawdown >= self.max_drawdown:
            self.is_tripped = True
            self.trigger_emergency_protocol(drawdown, starting_nav, current_nav)
            return True
            
        return False

    def trigger_emergency_protocol(self, drawdown_pct, start_nav, curr_nav):
        """
        Broadcasts emergency alert and halts trading engine.
        """
        message = (
            f"🚨 *CRITICAL: CIRCUIT BREAKER TRIGGERED* 🚨\n\n"
            f"• *Daily Drawdown:* {drawdown_pct * 100:.2f}%\n"
            f"• *Starting NAV:* £{start_nav:,.2f}\n"
            f"• *Current NAV:* £{curr_nav:,.2f}\n\n"
            f"🛑 *Action Taken:* Autonomous trading halted. Capital preserved. Manual override required via dashboard."
        )
        print(message)
        self.alert._dispatch(message)
        
        # Write panic state to environment / database flag
        os.environ["PRV_PANIC_MODE"] = "TRUE"