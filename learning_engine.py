from db_manager import db

class LearningEngine:
    def __init__(self):
        self.db = db

    def generate_post_mortem(self):
        # Fetch closed trades
        trades = self.db.client.table("execution_journal").select("*, boardroom_debates(*)").not_.is_("realized_pnl", "null").execute()
        
        for trade in trades.data:
            pnl = trade['realized_pnl']
            # If trade was a significant loss
            if pnl < -5.0:  # Threshold for post-mortem
                self._analyze_failure(trade)

    def _analyze_failure(self, trade):
        # Logic: If PNL is bad, lower the weight of the Sentiment agent 
        # because the debate showed it had a high conviction score.
        debate = trade['boardroom_debates']
        if debate['conviction_score'] > 7.0 and debate['sentiment_analysis']['score'] > 7.0:
            print(f"⚠️ Learning: Over-reliance on Sentiment for {trade['asset_ticker']}. Adjusting weights.")
            # SQL logic to update agent_weights table...
            self.db.client.table("agent_weights").update({"weight": 0.9}).eq("agent_name", "Sentiment").execute()

learning = LearningEngine()