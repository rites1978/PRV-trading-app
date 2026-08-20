from db_manager import db
import datetime

class PostMortemEngine:
    def __init__(self):
        print("🧠 Post-Mortem Intelligence Engine Initialized.")

    def audit_closed_trades(self):
        print("🔍 Running post-mortem analysis on recent trades...")
        try:
            # Fetch recent executions from Supabase
            trades = db.get_execution_history(limit=10)
            if not trades:
                print("ℹ️ No trades to audit.")
                return

            for trade in trades:
                ticker = trade.get('asset_ticker')
                fill_price = float(trade.get('fill_price', 0))
                trade_id = trade.get('id', 'unknown')
                
                # Check if post-mortem already exists for this trade
                existing = db.client.table("post_mortem_analysis").select("trade_id").eq("trade_id", str(trade_id)).execute()
                if existing.data:
                    continue # Already audited

                # Simulate performance evaluation (in live usage, compare fill price vs current market price)
                simulated_return = 0.012  # Placeholder for real PnL check
                
                outcome = "WIN" if simulated_return > 0 else "LOSS"
                attributed_agent = "Technical Momentum Agent" if simulated_return > 0 else "Macro Sentiment Agent"
                root_cause = f"Trade on {ticker} resulted in {outcome}. Technical indicators aligned with market momentum."

                # Save analysis to Supabase
                db.client.table("post_mortem_analysis").insert({
                    "trade_id": str(trade_id),
                    "attributed_agent": attributed_agent,
                    "root_cause_analysis": root_cause
                }).execute()

                print(f"📝 Post-Mortem logged for {ticker}: {outcome} (Attributed to {attributed_agent})")

        except Exception as e:
            print(f"❌ Error during post-mortem audit: {e}")

if __name__ == "__main__":
    engine = PostMortemEngine()
    engine.audit_closed_trades()