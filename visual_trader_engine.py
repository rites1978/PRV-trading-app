import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from db_manager import db
from risk_engine import RiskEngine
from portfolio_guard import PortfolioGuard

load_dotenv()

API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")
BASE_URL = "https://demo.trading212.com/api/v0/equity"  # Change to live URL when ready

class VisualTraderEngine:
    def __init__(self):
        self.auth = HTTPBasicAuth(API_KEY, API_SECRET)
        self.risk_engine = RiskEngine(portfolio_nav=40000.0)
        self.portfolio_guard = PortfolioGuard()

    def get_portfolio(self):
        try:
            res = requests.get(f"{BASE_URL}/portfolio", auth=self.auth, timeout=5)
            if res.status_code == 200:
                import pandas as pd
                data = res.json()
                return pd.DataFrame(data) if data else pd.DataFrame(columns=['ticker', 'quantity', 'currentValue'])
        except Exception as e:
            print(f"⚠️ Failed to fetch broker portfolio: {e}")
        return pd.DataFrame(columns=['ticker', 'quantity', 'currentValue'])

    def execute_market_order(self, yf_ticker, t212_ticker, boardroom_decision_id):
        print(f"⚡ Visual Trader: Evaluating execution sequence for {yf_ticker} ({t212_ticker})...")
        
        # 1. Risk Sizing
        risk_metrics = self.risk_engine.calculate_position(yf_ticker)
        quantity = risk_metrics['quantity']
        stop_loss = risk_metrics['stop_loss_price']
        
        if quantity <= 0:
            print(f"⛔ Execution Halted: Calculated quantity too low for {yf_ticker}.")
            return False

        # 2. Portfolio Guard Check
        active_positions = self.get_portfolio()
        is_safe = self.portfolio_guard.check_correlation_and_concentration(
            proposed_ticker=yf_ticker,
            active_positions_df=active_positions,
            nav=40000.0
        )

        if not is_safe:
            print(f"🛡️ Execution Blocked by Portfolio Guard for {yf_ticker}.")
            return False

        # 3. Fire Order to Trading 212 API
        payload = {
            "ticker": t212_ticker,
            "quantity": quantity,
            "target": None
        }

        print(f"🚀 Dispatching market buy order to Trading 212: {quantity} shares of {t212_ticker}")
        try:
            res = requests.post(f"{BASE_URL}/orders/market", auth=self.auth, json=payload, timeout=10)
            
            if res.status_code in [200, 201]:
                order_data = res.json()
                fill_price = order_data.get('filledValue', 0) / max(quantity, 0.001)
                
                print(f"✅ Order Executed Successfully! Fill Price: ~{fill_price}")
                
                # 4. Commit to Supabase Execution Journal
                db.log_trade(
                    ticker=yf_ticker,
                    action="BUY",
                    price=fill_price if fill_price > 0 else 100.0,
                    quantity=quantity,
                    stop_loss=stop_loss,
                    debate_id=boardroom_decision_id
                )
                return True
            else:
                print(f"❌ Broker API Rejected Order: {res.status_code} - {res.text}")
                return False
                
        except Exception as e:
            print(f"❌ Critical Execution Error: {e}")
            return False

if __name__ == "__main__":
    trader = VisualTraderEngine()
    print("Visual Trader Engine initialized and linked to Trading 212 & Supabase.")
    from alert_system import AlertSystem

# Inside execute_market_order, upon successful fill:
alert = AlertSystem()
alert.send_trade_alert(
    ticker=yf_ticker,
    action="BUY",
    quantity=quantity,
    price=fill_price,
    stop_loss=stop_loss
)