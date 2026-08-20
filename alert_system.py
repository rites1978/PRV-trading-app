import os
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class AlertSystem:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID

    def send_trade_alert(self, ticker, action, quantity, price, stop_loss):
        message = (
            f"🚨 **PRV CAPITAL TRADE EXECUTION** 🚨\n\n"
            f"• **Asset:** {ticker}\n"
            f"• **Action:** {action}\n"
            f"• **Quantity:** {quantity}\n"
            f"• **Fill Price:** £{price:,.2f}\n"
            f"• **Stop-Loss:** £{stop_loss:,.2f}\n\n"
            f"*(Processed via Autonomous AI Boardroom & Visual Trader)*"
        )
        self._dispatch(message)

    def send_boardroom_summary(self, ticker, consensus, conviction, rationale):
        message = (
            f"🏛️ **AI BOARDROOM DELIBERATION**\n\n"
            f"• **Target:** {ticker}\n"
            f"• **Consensus:** {consensus}\n"
            f"• **Conviction Score:** {conviction}/10\n"
            f"• **Rationale:** {rationale}"
        )
        self._dispatch(message)

    def _dispatch(self, message):
        if not self.token or not self.chat_id:
            print(f"🔕 Alert skipped (Telegram credentials not configured): {message}")
            return
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            res = requests.post(url, json=payload, timeout=5)
            if res.status_code != 200:
                print(f"⚠️ Failed to send Telegram alert: {res.text}")
        except Exception as e:
            print(f"❌ Telegram notification error: {e}")

if __name__ == "__main__":
    alert = AlertSystem()
    print("Alert System initialized.")