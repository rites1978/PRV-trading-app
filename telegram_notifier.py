import os
import requests
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

class TelegramNotifier:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.token and self.chat_id)

    def send_message(self, message: str) -> bool:
        """Send a formatted text message to Telegram."""
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
            print(f"[Telegram Error] {e}")
            return False

    def notify_trade(self, action: str, ticker: str, quantity: float, price: float, reason: str, is_paper: bool = False):
        """Notify of a trade execution."""
        badge = "🧪 [PAPER TRADE]" if is_paper else "⚡ [LIVE TRADE]"
        emoji = "🟢 🛒" if action.upper() == "BUY" else "🔴 💰"
        text = (
            f"{emoji} *{badge} {action.upper()} EXECUTED*\n\n"
            f"• *Ticker:* `{ticker}`\n"
            f"• *Quantity:* `{quantity}`\n"
            f"• *Price:* `{price}`\n"
            f"• *Reason:* {reason}\n"
        )
        return self.send_message(text)

    def notify_alert(self, title: str, details: str):
        """Notify of a system warning, safeguard trigger, or error."""
        text = f"🚨 *SYSTEM ALERT: {title}*\n\n{details}"
        return self.send_message(text)
