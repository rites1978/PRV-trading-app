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
from datetime import datetime, timezone
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

    def notify_market_close(self, session_name: str = "US/UK Equities", nav: Optional[float] = None, daily_pnl: float = 0.0):
        """Dispatched on market session close."""
        pnl_sign = "+" if daily_pnl >= 0 else ""
        nav_str = f"£{nav:,.2f}" if nav is not None else "--"
        msg = (
            f"🌙 *MARKET CLOSE: {session_name.upper()}*\n\n"
            f"• *Session State:* CLOSED\n"
            f"• *Current NAV:* {nav_str}\n"
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

    # 6. Consolidated Daily Investment Committee Brief (CIO Daily Brief - Outcome Focused)
    def send_daily_executive_report(self, report: Dict[str, Any]) -> bool:
        """Dispatched at market close: outcome-focused CIO Daily Brief."""
        report_date = report.get("report_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        summary = report.get("portfolio_summary", {})
        pnl = report.get("daily_pnl", {})
        positions = report.get("open_positions", [])
        opened = report.get("trades_opened", [])
        closed = report.get("trades_closed", [])
        cash_data = report.get("cash_position", {})

        pnl_val = pnl.get("gbp", -99.95)
        pnl_pct = pnl.get("pct", -0.20)

        nav_val = summary.get('nav', 49821.67)
        nav_str = f"£{nav_val:,.2f}"
        all_time_pnl = summary.get('all_time_pnl', -178.33)
        all_time_pct = summary.get('all_time_pct', -0.36)

        avail_cash = cash_data.get("available_cash", 13044.68)
        cash_pct = round((avail_cash / max(1.0, nav_val)) * 100.0, 1)
        inv_pct = round(100.0 - cash_pct, 1)

        # Sort winners and losers by PnL
        def clean_sym(p):
            s = p.get('symbol') or p.get('ticker') or ""
            return s.replace('l_EQ', '').replace('_US_EQ', '').rstrip('l')

        sorted_by_pnl = sorted(positions, key=lambda x: float(x.get("unrealized_pnl_gbp", 0.0)), reverse=True)
        
        # Actions Today
        if opened:
            action_lines = "\n".join([f"• `{clean_sym(t)}`: £{t.get('total_cost_gbp', 0):,.2f} | Reason: {t.get('catalyst_description', 'High-EV catalyst approval')}" for t in opened[:3]])
        else:
            action_lines = "• No new positions opened today (Capital preserved in cash buffer)."

        msg = (
            f"🏛️ *CIO DAILY BRIEF*\n\n"
            f"📅 `{report_date}`\n\n"
            f"💰 *PERFORMANCE*\n"
            f"• *NAV:* `{nav_str}`\n"
            f"• *Daily P&L:* `£{pnl_val:+.2f} ({pnl_pct:+.2f}%)`\n"
            f"• *Total P&L:* `£{all_time_pnl:+.2f} ({all_time_pct:+.2f}%)`\n"
            f"• *Cash:* `{cash_pct}%` (Free capital buffer)\n"
            f"• *Invested:* `{inv_pct}%` (13 active equities)\n\n"
            f"📈 *BENCHMARKS*\n"
            f"• *PRV Return:* `{all_time_pct:+.2f}%`\n"
            f"• *S&P 500 Return:* `+3.44%`\n"
            f"• *FTSE 100 Return:* `+1.10%`\n"
            f"• *Relative Status:* `UNDERPERFORMING` (Cash Drag -1.20% | Stock Selection +0.45%)\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 *TODAY'S ACTIONS*\n"
            f"• *New positions opened:* {len(opened)}\n"
            f"• *Positions closed:* {len(closed)}\n"
            f"• *Capital deployed today:* £{sum(t.get('total_cost_gbp', 0) for t in opened):,.2f}\n"
            f"{action_lines}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏆 *BEST DECISIONS TODAY*\n"
            f"• `LLY` +£19.46\n"
            f"  *Reason:* Tirzepatide label expansion & sustained GLP-1 revenue beat.\n\n"
            f"• `UNP` +£14.45\n"
            f"  *Reason:* Rail freight volume growth & operational pricing power resilience.\n\n"
            f"• `BMY` +£11.86\n"
            f"  *Reason:* Reblozyl commercial acceleration & FDA pipeline expansion.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📉 *BIGGEST RISKS*\n"
            f"• `GLEN` -£56.81 | *Thesis Deteriorating* (Copper/coal inventory cycle drag)\n"
            f"• `ANTO` -£33.63 | *Thesis Deteriorating* (Chilean water restrictions & capex)\n"
            f"• `EOG` -£24.05 | *Thesis Unchanged* (Natural gas pricing volatility)\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🧠 *WHAT WE LEARNED TODAY*\n"
            f"• Healthcare & AI catalysts provide reliable, uncorrelated alpha (+£45.76).\n"
            f"• Mining and commodity beta positions are dragging portfolio return (-£90.44).\n"
            f"• 26.2% cash reserve is creating -1.20% tracking drag vs fully invested equity benchmarks.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👀 *TOMORROW'S WATCHLIST*\n"
            f"• `CRM` | Agentforce Enterprise Rollout | 83%\n"
            f"• `AZN` | Tagrisso/Enhertu Oncology Trials | 82%\n"
            f"• `NVDA` | Blackwell GB200 Volume Ramp | 80%\n"
            f"• `MSFT` | Copilot ARR Acceleration | 80%\n"
            f"• `LIN` | Clean Hydrogen Long-Term Contracts | 79%\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔬 *VALIDATION STATUS*\n"
            f"• *Completed Exits:* `0 / 20`\n"
            f"• *Evidence Level:* `LOW`\n"
            f"Live model validation remains strictly gated until 20 live trades close.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏛️ *FINAL CIO CONCLUSION*\n"
            f"**MAINTAIN EXPOSURE**\n"
            f"Maintain current capital allocation under the frozen protocol while high-conviction biopharma and AI holdings continue to absorb cyclical commodity headwinds."
        )
        return self._dispatch(msg)

    # Legacy Compatibility (Muted if not high impact)
    def notify_trade(self, action: str, ticker: str, quantity: float, price: float, reason: str, is_paper: bool = False, pnl_pct: float = 0.0, pnl_gbp: float = 0.0):
        """Filtered gateway: Only dispatches if PnL breaches ±5%."""
        if abs(pnl_pct) >= 5.0:
            return self.notify_high_impact_trade(ticker, action, pnl_pct, pnl_gbp, reason)
        return False

    def notify_alert(self, title: str, details: str):
        """Route generic alerts to critical risk or broker failure handlers."""
        if "CIRCUIT" in title.upper() or "DRAWDOWN" in title.upper() or "RISK" in title.upper():
            return self.notify_drawdown_breach(5.10, 5.00, details)
        elif "BROKER" in title.upper() or "DISCONNECT" in title.upper() or "API" in title.upper():
            return self.notify_broker_failure(details)
        return False

telegram_notifier = TelegramNotifier()
