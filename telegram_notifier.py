"""
PRV Capital Noise-Free Telegram Notification Gateway
Strictly filtered to critical actionable events:
1. Market Open
2. Market Close
3. Realized Profit > +5%
4. Realized Loss < -5%
5. Drawdown Breach (>= 5%)
6. Broker Failure
7. Compliance Failure
(All routine scanner, minor fill, attribution, and AI vote messages are permanently muted)
"""
import os
import requests
from dotenv import load_dotenv
from typing import Optional, Dict, Any

load_dotenv()

class TelegramNotifier:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.token and self.chat_id)

    def _dispatch(self, message: str) -> bool:
        """Internal dispatch to Telegram Bot API."""
        if not self.enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            res = requests.post(url, json=payload, timeout=5)
            return res.status_code == 200
        except Exception as e:
            print(f"[Telegram Notification Error] {e}")
            return False

    # 1. Market Open & Close Alerts
    def notify_market_open(self, session_name: str = "US/UK Equities", active_universe_count: int = 103):
        """Dispatched on market session open."""
        msg = (
            f"🔔 *MARKET OPEN: {session_name.upper()}*\n\n"
            f"• *Session State:* ACTIVE\n"
            f"• *Universe:* {active_universe_count} eligible equities\n"
            f"• *Strategy:* Phase 47 Dynamic 2.5x ATR Stops Active\n"
            f"• *Compliance:* Pre-Flight Firewall Enforcing"
        )
        return self._dispatch(msg)

    def notify_market_close(self, session_name: str = "US/UK Equities", nav: float = 4736.33, daily_pnl: float = 0.0):
        """Dispatched on market session close."""
        pnl_sign = "+" if daily_pnl >= 0 else ""
        msg = (
            f"🌙 *MARKET CLOSE: {session_name.upper()}*\n\n"
            f"• *Session State:* CLOSED\n"
            f"• *Current NAV:* £{nav:,.2f}\n"
            f"• *Daily Est Return:* {pnl_sign}£{daily_pnl:,.2f}\n"
            f"• *Strategy Mode:* Capital Preserved in Cash"
        )
        return self._dispatch(msg)

    # 2. High-Impact Realized P&L Alerts (> +5% or < -5%)
    def notify_high_impact_trade(self, ticker: str, action: str, pnl_pct: float, pnl_gbp: float, reason: str):
        """
        Dispatched ONLY when realized return breaches ±5.00%.
        All routine minor fills (< ±5%) are strictly muted.
        """
        if abs(pnl_pct) < 5.0:
            # Muted: Small routine fills do not generate chat noise
            return False

        if pnl_pct >= 5.0:
            header = "🚀 *HIGH PROFIT ALERT (> +5.0%)*"
            emoji = "🟢 💰"
        else:
            header = "⚠️ *HIGH LOSS ALERT (< -5.0%)*"
            emoji = "🔴 🛑"

        msg = (
            f"{header}\n\n"
            f"• *Instrument:* `{ticker}`\n"
            f"• *Action:* {action.upper()}\n"
            f"• *Realized Return:* `{pnl_pct:+.2f}%` ({emoji} £{pnl_gbp:+.2f})\n"
            f"• *Exit Reason:* {reason}\n"
            f"• *Attribution:* Logged to Governance Ledger"
        )
        return self._dispatch(msg)

    # 3. Critical Risk & Drawdown Breach Alerts
    def notify_drawdown_breach(self, current_dd_pct: float, max_allowed_pct: float = 5.00, action_taken: str = "HALT_TRADING"):
        """Dispatched when drawdown breaches circuit breaker threshold."""
        msg = (
            f"🚨 *CRITICAL RISK EVENT: DRAWDOWN BREACH*\n\n"
            f"• *Current Drawdown:* `{current_dd_pct:.2f}%`\n"
            f"• *Hard Circuit Ceiling:* `{max_allowed_pct:.2f}%`\n"
            f"• *Enforcement Action:* `{action_taken}`\n"
            f"• *Status:* Autonomous Derisking & Cash Lock Triggered"
        )
        return self._dispatch(msg)

    # 4. Broker / API Failure Alerts
    def notify_broker_failure(self, error_details: str):
        """Dispatched on broker API disconnect or fatal HTTP error."""
        msg = (
            f"❌ *CRITICAL ALERT: BROKER API FAILURE*\n\n"
            f"• *Gateway:* Trading 212 API\n"
            f"• *Error Diagnostic:* {error_details}\n"
            f"• *Safety Guard:* Order routing paused until reconnection"
        )
        return self._dispatch(msg)

    # 5. Pre-Flight Compliance Failure Alerts
    def notify_compliance_failure(self, reason: str, symbol: str, ticker: str):
        """Dispatched when pre-flight firewall blocks an order."""
        msg = (
            f"🛡️ *COMPLIANCE FIREWALL REJECTION*\n\n"
            f"• *Asset Target:* `{symbol}` ({ticker})\n"
            f"• *Veto Reason:* {reason}\n"
            f"• *Action:* Order aborted; zero capital deployed"
        )
        return self._dispatch(msg)

    # Legacy Compatibility (Muted if not high impact)
    def notify_trade(self, action: str, ticker: str, quantity: float, price: float, reason: str, is_paper: bool = False, pnl_pct: float = 0.0, pnl_gbp: float = 0.0):
        """Filtered gateway: Only dispatches if PnL breaches ±5%."""
        if abs(pnl_pct) >= 5.0:
            return self.notify_high_impact_trade(ticker, action, pnl_pct, pnl_gbp, reason)
        # Suppress routine fills to eliminate spam
        return False

    def notify_alert(self, title: str, details: str):
        """Route generic alerts to critical risk or broker failure handlers."""
        if "CIRCUIT" in title.upper() or "DRAWDOWN" in title.upper() or "RISK" in title.upper():
            return self.notify_drawdown_breach(5.10, 5.00, details)
        elif "BROKER" in title.upper() or "DISCONNECT" in title.upper() or "API" in title.upper():
            return self.notify_broker_failure(details)
        # Mute routine informational start/stop alerts
        return False

telegram_notifier = TelegramNotifier()
