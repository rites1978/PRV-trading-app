import os
import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
from dotenv import load_dotenv
from db_manager import db
from risk_engine import RiskEngine
from alert_system import AlertSystem

load_dotenv()

API_KEY = os.getenv("TRADING212_API_KEY")
API_SECRET = os.getenv("TRADING212_API_SECRET")
BASE_URL = "https://demo.trading212.com/api/v0/equity"

class PortfolioRebalancer:
    def __init__(self):
        self.auth = HTTPBasicAuth(API_KEY, API_SECRET)
        self.risk_engine = RiskEngine(portfolio_nav=40000.0)
        self.alert = AlertSystem()

    def audit_portfolio(self):
        print("🔍 Portfolio Rebalancer: Running risk audit on active positions...")
        
        try:
            res = requests.get(f"{BASE_URL}/portfolio", auth=self.auth, timeout=5)
            if res.status_code != 200 or not res.json():
                print("ℹ️ No active positions found to audit. Portfolio is 100% liquid in cash.")
                return

            positions = res.json()
            total_portfolio_value = 40000.0  # Baseline NAV
            
            for pos in positions:
                ticker = pos.get('ticker')
                quantity = pos.get('quantity', 0)
                avg_price = pos.get('averagePrice', 0)
                current_price = pos.get('currentPrice', 0)
                ppl = pos.get('ppl', 0)
                
                # Calculate return percentage
                return_pct = ((current_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
                
                print(f"📊 Auditing {ticker}: Qty: {quantity} | PnL: £{ppl:,.2f} ({return_pct:.2f}%)")

                # Example Risk Rule: If any position drops more than 7%, trigger warning alert
                if return_pct <= -7.0:
                    warning_msg = f"⚠️ **RISK WARNING: DRAWDOWN THRESHOLD BREACH**\n\nAsset `{ticker}` is down {return_pct:.2f}% (PnL: £{ppl:,.2f}). Review stop-loss parameters."
                    print(warning_msg)
                    self.alert._dispatch(warning_msg)

            # Update macro risk telemetry in Supabase
            db.client.table("risk_telemetry").insert({
                "total_nav": total_portfolio_value,
                "free_cash": total_portfolio_value, # Simplified assumption if fully cash/rebalanced
                "current_drawdown_pct": 0.0,
                "portfolio_var_95": total_portfolio_value * 0.025  # 2.5% daily VaR estimate
            }).execute()
            
            print("✅ Portfolio risk audit completed and logged to Supabase.")

        except Exception as e:
            print(f"❌ Error during portfolio audit execution: {e}")

if __name__ == "__main__":
    rebalancer = PortfolioRebalancer()
    rebalancer.audit_portfolio()