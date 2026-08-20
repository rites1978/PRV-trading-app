import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

class DatabaseManager:
    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("Supabase credentials missing from environment.")
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def log_market_regime(self, classification: str, vix: float, momentum: float, constraint: str):
        data = {
            "classification": classification,
            "vix_level": vix,
            "sector_momentum_score": momentum,
            "active_constraint": constraint
        }
        return self.client.table("market_regimes").insert(data).execute()

    def log_debate(self, ticker: str, tech_report: dict, sent_report: dict, veto: bool, consensus: str, conviction: float):
        data = {
            "asset_ticker": ticker,
            "technical_analysis": tech_report,
            "sentiment_analysis": sent_report,
            "risk_veto": veto,
            "final_consensus": consensus,
            "conviction_score": conviction
        }
        response = self.client.table("boardroom_debates").insert(data).execute()
        return response.data[0]["debate_id"] if response.data else None

    def log_trade(self, ticker: str, action: str, price: float, quantity: float, stop_loss: float = None, debate_id: str = None):
        data = {
            "debate_id": debate_id,
            "asset_ticker": ticker,
            "action": action,
            "fill_price": price,
            "quantity": quantity,
            "dynamic_stop_loss": stop_loss
        }
        return self.client.table("execution_journal").insert(data).execute()

    def log_telemetry(self, nav: float, free_cash: float, var_95: float = 0.0, drawdown: float = 0.0):
        data = {
            "total_nav": nav,
            "free_cash": free_cash,
            "portfolio_var_95": var_95,
            "current_drawdown_pct": drawdown
        }
        return self.client.table("risk_telemetry").insert(data).execute()

    # Query methods for Streamlit
    def get_latest_telemetry(self):
        res = self.client.table("risk_telemetry").select("*").order("timestamp", desc=True).limit(1).execute()
        return res.data[0] if res.data else None

    def get_recent_debates(self, limit=10):
        res = self.client.table("boardroom_debates").select("*").order("timestamp", desc=True).limit(limit).execute()
        return res.data if res.data else []

    def get_execution_history(self, limit=20):
        res = self.client.table("execution_journal").select("*").order("timestamp", desc=True).limit(limit).execute()
        return res.data if res.data else []

db = DatabaseManager()